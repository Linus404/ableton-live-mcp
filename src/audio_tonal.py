"""Bounded offline tonal evidence, without universal EQ targets or Live access."""
from __future__ import annotations

import math
from pathlib import Path

from audio_analysis import _seconds, _finite, _measure
from audio_capture import validate_wav
from audio_masking import _text, _number

BANDS = (("sub", 20, 60), ("bass", 60, 250), ("low_mid", 250, 500),
         ("mid", 500, 2000), ("upper_mid", 2000, 6000), ("high", 6000, 20000))
MAX_WORK_SAMPLES = 96_000_000
ABSOLUTE_POWER_FLOOR = 1e-30
RELATIVE_POWER_FLOOR = 1e-24


def _power_db(power):
    return _finite(10 * math.log10(power)) if power > 0 else None


def _spectrum(data, rate, np, signal):
    """Welch density integrated by fractional overlap of FFT-bin cells."""
    if len(data) < round(rate * .25):
        return {"status": "insufficient_duration", "minimum_seconds": .25}
    size = round(rate * .25)
    hop = size - size // 2
    blocks = 1 + (len(data) - size) // hop
    covered_frames = size + (blocks - 1) * hop
    frequencies, density = signal.welch(data, fs=rate, window="hann", nperseg=size,
        noverlap=size // 2, detrend=False, scaling="density", axis=0)
    density = np.mean(density, axis=1)  # Power, not a phase-cancelling mono fold.
    df = rate / size
    # DC/Nyquist one-sided endpoint cells have half width; double density there
    # preserves scipy's bin-energy normalization while integrating clipped cells.
    density = density.copy()
    density[0] *= 2
    if size % 2 == 0:
        density[-1] *= 2
    lo = np.maximum(0, frequencies - df / 2)
    hi = np.minimum(rate / 2, frequencies + df / 2)

    def energy(low, high):
        widths = np.maximum(0, np.minimum(hi, high) - np.maximum(lo, low))
        return float(np.sum(density * widths))

    raw_total = energy(20, min(20000, rate / 2))
    original_power = float(np.mean(np.square(data)))
    floor = max(ABSOLUTE_POWER_FLOOR, original_power * RELATIVE_POWER_FLOOR)
    total = raw_total if raw_total > floor else 0
    upper_relative = math.ceil(10 * math.log10(min(1, floor / total)) * 1000) / 1000 if total > 0 else None
    bands = []
    for name, low, high in BANDS:
        covered = min(high, rate / 2)
        status = "full" if high <= rate / 2 else "partial" if low < rate / 2 else "unsupported"
        power = energy(low, covered) if status != "unsupported" else None
        if power is not None and power <= floor:
            power = 0
        bands.append({"name": name, "low_hz": low, "high_hz": high,
            "covered_high_hz": covered if status != "unsupported" else None, "coverage": status,
            "measurement_status": "unsupported" if power is None else "measured" if power > 0 and total > 0 else "below_numerical_floor",
            "power_dbfs": _power_db(power) if power is not None else None,
            "relative_db": _power_db(power / total) if power is not None and total > 0 else None,
            "upper_relative_db": upper_relative if power == 0 else None})
    octave = []
    for index in range(10):
        low, high = 20 * 2 ** index, min(20000, 40 * 2 ** index)
        covered = min(high, rate / 2)
        status = "full" if high <= rate / 2 else "partial" if low < rate / 2 else "unsupported"
        power = energy(low, covered) if status != "unsupported" else None
        if power is not None and power <= floor:
            power = 0
        octave.append({"low_hz": low, "high_hz": high, "coverage": status,
            "measurement_status": "unsupported" if power is None else "measured" if power > 0 and total > 0 else "below_numerical_floor",
            "relative_db": _power_db(power / total) if power is not None and total > 0 else None,
            "upper_relative_db": upper_relative if power == 0 else None})
    widths = np.maximum(0, np.minimum(hi, 20000) - np.maximum(lo, 20))
    weights = density * widths
    centroid = float(np.sum(frequencies * weights) / total) if total > 0 else None
    rolloff = float(frequencies[np.searchsorted(np.cumsum(weights), total * .85)]) if total > 0 else None
    peaks = []
    if total > 0:
        db = 10 * np.log10(np.maximum(density, np.finfo(float).tiny))
        indices, properties = signal.find_peaks(db, prominence=6)
        for index, prominence in zip(indices, properties["prominences"]):
            frequency = float(frequencies[index])
            if not 20 <= frequency <= min(20000, rate / 2):
                continue
            power = float(np.sum(weights[max(0, index - 1):index + 2]))
            if power / total < .0001:
                continue
            left, right = index, index
            while left > 0 and db[left - 1] >= db[index] - 3:
                left -= 1
            while right < len(db) - 1 and db[right + 1] >= db[index] - 3:
                right += 1
            peaks.append({"frequency_hz": round(frequency, 3), "prominence_db": _finite(prominence),
                "three_db_width_hz": round((right - left + 1) * df, 3),
                "three_bin_relative_db": _power_db(power / total)})
        peaks.sort(key=lambda p: p["three_bin_relative_db"], reverse=True)
    return {"status": "measured" if total > 0 else "silent_in_analyzed_band" if original_power == 0 else "below_numerical_floor",
        "raw_analyzed_power_dbfs": _power_db(raw_total), "numerical_power_floor_dbfs": _power_db(floor),
        "dc_power_dbfs": _power_db(float(np.mean(np.square(np.mean(data, axis=0))))),
        "welch_blocks": blocks, "covered_duration_seconds": round(covered_frames / rate, 6),
        "omitted_tail_seconds": round((len(data) - covered_frames) / rate, 6),
        "normalization_low_hz": 20, "normalization_high_hz": min(20000, rate / 2),
        "resolution_hz": round(df, 6), "analyzed_power_dbfs": _power_db(total),
        "bands": bands, "octave_bands": octave, "centroid_hz": _finite(centroid) if centroid is not None else None,
        "rolloff_85_hz": _finite(rolloff) if rolloff is not None else None, "spectral_peaks": peaks[:5]}


def _compare(measurement, reference):
    a, b = measurement.get("bands", []), reference.get("bands", [])
    common_normalization = [(v["coverage"], v["covered_high_hz"]) for v in a] == [(v["coverage"], v["covered_high_hz"]) for v in b]
    values = []
    for source_band, ref_band in zip(a, b):
        supported = common_normalization and source_band["coverage"] == ref_band["coverage"] == "full"
        left, right = source_band["relative_db"], ref_band["relative_db"]
        values.append({"band": source_band["name"], "delta_relative_db":
            _finite(left - right) if supported and left is not None and right is not None else None,
            "status": "compared" if supported and left is not None and right is not None else "unavailable"})
    return values


def analyze_tonal(args):
    allowed = {"source", "reference", "brief", "sections", "window_seconds"}
    if not isinstance(args, dict) or set(args) - allowed:
        raise ValueError("unknown tonal argument or non-object arguments")
    sources = [args.get("source")]
    if "reference" in args:
        sources.append(args["reference"])
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"name", "path", "signal_path"}:
            raise ValueError("source/reference require name, path and signal_path")
        for key in source:
            _text(source[key], key)
    brief = args.get("brief")
    expectations = []
    if brief is not None:
        if not isinstance(brief, dict) or set(brief) - {"description", "band_expectations"}:
            raise ValueError("brief requires description and optional band_expectations")
        _text(brief.get("description"), "brief.description")
        expectations = brief.get("band_expectations", [])
        if not isinstance(expectations, list) or len(expectations) > len(BANDS):
            raise ValueError("at most six band expectations supported")
        seen = set()
        for item in expectations:
            if not isinstance(item, dict) or set(item) != {"band", "min_relative_db", "max_relative_db"}:
                raise ValueError("expectations require band, min_relative_db and max_relative_db")
            _text(item["band"], "band")
            if item["band"] not in {b[0] for b in BANDS} or item["band"] in seen:
                raise ValueError("expectation bands must be supported and unique")
            seen.add(item["band"])
            low = _number(item["min_relative_db"], "min_relative_db", -120, 0)
            high = _number(item["max_relative_db"], "max_relative_db", -120, 0)
            if high < low:
                raise ValueError("maximum band expectation must follow minimum")
    sections = args.get("sections", [])
    if not isinstance(sections, list) or len(sections) > 32:
        raise ValueError("sections must contain at most 32 entries")
    names = set()
    for section in sections:
        if not isinstance(section, dict) or set(section) != {"name", "start_seconds", "end_seconds"}:
            raise ValueError("sections require name, start_seconds, end_seconds")
        _text(section["name"], "section.name")
        if section["name"] in names:
            raise ValueError("section names must be unique")
        names.add(section["name"])
        if _seconds(section["end_seconds"], "end_seconds", positive=True) <= _seconds(section["start_seconds"], "start_seconds"):
            raise ValueError("section end must follow start")
    requested_window = args.get("window_seconds")
    if requested_window is not None:
        _number(requested_window, "window_seconds", .25, 600)
    try:
        import numpy as np
        import soundfile as sf
        import pyloudnorm as pyln
        from scipy import signal
    except ImportError as exc:
        raise RuntimeError('Install audio analysis with: python -m pip install -e ".[audio-analysis]"') from exc
    files = []
    budget = MAX_WORK_SAMPLES
    for position, source in enumerate(sources):
        path = Path(source["path"]).resolve()
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("WAV exceeds 128 MiB")
        metadata = validate_wav(path)
        rate, channels, frames = metadata["sample_rate"], metadata["channels"], metadata["frames"]
        if channels not in (1, 2) or not 8000 <= rate <= 192000:
            raise ValueError("only mono/stereo WAV at 8000–192000 Hz supported")
        if frames * channels > 12_000_000 or metadata["duration_seconds"] > 600:
            raise ValueError("WAV exceeds sample/duration budget")
        file_sections = sections if position == 0 else []
        duration = frames / rate
        window = requested_window if requested_window is not None else max(.25, duration / 120)
        count = math.ceil(duration / window - 1e-9)
        if position == 0 and count > 120:
            raise ValueError("window_seconds would exceed 120 windows")
        section_indices = []
        for section in file_sections:
            if section["end_seconds"] > duration:
                raise ValueError("section exceeds source duration")
            start, end = (round(section[k] * rate) for k in ("start_seconds", "end_seconds"))
            if end <= start:
                raise ValueError("section contains no sample interval")
            section_indices.append((start, end))
        # Decode, whole analysis, local coverage and every repeated section all
        # count against one request budget (including independent reference).
        work = channels * ((3 if position == 0 else 2) * frames + sum(end - start for start, end in section_indices))
        if work > budget:
            raise ValueError("tonal request exceeds total sample-work budget")
        budget -= work
        with sf.SoundFile(str(path)) as handle:
            if (handle.frames, handle.samplerate, handle.channels) != (frames, rate, channels):
                raise ValueError("decoder and WAV metadata disagree")
            data = handle.read(dtype="float64", always_2d=True)
        if len(data) != frames or not np.isfinite(data).all() or np.max(np.abs(data)) > 1e6:
            raise ValueError("truncated, nonfinite or unreasonable audio")
        meter = pyln.Meter(rate, filter_class="DeMan")

        def measure(start, end):
            interval = data[start:end]
            levels = _measure(interval, rate, meter, np)
            levels["dc_offset_by_channel"] = [float(value) for value in np.mean(interval, axis=0)]
            return {"start_seconds": round(start / rate, 6), "end_seconds": round(end / rate, 6),
                "levels": levels, "spectrum": _spectrum(interval, rate, np, signal)}

        whole = measure(0, frames)
        windows = [measure(round(index * window * rate), min(frames, round((index + 1) * window * rate))) for index in range(count)] if position == 0 else []
        measured_sections = [{"name": section["name"], **measure(start, end)}
            for section, (start, end) in zip(file_sections, section_indices)]
        persistence = []
        eligible = [w for w in windows if w["spectrum"]["status"] == "measured"]
        for peak in whole["spectrum"].get("spectral_peaks", []):
            matches = sum(any(abs(p["frequency_hz"] - peak["frequency_hz"]) <= 2 * w["spectrum"]["resolution_hz"]
                for p in w["spectrum"].get("spectral_peaks", [])) for w in eligible)
            persistence.append({**peak, "matching_local_windows": matches, "eligible_local_windows": len(eligible)})
        files.append({**source, "path": str(path), "wav": metadata, "whole_file": whole,
            "sections": measured_sections, "local_windows": windows, "peak_persistence": persistence})
    source = files[0]
    observations = []
    intervals = [("whole_file", source["whole_file"])] + [(s["name"], s) for s in source["sections"]] + [(f"window_{i}", w) for i, w in enumerate(source["local_windows"])]
    for label, interval in intervals:
        for expectation in expectations:
            band = next((b for b in interval["spectrum"].get("bands", []) if b["name"] == expectation["band"]), None)
            value = band["relative_db"] if band is not None else None
            upper = band["upper_relative_db"] if band is not None else None
            if band is None or band["coverage"] != "full":
                status = "unavailable"
            elif value is None:
                status = "below_brief" if upper is not None and upper < expectation["min_relative_db"] else "unavailable"
            else:
                status = "below_brief" if value < expectation["min_relative_db"] else "above_brief" if value > expectation["max_relative_db"] else "within_brief"
            observations.append({"interval": label, "start_seconds": interval["start_seconds"], "end_seconds": interval["end_seconds"],
                **expectation, "measured_relative_db": value, "upper_relative_db": upper, "status": status})
    comparison = None
    if len(files) == 2:
        reference = files[1]["whole_file"]
        a, b = source["whole_file"]["levels"], reference["levels"]
        gain = a["integrated_lufs"] - b["integrated_lufs"] if a["integrated_lufs"] is not None and b["integrated_lufs"] is not None else None
        comparison = {"time_basis": "independent reference whole file; no alignment or corresponding musical time claimed",
            "shape_normalization": "each spectrum divided by its own 20 Hz–20 kHz covered power; gain invariant, not LUFS normalization",
            "reference_gain_to_source_lufs_db": _finite(gain) if gain is not None else None,
            "predicted_reference_sample_peak_dbfs": _finite(b["sample_peak_dbfs"] + gain) if gain is not None and b["sample_peak_dbfs"] is not None else None,
            "predicted_reference_sample_peak_headroom_db": _finite(-b["sample_peak_dbfs"] - gain) if gain is not None and b["sample_peak_dbfs"] is not None else None,
            "gain_applied": False, "whole_file": _compare(source["whole_file"]["spectrum"], reference["spectrum"]),
            "sections": [{"name": s["name"], "bands": _compare(s["spectrum"], reference["spectrum"])} for s in source["sections"]],
            "local_windows": [{"start_seconds": w["start_seconds"], "end_seconds": w["end_seconds"],
                "bands": _compare(w["spectrum"], reference["spectrum"])} for w in source["local_windows"]]}
    spectra = [f["whole_file"]["spectrum"] for f in files] + [i["spectrum"] for i in source["sections"] + source["local_windows"]]
    short_count = sum(s["status"] == "insufficient_duration" for s in spectra)
    tail_count = sum(s.get("omitted_tail_seconds", 0) > 0 for s in spectra)
    report = {"schema_version": 1, "complete": True, "processing_complete": True,
        "complete_semantics": "all requested file/interval processing completed; not complete spectral passage coverage or qualified acquisition",
        "spectrum_coverage_complete": not (short_count or tail_count),
        "spectrum_coverage_incomplete_reasons": ([{"reason": "interval_shorter_than_250_ms", "interval_count": short_count}] if short_count else []) +
            ([{"reason": "incomplete_final_welch_block", "interval_count": tail_count}] if tail_count else []),
        "source": source,
        "reference": files[1] if len(files) == 2 else None, "reference_comparison": comparison,
        "brief": brief, "brief_observations": observations,
        "method": {"spectrum": "Welch Hann 250 ms, 50% overlap, no detrend; mean channel power; fractional FFT-bin cell integration",
            "bands": "unweighted power dBFS (unit mean square = 0); relative dB against covered 20–20000 Hz power",
            "peaks": "top five >=6 dB local log-PSD prominences with >=-40 dB three-bin energy; quantized three-dB width",
            "brightness": "power-weighted centroid and 85% power rolloff over covered 20–20000 Hz",
            "frequency_coverage": [{"name": f["name"], "nyquist_hz": f["wav"]["sample_rate"] / 2,
                "normalization_low_hz": 20, "normalization_high_hz": min(20000, f["wav"]["sample_rate"] / 2)} for f in files],
            "numerical_floor": {"absolute_power": ABSOLUTE_POWER_FLOOR, "relative_to_original_power": RELATIVE_POWER_FLOOR,
                "rule": "max(absolute, original channel-mean square * relative); spectra/bands at or below floor unavailable"},
            "budget": {"max_sample_work": MAX_WORK_SAMPLES, "used_sample_work": MAX_WORK_SAMPLES - budget}},
        "time_basis": "seconds relative to each identified file; source sections are not reference section mappings",
        "interpretations": ["Above-brief sub/bass or low-mid energy is evidence consistent with low-end accumulation or muddiness only under that brief; it does not establish a mixing fault.",
            "Above-brief upper-mid energy may be consistent with harshness under that brief; spectral energy is not perceived harshness.",
            "Persistent narrow spectral peaks are potential resonances or intended harmonics; this analysis does not identify their cause."],
        "musical_judgment": "not inferred; retain/revert decisions require the stated goal and listening",
        "limitations": ["No audibility, masking, human approval, universal tonal target or quality score.",
            "Nyquist-truncated bands are partial/unsupported and never treated as missing treble; comparisons require full band coverage and identical covered normalization ranges.",
            "Reported dB values are rounded to 0.001 dB; brief boundary classifications use that reporting precision.",
            "250 ms Welch blocks limit frequency/transient resolution; incomplete final Welch blocks are not analyzed, and intervals shorter than 250 ms have unavailable spectra.",
            "Welch averages assume locally stationary spectral statistics; rapidly evolving sounds are averaged, not perceptual events. Hann weighting can attenuate boundary transients.",
            "Power spectra omit phase and temporal masking; channel power averaging is not mono compatibility.",
            "Relative band power depends on other bands; a departure does not uniquely identify an EQ correction.",
            "Signal-path descriptions are caller evidence, not physical qualification; isolated pre-mixer files do not establish in-mix source attribution.",
            "Independent reference passages need musical comparability; equal local seconds do not establish alignment. LUFS match is a reported gain only, not a listening audition."]}
    return report
