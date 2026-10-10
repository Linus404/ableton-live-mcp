"""Bounded offline stereo/fold evidence; no playback-device or human verdict."""
from __future__ import annotations

import math
from pathlib import Path

from audio_capture import validate_wav
from audio_dynamics import _regions
from audio_masking import _number, _text, _listening_condition, _perceptual_window, _model_power
from audio_tonal import BANDS, ABSOLUTE_POWER_FLOOR, RELATIVE_POWER_FLOOR

MAX_SAMPLES = 12_000_000
MAX_TOTAL_SAMPLES = 48_000_000
MAX_WORK = 96_000_000
TOOL_REQUIRED = ["source"]


def tool_properties():
    text = {"type": "string", "minLength": 1, "maxLength": 1024}
    source = {"type": "object", "properties": {k: dict(text) for k in ("name", "path", "signal_path")},
              "required": ["name", "path", "signal_path"], "additionalProperties": False}
    part = {"type": "object", "properties": {"name": dict(text), "path": dict(text),
            "gain_db": {"type": "number", "minimum": -60, "maximum": 60}},
            "required": ["name", "path"], "additionalProperties": False}
    return {"source": source, "target": part,
        "competitors": {"type": "array", "items": part, "minItems": 1, "maxItems": 8},
        "alignment": {"type": "object", "properties": {"verified": {"const": True}, "source": dict(text),
            "uncertainty_samples": {"const": 0}, "offsets_samples": {"type": "object",
                "additionalProperties": {"type": "integer", "minimum": 0}}},
            "required": ["verified", "source", "uncertainty_samples"], "additionalProperties": False},
        "provenance": {"type": "object", "properties": {"disjoint_contributions": {"const": True},
            "in_mix_levels": {"const": True}, "signal_path": dict(text)},
            "required": ["disjoint_contributions", "in_mix_levels", "signal_path"], "additionalProperties": False},
        "listening_condition": {"type": "object", "properties": {"kind": {"enum": ["calibrated", "assumed"]},
            "db_spl_at_0_dbfs_rms": {"type": "number", "minimum": 0, "maximum": 140}, "source": dict(text)},
            "required": ["kind", "db_spl_at_0_dbfs_rms", "source"], "additionalProperties": False},
        "sections": {"type": "array", "maxItems": 32, "items": {"type": "object", "properties": {
            "name": dict(text), "start_seconds": {"type": "number", "minimum": 0},
            "end_seconds": {"type": "number", "minimum": 0}},
            "required": ["name", "start_seconds", "end_seconds"], "additionalProperties": False}},
        "window_seconds": {"type": "number", "minimum": .1, "maximum": 1, "default": 1},
        "max_windows": {"type": "integer", "minimum": 1, "maximum": 120, "default": 120}}


def _db(power, floor):
    return round(10 * math.log10(power), 6) if power > floor else None


def _metrics(left, right, mid, side, cross, floor, mono=False):
    mean = (left + right) / 2
    denominator = math.sqrt(left * right)
    correlation = max(-1., min(1., float(cross.real) / denominator)) if min(left, right) > floor else None
    cross_active = abs(cross) > floor and min(left, right) > floor
    return {"status": "silent" if mean == 0 else "below_numerical_floor" if mean <= floor else "measured",
        "left_power_dbfs": _db(left, floor), "right_power_dbfs": _db(right, floor) if not mono else None,
        "mean_channel_power_dbfs": _db(mean, floor), "mono_power_dbfs": _db(mid, floor),
        "side_power_dbfs": _db(side, floor) if not mono else None,
        "side_fraction": round(side / (mid + side), 6) if not mono and mid + side > floor else None,
        "lr_normalized_real_cross_power": round(correlation, 6) if not mono and correlation is not None else None,
        "lr_cross_phase_degrees": round(math.degrees(math.atan2(cross.imag, cross.real)), 6) if not mono and cross_active else None,
        "stereo_status": "unavailable_native_mono" if mono else "measured" if min(left, right) > floor else "unavailable_inactive_channel",
        "mono_fold_power_change_db": round(10 * math.log10(mid / mean), 6) if mean > floor and mid > floor else None,
        "mono_fold_change_upper_db": round(10 * math.log10(floor / mean), 6) if mean > floor and mid <= floor else None,
        "mono_fold_status": "unavailable_inactive_source" if mean <= floor else "below_numerical_floor" if mid <= floor else "measured",
        "exact_zero_mono_power": bool(mid == 0 and mean > floor)}


