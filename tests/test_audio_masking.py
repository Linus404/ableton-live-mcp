"""Analytic signals exercise competition evidence independently of implementation."""
import copy
import json

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

from audio_masking import analyze_masking


def tone(frequency=1000, amplitude=0.1, duration=0.4, rate=16000):
    return amplitude * np.sin(2 * np.pi * frequency * np.arange(round(duration * rate)) / rate)


def request(tmp_path, target=None, competitors=None, rate=16000):
    signals = [tone() if target is None else target, *(competitors if competitors is not None else [tone(amplitude=0.4)])]
    entries = []
    for index, signal in enumerate(signals):
        path = tmp_path / f"source{index}.wav"
        sf.write(path, signal, rate, subtype="FLOAT")
        entries.append({"name": f"source{index}", "path": str(path)})
    return {"target": entries[0], "competitors": entries[1:],
        "alignment": {"verified": True, "source": "Offline render sharing start and clock", "uncertainty_samples": 0},
        "provenance": {"disjoint_contributions": True, "in_mix_levels": True, "signal_path": "post-fader disjoint dry tracks, no shared processing"}}


def strongest(report, window=0):
    return report["windows"][window]["strongest_target_bands"][0]


def test_same_band_vs_separated_and_calibrated_ratio(tmp_path):
    args = request(tmp_path)
    same = analyze_masking(args)
    assert strongest(same)["target_to_competitor_db"] == pytest.approx(-12.041, abs=0.02)
    # Unit sine mean-square is A²/2; nearest roex center loses only a little power.
    assert strongest(same)["target_power_dbfs"] == pytest.approx(10 * np.log10(0.1 ** 2 / 2), abs=1.2)
    assert same["windows"][0]["competition_fraction"] > 0.99
    sf.write(args["competitors"][0]["path"], tone(4000, 0.4), 16000, subtype="FLOAT")
    separated = analyze_masking(args)
    assert separated["windows"][0]["competition_fraction"] < 0.01
    # Float WAV quantization/Hann leakage can leave tiny, nonzero residuals.
    assert strongest(separated)["competitor_power_dbfs"] is None or strongest(separated)["competitor_power_dbfs"] < -100
    json.dumps(separated, allow_nan=False)


def test_disjoint_time_and_intervals(tmp_path):
    target = tone()
    masker = tone(amplitude=0.4)
    target[3200:] = 0
    masker[:3200] = 0
    report = analyze_masking(request(tmp_path, target, [masker]))
    assert report["active_target_windows"] == 2
    assert report["inactive_target_windows"] == 2
    assert report["competition_intervals"] == []
    assert report["windows"][2]["competition_fraction"] is None


def test_relative_gain_changes_ratio_without_normalization(tmp_path):
    args = request(tmp_path)
    original = analyze_masking(args)
    args["target"]["gain_db"] = 18
    changed = analyze_masking(args)
    assert strongest(changed)["target_to_competitor_db"] - strongest(original)["target_to_competitor_db"] == pytest.approx(18, abs=0.002)
    assert changed["windows"][0]["competition_fraction"] == 0
    assert strongest(changed)["competitor_power_dbfs"] == strongest(original)["competitor_power_dbfs"]
    assert strongest(changed)["original_target_power_dbfs"] == strongest(original)["target_power_dbfs"]
    assert strongest(changed)["original_target_to_competitor_db"] == strongest(original)["target_to_competitor_db"]
    args["competitors"][0]["gain_db"] = -6
    adjusted = strongest(analyze_masking(args))
    assert adjusted["target_to_competitor_db"] - strongest(changed)["target_to_competitor_db"] == pytest.approx(6, abs=0.002)
    assert adjusted["contributors"][0]["original_power_dbfs"] == strongest(original)["contributors"][0]["power_dbfs"]


def test_silence_and_antiphase_stereo(tmp_path):
    mono = tone()
    stereo = np.column_stack([mono, -mono])
    report = analyze_masking(request(tmp_path, stereo, [stereo * 4]))
    assert report["active_target_windows"] == 4
    assert strongest(report)["target_to_competitor_db"] == pytest.approx(-12.041, abs=0.02)
    zero = np.zeros_like(stereo)
    silent = analyze_masking(request(tmp_path, zero, [zero]))
    assert silent["active_target_windows"] == 0
    assert all(w["strongest_target_bands"] == [] for w in silent["windows"])
    json.dumps(silent, allow_nan=False)


def test_multiple_competitors_attributed_by_power(tmp_path):
    report = analyze_masking(request(tmp_path, competitors=[tone(amplitude=0.2), tone(amplitude=0.4)]))
    band = strongest(report)
    assert [c["share"] for c in band["contributors"]] == pytest.approx([0.2, 0.8])
    assert band["target_to_competitor_db"] == pytest.approx(-13.0103, abs=0.02)
    assert report["competition_intervals"] == [{"start_seconds": 0.0, "end_seconds": 0.4}]


