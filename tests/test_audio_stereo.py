import json

import numpy as np
import pytest
import soundfile as sf

from audio_stereo import analyze_stereo, tool_properties, TOOL_REQUIRED


def tone(frequency=1000, duration=1, rate=48000):
    return .1 * np.sin(2 * np.pi * frequency * np.arange(round(rate * duration)) / rate)


def wav(tmp_path, name, data, rate=48000):
    path = tmp_path / f"{name}.wav"
    sf.write(path, data, rate, subtype="FLOAT")
    return {"name": name, "path": str(path), "signal_path": "synthetic identified offline fixture"}


def measurement(report):
    return report["source"]["whole_file"]["broadband"]


def band(report, name):
    return next(b for b in report["source"]["whole_file"]["spectrum"]["bands"] if b["name"] == name)


@pytest.mark.parametrize("kind,correlation,side,fold", [
    ("center", 1, 0, 0), ("opposite", -1, 1, None), ("left", None, .5, -3.0103)])
def test_exact_stereo_algebra(tmp_path, kind, correlation, side, fold):
    x = tone()
    right = x if kind == "center" else -x if kind == "opposite" else np.zeros_like(x)
    report = analyze_stereo({"source": wav(tmp_path, kind, np.column_stack((x, right)))})
    broad = measurement(report)
    assert broad["lr_normalized_real_cross_power"] == correlation
    assert broad["side_fraction"] == side
    assert broad["mono_fold_power_change_db"] == pytest.approx(fold) if fold is not None else broad["mono_fold_power_change_db"] is None
    assert broad["exact_zero_mono_power"] is (kind == "opposite")
    if kind == "opposite":
        assert broad["mono_fold_status"] == "below_numerical_floor"
        assert broad["mono_fold_change_upper_db"] < -200
        assert abs(band(report, "mid")["measurement"]["lr_cross_phase_degrees"]) == 180
    json.dumps(report, allow_nan=False)


def test_frequency_dependent_phase_width_and_fold(tmp_path):
    bass, bright = tone(100), tone(3000)
    report = analyze_stereo({"source": wav(tmp_path, "bands", np.column_stack((bass + bright, bass - bright)))})
    low, high = band(report, "bass")["measurement"], band(report, "upper_mid")["measurement"]
    assert low["side_fraction"] < 1e-6
    assert high["side_fraction"] > .999999
    assert low["mono_fold_power_change_db"] == pytest.approx(0, abs=.001)
    assert high["mono_fold_power_change_db"] is None or high["mono_fold_power_change_db"] < -120
    assert abs(high["lr_cross_phase_degrees"]) == pytest.approx(180, abs=.001)
    assert measurement(report)["mono_fold_power_change_db"] == pytest.approx(-3.0103, abs=.001)


def test_quadrature_band_phase_and_uncentered_dc(tmp_path):
    t = np.arange(48000) / 48000
    source = wav(tmp_path, "quarter", np.column_stack((.1 * np.cos(2*np.pi*1000*t), .1 * np.sin(2*np.pi*1000*t))))
    report = analyze_stereo({"source": source})
    assert band(report, "mid")["measurement"]["lr_cross_phase_degrees"] == pytest.approx(-90, abs=.001)
    assert abs(measurement(report)["lr_normalized_real_cross_power"]) < 1e-6
    dc = analyze_stereo({"source": wav(tmp_path, "dc", np.full((48000, 2), .1))})
    assert measurement(dc)["lr_normalized_real_cross_power"] == 1


def test_native_mono_silence_floor_and_float_headroom(tmp_path):
    report = analyze_stereo({"source": wav(tmp_path, "native", tone())})
    assert measurement(report)["stereo_status"] == "unavailable_native_mono"
    assert measurement(report)["right_power_dbfs"] is None
    assert measurement(report)["side_fraction"] is None
    assert measurement(report)["mono_fold_power_change_db"] == 0
    silence = analyze_stereo({"source": wav(tmp_path, "silent", np.zeros((48000, 2)))})
    assert measurement(silence)["status"] == "silent"
    assert measurement(silence)["mono_fold_power_change_db"] is None
    tiny = analyze_stereo({"source": wav(tmp_path, "tiny", np.column_stack((tone(), tone())) * 1e-16)})
    assert measurement(tiny)["status"] == "below_numerical_floor"
    hot = analyze_stereo({"source": wav(tmp_path, "hot", np.column_stack((tone(), tone())) * 20)})
    assert measurement(hot)["mean_channel_power_dbfs"] > 0
    json.dumps(tiny, allow_nan=False)