def _measurement(data, rate, np, signal):
    mono = data.shape[1] == 1
    left = data[:, 0]
    right = left if mono else data[:, 1]
    mid, side = (left + right) / 2, (left - right) / 2
    powers = [float(np.mean(v * v)) for v in (left, right, mid, side)]
    floor = max(ABSOLUTE_POWER_FLOOR, max(powers[:2]) * RELATIVE_POWER_FLOOR)
    broad = _metrics(*powers, complex(np.mean(left * right)), floor, mono)
    broad["numerical_power_floor_dbfs"] = round(10 * math.log10(floor), 6)
    size = round(rate * .25)
    if len(data) < size:
        return {"broadband": broad, "spectrum": {"status": "insufficient_duration", "minimum_seconds": .25,
            "covered_duration_seconds": 0., "omitted_tail_seconds": len(data) / rate, "bands": []}}
    hop = size - size // 2
    blocks = 1 + (len(data) - size) // hop
    covered = size + (blocks - 1) * hop
    # Direct mid/side FFTs retain cancellation below the subtraction precision
    # of (P_L+P_R +/- 2 Re cross)/4.
    channels = np.column_stack((left, right, mid, side))
    frequency, density = signal.welch(channels, fs=rate, nperseg=size, noverlap=size // 2,
        window="hann", detrend=False, scaling="density", axis=0)
    _, cross = signal.csd(left, right, fs=rate, nperseg=size, noverlap=size // 2,
        window="hann", detrend=False, scaling="density")
    density[0] *= 2
    cross[0] *= 2
    if size % 2 == 0:
        density[-1] *= 2
        cross[-1] *= 2
    df = rate / size
    lo, hi = np.maximum(0, frequency - df / 2), np.minimum(rate / 2, frequency + df / 2)
    bands = []
    for name, low, high in BANDS:
        coverage = "full" if high <= rate / 2 else "partial" if low < rate / 2 else "unsupported"
        weights = np.maximum(0, np.minimum(hi, high) - np.maximum(lo, low))
        energy = np.sum(density * weights[:, None], axis=0)
        metrics = _metrics(*map(float, energy), complex(np.sum(cross * weights)), floor, mono) if coverage != "unsupported" else None
        bands.append({"name": name, "low_hz": low, "high_hz": high, "coverage": coverage,
            "covered_high_hz": min(high, rate / 2) if coverage != "unsupported" else None,
            "measurement": metrics})
    return {"broadband": broad, "spectrum": {"status": "measured", "bands": bands,
        "resolution_hz": df, "welch_blocks": blocks, "covered_duration_seconds": covered / rate,
        "omitted_tail_seconds": (len(data) - covered) / rate}}


