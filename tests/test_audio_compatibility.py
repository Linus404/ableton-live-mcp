"""Numerical oracles use synthetic WAVs and equations, not production helpers."""
import json
import math

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

from audio_compatibility import analyze_compatibility, tool_properties, TOOL_REQUIRED


def tone(frequency=1000, duration=.4, amplitude=.1, rate=16000):
    return amplitude * np.sin(2 * np.pi * frequency * np.arange(round(duration * rate)) / rate)


def request(tmp_path, first=None, second=None, rate=16000):
    sources = []
    for i, data in enumerate([tone() if first is None else first, tone(1040) if second is None else second]):
        path = tmp_path / f"source{i}.wav"
        sf.write(path, data, rate, subtype="FLOAT")
        sources.append({"name": f"source{i}", "path": str(path), "signal_path": f"Disjoint post-mixer source{i}"})
    return {"target": sources[0], "competitors": sources[1:],
        "alignment": {"verified": True, "source": "Synthetic shared sample clock and render epoch", "uncertainty_samples": 0},
        "provenance": {"disjoint_contributions": True, "in_mix_levels": True, "signal_path": "Independent linear post-mixer contributions"}}


def first_pair(report):
    return report["measured_facts"]["windows"][0]["pairs"][0]


def roughness(report):
    return report["perceptual_estimates"]["windows"][0]["pairs"][0]["roughness"]


def test_independent_two_sine_roughness_oracle_and_frequency_relationship(tmp_path):
    report = analyze_compatibility(request(tmp_path))
    # Equal-amplitude resolved sinusoids yield equal retained amplitudes. Cross
    # amplitude product / summed squares = 1/2, independently of Hann scaling.
    distance = .24 * 40 / (.0207 * 1000 + 18.96)
    expected = .5 * (math.exp(-3.5 * distance) - math.exp(-5.75 * distance))
    assert roughness(report)["original"] == pytest.approx(expected, rel=.002)
    pair = first_pair(report)["partial_relationships"]["pairs"][0]
    assert pair["target_partial_hz"] == 1000
    assert pair["competitor_partial_hz"] == 1040
    assert pair["cents_from_ratio"] == pytest.approx(1200 * math.log2(1.04))
    assert pair["nearest_integer_ratio"] == [1, 1]
    assert pair["resolution_cents_interval"][0] < pair["cents_from_ratio"] < pair["resolution_cents_interval"][1]
    json.dumps(report, allow_nan=False)


def test_unison_octave_nearby_and_wide_partial_relationships(tmp_path):
    values = {}
    for frequency in (1000, 1040, 2000):
        report = analyze_compatibility(request(tmp_path, second=tone(frequency)))
        values[frequency] = roughness(report)["original"]
        if frequency == 2000:
            pair = first_pair(report)["partial_relationships"]["pairs"][0]
            assert pair["nearest_integer_ratio"] == [2, 1]
            assert abs(pair["cents_from_ratio"]) < .001
    assert values[1000] == pytest.approx(0, abs=1e-10)
    assert values[1040] > .05
    assert values[2000] < values[1040] / 1000


def test_direct_timing_separates_activity_and_retains_spectral_endpoint_impulse(tmp_path):
    first, second = tone(), tone()
    first[3200:] = 0
    second[:3200] = 0
    report = analyze_compatibility(request(tmp_path, first, second))
    windows = report["measured_facts"]["windows"]
    assert sum(w["pairs"][0]["timing"]["joint_active_seconds"] for w in windows) == 0
    assert sum(w["target_exposed_from_all_seconds"] for w in windows) == pytest.approx(.2)
    simultaneous = analyze_compatibility(request(tmp_path))
    assert first_pair(simultaneous)["timing"]["joint_active_seconds"] == pytest.approx(.1)
    impulse = np.zeros(6400)
    impulse[0] = .5
    report = analyze_compatibility(request(tmp_path, impulse, np.zeros_like(impulse)))
    assert first_pair(report)["timing"]["target_active_seconds"] == .01
    assert report["measured_facts"]["frequency_competition"]["windows"][0]["target_active"] is False
    assert first_pair(report)["partial_relationships"]["status"] == "unavailable"


def test_silence_antiphase_and_gain_original_evidence(tmp_path):
    first, second = tone(), tone(1040)
    mono = analyze_compatibility(request(tmp_path, first, second))
    stereo = analyze_compatibility(request(tmp_path, np.column_stack([first, -first]), np.column_stack([second, -second])))
    assert roughness(stereo)["original"] == pytest.approx(roughness(mono)["original"], rel=1e-6)
    args = request(tmp_path, first, second)
    args["competitors"][0]["gain_db"] = -20
    adjusted = analyze_compatibility(args)
    assert roughness(adjusted)["original"] == pytest.approx(roughness(mono)["original"])
    assert roughness(adjusted)["gain_scenario"] < roughness(adjusted)["original"] / 4
    assert first_pair(adjusted)["timing"] == first_pair(mono)["timing"]
    args["target"]["gain_db"] = -20
    uniform = analyze_compatibility(args)
    assert roughness(uniform)["gain_scenario"] == pytest.approx(roughness(mono)["original"])
    silent = analyze_compatibility(request(tmp_path, np.zeros_like(first), np.zeros_like(second)))
    assert roughness(silent)["original"] is None
    assert first_pair(silent)["partial_relationships"]["status"] == "unavailable"
    assert first_pair(silent)["timing"]["joint_active_seconds"] == 0


