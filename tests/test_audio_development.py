import json

import numpy as np
import pytest
import soundfile as sf

from audio_development import analyze_development, tool_properties, TOOL_REQUIRED


def source(tmp_path, data):
    path = tmp_path / "programme.wav"
    sf.write(path, data, 8000, subtype="DOUBLE")
    return {"name": "programme", "path": str(path), "signal_path": "synthetic offline programme"}


def sections(duration=1):
    return [{"name": "a", "start_seconds": 0, "end_seconds": duration},
            {"name": "b", "start_seconds": duration, "end_seconds": 2 * duration}]


def tone(duration=1):
    return .1 * np.sin(2 * np.pi * 1000 * np.arange(round(duration * 8000)) / 8000)


def test_original_gain_contrast_and_intent_gate(tmp_path):
    args = {"source": source(tmp_path, np.r_[tone(), tone() * 2]), "sections": sections()}
    report = analyze_development(args)
    delta = report["measured_facts"]["adjacent_contrasts"][0]["deltas"]
    assert delta["rms_dbfs"] == pytest.approx(6.021, abs=.002)
    assert delta["crest_factor_db"] == pytest.approx(0, abs=.001)
    assert delta["effective_occupied_band_count"] == pytest.approx(0, abs=.001)
    assert report["expectation_departures"] == []
    assert report["perceptual_estimates"]["status"] == "unavailable"
    expectation = {"from_section": "a", "to_section": "b", "metric": "rms_dbfs", "expected_delta": 6.021, "tolerance": .01}
    with pytest.raises(ValueError, match="brief"):
        analyze_development({**args, "expected_contrasts": [expectation]})
    r = analyze_development({**args, "brief": {"description": "second section deliberately louder"}, "expected_contrasts": [expectation]})
    assert r["expectation_departures"][0]["status"] == "within_declared_expectation"
    r = analyze_development({**args, "brief": {"description": "equal levels"}, "expected_contrasts": [{**expectation, "expected_delta": 0}]})
    assert r["expectation_departures"][0]["status"] == "outside_declared_expectation"
    json.dumps(report, allow_nan=False)


def test_event_density_and_spectral_spread(tmp_path):
    data = np.zeros(32000)
    for start in [800, 8800, 16800, 20800, 24800, 28800]:
        data[start:start + 400] = tone(.05)
    r = analyze_development({"source": source(tmp_path, data), "sections": sections(2)})
    rows = r["measured_facts"]["sections"]
    assert rows[0]["temporal_density"]["reported_candidate_count"] == 2
    assert rows[1]["temporal_density"]["reported_candidate_count"] == 4
    assert rows[1]["metrics"]["onset_candidates_per_second"] == 2
    assert rows[0]["temporal_density"]["candidates"][0]["region_outcomes"]["tail"]["status"] in {"measured", "silent_or_below_numerical_floor"}
    noise = np.random.default_rng(12).normal(0, .1, 8000)
    r = analyze_development({"source": source(tmp_path, np.r_[tone(), noise]), "sections": sections()})
    assert r["measured_facts"]["adjacent_contrasts"][0]["deltas"]["effective_occupied_band_count"] > 1


def test_silence_short_sections_and_capped_density(tmp_path):
    r = analyze_development({"source": source(tmp_path, np.zeros(1600)), "sections": sections(.1)})
    assert r["measured_facts"]["sections"][0]["metrics"]["integrated_lufs"] is None
    assert r["measured_facts"]["sections"][0]["metrics"]["effective_occupied_band_count"] is None
    assert not r["coverage"]["spectrum_complete"]
    data = np.zeros(8000 * 16)
    for start in range(0, len(data) - 160, 800):
        data[start:start + 160] = tone(.02)
    r = analyze_development({"source": source(tmp_path, data), "sections": sections(8)})
    assert r["coverage"]["events"]["omitted_candidates"] > 0
    assert all(row["metrics"]["onset_candidates_per_second"] is None for row in r["measured_facts"]["sections"])
    assert sum(len(row["temporal_density"]["candidates"]) for row in r["measured_facts"]["sections"]) <= 120
    assert any(e["truncated"] for row in r["measured_facts"]["sections"] for e in row["temporal_density"]["candidates"])


def test_bounds_and_schema(tmp_path, monkeypatch):
    args = {"source": source(tmp_path, np.r_[tone(), tone()]), "sections": sections()}
    assert set(TOOL_REQUIRED) == {"source", "sections"}
    assert set(tool_properties()) == {"source", "sections", "brief", "expected_contrasts", "balance"}
    for update in [{"sections": sections()[::-1]}, {"sections": []}, {"unexpected": True},
                   {"sections": [{"name": "a", "start_seconds": 0, "end_seconds": True}, sections()[1]]}]:
        with pytest.raises(ValueError):
            analyze_development({**args, **update})
    monkeypatch.setattr("audio_development.MAX_WORK", 1)
    monkeypatch.setattr("audio_development.analyze_dynamics", lambda _: pytest.fail("decode occurred before budget gate"))
    with pytest.raises(ValueError, match="combined"):
        analyze_development(args)


def test_nested_balance_original_levels_and_time_gate(tmp_path):
    data = np.r_[tone(), tone() * 2]
    programme = source(tmp_path, data)
    part_path = tmp_path / "part.wav"
    sf.write(part_path, data, 8000, subtype="DOUBLE")
    balance = {"programme": {"name": "mix", "path": programme["path"]},
               "parts": [{"name": "part", "path": str(part_path)}],
               "alignment": {"verified": True, "source": "synthetic common clock", "uncertainty_samples": 0},
               "provenance": {"disjoint_contributions": True, "in_mix_levels": True, "signal_path": "single part equals unity programme"}}
    args = {"source": programme, "sections": sections(), "balance": balance}
    r = analyze_development(args)
    assert all(row["balance"][0]["relative_to_programme_lu"] == 0 for row in r["measured_facts"]["sections"])
    assert r["perceptual_estimates"]["provenance"] == balance["provenance"]
    with pytest.raises(ValueError, match="offset"):
        analyze_development({**args, "balance": {**balance, "alignment": {**balance["alignment"], "offsets_samples": {"mix": 1, "part": 0}}}})
    with pytest.raises(ValueError, match="provenance"):
        analyze_development({**args, "balance": {**balance, "provenance": {}}})
