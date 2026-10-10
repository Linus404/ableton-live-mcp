"""Bounded offline technical evidence, not a certified delivery meter."""
from __future__ import annotations

import json
import math
from pathlib import Path

from audio_analysis import _db, _measure
from audio_capture import validate_wav
from audio_dynamics import _regions, _text

TOOL_REQUIRED = ["source"]
MAX_WORK = 96_000_000


def tool_properties():
    text = {"type": "string", "minLength": 1, "maxLength": 4096}
    return {
        "source": {"type": "object", "properties": {k: text for k in ("name", "path", "signal_path")},
                   "required": ["name", "path", "signal_path"], "additionalProperties": False},
        "sections": {"type": "array", "maxItems": 32, "items": {"type": "object",
            "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 128},
                "start_seconds": {"type": "number", "minimum": 0}, "end_seconds": {"type": "number", "exclusiveMinimum": 0}},
            "required": ["name", "start_seconds", "end_seconds"], "additionalProperties": False}},
        "silence_threshold_dbfs": {"type": "number", "minimum": -120, "maximum": -20},
        "min_silence_seconds": {"type": "number", "minimum": .001, "maximum": 600},
        "discontinuity_threshold": {"type": "number", "minimum": .01, "maximum": 2},
        "delivery": {"type": "object", "properties": {
            "description": text, "sample_rate": {"type": "integer", "minimum": 8000, "maximum": 192000},
            "channels": {"type": "integer", "enum": [1, 2]},
            "subtype": {"type": "string", "enum": ["PCM_U8", "PCM_16", "PCM_24", "PCM_32", "FLOAT", "DOUBLE"]},
            "max_true_peak_dbtp": {"type": "number", "minimum": -120, "maximum": 120},
            "integrated_lufs_min": {"type": "number", "minimum": -120, "maximum": 120},
            "integrated_lufs_max": {"type": "number", "minimum": -120, "maximum": 120},
            "max_abs_dc": {"type": "number", "minimum": 0, "maximum": 1}},
            "required": ["description"], "additionalProperties": False},
    }


def _intervals(mask, rate, minimum_frames, np):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    keep = ends - starts >= minimum_frames
    starts, ends = starts[keep], ends[keep]
    return {"total_count": len(starts), "omitted_count": max(0, len(starts) - 120),
        "values": [{"start_seconds": round(int(a) / rate, 9), "end_seconds": round(int(b) / rate, 9),
                    "frames": int(b - a)} for a, b in zip(starts[:120], ends[:120])]}