def test_offsets_tail_sections_brief_and_listening_estimate(tmp_path):
    first, second = tone(duration=.455), tone(1040, duration=.435)
    args = request(tmp_path, first, second)
    args["alignment"]["offsets_samples"] = {"source0": 320, "source1": 0}
    args["sections"] = [{"name": "opening", "start_seconds": .02, "end_seconds": .08}]
    args["brief"] = {"description": "Intentional nearby tone beating"}
    args["listening_condition"] = {"kind": "assumed", "db_spl_at_0_dbfs_rms": 90, "source": "Explicit hypothetical listening level"}
    report = analyze_compatibility(args)
    assert report["coverage"]["timing_duration_seconds"] == pytest.approx(.435)
    assert report["coverage"]["spectral_duration_seconds"] == pytest.approx(.4)
    assert report["coverage"]["unmeasured_spectral_tail_seconds"] == pytest.approx(.035)
    assert report["measured_facts"]["windows"][-1]["partial_final_cell_frames"] == 80
    assert report["measured_facts"]["windows"][0]["overlapping_sections"] == ["opening"]
    assert report["perceptual_estimates"]["target_prominence"]["status"] == "estimated"
    assert report["brief"] == args["brief"]
    assert report["distinguishability"]["status"] == "human_distinguishability_unavailable"


@pytest.mark.parametrize("alter,match", [
    (lambda a: a.update(unrequested=True), "unknown"),
    (lambda a: a["target"].pop("signal_path"), "signal_path"),
    (lambda a: a["alignment"].update(verified=False), "alignment"),
    (lambda a: a["alignment"].update(uncertainty_samples=True), "alignment"),
    (lambda a: a["alignment"].update(offsets_samples={"source0": 0}), "offsets_samples"),
    (lambda a: a["provenance"].update(disjoint_contributions=False), "overlapping"),
    (lambda a: a["provenance"].update(in_mix_levels=False), "pre-mixer"),
    (lambda a: a["competitors"][0].update(path=a["target"]["path"]), "reuse"),
    (lambda a: a["competitors"][0].update(name=a["target"]["name"]), "unique"),
    (lambda a: a["target"].update(gain_db=float("nan")), "finite"),
    (lambda a: a.update(window_seconds=.01), "window_seconds"),
    (lambda a: a.update(max_windows=1), "window budget"),
    (lambda a: a.update(brief={"description": ""}), "description"),
    (lambda a: a.update(sections=[{"name": "empty", "start_seconds": .01, "end_seconds": .010001}]), "sample interval"),
    (lambda a: a.update(sections=[{"name": "outside", "start_seconds": .1, "end_seconds": 1}]), "common interval"),
])
def test_contract_guards(tmp_path, alter, match):
    args = request(tmp_path)
    alter(args)
    with pytest.raises(ValueError, match=match):
        analyze_compatibility(args)


def test_nonfinite_layout_and_window_resource_guards(tmp_path):
    args = request(tmp_path)
    sf.write(args["competitors"][0]["path"], np.column_stack([tone(), tone()]), 16000, subtype="FLOAT")
    with pytest.raises(ValueError, match="channel layout"):
        analyze_compatibility(args)
    args = request(tmp_path)
    bad = tone()
    bad[5] = np.nan
    sf.write(args["target"]["path"], bad, 16000, subtype="FLOAT")
    with pytest.raises(ValueError, match="nonfinite"):
        analyze_compatibility(args)
    args = request(tmp_path, tone(duration=12.1), tone(duration=12.1))
    with pytest.raises(ValueError, match="window budget"):
        analyze_compatibility(args)


def test_peak_cap_and_schema(tmp_path):
    frequencies = np.arange(200, 1800, 100)
    data = sum(tone(float(f), amplitude=.005) for f in frequencies)
    report = analyze_compatibility(request(tmp_path, data, tone(1040)))
    spectra = report["measured_facts"]["windows"][0]["source_spectra"][0]
    assert len(spectra["partials"]) == 12
    assert spectra["extraction"]["omitted_candidates"] == 4
    assert first_pair(report)["partial_relationships"]["omitted_pair_count"] == 9
    assert set(TOOL_REQUIRED) <= set(tool_properties())
    assert tool_properties()["target"]["required"] == ["name", "path", "signal_path"]
    json.dumps(tool_properties(), allow_nan=False)


def test_sample_work_reserved_before_dsp_and_file_change_rejected(tmp_path, monkeypatch):
    import audio_compatibility
    args = request(tmp_path)
    real_validate = audio_compatibility.validate_wav
    real_masking = audio_compatibility.analyze_masking
    with monkeypatch.context() as patch:
        patch.setattr(audio_compatibility, "validate_wav", lambda path: {**real_validate(path), "frames": 10_000_000})
        patch.setattr(audio_compatibility, "analyze_masking", lambda args: pytest.fail("DSP ran before resource reservation"))
        with pytest.raises(ValueError, match="sample-work budget"):
            analyze_compatibility(args)
    def mutate_after_masking(values):
        report = real_masking(values)
        # Different size guarantees the stamp guard catches the changed source.
        sf.write(args["target"]["path"], tone(duration=.5), 16000, subtype="FLOAT")
        return report
    monkeypatch.setattr(audio_compatibility, "analyze_masking", mutate_after_masking)
    with pytest.raises(ValueError, match="changed"):
        analyze_compatibility(args)


def test_nonfinite_unmeasured_spectral_tail_is_rejected(tmp_path):
    data = tone(duration=.435)
    data[-1] = float("nan")
    with pytest.raises(ValueError, match="nonfinite"):
        analyze_compatibility(request(tmp_path, data, tone(duration=.435)))
