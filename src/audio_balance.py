"""Verified aligned post-mixer loudness facts plus explicit perceptual estimates."""
from __future__ import annotations

from pathlib import Path

from audio_capture import validate_wav
from audio_analysis import _analyze_file
from audio_masking import analyze_masking, _number, _text


def analyze_balance(args):
    allowed = {"programme", "parts", "alignment", "provenance", "sections", "expected_section_differences",
               "listening_condition", "window_seconds", "max_windows", "window_step_seconds", "fair_loudness_match"}
    if not isinstance(args, dict) or set(args) - allowed:
        raise ValueError("unknown balance argument or non-object arguments")
    programme = args.get("programme")
    parts = args.get("parts")
    if not isinstance(programme, dict) or set(programme) - {"name", "path"}:
        raise ValueError("programme requires path and optional name")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 8:
        raise ValueError("parts must contain 1 to 8 disjoint in-mix contributions")
    programme = {"name": programme.get("name", "programme"), "path": programme.get("path")}
    _text(programme["name"], "programme.name")
    _text(programme["path"], "programme.path")
    if any(not isinstance(p, dict) for p in parts):
        raise ValueError("each part must be an object")
    names = [p.get("name") for p in parts]
    for name in names:
        _text(name, "part.name")
    if len(set(names)) != len(names):
        raise ValueError("part names must be unique")
    if programme["name"] in names:
        raise ValueError("programme name must differ from all parts")
    alignment = args.get("alignment")
    if not isinstance(alignment, dict):
        raise ValueError("explicit verified alignment required")
    offsets = alignment.get("offsets_samples")
    if offsets is not None and (not isinstance(offsets, dict) or set(offsets) != set(names + [programme["name"]])):
        raise ValueError("offsets_samples must include programme and every part")
    part_alignment = dict(alignment)
    if offsets is not None:
        part_alignment["offsets_samples"] = {n: offsets[n] for n in names}
    masking_args = {"target": parts[0], "competitors": parts[1:], "alignment": part_alignment,
                    "provenance": args.get("provenance")}
    for key in ("listening_condition", "sections", "window_seconds", "max_windows"):
        if key in args:
            masking_args[key] = args[key]
    metadata = []
    for part in parts:
        path = Path(_text(part.get("path"), "part.path")).resolve()
        if path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("part exceeds file byte budget")
        metadata.append(validate_wav(path))
    programme_path = Path(programme["path"]).resolve()
    if programme_path in [Path(p["path"]).resolve() for p in parts]:
        raise ValueError("programme cannot reuse a contribution path")
    if programme_path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("programme exceeds file byte budget")
    info = validate_wav(programme_path)
    if any((info["sample_rate"], info["channels"]) != (m["sample_rate"], m["channels"]) for m in metadata):
        raise ValueError("programme and parts must have identical rate/channel layout")
    if info["frames"] * info["channels"] > 12_000_000 or info["duration_seconds"] > 120:
        raise ValueError("programme exceeds sample/duration budget")
    if sum(m["frames"] * m["channels"] for m in metadata + [info]) > 48_000_000:
        raise ValueError("programme and parts exceed total sample budget")
    all_offsets = offsets or dict.fromkeys(names + [programme["name"]], 0)
    po = all_offsets[programme["name"]]
    if isinstance(po, bool) or not isinstance(po, int) or not 0 <= po < info["frames"]:
        raise ValueError("programme offset must be a frame index inside its file")
    if offsets is None and info["frames"] != metadata[0]["frames"]:
        raise ValueError("programme length must match parts without explicit offsets")
    for n, m in zip(names, metadata):
        if isinstance(all_offsets[n], bool) or not isinstance(all_offsets[n], int) or not 0 <= all_offsets[n] < m["frames"]:
            raise ValueError("part offset must be a frame index inside its file")
    frames = min([info["frames"] - po] + [m["frames"] - all_offsets[n] for m, n in zip(metadata, names)])
    rate = info["sample_rate"]
    # One decoding/spectral pass per source, reused for each target scenario.
    # Bound the entire workflow's decoded samples, not just each nested call.
    decoded_work = info["frames"] * info["channels"] + sum(
        m["frames"] * m["channels"] * (3 if p.get("gain_db", 0) else 2)
        for m, p in zip(metadata, parts))
    if decoded_work > 96_000_000:
        raise ValueError("balance exceeds total decoded analysis sample budget")
    spectral_cache = {}
    first_masking = analyze_masking(masking_args, frame_limit=frames, spectral_cache=spectral_cache, allow_no_competitors=True)
    sections = args.get("sections", [])
    if any(s["end_seconds"] > frames / rate for s in sections):
        raise ValueError("section exceeds common programme interval")
    expected = args.get("expected_section_differences", [])
    if not isinstance(expected, list) or len(expected) > 32:
        raise ValueError("expected_section_differences must contain at most 32 entries")
    section_names = {s["name"] for s in sections}
    for e in expected:
        if not isinstance(e, dict) or set(e) != {"from_section", "to_section", "expected_delta_lu", "tolerance_lu"}:
            raise ValueError("expected differences require from_section, to_section, expected_delta_lu, tolerance_lu")
        if e["from_section"] not in section_names or e["to_section"] not in section_names:
            raise ValueError("expected differences must reference declared sections")
        _number(e["expected_delta_lu"], "expected_delta_lu", -120, 120)
        # Two independently rounded .001-LU measurements contribute up to
        # .001 LU combined quantization error; finer judgments are unsupported.
        _number(e["tolerance_lu"], "tolerance_lu", 0.001, 120)
    match = args.get("fair_loudness_match")
    if match is not None:
        if not isinstance(match, dict) or set(match) != {"target_lufs"}:
            raise ValueError("fair_loudness_match requires target_lufs")
        _number(match["target_lufs"], "target_lufs", -70, 0)
    step = args.get("window_step_seconds")
    if step is not None:
        _number(step, "window_step_seconds", 0.001, 120)
    import numpy as np
    import soundfile as sf
    import pyloudnorm as pyln
    budget = [96_000_000]
    measure = lambda p, n, g=0: _analyze_file(Path(p).resolve(), sections, step, np, sf, pyln, budget,
                                           offset_frames=all_offsets[n], common_frames=frames, gain_db=g)
    prog = measure(programme["path"], programme["name"])
    results = []
    for index, part in enumerate(parts):
        original = measure(part["path"], part["name"])
        gain = part.get("gain_db", 0)
        scenario = measure(part["path"], part["name"], gain) if gain else original
        integrated = original["whole_file"]["integrated_lufs"]
        p_lufs = prog["whole_file"]["integrated_lufs"]
        item = {"name": part["name"], "path": part["path"], "gain_db": gain, "original": original,
                "gain_scenario": scenario, "relative_integrated_lu": round(integrated - p_lufs, 3) if integrated is not None and p_lufs is not None else None,
                "local_relative_to_programme": []}
        scenario_lufs = scenario["whole_file"]["integrated_lufs"]
        item["gain_scenario_relative_integrated_lu"] = round(scenario_lufs - p_lufs, 3) if scenario_lufs is not None and p_lufs is not None else None
        for p, m in zip(original["local_windows"]["values"], prog["local_windows"]["values"]):
            item["local_relative_to_programme"].append({"end_seconds": p["end_seconds"], **{
                key.replace("lufs", "delta_lu"): round(p[key] - m[key], 3) if p[key] is not None and m[key] is not None else None
                for key in ("momentary_lufs", "short_term_lufs")}})
        item["sections_relative_to_programme"] = [{"name": p["name"], "integrated_delta_lu":
            round(p["measurement"]["integrated_lufs"] - m["measurement"]["integrated_lufs"], 3)
            if p["measurement"]["integrated_lufs"] is not None and m["measurement"]["integrated_lufs"] is not None else None}
            for p, m in zip(original["sections"], prog["sections"])]
        if match is not None:
            required = match["target_lufs"] - integrated if integrated is not None else None
            peak = original["whole_file"]["sample_peak_dbfs"]
            item["fair_loudness_match"] = {"target_lufs": match["target_lufs"], "suggested_gain_db": round(required, 3) if required is not None else None,
                "predicted_sample_peak_dbfs": round(peak + required, 3) if peak is not None and required is not None else None,
                "would_exceed_unit_sample_peak": peak + required > 0 if peak is not None and required is not None else None,
                "applied": False, "purpose": "Isolated comparison only; changes in-mix balance. Re-measure after gain: BS.1770 absolute gating can change."}
        if "listening_condition" in args:
            model_args = {**masking_args, "target": part, "competitors": parts[:index] + parts[index + 1:]}
            # The model is already frame-limited to the programme interval.
            model = first_masking if index == 0 else analyze_masking(model_args, frame_limit=frames, spectral_cache=spectral_cache, allow_no_competitors=True)
            item["perceptual_prominence"] = {"model": model["perceptual_model"], "windows": model["windows"],
                                             "sections": model.get("sections", []), "modeled_masking_summary": model.get("modeled_masking_summary")}
            analyzed_end = item["perceptual_prominence"]["windows"][-1]["end_seconds"] if item["perceptual_prominence"]["windows"] else 0
            item["perceptual_prominence"]["coverage"] = {"analyzed_duration_seconds": analyzed_end,
                "unmeasured_tail_seconds": round(frames / rate - analyzed_end, 6), "complete": abs(frames / rate - analyzed_end) < 1e-6}
        else:
            item["perceptual_prominence"] = {"status": "unavailable", "reason": "explicit listening_condition required"}
        results.append(item)
    interpretations = []
    section_map = {s["name"]: s["measurement"]["integrated_lufs"] for s in prog["sections"]}
    for e in expected:
        a, b = section_map[e["from_section"]], section_map[e["to_section"]]
        actual = b - a if a is not None and b is not None else None
        deviation = actual - e["expected_delta_lu"] if actual is not None else None
        interpretations.append({**e, "observed_delta_lu": round(actual, 3) if actual is not None else None,
            "deviation_lu": round(deviation, 3) if deviation is not None else None,
            "judgment": "unmeasurable" if deviation is None else "within_declared_expectation" if abs(deviation) <= e["tolerance_lu"] else "outside_declared_expectation"})
    model_available = "listening_condition" in args
    model_complete = model_available and all(p["perceptual_prominence"].get("coverage", {}).get("complete", False) for p in results)
    return {"schema_version": 1, "complete": model_complete, "measurement_complete": True,
        "perceptual_estimation_complete": model_complete,
        "incomplete_reasons": [] if model_complete else ["Explicit listening_condition required for perceptual prominence and absolute masking thresholds"]
            if not model_available else ["Perceptual analysis leaves a short common-interval tail unmeasured"],
        "alignment": alignment, "provenance": args["provenance"],
        "listening_condition": args.get("listening_condition"), "programme": {"name": programme["name"], **prog}, "parts": results,
        "common_duration_seconds": frames / rate, "section_expectations": interpretations,
        "evidence": {"measured": "BS.1770 LUFS, RMS, sample peak and aligned local/section part-to-programme differences",
                     "modeled": "MPEG-1-adapted threshold margins and threshold-excess spectral prominence; not sones or human audibility probability",
                     "judgments": "Only deviations from caller-declared section expectations; no universal quality score"},
        "judgment_precision": {"loudness_report_resolution_lu": 0.001,
            "section_difference_maximum_rounding_error_lu": 0.001, "minimum_tolerance_lu": 0.001,
            "interpretation": "Judgments compare reported quantized measurements; tolerances below combined rounding resolution are rejected"},
        "limitations": ["Verified alignment and post-mixer disjoint contributions are caller evidence, not independently verified here.",
            "Programme remains original in gain scenarios; no recomputed master through unknown nonlinear processing.",
            "Separately gated integrated loudness differences are descriptive, not additive energy fractions or prominence ranks.",
            "Local windows share sample time and filtering definitions; no absolute monitor calibration inferred.",
            "Perceptual section summaries exclude partial windows. Threshold excess is a spectral model indicator, not standardized partial loudness."]}
