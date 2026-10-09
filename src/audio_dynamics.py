"""Bounded offline dynamics evidence. No Live calls or perceptual punch score."""
from __future__ import annotations

import math
from pathlib import Path

from audio_analysis import _seconds, _finite, _db, _measure
from audio_capture import validate_wav

MAX_WORK = 96_000_000
ABSOLUTE_FLOOR = 1e-30
RELATIVE_FLOOR = 1e-24
MODULATION_FLOOR_DB = .0005  # Below the 0.001 dB output resolution is not evidence.


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(f"{label} must be a nonempty string of at most 4096 characters")


def _regions(value, event=False):
    limit = 120 if event else 32
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{'events' if event else 'sections'} must be a list of at most {limit}")
    keys = ("start_seconds", "attack_end_seconds", "body_end_seconds", "end_seconds") if event else ("start_seconds", "end_seconds")
    names = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"name", *keys}:
            raise ValueError(f"regions require name and {', '.join(keys)}")
        _text(item["name"], "region.name")
        if item["name"] in names:
            raise ValueError("region names must be unique")
        names.add(item["name"])
        times = [_seconds(item[k], k) for k in keys]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError("region boundaries must be strictly increasing")
    return value


def _envelope(data, width, np):
    starts = np.arange(0, len(data), width)
    sizes = np.minimum(width, len(data) - starts)
    power = np.add.reduceat(np.mean(data * data, axis=1), starts) / sizes
    peaks = np.maximum.reduceat(np.max(np.abs(data), axis=1), starts)
    return starts, sizes, power, peaks


def _modulation(power, sizes, width, rate, floor, np, *, levels=None):
    full = sizes == width
    eligible = full & (power > floor)
    result = {"status": "unavailable", "duration_seconds": float(full.sum() * width / rate),
        "eligible_cells": int(eligible.sum()), "total_complete_cells": int(full.sum()),
        "omitted_partial_cells": int((~full).sum()), "dominant_frequency_hz": None,
        "envelope_std_db": None, "dominant_component_peak_amplitude_db": None,
        "frequency_resolution_hz": None, "intervals": []}
    edges = np.diff(np.r_[False, eligible, False].astype(int))
    runs = [(int(a), int(b)) for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))]
    long_runs = [(a, b) for a, b in runs if (b - a) * width / rate >= 4]
    for a, b in long_runs[:120]:
        values = 10 * np.log10(power[a:b]) if levels is None else levels[a:b]
        centered = values - np.mean(values)
        std = float(np.std(centered))
        interval = {"start_seconds": a * width / rate, "end_seconds": b * width / rate,
            "envelope_std_db": _finite(std), "frequency_resolution_hz": rate / (width * len(values)),
            "dominant_frequency_hz": None, "dominant_component_peak_amplitude_db": None,
            "status": "no_measurable_variation"}
        if std >= MODULATION_FLOOR_DB:
            taper = np.hanning(len(values))
            spectrum = np.abs(np.fft.rfft(centered * taper)) * 2 / taper.sum()
            frequencies = np.fft.rfftfreq(len(values), width / rate)
            selected = np.flatnonzero((frequencies >= .5) & (frequencies <= 10))
            best = selected[np.argmax(spectrum[selected])]
            if spectrum[best] >= MODULATION_FLOOR_DB:
                interval.update(status="measured", dominant_frequency_hz=_finite(frequencies[best]),
                    dominant_component_peak_amplitude_db=_finite(spectrum[best]))
            else:
                interval["status"] = "no_measurable_in_band_modulation"
        interval["modulation_reporting_floor_db"] = MODULATION_FLOOR_DB
        result["intervals"].append(interval)
    result.update(eligible_run_count=len(runs), measured_run_count=len(result["intervals"]),
        omitted_eligible_runs=max(0, len(long_runs) - 120),
        analyzed_duration_seconds=sum(i["end_seconds"] - i["start_seconds"] for i in result["intervals"]),
        unmeasured_duration_seconds=float(sizes.sum() / rate) - sum(i["end_seconds"] - i["start_seconds"] for i in result["intervals"]))
    result["coverage_complete"] = result["unmeasured_duration_seconds"] < .5 / rate
    if result["intervals"]:
        best = max(result["intervals"], key=lambda i: i["dominant_component_peak_amplitude_db"] or 0)
        result.update(best)
        result["reason"] = "strongest reported eligible interval; no interpolation across gaps; not a pumping diagnosis"
    else:
        result["reason"] = "no contiguous four-second non-floor-limited interval; gaps not interpolated"
    return result


