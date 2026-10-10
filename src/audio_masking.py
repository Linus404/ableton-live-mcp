"""Bounded offline auditory-filter competition evidence, never an audibility verdict."""
from __future__ import annotations

import math
from pathlib import Path

from audio_capture import validate_wav

MAX_SAMPLES = 12_000_000
MAX_TOTAL_SAMPLES = 48_000_000
MAX_WINDOWS = 120
POWER_FLOOR = 1e-20


def _model_power(data, np):
    size = 1024
    if len(data) < size:
        return None
    starts = list(range(0, len(data) - size + 1, 512))
    if starts[-1] != len(data) - size:
        starts.append(len(data) - size)
    window = np.hanning(size)
    power = sum(np.abs(np.fft.rfft(data[pos:pos + size] * window[:, None], axis=0)) ** 2 for pos in starts)
    power /= len(starts) * size * np.sum(window ** 2)
    power[1:-1] *= 2
    return power


def _listening_condition(value):
    if not isinstance(value, dict) or set(value) != {"kind", "db_spl_at_0_dbfs_rms", "source"}:
        raise ValueError("listening_condition requires kind, db_spl_at_0_dbfs_rms and source")
    if value["kind"] not in ("calibrated", "assumed"):
        raise ValueError("listening_condition.kind must be calibrated or assumed")
    _number(value["db_spl_at_0_dbfs_rms"], "db_spl_at_0_dbfs_rms", 0, 140)
    _text(value["source"], "listening_condition.source")
    return value


def _bark(frequency, np):
    return 13 * np.arctan(0.00076 * frequency) + 3.5 * np.arctan((frequency / 7500) ** 2)


def _ath(frequency, np):
    """Terhardt quiet threshold approximation, dB SPL (not a dBFS curve)."""
    khz = np.maximum(frequency / 1000, 0.02)
    return 3.64 * khz ** -0.8 - 6.5 * np.exp(-0.6 * (khz - 3.3) ** 2) + 0.001 * khz ** 4


def _individual_threshold(level, masker_bark, receiver_bark, tonal, np):
    """ISO MPEG Model 1 spread and tonal/noise masking index, in dB SPL.

    Equations checked independently against TwoLAME psycho_1_threshold;
    no encoder bit-rate-dependent ATH reduction is used for listening analysis.
    """
    dz = receiver_bark - masker_bark
    spread = np.select([dz < -1, dz < 0, dz < 1],
        [17 * (dz + 1) - (0.4 * level + 6), (0.4 * level + 6) * dz, -17 * dz],
        default=-(dz - 1) * (17 - 0.15 * level) - 17)
    index = -1.525 - (0.275 if tonal else 0.175) * masker_bark - (4.5 if tonal else 0.5)
    return np.where((dz >= -3) & (dz < 8), level + index + spread, -np.inf)


def _maskers(power, frequencies, reference, np):
    """1024-bin Model-1-style tonal peaks; residual noise in one-Bark bands."""
    bark = _bark(frequencies, np)
    levels = 10 * np.log10(np.maximum(power, POWER_FLOOR)) + reference
    remaining = power.copy()
    tonal = []
    for k in range(2, len(power) - 12):
        run = 2 if k < 63 else 3 if k < 127 else 6 if k < 255 else 12
        if levels[k] <= levels[k - 1] or levels[k] < levels[k + 1]:
            continue
        neighbours = [levels[k - j] for j in range(2, run + 1)] + [levels[k + j] for j in range(2, run + 1)]
        if levels[k] - max(neighbours) < 7:
            continue
        p = float(np.sum(power[k - 1:k + 2]))
        level = 10 * math.log10(max(p, POWER_FLOOR)) + reference
        if level >= float(_ath(frequencies[k], np)):
            tonal.append((float(frequencies[k]), float(bark[k]), level, True, p))
        remaining[k - run:k + run + 1] = 0
    # Keep strongest tonal component inside a 0.5-Bark neighbourhood.
    retained = []
    for item in sorted(tonal, key=lambda item: item[2], reverse=True):
        if all(abs(item[1] - other[1]) >= 0.5 for other in retained):
            retained.append(item)
    for band in range(25):
        select = (bark >= band) & (bark < band + 1) & (frequencies >= 20)
        p = float(np.sum(remaining[select]))
        if p <= POWER_FLOOR:
            continue
        f = float(np.exp(np.sum(remaining[select] * np.log(frequencies[select])) / p))
        level = 10 * math.log10(p) + reference
        if level >= float(_ath(f, np)):
            retained.append((f, float(_bark(f, np)), level, False, p))
    return retained


