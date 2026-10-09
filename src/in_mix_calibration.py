"""Repeatable owned-source experiments; qualification is computed from retained WAVs."""
from __future__ import annotations

import json
import math
import re
import uuid
from pathlib import Path

from ableton_paths import state_dir
from audio_capture import _require_runtime, validate_wav
from in_mix_capture import capture_in_mix
from in_mix_qualification import REQUIRED_CHECKS, _check_certificate, _hash, certificate_path, code_hashes, source_profile

SCENARIOS = ("baseline", "repeat", "gain_minus_6", "volume_zero", "mute", "pan_right", "latency")
RELATIVE_ERROR = 2e-4


def _clip_scan_code(track_ids=None):
    """Groups expose no Arrangement clips in the SDK; their regular children do."""
    selected = "" if track_ids is None else " and this._object_id(t) in " + repr(track_ids)
    return "clips = [c for t in song.tracks if t.is_foldable is False" + selected + " for c in t.arrangement_clips]\n"


def _lag(reference, observed, max_lag):
    """Integer signed delay of observed; broadband signature prevents sine ambiguity."""
    import numpy as np
    max_lag = min(max_lag, max(len(reference), len(observed)) - 1)
    size = 1 << (len(reference) + len(observed) - 1).bit_length()
    correlation = np.fft.irfft(np.fft.rfft(observed, size) * np.conj(np.fft.rfft(reference, size)), size)
    lags = np.arange(-max_lag, max_lag + 1)
    values = correlation[lags % size]
    best = int(lags[int(np.argmax(values))])
    if abs(best) == max_lag:
        raise ValueError("signature delay reaches measurement bound")
    return best


def _aligned(reference, observed, lag):
    first, second = max(0, -lag), max(0, lag)
    length = min(len(reference) - first, len(observed) - second)
    if length <= 0:
        raise ValueError("no aligned signal interval")
    return reference[first:first + length], observed[second:second + length]


def _error(reference, observed):
    import numpy as np
    energy = float(np.sum(reference * reference))
    if energy <= 1e-12:
        raise ValueError("reference signal is silent")
    return float(np.sqrt(np.sum((reference - observed) ** 2) / energy))


