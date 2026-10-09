"""Native Live acquisition; an offline interleave is not acquisition timing proof."""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import shutil
import time
import uuid
from pathlib import Path

from ableton_paths import state_dir
from audio_capture import _completed_wav, _number, _require_runtime, validate_wav


def _routing_profile_data(this, song):
    """Read only: snapshot objects, never infer latency from routing or null fields."""
    unknown, critical, excluded, count = [], [], [], [0]
    originals = list(song.tracks) + list(song.return_tracks) + [song.master_track]
    if len(originals) > 256:
        raise ValueError("Routing profile exceeds 256 tracks")
    for name in ("_in_mix_owned", "_in_mix_calibration_owned", "_in_mix_offset_owned"):
        registry = getattr(this, name, {})
        if not isinstance(registry, dict):
            raise ValueError("Invalid owned-object registry: " + name)
        for items in registry.values():
            for owner in items:
                for track in originals:
                    if this._same_live_object(owner, track) and not any(this._same_live_object(track, item) for item in excluded):
                        excluded.append(track)

    def stable_ref(obj):
        value = this._audio_capture_ref(obj)
        if value is None:
            return None
        if "id" not in value or isinstance(value["id"], bool):
            raise ValueError("Routing profile requires stable Live object identities")
        return {"id": int(value["id"])}

    def read(obj, name, label, required=False):
        try:
            value = getattr(obj, name, None)
        except Exception:
            value = None
        if value is None:
            unknown.append(label)
            if required:
                critical.append(label)
        return value

    def scalar(obj, name, label, required=False):
        value = read(obj, name, label, required)
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float) and math.isfinite(value):
            return value
        unknown.append(label)
        if required:
            critical.append(label)
        return None

    def route(obj, name, label, required=False):
        if required and name.endswith("_channel"):
            try:
                choices = getattr(obj, "available_" + name + "s", None)
                if choices is not None and len(choices) == 0:
                    required = False  # Known inapplicable channel, not unreadable selected routing.
            except Exception:
                pass
        value = read(obj, name, label, required)
        if value is None:
            return None
        display = getattr(value, "display_name", None)
        if display is None:
            unknown.append(label)
            if required:
                critical.append(label)
        return str(display) if display is not None else None

    def devices(objects, prefix, depth=0):
        if depth > 8:
            raise ValueError("Routing profile rack nesting exceeds eight levels")
        result = []
        for device in objects:
            count[0] += 1
            if count[0] > 1024:
                raise ValueError("Routing profile exceeds 1024 devices")
            ref = stable_ref(device)
            label = prefix + ".device:" + str(ref["id"])
            parameters = read(device, "parameters", label + ".parameters", True)
            if parameters is None or len(parameters) > 256:
                raise ValueError("Unreadable device parameters or more than 256 parameters")
            parameter_data = []
            for parameter in parameters:
                name = str(parameter.name)
                normalized = name.casefold().replace(" ", "").replace("_", "").replace("-", "")
                critical_mode = any(word in normalized for word in ("deviceon", "lookahead", "oversampl", "quality", "mode", "latency", "buffer", "fft", "truepeak"))
                sidechain_state = "sidechain" in normalized and any(word in normalized for word in ("on", "enable", "source", "routing", "external"))
                if not (critical_mode or sidechain_state or normalized == "scon"):
                    continue
                automation = read(parameter, "automation_state", label + ".automation:" + name)
                try:
                    automation = int(automation) if automation is not None else None
                except (TypeError, ValueError):
                    automation = None
                if automation not in (None, 0, 2):
                    critical.append(label + ".automated_critical_parameter:" + name)
                parameter_data.append({"name": name, "value": scalar(parameter, "value", label + ".parameter:" + name, True),
                                       "automation_state": automation})
            node = {"ref": ref, "name": str(device.name), "class_name": this._device_class_name(device),
                    "is_active": scalar(device, "is_active", label + ".is_active"),
                    "DeviceOn": [p["value"] for p in parameter_data if p["name"] == "Device On"],
                    "latency_in_samples": scalar(device, "latency_in_samples", label + ".latency_in_samples"),
                    "latency_in_ms": scalar(device, "latency_in_ms", label + ".latency_in_ms"),
                    "parameters": parameter_data, "routing_fields": {}, "chains": [], "return_chains": [],
                    "parameter_binding": "observed critical-mode labels, not universal latency-parameter coverage",
                    "unsupported_scope": "opaque/adaptive latency or unexposed routing that cannot be pinned"}
            if node["is_active"] is None and len(node["DeviceOn"]) != 1:
                critical.append(label + ".active_state")
            for name in ("input_routing_type", "input_routing_channel", "output_routing_type", "output_routing_channel",
                         "sidechain_routing_type", "sidechain_routing_channel"):
                if hasattr(device, name):
                    node["routing_fields"][name] = route(device, name, label + "." + name, True)
            node["can_have_chains"] = scalar(device, "can_have_chains", label + ".can_have_chains", True)
            for port_name in ("audio_inputs", "audio_outputs"):
                if hasattr(device, port_name):
                    ports = read(device, port_name, label + "." + port_name, True)
                    if ports is None or len(ports) > 64:
                        raise ValueError("Unreadable or oversized device audio I/O topology")
                    node["routing_fields"][port_name] = [{"ref": stable_ref(port),
                        "routing_type": route(port, "routing_type", label + "." + port_name, True),
                        "routing_channel": route(port, "routing_channel", label + "." + port_name, True)} for port in ports]
            if node["can_have_chains"]:
                chains = read(device, "chains", label + ".chains", True)
                if chains is None or len(chains) > 64:
                    raise ValueError("Unreadable rack topology or more than 64 chains")
                returns = read(device, "return_chains", label + ".return_chains", True) if hasattr(device, "return_chains") else []
                if returns is None or len(returns) > 64:
                    raise ValueError("Unreadable rack return topology or more than 64 return chains")
                regular = [chain for chain in chains if not any(this._same_live_object(chain, returned) for returned in returns)]
                for chain, returned in [(chain, False) for chain in regular] + [(chain, True) for chain in returns]:
                    chain_ref = stable_ref(chain)
                    chain_label = label + ".chain:" + str(chain_ref["id"])
                    children = read(chain, "devices", chain_label + ".devices", True)
                    if children is None:
                        raise ValueError("Unreadable rack device topology")
                    chain_node = {"ref": chain_ref, "name": str(chain.name),
                        "mute": scalar(chain, "mute", chain_label + ".mute"), "solo": scalar(chain, "solo", chain_label + ".solo"),
                        "devices": devices(children, chain_label, depth + 1), "sends": [], "routing_fields": {}}
                    mixer = read(chain, "mixer_device", chain_label + ".mixer_device", bool(returns))
                    sends = read(mixer, "sends", chain_label + ".sends", bool(returns)) if mixer is not None else None
                    if sends is None and returns:
                        raise ValueError("Rack return send topology is unreadable")
                    sends = list(sends) if sends is not None else []
                    if sends and len(sends) != len(returns):
                        raise ValueError("Rack chain send/return target mapping is unavailable")
                    chain_node["sends"] = [{"target_ref": stable_ref(returns[index]),
                        "value": scalar(send, "value", chain_label + ".send:" + str(index), True)} for index, send in enumerate(sends)]
                    for name in ("input_routing_type", "input_routing_channel", "output_routing_type", "output_routing_channel"):
                        if hasattr(chain, name):
                            chain_node["routing_fields"][name] = route(chain, name, chain_label + "." + name, True)
                    node["return_chains" if returned else "chains"].append(chain_node)
            result.append(node)
        return result

    entries = []
    for track in originals:
        if any(this._same_live_object(track, owner) for owner in excluded):
            continue
        master = this._same_live_object(track, song.master_track)
        returned = any(this._same_live_object(track, item) for item in song.return_tracks)
        kind = "master" if master else "return" if returned else "group" if getattr(track, "is_foldable", False) else "track"
        ref = stable_ref(track)
        label = "track:" + str(ref["id"])
        parent = read(track, "group_track", label + ".group_track")
        grouped = scalar(track, "is_grouped", label + ".is_grouped", not master)
        if grouped and parent is None:
            critical.append(label + ".group_track")
        mixer = track.mixer_device
        sends = list(mixer.sends) if not master else []
        if sends and len(sends) != len(song.return_tracks):
            raise ValueError("Send/return target mapping is unavailable")
        output_type = route(track, "output_routing_type", label + ".output_type", not master)
        channel_required = not master and output_type not in ("Main", "Master", "Sends Only", "No Output")
        entry = {"ref": ref, "name": str(track.name), "kind": kind,
                 "parent_ref": stable_ref(parent) if parent is not None else None,
                 "is_grouped": grouped,
                 "has_audio_output": scalar(track, "has_audio_output", label + ".has_audio_output", True),
                 "input_type": route(track, "input_routing_type", label + ".input_type", kind == "track"),
                 "input_channel": route(track, "input_routing_channel", label + ".input_channel", kind == "track"),
                 "output_type": output_type,
                 "output_channel": route(track, "output_routing_channel", label + ".output_channel", channel_required),
                 "current_monitoring_state": scalar(track, "current_monitoring_state", label + ".monitoring", kind == "track"),
                 "track_delay": scalar(track, "track_delay", label + ".track_delay"),
                 "delay_in_ms": scalar(track, "delay_in_ms", label + ".delay_in_ms"),
                 "devices": devices(track.devices, label),
                 "sends": [{"target_ref": stable_ref(song.return_tracks[index]),
                            "value": scalar(send, "value", label + ".send:" + str(index), True)} for index, send in enumerate(sends)]}
        if not isinstance(entry["has_audio_output"], bool):
            critical.append(label + ".has_audio_output_boolean")
        entries.append(entry)
    return {"profile": {"schema_version": 1, "tracks": entries, "unknown_fields": sorted(set(unknown)),
                         "critical_unknown_fields": sorted(set(critical))},
            "excluded_refs": [this._audio_capture_ref(track) for track in excluded]}


