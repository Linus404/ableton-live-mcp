import json

import numpy as np
import pytest
import soundfile as sf

from audio_tonal import analyze_tonal
from server import make_server


def wav(tmp_path, name, data, rate=48000):
    path = tmp_path / f"{name}.wav"
    sf.write(path, data, rate, subtype="FLOAT")
    return {"name": name, "path": str(path), "signal_path": "synthetic offline measured test signal"}


def tone(frequency, rate=48000, duration=1):
    return .1 * np.sin(2 * np.pi * frequency * np.arange(round(rate * duration)) / rate)


def band(report, name):
    return next(b for b in report["source"]["whole_file"]["spectrum"]["bands"] if b["name"] == name)


def test_sine_energy_frequency_and_antiphase_stereo(tmp_path):
    data = tone(1000)
    mono = analyze_tonal({"source": wav(tmp_path, "mono", data)})
    stereo = analyze_tonal({"source": wav(tmp_path, "stereo", np.column_stack([data, -data]))})
    spectrum = stereo["source"]["whole_file"]["spectrum"]
    assert band(stereo, "mid")["power_dbfs"] == pytest.approx(-23.01, abs=.02)
    assert band(stereo, "mid")["relative_db"] == pytest.approx(0, abs=.01)
    assert spectrum["centroid_hz"] == pytest.approx(1000, abs=1)
    assert spectrum["spectral_peaks"][0]["frequency_hz"] == pytest.approx(1000, abs=4)
    assert stereo["source"]["peak_persistence"][0]["matching_local_windows"] == 4
    assert spectrum["bands"] == mono["source"]["whole_file"]["spectrum"]["bands"]
    json.dumps(stereo, allow_nan=False)


def test_reference_gain_invariance_and_original_loudness(tmp_path):
    data = tone(100) + tone(3000)
    source = wav(tmp_path, "mix", data)
    reference = wav(tmp_path, "quiet", data * .1)
    report = analyze_tonal({"source": source, "reference": reference})
    comparison = report["reference_comparison"]
    assert comparison["reference_gain_to_source_lufs_db"] == pytest.approx(20, abs=.01)
    assert comparison["gain_applied"] is False
    for item in comparison["whole_file"]:
        if item["band"] in ("bass", "upper_mid"):
            assert item["delta_relative_db"] == pytest.approx(0, abs=.01)
    assert report["source"]["whole_file"]["levels"]["rms_dbfs"] - report["reference"]["whole_file"]["levels"]["rms_dbfs"] == pytest.approx(20, abs=.01)


def test_sections_localize_low_end_and_brief_departures(tmp_path):
    data = np.concatenate([tone(100), tone(3000)])
    report = analyze_tonal({"source": wav(tmp_path, "sections", data), "window_seconds": .5,
        "sections": [{"name": "bass", "start_seconds": 0, "end_seconds": 1},
                     {"name": "bright", "start_seconds": 1, "end_seconds": 2}],
        "brief": {"description": "Bass relative power should be below -6 dB",
                  "band_expectations": [{"band": "bass", "min_relative_db": -120, "max_relative_db": -6}]}})
    observations = {o["interval"]: o for o in report["brief_observations"]}
    assert observations["bass"]["status"] == "above_brief"
    assert observations["bright"]["status"] != "above_brief"
    assert observations["window_0"]["end_seconds"] == .5
    assert observations["window_0"]["status"] == "above_brief"
    assert report["source"]["sections"][1]["spectrum"]["centroid_hz"] == pytest.approx(3000, abs=2)


def test_silence_short_intervals_and_nyquist_not_missing_treble(tmp_path):
    silent = analyze_tonal({"source": wav(tmp_path, "silence", np.zeros(48000))})
    assert silent["source"]["whole_file"]["spectrum"]["status"] == "silent_in_analyzed_band"
    assert all(b["relative_db"] is None for b in silent["source"]["whole_file"]["spectrum"]["bands"])
    short = analyze_tonal({"source": wav(tmp_path, "short", tone(1000, duration=.1))})
    assert short["source"]["whole_file"]["spectrum"]["status"] == "insufficient_duration"
    low_rate = wav(tmp_path, "8k", tone(1000, rate=8000), 8000)
    report = analyze_tonal({"source": low_rate, "reference": wav(tmp_path, "48k", tone(1000))})
    assert band(report, "upper_mid")["coverage"] == "partial"
    assert band(report, "high")["coverage"] == "unsupported"
    assert band(report, "high")["relative_db"] is None
    assert all(b["status"] == "unavailable" for b in report["reference_comparison"]["whole_file"])


def test_white_noise_bandwidth_and_reference_brightness(tmp_path):
    rng = np.random.default_rng(23)
    source = wav(tmp_path, "white", rng.normal(0, .03, 48000 * 3))
    report = analyze_tonal({"source": source, "reference": wav(tmp_path, "dark", tone(100, duration=3))})
    spectrum = report["source"]["whole_file"]["spectrum"]
    assert spectrum["centroid_hz"] == pytest.approx(10010, abs=300)
    assert spectrum["rolloff_85_hz"] == pytest.approx(17003, abs=500)
    ratio = band(report, "high")["power_dbfs"] - band(report, "bass")["power_dbfs"]
    assert ratio == pytest.approx(10 * np.log10(14000 / 190), abs=.8)