@pytest.mark.parametrize("change", [
    {"alignment": {}}, {"alignment": {"verified": False, "source": "same duration", "uncertainty_samples": 0}},
    {"alignment": {"verified": True, "source": "raw capture", "uncertainty_samples": 1}},
    {"alignment": {"verified": True, "source": "", "uncertainty_samples": 0}},
    {"provenance": {"disjoint_contributions": False, "in_mix_levels": True, "signal_path": "group and child"}},
    {"provenance": {"disjoint_contributions": True, "in_mix_levels": False, "signal_path": "isolated taps"}},
    {"window_seconds": float("nan")}, {"window_seconds": 0.01}, {"max_windows": True}, {"max_windows": 121},
    {"unknown": 1}, {"competitors": []}, {"competitors": [None] * 9},
])
def test_contract_refusals(tmp_path, change):
    args = request(tmp_path)
    args.update(change)
    with pytest.raises(ValueError):
        analyze_masking(args)


def test_offsets_align_known_leading_frames_and_expose_tail(tmp_path):
    args = request(tmp_path, tone(duration=0.45), [np.concatenate([np.zeros(1600), tone(amplitude=0.4, duration=0.45)])])
    with pytest.raises(ValueError, match="frame lengths"):
        analyze_masking(args)
    args["alignment"]["offsets_samples"] = {"source0": 0, "source1": 1600}
    report = analyze_masking(args)
    assert report["common_duration_seconds"] == 0.45
    assert report["unmeasured_tail_seconds"] == 0.05
    assert strongest(report)["target_to_competitor_db"] == pytest.approx(-12.041, abs=0.02)
    args["alignment"]["offsets_samples"]["source1"] = -1
    with pytest.raises(ValueError, match="indices"):
        analyze_masking(args)


def test_rate_layout_duplicate_nonfinite_and_window_boundaries(tmp_path):
    args = request(tmp_path)
    path = args["competitors"][0]["path"]
    sf.write(path, tone(), 8000, subtype="FLOAT")
    with pytest.raises(ValueError, match="sample rate"):
        analyze_masking(args)
    sf.write(path, np.column_stack([tone(), tone()]), 16000, subtype="FLOAT")
    with pytest.raises(ValueError, match="channel layout"):
        analyze_masking(args)
    sf.write(path, np.full(6400, np.nan), 16000, subtype="FLOAT")
    with pytest.raises(ValueError, match="nonfinite"):
        analyze_masking(args)
    duplicate = copy.deepcopy(args)
    duplicate["competitors"][0]["path"] = duplicate["target"]["path"]
    with pytest.raises(ValueError, match="same WAV"):
        analyze_masking(duplicate)
    args["max_windows"] = 2
    with pytest.raises(ValueError, match="window budget"):
        analyze_masking(args)


def test_preallocation_sample_budget_and_corrupt_container(tmp_path, monkeypatch):
    args = request(tmp_path)
    monkeypatch.setattr("audio_masking.MAX_SAMPLES", 100)
    with pytest.raises(ValueError, match="sample/duration budget"):
        analyze_masking(args)
    monkeypatch.setattr("audio_masking.MAX_SAMPLES", 12_000_000)
    monkeypatch.setattr("audio_masking.MAX_TOTAL_SAMPLES", 100)
    with pytest.raises(ValueError, match="total sample budget"):
        analyze_masking(args)
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not wave")
    args["target"]["path"] = str(bad)
    with pytest.raises(ValueError, match="RIFF"):
        analyze_masking(args)


def test_endpoint_impulse_inactivity_is_not_reported_as_literal_silence(tmp_path):
    impulse = np.zeros(1600)
    impulse[0] = 0.5
    report = analyze_masking(request(tmp_path, impulse, [np.zeros(1600)]))
    assert np.count_nonzero(impulse) == 1
    assert report["inactive_target_windows"] == 1
    assert "silent_target_windows" not in report
    assert "not literal WAV silence" in report["method"]["target_active"]
    assert any("endpoint" in limitation for limitation in report["limitations"])
    impulse[0], impulse[800] = 0, 0.5
    middle = analyze_masking(request(tmp_path, impulse, [np.zeros(1600)]))
    assert middle["active_target_windows"] == 1


def test_high_frequency_content_has_explicit_finite_filter_coverage(tmp_path):
    report = analyze_masking(request(tmp_path, tone(20000, rate=48000),
        [np.zeros(19200)], rate=48000))
    coverage = report["method"]["frequency_coverage"]
    assert coverage["first_center_hz"] == pytest.approx(50)
    assert 14000 < coverage["last_center_hz"] < 16000
    assert coverage["intended_center_region_hz"] == [50, 16000]
    assert coverage["center_count"] > 30
    assert coverage["center_step_erb"] == 1
    assert coverage["upper_center_bound_exclusive"] is True
    assert "tails" in coverage["filter_support"]
    assert "full-Nyquist" in coverage["filter_support"]
    # High out-of-center-range audio can still excite tails; it is not a brickwall.
    assert report["active_target_windows"] > 0
    assert strongest(report)["center_hz"] < 16000