def read_routing_profile(bridge, *, request=None):
    """Return a stable critical graph fingerprint plus separately dated read evidence."""
    code = "import math\n" + inspect.getsource(_routing_profile_data) + "\nresult = _routing_profile_data(this, song)"
    data = (request or bridge.request)("exec", {"code": code})
    profile = data["profile"]
    encoded = json.dumps(profile, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"profile": profile, "sha256": hashlib.sha256(encoded).hexdigest(),
            "evidence": {"source": "read_only_live_routing_profile", "observed_at_unix": time.time(),
                         "excluded_refs": data["excluded_refs"]}}


def _select_returns(plan, refs):
    """Filter existing returns and paired source-context rows, preserving plan order."""
    returns = [track for track in plan["tracks"] if track["kind"] == "return"]
    chosen = set()
    for ref in refs:
        if "id" in ref:
            try:
                if isinstance(ref["id"], bool):
                    raise ValueError("boolean id")
                wanted = int(ref["id"])
                if isinstance(ref["id"], float) and ref["id"] != wanted:
                    raise ValueError("fractional id")
            except (TypeError, ValueError):
                raise ValueError("return_refs contains an invalid object id") from None
            matches = [track for track in returns if track["ref"].get("id") == wanted]
        else:
            matches = [track for track in returns if track["ref"].get("path") == ref.get("path")]
        if len(matches) != 1 or matches[0]["ref"]["id"] in chosen:
            raise ValueError("return_refs must uniquely select existing return tracks")
        chosen.add(matches[0]["ref"]["id"])
    contexts = iter(plan.get("source_contexts", []))
    filtered_tracks, filtered_contexts = [], []
    for track in plan["tracks"]:
        context = next(contexts) if track["kind"] != "master" else None
        if track["kind"] == "return" and track["ref"]["id"] not in chosen:
            continue
        filtered_tracks.append(track)
        if context is not None:
            filtered_contexts.append(context)
    if not filtered_tracks:
        raise ValueError("Native return selection leaves no capture targets")
    plan["tracks"], plan["source_contexts"] = filtered_tracks, filtered_contexts
    return plan


