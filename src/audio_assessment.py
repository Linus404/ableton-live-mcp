"""Fail-closed offline adapter from qualified capture evidence to balance analysis."""
from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path

from audio_capture import validate_wav


def _verify_partition_exclusions(manifest):
    excluded = manifest.get("unsupported_tracks", [])
    if not isinstance(excluded, list):
        raise ValueError("unsupported capture entries must be a list")
    if not excluded:
        return
    requested = manifest.get("requested")
    if not isinstance(requested, dict):
        raise ValueError("partition exclusions require retained exact selection provenance")
    selected = requested.get("track_refs", [])
    if not isinstance(selected, list) or any(not isinstance(r, dict) or not set(r) & {"id", "path"}
            or set(r) - {"id", "path"} or ("id" in r and (type(r["id"]) is not int or r["id"] <= 0))
            or ("path" in r and (not isinstance(r["path"], str) or not r["path"].strip())) for r in selected):
        raise ValueError("partition exclusions require exact selected track references")
    routing = manifest.get("routing_profile")
    profile = routing.get("tracks") if isinstance(routing, dict) else None
    if not isinstance(profile, list) or any(not isinstance(t, dict) or not isinstance(t.get("ref"), dict)
            or type(t["ref"].get("id")) is not int or t["ref"]["id"] <= 0 for t in profile):
        raise ValueError("partition exclusions require a verified routing graph")
    by_id = {t["ref"]["id"]: t for t in profile}
    if len(by_id) != len(profile):
        raise ValueError("routing graph has ambiguous track identities")
    captured = {t.get("ref", {}).get("id") for t in manifest["tracks"] if t.get("role") == "contribution"}
    for entry in excluded:
        if not isinstance(entry, dict) or entry.get("reason") not in {"nonterminal_or_nonmaster_route", "no_audio_output_or_unknown_capability"}:
            raise ValueError("assessment refuses unsupported selected capture entries")
        ref = entry.get("ref")
        if not isinstance(ref, dict) or type(ref.get("id")) is not int or not isinstance(ref.get("path"), str) or not ref["path"]:
            raise ValueError("excluded source identity cannot be pinned")
        if any(("id" in r and r["id"] == ref["id"]) or ("path" in r and r["path"].split() == ref["path"].split()) for r in selected):
            raise ValueError("an explicitly selected source was excluded")
        if ref["id"] in captured:
            raise ValueError("a captured contribution is also marked excluded")
        current, seen = by_id.get(ref["id"]), set()
        # Native snapshot includes only requested regulars when track_refs exists.
        if "track_refs" in requested and current is not None and current.get("kind") in ("track", "group"):
            raise ValueError("an explicitly selected regular source was excluded")
        if current is not None and current.get("has_audio_output") is False:
            continue
        if entry["reason"] != "nonterminal_or_nonmaster_route":
            raise ValueError("excluded source lacks proven non-audio capability")
        while current:
            identity = current["ref"]["id"]
            parent = by_id.get((current.get("parent_ref") or {}).get("id"))
            if identity in seen or identity in captured or current.get("is_grouped") is not True or not parent or parent.get("kind") != "group":
                raise ValueError("excluded source has no captured terminal group coverage")
            seen.add(identity)
            name = parent.get("name")
            if not isinstance(name, str) or not name or sum(t.get("name") == name for t in profile) != 1:
                raise ValueError("group routing name is ambiguous")
            route = current.get("output_type")
            if route != name or current.get("output_channel") not in ("", "Track In"):
                raise ValueError("excluded source does not route into its containing group")
            if parent["ref"]["id"] in captured:
                if parent.get("output_type") not in ("Main", "Master"):
                    raise ValueError("captured group is not a terminal programme contribution")
                break
            current = parent
        else:
            raise ValueError("excluded source routing identity is unavailable")


