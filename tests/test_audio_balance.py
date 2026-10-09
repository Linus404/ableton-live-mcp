"""Aligned programme facts and declared artistic expectations, not stem ranking."""
import json

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")
pytest.importorskip("pyloudnorm")

from audio_balance import analyze_balance


def request(tmp_path):
    rate = 16000
    time = np.arange(rate * 4) / rate
    a = 0.1 * np.sin(2 * np.pi * 1000 * time)
    b = 0.05 * np.sin(2 * np.pi * 3000 * time)
    a[rate * 2:] *= 2
    b[rate * 2:] *= 2
    entries = []
    for name, signal in (("programme", a + b), ("lead", a), ("pad", b)):
        path = tmp_path / f"{name}.wav"
        sf.write(path, signal, rate, subtype="FLOAT")
        entries.append({"name": name, "path": str(path)})
    return {"programme": entries[0], "parts": entries[1:],
        "alignment": {"verified": True, "source": "same offline render clock", "uncertainty_samples": 0},
        "provenance": {"disjoint_contributions": True, "in_mix_levels": True, "signal_path": "disjoint post-mixer stereo contributions"},
        "sections": [{"name": "quiet", "start_seconds": 0, "end_seconds": 2},
                     {"name": "loud", "start_seconds": 2, "end_seconds": 4}],
        "expected_section_differences": [{"from_section": "quiet", "to_section": "loud", "expected_delta_lu": 6.0206, "tolerance_lu": 0.05}]}


def test_balance_expected_contrast_local_evidence_and_matching(tmp_path):
    args = request(tmp_path)
    args["parts"][0]["gain_db"] = 3
    args["fair_loudness_match"] = {"target_lufs": -18}
    report = analyze_balance(args)
    assert report["measurement_complete"] is True
    assert report["complete"] is False
    assert report["perceptual_estimation_complete"] is False
    assert "listening_condition" in report["incomplete_reasons"][0]
    expectation = report["section_expectations"][0]
    assert expectation["observed_delta_lu"] == pytest.approx(6.021, abs=0.01)
    assert expectation["judgment"] == "within_declared_expectation"
    part = report["parts"][0]
    assert part["gain_scenario"]["whole_file"]["integrated_lufs"] - part["original"]["whole_file"]["integrated_lufs"] == pytest.approx(3, abs=0.01)
    assert part["relative_integrated_lu"] < 0
    assert part["local_relative_to_programme"][-1]["short_term_delta_lu"] < 0
    assert part["fair_loudness_match"]["applied"] is False
    args["expected_section_differences"][0]["expected_delta_lu"] = 0
    assert analyze_balance(args)["section_expectations"][0]["judgment"] == "outside_declared_expectation"
    json.dumps(report, allow_nan=False)


def test_balance_model_and_strict_provenance(tmp_path):
    args = request(tmp_path)
    args["listening_condition"] = {"kind": "assumed", "db_spl_at_0_dbfs_rms": 100, "source": "hypothetical listening level"}
    args["window_seconds"] = 1
    report = analyze_balance(args)
    assert len(report["parts"][0]["perceptual_prominence"]["windows"]) == 4
    assert report["parts"][0]["perceptual_prominence"]["model"]["status"] == "estimated"
    assert report["complete"] is True
    args["provenance"]["in_mix_levels"] = False
    with pytest.raises(ValueError, match="pre-mixer"):
        analyze_balance(args)


def test_balance_offset_common_interval_and_validation(tmp_path):
    args = request(tmp_path)
    original, rate = sf.read(args["programme"]["path"])
    sf.write(args["programme"]["path"], np.concatenate([np.zeros(1600), original]), rate, subtype="FLOAT")
    args["alignment"]["offsets_samples"] = {"programme": 1600, "lead": 0, "pad": 0}
    assert analyze_balance(args)["common_duration_seconds"] == 4
    args["alignment"]["offsets_samples"]["programme"] = True
    with pytest.raises(ValueError, match="offset"):
        analyze_balance(args)