def measure_experiments(takes, names, fixture_path=None):
    """Validate actual samples, not status booleans. Returns measured role offsets."""
    import numpy as np
    import soundfile as sf
    if set(takes) != set(SCENARIOS) or len(names) != 2:
        raise ValueError("seven calibration scenarios and two owned sources required")
    evidence, measurements, baseline, rate, offsets = [], {}, None, None, []
    fixture_reference = None
    for scenario in SCENARIOS:
        take = takes[scenario]
        if not take.get("complete") or not take.get("cleanup_complete") or take.get("unsupported_tracks"):
            raise ValueError("calibration capture or cleanup incomplete: " + scenario)
        entries = take["tracks"]
        if len(entries) != 3 or {e["name"] for e in entries if e["role"] == "contribution"} != set(names):
            raise ValueError("capture did not retain exactly the owned pair and programme")
        programs = [e for e in entries if e["role"] == "program"]
        if len(programs) != 1:
            raise ValueError("exactly one programme reference required")
        audio_path = take.get("normalized_interleaved_path") or take["interleaved_path"]
        interleaved_info = validate_wav(audio_path)
        current_rate = interleaved_info["sample_rate"]
        if (not 8000 <= current_rate <= 384000 or interleaved_info["channels"] != 6
                or interleaved_info["frames"] / current_rate > 90
                or interleaved_info["frames"] * 6 > 24_000_000
                or interleaved_info["format"] != "float" or interleaved_info["bits_per_sample"] not in (32, 64)):
            raise ValueError("calibration recording exceeds supported format/resource bounds")
        if rate is not None and rate != current_rate:
            raise ValueError("sample rate changed across experiments")
        rate = current_rate
        interleaved, _ = sf.read(audio_path, dtype="float64", always_2d=True)
        if not np.isfinite(interleaved).all() or float(np.max(np.abs(interleaved))) >= 0.95:
            raise ValueError("nonfinite or insufficient-headroom calibration audio")
        signals = {}
        for index, entry in enumerate(entries):
            info = validate_wav(entry["path"])
            if info["bits_per_sample"] not in (24, 32, 64):
                raise ValueError("physical qualification requires PCM24/32 or float32/64; PCM16 is unsupported")
            if info["sample_rate"] != rate or info["frames"] != len(interleaved) or info["channels"] != 2:
                raise ValueError("stereo copies do not share the interleaved frame clock")
            data, _ = sf.read(entry["path"], dtype="float64", always_2d=True)
            if not np.array_equal(data, interleaved[:, 2 * index:2 * index + 2]):
                raise ValueError("stereo copy differs from shared-clock recording")
            signals[entry["name"]] = data.astype("float64")
        # Retain the original interleaved evidence, which contains all three paths.
        if take.get("mode") == "in_mix_native_arrangement":
            evidence.extend({"path": entry["path"], "sha256": _hash(entry["path"])} for entry in entries)
        else:
            evidence.append({"path": audio_path, "sha256": _hash(audio_path)})
        if audio_path != take["interleaved_path"]:
            evidence.append({"path": take["interleaved_path"], "sha256": _hash(take["interleaved_path"])})
        a, b, programme = signals[names[0]], signals[names[1]], signals[programs[0]["name"]]
        active = np.flatnonzero(np.max(np.abs(b), axis=1) > 1e-5)
        if len(active) < rate * 8 or active[0] < rate // 5 or len(b) - active[-1] < rate // 5:
            raise ValueError("fixture first sample/tail or sufficient signal duration not captured")
        # The broadband leading signature and noise floor must survive, not just the sine.
        signature = b[active[0]:active[0] + rate // 4, 0]
        if float(np.sqrt(np.mean(np.diff(signature) ** 2))) < 0.001:
            raise ValueError("broadband fixture signature is missing")
        if _error(b[:, :1], b[:, 1:]) > RELATIVE_ERROR:
            raise ValueError("unchanged source B is not centred stereo")
        row = {"frames": len(b), "first_signal_sample": int(active[0]), "last_signal_sample": int(active[-1]),
               "source_b_rms": float(np.sqrt(np.mean(b ** 2))), "peak": float(np.max(np.abs(interleaved)))}
        if baseline is None:
            baseline = b
            if fixture_path is not None:
                fixture_info = validate_wav(fixture_path)
                if fixture_info["frames"] / fixture_info["sample_rate"] > 12 or fixture_info["channels"] != 2:
                    raise ValueError("invalid bounded calibration fixture")
                fixture, fixture_rate = sf.read(fixture_path, always_2d=True)
                if not np.isfinite(fixture).all():
                    raise ValueError("nonfinite fixture")
                expected = np.interp(np.arange(round(len(fixture) * rate / fixture_rate)) * fixture_rate / rate,
                                     np.arange(len(fixture)), fixture[:, 0])
                fixture_reference = expected
                fixture_lag = _lag(expected, b[:, 0], rate * 30)
                expected_active = np.flatnonzero(np.abs(expected) > 1e-5)
                first = int(expected_active[0])
                observed_first = first + fixture_lag
                count = rate // 4
                if observed_first < 0 or observed_first + count > len(b):
                    raise ValueError("unique fixture signature is not completely captured")
                reference = expected[first:first + count]
                observed = b[observed_first:observed_first + count, 0]
                similarity = float(np.dot(reference, observed) / np.sqrt(np.dot(reference, reference) * np.dot(observed, observed)))
                row.update(fixture_signature_correlation=similarity, fixture_offset_samples=fixture_lag)
                if not math.isfinite(similarity) or similarity < 0.8:
                    raise ValueError("captured source does not match the unique owned fixture signature")
                evidence.append({"path": str(fixture_path), "sha256": _hash(fixture_path)})
        else:
            lag = _lag(baseline[:, 0], b[:, 0], int(rate * 30))
            ref, obs = _aligned(baseline, b, lag)
            row["source_b_repeat_offset_samples"] = lag
            row["source_b_repeat_error"] = _error(ref, obs)
            if row["source_b_repeat_error"] > RELATIVE_ERROR:
                raise ValueError("unchanged source B changed between takes")
        if take.get("mode") == "in_mix_native_arrangement" and fixture_reference is not None:
            requested = take.get("requested") or {}
            tempo = take.get("prior_transport", {}).get("tempo")
            if type(tempo) not in (int, float) or not math.isfinite(tempo) or tempo <= 0:
                raise ValueError("native expected fixture epoch lacks known tempo")
            start, pre = requested.get("start_beat"), requested.get("pre_roll_beats", 0)
            if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in (start, pre)):
                raise ValueError("native expected fixture epoch lacks requested passage")
            begin = max(0, start - pre)
            expected_offset = round((start - begin) * 60 / tempo * rate)
            measured_offset = _lag(fixture_reference, b[:, 0], rate * 30)
            row.update(expected_fixture_offset_samples=expected_offset, fixture_offset_samples=measured_offset)
            if measured_offset != expected_offset or any(entry.get("native_clip", {}).get("start_time") != begin for entry in entries):
                raise ValueError("native fixture signature/clip start does not establish the expected sample epoch")
        if scenario == "latency":
            device = take.get("latency_device") or {}
            delay = device.get("latency_in_samples") or device.get("lookahead_ms") or 0
            enabled = [p.get("value") for p in device.get("parameters", []) if p.get("name", "").lower() == "device on"]
            if (device.get("class_name") != "Limiter" or len(enabled) != 1 or enabled[0] != 1
                    or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay <= 0):
                raise ValueError("latency-bearing active Limiter evidence unavailable")
            row["latency_device"] = device
        if scenario in ("baseline", "repeat", "latency"):
            source_lag = _lag(b[:, 0], a[:, 0], rate // 4)
            ref, obs = _aligned(b, a, source_lag)
            row["contribution_relative_lag_samples"] = source_lag
            row["contribution_error"] = _error(ref, obs)
            if source_lag != 0 or row["contribution_error"] > RELATIVE_ERROR:
                raise ValueError("contributions are not identical zero-offset Post Mixer paths")
        elif scenario == "gain_minus_6":
            gain_db = take.get("gain_db")
            if type(gain_db) not in (int, float) or not math.isfinite(gain_db) or abs(gain_db + 6) > 0.1:
                raise ValueError("finite fader gain experiment lacks measured -6 dB setting")
            expected = 10 ** (gain_db / 20)
            row.update(gain_db=gain_db, expected_gain=expected, gain_error=_error(b * expected, a))
            if row["gain_error"] > 0.002:
                raise ValueError("finite Post Mixer fader gain does not match measured setting")
        elif scenario in ("mute", "volume_zero"):
            row["silenced_a_rms_ratio"] = float(np.sqrt(np.sum(a ** 2) / np.sum(b ** 2)))
            if row["silenced_a_rms_ratio"] > 1e-6:
                raise ValueError(scenario + " did not silence the Post Mixer contribution")
        else:
            row["pan_left_rms_ratio"] = float(np.sqrt(np.sum(a[:, 0] ** 2) / np.sum(b[:, 0] ** 2)))
            row["pan_right_rms_ratio"] = float(np.sqrt(np.sum(a[:, 1] ** 2) / np.sum(b[:, 1] ** 2)))
            if row["pan_left_rms_ratio"] > 2e-5 or not 0.8 <= row["pan_right_rms_ratio"] <= 2:
                raise ValueError("hard-right pan not reflected in the Post Mixer contribution")
        mix = a + b
        lag = _lag(mix.sum(axis=1), programme.sum(axis=1), rate // 4)
        ref, obs = _aligned(mix, programme, lag)
        row["programme_lag_samples"] = lag
        row["programme_sum_error"] = _error(ref, obs)
        # Correlation trimming must not hide unrelated audio at unmatched edges.
        unmatched = programme[:max(0, lag)] if lag >= 0 else programme[len(programme) + lag:]
        row["unmatched_programme_peak"] = float(np.max(np.abs(unmatched))) if unmatched.size else 0.0
        if row["unmatched_programme_peak"] > 1e-6:
            raise ValueError("programme contains unrelated audio outside the aligned interval")
        if row["programme_sum_error"] > RELATIVE_ERROR:
            raise ValueError("programme is not the clean linear owned-source mix (processing or unrelated music)")
        offsets.append(lag)
        measurements[scenario] = row
    if len(set(offsets)) != 1:
        raise ValueError("programme latency is not repeatable across source/mixer experiments")
    lag = offsets[0]
    return {"sample_rate": rate, "measurements": measurements, "evidence": evidence,
            "checks": dict.fromkeys(REQUIRED_CHECKS, True),
            "role_offsets_samples": {"contribution": max(0, -lag), "program": max(0, lag)}}


def _certificate_from_report(report):
    fixture = report["fixture"]
    if _hash(fixture["path"]) != fixture["sha256"]:
        raise ValueError("calibration fixture changed")
    measured = measure_experiments(report["takes"], report["owned_names"], fixture["path"])
    identities = [(take["song_ref"]["id"], take["runtime_identity"]["runtime_code_sha256"], take["runtime_identity"]["process_id"])
                  for take in report["takes"].values()]
    if len(set(identities)) != 1 or identities[0][0] != report["prior"]["song_ref"]["id"]:
        raise ValueError("Live set or runtime changed during experiment")
    first = report["takes"]["baseline"]
    context, settings = first.get("capture_context"), first.get("recorder_settings")
    if not context or not settings or any(take.get("capture_context") != context or take.get("recorder_settings") != settings for take in report["takes"].values()):
        raise ValueError("capture processing context or recorder settings unavailable/changed")
    profiles = []
    for take in report["takes"].values():
        for entry in take.get("source_contexts", []):
            profile = source_profile(entry)
            if profile not in profiles:
                profiles.append(profile)
    candidate = {"schema_version": 1, "origin": "computed_from_captured_audio", "song_id": identities[0][0],
        "runtime_code_sha256": identities[0][1], "process_id": identities[0][2], "code_hashes": code_hashes(),
        "capture_context": context, "recorder_settings": settings, "source_profiles": profiles,
        "routing_profile": first["routing_profile"], "routing_profile_sha256": first["routing_profile_sha256"],
        "capture_mode": first["mode"], "clock_origin": "experimentally_measured_native_recording_epoch",
        "native_source_kinds": sorted({entry["kind"] for take in report["takes"].values() for entry in take.get("source_contexts", [])}), **measured}
    for take in report["takes"].values():
        _check_certificate(candidate, take)
    return candidate


def calibrate_in_mix(bridge, args):
    """Create only owned fixture tracks; preserve user material and fail closed."""
    import numpy as np
    import soundfile as sf
    if set(args) - {"output_directory"}:
        raise ValueError("calibration accepts only output_directory")
    _require_runtime(bridge)
    plan = bridge.request("native_in_mix_plan", {"include_returns": True, "include_master": True})
    prior = plan["transport"]
    if prior["playing"]:
        raise ValueError("calibration requires stopped transport")
    # The capture plan already rejects recording, automation writes and solos.
    inspect = bridge.request("exec", {"code": _clip_scan_code() + "result = {'last_end': max([float(c.end_time) for c in clips] + [0.0]), 'master_devices': [d.name for d in song.master_track.devices], 'start_time': float(song.start_time)}"})
    if inspect["master_devices"]:
        raise ValueError("calibration requires an unprocessed Master path; existing devices are preserved")
    tempo = prior["tempo"]
    if not isinstance(tempo, (int, float)) or not math.isfinite(tempo) or not 20 <= tempo <= 999:
        raise ValueError("unsupported calibration tempo")
    end = inspect["last_end"]
    if not isinstance(end, (int, float)) or not math.isfinite(end) or not 0 <= end <= 1e7:
        raise ValueError("unsupported Arrangement extent")
    # Eight seconds of existing tail before the owned passage; audio residual tests
    # refuse long tails, live input and unrelated generators instead of muting them.
    start = end + 8 * tempo / 60
    root = Path(args.get("output_directory") or (state_dir() / "in_mix_calibration")).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    directory = root / token
    directory.mkdir()
    report_path = directory / "experiment.json"
    names = ["MCP InMix Calibration " + token + " " + letter for letter in ("A", "B")]
    report = {"ok": False, "qualified": False, "token": token, "owned_names": names,
              "owned_refs": [], "takes": {}, "prior": plan, "cleanup_complete": False}

    def persist():
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")

    healthy, created = True, False

    def call(method, params):
        nonlocal healthy
        try:
            return bridge.request(method, params)
        except Exception:
            healthy = False
            raise

    rate = 44100
    samples = np.zeros(12 * rate)
    t = np.arange(10 * rate) / rate
    noise = np.random.default_rng(int(token[:16], 16)).normal(0, 0.005, len(t))
    samples[rate:11 * rate] = 0.05 * np.sin(2 * np.pi * 997 * t) + noise
    samples[rate:rate + rate // 4] = noise[:rate // 4] * 5
    fixture = directory / "fixture.wav"
    sf.write(fixture, np.column_stack((samples, samples)), rate, subtype="FLOAT")
    report["fixture"] = {"path": str(fixture), "sha256": _hash(fixture), "seed": token[:16]}
    persist()
    try:
        # Store object identities before clip creation, including partial failures.
        # Cleanup uses this registry, never names or shifting track indexes.
        created = True
        for name in names:
            code = "\n".join([
                "this._audio_capture_guard()", "assert not song.is_playing",
                "registry = getattr(this, '_in_mix_calibration_owned', None)",
                "if registry is None: registry = this._in_mix_calibration_owned = {}",
                "owned = registry.setdefault(" + repr(token) + ", [])",
                "song.create_audio_track(-1)", "t = song.tracks[-1]", "owned.append(t)",
                "t.name = " + repr(name), "t.mute = False", "t.solo = False", "t.arm = False",
                "t.mixer_device.volume.value = 0.85", "t.mixer_device.panning.value = 0.0",
                "for send in t.mixer_device.sends: send.value = 0.0",
                "c = t.create_audio_clip(" + repr(str(fixture)) + ", " + repr(start) + ")",
                "c.warping = False", "c.looping = False",
                "assert t.mixer_device.volume.str_for_value(t.mixer_device.volume.value).startswith('0')",
                "result = this._audio_capture_ref(t)"])
            report["owned_refs"].append(call("exec", {"code": code}))
            persist()
        for scenario in SCENARIOS:
            latency_device = None
            if scenario == "latency":
                inserted = call("track_insert_device", {"ref": report["owned_refs"][0], "device_name": "Limiter"})
                if not inserted.get("inserted"):
                    raise ValueError("owned-source latency experiment could not insert native Limiter")
                latency_device = call("exec", {"code": "\n".join([
                    "t = this._in_mix_calibration_owned[" + repr(token) + "][0]",
                    "d = t.devices[-1]",
                    "result = {'class_name': d.class_name, 'name': d.name, 'latency_in_samples': getattr(d, 'latency_in_samples', None), 'parameters': [{'name': p.name, 'value': p.value, 'display': p.str_for_value(p.value)} for p in d.parameters]}"])})
                for parameter in latency_device["parameters"]:
                    if parameter["name"].lower() == "device on" and parameter["value"] <= 0:
                        raise ValueError("latency experiment Limiter is disabled")
                    if "lookahead" in parameter["name"].lower():
                        match = re.search(r"(\d+(?:\.\d+)?)\s*ms", parameter["display"], re.I)
                        if match:
                            latency_device["lookahead_ms"] = float(match.group(1))
                report["latency_device"] = latency_device
                persist()
            code = "\n".join([
                "this._audio_capture_guard()", "assert not song.is_playing",
                "t = this._in_mix_calibration_owned[" + repr(token) + "][0]",
                "t.mute = " + repr(scenario == "mute"),
                "t.mixer_device.panning.value = " + repr(1.0 if scenario == "pan_right" else 0.0),
                "t.mixer_device.volume.value = " + repr(0.0 if scenario == "volume_zero" else 0.85),
                "result = {'mute': t.mute, 'pan': t.mixer_device.panning.value, 'volume': t.mixer_device.volume.value}"])
            if scenario == "gain_minus_6":
                code = code.rsplit("result =", 1)[0] + "\n" + "\n".join([
                    "p = t.mixer_device.volume", "low, high = p.min, p.max",
                    "for unused in range(24):",
                    "    middle = (low + high) / 2.0",
                    "    db = float(p.str_for_value(middle).split()[0].replace(',', '.'))",
                    "    if db < -6.0: low = middle",
                    "    else: high = middle",
                    "lower_edge = (low + high) / 2.0", "low, high = p.min, p.max",
                    "for unused in range(24):",
                    "    middle = (low + high) / 2.0",
                    "    db = float(p.str_for_value(middle).split()[0].replace(',', '.'))",
                    "    if db <= -6.0: low = middle",
                    "    else: high = middle",
                    "p.value = (lower_edge + (low + high) / 2.0) / 2.0",
                    "result = {'gain_db': float(p.str_for_value(p.value).split()[0].replace(',', '.')), 'value': p.value}"])
            report.setdefault("mixer_actions", {})[scenario] = call("exec", {"code": code})
            take = capture_in_mix(bridge, {"start_beat": start, "length_beats": 14 * tempo / 60,
                "pre_roll_beats": 2 * tempo / 60, "include_returns": False, "include_master": True,
                "track_refs": report["owned_refs"], "max_duration_seconds": 300,
                "output_directory": str(directory)})
            report["takes"][scenario] = take
            if latency_device:
                take["latency_device"] = latency_device
            if scenario == "gain_minus_6":
                take["gain_db"] = report["mixer_actions"][scenario]["gain_db"]
            persist()
            if not take.get("ok"):
                healthy = False  # Includes unknown sent outcomes and recorder delivery failures.
                raise RuntimeError("calibration take failed; owned fixtures retained: " + scenario)
            if any(track.get("wav", {}).get("bits_per_sample") not in (24, 32, 64) for track in take["tracks"]):
                raise ValueError("physical qualification requires PCM24/32 or float32/64; PCM16 is unsupported")
        report["computed_certificate"] = _certificate_from_report(report)
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if created and healthy:
            try:
                _require_runtime(bridge)
                code = "\n".join([
                    "this._audio_capture_guard()", "assert not song.is_playing",
                    "owned = this._in_mix_calibration_owned.get(" + repr(token) + ", [])",
                    "for i in reversed(range(len(song.tracks))):",
                    "    if any(this._same_live_object(song.tracks[i], t) for t in owned): song.delete_track(i)",
                    "assert not any(this._same_live_object(t, o) for t in song.tracks for o in owned)",
                    "this._in_mix_calibration_owned.pop(" + repr(token) + ", None)",
                    "song.loop = " + repr(prior["loop"]),
                    "song.current_song_time = " + repr(prior["time"]),
                    "song.start_time = " + repr(inspect.get("start_time", prior["time"])),
                    "song.view.selected_track = this._resolve(" + repr(plan["selected_track"]) + ")",
                    "result = {'cleaned': True}"])
                call("exec", {"code": code})
                if plan.get("selected_device"):
                    call("exec", {"code": "song.view.select_device(this._resolve(" + repr(plan["selected_device"]) + "))\nresult = True"})
                report["cleanup_complete"] = True
            except Exception as exc:
                report["cleanup_error"] = str(exc)
        elif created:
            report["cleanup_blocked"] = "Unknown mutation outcome; retain registry token and owned identities for explicit recovery"
        persist()
    if report.get("computed_certificate") and report["cleanup_complete"] and not report.get("error"):
        try:
            report["computed_certificate"] = _calibrate_existing_targets(bridge, report["computed_certificate"], plan, directory, report, persist)
        except Exception as exc:
            report["error"] = str(exc)
            persist()
    if report.get("computed_certificate") and report["cleanup_complete"] and not report.get("error"):
        destination = certificate_path()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(token + ".tmp")
        try:
            temporary.write_text(json.dumps(report["computed_certificate"], indent=2, allow_nan=False), encoding="utf-8")
            temporary.replace(destination)
            report.update(ok=True, qualified=True, certificate_path=str(destination), certificate_sha256=_hash(destination))
        finally:
            temporary.unlink(missing_ok=True)
            persist()
    return {"ok": report["ok"], "qualified": report["qualified"], "experiment_path": str(report_path),
            **{key: report[key] for key in ("error", "cleanup_complete", "cleanup_error", "cleanup_blocked", "certificate_path", "certificate_sha256") if key in report}}


def revalidate_calibration_report(report_path):
    """Replay measured WAV experiments after offline-policy changes; never rehash declarations."""
    report_path = Path(report_path)
    if not 0 < report_path.stat().st_size <= 4 * 1024 * 1024:
        raise ValueError("calibration replay report exceeds bounds")
    raw = report_path.read_text(encoding="utf-8")
    report = json.loads(raw)
    if report.get("ok") is not True or report.get("cleanup_complete") is not True or set(report.get("takes", {})) != set(SCENARIOS):
        raise ValueError("replay requires the complete cleaned seven-take experiment")
    original = report.get("computed_certificate") or {}
    current = code_hashes()
    acquisition = {key: current[key] for key in ("capture", "remote_script", "live_settings")}
    if any(original.get("code_hashes", {}).get(key) != value for key, value in acquisition.items()):
        raise ValueError("acquisition code changed; fresh physical calibration required")
    for item in original.get("evidence", []):
        if _hash(item["path"]) != item["sha256"]:
            raise ValueError("original physical calibration evidence changed")
    candidate = _certificate_from_report(report)
    snapshot = report_path.with_name("qualification_replay_evidence_" + uuid.uuid4().hex + ".json")
    snapshot.write_text(raw, encoding="utf-8")
    candidate["replay"] = {"source_report": str(report_path.resolve()), "source_report_sha256": _hash(report_path),
                           "snapshot_path": str(snapshot.resolve()), "snapshot_sha256": _hash(snapshot),
                           "unchanged_acquisition_hashes": acquisition, "method": "all seven retained WAV experiments recomputed"}
    _check_certificate(candidate, report["takes"]["baseline"])
    return candidate


def _measure_target_offset(manifest, certificate, target_id):
    """Learn one target's actual processed signal; known contributions stay fixed."""
    import numpy as np
    import soundfile as sf
    from in_mix_qualification import _live_id, track_offset, verify_native_sum
    tracks = manifest["tracks"]
    infos = [validate_wav(track["path"]) for track in tracks]
    if (not 2 <= len(tracks) <= 16 or len({(info["sample_rate"], info["frames"]) for info in infos}) != 1
            or any(info["channels"] != 2 or info["frames"] * 2 > 4_000_000 for info in infos)
            or sum(info["frames"] * 2 for info in infos) > 32_000_000):
        raise ValueError("target timing experiment exceeds resource/layout bounds")
    selected = [track for track in tracks if track["role"] == "contribution" and _live_id(track["ref"]) == target_id]
    if len(selected) != 1:
        raise ValueError("target timing experiment does not contain exactly its original source")
    known = certificate.get("source_offsets_samples", {})
    other = [track for track in tracks if track is not selected[0]]
    length = infos[0]["frames"] - max(track_offset(track, certificate["role_offsets_samples"], known) for track in other)
    reference = np.zeros((length, 2)); known_abs = np.zeros_like(reference)
    program_abs = np.zeros_like(reference); recorded = None
    for track in tracks:
        data, _ = sf.read(track["path"], dtype="float64", always_2d=True)
        if not np.isfinite(data).all() or float(np.max(np.abs(data))) >= 0.95:
            raise ValueError("target capture is nonfinite or lacks recording headroom")
        if track is selected[0]:
            recorded = data
            continue
        if track["role"] == "contribution" and track.get("kind") in ("group", "return") and str(_live_id(track["ref"])) not in known:
            raise ValueError("target experiment includes another uncalibrated group/return")
        start = track_offset(track, certificate["role_offsets_samples"], known)
        data = data[start:start + length]
        if track["role"] == "program":
            reference += data; program_abs = np.abs(data)
        else:
            reference -= data; known_abs += np.abs(data)
    channel = int(np.argmax(np.sum(reference * reference, axis=0)))
    expected, observed = reference[:, channel], recorded[:, channel]
    rms = float(np.sqrt(np.mean(recorded ** 2)))
    if rms <= 1e-6 or float(np.sqrt(np.mean(expected ** 2))) <= 1e-6:
        raise ValueError("target is silent/gated; no physical offset can be measured")
    rate = infos[0]["sample_rate"]
    bound = min(rate // 4 - 1, length // 4)
    size = 1 << (len(expected) + len(observed) - 1).bit_length()
    correlation = np.fft.irfft(np.fft.rfft(observed, size) * np.conj(np.fft.rfft(expected, size)), size)
    lags = np.arange(-bound, bound + 1)
    rstart, ostart = np.maximum(0, -lags), np.maximum(0, lags)
    count = np.minimum(len(expected) - rstart, len(observed) - ostart)
    ep = np.concatenate(([0.0], np.cumsum(expected ** 2)))
    op = np.concatenate(([0.0], np.cumsum(observed ** 2)))
    denominator = np.sqrt((ep[rstart + count] - ep[rstart]) * (op[ostart + count] - op[ostart]))
    scores = np.divide(correlation[lags % size], denominator, out=np.zeros_like(denominator), where=denominator > 0)
    index = int(np.argmax(scores)); lag = int(lags[index])
    if lag < 0 or lag == bound or scores[index] < 0.999:
        raise ValueError("target processed signal has no bounded matching sample offset")
    quantum = sum(2.0 ** (1 - info["bits_per_sample"]) for info in infos if info["format"] == "pcm")

    def fits(candidate):
        ref, obs = _aligned(reference, recorded, candidate)
        start = max(0, -candidate)
        rounding = 4 * (len(tracks) - 1) * np.finfo(np.float32).eps * (known_abs[start:start + len(ref)] + np.abs(obs) + program_abs[start:start + len(ref)])
        return bool(np.all(np.abs(ref - obs) <= quantum + rounding + 1e-12))

    if not fits(lag):
        raise ValueError("target admission failed fixed-offset full-stereo quantum sum")
    alternatives = lags[(scores >= scores[index] - 1e-4) & (lags != lag)]
    if any(fits(int(candidate)) for candidate in alternatives):
        raise ValueError("target waveform is periodic/ambiguous at sample precision")
    corrected = {**known, str(target_id): lag}
    measured = verify_native_sum(manifest, certificate["role_offsets_samples"], corrected)
    return {"offset_samples": lag, "rms": rms, "signature_correlation": float(scores[index]), "unique_lag": True,
            "channel": channel, "search_bound_samples": bound, "waveform": measured,
            "inference": "processed target versus programme minus already-calibrated fixed-offset contributions"}


def qualify_target_epochs(certificate, target_ref, kind, takes, directory):
    """Offline admission of two actual target epochs; returns a candidate, never publishes."""
    from in_mix_qualification import _live_id
    if kind not in ("group", "return") or len(takes) != 2 or len({take["take_id"] for take in takes}) != 2:
        raise ValueError("target admission requires two distinct group/return recording epochs")
    target_id = _live_id(target_ref)
    candidate = json.loads(json.dumps(certificate, allow_nan=False)); epochs = []
    for take in takes:
        if take.get("ok") is not True or take.get("complete") is not True or take.get("cleanup_complete") is not True:
            raise ValueError("target capture or cleanup is incomplete")
        measured = _measure_target_offset(take, candidate, target_id)
        if epochs and measured["offset_samples"] != epochs[0]["offset_samples"]:
            raise ValueError("target offsets disagree between independent epochs")
        snapshot = Path(directory) / ("target_epoch_" + uuid.uuid4().hex + ".json")
        snapshot.write_text(json.dumps(take, indent=2, allow_nan=False), encoding="utf-8")
        epochs.append({"take_id": take["take_id"], "manifest_path": str(snapshot.resolve()), "manifest_sha256": _hash(snapshot), **measured})
        for track in take["tracks"]:
            item = {"path": track["path"], "sha256": _hash(track["path"])}
            if item not in candidate["evidence"]:
                candidate["evidence"].append(item)
    candidate.setdefault("source_offsets_samples", {})[str(target_id)] = epochs[0]["offset_samples"]
    candidate.setdefault("target_offset_evidence", {})[str(target_id)] = {"kind": kind, "profile_sha256": candidate["routing_profile_sha256"], "epochs": epochs}
    candidate["native_source_kinds"] = sorted(set(candidate["native_source_kinds"]) | {kind})
    for take in takes:
        _check_certificate(candidate, take)
    return candidate


def _calibrate_existing_targets(bridge, certificate, original_plan, directory, report, persist):
    """Acquire original Returns first, then Groups, without changing their processors."""
    import numpy as np
    import soundfile as sf
    from in_mix_capture import read_routing_profile
    from in_mix_qualification import _live_id
    targets = [track for track in original_plan["tracks"] if track.get("kind") in ("return", "group")]
    targets.sort(key=lambda track: track["kind"] != "return")
    candidate = certificate
    rate = certificate["sample_rate"]
    report["target_calibrations"] = []
    for target in targets:
        token = uuid.uuid4().hex
        folder = Path(directory) / ("target_" + token)
        folder.mkdir()
        state = {"target_ref": target["ref"], "kind": target["kind"], "owned_token": token,
                 "generator_ref": None, "manifest_paths": [], "complete": False, "cleanup_complete": False}
        report["target_calibrations"].append(state); persist()
        healthy, created, takes = True, False, []

        def call(method, params):
            nonlocal healthy
            try:
                return bridge.request(method, params)
            except Exception:
                healthy = False
                raise

        try:
            _require_runtime(bridge)
            before = read_routing_profile(bridge, request=call)
            if before["sha256"] != candidate["routing_profile_sha256"]:
                raise ValueError("original routing/latency profile changed before target calibration")
            original_ids = [_live_id(item["ref"]) for item in before["profile"]["tracks"]]
            placement = call("exec", {"code": _clip_scan_code(original_ids) + "result = {'last_end': max([float(c.end_time) for c in clips] + [0.0]), 'tempo': float(song.tempo), 'start_time': float(song.start_time), 'position': float(song.current_song_time)}"})
            tempo, end = placement["tempo"], placement["last_end"]
            if not math.isfinite(tempo) or not 20 <= tempo <= 999 or not math.isfinite(end) or not 0 <= end <= 1e7:
                raise ValueError("unsupported target calibration passage")
            start = end + 8 * tempo / 60
            samples = np.zeros(12 * rate)
            samples[rate:11 * rate] = np.random.default_rng(int(token[:16], 16)).normal(0, 0.025, 10 * rate)
            # Short fades keep the owned test signal clean; timing is measured on
            # the processed target, not assumed from the generator's first sample.
            ramp = max(1, rate // 100)
            samples[rate:rate + ramp] *= np.linspace(0, 1, ramp)
            samples[11 * rate - ramp:11 * rate] *= np.linspace(1, 0, ramp)
            fixture = folder / "noise.wav"
            sf.write(fixture, np.column_stack((samples, samples)), rate, subtype="FLOAT")
            state["fixture"] = {"path": str(fixture), "sha256": _hash(fixture), "sample_rate": rate}
            persist()
            code = ["this._audio_capture_guard()", "assert not song.is_playing",
                    "target = this._resolve(" + repr(target["ref"]) + ")",
                    "registry = getattr(this, '_in_mix_offset_owned', None)",
                    "if registry is None: registry = this._in_mix_offset_owned = {}",
                    "owned = registry.setdefault(" + repr(token) + ", [])",
                    "before_ids = [this._object_id(t) for t in song.tracks]"]
            index = "list(song.tracks).index(target) + 1" if target["kind"] == "group" else "-1"
            code += ["t = song.create_audio_track(" + index + ")",
                     "if t is None: t = next(t for t in song.tracks if this._object_id(t) not in before_ids)",
                     "owned.append(t)", "t.name = " + repr("MCP Offset " + token),
                     "assert not t.devices, 'Owned offset generator must have no DSP devices'",
                     "t.arm = False", "t.current_monitoring_state = 2", "t.mute = False", "t.solo = False",
                     "t.mixer_device.volume.value = 0.85", "t.mixer_device.panning.value = 0.0",
                     "for send in t.mixer_device.sends: send.value = send.min"]
            if target["kind"] == "group":
                code += ["assert this._same_live_object(t.group_track, target), 'Owned child is not inside the target group'",
                         "route_name = target.name"]
            else:
                code += ["route_name = 'Sends Only'",
                         "send_index = next(i for i, r in enumerate(song.return_tracks) if this._same_live_object(r, target))",
                         "t.mixer_device.sends[send_index].value = t.mixer_device.sends[send_index].max"]
            code += ["routes = [r for r in t.available_output_routing_types if r.display_name == route_name]",
                     "assert len(routes) == 1, 'Owned generator output route unavailable/ambiguous'",
                     "t.output_routing_type = routes[0]", "assert t.output_routing_type.display_name == route_name",
                     "c = t.create_audio_clip(" + repr(str(fixture)) + ", " + repr(start) + ")",
                     "c.warping = False", "c.looping = False",
                     "result = {'ref': this._audio_capture_ref(t), 'devices_empty': not bool(t.devices), 'warping': c.warping, 'output': t.output_routing_type.display_name, 'sends': [p.value for p in t.mixer_device.sends]}"]
            created = True
            state["generator"] = call("exec", {"code": "\n".join(code)})
            state["generator_ref"] = state["generator"]["ref"]; persist()
            if read_routing_profile(bridge, request=call)["sha256"] != before["sha256"]:
                raise ValueError("owned generator admission altered the original routing/latency profile")
            return_refs = ([target["ref"]] if target["kind"] == "return" else
                           [track["ref"] for track in targets if track["kind"] == "return"])
            for epoch in range(2):
                take = capture_in_mix(bridge, {"start_beat": start, "length_beats": 14 * tempo / 60,
                    "pre_roll_beats": 2 * tempo / 60, "track_refs": [target["ref"]] if target["kind"] == "group" else [],
                    "include_returns": True, "return_refs": return_refs, "include_master": True,
                    "max_duration_seconds": 300, "output_directory": str(folder)})
                state["manifest_paths"].append(take.get("manifest_path")); persist()
                if take.get("ok") is not True:
                    healthy = bool(take.get("cleanup_complete") and not take.get("cleanup_error") and not take.get("cleanup_blocked"))
                    raise RuntimeError("target capture unsupported/incomplete: " + str(take.get("error")))
                takes.append(take)
            candidate = qualify_target_epochs(candidate, target["ref"], target["kind"], takes, folder)
            state["offset_samples"] = candidate["source_offsets_samples"][str(_live_id(target["ref"]))]
            state["complete"] = True
        except Exception as exc:
            state["error"] = str(exc)
            raise
        finally:
            if created and healthy:
                try:
                    _require_runtime(bridge)
                    call("exec", {"code": "\n".join([
                        "this._audio_capture_guard()", "assert not song.is_playing",
                        "owned = this._in_mix_offset_owned.get(" + repr(token) + ", [])",
                        "for i in reversed(range(len(song.tracks))):",
                        "    if any(this._same_live_object(song.tracks[i], t) for t in owned): song.delete_track(i)",
                        "assert not any(this._same_live_object(t, o) for t in song.tracks for o in owned)",
                        "this._in_mix_offset_owned.pop(" + repr(token) + ", None)",
                        "song.current_song_time = " + repr(placement["position"]),
                        "song.start_time = " + repr(placement["start_time"]),
                        "song.view.selected_track = this._resolve(" + repr(original_plan["selected_track"]) + ")",
                        "result = True"])})
                    if original_plan.get("selected_device"):
                        call("exec", {"code": "song.view.select_device(this._resolve(" + repr(original_plan["selected_device"]) + "))\nresult = True"})
                    if read_routing_profile(bridge, request=call)["sha256"] != before["sha256"]:
                        raise ValueError("original routing/latency profile not restored after owned child removal")
                    state["cleanup_complete"] = True
                except Exception as exc:
                    state["cleanup_error"] = str(exc)
            elif created:
                state["cleanup_blocked"] = "Unknown Live mutation outcome; exact owned generator retained for explicit recovery"
            if created and not state["cleanup_complete"]:
                report["cleanup_complete"] = False
            persist()
        if not state["cleanup_complete"]:
            raise RuntimeError("target generator cleanup/profile restoration incomplete")
    # With owned children removed, verify the actual complete original passage at
    # fixed offsets. Silent/absent original music is explicitly unmeasured here.
    eligible_ids = _eligible_audio_partition_ids(original_plan, candidate["routing_profile"])
    passage = bridge.request("exec", {"code": _clip_scan_code(eligible_ids) + "result = {'starts': [float(c.start_time) for c in clips], 'tempo': float(song.tempo), 'start_time': float(song.start_time), 'position': float(song.current_song_time)}"})
    if passage["starts"]:
        final = capture_in_mix(bridge, {"start_beat": min(passage["starts"]), "length_beats": 14 * passage["tempo"] / 60,
            "track_refs": [track["ref"] for track in original_plan["tracks"] if track["kind"] in ("track", "group")],
            "include_returns": True, "return_refs": [track["ref"] for track in targets if track["kind"] == "return"],
            "include_master": True, "max_duration_seconds": 300, "output_directory": str(directory)})
        report["final_admission"] = {"manifest_path": final.get("manifest_path"), "ok": final.get("ok")}
        if final.get("ok") is not True:
            if not final.get("cleanup_complete") or final.get("cleanup_error") or final.get("cleanup_blocked"):
                report["cleanup_complete"] = False
            raise RuntimeError("original-set final admission capture failed")
        try:
            _check_certificate(candidate, final)
            report["final_admission"]["fixed_sum_verified"] = True
        except ValueError as exc:
            if str(exc) != "native programme is silent; current-take timing is unmeasured":
                raise
            report["final_admission"]["original_programme"] = "unmeasured_silent_passage"
        finally:
            try:
                bridge.request("exec", {"code": "song.current_song_time = " + repr(passage["position"]) + "\nsong.start_time = " + repr(passage["start_time"]) + "\nresult = True"})
            except Exception as exc:
                report["cleanup_complete"] = False
                report["cleanup_error"] = "final admission state restoration failed: " + str(exc)
                persist()
                raise
    else:
        report["final_admission"] = {"original_programme": "unavailable_no_arrangement_clips",
            "basis": "two isolated processed-target epochs and restored original profile; every future capture still requires nonzero fixed-offset sum"}
    persist()
    return candidate


def _eligible_audio_partition_ids(plan, profile):
    """Choose actual terminal audio and real routed group descendants, not any MIDI clip."""
    from audio_assessment import _verify_partition_exclusions
    ids = {track["ref"]["id"] for track in plan["tracks"] if track.get("kind") in ("track", "group")}
    excluded = {entry["ref"]["id"]: entry for entry in plan.get("unsupported_tracks", [])}
    for track in profile.get("tracks", []):
        identity = track["ref"]["id"]
        if track.get("has_audio_output") is not True:
            ids.discard(identity)
            continue
        if identity in ids or identity not in excluded:
            continue
        try:
            _verify_partition_exclusions({"tracks": plan["tracks"], "requested": {}, "routing_profile": profile,
                                          "unsupported_tracks": [excluded[identity]]})
        except ValueError:
            continue
        ids.add(identity)
    return sorted(ids)
