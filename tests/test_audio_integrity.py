import json

import numpy as np
import pytest
import soundfile as sf

from audio_integrity import analyze_integrity, tool_properties


def analyze(tmp_path, data, rate=48000, subtype="DOUBLE", **kwargs):
    path = tmp_path / "integrity.wav"
    sf.write(path, data, rate, subtype=subtype)
    return analyze_integrity({"source": {"name": "test", "path": str(path), "signal_path": "synthetic final WAV"}, **kwargs})


def test_analytic_intersample_peak(tmp_path):
    # fs/4 with pi/4 phase: sampled peaks A/sqrt(2), continuous peaks A.
    rate = 48000
    signal = .95 * np.sin(np.arange(rate) * np.pi / 2 + np.pi / 4)
    report = analyze(tmp_path, signal)
    whole = report["measured_facts"]["whole_file"]
    assert whole["levels"]["sample_peak_dbfs"] == pytest.approx(20 * np.log10(.95 / np.sqrt(2)), abs=.002)
    assert whole["true_peak_estimate"]["dbtp"] == pytest.approx(20 * np.log10(.95), abs=.2)
    assert whole["true_peak_estimate"]["continuous_wave_maximum_verified"] is False
    assert "Near-Nyquist" in report["method"]["accuracy"]
    json.dumps(report, allow_nan=False)


def test_pcm_rails_and_dc(tmp_path):
    signal = np.full((4800, 2), .125)
    signal[10:13, 0] = 1
    signal[20:22, 1] = -1
    report = analyze(tmp_path, signal, subtype="PCM_16")
    whole = report["measured_facts"]["whole_file"]
    assert whole["clipping_observations"]["per_channel_sample_counts"] == [3, 2]
    assert whole["clipping_observations"]["proven_clipping"] is False
    runs = whole["clipping_observations"]["sustained_repeated_rail_runs"]["values"]
    assert [r["frames"] for r in runs] == [3, 2]
    assert whole["dc"]["per_channel_mean_linear"][0] == pytest.approx((4797 * .125 + 3 * (1 - 1 / 32768)) / 4800)


def test_float_silence_edit_delivery_and_sections(tmp_path):
    signal = np.zeros(48000)
    signal[4800:43200] = .1
    signal[24000] = 1.1  # intentional impulse is still only a candidate
    report = analyze(tmp_path, signal, delivery={"description": "caller constraints", "sample_rate": 48000,
        "channels": 1, "subtype": "DOUBLE", "max_true_peak_dbtp": -1, "max_abs_dc": .001},
        sections=[{"name": "ending", "start_seconds": .9, "end_seconds": 1}])
    whole = report["measured_facts"]["whole_file"]
    assert whole["clipping_observations"]["per_channel_sample_counts"] == [1]
    assert whole["silence_candidates"]["values"] == [
        {"start_seconds": 0, "end_seconds": .1, "frames": 4800},
        {"start_seconds": .9, "end_seconds": 1, "frames": 4800}]
    jumps = whole["discontinuity_candidates"]
    assert jumps["total_count"] == 2
    assert jumps["values"][0]["time_seconds"] == .5
    assert jumps["intent"] == "unknown"
    assert [x["status"] for x in report["delivery"]["checks"]] == ["within_requirement"] * 3 + ["outside_requirement"] * 2
    assert report["measured_facts"]["sections"][0]["measurement"]["silence_candidates"]["values"][0]["start_seconds"] == .9


def test_short_silent_and_edges(tmp_path):
    report = analyze(tmp_path, np.zeros(8), delivery={"description": "short", "integrated_lufs_min": -20})
    whole = report["measured_facts"]["whole_file"]
    assert whole["levels"]["integrated_lufs"] is None
    assert whole["true_peak_estimate"]["dbtp"] is None
    assert whole["true_peak_estimate"]["interior_supported_interval_seconds"] is None
    assert report["delivery"]["checks"][0]["status"] == "unavailable"
    impulse = analyze(tmp_path, np.ones(8))["measured_facts"]["whole_file"]
    assert all(b["candidate"] for b in impulse["discontinuity_candidates"]["file_boundary_observations"])


def test_caps_and_input_gates(tmp_path):
    report = analyze(tmp_path, np.tile([0., 1.], 1000))
    jumps = report["measured_facts"]["whole_file"]["discontinuity_candidates"]
    assert len(jumps["values"]) == 120
    assert jumps["omitted_count"] == 1999 - 120
    for kwargs in ({"silence_threshold_dbfs": float("nan")}, {"discontinuity_threshold": True},
                   {"unknown": 1}, {"delivery": {"description": "bad", "channels": True}},
                   {"delivery": {"description": "bad", "integrated_lufs_min": -10, "integrated_lufs_max": -20}}):
        with pytest.raises(ValueError):
            analyze(tmp_path, np.zeros(480), **kwargs)
    with pytest.raises(ValueError, match="nonfinite"):
        analyze(tmp_path, np.array([np.nan]))
    assert set(tool_properties()) >= {"source", "sections", "delivery"}


def test_section_work_gate_before_decode(tmp_path):
    signal = np.zeros(480000)
    with pytest.raises(ValueError, match="sample-work"):
        analyze(tmp_path, signal, sections=[{"name": str(i), "start_seconds": 0, "end_seconds": 10} for i in range(32)])