def _copy_native_recordings(receivers, tracks, directory):
    """Keep native acquisition files bit-for-bit; an interleave is only a derivative."""
    import numpy as np
    import soundfile as sf
    if len(receivers) != len(tracks):
        raise ValueError("Native receiver/source count mismatch")
    entries, paths, metadata = [], [], []
    for index, (receiver, track) in enumerate(zip(receivers, tracks)):
        clips = receiver.get("clips", [])
        if len(clips) != 1 or clips[0].get("is_recording") is not False:
            raise ValueError("Each owned receiver must have one stopped native audio clip")
        clip = clips[0]
        if not clip.get("file_path") or clip.get("is_audio_clip") is not True or clip.get("is_arrangement_clip") is not True:
            raise ValueError("Native receiver clip identity/path is unverified")
        source = Path(clip["file_path"])
        info = _completed_wav(source, timeout=30)
        if info["channels"] != 2 or info["sample_rate"] != clip.get("sample_rate") or info["frames"] != clip.get("sample_length"):
            raise ValueError("Native WAV layout disagrees with recorded clip sample evidence")
        before = (source.stat().st_size, source.stat().st_mtime_ns)
        target = Path(directory) / ("%03d.wav" % index)
        shutil.copyfile(source, target)
        if before != (source.stat().st_size, source.stat().st_mtime_ns) or validate_wav(target) != info:
            raise ValueError("Native file changed while being preserved")
        def digest(path):
            with Path(path).open("rb") as handle:
                return hashlib.file_digest(handle, "sha256").hexdigest()
        raw_hash = digest(source)
        if digest(target) != raw_hash:
            raise ValueError("Native recording copy is not bit-for-bit identical")
        entry = {**track, "path": str(target), "wav": info, "outcome": "complete", "native_original_path": str(source),
                 "native_sha256": raw_hash, "native_clip": clip, "receiver_ref": receiver["receiver_ref"]}
        entries.append(entry)
        paths.append(target)
        metadata.append(info)
    if len({(info["sample_rate"], info["frames"]) for info in metadata}) != 1:
        raise ValueError("Native recordings do not have matching rates/frame counts; no implicit padding/trimming")
    if len({(entry["native_clip"].get("start_time"), entry["native_clip"].get("end_time")) for entry in entries}) != 1:
        raise ValueError("Native Arrangement recording edges differ; frame-zero mapping is unavailable")
    target = Path(directory) / "interleaved_native_derivative.wav"
    handles = []
    try:
        for path in paths:
            handles.append(sf.SoundFile(str(path)))
        with sf.SoundFile(str(target), "w", samplerate=metadata[0]["sample_rate"], channels=2 * len(paths), subtype="DOUBLE") as output:
            remaining = metadata[0]["frames"]
            while remaining:
                count = min(65536, remaining)
                blocks = [handle.read(count, dtype="float64", always_2d=True) for handle in handles]
                if any(len(block) != count or not np.isfinite(block).all() for block in blocks):
                    raise ValueError("Native file contains incomplete or nonfinite audio")
                output.write(np.concatenate(blocks, axis=1))
                remaining -= count
    finally:
        for handle in handles:
            handle.close()
    wav = validate_wav(target)
    if wav["frames"] != metadata[0]["frames"]:
        raise ValueError("Constructed interleave frame count differs from acquisition files")
    return entries, str(target), wav


