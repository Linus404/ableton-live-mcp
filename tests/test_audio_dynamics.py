import json

import numpy as np
import pytest
import soundfile as sf

from audio_dynamics import analyze_dynamics
from server import make_server


def wav(tmp_path, name, data, rate=8000):
    path = tmp_path / f"{name}.wav"
    sf.write(path, data, rate, subtype="DOUBLE")
    return {"name": name, "path": str(path), "signal_path": "controlled offline signal"}


def tone(seconds=1, rate=8000):
    return .1 * np.sin(2 * np.pi * 1000 * np.arange(round(seconds * rate)) / rate)


def aligned(source, comparison, **kwargs):
    return {"source": source, "comparison": comparison, "alignment": {
        "verified": True, "source": "synthetic exact common clock", "uncertainty_samples": 0}, **kwargs}


def event(start=0, end=.3):
    return {"name": "hit", "start_seconds": start, "attack_end_seconds": start + .02,
            "body_end_seconds": start + .1, "end_seconds": end}


def test_analytic_crest_stereo_pulse_dc_and_original_levels(tmp_path):
    data = tone()
    report = analyze_dynamics({"source": wav(tmp_path, "stereo", np.column_stack([data, -data]))})
    whole = report["source"]["whole_file"]
    assert whole["crest_factor_db"] == pytest.approx(3.0103, abs=.001)
    assert whole["crest_factor_by_channel_db"] == [whole["crest_factor_db"]] * 2
    assert whole["levels"]["rms_dbfs"] == pytest.approx(-23.0103, abs=.001)
    pulse = np.zeros(8000)
    pulse[::10] = .5
    r = analyze_dynamics({"source": wav(tmp_path, "pulse", pulse)})
    assert r["source"]["whole_file"]["crest_factor_db"] == pytest.approx(10, abs=.001)
    dc = analyze_dynamics({"source": wav(tmp_path, "dc", np.full(8000, 2.))})
    assert dc["source"]["whole_file"]["crest_factor_db"] == 0
    assert dc["source"]["whole_file"]["dc_offset_by_channel"] == [2.]
    assert dc["source"]["whole_file"]["levels"]["sample_peak_dbfs"] > 0
    json.dumps(report, allow_nan=False)


def test_explicit_event_energy_contrasts_and_gain_matching(tmp_path):
    data = tone()
    data[:160] *= 4
    data[800:2400] *= .5
    source = wav(tmp_path, "before", data)
    comparison = wav(tmp_path, "gain", data * 2)
    r = analyze_dynamics(aligned(source, comparison, events=[event()]))
    e = r["source"]["events"][0]
    assert e["attack_body_rms_db"] == pytest.approx(20 * np.log10(4), abs=.001)
    assert e["tail_body_rms_db"] == pytest.approx(20 * np.log10(.5), abs=.001)
    assert e["regions"]["attack"]["energy_sample_sum"] == pytest.approx(np.sum(data[:160] ** 2))
    assert e["regions"]["tail"]["energy_seconds"] == pytest.approx(np.sum(data[800:2400] ** 2) / 8000)
    paired = r["comparison_report"]
    assert paired["comparison_gain_to_source_lufs_db"] == pytest.approx(-6.021, abs=.001)
    assert paired["whole_file"]["crest_factor_delta_db"] == 0
    assert paired["events"][0]["attack_body_rms_db_delta"] == 0
    assert paired["whole_file"]["rms_dbfs"]["lufs_matched_delta"] == pytest.approx(0, abs=.002)
    assert paired["gain_applied_to_files"] is False


def test_known_limiter_reduces_crest_and_attack_contrast(tmp_path):
    data = tone()
    data[:160] *= 8
    clipped = np.clip(data, -.15, .15)
    r = analyze_dynamics(aligned(wav(tmp_path, "before", data), wav(tmp_path, "limited", clipped), events=[event()]))
    c = r["comparison_report"]
    expected = 20 * np.log10(np.max(np.abs(clipped)) / np.sqrt(np.mean(clipped ** 2))) - 20 * np.log10(np.max(np.abs(data)) / np.sqrt(np.mean(data ** 2)))
    assert c["whole_file"]["crest_factor_delta_db"] == pytest.approx(expected, abs=.002)
    assert c["events"][0]["attack_body_rms_db_delta"] < -10


