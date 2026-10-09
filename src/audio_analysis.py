"""Offline, bounded WAV loudness evidence; never accesses Live or sums stems.

Install the optional ``audio-analysis`` extra. ``analyze_audio`` accepts a dict
with exactly one of ``path`` (WAV) or ``manifest_path`` (audio_capture manifest),
optional ``sections`` [{name, start_seconds, end_seconds}], and optional
``window_step_seconds``. Times always refer to each raw file, not Arrangement.
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

from audio_capture import validate_wav

MAX_SAMPLES = 12_000_000  # Scalar samples, including both stereo channels.
MAX_TOTAL_SAMPLES = 96_000_000
MAX_WINDOWS = 120


def _seconds(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return float(value)


def _finite(value):
    return round(float(value), 3) if math.isfinite(float(value)) else None


def _db(value):
    return _finite(20 * math.log10(value)) if value > 0 else None


def _measure(data, rate, meter, np):
    duration = len(data) / rate
    integrated = None
    if duration >= 0.4:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # Empty absolute gate (silence).
            # The backend rounds its block count; exclude incomplete 400 ms blocks.
            hops = math.floor((duration - 0.4) / 0.1 + 1e-9)
            frames = round((0.4 + hops * 0.1) * rate)
            integrated = _finite(meter.integrated_loudness(data[:frames]))
    return {
        "duration_seconds": round(duration, 6),
        "integrated_lufs": integrated,
        "integrated_status": "measured" if integrated is not None else
            "insufficient_duration" if duration < 0.4 else "below_absolute_gate_or_silent",
        "sample_peak_dbfs": _db(float(np.max(np.abs(data)))),
        "rms_dbfs": _db(float(np.sqrt(np.mean(np.square(data))))),
        "loudness_range_lu": None,
        "loudness_range_status": "unsupported_by_backend",
    }


def _analyze_file(path, sections, step, np, sf, pyln, budget, *, offset_frames=0, common_frames=None, gain_db=0):
    metadata = validate_wav(path)
    rate, channels = metadata["sample_rate"], metadata["channels"]
    if channels not in (1, 2):
        raise ValueError("only mono/stereo supported; multichannel layout is not inferred")
    if not 8000 <= rate <= 192000:
        raise ValueError("sample rate must be between 8000 and 192000 Hz")
    samples = metadata["frames"] * channels
    if samples > MAX_SAMPLES or samples > budget[0] or metadata["duration_seconds"] > 600:
        raise ValueError("audio exceeds sample/duration budget")
    budget[0] -= samples
    with sf.SoundFile(str(path)) as handle:
        if (handle.frames, handle.samplerate, handle.channels) != (metadata["frames"], rate, channels):
            raise ValueError("decoder and WAV metadata disagree")
        handle.seek(offset_frames)
        requested_frames = common_frames if common_frames is not None else metadata["frames"]
        data = handle.read(requested_frames, dtype="float64", always_2d=True)
    if len(data) != requested_frames:
        raise ValueError("WAV changed or was truncated during decoding")
    if not np.isfinite(data).all() or np.max(np.abs(data)) > 1e6:
        raise ValueError("audio contains nonfinite or unreasonably large samples")
    data *= 10 ** (gain_db / 20)
    duration = len(data) / rate
    effective_step = step if step is not None else max(0.1, duration / MAX_WINDOWS)
    if duration / effective_step > MAX_WINDOWS + 1e-9:
        raise ValueError(f"window_step_seconds would exceed {MAX_WINDOWS} windows")
    # DeMan implements reference BS.1770 K-weighting coefficients, not an EQ approximation.
    meter = pyln.Meter(rate, filter_class="DeMan")
    result = {"path": str(path), "wav": metadata, "whole_file": _measure(data, rate, meter, np), "sections": []}
    for section in sections:
        if section["end_seconds"] > duration:
            raise ValueError(f"section {section['name']!r} exceeds file duration")
        start, end = (int(round(section[key] * rate)) for key in ("start_seconds", "end_seconds"))
        if end <= start:
            raise ValueError("section contains no complete sample interval")
        section_samples = (end - start) * channels
        if section_samples > budget[0]:
            raise ValueError("sections exceed total analysis sample budget")
        budget[0] -= section_samples
        measurement = _measure(data[start:end], rate, meter, np)
        whole_lufs = result["whole_file"]["integrated_lufs"]
        delta = measurement["integrated_lufs"] - whole_lufs if measurement["integrated_lufs"] is not None and whole_lufs is not None else None
        result["sections"].append({**section, "measurement": measurement,
            "integrated_delta_vs_whole_lu": _finite(delta) if delta is not None else None})
    # Filter once with continuity for ungated 400 ms / 3 s trailing windows.
    # The dependency is pinned: _filters is the same filter chain its meter uses.
    filtered = data.copy()
    for stage in meter._filters.values():
        for channel in range(channels):
            filtered[:, channel] = stage.apply_filter(filtered[:, channel])
    power = np.sum(np.square(filtered), axis=1)  # Mono/stereo BS.1770 weights are 1.
    del filtered

    def trailing(end, seconds):
        width = int(round(seconds * rate))
        if end < width:
            return None
        # Direct means avoid subtracting nearly equal cumulative energies after
        # a loud passage, which can erase a later quiet but nonzero window.
        energy = float(np.mean(power[end - width:end]))
        return _finite(-0.691 + 10 * math.log10(energy)) if energy > 0 else None

    windows = []
    count = max(1, math.ceil(duration / effective_step - 1e-9))
    for index in range(1, count + 1):
        end = int(round(min(duration, index * effective_step) * rate))
        windows.append({"end_seconds": round(end / rate, 6),
                        "momentary_lufs": trailing(end, 0.4), "short_term_lufs": trailing(end, 3.0)})
    result["local_windows"] = {"step_seconds": effective_step, "trailing": True, "gated": False,
        "momentary_duration_seconds": 0.4, "short_term_duration_seconds": 3.0,
        "null_reason": "insufficient preceding samples or zero energy", "values": windows}
    changes = [(b["short_term_lufs"] - a["short_term_lufs"], a["end_seconds"], b["end_seconds"])
               for a, b in zip(windows, windows[1:])
               if a["short_term_lufs"] is not None and b["short_term_lufs"] is not None]
    largest = max(changes, key=lambda item: abs(item[0]), default=None)
    result["level_change"] = {"kind": "largest consecutive sampled short-term change; descriptive only",
        "delta_lu": round(largest[0], 3) if largest else None,
        "from_end_seconds": largest[1] if largest else None, "to_end_seconds": largest[2] if largest else None}
    return result


def analyze_audio(args):
    """Return JSON-safe measurement evidence. Invalid arguments raise ValueError.

    Manifest entry failures are returned individually and make ``complete`` false.
    A standalone corrupt/unsupported WAV raises ValueError (or OSError if missing).
    ``complete`` covers all requested entries, not proof of calibrated capture.
    """
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    if set(args) - {"path", "manifest_path", "sections", "window_step_seconds"}:
        raise ValueError("unknown audio analysis argument")
    if ("path" in args) == ("manifest_path" in args):
        raise ValueError("provide exactly one of path or manifest_path")
    for key in ("path", "manifest_path"):
        if key in args and (not isinstance(args[key], str) or not args[key].strip()):
            raise ValueError(f"{key} must be a nonempty path string")
    step = _seconds(args["window_step_seconds"], "window_step_seconds", positive=True) if "window_step_seconds" in args else None
    sections = args.get("sections", [])
    if not isinstance(sections, list) or len(sections) > 32:
        raise ValueError("sections must be a list of at most 32 entries")
    names = set()
    for section in sections:
        if not isinstance(section, dict) or set(section) != {"name", "start_seconds", "end_seconds"}:
            raise ValueError("sections require name, start_seconds, end_seconds")
        name = section["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or name in names:
            raise ValueError("section names must be unique nonempty strings of at most 128 characters")
        names.add(name)
        start = _seconds(section["start_seconds"], "start_seconds")
        end = _seconds(section["end_seconds"], "end_seconds", positive=True)
        if end <= start:
            raise ValueError("section end must follow start")
    try:
        import numpy as np
        import soundfile as sf
        import pyloudnorm as pyln
    except ImportError as exc:
        raise RuntimeError('Install audio analysis with: python -m pip install -e ".[audio-analysis]"') from exc
    report = {"schema_version": 1, "complete": False,
        "method": {"integrated": "pyloudnorm DeMan K-weighting, BS.1770 absolute -70 LUFS and relative -10 LU gate",
                   "local": "ungated K-weighted channel-summed mean-square, trailing 400 ms / 3 s",
                   "rms": "unweighted mean-square across all samples/channels; 0 dBFS = unit RMS",
                   "peak": "sample peak across all channels; not true peak",
                   "lra": "not implemented by this backend; no percentile proxy substituted"},
        "time_basis": "seconds relative to each file; no Arrangement mapping",
        "limitations": ["Isolated signal-point loudness does not establish in-mix audibility or masking.",
            "Pre-mixer levels do not represent fader balance; master-chain capture is not verified final delivery audio.",
            "Overlapping tracks, groups, returns and master are measured separately and never summed.",
            "Level changes are descriptive; no musical desirability or unexpectedness inferred.",
            "Sections are independently filtered/gated; local windows retain full-file filter continuity.",
            "LRA requires standardized short-term gating/percentiles and adequate programme duration; this backend does not support it."],
        "tracks": [], "relative_to_master": {"status": "unavailable", "values": [],
            "reason": "No verified common audio interval/alignment; equal file-relative seconds alone are insufficient."}}
    budget = [MAX_TOTAL_SAMPLES]
    if "path" in args:
        report["signal_point"] = "external WAV; routing and delivery provenance unknown"
        report["tracks"] = [{"outcome": "analyzed", **_analyze_file(Path(args["path"]).resolve(), sections, step, np, sf, pyln, budget)}]
        report["complete"] = True
        return report
    manifest_path = Path(args["manifest_path"]).resolve()
    if manifest_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("manifest exceeds 4 MiB")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    json.dumps(manifest, allow_nan=False)  # Reject nonfinite provenance, too.
    if not isinstance(manifest, dict) or not isinstance(manifest.get("tracks"), list) or not 1 <= len(manifest["tracks"]) <= 64:
        raise ValueError("manifest requires between 1 and 64 tracks")
    report["manifest_path"] = str(manifest_path)
    report["capture"] = {key: manifest.get(key) for key in ("take_id", "complete", "precision", "raw_untrimmed", "sample_aligned", "sample_uncertainty", "readiness", "signal_point", "context", "requested", "error", "restore_error", "passage_observed_complete")}
    for entry in manifest["tracks"]:
        if not isinstance(entry, dict):
            report["tracks"].append({"outcome": "invalid", "reason": "capture entry must be an object"})
            continue
        item = {key: entry[key] for key in ("name", "ref", "kind", "group_ref", "path", "outcome", "reason", "error") if key in entry}
        item["capture_outcome"] = entry.get("outcome")
        report["tracks"].append(item)
        if entry.get("outcome") != "captured" or entry.get("error"):
            item["outcome"] = "unsupported" if entry.get("outcome") == "unsupported" else "incomplete"
            continue
        try:
            if not isinstance(entry.get("path"), str) or not entry["path"]:
                raise ValueError("captured entry lacks WAV path")
            path = Path(entry["path"])
            if not path.is_absolute():
                path = manifest_path.parent / path
            item.update(_analyze_file(path.resolve(), sections, step, np, sf, pyln, budget))
            item["outcome"] = "analyzed"
        except (ValueError, OSError, RuntimeError) as exc:
            item.update(outcome="analysis_failed", reason=str(exc))
    report["complete"] = manifest.get("complete") is True and all(item["outcome"] == "analyzed" for item in report["tracks"])
    # Reject nonstandard JSON from capture metadata as well as measurement output.
    json.dumps(report, allow_nan=False)
    return report