def analyze_stereo(args):
    """Identify signal paths explicitly; declarations do not qualify acquisitions."""
    if not isinstance(args, dict) or set(args) - set(tool_properties()):
        raise ValueError("unknown stereo argument or non-object arguments")
    sections = _regions(args.get("sections", []))
    for section in sections:
        _text(section["name"], "section.name")
    width_seconds = _number(args.get("window_seconds", 1), "window_seconds", .1, 1)
    limit = args.get("max_windows", 120)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 120:
        raise ValueError("max_windows must be an integer from 1 to 120")
    optional = {"target", "competitors", "alignment", "provenance", "listening_condition"}
    present = optional & set(args)
    if present and present != optional:
        raise ValueError("target mode requires target, competitors, alignment, provenance and listening_condition")
    target_mode = bool(present)
    condition = _listening_condition(args["listening_condition"]) if target_mode else None
    competitors = args.get("competitors", [])
    if not isinstance(competitors, list) or target_mode and not 1 <= len(competitors) <= 8:
        raise ValueError("competitors must contain 1 to 8 WAVs")
    entries = [args.get("source"), *([args["target"], *competitors] if target_mode else [])]
    paths, names, metadata, gains = [], [], [], []
    for index, entry in enumerate(entries):
        keys = {"name", "path", "signal_path"} if index == 0 else {"name", "path", "gain_db"}
        required = keys if index == 0 else {"name", "path"}
        if not isinstance(entry, dict) or set(entry) - keys or not required <= set(entry):
            raise ValueError("source requires name/path/signal_path; contributions require name/path and optional gain_db")
        for key in required:
            _text(entry[key], key)
        name, path = entry["name"], Path(entry["path"]).resolve()
        if name in names or path in paths:
            raise ValueError("source names and resolved WAV paths must be unique")
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("WAV exceeds file byte budget")
        info = validate_wav(path)
        if info["channels"] not in (1, 2) or not 8000 <= info["sample_rate"] <= 192000:
            raise ValueError("only mono/stereo WAVs at 8000..192000 Hz supported")
        if info["frames"] * info["channels"] > MAX_SAMPLES or info["duration_seconds"] > 120:
            raise ValueError("WAV exceeds sample/duration budget")
        gains.append(_number(entry.get("gain_db", 0), "gain_db", -60, 60))
        names.append(name)
        paths.append(path)
        metadata.append(info)
    if sum(m["frames"] * m["channels"] for m in metadata) > MAX_TOTAL_SAMPLES:
        raise ValueError("WAVs exceed total decoded sample budget")
    rate, channels = metadata[0]["sample_rate"], metadata[0]["channels"]
    if any((m["sample_rate"], m["channels"]) != (rate, channels) for m in metadata):
        raise ValueError("programme/contributions require identical sample rate and channel layout")
    offsets = dict.fromkeys(names, 0)
    if target_mode:
        alignment, provenance = args["alignment"], args["provenance"]
        if not isinstance(alignment, dict) or set(alignment) - {"verified", "source", "uncertainty_samples", "offsets_samples"}:
            raise ValueError("alignment requires verified source and uncertainty_samples")
        uncertainty = alignment.get("uncertainty_samples")
        if alignment.get("verified") is not True or uncertainty != 0 or isinstance(uncertainty, bool):
            raise ValueError("alignment must be verified with zero sample uncertainty")
        _text(alignment.get("source"), "alignment.source")
        if not isinstance(provenance, dict) or set(provenance) != {"disjoint_contributions", "in_mix_levels", "signal_path"}:
            raise ValueError("provenance requires disjoint_contributions, in_mix_levels and signal_path")
        if provenance["disjoint_contributions"] is not True or provenance["in_mix_levels"] is not True:
            raise ValueError("only disjoint actual in-mix contributions support prominence estimates")
        _text(provenance["signal_path"], "provenance.signal_path")
        if "offsets_samples" not in alignment and len({m["frames"] for m in metadata}) != 1:
            raise ValueError("equal frame lengths required without offsets_samples")
        offsets = alignment.get("offsets_samples", offsets)
        if not isinstance(offsets, dict) or set(offsets) != set(names):
            raise ValueError("offsets_samples must map every name including programme source")
        for name, info in zip(names, metadata):
            if isinstance(offsets[name], bool) or not isinstance(offsets[name], int) or not 0 <= offsets[name] < info["frames"]:
                raise ValueError("offsets_samples must be integer frame indices inside every WAV")
    frames = min(m["frames"] - offsets[n] for m, n in zip(metadata, names))
    width = round(width_seconds * rate)
    count = math.ceil(frames / width)
    if count > limit:
        raise ValueError("common interval exceeds window budget; choose larger window_seconds")
    spans = []
    for section in sections:
        if section["end_seconds"] > frames / rate:
            raise ValueError("section must span nonempty samples inside analyzed common interval")
        start, end = round(section["start_seconds"] * rate), round(section["end_seconds"] * rate)
        if not 0 <= start < end <= frames:
            raise ValueError("section must span nonempty samples inside analyzed common interval")
        spans.append((section, start, end))
    # Source broadband+four-channel Welch+cross FFT work, including overlapping
    # Welch blocks, whole/local/sections; contribution stereo+mono model work.
    source_work = (2 * frames + sum(b - a for _, a, b in spans)) * 16
    model_work = frames * (len(entries) - 1) * (channels + 1) * 3 if target_mode else 0
    if source_work + model_work > MAX_WORK:
        raise ValueError("analysis exceeds reserved sample-work budget")
    try:
        import numpy as np
        import soundfile as sf
        from scipy import signal
    except ImportError as exc:
        raise RuntimeError('Install audio analysis with: python -m pip install -e ".[audio-analysis]"') from exc
    decoded = []
    for path, info, name in zip(paths, metadata, names):
        with sf.SoundFile(str(path)) as handle:
            if (handle.frames, handle.samplerate, handle.channels) != (info["frames"], rate, channels):
                raise ValueError("decoder and WAV metadata disagree")
            handle.seek(offsets[name])
            data = handle.read(frames, dtype="float64", always_2d=True)
        if len(data) != frames or not np.isfinite(data).all() or np.max(np.abs(data)) > 1e6:
            raise ValueError("WAV truncated, changed, nonfinite or unreasonably large")
        decoded.append(data)
    source = decoded[0]
    whole = _measurement(source, rate, np, signal)
    windows = []
    perceptual = []
    frequencies = np.fft.rfftfreq(1024, 1 / rate)
    for index in range(count):
        start, end = index * width, min(frames, (index + 1) * width)
        windows.append({"start_seconds": start / rate, "end_seconds": end / rate,
            **_measurement(source[start:end], rate, np, signal)})
        if target_mode:
            chunk = [data[start:end] for data in decoded[1:]]
            original = [_model_power(data, np) for data in chunk]
            folded = [_model_power(np.mean(data, axis=1, keepdims=True), np) for data in chunk]
            entry = {"start_seconds": start / rate, "end_seconds": end / rate}
            if original[0] is None:
                entry.update(status="unavailable_insufficient_duration", minimum_frames=1024)
            else:
                stereo = _perceptual_window(np.asarray(original), frequencies, gains[1:], condition, names[1:], np)
                mono = _perceptual_window(np.asarray(folded), frequencies, gains[1:], condition, names[1:], np)
                a, b = stereo["threshold_excess_dbfs"], mono["threshold_excess_dbfs"]
                entry.update(status="modeled", stereo=stereo, mono=mono,
                    mono_minus_stereo_threshold_excess_db=b - a if a is not None and b is not None else None)
            perceptual.append(entry)
    section_reports = [{**section, **_measurement(source[start:end], rate, np, signal)} for section, start, end in spans]
    measurements = [whole, *windows, *section_reports]
    spectral_complete = all(m["spectrum"]["omitted_tail_seconds"] == 0 for m in measurements)
    return {"processing_complete": True, "source": {**args["source"], "metadata": metadata[0],
            "whole_file": whole, "windows": windows, "sections": section_reports},
        "measured_facts": {"mono_fold": "(L+R)/2 for stereo; native mono unchanged", "audio_files_modified": False,
            "programme_gain_applied": False, "contribution_gains_are_counterfactual": True},
        "perceptual_estimates": {"status": "modeled" if target_mode else "unavailable",
            "reason": None if target_mode else "important-part attribution requires aligned disjoint in-mix contributions and listening conditions",
            "target": args.get("target"), "competitors": competitors, "windows": perceptual,
            "retained_sources": [{**entry, "metadata": info, "applied_counterfactual_gain_db": gain,
                "original_levels": {"mean_channel_rms_dbfs": _db(float(np.mean(data * data)), ABSOLUTE_POWER_FLOOR),
                    "mono_fold_rms_dbfs": _db(float(np.mean(np.mean(data, axis=1) ** 2)), ABSOLUTE_POWER_FLOOR),
                    "sample_peak_dbfs": _db(float(np.max(np.abs(data))) ** 2, ABSOLUTE_POWER_FLOOR)}}
                for entry, info, gain, data in zip(entries[1:], metadata[1:], gains[1:], decoded[1:])],
            "alignment": args.get("alignment"), "provenance": args.get("provenance"), "listening_condition": condition,
            "acquisition_qualification": "caller declarations only; not independently verified"},
        "coverage": {"time_coordinates": "common-time seconds" if target_mode else "file-relative seconds",
            "whole_file_result_scope": "entire analyzed common interval" if target_mode else "entire source file",
            "frames": frames, "duration_seconds": frames / rate, "offsets_samples": offsets,
            "spectral_coverage_complete": spectral_complete,
            "unmeasured_perceptual_seconds": sum(w["end_seconds"] - w["start_seconds"] for w in perceptual if w["status"] != "modeled"),
            "reserved_sample_work": source_work + model_work},
        "method": {"spectrum": "250 ms Hann Welch, 50% overlap; FFT-bin-cell band integration",
            "phase_convention": "angle of band-summed conj(L)*R; not a delay or per-bin phase estimate",
            "correlation": "normalized uncentered real cross-power, not DC-subtracted Pearson correlation",
            "width": "side power / (mid power + side power); no universal target",
            "prominence": "existing MPEG-1 Model-1 adaptation, independent channel estimates versus arithmetic mono fold"},
        "limitations": ["No binaural/temporal masking, speaker/headphone/room translation guarantee or human audibility approval.",
            "Single-source stereo metrics do not attribute cancellation or important-part audibility.",
            "Stereo-versus-mono estimates retain original gains and identical declared SPL reference; not loudness-normalized listening comparisons.",
            "Band-summed cross phase can hide differing per-frequency relationships; floor-limited or inactive-channel phase is null.",
            "Hann weighting suppresses endpoints; incomplete Welch tails and sub-250 ms intervals lack spectra.",
            "Competition sums incoherent powers, not correlated interference or nonlinear shared processing."]}
