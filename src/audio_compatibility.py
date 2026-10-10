"""Bounded offline compatibility evidence, never a musical-quality verdict."""
import math
from pathlib import Path

from audio_masking import analyze_masking, _number, _text
from audio_capture import validate_wav

TOOL_REQUIRED = ["target", "competitors", "alignment", "provenance"]


def tool_properties():
    source = {"type": "object", "additionalProperties": False,
        "required": ["name", "path", "signal_path"], "properties": {
            key: {"type": "string", "minLength": 1, "maxLength": 128 if key == "name" else 1024}
            for key in ("name", "path", "signal_path")}}
    source["properties"]["gain_db"] = {"type": "number", "minimum": -60, "maximum": 60}
    return {
        "target": source,
        "competitors": {"type": "array", "minItems": 1, "maxItems": 8, "items": source},
        "alignment": {"type": "object", "additionalProperties": False,
            "required": ["verified", "source", "uncertainty_samples"], "properties": {
                "verified": {"const": True}, "source": {"type": "string", "minLength": 1, "maxLength": 1024},
                "uncertainty_samples": {"type": "integer", "const": 0},
                "offsets_samples": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}}}},
        "provenance": {"type": "object", "additionalProperties": False,
            "required": ["disjoint_contributions", "in_mix_levels", "signal_path"], "properties": {
                "disjoint_contributions": {"const": True}, "in_mix_levels": {"const": True},
                "signal_path": {"type": "string", "minLength": 1, "maxLength": 1024}}},
        "window_seconds": {"type": "number", "minimum": .1, "maximum": 1, "default": .1},
        "max_windows": {"type": "integer", "minimum": 1, "maximum": 120, "default": 120},
        "listening_condition": {"type": "object", "additionalProperties": False,
            "required": ["kind", "db_spl_at_0_dbfs_rms", "source"], "properties": {
                "kind": {"enum": ["calibrated", "assumed"]},
                "db_spl_at_0_dbfs_rms": {"type": "number", "minimum": 0, "maximum": 140},
                "source": {"type": "string", "minLength": 1, "maxLength": 1024}}},
        "sections": {"type": "array", "maxItems": 32, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "start_seconds", "end_seconds"], "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 1024},
                "start_seconds": {"type": "number", "minimum": 0, "maximum": 120},
                "end_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 120}}}},
        "brief": {"type": "object", "additionalProperties": False, "required": ["description"],
            "properties": {"description": {"type": "string", "minLength": 1, "maxLength": 1024}}}}


def _partials(data, rate, np):
    """Resolved FFT-bin maxima; channel power averaging avoids mono cancellation."""
    length = len(data)
    window = np.hanning(length)
    power = np.mean(np.abs(np.fft.rfft(data * window[:, None], axis=0)) ** 2, axis=1)
    power /= length * np.sum(window ** 2)
    power[1:-1 if length % 2 == 0 else None] *= 2
    frequencies = np.fft.rfftfreq(length, 1 / rate)
    indices = np.arange(1, len(power) - 1)
    floor = max(1e-20, float(np.max(power)) * 1e-4)
    candidates = indices[(power[indices] > power[indices - 1]) &
        (power[indices] >= power[indices + 1]) & (power[indices] > floor) &
        (frequencies[indices] >= 20)]
    retained = candidates[np.argsort(power[candidates])[::-1][:12]]
    return [(float(frequencies[i]), math.sqrt(float(power[i]))) for i in retained], {
        "candidate_count": len(candidates), "retained_count": len(retained),
        "omitted_candidates": max(0, len(candidates) - 12), "frequency_bin_hz": rate / length,
        "frequency_region_hz": [20, float(frequencies[-2])],
        "retained_peak_power_fraction": float(np.sum(power[retained]) / np.sum(power)) if np.sum(power) > 1e-20 else None}