def analyze_integrity(args):
    properties = tool_properties()
    if not isinstance(args, dict) or set(args) - set(properties):
        raise ValueError("unknown integrity argument or non-object arguments")
    source = args.get("source")
    if not isinstance(source, dict) or set(source) != {"name", "path", "signal_path"}:
        raise ValueError("source requires name, path, signal_path")
    for key, value in source.items():
        _text(value, key)
    sections = _regions(args.get("sections", []))
    if any(len(s["name"]) > 128 for s in sections):
        raise ValueError("section name exceeds 128 characters")
    options = {}
    for key, default, low, high in (("silence_threshold_dbfs", -90, -120, -20),
            ("min_silence_seconds", .1, .001, 600), ("discontinuity_threshold", .5, .01, 2)):
        value = args.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be finite in [{low}, {high}]")
        options[key] = value
    delivery = args.get("delivery")
    if delivery is not None:
        if not isinstance(delivery, dict) or "description" not in delivery or set(delivery) - set(properties["delivery"]["properties"]):
            raise ValueError("invalid delivery requirements")
        _text(delivery["description"], "delivery.description")
        for key, value in delivery.items():
            spec = properties["delivery"]["properties"][key]
            if key == "description":
                continue
            if "enum" in spec and value not in spec["enum"]:
                raise ValueError(f"invalid delivery {key}")
            if spec["type"] == "integer" and type(value) is not int:
                raise ValueError(f"delivery {key} must be integer")
            if spec["type"] in ("integer", "number") and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not spec.get("minimum", -math.inf) <= value <= spec.get("maximum", math.inf)):
                raise ValueError(f"invalid delivery {key}")
        if delivery.get("integrated_lufs_min", -math.inf) > delivery.get("integrated_lufs_max", math.inf):
            raise ValueError("delivery loudness minimum exceeds maximum")
    path = Path(source["path"]).resolve()
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("WAV exceeds 128 MiB")
    metadata = validate_wav(path)
    rate, channels, frames = metadata["sample_rate"], metadata["channels"], metadata["frames"]
    if channels not in (1, 2) or not 8000 <= rate <= 192000:
        raise ValueError("only mono/stereo WAV at 8000–192000 Hz supported")
    if frames * channels > 12_000_000 or metadata["duration_seconds"] > 600:
        raise ValueError("WAV exceeds sample/duration budget")
    spans = [(0, frames)]
    for section in sections:
        if section["end_seconds"] > frames / rate:
            raise ValueError("section exceeds file duration")
        a, b = (round(section[k] * rate) for k in ("start_seconds", "end_seconds"))
        if b <= a:
            raise ValueError("section contains no sample interval")
        spans.append((a, b))
    # Decode, whole-file interpolation + level/detection scans and repeated sections.
    work = frames * channels + sum(((b - a) * 7 + 80) * channels for a, b in spans)
    if work > MAX_WORK:
        raise ValueError("integrity request exceeds total sample-work budget")
    try:
        import numpy as np
        import soundfile as sf
        import pyloudnorm as pyln
        from scipy.signal import resample_poly
    except ImportError as exc:
        raise RuntimeError('Install audio analysis with: python -m pip install -e ".[audio-analysis]"') from exc
    with sf.SoundFile(str(path)) as handle:
        if (handle.frames, handle.samplerate, handle.channels) != (frames, rate, channels):
            raise ValueError("decoder and WAV metadata disagree")
        subtype = handle.subtype
        data = handle.read(dtype="float64", always_2d=True)
    if len(data) != frames or not np.isfinite(data).all() or np.max(np.abs(data)) > 1e6:
        raise ValueError("truncated, nonfinite or unreasonable audio")
    meter = pyln.Meter(rate, filter_class="DeMan")

    def measure(a, b):
        values = data[a:b]
        levels = _measure(values, rate, meter, np)
        # SciPy's 81-tap 4x Kaiser(5) low-pass: support +/-10 original frames.
        # Sections use surrounding real samples, not artificial section-edge zeros.
        left, right = max(0, a - 10), min(frames, b + 10)
        oversampled = resample_poly(data[left:right], 4, 1, axis=0, window=("kaiser", 5.0), padtype="constant")
        estimate = oversampled[(a - left) * 4:(b - left) * 4]
        peak_values = np.max(np.abs(estimate), axis=0)
        peak_positions = np.argmax(np.abs(estimate), axis=0)
        dc = np.mean(values, axis=0)
        threshold = 10 ** (options["silence_threshold_dbfs"] / 20)
        silent = _intervals(np.max(np.abs(values), axis=1) <= threshold, rate,
                            math.ceil(options["min_silence_seconds"] * rate), np)
        for interval in silent["values"]:
            interval["start_seconds"] += a / rate
            interval["end_seconds"] += a / rate
        pcm = metadata["format"] == "pcm"
        positive_rail = 1 - 2 ** (1 - metadata["bits_per_sample"]) if pcm else 1
        rail_mask = (values <= -1) | (values >= positive_rail)
        runs = _intervals(np.any(rail_mask[:-1] & rail_mask[1:] & (values[:-1] == values[1:]), axis=1), rate, 1, np)
        for interval in runs["values"]:
            interval["start_seconds"] += a / rate
            interval["end_seconds"] += (a + 1) / rate
            interval["frames"] += 1
        jumps = np.max(np.abs(np.diff(values, axis=0)), axis=1)
        indices = np.flatnonzero(jumps >= options["discontinuity_threshold"])
        candidates = [{"time_seconds": (a + int(i) + 1) / rate, "jump_linear": float(jumps[i]),
                       "kind": "adjacent_sample_discontinuity_candidate"} for i in indices[:120]]
        boundaries = []
        for position, sample, side in ((0, data[0], "start"), (frames, data[-1], "end")):
            if (position == 0 and a == 0) or (position == frames and b == frames):
                jump = float(np.max(np.abs(sample)))
                boundaries.append({"side": side, "time_seconds": position / rate, "jump_to_zero_linear": jump,
                    "candidate": jump >= options["discontinuity_threshold"], "outside_file_audio": "unknown"})
        interior_start, interior_end = max(a, 10), min(b, frames - 10)
        return {"start_seconds": a / rate, "end_seconds": b / rate, "levels": levels,
            "true_peak_estimate": {"dbtp": _db(float(np.max(peak_values))),
                "per_channel_dbtp": [_db(float(p)) for p in peak_values],
                "per_channel_peak_time_seconds": [(a + int(p) / 4) / rate for p in peak_positions],
                "headroom_to_unity_db": -_db(float(np.max(peak_values))) if np.max(peak_values) > 0 else None,
                "interior_supported_interval_seconds": [interior_start / rate, interior_end / rate] if interior_end > interior_start else None,
                "boundary_context_complete": a >= 10 and b <= frames - 10,
                "continuous_wave_maximum_verified": False},
            "dc": {"per_channel_mean_linear": [float(v) for v in dc], "max_abs_mean_linear": float(np.max(np.abs(dc)))},
            "clipping_observations": {"kind": "pcm_rail_contacts" if pcm else "float_at_or_above_unity",
                "positive_threshold_linear": positive_rail, "per_channel_sample_counts": [int(v) for v in rail_mask.sum(axis=0)],
                "sustained_repeated_rail_runs": runs,
                "proven_clipping": False},
            "silence_candidates": {**silent, "threshold_dbfs": options["silence_threshold_dbfs"],
                "minimum_seconds": options["min_silence_seconds"], "intent": "unknown"},
            "discontinuity_candidates": {"threshold_linear": options["discontinuity_threshold"],
                "total_count": len(indices), "omitted_count": max(0, len(indices) - 120), "values": candidates,
                "file_boundary_observations": boundaries, "intent": "unknown"}}

    whole = measure(0, frames)
    checks = []
    if delivery is not None:
        measurements = {"sample_rate": rate, "channels": channels, "subtype": subtype,
            "max_true_peak_dbtp": whole["true_peak_estimate"]["dbtp"],
            "integrated_lufs_min": whole["levels"]["integrated_lufs"],
            "integrated_lufs_max": whole["levels"]["integrated_lufs"],
            "max_abs_dc": whole["dc"]["max_abs_mean_linear"]}
        for key, required in delivery.items():
            if key == "description":
                continue
            measured = measurements[key]
            passed = measured == required if key in ("sample_rate", "channels", "subtype") else (
                measured >= required if key == "integrated_lufs_min" else measured <= required) if measured is not None else None
            checks.append({"requirement": key, "required": required, "measured": measured,
                "status": "unavailable" if passed is None else "within_requirement" if passed else "outside_requirement",
                "basis": "finite_FIR_estimate_not_certification" if key == "max_true_peak_dbtp" else "file_measurement"})
    report = {"schema_version": 1, "processing_complete": True, "source": {**source, "path": str(path)},
        "wav": {**metadata, "subtype": subtype}, "time_basis": "file-relative seconds",
        "measured_facts": {"whole_file": whole, "sections": [{**s, "measurement": measure(*span)} for s, span in zip(sections, spans[1:])]},
        "perceptual_estimates": {"status": "unsupported"},
        "interpretations": ["Rail contacts may reflect clipping; floating over-unity may remain valid internal headroom.",
            "Discontinuities may be clicks, abrupt edits, or intentional transients/high-frequency waveforms.",
            "Detected silence is not proven unintended; no automatic repair or musical judgment."],
        "delivery": {"requirements": delivery, "checks": checks, "certified_compliance": False},
        "method": {"true_peak": "4x scipy resample_poly, 81-tap Kaiser beta=5 FIR, zero extension outside file",
            "accuracy": "Finite FIR/fourfold sampling estimate; not BS.1770 true-peak conformance or a bounded-error meter. Near-Nyquist peaks and between-grid maxima may be missed.",
            "edges": "First/last 10 original frames lack real interpolation context; zero-extension estimates retained but continuous-wave boundary maxima unverified. Short files have no supported interior.",
            "dc": "arithmetic channel mean; low-frequency musical energy may contribute",
            "budget": {"reserved_sample_work": work, "max_sample_work": MAX_WORK}},
        "limitations": ["Caller signal_path identifies provenance but does not qualify acquisition or final-release identity.",
            "Sample peak is distinct from intersample estimate; codec overshoot and certified true-peak accuracy unsupported.",
            "LUFS and DC checks retain original levels; silence/short-duration LUFS unavailable.",
            "Candidates are capped with omitted counts; processing completion is not exhaustive defect detection or listening approval."]}
    json.dumps(report, allow_nan=False)
    return report