def assess_audio(args):
    options = {"listening_condition", "sections", "expected_section_differences", "fair_loudness_match",
               "window_seconds", "max_windows", "window_step_seconds", "gains_db"}
    if not isinstance(args, dict) or set(args) - (options | {"manifest_path"}):
        raise ValueError("unknown assessment argument or non-object arguments")
    if "listening_condition" not in args:
        raise ValueError("assessment requires explicit listening_condition")
    raw_path = args.get("manifest_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("manifest_path must be a nonempty local path")
    path = Path(raw_path).expanduser().resolve()
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("capture manifest exceeds byte budget")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("mode") != "in_mix_native_arrangement":
        raise ValueError("assessment requires a native in-mix capture manifest; legacy raw taps are unsupported")
    if manifest.get("complete") is not True or manifest.get("cleanup_complete") is not True:
        raise ValueError("capture and owned-resource cleanup must both be complete")
    alignment, provenance = manifest.get("alignment"), manifest.get("provenance")
    if not isinstance(alignment, dict) or alignment.get("verified") is not True or type(alignment.get("uncertainty_samples")) is not int or alignment.get("uncertainty_samples") != 0:
        raise ValueError("capture alignment is unverified")
    if not isinstance(provenance, dict) or provenance.get("disjoint_contributions") is not True or provenance.get("in_mix_levels") is not True:
        raise ValueError("capture in-mix/disjoint provenance is unverified")
    for value in (alignment.get("source"), provenance.get("signal_path")):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("capture alignment and signal-path evidence must be nonempty")
    from in_mix_qualification import verify_qualification
    proof = verify_qualification(manifest)
    _verify_partition_exclusions(manifest)
    tracks = manifest.get("tracks")
    if not isinstance(tracks, list) or not 2 <= len(tracks) <= 9:
        raise ValueError("assessment requires one program and 1-8 contributions")
    sources, roles, metadata = [], [], []
    for entry in tracks:
        if not isinstance(entry, dict) or entry.get("outcome") != "complete" or entry.get("role") not in {"program", "contribution"}:
            raise ValueError("every capture entry must be complete with a supported role")
        name, file_path = entry.get("name"), entry.get("path")
        if not isinstance(name, str) or not name.strip() or not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("capture entries require nonempty name and path")
        file = Path(file_path).expanduser()
        file = (file if file.is_absolute() else path.parent / file).resolve()
        if file.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("capture WAV exceeds byte budget")
        info = validate_wav(file)
        recorded = entry.get("wav")
        if not isinstance(recorded, dict) or any(recorded.get(k) != info[k] for k in ("sample_rate", "channels", "frames", "format", "bits_per_sample")):
            raise ValueError("capture WAV metadata does not match finalized file")
        metadata.append(info)
        sources.append({"name": name, "path": str(file)})
        roles.append(entry["role"])
    if roles.count("program") != 1:
        raise ValueError("capture requires exactly one separate program reference")
    if len({s["name"] for s in sources}) != len(sources) or len({s["path"] for s in sources}) != len(sources):
        raise ValueError("capture source names and file paths must be unique")
    if any((m["sample_rate"], m["channels"], m["frames"]) != (metadata[0]["sample_rate"], metadata[0]["channels"], metadata[0]["frames"]) for m in metadata):
        raise ValueError("capture WAVs must share rate, channel layout and frame count")
    interleaved = manifest.get("interleaved_wav")
    if not isinstance(interleaved, dict) or any(interleaved.get(k) != metadata[0][k] for k in ("sample_rate", "frames")) or interleaved.get("channels") != 2 * len(tracks):
        raise ValueError("capture channel map does not match interleaved recorder metadata")
    recorded_path = manifest.get("normalized_interleaved_path", manifest.get("interleaved_path"))
    if not isinstance(recorded_path, str) or not recorded_path.strip():
        raise ValueError("capture requires retained interleaved recording")
    recording = Path(recorded_path).expanduser()
    recording = (recording if recording.is_absolute() else path.parent / recording).resolve()
    if str(recording) in {s["path"] for s in sources} or recording.stat().st_size > 400 * 1024 * 1024:
        raise ValueError("interleaved recording path or byte budget is invalid")
    recorded_info = validate_wav(recording)
    if any(recorded_info[k] != interleaved.get(k) for k in ("sample_rate", "channels", "frames", "format", "bits_per_sample")):
        raise ValueError("interleaved recording metadata does not match finalized file")
    if recorded_info["format"] != "float" or recorded_info["bits_per_sample"] not in (32, 64) or any(
            m["channels"] != 2 or (m["format"], m["bits_per_sample"]) not in
            {("pcm", 8), ("pcm", 16), ("pcm", 24), ("pcm", 32), ("float", 32), ("float", 64)} for m in metadata):
        raise ValueError("qualified capture requires supported stereo native WAVs and a lossless float interleaved recording")
    if recorded_info["frames"] * recorded_info["channels"] > 48_000_000 or any(m["frames"] * m["channels"] > 12_000_000 or m["duration_seconds"] > 120 for m in metadata):
        raise ValueError("capture exceeds assessment sample/duration budget")
    # float64 preserves native PCM32 LSBs and float64 acquisition samples exactly.
    import numpy as np
    import soundfile as sf
    with ExitStack() as stack:
        shared = stack.enter_context(sf.SoundFile(str(recording)))
        copies = [stack.enter_context(sf.SoundFile(s["path"])) for s in sources]
        for block in shared.blocks(blocksize=65536, dtype="float64", always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError("interleaved recording contains nonfinite samples")
            for index, copy in enumerate(copies):
                if not np.array_equal(copy.read(len(block), dtype="float64", always_2d=True), block[:, 2 * index:2 * index + 2]):
                    raise ValueError("capture WAV does not match its interleaved recorder channels")
    programme = sources[roles.index("program")]
    parts = [s for s, role in zip(sources, roles) if role == "contribution"]
    gains = args.get("gains_db", {})
    if not isinstance(gains, dict) or set(gains) - {p["name"] for p in parts}:
        raise ValueError("gains_db must map captured contribution names to scenario gains")
    parts = [{**p, **({"gain_db": gains[p["name"]]} if p["name"] in gains else {})} for p in parts]
    from audio_balance import analyze_balance
    result = analyze_balance({"programme": programme, "parts": parts,
        "alignment": {k: alignment[k] for k in ("verified", "source", "uncertainty_samples", "offsets_samples") if k in alignment},
        "provenance": {k: provenance[k] for k in ("disjoint_contributions", "in_mix_levels", "signal_path")},
        **{k: v for k, v in args.items() if k in options - {"gains_db"}}})
    result["capture_evidence"] = {**manifest, "manifest_path": str(path), "verified_qualification": proof}
    return result