def analyze_dynamics(args):
    allowed = {"source", "comparison", "alignment", "sections", "events", "window_seconds", "brief"}
    if not isinstance(args, dict) or set(args) - allowed:
        raise ValueError("unknown dynamics argument or non-object arguments")
    sources = [args.get("source")]
    if "comparison" in args:
        sources.append(args["comparison"])
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"name", "path", "signal_path"}:
            raise ValueError("source/comparison require name, path and signal_path")
        for key, value in source.items():
            _text(value, key)
    if len(sources) == 2 and sources[0]["name"] == sources[1]["name"]:
        raise ValueError("comparison source names must differ")
    alignment = args.get("alignment")
    if len(sources) == 1 and "alignment" in args:
        raise ValueError("alignment requires comparison")
    if len(sources) == 2:
        if not isinstance(alignment, dict) or set(alignment) - {"verified", "source", "uncertainty_samples", "offsets_samples"}:
            raise ValueError("comparison requires verified alignment evidence")
        if alignment.get("verified") is not True or type(alignment.get("uncertainty_samples")) is not int or alignment["uncertainty_samples"] != 0:
            raise ValueError("alignment must be verified with zero sample uncertainty")
        _text(alignment.get("source"), "alignment.source")
    sections = _regions(args.get("sections", []))
    events = _regions(args.get("events", []), event=True) if "events" in args else None
    window = _seconds(args["window_seconds"], "window_seconds", positive=True) if "window_seconds" in args else None
    if window is not None and not .01 <= window <= 600:
        raise ValueError("window_seconds must be 0.01–600")
    brief = args.get("brief")
    if brief is not None:
        if not isinstance(brief, dict) or set(brief) != {"description"}:
            raise ValueError("brief requires description only")
        _text(brief["description"], "brief.description")
    try:
        import numpy as np
        import soundfile as sf
        import pyloudnorm as pyln
    except ImportError as exc:
        raise RuntimeError('Install audio analysis with: python -m pip install -e ".[audio-analysis]"') from exc

    metadata = []
    paths = []
    for source in sources:
        path = Path(source["path"]).resolve()
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("WAV exceeds 128 MiB")
        info = validate_wav(path)
        if info["channels"] not in (1, 2) or not 8000 <= info["sample_rate"] <= 192000:
            raise ValueError("only mono/stereo WAV at 8000–192000 Hz supported")
        if info["frames"] * info["channels"] > 12_000_000 or info["duration_seconds"] > 600:
            raise ValueError("WAV exceeds sample/duration budget")
        paths.append(path)
        metadata.append(info)
    rate, channels = metadata[0]["sample_rate"], metadata[0]["channels"]
    offsets = [0] * len(sources)
    if len(sources) == 2:
        if any((m["sample_rate"], m["channels"]) != (rate, channels) for m in metadata):
            raise ValueError("comparison requires identical sample rate and channel layout")
        declared = alignment.get("offsets_samples")
        if declared is None:
            if metadata[0]["frames"] != metadata[1]["frames"]:
                raise ValueError("equal frame lengths required without offsets_samples")
        else:
            if not isinstance(declared, dict) or set(declared) != {s["name"] for s in sources}:
                raise ValueError("offsets_samples must map every source name to a file frame index")
            offsets = [declared[s["name"]] for s in sources]
            if any(type(o) is not int or not 0 <= o < m["frames"] for o, m in zip(offsets, metadata)):
                raise ValueError("offsets_samples must be nonnegative integer indices inside each file")
    frames = min(m["frames"] - o for m, o in zip(metadata, offsets))
    duration = frames / rate
    window = window if window is not None else max(.01, duration / 120)
    count = math.ceil(duration / window - 1e-9)
    if count > 120:
        raise ValueError("window_seconds would exceed 120 windows")
    if round(window * rate) < 1:
        raise ValueError("window contains no sample interval")
    for item in sections + (events or []):
        if item["end_seconds"] > duration:
            raise ValueError("region exceeds analyzed duration")
        # Keys are not assumed to retain the caller's JSON order.
        keys = ("start_seconds", "attack_end_seconds", "body_end_seconds", "end_seconds") if "attack_end_seconds" in item else ("start_seconds", "end_seconds")
        indices = [round(item[k] * rate) for k in keys]
        if any(b <= a for a, b in zip(indices, indices[1:])):
            raise ValueError("region contains an empty sample interval")
    section_work = sum(round(s["end_seconds"] * rate) - round(s["start_seconds"] * rate) for s in sections)
    event_work = sum(round(e["end_seconds"] * rate) - round(e["start_seconds"] * rate) for e in events) if events is not None else min(frames * 120, round(.3 * rate) * 120)
    # Decode + whole/local + continuous envelope + regional repeats. Reserve
    # another passage for paired envelope/comparison processing before reading.
    work = sum(m["frames"] * channels for m in metadata) + len(sources) * channels * (3 * frames + section_work + event_work) + (frames if len(sources) == 2 else 0)
    if work > MAX_WORK:
        raise ValueError("dynamics request exceeds total sample-work budget")
    width = max(1, round(.01 * rate))
    loaded = []
    for path, info, offset in zip(paths, metadata, offsets):
        with sf.SoundFile(str(path)) as handle:
            if (handle.frames, handle.samplerate, handle.channels) != (info["frames"], rate, channels):
                raise ValueError("decoder and WAV metadata disagree")
            handle.seek(offset)
            data = handle.read(frames, dtype="float64", always_2d=True)
        if len(data) != frames or not np.isfinite(data).all() or np.max(np.abs(data)) > 1e6:
            raise ValueError("truncated, nonfinite or unreasonable audio")
        floor = max(ABSOLUTE_FLOOR, float(np.mean(data * data)) * RELATIVE_FLOOR)
        loaded.append((data, floor, _envelope(data, width, np)))

    candidate_count = 0
    if events is None:
        starts, sizes, powers, peaks = loaded[0][2]
        candidates = []
        last = -rate
        for i, start in enumerate(starts):
            if powers[i] <= loaded[0][1] or start - last < round(.05 * rate):
                continue
            earlier = powers[max(0, i - 10):i]
            previous = float(np.mean(earlier)) if len(earlier) else 0
            if previous <= loaded[0][1] or powers[i] >= previous * 10 ** .6:
                candidates.append((int(start), "silence_to_signal" if previous <= loaded[0][1] else "rms_rise"))
                last = start
        candidate_count = len(candidates)
        events = []
        for i, (start, kind) in enumerate(candidates[:120]):
            end = min(frames, start + round(.3 * rate), candidates[i + 1][0] if i + 1 < len(candidates) else frames)
            events.append({"name": f"candidate_{i}", "start_seconds": start / rate,
                "attack_end_seconds": min(end, start + round(.02 * rate)) / rate,
                "body_end_seconds": min(end, start + round(.1 * rate)) / rate,
                "end_seconds": end / rate, "onset_kind": kind,
                "truncated": end < start + round(.3 * rate)})

    outputs = []
    for source, path, info, offset, (data, floor, envelope) in zip(sources, paths, metadata, offsets, loaded):
        meter = pyln.Meter(rate, filter_class="DeMan")

        def measure(start, end):
            if end <= start:
                return {"status": "unavailable", "reason": "empty_event_region", "levels": None,
                    "crest_factor_db": None, "energy_sample_sum": None}
            interval = data[start:end]
            power = float(np.mean(interval * interval))
            levels = _measure(interval, rate, meter, np)
            peak = float(np.max(np.abs(interval)))
            crest = _finite(20 * math.log10(peak) - 10 * math.log10(power)) if power > floor else None
            by_channel = []
            for channel in interval.T:
                p = float(np.mean(channel * channel))
                by_channel.append(_finite(20 * math.log10(float(np.max(np.abs(channel)))) - 10 * math.log10(p)) if p > floor else None)
            return {"start_seconds": start / rate, "end_seconds": end / rate,
                "status": "measured" if power > floor else "silent_or_below_numerical_floor",
                "levels": levels, "crest_factor_db": crest, "crest_factor_by_channel_db": by_channel,
                "energy_sample_sum": float(np.sum(interval * interval) / channels),
                "energy_seconds": float(np.sum(interval * interval) / (channels * rate)),
                "peak_time_seconds": (start + int(np.argmax(np.max(np.abs(interval), axis=1)))) / rate if power > floor else None,
                "dc_offset_by_channel": [float(v) for v in np.mean(interval, axis=0)]}

        whole = measure(0, frames)
        windows = [measure(round(i * window * rate), min(frames, round((i + 1) * window * rate))) for i in range(count)]
        measured_sections = [{"name": s["name"], **measure(round(s["start_seconds"] * rate), round(s["end_seconds"] * rate))} for s in sections]
        measured_events = []
        for e in events:
            bounds = [round(e[k] * rate) for k in ("start_seconds", "attack_end_seconds", "body_end_seconds", "end_seconds")]
            regions = {name: measure(a, b) for name, a, b in zip(("attack", "body", "tail"), bounds, bounds[1:])}

            def contrast(a, b, peak=False):
                left, right = regions[a], regions[b]
                if left["status"] != "measured" or right["status"] != "measured":
                    return None
                return _finite(left["levels"]["sample_peak_dbfs" if peak else "rms_dbfs"] - right["levels"]["rms_dbfs"])

            attack = data[bounds[0]:bounds[1]]
            rise = None
            if len(attack) >= width * 2:
                astart, asize, apower, _ = _envelope(attack, width, np)
                rms = np.sqrt(apower)
                high = float(np.max(rms))
                low_cross = np.flatnonzero(rms >= high * .1)
                high_cross = np.flatnonzero(rms >= high * .9)
                if high * high > floor and len(low_cross) and len(high_cross):
                    rise = float((astart[high_cross[0]] - astart[low_cross[0]]) / rate)
            measured_events.append({**e, "regions": regions,
                "attack_body_rms_db": contrast("attack", "body"), "tail_body_rms_db": contrast("tail", "body"),
                "attack_peak_body_rms_db": contrast("attack", "body", True),
                "attack_envelope_10_90_rise_seconds": rise,
                "status": "measured" if all(r["status"] == "measured" for r in regions.values()) else "partial_or_floor_limited"})
        starts, sizes, power, peaks = envelope
        envelope_summary = []
        for i in range(count):
            lo, hi = round(i * window * rate), min(frames, round((i + 1) * window * rate))
            selected = (starts >= lo) & (starts < hi)
            covered = int(sizes[selected].sum())
            envelope_summary.append({"report_start_seconds": lo / rate, "report_end_seconds": hi / rate,
                "cell_count": int(selected.sum()), "covered_frames": covered,
                "cell_span_start_seconds": float(starts[selected][0] / rate) if selected.any() else None,
                "cell_span_end_seconds": float((starts[selected][-1] + sizes[selected][-1]) / rate) if selected.any() else None,
                "rms_dbfs": _db(float(np.sqrt(np.sum(power[selected] * sizes[selected]) / covered))) if covered else None,
                "sample_peak_dbfs": _db(float(np.max(peaks[selected]))) if selected.any() else None})
        partial = [{"start_seconds": float(start / rate), "end_seconds": float((start + size) / rate),
            "frames": int(size), "rms_dbfs": _db(float(math.sqrt(p))), "sample_peak_dbfs": _db(float(peak))}
            for start, size, p, peak in zip(starts[-1:], sizes[-1:], power[-1:], peaks[-1:]) if size < width]
        outputs.append({**source, "path": str(path), "wav": info, "analyzed_file_start_frame": offset,
            "analyzed_frames": frames, "excluded_leading_frames": offset,
            "excluded_trailing_frames": info["frames"] - offset - frames,
            "numerical_power_floor": floor, "whole_file": whole,
            "local_windows": windows, "sections": measured_sections, "events": measured_events,
            "envelope_summary": {"cell_assignment": "each cell assigned once by start; cell span may extend report boundary",
                "total_cells": len(starts), "represented_cells": sum(i["cell_count"] for i in envelope_summary),
                "windows": envelope_summary, "partial_final_cells": partial},
            "modulation": _modulation(power, sizes, width, rate, floor, np)})

    comparison_report = None
    if len(outputs) == 2:
        before, after = outputs
        a, b = before["whole_file"]["levels"], after["whole_file"]["levels"]
        gain = a["integrated_lufs"] - b["integrated_lufs"] if a["integrated_lufs"] is not None and b["integrated_lufs"] is not None else None

        def delta(left, right):
            measured = left["status"] == right["status"] == "measured"
            values = {"status": "compared" if measured else "unavailable",
                "unavailable_reason": None if measured else "silent_or_floor_limited_region"}
            for key in ("rms_dbfs", "sample_peak_dbfs", "integrated_lufs"):
                x, y = (r["levels"][key] if r["levels"] else None for r in (left, right))
                values[key] = {"original_delta": _finite(y - x) if measured and x is not None and y is not None else None,
                    "lufs_matched_delta": _finite(y + gain - x) if measured and x is not None and y is not None and gain is not None else None}
            x, y = left["crest_factor_db"], right["crest_factor_db"]
            values["crest_factor_delta_db"] = _finite(y - x) if x is not None and y is not None else None
            return values

        starts, sizes, p, _ = loaded[0][2]
        q = loaded[1][2][2]
        valid = (p > loaded[0][1]) & (q > loaded[1][1])
        difference = np.zeros(len(p))
        difference[valid] = 10 * np.log10(q[valid]) - 10 * np.log10(p[valid])
        summary = []
        for i in range(count):
            lo, hi = round(i * window * rate), min(frames, round((i + 1) * window * rate))
            selected = (starts >= lo) & (starts < hi)
            usable = selected & valid
            summary.append({"start_seconds": lo / rate, "end_seconds": hi / rate,
                "cell_span_start_seconds": float(starts[selected][0] / rate) if selected.any() else None,
                "cell_span_end_seconds": float((starts[selected][-1] + sizes[selected][-1]) / rate) if selected.any() else None,
                "eligible_cells": int(usable.sum()), "represented_cells": int(selected.sum()),
                "level_change_mean_db": _finite(np.mean(difference[usable])) if usable.any() else None,
                "level_change_min_db": _finite(np.min(difference[usable])) if usable.any() else None,
                "level_change_max_db": _finite(np.max(difference[usable])) if usable.any() else None})
        paired_events = []
        for left, right in zip(before["events"], after["events"]):
            contrasts = {}
            for key in ("attack_body_rms_db", "tail_body_rms_db", "attack_peak_body_rms_db"):
                x, y = left[key], right[key]
                contrasts[key + "_delta"] = _finite(y - x) if x is not None and y is not None else None
            paired_events.append({"name": left["name"], "start_seconds": left["start_seconds"],
                "regions": {k: delta(left["regions"][k], right["regions"][k]) for k in ("attack", "body", "tail")}, **contrasts})
        comparison_report = {"direction": "comparison minus source", "alignment": alignment,
            "alignment_verification": "caller-declared; not independently verified", "common_frames": frames,
            "comparison_gain_to_source_lufs_db": _finite(gain) if gain is not None else None,
            "matching_status": "available" if gain is not None else "unavailable_integrated_lufs",
            "predicted_matched_comparison_sample_peak_dbfs": _finite(b["sample_peak_dbfs"] + gain) if gain is not None and b["sample_peak_dbfs"] is not None else None,
            "predicted_matched_comparison_sample_peak_headroom_db": _finite(-b["sample_peak_dbfs"] - gain) if gain is not None and b["sample_peak_dbfs"] is not None else None,
            "gain_applied_to_files": False, "whole_file": delta(before["whole_file"], after["whole_file"]),
            "local_windows": [{"start_seconds": x["start_seconds"], "end_seconds": x["end_seconds"], **delta(x, y)} for x, y in zip(before["local_windows"], after["local_windows"])],
            "sections": [{"name": x["name"], **delta(x, y)} for x, y in zip(before["sections"], after["sections"])],
            "events": paired_events, "level_change_envelope": summary,
            "level_change_eligible_cells": int(valid.sum()), "level_change_total_cells": len(valid),
            "level_change_represented_cells": sum(s["represented_cells"] for s in summary),
            "level_change_modulation": _modulation(valid.astype(float), sizes, width, rate, .5, np, levels=difference)}

    return {"schema_version": 1, "processing_complete": True, "complete": True,
        "complete_semantics": "requested processing completed, not full event coverage or acquisition qualification",
        "envelope_coverage_complete": True,
        "event_coverage": {"mode": "caller_defined" if "events" in args else "candidate_onsets",
            "candidate_count": candidate_count if "events" not in args else None, "reported_count": len(events),
            "omitted_candidates": max(0, candidate_count - len(events)),
            "complete": candidate_count <= 120, "detector_is_exhaustive": False},
        "source": outputs[0], "comparison": outputs[1] if len(outputs) == 2 else None,
        "comparison_report": comparison_report, "brief": brief,
        "time_basis": "common-time seconds from declared file offsets" if len(outputs) == 2 else "file-relative seconds",
        "method": {"crest": "sample peak / unweighted RMS; pooled mean channel power and separate per-channel crest",
            "energy": "mean channel sum of squared samples; energy_seconds divides by sample rate",
            "envelope": {"cell_frames": width, "cell_seconds": width / rate, "final_partial_cell_retained": True},
            "events": "source RMS rise >=6 dB vs preceding 100 ms, 50 ms refractory; default 20/100/300 ms regions; explicit regions preferred",
            "rise_time": "first 10% to first 90% of regional maximum linear RMS; quantized to envelope cell; zero means unresolved",
            "modulation": "mean-removed log-RMS envelope, Hann rFFT amplitude per contiguous eligible run; 0.5–10 Hz, >=4 seconds, at most 120 runs, no silent-cell interpolation; strongest reported run summarized",
            "modulation_reporting_floor_db": MODULATION_FLOOR_DB,
            "numerical_floor": {"absolute_power": ABSOLUTE_FLOOR, "relative_to_original_power": RELATIVE_FLOOR},
            "budget": {"max_sample_work": MAX_WORK, "reserved_sample_work": work}},
        "interpretations": ["Reduced crest or attack/body contrast may be consistent with reduced impact under the brief, not automatically worse sound.",
            "Envelope modulation may be consistent with pumping, tremolo, repeated notes or intentional ducking; no cause is inferred.",
            "Paired differences concern the declared same-source experiment only; processing attribution requires retained source/routing/latency evidence."],
        "musical_judgment": "not inferred; no perceived punch score, improvement or retain/revert recommendation",
        "limitations": ["Signal paths/alignment are caller evidence, not physical qualification or human approval.",
            "Sample peak is not true peak; crest is not LRA or perceived punch; DC is retained and can inflate RMS.",
            "Channel energy is not mono compatibility or in-mix source audibility.",
            "10 ms cells can miss/merge fast events; candidate detector is not exhaustive; truncated regions are explicit.",
            "Pumping spectrum requires contiguous non-floor-limited complete cells; final partial cells are excluded from that spectrum only.",
            "Paired level-change envelopes are not literal compressor gain reduction for nonlinear processing or tails.",
            "Whole_file refers to the analyzed common interval in paired mode; excluded frames are retained as metadata.",
            "LUFS matching predicts level/headroom only; original files are untouched; louder alone does not mean better."]}