def capture_in_mix(bridge, args):
    """Supported native Live recording; timing qualification is never inferred from interleaving."""
    import soundfile  # Dependency check before Live mutations.
    from live_settings import read_live_settings
    start = _number(args, "start_beat")
    length = _number(args, "length_beats", positive=True)
    pre, post = _number(args, "pre_roll_beats", 0), _number(args, "post_roll_beats", 0)
    duration = _number(args, "max_duration_seconds", 120, positive=True)
    if duration > 600 or not math.isfinite(start + length + post):
        raise ValueError("Native capture duration/end point exceeds bounds")
    for key in ("include_returns", "include_master"):
        if key in args and not isinstance(args[key], bool):
            raise ValueError(key + " must be boolean")
    refs = args.get("track_refs")
    if refs is not None and (not isinstance(refs, list) or any(not isinstance(ref, dict) or not ("id" in ref or "path" in ref) for ref in refs)):
        raise ValueError("track_refs must be Live references")
    return_refs = args.get("return_refs")
    if "return_refs" in args:
        if not isinstance(return_refs, list) or any(not isinstance(ref, dict) or not ("id" in ref or "path" in ref) for ref in return_refs):
            raise ValueError("return_refs must be a list of Live references")
        if args.get("include_returns") is False:
            raise ValueError("return_refs cannot be combined with include_returns:false")
    runtime = _require_runtime(bridge)
    runtime_identity = bridge.request("ping", {}).get("remote_script")
    if not isinstance(runtime_identity, dict) or not runtime_identity:
        raise RuntimeError("Running Remote Script identity is unavailable")
    plan = bridge.request("native_in_mix_plan", {key: args[key] for key in ("track_refs", "include_returns", "include_master") if key in args})
    if return_refs is not None:
        plan = _select_returns(plan, return_refs)
    serving_pid = runtime_identity.get("process_id")
    if type(serving_pid) is not int or serving_pid <= 0:
        raise RuntimeError("Bridge-serving Live process identity is unavailable")
    settings_before = read_live_settings(expected_pid=serving_pid)
    if settings_before.get("evidence", {}).get("pid") != serving_pid:
        raise RuntimeError("Live settings cannot be bound to the bridge-serving process")
    context = plan.get("capture_context", {})
    for source, key in (("delay_compensation", "global_delay_compensation"), ("reduced_latency_when_monitoring", "reduced_latency_when_monitoring")):
        if isinstance(settings_before.get(source), bool):
            context[key] = settings_before[source]
    context["settings_source"] = settings_before.get("evidence", {}).get("source")
    context["settings_method_version"] = settings_before.get("evidence", {}).get("method_version")
    tracks, transport = plan["tracks"], plan["transport"]
    if transport.get("playing") is not False:
        raise RuntimeError("Native capture requires stopped transport; active-position restoration is not physically qualified")
    profile_before = read_routing_profile(bridge)
    if profile_before["profile"].get("critical_unknown_fields"):
        raise RuntimeError("Critical original routing topology is unreadable; measured offsets cannot be bound")
    begin, end = max(0, start - pre), start + length + post
    expected_seconds = (end - begin) * 60 / transport["tempo"]
    if duration <= expected_seconds + 2:
        raise ValueError("Native capture budget must cover playback plus startup")
    root = Path(args.get("output_directory") or (state_dir() / "audio_captures_in_mix")).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < math.ceil(duration * 384000 * len(tracks) * 2 * 8 * 2) + 64 * 1024 * 1024:
        raise ValueError("Insufficient disk space for native copies and derived interleave")
    token = uuid.uuid4().hex
    directory = root / token
    directory.mkdir()
    manifest_path = directory / "manifest.json"
    manifest = {"take_id": token, "complete": False, "cleanup_complete": False, "mode": "in_mix_native_arrangement",
                "capture_engine": "live_native_arrangement", "derivative_clock": "constructed_from_native",
                "native_acquisition": {"epoch_id": token, "receivers_monitor_off": False,
                                       "frame_zero_mapping_verified": False},
                "runtime": runtime, "runtime_identity": runtime_identity, "song_ref": plan["song_ref"],
                "capture_context": context, "source_contexts": plan.get("source_contexts", []),
                "live_settings_observations": [{"phase": "planning", **settings_before}],
                "routing_profile": profile_before["profile"], "routing_profile_sha256": profile_before["sha256"],
                "routing_profile_observations": [{"phase": "before", **profile_before}], "routing_profile_stable": False,
                "requested": args, "prior_transport": transport, "tracks": tracks, "unsupported_tracks": plan.get("unsupported_tracks", []),
                "raw_untrimmed": True, "sample_aligned": False, "shared_sample_clock": False,
                "alignment": {"verified": False, "uncertainty_samples": None,
                              "source": "native Arrangement recording epoch; frame-zero/PDC mapping requires measured qualification"},
                "provenance": {"disjoint_contributions": False, "in_mix_levels": False, "signal_path": plan["signal_path"]},
                "native_clock": {"engine": "Ableton Live", "simultaneous_record_command": True, "acquisition_epoch_verified": False,
                                 "punch_out_bounds_clip_only": True,
                                 "watchdog": "Remote Script scheduler-owned deadline; requires functioning Live scheduler"},
                "owned_receivers": [], "observations": [], "recorder_settings": {"monitoring": "off", "acquisition": "native Arrangement recording"}}
    deadline = time.monotonic() + duration
    healthy, mutated, began, removed = True, False, False, False
    captured = None

    def persist():
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(manifest_path)

    def call(method, params):
        nonlocal healthy
        intent = params if method != "exec" else {"code_sha256": hashlib.sha256(params["code"].encode("utf-8")).hexdigest()}
        manifest["last_rpc"] = {"method": method, "params": intent, "outcome": "submitted"}
        persist()
        try:
            result = bridge.request(method, params)
        except Exception:
            healthy = False
            raise
        manifest["last_rpc"]["outcome"] = "acknowledged"
        persist()
        return result

    def settle(method, params, key):
        result = call(method, params)
        settle_deadline = time.monotonic() + 10
        while not result.get(key) and result.get("pending") in ("transport_stop", "transport_seek") and time.monotonic() < settle_deadline:
            time.sleep(0.1)
            result = call(method, params)
        if not result.get(key):
            raise RuntimeError("Native transport phase did not settle: " + method)
        return result

    persist()
    try:
        mutated = True
        manifest["prepare"] = settle("native_in_mix_prepare", {"token": token, "start_beat": begin, "end_beat": end}, "prepared")
        manifest["native_clock"]["engine_punch_out_beat"] = end
        persist()
        for track in tracks:
            setup = call("in_mix_capture_add_receiver", {"token": token, "source_ref": track["ref"], "native": True})
            manifest["owned_receivers"].append(setup)
            persist()
            route_deadline = min(deadline, time.monotonic() + 10)
            while setup.get("pending") == "routing_settle" and time.monotonic() < route_deadline:
                time.sleep(0.1)
                setup = call("in_mix_capture_configure_receiver", {"token": token, "receiver_ref": setup["receiver_ref"]})
                manifest["owned_receivers"][-1] = setup
                persist()
            if not setup.get("ok"):
                raise RuntimeError("Native receiver setup failed: %s" % setup)
        if deadline - time.monotonic() <= expected_seconds + 2:
            raise RuntimeError("Native setup exhausted the requested playback budget")
        record_bound = min(deadline - time.monotonic(), expected_seconds + 2)
        manifest["native_clock"]["watchdog_duration_seconds"] = record_bound
        manifest["native_clock"]["watchdog_basis"] = "requested passage at initial tempo plus 2 seconds; independent of setup budget"
        began = True
        manifest["begin_ack"] = call("native_in_mix_begin", {"token": token, "max_duration_seconds": record_bound})
        manifest["native_acquisition"]["recording_start"] = manifest["begin_ack"]
        manifest["native_acquisition"]["receivers_monitor_off"] = manifest["begin_ack"].get("begun") is True
        persist()
        previous = begin
        previous_observed = time.monotonic()
        while time.monotonic() < deadline:
            status = call("native_in_mix_status", {"token": token})
            current = status["transport"]["time"]
            observed = time.monotonic()
            manifest["observations"].append({"monotonic": observed, "transport": status["transport"],
                                              "receivers": [{"receiver_ref": item["receiver_ref"], "arm": item["arm"],
                                                             "input_meter_left": item.get("input_meter_left"), "input_meter_right": item.get("input_meter_right")}
                                                            for item in status["receivers"]]})
            if current < previous:
                raise RuntimeError("Arrangement moved backwards during native recording")
            tempo_bound = max(transport["tempo"], status["transport"].get("tempo", transport["tempo"]))
            if current - previous > (observed - previous_observed) * tempo_bound / 60 * 2 + 2:
                raise RuntimeError("Arrangement jumped forwards during native recording")
            previous = current
            previous_observed = observed
            if current >= end:
                break
            if status["transport"]["playing"] is False:
                raise RuntimeError("Native transport stopped before requested endpoint")
            if status.get("watchdog_error"):
                raise RuntimeError("Native watchdog failed: " + status["watchdog_error"])
            time.sleep(0.1)
        else:
            raise RuntimeError("Native capture deadline exceeded; owned scheduler watchdog remains armed")
        manifest["stop_ack"] = settle("native_in_mix_stop", {"token": token}, "stopped")
        manifest["native_acquisition"]["recording_stop"] = manifest["stop_ack"]
        began = False
        persist()
        metadata_deadline = time.monotonic() + 10
        while time.monotonic() < metadata_deadline:
            captured = call("native_in_mix_status", {"token": token})
            if all(len(item["clips"]) == 1 and item["clips"][0].get("file_path") and item["clips"][0].get("is_recording") is False for item in captured["receivers"]):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Native clip metadata did not finalize after stop")
        manifest["native_recordings"] = captured["receivers"]
        if len(captured["receivers"]) != len(tracks):
            raise RuntimeError("Native final receiver/source identity count changed")
        for expected, setup, actual in zip(tracks, manifest["owned_receivers"], captured["receivers"]):
            actual_start = actual["clips"][0].get("start_time")
            if (not isinstance(actual_start, (int, float)) or not math.isfinite(actual_start)
                    or abs(actual_start - begin) > 1e-7):
                raise RuntimeError("Native recording clip did not begin at the requested acquisition epoch")
            if (actual.get("receiver_ref") != setup.get("receiver_ref")
                    or actual.get("source_ref", {}).get("id") != expected["ref"].get("id")
                    or actual.get("route_verified") is not True or actual.get("current_monitoring_state") != 2
                    or actual.get("output_type") != "Sends Only" or actual.get("sends_zero") is not True
                    or actual.get("devices_empty") is not True):
                raise RuntimeError("Native final acquisition routing proof does not match configured identities")
        settings_after = read_live_settings(expected_pid=serving_pid)
        manifest["live_settings_observations"].append({"phase": "after_stop", **settings_after})
        keys = ("delay_compensation", "reduced_latency_when_monitoring")
        same = (all(settings_before.get(key) == settings_after.get(key) for key in keys)
                and settings_after.get("evidence", {}).get("pid") == serving_pid)
        manifest["live_settings_stable"] = same and all(isinstance(settings_before.get(key), bool) for key in keys)
        if not same:
            raise RuntimeError("Live recording/PDC settings or verified process changed during capture")
        profile_after = read_routing_profile(bridge, request=call)
        manifest["routing_profile_observations"].append({"phase": "end", **profile_after})
        manifest["routing_profile_stable"] = profile_after["sha256"] == profile_before["sha256"]
        if not manifest["routing_profile_stable"]:
            raise RuntimeError("Critical original routing/latency profile changed during capture")
        manifest["native_clock"]["begin_unix"] = captured.get("begin_unix")
        manifest["native_clock"]["originals_disarmed"] = True
        persist()
        _require_runtime(bridge)
        manifest["cleanup"] = call("in_mix_capture_cleanup", {"token": token, "selected_device": plan.get("selected_device")})
        removed = True
        manifest["cleanup_complete"] = manifest["cleanup"].get("ok") is True
        persist()
        # Live on Windows retains writer handles until owned recording tracks are removed.
        manifest["tracks"], derivative, wav = _copy_native_recordings(captured["receivers"], tracks, directory)
        manifest["interleaved_path"], manifest["interleaved_wav"] = derivative, wav
        if wav["duration_seconds"] < expected_seconds * 0.7:
            raise RuntimeError("Native recording is grossly shorter than requested passage at initial tempo")
        manifest["interleaved_is_reconstructed"] = True
        manifest["interleave_evidence"] = {"acquisition_file": False, "frame_faithful_derivative": True,
                                           "padding": False, "resampling": False, "gain_applied": False}
        manifest["recorder_settings"]["sample_rate"] = wav["sample_rate"]
        manifest["complete"] = True
    except Exception as exc:
        manifest["error"] = str(exc)
    finally:
        if mutated and healthy:
            try:
                _require_runtime(bridge)
                if began:
                    manifest["finally_stop"] = settle("native_in_mix_stop", {"token": token}, "stopped")
                if not removed:
                    manifest["cleanup"] = call("in_mix_capture_cleanup", {"token": token, "selected_device": plan.get("selected_device")})
                    manifest["cleanup_complete"] = manifest["cleanup"].get("ok") is True
                manifest["native_restore"] = call("native_in_mix_restore", {"token": token})
                manifest["restore"] = settle("audio_capture_restore", {"loop": transport["loop"], "selected_track": plan.get("selected_track")}, "restored")
                call("transport", {"action": "stop", "time": transport["time"]})
            except Exception as exc:
                manifest["cleanup_error"] = str(exc)
        else:
            manifest["cleanup_blocked"] = "Unknown Live mutation outcome; exact owned take/receivers retained for explicit recovery"
        persist()
    return {"ok": manifest["complete"] and manifest["cleanup_complete"] and not manifest.get("cleanup_error"),
            "manifest_path": str(manifest_path), **manifest}
