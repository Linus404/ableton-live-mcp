"""Sequential, approximate raw passage capture. No sample-alignment claim."""
from __future__ import annotations

import json
import hashlib
import math
import shutil
import struct
import time
import uuid
from pathlib import Path

from ableton_paths import state_dir


def _number(args, name, default=None, *, positive=False):
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return float(value)


def validate_wav(path):
    """Inspect RIFF PCM/IEEE-float (including extensible) without reading audio."""
    path = Path(path)
    size = path.stat().st_size
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
            raise ValueError("not a RIFF WAVE file")
        end = struct.unpack_from("<I", header, 4)[0] + 8
        if end != size:
            raise ValueError("RIFF size not finalized")
        fmt = None
        data_size = None
        while handle.tell() < end:
            chunk = handle.read(8)
            if len(chunk) != 8:
                raise ValueError("truncated WAV chunk")
            kind, length = struct.unpack("<4sI", chunk)
            position = handle.tell()
            if position + length + (length & 1) > end:
                raise ValueError("truncated WAV payload")
            if kind == b"fmt ":
                raw = handle.read(min(length, 40))
                if len(raw) < 16:
                    raise ValueError("invalid WAV format")
                code, channels, rate, byte_rate, align, bits = struct.unpack_from("<HHIIHH", raw)
                if code == 0xFFFE:
                    if len(raw) < 40 or struct.unpack_from("<H", raw, 16)[0] < 22:
                        raise ValueError("invalid extensible WAV")
                    if raw[28:40] != bytes.fromhex("00001000800000aa00389b71"):
                        raise ValueError("unsupported WAV subformat")
                    code = struct.unpack_from("<I", raw, 24)[0]
                if code not in (1, 3) or channels < 1 or rate < 1 or bits not in (8, 16, 24, 32, 64):
                    raise ValueError("unsupported WAV format")
                if code == 3 and bits not in (32, 64):
                    raise ValueError("invalid float WAV")
                if align != channels * (bits // 8) or byte_rate != rate * align:
                    raise ValueError("invalid WAV frame layout")
                fmt = {"format": "float" if code == 3 else "pcm", "channels": channels,
                       "sample_rate": rate, "bits_per_sample": bits, "block_align": align}
            elif kind == b"data":
                data_size = length
            handle.seek(position + length + (length & 1))
        if fmt is None or not data_size or data_size % fmt["block_align"]:
            raise ValueError("missing, empty, or partial WAV frames")
        frames = data_size // fmt["block_align"]
        return {**fmt, "frames": frames, "duration_seconds": frames / fmt["sample_rate"], "bytes": size}


def _completed_wav(path, timeout=5.0):
    deadline = time.monotonic() + timeout
    previous = None
    error = "WAV missing"
    while time.monotonic() < deadline:
        try:
            current = (Path(path).stat().st_size, Path(path).stat().st_mtime_ns)
            if current == previous:
                return validate_wav(path)
            previous = current
        except (OSError, ValueError) as exc:
            error = str(exc)
        time.sleep(0.1)
    raise ValueError(f"WAV completion not verified: {error}")


def _require_runtime(bridge):
    # Reuse the validator's loaded-code fingerprint, not only files on disk.
    from install_remote_script import remote_script_status
    from validate import _attach_live_runtime_code_status, _check_running_remote_script, _live_runtime_code_fingerprint_code
    remote = remote_script_status()
    if not remote.get("current") or not remote.get("target"):
        raise RuntimeError("installed Remote Script is stale or missing")
    results = {"remote_script": remote}
    results["live_runtime_code"] = bridge.request("exec", {"code": _live_runtime_code_fingerprint_code(Path(remote["target"]) / "bridge.py")})
    _attach_live_runtime_code_status(results)
    if not remote.get("live_compiled_runtime_code_sha256"):
        raise RuntimeError("running code fingerprint could not be verified")
    results["ping"] = bridge.request("ping", {})
    current, reason = _check_running_remote_script(results)
    if not current:
        raise RuntimeError(f"runtime_current false; live_mutations_safe false: {reason}")
    return {"runtime_current": True, "live_mutations_safe": True}


def capture_audio(bridge, args):
    import audio_tap

    if args.get("precision") not in (None, "approximate") or args.get("sample_aligned"):
        raise ValueError("Only approximate raw capture is supported; sample alignment is unavailable")
    start = _number(args, "start_beat")
    length = _number(args, "length_beats", positive=True)
    pre = _number(args, "pre_roll_beats", 0)
    post = _number(args, "post_roll_beats", 0)
    duration = _number(args, "max_duration_seconds", 120, positive=True)
    if duration > 600:
        raise ValueError("max_duration_seconds cannot exceed 600")
    if not math.isfinite(start + length + post):
        raise ValueError("passage endpoint must be finite")
    refs = args.get("track_refs")
    if refs is not None and (not isinstance(refs, list) or any(not isinstance(ref, dict) or not ("path" in ref or "id" in ref) for ref in refs)):
        raise ValueError("track_refs must be a list of Live references")
    for key in ("include_returns", "include_master"):
        if key in args and not isinstance(args[key], bool):
            raise ValueError(f"{key} must be boolean")
    runtime = _require_runtime(bridge)
    snapshot_args = {"include_returns": args.get("include_returns", True), "include_master": args.get("include_master", True)}
    if refs is not None:
        snapshot_args["track_refs"] = refs
    snapshot = bridge.request("audio_capture_snapshot", snapshot_args)
    transport = snapshot["transport"]
    for key in ("playing", "record_mode", "session_record", "arrangement_overdub", "session_automation_record", "back_to_arranger", "loop"):
        if key not in transport or transport[key] is None:
            raise RuntimeError(f"unknown transport ownership state: {key}")
    if any(transport[key] for key in ("record_mode", "session_record", "arrangement_overdub", "session_automation_record", "back_to_arranger")):
        raise RuntimeError("capture requires Arrangement playback with recording/automation recording disabled and no Session override")
    tracks = snapshot["tracks"]
    supported = [track for track in tracks if track.get("has_audio_output") is True and track.get("is_frozen") is False]
    root = Path(args.get("output_directory") or (state_dir() / "audio_captures")).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    # Conservative disk reservation, not a timing or sample-rate guarantee.
    budget = math.ceil(duration * 8 * 1024 * 1024 * len(supported)) + 64 * 1024 * 1024
    if shutil.disk_usage(root).free < budget:
        raise ValueError(f"insufficient disk space; require {budget} bytes")
    take_id = uuid.uuid4().hex
    directory = root / take_id
    directory.mkdir()
    manifest_path = directory / "manifest.json"
    manifest = {"take_id": take_id, "complete": False, "runtime": runtime,
                "requested": {"start_beat": start, "length_beats": length, "pre_roll_beats": pre, "post_roll_beats": post, "max_duration_seconds": duration},
                "precision": "approximate", "raw_untrimmed": True, "sample_aligned": False,
                "sample_uncertainty": None, "readiness": "command-only; no guaranteed first sample",
                "signal_point": "end-of-device-chain, pre-mixer; final output unverified",
                "context": "pre/post-roll continue Arrangement playback; post-roll is not an isolated tail",
                "prior_transport": transport, "transport_stopped": False, "tap_devices_retained": True, "tracks": [], "observations": [],
                "timeline_jump_detection": "observed backwards motion or heuristic forward discontinuity; not exhaustive"}
    active = []
    healthy = True
    mutated = False
    deadline = None

    def call(method, params):
        nonlocal healthy
        try:
            return bridge.request(method, params)
        except Exception:
            healthy = False  # Unknown sent-mutation outcome: no retries or further Live work.
            raise

    def persist():
        manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")

    def stopped_phase(method, params, result_key):
        result = call(method, params)
        if result.get(result_key) is True:
            return result
        if (result.get(result_key) is not False or result.get("settled") is not False
                or result.get("pending") != "transport_stop"):
            raise RuntimeError(f"{method} did not acknowledge completion or pending stop")
        # Only an explicit accepted-stop response permits a second phase call.
        # Poll outside Live's callback; sent-call exceptions still fail closed.
        settle_deadline = time.monotonic() + 10
        while time.monotonic() < settle_deadline:
            before = time.monotonic()
            status = call("audio_capture_snapshot", {"track_refs": [], "include_returns": False, "include_master": False})["transport"]
            after = time.monotonic()
            manifest["observations"].append({"phase": result_key, "request_monotonic": before,
                                             "response_monotonic": after, "observed_unix": time.time(), "transport": status})
            if after >= settle_deadline:
                break
            if status.get("playing") is False:
                completed = call(method, params)
                if completed.get(result_key) is not True:
                    raise RuntimeError(f"{method} did not complete after observed stop")
                return completed
            if status.get("playing") is not True:
                raise RuntimeError("unknown transport state while settling stop")
            time.sleep(0.1)
        raise RuntimeError(f"{method} transport stop did not settle")

    def command(item, action, **kwargs):
        tap = item["tap"]
        ack = audio_tap.send_command(tap["command_file"], tap["status_file"], action,
                                     instance_id=item["instance_id"], take_id=take_id, **kwargs)
        if (ack.get("runtime_version") != audio_tap.RUNTIME_VERSION or ack.get("error")
                or ack.get("event") != action or ack.get("take_id") != take_id
                or ack.get("path") != item["path"] or ack.get("command_only") is not True):
            raise RuntimeError(f"invalid tap {action} acknowledgement: {ack}")
        return ack

    persist()
    try:
        if supported:
            mutated = True
            manifest["prepare"] = stopped_phase("audio_capture_prepare", {"start_beat": max(0, start - pre)}, "prepared")
        for index, track in enumerate(tracks):
            item = {"name": track["name"], "ref": track["ref"], "kind": track["kind"], "group_ref": track.get("group_ref")}
            manifest["tracks"].append(item)
            if track.get("has_audio_output") is not True or track.get("is_frozen") is not False:
                reason = "frozen" if track.get("is_frozen") is True else "no_audio_output" if track.get("has_audio_output") is False else "unknown_capability"
                item.update(outcome="unsupported", reason=reason)
                continue
            identity = json.dumps([snapshot["song_ref"]["id"], track["ref"]["id"]])
            instance_id = "capture_" + hashlib.sha256(identity.encode()).hexdigest()[:24]
            tap = audio_tap.build_instance(instance_id)
            item.update(tap=tap, instance_id=instance_id, path=str(directory / f"{index:03d}.wav"), outcome="setup_pending")
            mutated = True
            setup = call("agent_audio_tap_setup", {"isolated": True, "device_name": tap["device_name"], "placement": "track", "target_track": track["ref"]})
            item["setup"] = setup
            if not setup.get("ok") or not setup.get("end_verified"):
                raise RuntimeError(f"tap setup not verified: {track['name']}")
            initial_ack = audio_tap.send_command(tap["command_file"], tap["status_file"], "status", instance_id=instance_id)
            item["initial_ack"] = initial_ack
            if (initial_ack.get("runtime_version") != audio_tap.RUNTIME_VERSION or initial_ack.get("event") != "status"
                    or initial_ack.get("error") or initial_ack.get("command_only") is not True
                    or initial_ack.get("state") not in ("idle", "stopped", "open")):
                raise RuntimeError(f"tap runtime not safely initialized: {initial_ack}")
            item["outcome"] = "prepared"
        if not supported:
            raise RuntimeError("no supported audio-output paths selected")
        for item in manifest["tracks"]:
            if item["outcome"] != "prepared":
                continue
            if deadline is None:
                deadline = time.monotonic() + duration
            if time.monotonic() >= deadline:
                raise RuntimeError("capture deadline exceeded during recorder start")
            active.append(item)  # Stop even if the start acknowledgement times out.
            item["start_ack"] = command(item, "start", path=item["path"], max_duration_seconds=max(0.001, deadline - time.monotonic()))
            ready_deadline = min(deadline, time.monotonic() + 5)
            ack = item["start_ack"]
            while ack.get("state") == "starting" and time.monotonic() < ready_deadline:
                time.sleep(0.1)
                ack = command(item, "status", timeout=max(0.001, ready_deadline - time.monotonic()))
            item["recording_command_ack"] = ack
            if ack.get("state") != "recording":
                raise RuntimeError("recorder did not acknowledge recording command state")
            item["recording_observed_monotonic"] = time.monotonic()
            item["outcome"] = "recording"
        play_requested = time.monotonic()
        call("transport", {"action": "play"})
        previous = (play_requested, max(0, start - pre), float(transport.get("tempo", 999)))
        endpoint = start + length + post
        while True:
            if time.monotonic() >= deadline:
                raise RuntimeError("capture deadline exceeded")
            before = time.monotonic()
            status = call("audio_capture_snapshot", {"track_refs": [], "include_returns": False, "include_master": False})["transport"]
            after = time.monotonic()
            beat = status["time"]
            if not isinstance(beat, (int, float)) or not math.isfinite(beat):
                raise RuntimeError("unknown timeline position")
            observation = {"request_monotonic": before, "response_monotonic": after, "observed_unix": time.time(), "transport": status}
            manifest["observations"].append(observation)
            if previous:
                old_time, old_beat, old_tempo = previous
                tempo = max(float(status.get("tempo", 999)), old_tempo)
                # Heuristic discontinuity detection only; this is not an uncertainty bound.
                if beat < old_beat - 0.01 or beat - old_beat > (after - old_time) * tempo / 60 + 2:
                    raise RuntimeError("timeline discontinuity observed")
            if not status["playing"]:
                raise RuntimeError("transport stopped before passage completed")
            if after >= deadline:
                raise RuntimeError("capture deadline exceeded during status call")
            if beat >= endpoint:
                manifest["passage_observed_complete"] = True
                break
            previous = (before, beat, float(status.get("tempo", 999)))
            time.sleep(0.1)
    except Exception as exc:
        manifest["error"] = str(exc)
    finally:
        if healthy and mutated:
            try:
                restored = stopped_phase("audio_capture_restore", {"loop": transport["loop"], "selected_track": snapshot.get("selected_track")}, "restored")
                manifest["restore"] = restored
                manifest["transport_stopped"] = restored.get("playing") is False
            except Exception as exc:
                manifest["restore_error"] = str(exc)
        for item in active:
            try:
                final_ack = command(item, "status")
                item["final_recording_ack"] = final_ack
                if item["outcome"] != "recording" or final_ack.get("state") != "recording":
                    item["error"] = "recording state not maintained through passage"
            except Exception as exc:
                item["error"] = str(exc)
            try:
                item["stop_requested_monotonic"] = time.monotonic()
                item["stop_ack"] = command(item, "stop")
                if item["stop_ack"].get("state") != "stopped":
                    raise RuntimeError("recorder did not acknowledge stopped state")
            except Exception as exc:
                item["error"] = str(exc)
        # Every owned recorder gets its stop before any potentially slow WAV wait.
        for item in active:
            try:
                item["wav"] = _completed_wav(item["path"])
                if "recording_observed_monotonic" in item:
                    elapsed = max(0, item["stop_requested_monotonic"] - item["recording_observed_monotonic"])
                    minimum = max(0, elapsed - max(1, 0.25 * elapsed))
                    item["duration_sanity"] = {"kind": "gross truncation heuristic, not timing calibration", "command_elapsed_seconds": elapsed,
                                               "minimum_seconds": minimum, "wav_seconds": item["wav"]["duration_seconds"]}
                    if item["wav"]["duration_seconds"] < minimum:
                        item["error"] = "WAV grossly shorter than observed recording command interval"
                item["outcome"] = "incomplete" if item.get("error") else "captured"
            except Exception as exc:
                item.update(outcome="incomplete", error=str(exc))
        manifest["complete"] = bool(manifest.get("passage_observed_complete") and not manifest.get("error") and manifest["transport_stopped"] and active and all(item["outcome"] == "captured" for item in active))
        persist()
    return {"complete": manifest["complete"], "take_id": take_id, "directory": str(directory), "manifest_path": str(manifest_path),
            "transport_stopped": manifest["transport_stopped"], "error": manifest.get("error"),
            "tracks": [{key: item[key] for key in ("name", "ref", "kind", "path", "outcome", "reason", "error", "wav") if key in item} for item in manifest["tracks"]]}
