"""Bounded, explicitly sectioned musical-development evidence; no Live calls."""
from __future__ import annotations

import math
from pathlib import Path

from audio_capture import validate_wav
from audio_dynamics import _regions, _text, analyze_dynamics
from audio_tonal import analyze_tonal
from audio_balance import analyze_balance
from audio_masking import _listening_condition, _number

TOOL_REQUIRED = ["source", "sections"]
METRICS = {"integrated_lufs": "LU", "rms_dbfs": "dB", "crest_factor_db": "dB",
           "centroid_hz": "Hz", "onset_candidates_per_second": "candidates/s",
           "effective_occupied_band_count": "effective broad bands"}
MAX_WORK = 96_000_000


def tool_properties():
    text = {"type": "string", "minLength": 1, "maxLength": 4096}
    source = {"type": "object", "properties": {k: text for k in ("name", "path", "signal_path")},
              "required": ["name", "path", "signal_path"], "additionalProperties": False}
    section = {"type": "object", "properties": {"name": text,
               "start_seconds": {"type": "number", "minimum": 0},
               "end_seconds": {"type": "number", "exclusiveMinimum": 0}},
               "required": ["name", "start_seconds", "end_seconds"], "additionalProperties": False}
    expectation = {"type": "object", "properties": {
        "from_section": text, "to_section": text, "metric": {"type": "string", "enum": list(METRICS)},
        "expected_delta": {"type": "number"}, "tolerance": {"type": "number", "minimum": .001}},
        "required": ["from_section", "to_section", "metric", "expected_delta", "tolerance"],
        "additionalProperties": False}
    part = {"type": "object", "properties": {"name": text, "path": text},
            "required": ["name", "path"], "additionalProperties": False}
    balance = {"type": "object", "properties": {
        "programme": {"type": "object", "properties": {"name": text, "path": text}, "required": ["path"], "additionalProperties": False},
        "parts": {"type": "array", "items": part, "minItems": 1, "maxItems": 8},
        "alignment": {"type": "object", "properties": {"verified": {"const": True}, "source": text,
            "uncertainty_samples": {"type": "integer", "const": 0},
            "offsets_samples": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}}},
            "required": ["verified", "source", "uncertainty_samples"], "additionalProperties": False},
        "provenance": {"type": "object", "properties": {"disjoint_contributions": {"const": True},
            "in_mix_levels": {"const": True}, "signal_path": text},
            "required": ["disjoint_contributions", "in_mix_levels", "signal_path"], "additionalProperties": False},
        "listening_condition": {"type": "object", "properties": {"kind": {"enum": ["calibrated", "assumed"]},
            "db_spl_at_0_dbfs_rms": {"type": "number"}, "source": text},
            "required": ["kind", "db_spl_at_0_dbfs_rms", "source"], "additionalProperties": False},
        "window_seconds": {"type": "number", "minimum": .1, "maximum": 1},
        "max_windows": {"type": "integer", "minimum": 1, "maximum": 120},
        "window_step_seconds": {"type": "number", "minimum": .001, "maximum": 120}},
        "required": ["programme", "parts", "alignment", "provenance"], "additionalProperties": False,
        "description": "Original in-mix balance. Programme must be the source WAV with zero programme offset; wrapper supplies sections."}
    return {"source": source, "sections": {"type": "array", "items": section, "minItems": 2, "maxItems": 32},
        "brief": {"type": "object", "properties": {"description": text}, "required": ["description"],
                  "additionalProperties": False},
        "expected_contrasts": {"type": "array", "items": expectation, "maxItems": 32},
        "balance": balance}


def _metadata(source):
    path = Path(source["path"]).resolve()
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError("WAV exceeds 128 MiB")
    info = validate_wav(path)
    if info["channels"] not in (1, 2) or not 8000 <= info["sample_rate"] <= 192000:
        raise ValueError("only mono/stereo WAV at 8000–192000 Hz supported")
    if info["frames"] * info["channels"] > 12_000_000 or info["duration_seconds"] > 600:
        raise ValueError("WAV exceeds sample/duration budget")
    return path, info