def _roughness(first, second):
    """Sethares kernel, explicitly normalized cross-source amplitude products."""
    denominator = sum(a * a for _, a in first + second)
    if not first or not second or denominator <= 1e-20:
        return None
    total = 0.0
    for f, a in first:
        for g, b in second:
            distance = .24 * abs(f - g) / (.0207 * min(f, g) + 18.96)
            total += a * b * (math.exp(-3.5 * distance) - math.exp(-5.75 * distance))
    return total / denominator


def _relationships(first, second, resolution):
    if not first or not second:
        return {"status": "unavailable", "reason": "No retained resolved partials in one or both sources", "pairs": []}
    # Top three amplitude-product pairs, not an exhaustive harmonic inventory.
    pairs = sorted(((a * b, f, g) for f, a in first for g, b in second), reverse=True)[:3]
    result = []
    for _, f, g in pairs:
        ratio = g / f
        numerator, denominator = min(((n, d) for n in range(1, 9) for d in range(1, 9)),
            key=lambda pair: (abs(math.log2(ratio / (pair[0] / pair[1]))), sum(pair)))
        divisor = math.gcd(numerator, denominator)
        low_f, low_g = max(f - resolution, 1e-9), max(g - resolution, 1e-9)
        cents = 1200 * math.log2(ratio / (numerator / denominator))
        result.append({"target_partial_hz": f, "competitor_partial_hz": g,
            "frequency_ratio": ratio, "nearest_integer_ratio": [numerator // divisor, denominator // divisor],
            "cents_from_ratio": cents,
            "resolution_cents_interval": [1200 * math.log2(low_g / (f + resolution) / (numerator / denominator)),
                1200 * math.log2((g + resolution) / low_f / (numerator / denominator))]})
    return {"status": "resolved_spectral_partial_relationships", "confidence": "FFT-bin resolution bound, not pitch-recognition confidence",
        "pairs": result, "omitted_pair_count": len(first) * len(second) - len(result)}


def analyze_compatibility(args):
    if not isinstance(args, dict) or set(args) - set(tool_properties()):
        raise ValueError("unknown compatibility argument or non-object arguments")
    competitors = args.get("competitors")
    if not isinstance(competitors, list) or not 1 <= len(competitors) <= 8:
        raise ValueError("competitors must contain 1 to 8 named WAVs")
    sources = [args.get("target"), *competitors]
    for source in sources:
        if not isinstance(source, dict) or set(source) - {"name", "path", "signal_path", "gain_db"}:
            raise ValueError("sources require name, path, signal_path and optional gain_db")
        for key in ("name", "path", "signal_path"):
            _text(source.get(key), key)
    brief = args.get("brief")
    if "brief" in args:
        if not isinstance(brief, dict) or set(brief) != {"description"}:
            raise ValueError("brief requires description only")
        _text(brief["description"], "brief.description")
    masking_args = {key: value for key, value in args.items() if key != "brief"}
    masking_sources = [{key: value for key, value in s.items() if key != "signal_path"} for s in sources]
    masking_args.update(target=masking_sources[0], competitors=masking_sources[1:])
    paths = [Path(s["path"]).resolve() for s in sources]
    stamps = [(p.stat().st_size, p.stat().st_mtime_ns) for p in paths]
    if any(size > 128 * 1024 * 1024 for size, _ in stamps):
        raise ValueError("WAV exceeds file byte budget")
    metadata = [validate_wav(p) for p in paths]
    # Reserve both decodes, both spectral passes, direct RMS timing, and optional
    # perceptual spectra (50% overlap: <=2 traversals) before DSP. Full-file reservation is conservative for
    # offset-trimmed common intervals. Roex computation has its own tighter cap.
    sample_work = (7 if "listening_condition" in args else 5) * sum(m["frames"] * m["channels"] for m in metadata)
    if sample_work > 96_000_000:
        raise ValueError("compatibility exceeds total sample-work budget")
    competition = analyze_masking(masking_args)
    import numpy as np
    import soundfile as sf
    from contextlib import ExitStack

    rate = competition["sample_rate"]
    frames = min(s["wav"]["frames"] - s["offset_samples"] for s in competition["sources"])
    width = round(_number(args.get("window_seconds", .1), "window_seconds", .1, 1) * rate)
    cell_width = round(.01 * rate)
    gains = [10 ** (s.get("gain_db", 0) / 20) for s in sources]
    for section in args.get("sections", []):
        if round(section["end_seconds"] * rate) <= round(section["start_seconds"] * rate):
            raise ValueError("section contains no sample interval")
    windows, perceptual_windows = [], []
    with ExitStack() as stack:
        handles = []
        for path, source, stamp in zip(paths, competition["sources"], stamps):
            if (path.stat().st_size, path.stat().st_mtime_ns) != stamp:
                raise ValueError("WAV changed during analysis")
            handle = stack.enter_context(sf.SoundFile(str(path)))
            if (handle.frames, handle.samplerate, handle.channels) != (source["wav"]["frames"], rate, competition["channels"]):
                raise ValueError("decoder and WAV metadata disagree")
            handle.seek(source["offset_samples"])
            handles.append(handle)
        for start in range(0, frames, width):
            length = min(width, frames - start)
            powers, peaks, extraction = [], [], []
            sizes = np.array([min(cell_width, length - i) for i in range(0, length, cell_width)])
            for handle in handles:
                data = handle.read(length, dtype="float64", always_2d=True)
                if len(data) != length or not np.isfinite(data).all() or np.max(np.abs(data)) > 1e6:
                    raise ValueError("WAV truncated, changed, nonfinite or unreasonably large")
                power = np.mean(data * data, axis=1)
                powers.append(np.array([float(np.mean(power[i:i + cell_width])) for i in range(0, length, cell_width)]))
                if length >= round(.1 * rate):
                    partials, details = _partials(data, rate, np)
                else:
                    partials, details = [], {"status": "unavailable", "reason": "Spectral tail shorter than 100 ms"}
                peaks.append(partials)
                extraction.append(details)
            activity = [p > max(1e-20, float(np.max(p)) * 1e-8) for p in powers]
            pairs, roughness_pairs = [], []
            for index, source in enumerate(sources[1:], 1):
                both = activity[0] & activity[index]
                exposed = activity[0] & ~activity[index]
                scenario_first = [(f, a * gains[0]) for f, a in peaks[0]]
                scenario_second = [(f, a * gains[index]) for f, a in peaks[index]]
                original_roughness = _roughness(peaks[0], peaks[index])
                scenario_roughness = _roughness(scenario_first, scenario_second)
                pairs.append({"competitor": source["name"],
                    "timing": {"target_active_seconds": float(np.sum(sizes[activity[0]]) / rate),
                        "competitor_active_seconds": float(np.sum(sizes[activity[index]]) / rate),
                        "joint_active_seconds": float(np.sum(sizes[both]) / rate),
                        "target_exposed_seconds": float(np.sum(sizes[exposed]) / rate)},
                    "partial_relationships": _relationships(peaks[0], peaks[index], rate / length)})
                roughness_pairs.append({"competitor": source["name"],
                    "roughness": {"original": original_roughness,
                        "gain_scenario": scenario_roughness,
                        "units": "dimensionless normalized cross-partial interaction", "status": "estimated" if peaks[0] and peaks[index] else "unavailable",
                        "gain_scenario_status": "estimated" if scenario_roughness is not None else "unavailable",
                        "unavailable_reason": None if original_roughness is not None and scenario_roughness is not None else "No retained partials, short spectral tail or retained total power <=1e-20"}})
            perceptual_windows.append({"start_seconds": start / rate, "end_seconds": (start + length) / rate, "pairs": roughness_pairs})
            all_competitors = np.any(np.asarray(activity[1:]), axis=0)
            windows.append({"start_seconds": start / rate, "end_seconds": (start + length) / rate,
                "target_exposed_from_all_seconds": float(np.sum(sizes[activity[0] & ~all_competitors]) / rate),
                "timing_cell_count": len(sizes), "partial_final_cell_frames": int(sizes[-1]) if sizes[-1] < cell_width else 0,
                "source_spectra": [{"name": s["name"], "partials": [{"frequency_hz": f, "amplitude": a} for f, a in p],
                    "extraction": e} for s, p, e in zip(sources, peaks, extraction)], "pairs": pairs,
                "overlapping_sections": [s["name"] for s in args.get("sections", [])
                    if s["start_seconds"] < (start + length) / rate and s["end_seconds"] > start / rate]})
    if any((p.stat().st_size, p.stat().st_mtime_ns) != stamp for p, stamp in zip(paths, stamps)):
        raise ValueError("WAV changed during analysis")
    return {"schema_version": 1, "processing_complete": True,
        "sources": [{**s, "path": str(p)} for s, p in zip(sources, paths)],
        "alignment": args["alignment"], "provenance": args["provenance"],
        "brief": brief, "sections": args.get("sections", []),
        "measured_facts": {"frequency_competition": competition, "windows": windows},
        "perceptual_estimates": {"windows": perceptual_windows,
            "target_prominence": competition["perceptual_model"]},
        "distinguishability": {"status": "human_distinguishability_unavailable",
            "evidence": "Measured timing exposure and roex competition; optional listening-dependent modeled target prominence",
            "reason": "Spectral competition, threshold excess and roughness do not establish recognition or human source separation"},
        "musical_judgment": {"status": "unavailable", "reason": "No universal compatibility, quality or keep/revert verdict"},
        "coverage": {"timing_duration_seconds": frames / rate, "spectral_duration_seconds": competition["coverage"]["analyzed_duration_seconds"],
            "unmeasured_spectral_tail_seconds": competition["unmeasured_tail_seconds"],
            "time_basis": competition["coverage"]["time_basis"], "sample_work_reserved": sample_work},
        "method": {"timing": "Direct channel-mean 10 ms RMS cells, actual partial-cell durations; power > max(1e-20, per-source reporting-window peak cell power * 1e-8). Original levels, not human audibility.",
            "partials": "Channel-mean Hann one-sided FFT-bin power; local maxima >=20 Hz excluding DC/Nyquist endpoint; >-40 dB relative to strongest bin and >1e-20 power; retain top12. Bin frequencies, not interpolated f0.",
            "relationships": "Top3 cross-source amplitude-product pairs; nearest ratio of integers 1..8, signed cents. +/-one-bin sensitivity interval is not statistical confidence or a voicedness test.",
            "roughness": "Sum a*b*(exp(-3.5*d)-exp(-5.75*d))/sum(all retained a^2), d=0.24*abs(f-g)/(0.0207*min(f,g)+18.96). Cross-source only; pair-specific normalization adaptation, not standardized dissonance units.",
            "reference": "Sethares (1993), Local consonance and the relationship between timbre and scale, JASA 94:1218-1228, doi:10.1121/1.408175; critical-band dissonance basis: Plomp & Levelt (1965), JASA 38:548-560, doi:10.1121/1.1909741",
            "gain_scenarios": "Explicit offline source amplitude gains applied only to roughness/competition estimates; original measurements retained. No file mutation or loudness normalization.",
            "sections": "Window overlap labels only; boundary windows include audio outside the section. No exact section summary inferred."},
        "limitations": ["Declarations do not independently establish acquisition/routing/alignment qualification.",
            "Resolved partials are not fundamental pitch, chord/key recognition, consonance approval or evidence that a source is voiced. Noise and transients can have spectral maxima.",
            "Stationary Hann spectra underweight endpoint transients; 100 ms windows resolve at best 10 Hz. Time-varying/voiced pitch and within-window beating are not tracked.",
            "Roughness uses only retained spectral peaks, omits residual noise, source self-roughness, phase/interference, temporal and binaural effects. Normalized estimates are not SPL-dependent listening judgments.",
            "Timing activity is numerical signal presence at disclosed floors, not audible exposure. Cells/windows quantize timing and may mix boundaries.",
            "Top partial/pair caps and reported frequency region limit coverage; spectral silence and sub100ms tails have unavailable relationships/roughness.",
            "Target prominence is optional and retains the existing adapted simultaneous-masking model limitations; no human distinguishability or music-quality score."]}
