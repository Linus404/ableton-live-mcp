"""Bind in-mix capture qualification to measured local evidence, never flags alone."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from contextlib import ExitStack

from ableton_paths import state_dir

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_CHECKS = {"post_mixer_gain", "pan", "mute", "shared_clock", "programme_path", "latency"}


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def code_hashes():
    return {name: _hash(path) for name, path in {
        "capture": ROOT / "src" / "in_mix_capture.py",
        "remote_script": ROOT / "Ableton_Live_MCP" / "bridge.py",
        "calibration": ROOT / "src" / "in_mix_calibration.py",
        "qualification": Path(__file__),
        "live_settings": ROOT / "src" / "live_settings.py",
        "assessment": ROOT / "src" / "audio_assessment.py",
    }.items()}


def certificate_path():
    return state_dir() / "in_mix" / "qualification.json"


def source_profile(entry):
    """Only experimentally exercised terminal audio paths have an applicable profile."""
    if not isinstance(entry, dict) or not isinstance(entry.get("context"), dict):
        raise ValueError("source context is unavailable")
    context = entry.get("context") or {}
    if entry.get("kind") != "track" or entry.get("role") != "contribution" or context.get("output_type") not in ("Main", "Master"):
        raise ValueError("source topology was not experimentally qualified")
    delays = [context.get(key) for key in ("delay_in_ms", "track_delay")]
    if any(value is not None and (type(value) not in (int, float) or not math.isfinite(value)) for value in delays):
        raise ValueError("source delay diagnostics are invalid")
    devices = context.get("devices")
    if not isinstance(devices, list) or len(devices) > 1 or any(not isinstance(device, dict) or device.get("class_name") != "Limiter" for device in devices):
        raise ValueError("source device/PDC topology was not experimentally qualified")
    if not isinstance(context.get("output_channel"), str):
        raise ValueError("source output channel is unavailable")
    return {key: context.get(key) for key in ("output_type", "output_channel", "delay_in_ms", "track_delay", "devices")}


def _read_certificate(path):
    if not 0 < path.stat().st_size <= 256 * 1024:
        raise ValueError("qualification certificate size is invalid")
    certificate = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(certificate, dict):
        raise ValueError("qualification certificate must be an object")
    return certificate


def _live_id(ref):
    identity = ref.get("id") if isinstance(ref, dict) else None
    if type(identity) is not int or identity <= 0:
        raise ValueError("native route proof requires a positive Live object ID")
    return identity


def routing_profile_hash(profile):
    if not isinstance(profile, dict) or profile.get("schema_version") != 1 or profile.get("critical_unknown_fields"):
        raise ValueError("routing/latency topology is unavailable or critically opaque")
    tracks = profile.get("tracks")
    if not isinstance(tracks, list) or len(tracks) > 512:
        raise ValueError("routing profile track scope is invalid")
    names = {}
    edges = {_live_id(track["ref"]): set() for track in tracks}
    if len(edges) != len(tracks):
        raise ValueError("routing profile source identities are ambiguous")
    for track in tracks:
        names.setdefault(track.get("name"), []).append(_live_id(track["ref"]))
    for track in tracks:
        identity = _live_id(track["ref"])
        for field, reverse in (("output_type", False), ("input_type", True)):
            matches = names.get(track.get(field), [])
            if len(matches) > 1:
                raise ValueError("routing profile contains ambiguous source names")
            if matches:
                edges[matches[0] if reverse else identity].add(identity if reverse else matches[0])
        for send in track.get("sends", []):
            if send.get("value", 0) > 0:
                target = _live_id(send["target_ref"])
                if target not in edges:
                    raise ValueError("send routing target is not pinned in the original graph")
                edges[identity].add(target)
    active, done = set(), set()

    def visit(identity):
        if identity in active:
            raise ValueError("feedback routing is unsupported for target calibration")
        if identity in done:
            return
        active.add(identity)
        for target in edges[identity]:
            visit(target)
        active.remove(identity); done.add(identity)

    for identity in edges:
        visit(identity)
    return hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def track_offset(track, offsets, source_offsets=None):
    if track["role"] == "contribution":
        specific = (source_offsets or {}).get(str(_live_id(track.get("ref"))))
        if specific is not None:
            return specific
    return offsets[track["role"]]


def verify_native_sum(manifest, offsets, source_offsets=None):
    """Verify this recording at fixed measured offsets; never search for a better lag."""
    import numpy as np
    import soundfile as sf
    from audio_capture import validate_wav
    tracks = manifest.get("tracks")
    if (not isinstance(tracks, list) or not 2 <= len(tracks) <= 16
            or any(not isinstance(track, dict) or track.get("role") not in ("contribution", "program") for track in tracks)
            or sum(track["role"] == "program" for track in tracks) != 1):
        raise ValueError("native sum requires bounded contributions and exactly one programme")
    clock = manifest.get("native_clock") or {}
    acquisition = manifest.get("native_acquisition") or {}
    if (clock.get("engine") != "Ableton Live" or clock.get("simultaneous_record_command") is not True
            or clock.get("originals_disarmed") is not True or manifest.get("live_settings_stable") is not True
            or manifest.get("interleaved_is_reconstructed") is not True
            or manifest.get("capture_engine") != "live_native_arrangement"
            or manifest.get("derivative_clock") != "constructed_from_native"
            or acquisition.get("epoch_id") != manifest.get("take_id") or not acquisition.get("epoch_id")
            or acquisition.get("receivers_monitor_off") is not True):
        raise ValueError("native recording ownership/settings evidence is incomplete")
    start, stop = acquisition.get("recording_start") or {}, acquisition.get("recording_stop") or {}
    if (start.get("token") != acquisition["epoch_id"] or start.get("begun") is not True
            or stop.get("token") != acquisition["epoch_id"] or stop.get("stopped") is not True):
        raise ValueError("native begin/stop acknowledgements do not share the owned epoch")
    metadata, paths, refs, source_refs, edges = [], set(), set(), set(), set()
    request = manifest.get("requested") or {}
    requested_start, requested_pre = request.get("start_beat"), request.get("pre_roll_beats", 0)
    if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in (requested_start, requested_pre)):
        raise ValueError("native capture lacks bounded requested start/pre-roll")
    requested_begin = max(0, requested_start - requested_pre)
    for track in tracks:
        path = Path(track["path"]).resolve()
        info = validate_wav(path)
        if (path in paths or info["channels"] != 2 or info["duration_seconds"] > 600
                or info["frames"] * 2 > 12_000_000 or info["bytes"] > 128 * 1024**2
                or info["bits_per_sample"] not in (24, 32, 64)):
                raise ValueError("native source WAV exceeds format/resource bounds or duplicates a path")
        paths.add(path)
        if _hash(path) != track.get("native_sha256"):
            raise ValueError("native acquisition copy changed")
        receiver = track.get("receiver_ref") or {}
        identity = _live_id(receiver)
        if identity in refs:
            raise ValueError("native receiver identity is missing or duplicated")
        refs.add(identity)
        source_identity = _live_id(track.get("ref"))
        if source_identity in source_refs:
            raise ValueError("native source identity is missing or duplicated")
        source_refs.add(source_identity)
        initial = [item for item in manifest.get("owned_receivers", []) if _live_id(item.get("receiver_ref")) == identity]
        final = [item for item in manifest.get("native_recordings", []) if _live_id(item.get("receiver_ref")) == identity]
        if len(initial) != 1 or len(final) != 1:
            raise ValueError("native receiver lacks initial/final route readback")
        wanted = "Resampling" if track["role"] == "program" else track["name"]
        for route in (initial[0], final[0]):
            if (_live_id(route.get("source_ref")) != source_identity
                    or route.get("input_type") != wanted or route.get("output_type") != "Sends Only"
                    or (track["role"] != "program" and route.get("input_channel") != "Post Mixer")):
                raise ValueError("native receiver routing does not match its declared acquisition source")
        if (final[0].get("current_monitoring_state") != 2 or final[0].get("sends_zero") is not True
                or final[0].get("devices_empty") is not True):
            raise ValueError("native receiver monitoring/isolation changed")
        clip = track.get("native_clip") or {}
        if (clip.get("sample_rate") != info["sample_rate"] or clip.get("sample_length") != info["frames"]
                or clip.get("is_recording") is not False or type(clip.get("warping")) is not bool):
            raise ValueError("native file/clip epoch metadata is inconsistent or warped")
        edge = (clip.get("start_time"), clip.get("end_time"))
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in edge) or edge[1] <= edge[0]:
            raise ValueError("native recorded clip edges are unavailable")
        if edge[0] != requested_begin:
            raise ValueError("native recording starts outside its requested acquisition epoch")
        edges.add(edge)
        metadata.append(info)
    if len(edges) != 1 or len({(info["sample_rate"], info["frames"]) for info in metadata}) != 1:
        raise ValueError("native recording epochs/layouts differ")
    if sum(info["frames"] * 2 for info in metadata) > 96_000_000:
        raise ValueError("native verification exceeds total sample budget")
    derivative = Path(manifest["interleaved_path"])
    derivative_info = validate_wav(derivative)
    if (derivative_info["format"] != "float" or derivative_info["bits_per_sample"] != 64
            or derivative_info["channels"] != 2 * len(tracks)
            or any(derivative_info[key] != metadata[0][key] for key in ("sample_rate", "frames"))):
        raise ValueError("native derivative layout is invalid")
    energy, residual_energy, peak_error, checked = 0.0, 0.0, 0.0, 0
    # Full quantization steps cover truncation as well as rounding; do not assume
    # the recorder's quantizer or dither configuration from its PCM bit depth.
    quantum = sum(2.0 ** (1 - info["bits_per_sample"]) for info in metadata if info["format"] == "pcm")
    per_track = [track_offset(track, offsets, source_offsets) for track in tracks]
    frames = metadata[0]["frames"] - max(per_track)
    if frames <= 0:
        raise ValueError("native aligned interval is empty")
    with ExitStack() as stack:
        files = [stack.enter_context(sf.SoundFile(track["path"])) for track in tracks]
        interleaved = stack.enter_context(sf.SoundFile(str(derivative)))
        # Validate the derivative without mistaking it for acquisition clock evidence.
        for start in range(0, metadata[0]["frames"], 65536):
            count = min(65536, metadata[0]["frames"] - start)
            block = interleaved.read(count, dtype="float64", always_2d=True)
            for index, handle in enumerate(files):
                native = handle.read(count, dtype="float64", always_2d=True)
                if not np.isfinite(native).all() or not np.array_equal(native, block[:, 2 * index:2 * index + 2]):
                    raise ValueError("native copy differs from reconstructed channel map")
                info = metadata[index]
                if info["format"] == "pcm" and (np.any(native <= -1) or np.any(native >= 1 - 2.0 ** (1 - info["bits_per_sample"]))):
                    raise ValueError("possible PCM acquisition clipping at a rail; linear in-mix proof is unsupported")
        for offset, handle in zip(per_track, files):
            handle.seek(offset)
        program_index = next(index for index, track in enumerate(tracks) if track["role"] == "program")
        while checked < frames:
            count = min(65536, frames - checked)
            blocks = [handle.read(count, dtype="float64", always_2d=True) for handle in files]
            program = blocks[program_index]
            parts = [block for index, block in enumerate(blocks) if index != program_index]
            summed = np.sum(parts, axis=0)
            error = summed - program
            # Quantization plus conservative float32 engine summation round-off.
            bound = quantum + 4 * len(parts) * np.finfo(np.float32).eps * (np.sum(np.abs(parts), axis=0) + np.abs(program)) + 1e-12
            if np.any(np.abs(error) > bound):
                raise ValueError("native current-take programme is not the fixed-offset sum of all captured contributions")
            energy += float(np.sum(program * program))
            residual_energy += float(np.sum(error * error))
            peak_error = max(peak_error, float(np.max(np.abs(error))))
            checked += count
    if energy <= checked * 2 * 1e-12:
        raise ValueError("native programme is silent; current-take timing is unmeasured")
    return {"frames_checked": checked, "offsets_samples": dict(offsets), "programme_rms": math.sqrt(energy / (checked * 2)),
            "source_offsets_samples": dict(source_offsets or {}), "common_crop_samples": max(per_track),
            "relative_residual": math.sqrt(residual_energy / energy), "peak_error": peak_error,
            "method": "fixed experimentally measured role offsets; per-sample quantization/float32 rounding bound"}


def _check_certificate(certificate, manifest):
    json.dumps(certificate, allow_nan=False)
    if certificate.get("origin") != "computed_from_captured_audio" or certificate.get("schema_version") != 1:
        raise ValueError("qualification requires measured experimental evidence")
    checks = certificate.get("checks")
    if not isinstance(checks, dict) or set(checks) != REQUIRED_CHECKS or any(value is not True for value in checks.values()):
        raise ValueError("qualification checks are incomplete or failed")
    if certificate.get("code_hashes") != code_hashes():
        raise ValueError("qualification is stale after capture/recorder/bridge changes")
    replay = certificate.get("replay")
    if replay is not None:
        path = Path(replay["snapshot_path"])
        if path.stat().st_size > 4 * 1024 * 1024 or _hash(path) != replay.get("snapshot_sha256"):
            raise ValueError("calibration replay provenance changed or exceeds bounds")
        if any(replay.get("unchanged_acquisition_hashes", {}).get(key) != code_hashes()[key] for key in ("capture", "remote_script", "live_settings")):
            raise ValueError("calibration replay acquisition implementation changed")
    native = certificate.get("capture_mode") == "in_mix_native_arrangement"
    if not native:
        raise ValueError("retired MSP-bus capture is not a supported acquisition pipeline")
    if (manifest.get("mode") != certificate.get("capture_mode")
            or certificate.get("clock_origin") != "experimentally_measured_native_recording_epoch"):
        raise ValueError("capture engine/sample-clock origin was not experimentally qualified")
    if certificate.get("song_id") is None or certificate.get("song_id") != manifest.get("song_ref", {}).get("id"):
        raise ValueError("qualification belongs to a different Live session/set")
    identity = manifest.get("runtime_identity") or {}
    if not identity.get("runtime_code_sha256") or certificate.get("runtime_code_sha256") != identity["runtime_code_sha256"]:
        raise ValueError("qualification loaded-runtime fingerprint mismatch")
    if native:
        pid = identity.get("process_id")
        observations = manifest.get("live_settings_observations")
        if (type(pid) is not int or pid <= 0 or certificate.get("process_id") != pid
                or not isinstance(observations, list) or len(observations) != 2
                or any(not isinstance(item, dict) for item in observations)
                or {item.get("phase") for item in observations} != {"planning", "after_stop"}
                or any(item.get("evidence", {}).get("pid") != pid for item in observations)):
            raise ValueError("native settings evidence does not identify the serving Live process")
    wav = manifest.get("interleaved_wav") or {}
    rate = certificate.get("sample_rate")
    if type(rate) is not int or not 8000 <= rate <= 384000 or rate != wav.get("sample_rate"):
        raise ValueError("qualification sample rate mismatch")
    context = certificate.get("capture_context")
    if (not isinstance(context, dict) or not isinstance(context.get("master"), dict)
            or context.get("global_delay_compensation") is not True
            or type(context.get("reduced_latency_when_monitoring")) is not bool):
        raise ValueError("qualification lacks known enabled global PDC, reduced-latency setting and Master context")
    if context != manifest.get("capture_context"):
        raise ValueError("qualification Master/processing context changed")
    if native and context.get("reduced_latency_when_monitoring") is not False:
        raise ValueError("native source-monitoring bypass has not been qualified with reduced latency enabled")
    if native and any(item.get("delay_compensation") is not True or item.get("reduced_latency_when_monitoring") is not False
                      or item.get("evidence", {}).get("source") != "windows_native_options_menu"
                      or item.get("evidence", {}).get("method_version") != 1 for item in observations):
        raise ValueError("native settings readback is unavailable or inconsistent with acquisition context")
    settings = certificate.get("recorder_settings")
    if (not isinstance(settings, dict) or set(settings) != {"sample_rate", "monitoring", "acquisition"}
            or settings.get("sample_rate") != rate or settings.get("monitoring") != "off"
            or settings.get("acquisition") != "native Arrangement recording"):
        raise ValueError("qualification recorder settings are unavailable or invalid")
    if settings != manifest.get("recorder_settings"):
        raise ValueError("qualification recorder settings changed")
    offsets = certificate.get("role_offsets_samples")
    if (not isinstance(offsets, dict) or set(offsets) != {"contribution", "program"}
            or any(type(value) is not int or not 0 <= value < rate // 4 for value in offsets.values())
            or min(offsets.values()) != 0):
        raise ValueError("qualification lacks bounded measured role offsets")
    source_offsets = certificate.get("source_offsets_samples", {})
    if (not isinstance(source_offsets, dict) or len(source_offsets) > 15
            or any(not isinstance(key, str) or not key.isdigit() or int(key) <= 0 for key in source_offsets)
            or any(type(value) is not int or not 0 <= value < rate // 4 for value in source_offsets.values())):
        raise ValueError("qualification measured source offsets are invalid")
    profile_sha = routing_profile_hash(certificate.get("routing_profile"))
    if (certificate.get("routing_profile_sha256") != profile_sha or manifest.get("routing_profile_sha256") != profile_sha
            or routing_profile_hash(manifest.get("routing_profile")) != profile_sha or manifest.get("routing_profile_stable") is not True):
        raise ValueError("original routing/latency profile changed or is unverified")
    profile_observations = manifest.get("routing_profile_observations")
    if (not isinstance(profile_observations, list) or len(profile_observations) != 2
            or {item.get("phase") for item in profile_observations} != {"before", "end"}
            or any(item.get("sha256") != profile_sha or routing_profile_hash(item.get("profile")) != profile_sha for item in profile_observations)):
        raise ValueError("original routing/latency profile lacks matching before/end readbacks")
    profiles = certificate.get("source_profiles")
    sources = manifest.get("source_contexts")
    if (not isinstance(profiles, list) or not 1 <= len(profiles) <= 2 or any(not isinstance(profile, dict) for profile in profiles)
            or not isinstance(sources, list) or not 1 <= len(sources) <= 15):
        raise ValueError("qualification lacks source applicability evidence")
    tracks = manifest.get("tracks")
    if (not isinstance(tracks, list) or not 2 <= len(tracks) <= 16
            or any(not isinstance(track, dict) or track.get("role") not in ("contribution", "program") or not isinstance(track.get("name"), str) for track in tracks)
            or sum(track["role"] == "program" for track in tracks) != 1
            or len(sources) != len(tracks) - 1 or len({track["name"] for track in tracks}) != len(tracks)):
        raise ValueError("capture contains unsupported/incomplete or ambiguous source identities")
    if manifest.get("unsupported_tracks"):
        # One shared exact-selection/real-route guard for qualification and the
        # assessment adapter; a reason string alone never establishes capability.
        from audio_assessment import _verify_partition_exclusions
        _verify_partition_exclusions(manifest)
    if native:
        roles = certificate.get("native_source_kinds")
        if not isinstance(roles, list) or not roles or any(kind not in ("track", "group", "return") for kind in roles):
            raise ValueError("native acquisition role experiments are unavailable")
        target_evidence = certificate.get("target_offset_evidence", {})
        if not isinstance(target_evidence, dict) or set(target_evidence) != set(source_offsets):
            raise ValueError("source offsets lack corresponding physical target experiments")
        measured_roles = {"track"}
        originals = {str(_live_id(item["ref"])): item for item in certificate["routing_profile"].get("tracks", [])}
        for source_id, target in target_evidence.items():
            if (source_id not in originals or target.get("kind") not in ("group", "return")
                    or target["kind"] != originals[source_id].get("kind") or target.get("profile_sha256") != profile_sha):
                raise ValueError("target calibration is not bound to the original source topology")
            epochs = target.get("epochs")
            if not isinstance(epochs, list) or len(epochs) != 2 or len({item.get("take_id") for item in epochs}) != 2:
                raise ValueError("target offset requires two independent physical recording epochs")
            for experiment in epochs:
                path = Path(experiment["manifest_path"])
                if path.stat().st_size > 2 * 1024 * 1024 or _hash(path) != experiment.get("manifest_sha256"):
                    raise ValueError("target experiment manifest changed or exceeds bounds")
                rms = experiment.get("rms")
                if (type(experiment.get("offset_samples")) is not int or experiment["offset_samples"] != source_offsets[source_id]
                        or type(rms) not in (int, float) or not math.isfinite(rms) or rms <= 1e-6):
                    raise ValueError("target timing experiments disagree or lack nonzero signal")
                similarity = experiment.get("signature_correlation")
                if type(similarity) not in (int, float) or not math.isfinite(similarity) or similarity < 0.999 or experiment.get("unique_lag") is not True:
                    raise ValueError("target waveform lag is unmeasured or ambiguous")
            measured_roles.add(target["kind"])
        if not set(roles) <= measured_roles:
            raise ValueError("native group/return acquisition lacks physical role evidence")
        contributions = [track for track in tracks if track["role"] == "contribution"]
        if any(track.get("kind") != entry.get("kind") for track, entry in zip(contributions, sources)):
            raise ValueError("native source role metadata disagrees with the captured channel map")
        for entry in sources:
            context_source = entry.get("context") or {}
            if entry.get("kind") not in roles or entry.get("role") != "contribution" or context_source.get("output_type") not in ("Master", "Main"):
                raise ValueError("native source role/routing was not experimentally qualified")
            delays = [context_source.get(key) for key in ("delay_in_ms", "track_delay")]
            if any(value is not None and (type(value) not in (int, float) or not math.isfinite(value)) for value in delays):
                raise ValueError("native source delay diagnostics are invalid")
            if any(value is not None and value != 0 for value in delays):
                raise ValueError("known nonzero native track delay has not been experimentally qualified")
            # Unavailable delays remain null. Any applied delay is already part of
            # the captured Post Mixer signal; fixed-offset current waveform sum
            # verifies its actual relationship to programme without guessing zero.
        for track in contributions:
            if track.get("kind") in ("group", "return") and str(_live_id(track["ref"])) not in source_offsets:
                raise ValueError("this current group/return source has no measured fixed offset")
    evidence = certificate.get("evidence")
    if not isinstance(evidence, list) or not 7 <= len(evidence) <= 256:
        raise ValueError("qualification lacks bounded retained experiment evidence")
    paths, total = set(), 0
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"} or not isinstance(item["path"], str):
            raise ValueError("qualification experiment evidence is invalid")
        path = Path(item["path"]).resolve()
        size = path.stat().st_size
        total += size
        if path in paths or not 0 < size <= 128 * 1024**2 or total > 1024**3:
            raise ValueError("qualification experiment evidence exceeds resource bounds or repeats")
        paths.add(path)
        if _hash(path) != item["sha256"]:
            raise ValueError("qualification experiment evidence changed or is missing")
    if not isinstance(certificate.get("measurements"), dict) or not certificate["measurements"]:
        raise ValueError("qualification lacks recorded numerical measurements")
    measurements = certificate["measurements"]
    required = {"baseline", "repeat", "gain_minus_6", "volume_zero", "mute", "pan_right", "latency"}
    if set(measurements) != required:
        raise ValueError("qualification lacks all seven measured experiments")
    for row in measurements.values():
        if (not isinstance(row, dict) or type(row.get("source_b_rms")) not in (int, float)
                or not math.isfinite(row["source_b_rms"]) or row["source_b_rms"] <= 1e-6
                or type(row.get("programme_lag_samples")) is not int
                or row.get("programme_lag_samples") != offsets["program"] - offsets["contribution"]
                or type(row.get("programme_sum_error")) not in (int, float)
                or not math.isfinite(row["programme_sum_error"]) or not 0 <= row["programme_sum_error"] <= 2e-4):
            raise ValueError("qualification measured signal/latency evidence is invalid")
        if native and (type(row.get("expected_fixture_offset_samples")) is not int
                       or row.get("fixture_offset_samples") != row["expected_fixture_offset_samples"]):
            raise ValueError("native qualification does not establish the expected fixture sample epoch")
    gain = measurements["gain_minus_6"]
    if (type(gain.get("gain_db")) not in (int, float) or not math.isfinite(gain["gain_db"]) or abs(gain["gain_db"] + 6) > 0.1
            or type(gain.get("gain_error")) not in (int, float) or not math.isfinite(gain["gain_error"]) or not 0 <= gain["gain_error"] <= 0.002):
        raise ValueError("qualification finite fader gain evidence is invalid")
    if native:
        master = context["master"]
        if (master.get("devices") != [] or (master.get("mute") is not None and master.get("mute") is not False)
                or master.get("panning") != 0):
            raise ValueError("native current-sum qualification requires unprocessed centred unmuted Master")
        verify_native_sum(manifest, offsets, source_offsets)
    return certificate


def verify_qualification(manifest):
    """Offline check of a pipeline qualification and its retained evidence binding."""
    proof = manifest.get("qualification") or {}
    if proof.get("verified") is not True or proof.get("kind") != "live_experimental":
        raise ValueError("capture has no verified experimental qualification")
    path = Path(proof.get("certificate_path", "")).resolve()
    if path != certificate_path().resolve() or path.stat().st_size > 256 * 1024:
        raise ValueError("qualification certificate location or size is invalid")
    if _hash(path) != proof.get("certificate_sha256"):
        raise ValueError("qualification certificate changed after capture")
    certificate = _read_certificate(path)
    _check_certificate(certificate, manifest)
    if manifest.get("complete") is not True or manifest.get("cleanup_complete") is not True:
        raise ValueError("capture or cleanup is incomplete")
    return {"kind": "live_experimental", "checks": certificate["checks"],
            "measurements": certificate["measurements"], "certificate_sha256": proof["certificate_sha256"]}


def attach_qualification(result):
    """Attach only an applicable certificate; keep unqualified capture diagnostics."""
    result = dict(result)
    path = certificate_path()
    try:
        if result.get("complete") is not True or result.get("cleanup_complete") is not True:
            raise ValueError("capture or cleanup is incomplete")
        certificate = _read_certificate(path)
        _check_certificate(certificate, result)
        result["qualification"] = {"verified": True, "kind": "live_experimental",
            "certificate_path": str(path), "certificate_sha256": _hash(path)}
        offsets = certificate["role_offsets_samples"]
        result["alignment"] = {"verified": True, "uncertainty_samples": 0,
            "source": "Measured native recording epoch and fixed role/source-ID corrections; current sum checks consistency, not independent timing of silent/periodic/cancelling parts",
            "offsets_samples": {t["name"]: track_offset(t, offsets, certificate.get("source_offsets_samples")) for t in result["tracks"]}}
        result["sample_aligned"] = True
        result["shared_sample_clock"] = True
        result["native_clock"] = {**result.get("native_clock", {}), "acquisition_epoch_verified": True}
        result["native_acquisition"] = {**result.get("native_acquisition", {}), "frame_zero_mapping_verified": True}
        result["provenance"] = {"disjoint_contributions": True, "in_mix_levels": True,
            "signal_path": "Qualified terminal Post Mixer contributions and separate Main Resampling programme"}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["qualification"] = {"verified": False, "reason": str(exc)}
        result["sample_aligned"] = False
        result["shared_sample_clock"] = False
        if result.get("mode") == "in_mix_native_arrangement":
            result["native_clock"] = {**result.get("native_clock", {}), "acquisition_epoch_verified": False}
            result["native_acquisition"] = {**result.get("native_acquisition", {}), "frame_zero_mapping_verified": False}
        result["alignment"] = {"verified": False, "uncertainty_samples": None, "source": "experimental qualification unavailable"}
        result["provenance"] = {"disjoint_contributions": False, "in_mix_levels": False, "signal_path": "experimental qualification unavailable"}
    if result.get("manifest_path"):
        stored = {key: value for key, value in result.items() if key not in ("manifest_path", "ok")}
        Path(result["manifest_path"]).write_text(json.dumps(stored, indent=2, allow_nan=False), encoding="utf-8")
    return result