def _perceptual_window(source_power, frequencies, gains, condition, names, np):
    """Independent channel estimates, never a binaural unmasking claim."""
    reference = condition["db_spl_at_0_dbfs_rms"]
    components = []
    total_power = surviving = excess = 0.0
    for channel in range(source_power.shape[2]):
        maskers = [_maskers(p[:, channel] * 10 ** (g / 10), frequencies, reference, np)
                   for p, g in zip(source_power, gains)]
        for f, z, level, tonal, p in maskers[0]:
            contributions = []
            for name, source in zip(names[1:], maskers[1:]):
                threshold_power = sum(10 ** (float(_individual_threshold(l, b, z, t, np)) / 10)
                                      for _, b, l, t, _ in source)
                contributions.append((name, threshold_power))
            quiet = 10 ** (float(_ath(f, np)) / 10)
            masking = sum(v for _, v in contributions)
            threshold = 10 * math.log10(quiet + masking)
            margin = level - threshold
            excess_p = max(0, p - (quiet + masking) / 10 ** (reference / 10))
            total_power += p
            surviving += p if margin > 0 else 0
            excess += excess_p
            components.append({"frequency_hz": round(f, 2), "bark": round(z, 3), "channel": channel,
                "type": "tonal" if tonal else "noise", "target_level_db_spl": round(level, 3),
                "quiet_threshold_db_spl": round(10 * math.log10(quiet), 3),
                "masking_threshold_db_spl": round(threshold, 3), "margin_db": round(margin, 3),
                "estimate": "above_threshold" if margin > 0 else "below_threshold",
                "contributors": [{"name": name, "threshold_db_spl": round(10 * math.log10(v), 3) if v > 0 else None,
                    "share_of_masker_threshold": round(v / masking, 4) if masking > 0 else None}
                    for name, v in contributions]})
    return {"components": components, "active_component_count": len(components),
        "above_threshold_component_count": sum(c["estimate"] == "above_threshold" for c in components),
        "above_threshold_power_fraction": round(surviving / total_power, 5) if total_power else None,
        "threshold_excess_power_fraction": round(excess / total_power, 5) if total_power else None,
        "threshold_excess_dbfs": _db(excess / source_power.shape[2]),
        "status": "modeled" if total_power else "no_components_above_quiet_threshold"}


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and between {low} and {high}")
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024:
        raise ValueError(f"{name} must be a nonempty string of at most 1024 characters")
    return value


def _db(power):
    return round(10 * math.log10(power), 3) if power > POWER_FLOOR else None


