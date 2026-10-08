import json
import math
import re
import shutil
import subprocess

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")
pytest.importorskip("pyloudnorm")

from audio_analysis import analyze_audio


RATE = 48000


def tone(seconds=4, gain=0.1):
    return gain * np.sin(2 * np.pi * 1000 * np.arange(round(seconds * RATE)) / RATE)


def write(tmp_path, data, name="tone.wav"):
    path = tmp_path / name
    sf.write(path, data, RATE, subtype="FLOAT")
    return str(path)


def track(path, **args):
    return analyze_audio({"path": path, **args})["tracks"][0]


def test_calibrated_sine_and_channel_weighting(tmp_path):
    mono = track(write(tmp_path, tone()))["whole_file"]
    stereo = track(write(tmp_path, np.column_stack([tone(), tone()]), "stereo.wav"))["whole_file"]
    assert mono["integrated_lufs"] == pytest.approx(-23.0, abs=0.06)
    assert mono["sample_peak_dbfs"] == pytest.approx(-20.0, abs=0.002)
    assert mono["rms_dbfs"] == pytest.approx(-23.0103, abs=0.002)
    assert stereo["integrated_lufs"] - mono["integrated_lufs"] == pytest.approx(3.0103, abs=0.003)
    assert stereo["rms_dbfs"] == mono["rms_dbfs"]
    assert mono["loudness_range_lu"] is None
    assert mono["loudness_range_status"] == "unsupported_by_backend"


def test_silence_is_json_null_and_short_signals_not_lufs(tmp_path):
    result = analyze_audio({"path": write(tmp_path, np.zeros(4 * RATE))})
    json.dumps(result, allow_nan=False)
    whole = result["tracks"][0]["whole_file"]
    assert whole["integrated_lufs"] is whole["rms_dbfs"] is whole["sample_peak_dbfs"] is None
    assert all(w["momentary_lufs"] is w["short_term_lufs"] is None for w in result["tracks"][0]["local_windows"]["values"])
    short = track(write(tmp_path, tone(0.1), "short.wav"))
    assert short["whole_file"]["integrated_status"] == "insufficient_duration"
    assert short["whole_file"]["rms_dbfs"] is not None
    assert short["local_windows"]["values"][0]["momentary_lufs"] is None


def test_gain_step_sections_and_local_windows(tmp_path):
    path = write(tmp_path, np.concatenate([tone(4), tone(4, 0.01)]))
    result = track(path, sections=[{"name": "loud", "start_seconds": 0, "end_seconds": 4},
                                  {"name": "quiet", "start_seconds": 4, "end_seconds": 8}], window_step_seconds=1)
    measurements = [s["measurement"]["integrated_lufs"] for s in result["sections"]]
    assert measurements[1] - measurements[0] == pytest.approx(-20, abs=0.003)
    windows = result["local_windows"]["values"]
    assert windows[3]["momentary_lufs"] == pytest.approx(-23, abs=0.06)
    assert windows[-1]["short_term_lufs"] == pytest.approx(-43, abs=0.06)
    assert result["level_change"]["delta_lu"] < -10
    assert "descriptive" in result["level_change"]["kind"]
    assert result["sections"][1]["integrated_delta_vs_whole_lu"] < -19


def test_quiet_window_after_loud_signal_retains_energy(tmp_path):
    path = write(tmp_path, np.concatenate([tone(4, 1), tone(4, 1e-9)]))
    last = track(path, window_step_seconds=1)["local_windows"]["values"][-1]
    assert last["momentary_lufs"] == pytest.approx(-183, abs=0.06)
    assert last["short_term_lufs"] == pytest.approx(-183, abs=0.06)


def test_null_gap_does_not_count_as_consecutive_change(tmp_path):
    # Leave enough silence for filter decay to become exact zero in float64.
    path = write(tmp_path, np.concatenate([tone(3), np.zeros(37 * RATE), tone(3, 0.01)]))
    result = track(path, window_step_seconds=10)
    windows = result["local_windows"]["values"]
    assert any(w["short_term_lufs"] is None for w in windows)
    # The final quiet window follows a null window: no fictitious delta is reported.
    assert result["level_change"]["to_end_seconds"] != 43


def test_gate_excludes_long_silence(tmp_path):
    steady = track(write(tmp_path, tone(10)))["whole_file"]["integrated_lufs"]
    mixed = track(write(tmp_path, np.concatenate([tone(10), np.zeros(10 * RATE)]), "gated.wav"))["whole_file"]["integrated_lufs"]
    assert mixed == pytest.approx(steady, abs=0.15)
    tiny = track(write(tmp_path, tone(2, 1e-5), "tiny.wav"))["whole_file"]
    assert tiny["integrated_lufs"] is None
    assert tiny["sample_peak_dbfs"] == pytest.approx(-100, abs=0.01)


def test_non_hop_aligned_file_and_section_use_complete_gate_blocks(tmp_path):
    path = write(tmp_path, tone(0.46))
    result = track(path, sections=[{"name": "short", "start_seconds": 0, "end_seconds": 0.46}])
    assert result["whole_file"]["duration_seconds"] == 0.46
    assert result["whole_file"]["integrated_lufs"] == pytest.approx(-23.004, abs=0.01)
    assert result["sections"][0]["measurement"]["integrated_lufs"] == result["whole_file"]["integrated_lufs"]
    assert result["whole_file"]["rms_dbfs"] == pytest.approx(-23.0103, abs=0.002)