def test_modulation_steady_carrier_and_processing_change(tmp_path):
    t = np.arange(64000) / 8000
    carrier = tone(8)
    # Exact log-amplitude modulation: independently known 3 dB amplitude at 2 Hz.
    changing = carrier * 10 ** ((3 * np.sin(2 * np.pi * 2 * t)) / 20)
    r = analyze_dynamics(aligned(wav(tmp_path, "steady", carrier), wav(tmp_path, "changing", changing)))
    assert r["source"]["modulation"]["status"] == "no_measurable_variation"
    m = r["comparison"]["modulation"]
    assert m["dominant_frequency_hz"] == pytest.approx(2, abs=.001)
    assert m["dominant_component_peak_amplitude_db"] == pytest.approx(3, abs=.02)
    p = r["comparison_report"]["level_change_modulation"]
    assert p["dominant_frequency_hz"] == pytest.approx(2, abs=.001)
    assert p["dominant_component_peak_amplitude_db"] == pytest.approx(3, abs=.02)
    pcm_a = wav(tmp_path, "pcm_before", carrier)
    pcm_b = wav(tmp_path, "pcm_gain", carrier * .5)
    sf.write(pcm_a["path"], carrier, 8000, subtype="PCM_24")
    sf.write(pcm_b["path"], carrier * .5, 8000, subtype="PCM_24")
    quantized = analyze_dynamics(aligned(pcm_a, pcm_b))["comparison_report"]["level_change_modulation"]
    assert quantized["dominant_frequency_hz"] is None
    assert quantized["status"] == "no_measurable_variation"


def test_silence_floors_short_modulation_and_partial_cells(tmp_path):
    data = tone(5)
    data[16000:24000] = 0
    r = analyze_dynamics({"source": wav(tmp_path, "gap", data)})
    assert r["source"]["modulation"]["status"] == "unavailable"
    assert "gaps not interpolated" in r["source"]["modulation"]["reason"]
    quiet = analyze_dynamics({"source": wav(tmp_path, "floor", tone() * 1e-20)})
    assert quiet["source"]["whole_file"]["crest_factor_db"] is None
    silent = analyze_dynamics({"source": wav(tmp_path, "silent", np.zeros(8000))})
    assert silent["source"]["whole_file"]["crest_factor_db"] is None
    tail = analyze_dynamics({"source": wav(tmp_path, "tail", tone(.305)), "window_seconds": .1})
    assert tail["envelope_coverage_complete"] is True
    assert tail["source"]["modulation"]["omitted_partial_cells"] == 1
    assert tail["source"]["local_windows"][-1]["end_seconds"] == .305
    paired = analyze_dynamics(aligned(wav(tmp_path, "silent2", np.zeros(8000)), wav(tmp_path, "s", tone())))
    assert paired["comparison_report"]["matching_status"] == "unavailable_integrated_lufs"


def test_candidates_source_shared_cap_and_truncation(tmp_path):
    data = np.tile(np.concatenate([tone(.03), np.zeros(1360)]), 130)
    r = analyze_dynamics(aligned(wav(tmp_path, "many", data), wav(tmp_path, "quiet", data * .1)))
    assert r["event_coverage"]["candidate_count"] == 130
    assert r["event_coverage"]["omitted_candidates"] == 10
    assert r["event_coverage"]["complete"] is False
    assert [e["start_seconds"] for e in r["source"]["events"]] == [e["start_seconds"] for e in r["comparison"]["events"]]
    final = np.zeros(8000)
    final[-40:] = tone(.005)
    tail = analyze_dynamics({"source": wav(tmp_path, "endhit", final)})
    assert tail["source"]["events"][-1]["truncated"] is True
    assert tail["source"]["events"][-1]["regions"]["body"]["status"] == "unavailable"


def test_offset_common_interval_sections_and_fractional_boundaries(tmp_path):
    data = tone()
    a = wav(tmp_path, "a", np.r_[np.zeros(17), data])
    b = wav(tmp_path, "b", np.r_[np.zeros(31), data, np.zeros(50)])
    args = aligned(a, b, sections=[{"name": "region", "start_seconds": .1234, "end_seconds": .5432}])
    args["alignment"]["offsets_samples"] = {"a": 17, "b": 31}
    r = analyze_dynamics(args)
    assert r["comparison_report"]["common_frames"] == 8000
    assert r["comparison"]["excluded_trailing_frames"] == 50
    assert r["comparison_report"]["whole_file"]["rms_dbfs"]["original_delta"] == 0
    assert r["source"]["sections"][0]["start_seconds"] == round(.1234 * 8000) / 8000


