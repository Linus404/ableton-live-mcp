import copy
import json

import numpy as np
import pytest
import soundfile as sf
from types import SimpleNamespace

import in_mix_calibration as calibration
import in_mix_qualification as qualification


def recorded_experiments(tmp_path, programme_delay=37):
    """Real finalized WAVs: one interleaved clock and exact channel copies."""
    rate = 8000
    n = 12 * rate
    rng = np.random.default_rng(73)
    signal = np.zeros(n)
    time = np.arange(9 * rate) / rate
    signal[rate:10 * rate] = 0.03 * np.sin(2 * np.pi * 997 * time) + rng.normal(0, 0.007, len(time))
    names = ["owned A", "owned B"]
    takes = {}
    for index, scenario in enumerate(calibration.SCENARIOS):
        folder = tmp_path / scenario
        folder.mkdir()
        b = np.column_stack((signal, signal))
        # Different recording starts, not different musical sample alignment.
        b = np.roll(b, index * 41, axis=0)
        a = b.copy()
        if scenario in ("mute", "volume_zero"):
            a[:] = 0
        elif scenario == "gain_minus_6":
            a *= 10 ** (-6 / 20)
        elif scenario == "pan_right":
            a[:, 0] = 0
        programme = np.roll(a + b, programme_delay, axis=0)
        interleaved = np.column_stack((a, b, programme)).astype("float32")
        path = folder / "interleaved.wav"
        sf.write(path, interleaved, rate, subtype="FLOAT")
        entries = []
        for channel, name in enumerate(names + ["Master"]):
            stereo_path = folder / (str(channel) + ".wav")
            sf.write(stereo_path, interleaved[:, 2 * channel:2 * channel + 2], rate, subtype="FLOAT")
            entries.append({"name": name, "role": "program" if channel == 2 else "contribution", "path": str(stereo_path)})
        takes[scenario] = {"complete": True, "cleanup_complete": True, "tracks": entries,
                           "mode": "in_mix_multichannel", "shared_sample_clock": True,
                           "interleaved_path": str(path), "song_ref": {"id": 1},
                           "runtime_identity": {"runtime_code_sha256": "current-runtime"},
                           "capture_context": {"master": {"devices": []}, "global_delay_compensation": True,
                                               "reduced_latency_when_monitoring": False},
                           "recorder_settings": {"sample_rate": rate, "signal_vector": 64, "io_vector": 64}}
        takes[scenario]["source_contexts"] = [{"kind": "track", "role": "contribution", "context": {
            "output_type": "Main", "output_channel": "1/2", "delay_in_ms": 0, "track_delay": None, "devices": []}}] * 2
        if scenario == "gain_minus_6":
            takes[scenario]["gain_db"] = -6
        if scenario == "latency":
            takes[scenario]["latency_device"] = {"class_name": "Limiter", "latency_in_samples": 24,
                "parameters": [{"name": "Device On", "value": 1}]}
    return takes, names


@pytest.mark.parametrize("delay", [37, -53, 0])
def test_real_wavs_prove_gain_pan_mute_clock_and_measured_offsets(tmp_path, delay):
    takes, names = recorded_experiments(tmp_path, delay)
    proof = calibration.measure_experiments(takes, names)
    assert proof["checks"] == dict.fromkeys(qualification.REQUIRED_CHECKS, True)
    assert proof["role_offsets_samples"] == {"contribution": max(0, -delay), "program": max(0, delay)}
    assert len(proof["evidence"]) == 7
    assert proof["measurements"]["repeat"]["source_b_repeat_offset_samples"] == 41
    assert proof["measurements"]["baseline"]["programme_sum_error"] < 1e-6


def rewrite_take(take, transform):
    data, rate = sf.read(take["interleaved_path"], dtype="float32", always_2d=True)
    transform(data)
    sf.write(take["interleaved_path"], data, rate, subtype="FLOAT")
    for index, entry in enumerate(take["tracks"]):
        sf.write(entry["path"], data[:, 2 * index:2 * index + 2], rate, subtype="FLOAT")


@pytest.mark.parametrize("scenario,change,reason", [
    ("volume_zero", lambda d: d.__setitem__((slice(None), slice(0, 2)), d[:, 2:4]), "did not silence"),
    ("mute", lambda d: d.__setitem__((slice(None), slice(0, 2)), d[:, 2:4] * 0.1), "did not silence"),
    ("pan_right", lambda d: d.__setitem__((slice(None), 0), d[:, 2]), "hard-right pan"),
    ("repeat", lambda d: d.__setitem__((slice(None), slice(2, 4)), d[:, 2:4] * 0.9), "source B changed"),
    ("baseline", lambda d: d.__setitem__((slice(None), slice(4, 6)), d[:, 4:6] * 0.8), "clean linear"),
    ("baseline", lambda d: d.__setitem__((slice(None), slice(0, 2)), np.roll(d[:, 0:2], 1, axis=0)), "zero-offset"),
    ("gain_minus_6", lambda d: d.__setitem__((slice(None), slice(0, 2)), d[:, 2:4]), "finite Post Mixer"),
])
def test_numeric_failures_cannot_be_qualified(tmp_path, scenario, change, reason):
    takes, names = recorded_experiments(tmp_path)
    rewrite_take(takes[scenario], change)
    with pytest.raises(ValueError, match=reason):
        calibration.measure_experiments(takes, names)