def test_manifest_retains_restore_failure_reason(tmp_path):
    path = write(tmp_path, tone())
    manifest = {"complete": False, "passage_observed_complete": True,
        "restore_error": "transport stop did not settle",
        "tracks": [{"path": path, "outcome": "captured"}]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    result = analyze_audio({"manifest_path": str(manifest_path)})
    assert not result["complete"]
    assert result["tracks"][0]["outcome"] == "analyzed"
    assert result["capture"]["restore_error"] == manifest["restore_error"]
    assert result["capture"]["passage_observed_complete"] is True


def test_manifest_preserves_uncertainty_and_fails_closed(tmp_path):
    path = write(tmp_path, tone())
    manifest = {"complete": True, "precision": "approximate", "raw_untrimmed": True,
        "sample_aligned": False, "sample_uncertainty": None, "signal_point": "pre-mixer",
        "tracks": [{"name": "source", "kind": "track", "path": "tone.wav", "outcome": "captured"},
                   {"name": "master", "kind": "master", "path": path, "outcome": "captured"},
                   {"name": "frozen", "outcome": "unsupported", "reason": "frozen"},
                   {"name": "partial", "path": path, "outcome": "incomplete"},
                   {"name": "missing", "path": "missing.wav", "outcome": "captured"}]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    result = analyze_audio({"manifest_path": str(manifest_path)})
    assert not result["complete"]
    assert result["capture"]["signal_point"] == "pre-mixer"
    assert result["capture"]["sample_uncertainty"] is None
    assert [t["outcome"] for t in result["tracks"]] == ["analyzed", "analyzed", "unsupported", "incomplete", "analysis_failed"]
    assert result["relative_to_master"]["values"] == []
    assert result["relative_to_master"]["status"] == "unavailable"
    manifest["tracks"] = manifest["tracks"][:2]
    manifest["complete"] = False
    manifest_path.write_text(json.dumps(manifest))
    assert not analyze_audio({"manifest_path": str(manifest_path)})["complete"]
    manifest["complete"] = True
    manifest_path.write_text(json.dumps(manifest))
    assert analyze_audio({"manifest_path": str(manifest_path)})["complete"]


@pytest.mark.parametrize("args", [{}, {"path": "x", "manifest_path": "y"}, {"path": 1},
    {"path": "x", "window_step_seconds": True}, {"path": "x", "window_step_seconds": math.nan},
    {"path": "x", "unknown": 1}, {"path": "x", "sections": [{"name": "a", "start_seconds": 2, "end_seconds": 1}]}])
def test_argument_validation(args):
    with pytest.raises(ValueError):
        analyze_audio(args)


def test_file_and_resource_validation(tmp_path, monkeypatch):
    path = write(tmp_path, tone())
    with pytest.raises(ValueError, match="windows"):
        track(path, window_step_seconds=0.001)
    assert len(track(path, window_step_seconds=1e308)["local_windows"]["values"]) == 1
    with pytest.raises(ValueError, match="duration"):
        track(path, sections=[{"name": "outside", "start_seconds": 0, "end_seconds": 100}])
    with pytest.raises(ValueError, match="mono/stereo"):
        track(write(tmp_path, np.zeros((RATE, 3)), "surround.wav"))
    with pytest.raises(ValueError, match="nonfinite"):
        track(write(tmp_path, np.full(RATE, np.nan), "nan.wav"))
    with pytest.raises(ValueError, match="RIFF size"):
        broken = tmp_path / "broken.wav"
        broken.write_bytes((tmp_path / "tone.wav").read_bytes()[:-1])
        track(str(broken))
    monkeypatch.setattr("audio_analysis.MAX_SAMPLES", 100)
    with pytest.raises(ValueError, match="budget"):
        track(path)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="optional independent EBU R128 oracle")
@pytest.mark.parametrize("data", [tone(0.46), tone(10), np.column_stack([tone(10), tone(10)]),
    np.concatenate([tone(5), tone(5, 0.01), np.zeros(5 * RATE)])])
def test_ffmpeg_ebur128_oracle(tmp_path, data):
    path = write(tmp_path, data)
    process = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True, timeout=30, check=True)
    oracle = float(re.findall(r"I:\s+(-?\d+\.\d+) LUFS", process.stderr)[-1])
    result = track(path)["whole_file"]["integrated_lufs"]
    assert result == pytest.approx(oracle, abs=0.12)
    if data.ndim == 1 and len(data) == 10 * RATE:
        oracle_windows = re.findall(r"t:\s+([\d.]+).*?M:\s+(-?[\d.]+)\s+S:\s+(-?[\d.]+)", process.stderr)
        end, momentary, short_term = map(float, oracle_windows[-1])
        local = track(path, window_step_seconds=1)["local_windows"]["values"][-1]
        assert local["end_seconds"] == pytest.approx(end, abs=0.001)
        assert local["momentary_lufs"] == pytest.approx(momentary, abs=0.12)
        assert local["short_term_lufs"] == pytest.approx(short_term, abs=0.12)