def test_single_part_ath_and_shorter_programme_are_supported(tmp_path):
    args = request(tmp_path)
    args["parts"] = args["parts"][:1]
    args["sections"] = []
    args["expected_section_differences"] = []
    programme, rate = sf.read(args["programme"]["path"])
    sf.write(args["programme"]["path"], programme[:rate * 2], rate, subtype="FLOAT")
    args["alignment"]["offsets_samples"] = {"programme": 0, "lead": 0}
    args["listening_condition"] = {"kind": "assumed", "db_spl_at_0_dbfs_rms": 100, "source": "hypothetical"}
    report = analyze_balance(args)
    assert report["common_duration_seconds"] == 2
    model = report["parts"][0]["perceptual_prominence"]
    assert model["windows"][-1]["end_seconds"] == 2
    assert all(not c["contributors"] for w in model["windows"] for c in w["perceptual_estimate"]["components"])


def test_spectra_reused_across_targets(tmp_path, monkeypatch):
    args = request(tmp_path)
    args["listening_condition"] = {"kind": "assumed", "db_spl_at_0_dbfs_rms": 100, "source": "hypothetical"}
    args["window_seconds"] = 1
    real_open = sf.SoundFile
    opened = []

    def counting_open(*a, **kw):
        opened.append(a[0])
        return real_open(*a, **kw)

    monkeypatch.setattr(sf, "SoundFile", counting_open)
    analyze_balance(args)
    # Two contribution FFT reads + programme and two loudness reads.
    assert len(opened) == 5


def test_quiet_threshold_inactivity_is_completed_estimation(tmp_path):
    args = request(tmp_path)
    args["listening_condition"] = {"kind": "assumed", "db_spl_at_0_dbfs_rms": 0, "source": "hypothetical very quiet playback"}
    report = analyze_balance(args)
    assert report["measurement_complete"] is True
    assert report["perceptual_estimation_complete"] is True
    assert report["complete"] is True
    assert report["incomplete_reasons"] == []
    assert all(w["perceptual_estimate"]["status"] == "no_components_above_quiet_threshold"
               for part in report["parts"] for w in part["perceptual_prominence"]["windows"])


def test_expectation_tolerance_below_report_resolution_rejected(tmp_path):
    args = request(tmp_path)
    # Doubling is 6.020599913 LU, but independently reported values are .001 LU.
    args["expected_section_differences"][0]["tolerance_lu"] = 0.0001
    with pytest.raises(ValueError, match="tolerance_lu.*0.001"):
        analyze_balance(args)
    args["expected_section_differences"][0]["tolerance_lu"] = 0.001
    report = analyze_balance(args)
    assert report["section_expectations"][0]["judgment"] == "within_declared_expectation"
    assert report["judgment_precision"]["minimum_tolerance_lu"] == 0.001


def test_frame_limited_final_window_survives_upward_time_rounding(tmp_path):
    rate, frames = 44100, 751616
    duration = frames / rate
    assert round(duration, 6) > duration
    time = np.arange(frames) / rate
    signal = 0.1 * np.sin(2 * np.pi * 1000 * time)
    entries = []
    for name in ("programme", "lead"):
        path = tmp_path / f"{name}.wav"
        sf.write(path, signal, rate, subtype="FLOAT")
        entries.append({"name": name, "path": str(path)})
    args = {"programme": entries[0], "parts": entries[1:],
        "alignment": {"verified": True, "source": "identical rendered frame clocks", "uncertainty_samples": 0},
        "provenance": {"disjoint_contributions": True, "in_mix_levels": True, "signal_path": "single post-mixer contribution and separate programme"},
        "listening_condition": {"kind": "assumed", "db_spl_at_0_dbfs_rms": 100, "source": "hypothetical"},
        "window_seconds": 0.3}
    report = analyze_balance(args)
    model = report["parts"][0]["perceptual_prominence"]
    # Last 0.2446-second window is measured, not the unsupported <100ms tail.
    assert model["windows"][-1]["end_seconds"] == round(duration, 6)
    assert model["coverage"]["complete"] is True
    assert report["complete"] is True