def test_sections_and_short_spectral_coverage(tmp_path):
    x = tone()
    data = np.concatenate((np.column_stack((x, x)), np.column_stack((x, -x))))
    report = analyze_stereo({"source": wav(tmp_path, "passage", data), "sections": [
        {"name": "center", "start_seconds": 0, "end_seconds": 1},
        {"name": "side", "start_seconds": 1, "end_seconds": 2}]})
    assert report["source"]["sections"][0]["broadband"]["side_fraction"] == 0
    assert report["source"]["sections"][1]["broadband"]["side_fraction"] == 1
    assert report["coverage"]["spectral_coverage_complete"]
    short = analyze_stereo({"source": wav(tmp_path, "short", np.column_stack((tone(duration=.1), tone(duration=.1))))})
    assert short["source"]["whole_file"]["spectrum"]["status"] == "insufficient_duration"
    assert not short["coverage"]["spectral_coverage_complete"]
    tail = analyze_stereo({"source": wav(tmp_path, "tail", np.column_stack((tone(duration=1.01), tone(duration=1.01))))})
    assert tail["source"]["whole_file"]["spectrum"]["omitted_tail_seconds"] == pytest.approx(.01)
    assert tail["source"]["windows"][-1]["spectrum"]["status"] == "insufficient_duration"


def test_nyquist_coverage(tmp_path):
    x = tone(rate=8000)
    report = analyze_stereo({"source": wav(tmp_path, "lowrate", np.column_stack((x, x)), 8000)})
    assert band(report, "upper_mid")["coverage"] == "partial"
    assert band(report, "high")["coverage"] == "unsupported"
    assert band(report, "high")["measurement"] is None


def target_args(tmp_path, target=None, competitor=None, rate=48000, duration=1):
    x = tone(1000, duration, rate)
    target = np.column_stack((x, -x)) if target is None else target
    competitor = np.column_stack((tone(2000, duration, rate), tone(2000, duration, rate))) if competitor is None else competitor
    programme = wav(tmp_path, "programme", target + competitor, rate)
    a, b = wav(tmp_path, "part", target, rate), wav(tmp_path, "other", competitor, rate)
    return {"source": programme, "target": {k: a[k] for k in ("name", "path")},
        "competitors": [{k: b[k] for k in ("name", "path")}],
        "alignment": {"verified": True, "source": "same synthetic sample clock", "uncertainty_samples": 0},
        "provenance": {"disjoint_contributions": True, "in_mix_levels": True, "signal_path": "disjoint additive in-mix source fixtures"},
        "listening_condition": {"kind": "assumed", "db_spl_at_0_dbfs_rms": 100, "source": "explicit synthetic test condition"}}


def test_important_part_fold_and_required_evidence(tmp_path):
    args = target_args(tmp_path)
    report = analyze_stereo(args)
    window = report["perceptual_estimates"]["windows"][0]
    assert window["stereo"]["active_component_count"] > 0
    assert window["stereo"]["threshold_excess_dbfs"] is not None
    assert window["mono"]["active_component_count"] == 0
    assert window["mono_minus_stereo_threshold_excess_db"] is None
    assert report["perceptual_estimates"]["listening_condition"] == args["listening_condition"]
    assert report["coverage"]["offsets_samples"] == {"programme": 0, "part": 0, "other": 0}
    standalone = analyze_stereo({"source": args["source"]})
    assert standalone["perceptual_estimates"]["status"] == "unavailable"
    json.dumps(report, allow_nan=False)
    for key in ("alignment", "provenance", "listening_condition", "competitors"):
        with pytest.raises(ValueError):
            analyze_stereo({k: v for k, v in args.items() if k != key})