def test_pan_endpoint_measured_native_floor_is_retained_without_silence_claim(tmp_path):
    takes, names = recorded_experiments(tmp_path)

    def native_floor(data):
        data[:, 0] = data[:, 2] * 1.0039399066e-5
        data[:, 1] = data[:, 3] * np.sqrt(2)
        data[:, 4:6] = np.roll(data[:, 0:2] + data[:, 2:4], 37, axis=0)

    rewrite_take(takes["pan_right"], native_floor)
    measured = calibration.measure_experiments(takes, names)["measurements"]["pan_right"]
    assert 1e-5 < measured["pan_left_rms_ratio"] < 2e-5
    assert measured["pan_right_rms_ratio"] == pytest.approx(np.sqrt(2), rel=1e-6)
    rewrite_take(takes["pan_right"], lambda data: data.__setitem__((slice(None), 0), data[:, 2] * 3e-5))
    with pytest.raises(ValueError, match="hard-right pan"):
        calibration.measure_experiments(takes, names)


def test_latency_must_repeat_and_shared_clock_must_be_real(tmp_path):
    takes, names = recorded_experiments(tmp_path)
    rewrite_take(takes["pan_right"], lambda d: d.__setitem__((slice(None), slice(4, 6)), np.roll(d[:, 4:6], 1, axis=0)))
    with pytest.raises(ValueError, match="latency is not repeatable"):
        calibration.measure_experiments(takes, names)