def _delta(a, b):
    return round(b - a, 3) if a is not None and b is not None else None


def analyze_development(args):
    if not isinstance(args, dict) or set(args) - set(tool_properties()):
        raise ValueError("unknown development argument or non-object arguments")
    source = args.get("source")
    if not isinstance(source, dict) or set(source) != {"name", "path", "signal_path"}:
        raise ValueError("source requires name, path and signal_path")
    for key, value in source.items():
        _text(value, key)
    sections = _regions(args.get("sections"))
    if len(sections) < 2:
        raise ValueError("development requires at least two explicit sections")
    if any(b["start_seconds"] < a["end_seconds"] for a, b in zip(sections, sections[1:])):
        raise ValueError("sections must be chronological and nonoverlapping")
    brief = args.get("brief")
    if "brief" in args:
        if not isinstance(brief, dict) or set(brief) != {"description"}:
            raise ValueError("brief requires description")
        _text(brief["description"], "brief.description")
    expected = args.get("expected_contrasts", [])
    if not isinstance(expected, list) or len(expected) > 32:
        raise ValueError("at most 32 expected contrasts supported")
    if expected and brief is None:
        raise ValueError("expected contrasts require an explicit musical brief")
    names = {s["name"] for s in sections}
    seen = set()
    for e in expected:
        if not isinstance(e, dict) or set(e) != {"from_section", "to_section", "metric", "expected_delta", "tolerance"}:
            raise ValueError("expected contrast requires sections, metric, expected_delta and tolerance")
        if any(not isinstance(e[k], str) for k in ("from_section", "to_section", "metric")):
            raise ValueError("contrast references must be strings")
        if e["from_section"] not in names or e["to_section"] not in names or e["from_section"] == e["to_section"] or e["metric"] not in METRICS:
            raise ValueError("contrast must reference distinct declared sections and a supported metric")
        identity = (e["from_section"], e["to_section"], e["metric"])
        if identity in seen:
            raise ValueError("duplicate expected contrast")
        seen.add(identity)
        for key in ("expected_delta", "tolerance"):
            if isinstance(e[key], bool) or not isinstance(e[key], (int, float)) or not math.isfinite(e[key]) or abs(e[key]) > 1e6:
                raise ValueError("contrast numbers must be finite and bounded by 1e6")
        if e["tolerance"] < .001:
            raise ValueError("tolerance must be at least 0.001 reporting resolution")

    path, info = _metadata(source)
    rate, channels, frames = info["sample_rate"], info["channels"], info["frames"]
    section_frames = 0
    for s in sections:
        start, end = (round(s[k] * rate) for k in ("start_seconds", "end_seconds"))
        if s["end_seconds"] > frames / rate or end <= start:
            raise ValueError("section exceeds source or contains no sample interval")
        section_frames += end - start
    # Same reservations as dynamics and tonal, combined before either decodes.
    work = channels * (7 * frames + 2 * section_frames + min(frames * 120, round(.3 * rate) * 120))
    balance_args = args.get("balance")
    if "balance" in args:
        allowed = {"programme", "parts", "alignment", "provenance", "listening_condition",
                   "window_seconds", "max_windows", "window_step_seconds"}
        if not isinstance(balance_args, dict) or set(balance_args) - allowed:
            raise ValueError("balance requires existing balance arguments without sections or gain scenarios")
        programme = balance_args.get("programme")
        if not isinstance(programme, dict) or set(programme) - {"name", "path"} or not isinstance(programme.get("path"), str):
            raise ValueError("balance programme requires path and optional name")
        if Path(programme["path"]).resolve() != path:
            raise ValueError("balance programme must be the development source WAV")
        parts = balance_args.get("parts")
        if not isinstance(parts, list) or not 1 <= len(parts) <= 8:
            raise ValueError("balance requires 1–8 original in-mix parts")
        alignment = balance_args.get("alignment")
        if not isinstance(alignment, dict) or set(alignment) - {"verified", "source", "uncertainty_samples", "offsets_samples"} or alignment.get("verified") is not True or type(alignment.get("uncertainty_samples")) is not int or alignment["uncertainty_samples"] != 0:
            raise ValueError("balance requires verified zero-uncertainty alignment")
        _text(alignment.get("source"), "alignment.source")
        offsets = alignment.get("offsets_samples")
        programme_offset = offsets.get(programme.get("name", "programme")) if isinstance(offsets, dict) else None
        if offsets is not None and (type(programme_offset) is not int or programme_offset != 0):
            raise ValueError("balance programme offset must be zero for file-relative sections")
        provenance = balance_args.get("provenance")
        if not isinstance(provenance, dict) or set(provenance) != {"disjoint_contributions", "in_mix_levels", "signal_path"} or provenance.get("disjoint_contributions") is not True or provenance.get("in_mix_levels") is not True:
            raise ValueError("balance requires disjoint actual in-mix provenance")
        _text(provenance.get("signal_path"), "provenance.signal_path")
        if "listening_condition" in balance_args:
            _listening_condition(balance_args["listening_condition"])
        for key, low, high in (("window_seconds", .1, 1), ("max_windows", 1, 120), ("window_step_seconds", .001, 120)):
            if key in balance_args:
                _number(balance_args[key], key, low, high)
        if "max_windows" in balance_args and type(balance_args["max_windows"]) is not int:
            raise ValueError("max_windows must be an integer")
        # Conservative reservation for decode/levels/repeats/spectral passes;
        # existing balance performs its own exact bounds and signal-path gates.
        work += 8 * channels * (frames + section_frames)
        for part in parts:
            if not isinstance(part, dict) or set(part) != {"name", "path"}:
                raise ValueError("balance parts require name/path; gain scenarios unsupported")
            for k, v in part.items():
                _text(v, k)
            _, meta = _metadata(part)
            work += 8 * (meta["frames"] * meta["channels"] + section_frames * meta["channels"])
    if work > MAX_WORK:
        raise ValueError("development exceeds combined sample-work budget")

    balance = analyze_balance({**balance_args, "sections": sections}) if balance_args is not None else None
    dynamics = analyze_dynamics({"source": source, "sections": sections})
    tonal = analyze_tonal({"source": source, "sections": sections})
    coverage = dynamics["event_coverage"]
    rows = []
    for s, d, t in zip(sections, dynamics["source"]["sections"], tonal["source"]["sections"]):
        spectrum = t["spectrum"]
        powers = [10 ** (b["power_dbfs"] / 10) for b in spectrum.get("bands", []) if b["power_dbfs"] is not None]
        total = sum(powers)
        effective = math.exp(-sum((p / total) * math.log(p / total) for p in powers)) if total > 0 else None
        events = [e for e in dynamics["source"]["events"] if d["start_seconds"] <= e["start_seconds"] < d["end_seconds"]]
        duration = d["end_seconds"] - d["start_seconds"]
        density = len(events) / duration if coverage["complete"] else None
        values = {k: d["levels"][k] for k in ("integrated_lufs", "rms_dbfs")}
        values.update(crest_factor_db=d["crest_factor_db"], centroid_hz=spectrum.get("centroid_hz"),
                      onset_candidates_per_second=round(density, 3) if density is not None else None,
                      effective_occupied_band_count=round(effective, 3) if effective is not None else None)
        rows.append({"name": s["name"], "start_seconds": d["start_seconds"], "end_seconds": d["end_seconds"],
            "duration_seconds": duration, "metrics": values, "original_levels": d["levels"], "spectrum": spectrum,
            "temporal_density": {"reported_candidate_count": len(events), "rate_status": "measured_proxy" if coverage["complete"] else "unavailable_capped_candidates",
                "candidate_timing_resolution_seconds": .01, "exhaustive_musical_events": False,
                "candidates": [{k: e[k] for k in ("name", "start_seconds", "attack_end_seconds", "body_end_seconds", "end_seconds", "onset_kind", "truncated", "status")} |
                    {"region_outcomes": {k: {"status": region["status"], "reason": region.get("reason")}
                                         for k, region in e["regions"].items()}} for e in events]},
            "balance": [{"name": p["name"], "measurement": p["original"]["sections"][len(rows)]["measurement"],
                         "relative_to_programme_lu": p["sections_relative_to_programme"][len(rows)]["integrated_delta_lu"]} for p in balance["parts"]] if balance else None})
    by_name = {r["name"]: r for r in rows}
    contrasts = [{"from_section": a["name"], "to_section": b["name"],
                  "deltas": {k: _delta(a["metrics"][k], b["metrics"][k]) for k in METRICS},
                  "part_balance_deltas": [{"name": x["name"],
                      "integrated_delta_lu": _delta(x["measurement"]["integrated_lufs"], y["measurement"]["integrated_lufs"]),
                      "relative_to_programme_delta_lu": _delta(x["relative_to_programme_lu"], y["relative_to_programme_lu"])}
                      for x, y in zip(a["balance"] or [], b["balance"] or [])]}
                 for a, b in zip(rows, rows[1:])]
    departures = []
    for e in expected:
        actual = _delta(by_name[e["from_section"]]["metrics"][e["metric"]], by_name[e["to_section"]]["metrics"][e["metric"]])
        deviation = _delta(e["expected_delta"], actual)
        departures.append({**e, "unit": METRICS[e["metric"]], "observed_delta": actual, "deviation": deviation,
            "status": "unavailable" if deviation is None else "within_declared_expectation" if abs(deviation) <= e["tolerance"] else "outside_declared_expectation"})
    return {"schema_version": 1, "processing_complete": True, "complete": True,
        "complete_semantics": "requested processing, not exhaustive density, spectral coverage or acquisition qualification",
        "source": {**source, "path": str(path), "wav": info}, "time_basis": "file-relative seconds; sample-rounded boundaries",
        "brief": brief, "measured_facts": {"sections": rows, "adjacent_contrasts": contrasts, "units": METRICS},
        "perceptual_estimates": balance if balance else {"status": "unavailable", "reason": "aligned disjoint in-mix balance evidence not supplied"},
        "expectation_departures": departures, "musical_judgment": "not inferred; contrasts are observations, not arrangement faults or keep/revert decisions",
        "coverage": {"events": coverage, "spectrum_complete": tonal["spectrum_coverage_complete"],
                     "spectrum_incomplete_reasons": tonal["spectrum_coverage_incomplete_reasons"]},
        "method": {"dynamics": dynamics["method"], "tonal": tonal["method"],
            "temporal_density": "existing >=6 dB 10 ms RMS-rise / silence-to-signal candidates; 50 ms refractory; count divided by sample-rounded section duration",
            "spectral_density": "exp(Shannon entropy) of six broad-band powers over Nyquist-covered bands; floor-limited bands excluded; rounded input powers",
            "contrast_direction": "to minus from; original levels retained; no gain applied",
            "budget": {"reserved_sample_work": work, "max_sample_work": MAX_WORK}},
        "limitations": ["Density proxies are neither note/sound counts nor polyphony, arrangement understanding or musical quality.",
            "Candidate detector is nonexhaustive; capped candidate rates are unavailable, and timing resolution can merge fast events.",
            "Broad-band entropy is spectral spread, affected by unequal band widths and Nyquist coverage; not active source count.",
            "Welch omissions and numerical floors remain explicit; short or silent spectra cannot establish missing density.",
            "Part-to-programme separately gated LUFS differences do not prove prominence or additive contributions.",
            "Signal path, alignment and in-mix provenance are caller declarations, not acquisition qualification.",
            "No universal targets, causal attribution, listening approval or autonomous retain/revert recommendation."]}