def test_fold_preserves_centered_levels_and_reports_short_tail(tmp_path):
    x = tone(duration=1.01)
    args = target_args(tmp_path, target=np.column_stack((x, x)), duration=1.01)
    report = analyze_stereo(args)
    windows = report["perceptual_estimates"]["windows"]
    assert windows[0]["mono_minus_stereo_threshold_excess_db"] == pytest.approx(0, abs=.001)
    assert windows[-1]["status"] == "unavailable_insufficient_duration"
    assert report["coverage"]["unmeasured_perceptual_seconds"] == pytest.approx(.01)


def test_offsets_include_programme_and_common_interval(tmp_path):
    args = target_args(tmp_path)
    args["alignment"]["offsets_samples"] = {"programme": 4800, "part": 2400, "other": 0}
    report = analyze_stereo(args)
    assert report["coverage"]["duration_seconds"] == .9
    args["alignment"]["offsets_samples"].pop("programme")
    with pytest.raises(ValueError, match="every name including programme"):
        analyze_stereo(args)


@pytest.mark.parametrize("change", ["uncertainty", "pre_fader", "overlap", "layout", "rate", "samepath", "offset_bool", "duplicate_name"])
def test_target_evidence_and_metadata_rejection(tmp_path, change):
    args = target_args(tmp_path)
    if change == "uncertainty":
        args["alignment"]["uncertainty_samples"] = True
    elif change == "pre_fader":
        args["provenance"]["in_mix_levels"] = False
    elif change == "overlap":
        args["provenance"]["disjoint_contributions"] = False
    elif change in ("layout", "rate"):
        replacement = wav(tmp_path, "changed", tone() if change == "layout" else np.column_stack((tone(rate=44100), tone(rate=44100))), 48000 if change == "layout" else 44100)
        args["target"]["path"] = replacement["path"]
    elif change == "samepath":
        args["target"]["path"] = args["competitors"][0]["path"]
    elif change == "duplicate_name":
        args["target"]["name"] = args["source"]["name"]
    else:
        args["alignment"]["offsets_samples"] = {"programme": False, "part": 0, "other": 0}
    with pytest.raises(ValueError):
        analyze_stereo(args)


@pytest.mark.parametrize("extra", [
    {"window_seconds": False}, {"window_seconds": float("nan")}, {"max_windows": True}, {"max_windows": 0},
    {"oops": 1}, {"sections": [{"name": "outside", "start_seconds": 0, "end_seconds": 2}]},
    {"sections": [{"name": "empty", "start_seconds": 0, "end_seconds": 1e-10}]},
    {"sections": [{"name": "backwards", "start_seconds": 1, "end_seconds": 0}]},
    {"sections": [{"name": "huge", "start_seconds": 0, "end_seconds": 1e307}]}])
def test_validation(tmp_path, extra):
    x = tone()
    with pytest.raises(ValueError):
        analyze_stereo({"source": wav(tmp_path, "source", np.column_stack((x, x))), **extra})


def test_nonfinite_work_bound_and_window_bound(tmp_path):
    x = tone()
    with pytest.raises(ValueError, match="nonfinite"):
        analyze_stereo({"source": wav(tmp_path, "nan", np.full((48000, 2), np.nan))})
    source = wav(tmp_path, "valid", np.column_stack((x, x)))
    with pytest.raises(ValueError, match="window budget"):
        analyze_stereo({"source": source, "window_seconds": .1, "max_windows": 1})
    # Repeated sections reserve work before decode/DSP.
    long = tone(duration=4)
    source = wav(tmp_path, "long", np.column_stack((long, long)))
    with pytest.raises(ValueError, match="sample-work"):
        analyze_stereo({"source": source, "sections": [
            {"name": str(i), "start_seconds": 0, "end_seconds": 4} for i in range(32)]})


def test_lean_schema_export():
    assert TOOL_REQUIRED == ["source"]
    assert set(tool_properties()) == {"source", "target", "competitors", "alignment", "provenance", "listening_condition", "sections", "window_seconds", "max_windows"}
    json.dumps(tool_properties(), allow_nan=False)