def test_latency_device_and_unique_fixture_signature_are_required(tmp_path):
    takes, names = recorded_experiments(tmp_path)
    fixture = tmp_path / "fixture.wav"
    data, rate = sf.read(takes["baseline"]["tracks"][1]["path"], always_2d=True)
    sf.write(fixture, data, rate, subtype="FLOAT")
    proof = calibration.measure_experiments(takes, names, fixture)
    assert proof["measurements"]["baseline"]["fixture_signature_correlation"] > 0.999
    data[rate:rate + rate // 4] = np.random.default_rng(999).normal(0, 0.03, (rate // 4, 2))
    sf.write(fixture, data, rate, subtype="FLOAT")
    with pytest.raises(ValueError, match="unique owned fixture"):
        calibration.measure_experiments(takes, names, fixture)
    takes["latency"].pop("latency_device")
    with pytest.raises(ValueError, match="latency-bearing"):
        calibration.measure_experiments(takes, names)
    take = takes["baseline"]
    path = take["tracks"][0]["path"]
    data, rate = sf.read(path, always_2d=True)
    data[0, 0] = 0.01
    sf.write(path, data, rate, subtype="FLOAT")
    with pytest.raises(ValueError, match="differs from shared-clock"):
        calibration.measure_experiments(takes, names)


def test_certificate_binding_missing_changed_and_stale_evidence(tmp_path, monkeypatch):
    takes, names = native_experiments(tmp_path)
    proof = calibration.measure_experiments(takes, names, tmp_path / "native-fixture.wav")
    hashes = {"capture": "original", "recorder": "original", "remote_script": "original"}
    monkeypatch.setattr(qualification, "code_hashes", lambda: hashes)
    path = tmp_path / "qualification.json"
    monkeypatch.setattr(qualification, "certificate_path", lambda: path)
    certificate = {"schema_version": 1, "origin": "computed_from_captured_audio", "song_id": 1,
                   "capture_mode": "in_mix_native_arrangement", "clock_origin": "experimentally_measured_native_recording_epoch",
                   "native_source_kinds": ["track"], "process_id": 42,
                   "runtime_code_sha256": "current-runtime", "code_hashes": dict(hashes),
                   "capture_context": takes["baseline"]["capture_context"],
                   "recorder_settings": takes["baseline"]["recorder_settings"],
                   "routing_profile": takes["baseline"]["routing_profile"], "routing_profile_sha256": takes["baseline"]["routing_profile_sha256"],
                   "source_profiles": [qualification.source_profile(takes["baseline"]["source_contexts"][0])], **proof}
    path.write_text(json.dumps(certificate), encoding="utf-8")
    manifest = copy.deepcopy(takes["baseline"])
    attached = qualification.attach_qualification(manifest)
    assert attached["qualification"]["verified"]
    assert attached["shared_sample_clock"] and attached["native_clock"]["acquisition_epoch_verified"]
    assert attached["native_acquisition"]["frame_zero_mapping_verified"]
    assert not manifest["native_clock"]["acquisition_epoch_verified"]
    assert not manifest["native_acquisition"]["frame_zero_mapping_verified"]
    assert qualification.verify_qualification(attached)["kind"] == "live_experimental"
    hashes["recorder"] = "changed"
    assert "stale" in qualification.attach_qualification(manifest)["qualification"]["reason"]
    hashes["recorder"] = "original"
    for key, value in [("capture_context", {"global_delay_compensation": False}),
                       ("recorder_settings", {"sample_rate": 8000, "signal_vector": 128, "io_vector": 64})]:
        changed = copy.deepcopy(manifest)
        changed[key] = value
        assert qualification.attach_qualification(changed)["qualification"]["verified"] is False
    for kind, devices, delay in [("group", [], 0), ("return", [], 0), ("track", [], 5)]:
        changed = copy.deepcopy(manifest)
        changed["source_contexts"][0]["kind"] = kind
        changed["source_contexts"][0]["context"]["devices"] = devices
        changed["source_contexts"][0]["context"]["delay_in_ms"] = delay
        assert qualification.attach_qualification(changed)["qualification"]["verified"] is False
    for bad_offsets in [None, {"contribution": True, "program": 37}, {"contribution": 0, "program": -1},
                        {"contribution": 4, "program": 41}, {"contribution": 0, "program": 2000}]:
        malformed = copy.deepcopy(certificate)
        malformed["role_offsets_samples"] = bad_offsets
        with pytest.raises(ValueError, match="offsets"):
            qualification._check_certificate(malformed, manifest)
    malformed = copy.deepcopy(certificate)
    malformed["evidence"][1] = malformed["evidence"][0]
    with pytest.raises(ValueError, match="repeats"):
        qualification._check_certificate(malformed, manifest)
    malformed = copy.deepcopy(certificate)
    malformed["measurements"]["baseline"]["source_b_rms"] = float("nan")
    with pytest.raises(ValueError):
        qualification._check_certificate(malformed, manifest)
    changed = copy.deepcopy(manifest)
    changed["runtime_identity"]["runtime_code_sha256"] = "stale-runtime"
    assert "fingerprint" in qualification.attach_qualification(changed)["qualification"]["reason"]
    evidence_path = proof["evidence"][0]["path"]
    original = open(evidence_path, "rb").read()
    with open(evidence_path, "ab") as handle:
        handle.write(b"changed")
    assert "evidence changed" in qualification.attach_qualification(manifest)["qualification"]["reason"]
    with open(evidence_path, "wb") as handle:
        handle.write(original)
    path.unlink()
    assert qualification.attach_qualification(manifest)["qualification"]["verified"] is False
    path.write_text("x" * (256 * 1024 + 1), encoding="utf-8")
    stale_proof = copy.deepcopy(attached)
    refused = qualification.attach_qualification(stale_proof)
    assert not refused["qualification"]["verified"] and not refused["alignment"]["verified"]
    assert not refused["sample_aligned"] and not refused["provenance"]["in_mix_levels"]
    assert not refused["shared_sample_clock"] and not refused["native_clock"]["acquisition_epoch_verified"]
    assert not refused["native_acquisition"]["frame_zero_mapping_verified"]


def test_normalized_capture_is_measured_and_raw_repair_evidence_retained(tmp_path):
    takes, names = recorded_experiments(tmp_path)
    for take in takes.values():
        normalized = take["interleaved_path"]
        raw = normalized + ".raw.wav"
        # Deliberately invalid raw RIFF proves numerical checks use finalized copy.
        with open(raw, "wb") as handle:
            handle.write(b"raw native recording with documented header defect")
        take["interleaved_path"] = raw
        take["normalized_interleaved_path"] = normalized
        take["normalization"] = {"normalized_path": normalized, "raw_path": raw}
    proof = calibration.measure_experiments(takes, names)
    assert len(proof["evidence"]) == 14


def native_experiments(tmp_path):
    takes, names = recorded_experiments(tmp_path)
    profile = {"schema_version": 1, "critical_unknown_fields": [], "unknown_fields": ["reported_latency_null_not_zero"], "tracks": [
        {"ref": {"id": 300}, "kind": "return", "name": "Original Return", "has_audio_output": True, "output_type": "Main", "devices": [], "sends": []},
        {"ref": {"id": 400}, "kind": "group", "name": "Original Group", "has_audio_output": True, "output_type": "Main", "devices": [], "sends": []},
        {"ref": {"id": 3}, "kind": "master", "name": "Main", "has_audio_output": True, "output_type": "Ext. Out", "devices": [], "sends": []},
        {"ref": {"id": 9000}, "kind": "track", "name": "Empty MIDI", "has_audio_output": False, "output_type": "Main", "devices": [], "sends": []}]}
    digest = qualification.routing_profile_hash(profile)
    for take_index, (scenario, take) in enumerate(takes.items()):
        blocks = []
        for index, track in enumerate(take["tracks"]):
            data, rate = sf.read(track["path"], dtype="float64", always_2d=True)
            data = np.roll(data, -take_index * 41, axis=0)
            sf.write(track["path"], data, rate, subtype="PCM_32")
            data, _ = sf.read(track["path"], dtype="float64", always_2d=True)
            blocks.append(data)
            track.update(kind="master" if track["role"] == "program" else "track",
                         native_sha256=qualification._hash(track["path"]), ref={"id": index + 1}, receiver_ref={"id": index + 100},
                         native_clip={"sample_rate": rate, "sample_length": len(data), "is_recording": False,
                                      "warping": True, "start_time": 0, "end_time": 24})
        sf.write(take["interleaved_path"], np.concatenate(blocks, axis=1), rate, subtype="DOUBLE")
        take.update(ok=True, mode="in_mix_native_arrangement", take_id=scenario, capture_engine="live_native_arrangement",
                    shared_sample_clock=False,
                    derivative_clock="constructed_from_native", interleaved_is_reconstructed=True, live_settings_stable=True,
                    native_clock={"engine": "Ableton Live", "simultaneous_record_command": True, "originals_disarmed": True,
                                  "acquisition_epoch_verified": False},
                    native_acquisition={"epoch_id": scenario, "receivers_monitor_off": True,
                                        "frame_zero_mapping_verified": False,
                                        "recording_start": {"begun": True, "token": scenario},
                                        "recording_stop": {"stopped": True, "token": scenario}},
                    recorder_settings={"sample_rate": rate, "acquisition": "native Arrangement recording", "monitoring": "off"})
        take["requested"] = {"start_beat": 0, "pre_roll_beats": 0, "length_beats": 24}
        take["prior_transport"] = {"tempo": 120}
        take["runtime_identity"]["process_id"] = 42
        take["capture_context"]["master"].update(mute=False, panning=0, volume=0.85)
        take["live_settings_observations"] = [{"phase": phase, "delay_compensation": True,
                                               "reduced_latency_when_monitoring": False,
                                               "evidence": {"pid": 42, "source": "windows_native_options_menu", "method_version": 1}}
                                              for phase in ("planning", "after_stop")]
        take["owned_receivers"] = [{"receiver_ref": track["receiver_ref"], "source_ref": track["ref"],
                                     "input_type": "Resampling" if track["role"] == "program" else track["name"],
                                     "input_channel": "Post Mixer", "output_type": "Sends Only"} for track in take["tracks"]]
        take["native_recordings"] = [{**item, "current_monitoring_state": 2, "sends_zero": True, "devices_empty": True}
                                     for item in take["owned_receivers"]]
        take["interleaved_wav"] = {"sample_rate": rate}
        take.update(routing_profile=profile, routing_profile_sha256=digest, routing_profile_stable=True,
                    routing_profile_observations=[{"phase": phase, "profile": profile, "sha256": digest} for phase in ("before", "end")])
    fixture = tmp_path / "native-fixture.wav"
    data, rate = sf.read(takes["baseline"]["tracks"][1]["path"], dtype="float64", always_2d=True)
    sf.write(fixture, data, rate, subtype="DOUBLE")
    return takes, names


def test_native_current_sum_fixed_offsets_preserves_pcm32_and_rejects_missing_audio(tmp_path):
    takes, names = native_experiments(tmp_path)
    proof = calibration.measure_experiments(takes, names, tmp_path / "native-fixture.wav")
    take = takes["baseline"]
    offsets = proof["role_offsets_samples"]
    observed = qualification.verify_native_sum(take, offsets)
    assert observed["frames_checked"] == 12 * 8000 - 37
    assert observed["relative_residual"] < 1e-6
    with pytest.raises(ValueError, match="fixed-offset sum"):
        qualification.verify_native_sum(take, {"contribution": 0, "program": 38})
    wrong = copy.deepcopy(take)
    wrong["tracks"] = wrong["tracks"][1:]
    with pytest.raises(ValueError):
        qualification.verify_native_sum(wrong, offsets)
    data, rate = sf.read(take["tracks"][0]["path"], dtype="float64", always_2d=True)
    data[12345, 0] += 2 ** -31
    sf.write(take["tracks"][0]["path"], data, rate, subtype="PCM_32")
    with pytest.raises(ValueError, match="copy changed"):
        qualification.verify_native_sum(take, offsets)


def test_native_live_ref_identity_ignores_optional_paths_and_rejects_alias_duplicates(tmp_path):
    takes, names = native_experiments(tmp_path)
    take = takes["baseline"]
    offsets = {"contribution": 0, "program": 37}
    for index, track in enumerate(take["tracks"]):
        track["ref"] = {**track["ref"], "path": "live_set tracks %d" % index}
        track["receiver_ref"] = {**track["receiver_ref"], "path": "live_set tracks %d" % (index + 20)}
    # Readbacks intentionally retain id-only refs, like the actual Live bridge.
    assert qualification.verify_native_sum(take, offsets)["frames_checked"] > 0
    duplicate = copy.deepcopy(take)
    duplicate["tracks"][1]["ref"] = {"id": duplicate["tracks"][0]["ref"]["id"], "path": "different alias"}
    with pytest.raises(ValueError, match="source identity.*duplicated"):
        qualification.verify_native_sum(duplicate, offsets)
    invalid = copy.deepcopy(take)
    invalid["tracks"][0]["ref"]["id"] = True
    with pytest.raises(ValueError, match="positive Live object ID"):
        qualification.verify_native_sum(invalid, offsets)


def test_native_qualification_uses_measured_roles_and_current_signal_not_upstream_whitelist(tmp_path, monkeypatch):
    takes, names = native_experiments(tmp_path)
    proof = calibration.measure_experiments(takes, names, tmp_path / "native-fixture.wav")
    take = takes["baseline"]
    hashes = {"native": "current"}
    monkeypatch.setattr(qualification, "code_hashes", lambda: hashes)
    certificate = {"schema_version": 1, "origin": "computed_from_captured_audio", "song_id": 1,
                   "capture_mode": take["mode"], "clock_origin": "experimentally_measured_native_recording_epoch",
                   "process_id": 42, "runtime_code_sha256": "current-runtime", "code_hashes": hashes,
                   "capture_context": take["capture_context"], "recorder_settings": take["recorder_settings"],
                   "source_profiles": [qualification.source_profile(take["source_contexts"][0])],
                   "routing_profile": take["routing_profile"], "routing_profile_sha256": take["routing_profile_sha256"],
                   "native_source_kinds": ["track"], **proof}
    qualification._check_certificate(certificate, take)
    # Real Master tracks expose no mute property; null stays a diagnostic, while
    # the nonzero programme and exact current-take sum prove an active signal path.
    null_master = copy.deepcopy(take)
    null_master["capture_context"]["master"]["mute"] = None
    null_certificate = copy.deepcopy(certificate)
    null_certificate["capture_context"]["master"]["mute"] = None
    qualification._check_certificate(null_certificate, null_master)
    assert null_master["capture_context"]["master"]["mute"] is None
    muted_master = copy.deepcopy(null_master)
    muted_master["capture_context"]["master"]["mute"] = True
    muted_certificate = copy.deepcopy(null_certificate)
    muted_certificate["capture_context"]["master"]["mute"] = True
    with pytest.raises(ValueError, match="unmuted Master"):
        qualification._check_certificate(muted_certificate, muted_master)
    arbitrary = copy.deepcopy(take)
    arbitrary["source_contexts"][0]["context"]["devices"] = [{"class_name": "Sampler"}, {"class_name": "Compressor"}]
    arbitrary["source_contexts"][0]["context"]["delay_in_ms"] = None
    arbitrary["source_contexts"][0]["context"]["track_delay"] = None
    qualification._check_certificate(certificate, arbitrary)
    for change in ("wrong_pid", "unknown_pdc", "unmeasured_group", "epoch_mismatch"):
        invalid = copy.deepcopy(take)
        if change == "wrong_pid":
            invalid["live_settings_observations"][0]["evidence"]["pid"] = 43
        elif change == "unknown_pdc":
            invalid["capture_context"]["global_delay_compensation"] = None
        elif change == "unmeasured_group":
            invalid["source_contexts"][0]["kind"] = "group"
        else:
            invalid["native_acquisition"]["epoch_id"] = "different"
        with pytest.raises(ValueError):
            qualification._check_certificate(certificate, invalid)


def test_native_role_extension_requires_actual_nonzero_capture_and_retains_immutable_proof(tmp_path, monkeypatch):
    takes, names = native_experiments(tmp_path)
    proof = calibration.measure_experiments(takes, names, tmp_path / "native-fixture.wav")
    hashes = {"native": "current"}
    monkeypatch.setattr(qualification, "code_hashes", lambda: hashes)
    monkeypatch.setattr(calibration, "code_hashes", lambda: hashes)
    certificate = native_base_certificate(takes, names, tmp_path, hashes)
    grouped, _ = return_experiment(takes["baseline"], tmp_path / "group_first", "g1", 0, kind="group")
    second, _ = return_experiment(takes["baseline"], tmp_path / "group_second", "g2", 0, kind="group")
    extended = calibration.qualify_target_epochs(certificate, {"id": 400}, "group", [grouped, second], tmp_path)
    assert extended["native_source_kinds"] == ["group", "track"]
    assert certificate["native_source_kinds"] == ["track"]
    assert extended["target_offset_evidence"]["400"]["epochs"][0]["rms"] > 0.001
    qualification._check_certificate(extended, grouped)
    evidence = extended["target_offset_evidence"]["400"]["epochs"][0]
    with open(evidence["manifest_path"], "a", encoding="utf-8") as handle:
        handle.write("changed")
    with pytest.raises(ValueError, match="target experiment manifest changed"):
        qualification._check_certificate(extended, grouped)


def native_base_certificate(takes, names, tmp_path, hashes):
    take = takes["baseline"]
    proof = calibration.measure_experiments(takes, names, tmp_path / "native-fixture.wav")
    return {"schema_version": 1, "origin": "computed_from_captured_audio", "song_id": 1,
            "capture_mode": take["mode"], "clock_origin": "experimentally_measured_native_recording_epoch",
            "process_id": 42, "runtime_code_sha256": "current-runtime", "code_hashes": hashes,
            "capture_context": take["capture_context"], "recorder_settings": take["recorder_settings"],
            "source_profiles": [qualification.source_profile(take["source_contexts"][0])],
            "routing_profile": take["routing_profile"], "routing_profile_sha256": take["routing_profile_sha256"],
            "native_source_kinds": ["track"], **proof}


def return_experiment(base, folder, epoch, lag, *, kind="return", anti_phase=False):
    folder.mkdir()
    result = copy.deepcopy(base)
    result["source_contexts"] = [copy.deepcopy(base["source_contexts"][0])]
    result["source_contexts"][0]["kind"] = kind
    result["tracks"] = [result["tracks"][0], result["tracks"][2]]
    result["owned_receivers"] = [result["owned_receivers"][0], result["owned_receivers"][2]]
    result["native_recordings"] = [result["native_recordings"][0], result["native_recordings"][2]]
    target_id = 300 if kind == "return" else 400
    result["tracks"][0].update(kind=kind, name="Original Return" if kind == "return" else "Original Group", ref={"id": target_id})
    for row in (result["owned_receivers"][0], result["native_recordings"][0]):
        row.update(source_ref={"id": target_id}, input_type=result["tracks"][0]["name"])
    result["take_id"] = result["native_acquisition"]["epoch_id"] = epoch
    for phase in ("recording_start", "recording_stop"):
        result["native_acquisition"][phase]["token"] = epoch
    blocks = []
    processed, _ = sf.read(base["tracks"][0]["path"], dtype="float64", always_2d=True)
    if anti_phase:
        processed[:, 1] = -processed[:, 0]
    for index, track in enumerate(result["tracks"]):
        rate = track["native_clip"]["sample_rate"]
        data = np.roll(processed, lag if index == 0 else 37, axis=0)
        path = folder / (str(index) + ".wav")
        sf.write(path, data, rate, subtype="PCM_32")
        data, _ = sf.read(path, dtype="float64", always_2d=True)
        blocks.append(data)
        track["path"], track["native_sha256"] = str(path), qualification._hash(path)
    derivative = folder / "interleaved.wav"
    sf.write(derivative, np.concatenate(blocks, axis=1), rate, subtype="DOUBLE")
    result["interleaved_path"] = str(derivative)
    path = folder / "manifest.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    return result, path


def test_target_id_offset_two_epochs_profile_binding_and_future_sum_never_searches(tmp_path, monkeypatch):
    takes, names = native_experiments(tmp_path)
    hashes = {"capture": "current", "remote_script": "current", "live_settings": "current"}
    monkeypatch.setattr(qualification, "code_hashes", lambda: hashes)
    monkeypatch.setattr(calibration, "code_hashes", lambda: hashes)
    certificate = native_base_certificate(takes, names, tmp_path, hashes)
    first, _ = return_experiment(takes["baseline"], tmp_path / "return_first", "first", 257, anti_phase=True)
    second, _ = return_experiment(takes["baseline"], tmp_path / "return_second", "second", 257, anti_phase=True)
    with pytest.raises(ValueError, match="two distinct"):
        calibration.qualify_target_epochs(certificate, {"id": 300}, "return", [first], tmp_path)
    extended = calibration.qualify_target_epochs(certificate, {"id": 300}, "return", [first, second], tmp_path)
    assert extended["source_offsets_samples"] == {"300": 257}
    qualification._check_certificate(extended, first)
    path = tmp_path / "qualified.json"
    path.write_text(json.dumps(extended), encoding="utf-8")
    monkeypatch.setattr(qualification, "certificate_path", lambda: path)
    attached = qualification.attach_qualification(second)
    assert attached["alignment"]["offsets_samples"]["Original Return"] == 257
    future, _ = return_experiment(takes["baseline"], tmp_path / "return_future", "future", 258, anti_phase=True)
    with pytest.raises(ValueError, match="fixed-offset sum"):
        qualification._check_certificate(extended, future)
    with pytest.raises(ValueError, match="offsets disagree"):
        calibration.qualify_target_epochs(certificate, {"id": 300}, "return", [first, future], tmp_path)
    with pytest.raises(ValueError, match="two distinct"):
        calibration.qualify_target_epochs(certificate, {"id": 300}, "return", [first, first], tmp_path)
    changed = copy.deepcopy(second)
    changed["routing_profile"] = copy.deepcopy(second["routing_profile"])
    changed["routing_profile"]["tracks"][0]["devices"] = [{"latency_in_samples": 128}]
    changed["routing_profile_sha256"] = qualification.routing_profile_hash(changed["routing_profile"])
    with pytest.raises(ValueError, match="profile changed"):
        qualification._check_certificate(extended, changed)


def test_feedback_graph_is_not_admitted():
    profile = {"schema_version": 1, "critical_unknown_fields": [], "tracks": [
        {"ref": {"id": 1}, "name": "Group", "output_type": "Main", "sends": [{"target_ref": {"id": 2}, "value": 1}]},
        {"ref": {"id": 2}, "name": "Return", "output_type": "Group", "sends": []}]}
    with pytest.raises(ValueError, match="feedback routing"):
        qualification.routing_profile_hash(profile)


def test_shared_clip_scan_skips_sdk_raising_group_for_preflight_target_and_final_passage():
    class Group:
        is_foldable = True
        identity = 4
        @property
        def arrangement_clips(self):
            raise RuntimeError("Main, Group and Return Tracks have no arrangement clips")

    child = SimpleNamespace(is_foldable=False, identity=3, arrangement_clips=[SimpleNamespace(start_time=2, end_time=10)])
    other = SimpleNamespace(is_foldable=False, identity=5, arrangement_clips=[SimpleNamespace(start_time=12, end_time=14)])
    song = SimpleNamespace(tracks=[Group(), child, other])
    this = SimpleNamespace(_object_id=lambda track: track.identity)
    for ids, expected in [(None, [2, 12]), ([3, 4, 5], [2, 12]), ([3, 4], [2])]:
        scope = {"song": song, "this": this}
        exec(calibration._clip_scan_code(ids), scope)
        assert [clip.start_time for clip in scope["clips"]] == expected


def test_qualified_native_pcm16_is_explicitly_unsupported(tmp_path):
    takes, names = native_experiments(tmp_path)
    track = takes["baseline"]["tracks"][0]
    data, rate = sf.read(track["path"], dtype="float64", always_2d=True)
    sf.write(track["path"], data, rate, subtype="PCM_16")
    with pytest.raises(ValueError, match="PCM16 is unsupported"):
        calibration.measure_experiments(takes, names, tmp_path / "native-fixture.wav")
    with pytest.raises(ValueError, match="format/resource"):
        qualification.verify_native_sum(takes["baseline"], {"contribution": 0, "program": 37})


@pytest.mark.parametrize("subtype,value,rejected", [("PCM_24", 1.2, True), ("FLOAT", 1.1, False)])
def test_native_pcm_rails_reject_false_linear_proof_but_float_over_unity_is_preserved(tmp_path, subtype, value, rejected):
    takes, _ = native_experiments(tmp_path)
    take = takes["baseline"]
    # A single part and Main can otherwise pass the sum while both acquire the
    # same clipped integer waveform. Floating-point acquisition retains 1.1.
    take["tracks"] = [take["tracks"][0], take["tracks"][2]]
    take["source_contexts"] = [take["source_contexts"][0]]
    take["owned_receivers"] = [take["owned_receivers"][0], take["owned_receivers"][2]]
    take["native_recordings"] = [take["native_recordings"][0], take["native_recordings"][2]]
    blocks = []
    for track in take["tracks"]:
        sf.write(track["path"], np.full((12 * 8000, 2), value), 8000, subtype=subtype)
        block, _ = sf.read(track["path"], dtype="float64", always_2d=True)
        blocks.append(block)
        track["native_sha256"] = qualification._hash(track["path"])
    sf.write(take["interleaved_path"], np.concatenate(blocks, axis=1), 8000, subtype="DOUBLE")
    if rejected:
        with pytest.raises(ValueError, match="possible PCM acquisition clipping"):
            qualification.verify_native_sum(take, {"contribution": 0, "program": 0})
    else:
        assert qualification.verify_native_sum(take, {"contribution": 0, "program": 0})["programme_rms"] > 1


def test_final_passage_eligible_partition_ignores_noaudio_external_and_accepts_real_group_child():
    group = {"ref": {"id": 4}, "kind": "group", "role": "contribution", "name": "G"}
    entries = [
        {"ref": {"id": 1}, "kind": "track", "name": "MIDI", "has_audio_output": False},
        {"ref": {"id": 2}, "kind": "track", "name": "External", "has_audio_output": True, "output_type": "Ext. Out"},
        {"ref": {"id": 3}, "kind": "track", "name": "Child", "has_audio_output": True, "is_grouped": True,
         "parent_ref": {"id": 4}, "output_type": "G", "output_channel": ""},
        {"ref": {"id": 4}, "kind": "group", "name": "G", "has_audio_output": True, "output_type": "Main"}]
    plan = {"tracks": [group], "unsupported_tracks": [{"ref": {"id": identity, "path": "live_set tracks %d" % identity},
              "reason": "nonterminal_or_nonmaster_route"} for identity in (1, 2, 3)]}
    assert calibration._eligible_audio_partition_ids(plan, {"tracks": entries}) == [3, 4]
    entries[2]["output_type"] = "Ext. Out"
    assert calibration._eligible_audio_partition_ids(plan, {"tracks": entries}) == [4]


def test_automatic_targets_return_first_owned_child_cleanup_and_selected_device_restore(tmp_path, monkeypatch):
    takes, names = native_experiments(tmp_path)
    hashes = {"native": "current"}
    monkeypatch.setattr(qualification, "code_hashes", lambda: hashes)
    monkeypatch.setattr(calibration, "code_hashes", lambda: hashes)
    monkeypatch.setattr(calibration, "_require_runtime", lambda bridge: None)
    certificate = native_base_certificate(takes, names, tmp_path, hashes)
    returns = [return_experiment(takes["baseline"], tmp_path / ("r%d" % index), "r%d" % index, 257)[0] for index in range(2)]
    groups = [return_experiment(takes["baseline"], tmp_path / ("g%d" % index), "g%d" % index, 0, kind="group")[0] for index in range(2)]
    # Group sends reach the already-qualified Return. Its correction stays fixed;
    # the group learner must not re-fit it or silently omit its contribution.
    for index, group in enumerate(groups):
        source, rate = sf.read(group["tracks"][0]["path"], dtype="float64", always_2d=True)
        ret = copy.deepcopy(returns[index]["tracks"][0]); ret["receiver_ref"] = {"id": 555}
        ret_path = tmp_path / ("gret%d.wav" % index)
        sf.write(ret_path, np.roll(source * 0.4, 257, axis=0), rate, subtype="PCM_32")
        ret["path"], ret["native_sha256"] = str(ret_path), qualification._hash(ret_path)
        group["tracks"].insert(1, ret)
        group["source_contexts"].append(copy.deepcopy(returns[index]["source_contexts"][0]))
        for key in ("owned_receivers", "native_recordings"):
            route = copy.deepcopy(returns[index][key][0]); route["receiver_ref"] = {"id": 555}
            group[key].insert(1, route)
        program = group["tracks"][-1]
        sf.write(program["path"], np.roll(source * 1.4, 37, axis=0), rate, subtype="PCM_32")
        program["native_sha256"] = qualification._hash(program["path"])
        blocks = [sf.read(track["path"], dtype="float64", always_2d=True)[0] for track in group["tracks"]]
        sf.write(group["interleaved_path"], np.concatenate(blocks, axis=1), rate, subtype="DOUBLE")

    class Bridge:
        def __init__(self): self.calls = []
        def request(self, method, params):
            self.calls.append((method, params))
            code = params.get("code", "")
            if "'last_end'" in code:
                return {"last_end": 0, "tempo": 120, "start_time": 11, "position": 7}
            if "song.create_audio_track" in code:
                return {"ref": {"id": 999}, "devices_empty": True, "warping": False, "output": "Sends Only", "sends": [1]}
            if "'starts'" in code:
                return {"starts": [], "tempo": 120, "start_time": 11, "position": 7}
            return True

    import in_mix_capture
    monkeypatch.setattr(in_mix_capture, "read_routing_profile", lambda bridge, request=None: {
        "profile": certificate["routing_profile"], "sha256": certificate["routing_profile_sha256"]})
    order = []
    queues = {"return": iter(returns), "group": iter(groups)}

    def capture(bridge, args):
        kind = "group" if args["track_refs"] else "return"
        order.append(kind)
        assert args["return_refs"] == [{"id": 300}]
        return next(queues[kind])

    monkeypatch.setattr(calibration, "capture_in_mix", capture)
    bridge = Bridge()
    plan = {"selected_track": {"id": 10}, "selected_device": {"id": 11}, "tracks": [
        {"ref": {"id": 400}, "kind": "group"}, {"ref": {"id": 300}, "kind": "return"}]}
    report = {"cleanup_complete": True}
    candidate = calibration._calibrate_existing_targets(bridge, certificate, plan, tmp_path, report, lambda: None)
    assert order == ["return", "return", "group", "group"]
    assert candidate["source_offsets_samples"] == {"300": 257, "400": 0}
    deletes = [params["code"] for _, params in bridge.calls if "song.delete_track" in params.get("code", "")]
    assert len(deletes) == 2 and all("_same_live_object" in code for code in deletes)
    assert all("song.start_time = 11" in code and "song.current_song_time = 7" in code for code in deletes)
    assert sum("select_device" in params.get("code", "") for _, params in bridge.calls) == 2
    assert all(item["cleanup_complete"] for item in report["target_calibrations"])


def test_measured_replay_all_seven_raw_files_and_acquisition_hashes_are_required(tmp_path, monkeypatch):
    takes, names = native_experiments(tmp_path)
    hashes = {"capture": "acquisition", "remote_script": "bridge", "live_settings": "settings", "qualification": "new-policy"}
    monkeypatch.setattr(qualification, "code_hashes", lambda: hashes)
    monkeypatch.setattr(calibration, "code_hashes", lambda: hashes)
    old = native_base_certificate(takes, names, tmp_path, {**hashes, "qualification": "old-policy"})
    fixture = tmp_path / "native-fixture.wav"
    report = {"ok": True, "cleanup_complete": True, "takes": takes, "owned_names": names,
              "fixture": {"path": str(fixture), "sha256": qualification._hash(fixture)},
              "prior": {"song_ref": {"id": 1}}, "computed_certificate": old}
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    replayed = calibration.revalidate_calibration_report(path)
    assert replayed["code_hashes"]["qualification"] == "new-policy"
    assert replayed["replay"]["source_report_sha256"] == qualification._hash(path)
    assert replayed["measurements"]["latency"]["fixture_offset_samples"] == 0
    hashes["capture"] = "changed-acquisition"
    with pytest.raises(ValueError, match="fresh physical calibration"):
        calibration.revalidate_calibration_report(path)
    hashes["capture"] = "acquisition"
    damaged = old["evidence"][0]["path"]
    with open(damaged, "ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="physical calibration evidence changed"):
        calibration.revalidate_calibration_report(path)


def test_unknown_capture_outcome_retains_fixtures_and_preserves_certificate(tmp_path, monkeypatch):
    class Bridge:
        def __init__(self):
            self.calls = []

        def request(self, method, params):
            self.calls.append((method, params))
            if method == "native_in_mix_plan":
                return {"song_ref": {"id": 1}, "selected_track": {"id": 2},
                        "transport": {"playing": False, "time": 7, "loop": True, "tempo": 120}}
            if method == "exec" and "last_end" in params["code"]:
                return {"last_end": 32, "master_devices": []}
            if method == "exec" and "create_audio_track" in params["code"]:
                return {"id": len(self.calls)}
            return {}

    monkeypatch.setattr(calibration, "_require_runtime", lambda bridge: None)
    monkeypatch.setattr(calibration, "capture_in_mix", lambda *args: {"ok": False, "cleanup_blocked": "sent timeout"})
    path = tmp_path / "valid-certificate.json"
    path.write_text("existing certificate", encoding="utf-8")
    monkeypatch.setattr(calibration, "certificate_path", lambda: path)
    bridge = Bridge()
    result = calibration.calibrate_in_mix(bridge, {"output_directory": str(tmp_path)})
    assert not result["qualified"] and not result["cleanup_complete"]
    assert "Unknown mutation outcome" in result["cleanup_blocked"]
    assert path.read_text(encoding="utf-8") == "existing certificate"
    assert not any("delete_track" in params.get("code", "") for _, params in bridge.calls)
    report = json.loads(open(result["experiment_path"], encoding="utf-8").read())
    assert len(report["owned_refs"]) == 2 and len(report["token"]) == 32