def test_validation_resource_guards_and_nonfinite(tmp_path):
    source = wav(tmp_path, "s", tone())
    for change in ({"unknown": 1}, {"window_seconds": True}, {"window_seconds": .001},
                   {"alignment": {}}, {"comparison": source}, {"comparison": wav(tmp_path, "b", tone())},
                   {"sections": [{"name": "bad", "start_seconds": 0, "end_seconds": 2}]},
                   {"events": [{**event(), "attack_end_seconds": .000001}]},
                   {"brief": {"description": "x", "score": 1}}):
        with pytest.raises(ValueError):
            analyze_dynamics({"source": source, **change})
    for alignment in ({"verified": False, "source": "x", "uncertainty_samples": 0},
                      {"verified": True, "source": "x", "uncertainty_samples": False},
                      {"verified": True, "source": "x", "uncertainty_samples": 0, "offsets_samples": {"s": 0, "b": True}}):
        with pytest.raises(ValueError):
            analyze_dynamics({"source": source, "comparison": wav(tmp_path, "b", tone()), "alignment": alignment})
    with pytest.raises(ValueError, match="equal frame lengths"):
        analyze_dynamics(aligned(source, wav(tmp_path, "short", tone(.5))))
    with pytest.raises(ValueError, match="channel layout"):
        analyze_dynamics(aligned(source, wav(tmp_path, "stereo", np.column_stack([tone(), tone()]))))
    with pytest.raises(ValueError, match="nonfinite"):
        analyze_dynamics({"source": wav(tmp_path, "nan", np.full(8000, np.nan))})
    long = wav(tmp_path, "long", np.zeros((480000, 2)))
    with pytest.raises(ValueError, match="sample-work"):
        analyze_dynamics({"source": long, "events": [{**event(), "name": str(i), "end_seconds": 60} for i in range(120)]})
    with pytest.raises(ValueError, match="120 windows"):
        analyze_dynamics({"source": long, "window_seconds": .01})


def test_public_mcp_schema_and_offline_dispatch(tmp_path):
    class NoLive:
        def request(self, *args, **kwargs):
            raise AssertionError("offline dynamics must not call Live")
    server = make_server(NoLive())
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    tool = next(t for t in tools if t["name"] == "live_audio_dynamics")
    assert tool["inputSchema"]["required"] == ["source"]
    result = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "live_audio_dynamics", "arguments": {"source": wav(tmp_path, "tool", tone())}}})
    assert not result["result"].get("isError")
    report = json.loads(result["result"]["content"][0]["text"])
    assert report["source"]["whole_file"]["crest_factor_db"] == pytest.approx(3.01, abs=.001)


def test_review_boundary_cells_runs_partial_evidence_and_floor_deltas(tmp_path):
    a = wav(tmp_path, "boundary_a", tone(1.005))
    b = wav(tmp_path, "boundary_b", tone(1.005) * 2)
    r = analyze_dynamics(aligned(a, b, window_seconds=.013))
    env = r["source"]["envelope_summary"]
    assert env["represented_cells"] == env["total_cells"] == 101
    assert sum(w["covered_frames"] for w in env["windows"]) == 8040
    assert env["partial_final_cells"][0]["frames"] == 40
    assert env["partial_final_cells"][0]["rms_dbfs"] == pytest.approx(-23.01, abs=.001)
    assert r["comparison_report"]["level_change_represented_cells"] == 101
    data = np.r_[tone(5), np.zeros(80), tone(1)]
    runs = analyze_dynamics({"source": wav(tmp_path, "runs", data)})["source"]["modulation"]
    assert runs["status"] == "no_measurable_variation"
    assert runs["intervals"][0]["start_seconds"] == 0
    assert runs["intervals"][0]["end_seconds"] == 5
    assert runs["coverage_complete"] is False
    assert runs["analyzed_duration_seconds"] == 5
    assert runs["unmeasured_duration_seconds"] == pytest.approx(1.01)
    floor = analyze_dynamics(aligned(wav(tmp_path, "floor_a", tone() * 1e-20), wav(tmp_path, "floor_b", tone() * 1e-19)))
    d = floor["comparison_report"]["whole_file"]
    assert d["rms_dbfs"]["original_delta"] is None
    assert d["status"] == "unavailable"