def test_trust_boundary_and_request_budget(tmp_path):
    source = wav(tmp_path, "normal", tone(1000))
    for change in ({"window_seconds": True}, {"window_seconds": .001}, {"unknown": 2},
                   {"sections": [{"name": "oops", "start_seconds": 0, "end_seconds": 2}]},
                   {"brief": {"description": "x", "band_expectations": [{"band": "high", "min_relative_db": -2, "max_relative_db": -10}]}}):
        with pytest.raises(ValueError):
            analyze_tonal({"source": source, **change})
    sections = [{"name": str(i), "start_seconds": 0, "end_seconds": 40} for i in range(32)]
    # Stereo adds the scalar-channel budget; repeated sections count too.
    long = wav(tmp_path, "budget_stereo", np.zeros((48000 * 40, 2)))
    with pytest.raises(ValueError, match="total sample-work"):
        analyze_tonal({"source": long, "sections": sections})
    with pytest.raises(ValueError, match="120 windows"):
        analyze_tonal({"source": long, "window_seconds": .25})


def test_tail_coverage_and_nonfinite_audio(tmp_path):
    source = wav(tmp_path, "tail", tone(1000, duration=.3))
    report = analyze_tonal({"source": source, "window_seconds": .25})
    spectrum = report["source"]["whole_file"]["spectrum"]
    assert spectrum["covered_duration_seconds"] == .25
    assert spectrum["omitted_tail_seconds"] == .05
    assert report["processing_complete"] is True
    assert report["spectrum_coverage_complete"] is False
    assert report["source"]["local_windows"][1]["spectrum"]["status"] == "insufficient_duration"
    bad = wav(tmp_path, "nan", np.array([float("nan")] * 48000))
    with pytest.raises(ValueError, match="nonfinite"):
        analyze_tonal({"source": bad})
    with pytest.raises(ValueError, match="band must"):
        analyze_tonal({"source": source, "brief": {"description": "x", "band_expectations": [
            {"band": [], "min_relative_db": -20, "max_relative_db": -10}]}})


def test_dc_nyquist_roundoff_not_tonal_evidence_and_quiet_real_tone(tmp_path):
    for name, data in (("dc", np.full(48000, .1)),
                       ("nyquist", .1 * (-1.) ** np.arange(48000))):
        report = analyze_tonal({"source": wav(tmp_path, name, data)})
        spectrum = report["source"]["whole_file"]["spectrum"]
        assert spectrum["status"] == "below_numerical_floor"
        assert spectrum["centroid_hz"] is None
        assert spectrum["rolloff_85_hz"] is None
        assert spectrum["spectral_peaks"] == []
        assert all(b["relative_db"] is None for b in spectrum["bands"])
        assert report["source"]["whole_file"]["levels"]["rms_dbfs"] == pytest.approx(-20, abs=.01)
    quiet = analyze_tonal({"source": wav(tmp_path, "quiet_real", tone(1000) * 1e-9)})
    assert quiet["source"]["whole_file"]["spectrum"]["status"] == "measured"
    assert quiet["source"]["whole_file"]["spectrum"]["centroid_hz"] == pytest.approx(1000, abs=1)
    assert band(quiet, "mid")["power_dbfs"] == pytest.approx(-203.01, abs=.02)


def test_below_floor_band_upper_bound_can_establish_missing_region(tmp_path):
    brief = {"description": "Bass power expected", "band_expectations": [
        {"band": "bass", "min_relative_db": -30, "max_relative_db": -6}]}
    report = analyze_tonal({"source": wav(tmp_path, "no_bass", tone(1000)), "brief": brief})
    bass = band(report, "bass")
    assert bass["measurement_status"] == "below_numerical_floor"
    assert bass["relative_db"] is None
    assert bass["upper_relative_db"] < -30
    observed = report["brief_observations"][0]
    assert observed["measured_relative_db"] is None
    assert observed["status"] == "below_brief"
    assert observed["upper_relative_db"] < -30
    silent = analyze_tonal({"source": wav(tmp_path, "silent_brief", np.zeros(48000)), "brief": brief})
    assert all(o["status"] == "unavailable" for o in silent["brief_observations"])


def test_tool_schema_and_real_offline_dispatch(tmp_path):
    class NoLive:
        def request(self, *args):
            raise AssertionError("tonal analysis must never access Live")
    server = make_server(NoLive())
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    tool = next(t for t in tools if t["name"] == "live_audio_tonal")
    assert tool["inputSchema"]["required"] == ["source"]
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "live_audio_tonal", "arguments": {"source": wav(tmp_path, "tool", tone(1000))}}})
    assert not response["result"].get("isError")
    report = json.loads(response["result"]["content"][0]["text"])
    assert report["source"]["whole_file"]["spectrum"]["centroid_hz"] == pytest.approx(1000, abs=1)