def test_iso_model1_threshold_external_reference_vectors():
    """Hand-evaluated independent TwoLAME psycho_1.c threshold oracle.

    Source: https://github.com/Distrotech/twolame/blob/master/libtwolame/psycho_1.c
    psycho_1_threshold, L=60 dB SPL and z=8 Bark, not fitted to our output.
    These validate all four branches, masking type and support boundaries.
    """
    from audio_masking import _individual_threshold, _ath
    dz = np.array([-3, -1, -0.5, 0, 0.5, 1, 2, 7, 8])
    tonal = _individual_threshold(60, 8, 8 + dz, True, np)
    assert tonal[:-1] == pytest.approx([-12.225, 21.775, 36.775, 51.775, 43.275, 34.775, 26.775, -13.225])
    assert np.isneginf(tonal[-1])
    assert float(_individual_threshold(60, 8, 8, False, np)) == pytest.approx(56.575)
    # Terhardt's published quiet-threshold approximation: roughly 3.37 dB at 1 kHz.
    assert float(_ath(1000, np)) == pytest.approx(3.37, abs=0.01)


def test_perceptual_masking_same_vs_separated_and_gain(tmp_path):
    args = request(tmp_path, tone(amplitude=0.01), [tone(amplitude=0.4)])
    args["listening_condition"] = {"kind": "assumed", "db_spl_at_0_dbfs_rms": 100, "source": "Explicit hypothetical reference, not calibrated monitors"}
    same = analyze_masking(args)
    estimate = same["windows"][0]["perceptual_estimate"]
    tone_component = min(estimate["components"], key=lambda c: abs(c["frequency_hz"] - 1000))
    # Independent acoustic calibration: A=.01 sine has RMS=.01/sqrt(2),
    # so its level is -43.0103 dBFS + explicit 100 dB SPL RMS reference.
    assert tone_component["target_level_db_spl"] == pytest.approx(56.9897, abs=0.01)
    assert tone_component["type"] == "tonal"
    assert tone_component["margin_db"] < 0
    assert tone_component["contributors"][0]["share_of_masker_threshold"] == 1
    sf.write(args["competitors"][0]["path"], tone(4000, amplitude=0.4), 16000, subtype="FLOAT")
    separated = analyze_masking(args)["windows"][0]["perceptual_estimate"]
    assert separated["above_threshold_power_fraction"] > estimate["above_threshold_power_fraction"]
    args["target"]["gain_db"] = 12
    gained = analyze_masking(args)
    original = gained["windows"][0]["original_perceptual_estimate"]
    changed = gained["windows"][0]["perceptual_estimate"]
    before = min(original["components"], key=lambda c: abs(c["frequency_hz"] - 1000))
    after = min(changed["components"], key=lambda c: abs(c["frequency_hz"] - 1000))
    assert after["target_level_db_spl"] - before["target_level_db_spl"] == pytest.approx(12, abs=0.002)
    assert changed["threshold_excess_power_fraction"] >= original["threshold_excess_power_fraction"]
    json.dumps(gained, allow_nan=False)


def test_explicit_listening_condition_and_section_coverage(tmp_path):
    args = request(tmp_path)
    assert analyze_masking(args)["perceptual_model"]["status"] == "unavailable"
    args["listening_condition"] = {"kind": "assumed", "db_spl_at_0_dbfs_rms": 100, "source": "hypothetical"}
    args["sections"] = [{"name": "first", "start_seconds": 0.05, "end_seconds": 0.35}]
    assert analyze_masking(args)["sections"][0]["covered_windows"] == 2
    args["listening_condition"]["db_spl_at_0_dbfs_rms"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        analyze_masking(args)


def test_sub_millidecibel_threshold_classification_uses_unrounded_margin(tmp_path):
    from audio_masking import _ath
    # Bin-centered tone power is A^2/2. Place it 0.0004 dB above the
    # independent Terhardt ATH, accounting for Hann three-bin capture.
    rate, size = 16000, 1024
    amplitude = 0.1
    window = np.hanning(size)
    sample = amplitude * np.sin(2 * np.pi * 1000 * np.arange(size) / rate)
    spectrum = np.abs(np.fft.rfft(sample * window)) ** 2 / (size * np.sum(window ** 2))
    spectrum[1:-1] *= 2
    reference = float(_ath(1000, np)) - 10 * np.log10(np.sum(spectrum[63:66])) + 0.0004
    args = request(tmp_path, tone(amplitude=amplitude), [np.zeros(6400)])
    args["listening_condition"] = {"kind": "assumed", "db_spl_at_0_dbfs_rms": reference, "source": "explicit boundary test"}
    report = analyze_masking(args)
    estimate = report["windows"][0]["perceptual_estimate"]
    assert estimate["components"][0]["margin_db"] == 0
    assert estimate["components"][0]["estimate"] == "above_threshold"
    assert estimate["above_threshold_component_count"] == 1
    assert estimate["above_threshold_power_fraction"] == 1
    assert report["modeled_masking_summary"]["all_active_components_below_threshold_intervals"] == []
    assert report["modeled_masking_summary"]["affected_frequency_regions"] == []