def analyze_masking(args, *, frame_limit=None, spectral_cache=None, allow_no_competitors=False):
    """Measure declared aligned, disjoint in-mix WAV contributions.

    Offsets are nonnegative file frame indices at common time zero, NOT delays to
    infer. Only zero-uncertainty verified alignment is supported. Invalid or
    unsupported input raises ValueError; missing dependencies raise RuntimeError.
    """
    keys = {"target", "competitors", "alignment", "provenance", "window_seconds", "max_windows", "listening_condition", "sections"}
    if not isinstance(args, dict) or set(args) - keys:
        raise ValueError("unknown masking argument or non-object arguments")
    condition = _listening_condition(args["listening_condition"]) if "listening_condition" in args else None
    sections = args.get("sections", [])
    if not isinstance(sections, list) or len(sections) > 32:
        raise ValueError("sections must contain at most 32 entries")
    section_names = set()
    for section in sections:
        if not isinstance(section, dict) or set(section) != {"name", "start_seconds", "end_seconds"}:
            raise ValueError("sections require name, start_seconds, end_seconds")
        name = _text(section["name"], "section.name")
        if name in section_names:
            raise ValueError("section names must be unique")
        section_names.add(name)
        start = _number(section["start_seconds"], "section.start_seconds", 0, 120)
        end = _number(section["end_seconds"], "section.end_seconds", 0, 120)
        if end <= start:
            raise ValueError("section end must follow start")
    alignment = args.get("alignment")
    if not isinstance(alignment, dict) or set(alignment) - {"verified", "source", "uncertainty_samples", "offsets_samples"}:
        raise ValueError("alignment requires explicit verified source and uncertainty_samples")
    if alignment.get("verified") is not True or alignment.get("uncertainty_samples") != 0 or isinstance(alignment.get("uncertainty_samples"), bool):
        raise ValueError("unsupported: alignment must be verified with zero sample uncertainty")
    _text(alignment.get("source"), "alignment.source")
    provenance = args.get("provenance")
    if not isinstance(provenance, dict) or set(provenance) != {"disjoint_contributions", "in_mix_levels", "signal_path"}:
        raise ValueError("provenance requires disjoint_contributions, in_mix_levels and signal_path")
    if provenance["disjoint_contributions"] is not True or provenance["in_mix_levels"] is not True:
        raise ValueError("unsupported: overlapping paths or isolated pre-mixer levels cannot establish in-mix competition")
    _text(provenance["signal_path"], "provenance.signal_path")
    competitors = args.get("competitors")
    if not isinstance(competitors, list) or not (0 if allow_no_competitors else 1) <= len(competitors) <= 8:
        raise ValueError("competitors must contain 1 to 8 named WAVs")
    entries = [args.get("target"), *competitors]
    names, paths, gains, metadata = [], [], [], []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"name", "path", "gain_db"}:
            raise ValueError("sources require name, path and optional gain_db")
        name = _text(entry.get("name"), "source.name")
        if len(name) > 128 or name in names:
            raise ValueError("source names must be unique and at most 128 characters")
        path = Path(_text(entry.get("path"), "source.path")).resolve()
        if path in paths:
            raise ValueError("disjoint contributions cannot reuse the same WAV path")
        gain = _number(entry.get("gain_db", 0), "gain_db", -60, 60)
        # Bound container size before scanning chunks or allocating decoded audio.
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("WAV exceeds file byte budget")
        info = validate_wav(path)
        if info["channels"] not in (1, 2) or not 8000 <= info["sample_rate"] <= 192000:
            raise ValueError("only mono/stereo WAVs at 8000..192000 Hz supported")
        if info["frames"] * info["channels"] > MAX_SAMPLES or info["duration_seconds"] > 120:
            raise ValueError("WAV exceeds sample/duration budget")
        names.append(name)
        paths.append(path)
        gains.append(gain)
        metadata.append(info)
    if sum(m["frames"] * m["channels"] for m in metadata) > MAX_TOTAL_SAMPLES:
        raise ValueError("WAVs exceed total sample budget")
    rate, channels = metadata[0]["sample_rate"], metadata[0]["channels"]
    if any((m["sample_rate"], m["channels"]) != (rate, channels) for m in metadata):
        raise ValueError("sources must have identical sample rate and channel layout; no resampling inferred")
    offsets = alignment.get("offsets_samples")
    if offsets is None:
        if len({m["frames"] for m in metadata}) != 1:
            raise ValueError("equal frame lengths required without explicit offsets_samples")
        offsets = dict.fromkeys(names, 0)
    if not isinstance(offsets, dict) or set(offsets) != set(names):
        raise ValueError("offsets_samples must map every source name to a file frame index")
    for name, m in zip(names, metadata):
        if isinstance(offsets[name], bool) or not isinstance(offsets[name], int) or not 0 <= offsets[name] < m["frames"]:
            raise ValueError("offsets_samples must be nonnegative integer indices inside each file")
    frames = min(m["frames"] - offsets[name] for name, m in zip(names, metadata))
    if frame_limit is not None:
        if isinstance(frame_limit, bool) or not isinstance(frame_limit, int) or frame_limit <= 0:
            raise ValueError("internal frame_limit must be a positive integer")
        frames = min(frames, frame_limit)
    if any(s["end_seconds"] > frames / rate for s in sections):
        raise ValueError("section exceeds common interval")
    width = round(_number(args.get("window_seconds", 0.1), "window_seconds", 0.1, 1) * rate)
    limit = args.get("max_windows", MAX_WINDOWS)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_WINDOWS:
        raise ValueError("max_windows must be an integer from 1 to 120")
    count = math.ceil(frames / width)
    if count > limit or frames < round(0.1 * rate):
        raise ValueError("common interval too short or exceeds window budget; choose larger window_seconds")
    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError('Install audio analysis with: python -m pip install -e ".[audio-analysis]"') from exc
    # One ERB-rate step per filter, restricted to a useful speech/music range.
    erb_rate = lambda hz: 21.4 * np.log10(1 + 0.00437 * hz)
    centers = (10 ** (np.arange(erb_rate(50), erb_rate(min(16000, rate / 2)), 1) / 21.4) - 1) / 0.00437
    bandwidths = 24.7 * (1 + 0.00437 * centers)
    if frames * len(entries) * len(centers) / 2 > 300_000_000:
        raise ValueError("analysis exceeds filter computation budget")
    kernels = {}
    spectra = []
    model_spectra = []
    model_frequencies = np.fft.rfftfreq(1024, 1 / rate)
    for path, m, name, gain in zip(paths, metadata, names, gains):
        stat = path.stat()
        cache_key = (str(path), stat.st_mtime_ns, stat.st_size, offsets[name], frames, width, bool(condition))
        if spectral_cache is not None and cache_key in spectral_cache:
            original_powers, original_model_powers = spectral_cache[cache_key]
            spectra.append(original_powers * 10 ** (gain / 10))
            model_spectra.append(original_model_powers)
            continue
        powers = []
        model_powers = []
        with sf.SoundFile(str(path)) as handle:
            if (handle.frames, handle.samplerate, handle.channels) != (m["frames"], rate, channels):
                raise ValueError("decoder and WAV metadata disagree")
            handle.seek(offsets[name])
            for index in range(count):
                length = min(width, frames - index * width)
                data = handle.read(length, dtype="float64", always_2d=True)
                if len(data) != length or not np.isfinite(data).all() or np.max(np.abs(data)) > 1e6:
                    raise ValueError("WAV truncated, changed, nonfinite or unreasonably large")
                if length < round(0.1 * rate):
                    # Short tail remains explicitly unmeasured, not padded into evidence.
                    break
                if condition:
                    # Average overlapping short-frame spectra, not a single long FFT.
                    # A final edge-aligned frame covers the end; subframe variability
                    # is not represented by the stationary-window estimate.
                    bins = _model_power(data, np)
                    if bins is None:
                        raise ValueError("perceptual model requires at least 1024 samples per window")
                    model_powers.append(bins)
                if length not in kernels:
                    window = np.hanning(length)
                    frequencies = np.fft.rfftfreq(length, 1 / rate)
                    g = np.abs(frequencies[None, :] - centers[:, None]) / centers[:, None]
                    pg = (4 * centers / bandwidths)[:, None] * g
                    kernels[length] = (window, (1 + pg) * np.exp(-pg))
                window, weights = kernels[length]
                fft = np.fft.rfft(data * window[:, None], axis=0)
                power = np.mean(np.abs(fft) ** 2, axis=1) / (length * np.sum(window ** 2))
                power[1:-1 if length % 2 == 0 else None] *= 2
                powers.append(weights @ power)
        original_powers, original_model_powers = np.asarray(powers), np.asarray(model_powers)
        if spectral_cache is not None:
            spectral_cache[cache_key] = (original_powers, original_model_powers)
        spectra.append(original_powers * 10 ** (gain / 10))
        model_spectra.append(original_model_powers)
    target = spectra[0]
    others = np.asarray(spectra[1:]) if len(spectra) > 1 else np.zeros((0, *target.shape))
    combined = np.sum(others, axis=0)
    windows, intervals = [], []
    active_count = 0
    for index, (t, c) in enumerate(zip(target, combined)):
        active = t > max(POWER_FLOOR, float(np.max(t)) * 1e-8)
        active_count += int(np.any(active))
        fraction = float(np.sum(t[active & (c >= t)]) / np.sum(t[active])) if np.any(active) else None
        bands = []
        for band in np.argsort(t)[::-1][:3]:
            if not active[band]:
                continue
            contribution = others[:, index, band]
            original_target = float(t[band]) / 10 ** (gains[0] / 10)
            original_contributions = [float(p) / 10 ** (gain / 10) for p, gain in zip(contribution, gains[1:])]
            original_competitor = sum(original_contributions)
            bands.append({"center_hz": round(float(centers[band]), 2), "erb_hz": round(float(bandwidths[band]), 2),
                "target_power_dbfs": _db(float(t[band])), "competitor_power_dbfs": _db(float(c[band])),
                "original_target_power_dbfs": _db(original_target), "original_competitor_power_dbfs": _db(original_competitor),
                "original_target_to_competitor_db": round(10 * math.log10(original_target / original_competitor), 3) if original_competitor > POWER_FLOOR else None,
                "target_to_competitor_db": round(10 * math.log10(float(t[band] / c[band])), 3) if c[band] > POWER_FLOOR else None,
                "contributors": [{"name": name, "power_dbfs": _db(float(p)),
                    "original_power_dbfs": _db(original),
                    "share": round(float(p / c[band]), 4) if c[band] > POWER_FLOOR else None}
                    for name, p, original in zip(names[1:], contribution, original_contributions)]})
        start, end = index * width / rate, min((index + 1) * width, frames) / rate
        windows.append({"start_seconds": round(start, 6), "end_seconds": round(end, 6),
            "target_active": bool(np.any(active)), "competitors_active": bool(np.any(c > POWER_FLOOR)),
             "competition_fraction": round(fraction, 4) if fraction is not None else None, "strongest_target_bands": bands})
        if condition:
            source_power = np.asarray([s[index] for s in model_spectra])
            windows[-1]["perceptual_estimate"] = _perceptual_window(source_power, model_frequencies, gains, condition, names, np)
            if any(gains):
                windows[-1]["original_perceptual_estimate"] = _perceptual_window(source_power, model_frequencies, [0] * len(gains), condition, names, np)
        if fraction is not None and fraction >= 0.5:
            if intervals and intervals[-1]["end_seconds"] == round(start, 6):
                intervals[-1]["end_seconds"] = round(end, 6)
            else:
                intervals.append({"start_seconds": round(start, 6), "end_seconds": round(end, 6)})
    report = {"schema_version": 2, "complete": len(windows) == count, "outcome": "measured_competition_proxy",
        "alignment": alignment, "provenance": provenance,
        "sources": [{"name": n, "path": str(p), "gain_db": g, "offset_samples": offsets[n], "wav": m}
                    for n, p, g, m in zip(names, paths, gains, metadata)],
        "sample_rate": rate, "channels": channels, "common_duration_seconds": round(frames / rate, 6),
        "coverage": {"status": "partial_short_tail" if len(windows) < count else "full_common_interval",
            "analyzed_duration_seconds": windows[-1]["end_seconds"], "contiguous": True,
            "time_basis": "Seconds from caller-declared common time zero, not Arrangement time",
            "alignment_verification": "caller-declared; not independently verified"},
        "unmeasured_tail_seconds": round((frames - len(windows) * width) / rate, 6) if len(windows) < count else 0,
        "active_target_windows": active_count, "inactive_target_windows": len(windows) - active_count,
        "competition_intervals": intervals, "windows": windows,
        "method": {"filter": "Symmetric roex(p): (1+p*g)*exp(-p*g), p=4*fc/ERB; ERB=24.7*(1+0.00437*fc)",
            "frequency_coverage": {"center_count": len(centers),
                "center_step_erb": 1,
                "first_center_hz": round(float(centers[0]), 6), "last_center_hz": round(float(centers[-1]), 6),
                "intended_center_region_hz": [50, min(16000, rate / 2)],
                "upper_center_bound_exclusive": True,
                "filter_support": "roex tails, not hard frequency cutoffs; no uniformly covered full-Nyquist spectrum"},
            "target_active": "At least one Hann-weighted modeled-filter power exceeds max(1e-20, peak target filter power * 1e-8); inactivity is not literal WAV silence",
            "power": "Hann-window corrected one-sided FFT powers integrated through roex filters; channel mean power, unit mean-square = 0 dBFS",
            "gains": "Explicit gain_db is an offline relative-level scenario, not loudness matching or a Live mutation; original_* powers/ratios retain unadjusted WAV evidence",
            "competition_fraction": "Fraction of active target filter excitation with summed competitor excitation >= target; conservative energy-competition proxy, NOT probability of inaudibility",
            "interval_rule": "Adjacent sampled windows with competition_fraction >= 0.5; descriptive, not an audibility threshold",
            "numerical_floor_power": POWER_FLOOR, "relative_target_filter_floor_db": -80,
            "null_ratios": "competitor excitation at or below numerical floor; not infinite measured audibility",
            "references": ["Glasberg & Moore (1990), Derivation of auditory filter shapes from notched-noise data, Hearing Research 47:103-138, doi:10.1016/0378-5955(90)90170-T",
                "Patterson et al. (1982), The deterioration of hearing with age: Frequency selectivity, the critical ratio, the audiogram, and speech threshold, JASA 72:1788-1803, doi:10.1121/1.388652"]},
        "limitations": ["Caller declarations are preserved, not independently verified. Raw uncalibrated capture and isolated pre-mixer taps do not satisfy this contract.",
            "Competitor powers sum incoherently, not waveform mixing; correlations/interference and shared processing can change actual mix excitation.",
            "No absolute SPL calibration, hearing threshold, binaural/spatial unmasking, tonal/noise distinction, temporal masking, listener model or audibility verdict.",
            "Filter overlap is intentional. Competition fraction is excitation-weighted, not a fraction of independent physical energy bands.",
            "Only three strongest target filters are listed per window; competition_fraction uses all active filters. Hann weighting can underrepresent edge transients.",
            "An impulse at a Hann window endpoint has zero weight: inactive_target_windows describes modeled-filter inactivity, not literal silence or absence of audible content.",
            "Filter centers cover only the reported range below min(16 kHz, Nyquist); roex tails are not hard cutoffs and out-of-range content is not uniformly assessed.",
            "Negative ratios or spectral competition do not prove inaudibility or musical undesirability; no human approval or universal quality judgement.",
             "Analysis covers the common remaining interval after explicit offsets; extra frames outside it and tails shorter than 100 ms are not analyzed."]}
    report["perceptual_model"] = {"status": "unavailable", "reason": "Supply an explicit calibrated or assumed listening_condition for absolute hearing thresholds"}
    if condition:
        report["outcome"] = "measured_evidence_and_modeled_masking"
        report["listening_condition"] = condition
        report["perceptual_model"] = {"status": "estimated", "name": "MPEG Model 1 adapted simultaneous masking",
            "reference": "ISO/IEC 11172-3 Model 1; threshold equations checked against TwoLAME libtwolame/psycho_1.c psycho_1_threshold",
            "ath_reference": "Terhardt (1979), Calculating virtual pitch, Hearing Research 1:155-182; 3.64*f_kHz^-0.8 - 6.5*exp(-0.6*(f_kHz-3.3)^2) + 0.001*f_kHz^4",
            "fft_size": 1024, "fft_hop": 512, "frequency_bin_hz": rate / 1024,
            "frequency_coverage": {"noise_components": "20 Hz to min(Nyquist, 25 Bark), continuous one-Bark grouping",
                "tonal_candidate_bin_indices": [2, 500], "nyquist_hz": rate / 2,
                "resolution_limit": "Peak search omits first two and last twelve FFT bins; remaining power may enter residual noise groups"},
            "adaptations": ["Stationary window averages of power-corrected short Hann spectra; arbitrary sample rates, continuous Bark conversion and one-Bark residual noise groups instead of ISO sample-rate tables.",
                "Each disjoint competitor classified separately; individual threshold powers sum incoherently. Not a bit-exact MPEG encoder or standardized partial-loudness implementation.",
                "Separate channel estimates; no binaural/spatial unmasking. Components below quiet threshold excluded from activity."],
            "prominence": "Threshold-excess target power and surviving component power fractions are model-derived spectral prominence indicators, NOT sones, partial loudness, probability of audibility, or isolated LUFS ranking",
            "fraction_denominator": "Power of retained modeled target components above quiet threshold, across channels; not all physical target energy. Removed neighbouring tonal bins, quiet components and unsupported frequency regions are excluded.",
            "units": "SPL = spectral mean-square dBFS + declared db_spl_at_0_dbfs_rms; reference applies per channel; no encoder normalization or implicit 96 dB reference",
            "judgment": "Above/below modeled threshold only; no human audible/buried verdict or musical quality score"}
        report["limitations"] = [s for s in report["limitations"] if not s.startswith("No absolute SPL")]
        report["limitations"].extend(["Normal-hearing, stationary simultaneous-masker estimate; no temporal masking, attention, recognition, room/headphone transfer or individualized audiogram.",
            "Window averaging can hide brief exposed/covered events; 1024-bin resolution and adapted critical-band grouping limit precision. Estimates require listening experiments for human audibility claims.",
            "Assumed listening level is a counterfactual, not monitor calibration; per-source incoherent thresholds cannot reproduce correlated interference or shared nonlinear processing."])
        affected_intervals = []
        affected_bands = {}
        for w in windows:
            estimate = w["perceptual_estimate"]
            if estimate["active_component_count"] and not estimate["above_threshold_component_count"]:
                if affected_intervals and affected_intervals[-1]["end_seconds"] == w["start_seconds"]:
                    affected_intervals[-1]["end_seconds"] = w["end_seconds"]
                else:
                    affected_intervals.append({"start_seconds": w["start_seconds"], "end_seconds": w["end_seconds"]})
            covered_bands = set()
            for component in estimate["components"]:
                if component["estimate"] == "above_threshold":
                    continue
                band = int(component["bark"])
                if band not in affected_bands:
                    affected_bands[band] = {"bark_range": [band, band + 1], "windows": 0, "duration_seconds": 0,
                                           "minimum_margin_db": component["margin_db"], "affected_frequencies_hz": []}
                b = affected_bands[band]
                b["minimum_margin_db"] = min(b["minimum_margin_db"], component["margin_db"])
                b["affected_frequencies_hz"].append(component["frequency_hz"])
                if band not in covered_bands:
                    b["windows"] += 1
                    b["duration_seconds"] += w["end_seconds"] - w["start_seconds"]
                    covered_bands.add(band)
        for b in affected_bands.values():
            locations = b.pop("affected_frequencies_hz")
            b["affected_frequency_range_hz"] = [min(locations), max(locations)]
            b["duration_seconds"] = round(b["duration_seconds"], 6)
        report["modeled_masking_summary"] = {"all_active_components_below_threshold_intervals": affected_intervals,
            "affected_frequency_regions": list(affected_bands.values()),
            "interpretation": "Components below simultaneous masking-plus-quiet threshold; target quiet-threshold inactivity is separately reported, never counted as evidence of competitor masking"}
        report["sections"] = []
        for section in sections:
            selected = [w for w in windows if w["start_seconds"] >= section["start_seconds"] and w["end_seconds"] <= section["end_seconds"]]
            fractions = [w["perceptual_estimate"]["above_threshold_power_fraction"] for w in selected if w["perceptual_estimate"]["above_threshold_power_fraction"] is not None]
            report["sections"].append({**section, "covered_windows": len(selected), "analyzed_seconds": sum(w["end_seconds"] - w["start_seconds"] for w in selected),
                "mean_above_threshold_power_fraction": round(sum(fractions) / len(fractions), 5) if fractions else None,
                "fully_below_threshold_windows": sum(w["perceptual_estimate"]["active_component_count"] > 0 and w["perceptual_estimate"]["above_threshold_component_count"] == 0 for w in selected),
                "aggregation": "Unweighted mean of active complete-window fractions; section-edge partial windows excluded"})
    return report
