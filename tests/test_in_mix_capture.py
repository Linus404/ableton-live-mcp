import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

import in_mix_capture as capture
from audio_capture import validate_wav
from test_remote_bridge_fake_live import make_bridge


@pytest.mark.parametrize("main_name", ["Master", "Main"])
def test_terminal_topology_and_explicit_unsupported(monkeypatch, main_name):
    bridge, song, _ = make_bridge(monkeypatch)
    for track in list(song.tracks) + list(song.return_tracks):
        track.output_routing_type = SimpleNamespace(display_name=main_name)
    song.tracks[0].is_foldable = True
    song.tracks[1].is_grouped = True
    song.tracks[1].group_track = song.tracks[0]
    song.tracks[1].output_routing_type = SimpleNamespace(display_name=song.tracks[0].name)
    plan = bridge._rpc_in_mix_capture_plan({})
    assert plan["capture_context"]["global_delay_compensation"] is None
    assert "panning" in plan["capture_context"]["master"]
    assert "sources" not in plan["capture_context"] and len(plan["source_contexts"]) == 2
    assert [track["kind"] for track in plan["tracks"]] == ["group", "return", "master"]
    assert plan["unsupported_tracks"][0]["reason"] == "nonterminal_or_nonmaster_route"
    with pytest.raises(ValueError, match="directly to Master"):
        bridge._rpc_in_mix_capture_plan({"track_refs": [bridge._audio_capture_ref(song.tracks[1])]})
    song.tracks[0].solo = True
    with pytest.raises(ValueError, match="soloed"):
        bridge._rpc_in_mix_capture_plan({})


def test_receiver_settling_failure_is_owned_cleanup_exact(monkeypatch):
    bridge, song, _ = make_bridge(monkeypatch)
    original = list(song.tracks)
    receiver = SimpleNamespace(name="", available_output_routing_types=[], available_input_routing_types=[],
                               input_routing_type=SimpleNamespace(display_name="Ext. In"), available_input_routing_channels=[])
    monkeypatch.setattr(song, "create_audio_track", lambda index: song.tracks.append(receiver), raising=False)
    token = "a" * 32
    result = bridge._rpc_in_mix_capture_add_receiver({"token": token, "source_ref": bridge._audio_capture_ref(original[0]), "native": True})
    assert result["pending"] == "routing_settle" and bridge._in_mix_owned[token] == [receiver]
    params = {"token": token, "receiver_ref": result["receiver_ref"]}
    assert bridge._rpc_in_mix_capture_configure_receiver(params)["waiting_for"] == "input_type"
    receiver.available_input_routing_types = [SimpleNamespace(display_name=original[0].name)]
    assert bridge._rpc_in_mix_capture_configure_receiver(params)["waiting_for"] == "input_channel"
    assert bridge._rpc_in_mix_capture_configure_receiver(params)["waiting_for"] == "input_channel"
    receiver.available_input_routing_channels = [SimpleNamespace(display_name="Post Mixer")]
    failed = bridge._rpc_in_mix_capture_configure_receiver(params)
    assert not failed["ok"] and "Sends Only" in failed["error"]
    assert bridge._rpc_in_mix_capture_configure_receiver(params) == failed
    assert len(song.tracks) == len(original) + 1
    unrelated = SimpleNamespace(name=receiver.name)
    song.tracks.append(unrelated)
    monkeypatch.setattr(song, "delete_track", lambda index: song.tracks.pop(index), raising=False)
    cleaned = bridge._rpc_in_mix_capture_cleanup({"token": token})
    assert cleaned["ok"] and len(cleaned["deleted"]) == 1
    assert song.tracks == original + [unrelated]


class NativeBridge:
    def __init__(self, tmp_path, fail_begin=False, observed_time=1, clip_start=0):
        self.calls = []
        self.transport = dict(playing=False, time=7, tempo=120, loop=True)
        self.fail_begin, self.observed_time, self.clip_start = fail_begin, observed_time, clip_start
        self.source = tmp_path / "live_recording.wav"
        self.data = np.arange(44100, dtype=np.int32).reshape(22050, 2) / 44100
        sf.write(self.source, self.data, 44100, subtype="PCM_32")

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "ping":
            return {"remote_script": {"runtime_version": "test-runtime", "bridge_sha256": "test-source", "runtime_code_sha256": "test-code", "process_id": 1}}
        if method == "native_in_mix_plan":
            return {"transport": self.transport, "tracks": [{"name": "Audio", "ref": {"id": 2}}],
                    "song_ref": {"id": 1}, "signal_path": "Post Mixer", "selected_track": {"id": 2}}
        if method == "native_in_mix_prepare":
            return {"prepared": True}
        if method == "in_mix_capture_add_receiver":
            assert params["native"] is True
            return {"pending": "routing_settle", "receiver_ref": {"id": 3}}
        if method == "in_mix_capture_configure_receiver":
            return {"ok": True, "receiver_ref": {"id": 3}, "input_type": "Audio", "input_channel": "Post Mixer", "output_type": "Sends Only"}
        if method == "native_in_mix_begin":
            if self.fail_begin:
                raise TimeoutError("unknown sent begin")
            return {"begun": True}
        if method == "native_in_mix_status":
            return {"transport": {"playing": True, "time": self.observed_time}, "begin_unix": 123,
                    "receivers": [{"receiver_ref": {"id": 3}, "source_ref": {"id": 2}, "arm": True,
                                   "route_verified": True, "current_monitoring_state": 2, "output_type": "Sends Only",
                                   "sends_zero": True, "devices_empty": True, "clips": [{"file_path": str(self.source),
                                   "is_recording": False, "is_audio_clip": True, "is_arrangement_clip": True, "sample_rate": 44100,
                                   "sample_length": len(self.data), "start_time": self.clip_start, "end_time": 1, "warping": True}]}]}
        if method == "native_in_mix_stop":
            return {"stopped": True}
        if method in ("native_in_mix_restore", "audio_capture_restore"):
            return {"restored": True}
        if method == "in_mix_capture_cleanup":
            return {"ok": True}
        return {}


@pytest.fixture
def native_env(monkeypatch, tmp_path):
    import live_settings
    monkeypatch.setattr(live_settings, "read_live_settings", lambda expected_pid: {"delay_compensation": True, "reduced_latency_when_monitoring": False,
                         "evidence": {"source": "windows_native_options_menu", "method_version": 1, "pid": 1}})
    monkeypatch.setattr(capture, "_require_runtime", lambda bridge: {"runtime_current": True, "live_mutations_safe": True})
    monkeypatch.setattr(capture, "_completed_wav", lambda path, timeout=5: validate_wav(path))
    monkeypatch.setattr(capture, "read_routing_profile", lambda bridge, **kwargs: {
        "profile": {"schema_version": 1, "tracks": [], "unknown_fields": [], "critical_unknown_fields": []},
        "sha256": "stable-profile", "evidence": {"source": "read_only_live_routing_profile", "observed_at_unix": 1}})
    return {"start_beat": 0, "length_beats": 1, "output_directory": str(tmp_path / "captures")}


def test_native_capture_removes_owned_tracks_before_read_and_keeps_epoch_unverified(native_env, monkeypatch, tmp_path):
    bridge = NativeBridge(tmp_path)
    def finalized(path, timeout=5):
        assert any(method == "in_mix_capture_cleanup" for method, _ in bridge.calls)
        return validate_wav(path)
    monkeypatch.setattr(capture, "_completed_wav", finalized)
    result = capture.capture_in_mix(bridge, native_env)
    assert result["ok"] and result["mode"] == "in_mix_native_arrangement"
    assert result["capture_engine"] == "live_native_arrangement"
    assert result["native_acquisition"]["epoch_id"] == result["take_id"]
    assert result["native_acquisition"]["receivers_monitor_off"]
    assert result["derivative_clock"] == "constructed_from_native"
    assert result["interleaved_is_reconstructed"] and not result["shared_sample_clock"]
    assert not result["alignment"]["verified"] and not result["native_clock"]["acquisition_epoch_verified"]
    original, _ = sf.read(bridge.source, dtype="float64", always_2d=True)
    combined, _ = sf.read(result["interleaved_path"], dtype="float64", always_2d=True)
    assert np.array_equal(original, combined)
    assert np.any(original.astype("float32").astype("float64") != original)
    assert Path(result["tracks"][0]["path"]).read_bytes() == bridge.source.read_bytes()
    assert not any(method == "agent_audio_tap_setup" for method, _ in bridge.calls)
    assert bridge.calls[-1] == ("transport", {"action": "stop", "time": 7})


def test_native_sent_begin_failure_has_no_further_live_calls(native_env, tmp_path):
    bridge = NativeBridge(tmp_path, fail_begin=True)
    result = capture.capture_in_mix(bridge, native_env)
    assert not result["complete"] and result["cleanup_blocked"]
    assert bridge.calls[-1][0] == "native_in_mix_begin"
    stored = json.loads(Path(result["manifest_path"]).read_text())
    assert stored["last_rpc"]["method"] == "native_in_mix_begin"
    assert stored["last_rpc"]["outcome"] == "submitted"
    assert stored["last_rpc"]["params"]["max_duration_seconds"] == 2.5


@pytest.mark.parametrize("case", ["forward_jump", "wrong_clip_epoch"])
def test_native_capture_refuses_timeline_or_clip_epoch_changes(native_env, tmp_path, case):
    bridge = NativeBridge(tmp_path, observed_time=100 if case == "forward_jump" else 1, clip_start=0.1 if case == "wrong_clip_epoch" else 0)
    result = capture.capture_in_mix(bridge, native_env)
    assert not result["complete"] and result["cleanup_complete"]
    assert ("jumped forwards" if case == "forward_jump" else "acquisition epoch") in result["error"]


def test_native_capture_rejects_settings_from_another_live_process(native_env, monkeypatch, tmp_path):
    import live_settings
    seen = []
    def wrong_process(expected_pid):
        seen.append(expected_pid)
        return {"delay_compensation": True, "reduced_latency_when_monitoring": False, "evidence": {"pid": 2}}
    monkeypatch.setattr(live_settings, "read_live_settings", wrong_process)
    bridge = NativeBridge(tmp_path)
    with pytest.raises(RuntimeError, match="bridge-serving process"):
        capture.capture_in_mix(bridge, native_env)
    assert seen == [1]
    assert not any(method == "native_in_mix_prepare" for method, _ in bridge.calls)


def test_native_guard_refuses_original_armed_track(monkeypatch):
    bridge, song, _ = make_bridge(monkeypatch)
    song.tracks[0].can_be_armed = True
    song.tracks[0].arm = True
    with pytest.raises(RuntimeError, match="armed"):
        bridge._native_in_mix_guard()


def test_bridge_runtime_identity_has_serving_process(monkeypatch):
    bridge, _, _ = make_bridge(monkeypatch)
    assert bridge._remote_script_info()["process_id"] == os.getpid()


@pytest.mark.parametrize("change", ["source", "channel", "monitor", "send", "device"])
def test_native_route_proof_refuses_changed_acquisition_path(monkeypatch, change):
    bridge, song, _ = make_bridge(monkeypatch)
    source = song.tracks[0]
    receiver = SimpleNamespace(name="Owned Receiver", devices=[], current_monitoring_state=2,
                 input_routing_type=SimpleNamespace(display_name=source.name),
                 input_routing_channel=SimpleNamespace(display_name="Post Mixer"),
                 output_routing_type=SimpleNamespace(display_name="Sends Only"),
                 mixer_device=SimpleNamespace(sends=[SimpleNamespace(value=0, min=0)]))
    song.tracks.append(receiver)
    bridge._in_mix_configs = {"owned": [{"receiver": receiver, "source": source, "native": True}]}
    proof = bridge._native_in_mix_receiver_proof("owned", receiver)
    assert proof["route_verified"] and proof["source_ref"]["id"] == bridge._audio_capture_ref(source)["id"]
    if change == "source":
        receiver.input_routing_type = SimpleNamespace(display_name="Another Source")
    elif change == "channel":
        receiver.input_routing_channel = SimpleNamespace(display_name="Post FX")
    elif change == "monitor":
        receiver.current_monitoring_state = 0
    elif change == "send":
        receiver.mixer_device.sends[0].value = 0.5
    else:
        receiver.devices.append(SimpleNamespace(name="Unexpected"))
    with pytest.raises(RuntimeError, match="changed"):
        bridge._native_in_mix_receiver_proof("owned", receiver)


def test_native_watchdog_stops_only_matching_active_epoch(monkeypatch):
    bridge, song, _ = make_bridge(monkeypatch)
    receiver = SimpleNamespace(arm=True)
    bridge._in_mix_owned = {"owned": [receiver]}
    state = bridge._native_in_mix_take = {"token": "owned", "begun": True, "watchdog_deadline": 0}
    song.is_playing, song.record_mode = True, True
    bridge._native_in_mix_watchdog("foreign")
    assert song.record_mode and receiver.arm
    bridge._native_in_mix_watchdog("owned")
    assert not song.is_playing and not song.record_mode and not receiver.arm
    assert state["stopped"] and state["watchdog_triggered"]
    song.is_playing, song.record_mode = True, True
    bridge._native_in_mix_watchdog("owned")
    assert song.is_playing and song.record_mode


def test_native_watchdog_obeys_deadline_on_ten_hz_control_surface(monkeypatch):
    bridge, song, _ = make_bridge(monkeypatch)
    remote_time = bridge._native_in_mix_watchdog.__func__.__globals__["time"]
    clock = [0.0]
    monkeypatch.setattr(remote_time, "monotonic", lambda: clock[0])
    pending = []
    monkeypatch.setattr(bridge, "schedule_message", lambda ticks, callback: pending.append((clock[0] + ticks * 0.1, ticks, callback)))
    receiver = SimpleNamespace(arm=True)
    bridge._in_mix_owned = {"owned": [receiver]}
    bridge._native_in_mix_take = {"token": "owned", "begun": True, "watchdog_deadline": 3.0}
    song.is_playing, song.record_mode = True, True
    bridge._native_in_mix_watchdog("owned")
    while pending:
        due, ticks, callback = pending.pop(0)
        assert ticks == 1
        clock[0] = due
        callback()
    assert 3.0 <= clock[0] <= 3.1
    assert not song.is_playing and not song.record_mode and not receiver.arm
    assert bridge._native_in_mix_take["watchdog_triggered"]


def test_continue_does_not_reset_insert_marker_when_property_lags(monkeypatch):
    bridge, song, _ = make_bridge(monkeypatch)
    calls = []
    song.current_song_time = 17.4
    song.is_playing = False
    song.continue_playing = lambda: calls.append("continue")
    song.start_playing = lambda: pytest.fail("start_playing would reset the insert marker")
    result = bridge._rpc_transport({"action": "continue"})
    assert calls == ["continue"] and result["time"] == 17.4
    assert result["playing"] is True and result["raw_playing"] is False and result["settled"] is False


def test_absolute_seek_does_not_derive_delta_from_lagging_getter(monkeypatch):
    bridge, _, _ = make_bridge(monkeypatch)
    requested = []
    class LaggingSong:
        @property
        def current_song_time(self):
            return 999
        @current_song_time.setter
        def current_song_time(self, value):
            requested.append(value)
        def jump_by(self, delta):
            pytest.fail("relative seek would derive a wrong delta from stale current_song_time")
    bridge._seek_song(LaggingSong(), 17.4)
    assert requested == [17.4]


def test_stop_does_not_reset_an_already_stopped_playhead(monkeypatch):
    bridge, song, _ = make_bridge(monkeypatch)
    song.current_song_time, song.is_playing = 17.4, False
    song.stop_playing = lambda: pytest.fail("second Stop can reset the stopped playhead")
    bridge._stop_transport(song)
    assert song.current_song_time == 17.4


def test_native_nonzero_epoch_sets_insert_marker_starts_once_and_restores_marker(monkeypatch):
    bridge, song, _ = make_bridge(monkeypatch)
    song.current_song_time, song.is_playing, song.start_time = 23.2, False, 8.0
    song.loop_start, song.loop_length, song.punch_in, song.punch_out = 4.0, 16.0, False, False
    token = "a" * 32
    prepared = bridge._rpc_native_in_mix_prepare({"token": token, "start_beat": 17.4, "end_beat": 26.1})
    assert prepared["prepared"] and song.start_time == song.current_song_time == 17.4
    source = song.tracks[0]
    receiver = SimpleNamespace(name="Owned Receiver", arm=False, devices=[], arrangement_clips=[], current_monitoring_state=2,
                 input_routing_type=SimpleNamespace(display_name=source.name), input_routing_channel=SimpleNamespace(display_name="Post Mixer"),
                 output_routing_type=SimpleNamespace(display_name="Sends Only"), mixer_device=SimpleNamespace(sends=[]))
    song.tracks.append(receiver)
    bridge._in_mix_owned = {token: [receiver]}
    bridge._in_mix_configs = {token: [{"receiver": receiver, "source": source, "native": True}]}
    calls = []
    def start():
        calls.append(song.start_time)
        song.current_song_time = song.start_time
        # is_playing intentionally lags an accepted start.
    song.start_playing = start
    song.continue_playing = lambda: pytest.fail("native recording must use its explicit prepared insert marker")
    monkeypatch.setattr(bridge, "schedule_message", lambda ticks, callback: None)
    begun = bridge._rpc_native_in_mix_begin({"token": token, "max_duration_seconds": 3})
    assert begun["begun"] and calls == [17.4] and song.record_mode
    with pytest.raises(RuntimeError, match="prepared stopped ownership"):
        bridge._rpc_native_in_mix_begin({"token": token, "max_duration_seconds": 3})
    assert calls == [17.4]
    bridge._rpc_native_in_mix_stop({"token": token})
    bridge._rpc_native_in_mix_restore({"token": token})
    assert song.start_time == 8.0 and song.loop_start == 4.0 and song.loop_length == 16.0


def test_native_prepare_waits_for_absolute_cursor_and_marker_without_resending(monkeypatch):
    bridge, song, _ = make_bridge(monkeypatch)
    song.loop_start, song.loop_length, song.punch_in, song.punch_out = 4.0, 16.0, False, False
    song.is_playing, song.seek_settled, song.seek_writes = False, False, []
    class LaggingSong(type(song)):
        @property
        def current_song_time(self):
            return self.requested_cursor if self.seek_settled else 23.2
        @current_song_time.setter
        def current_song_time(self, value):
            self.seek_writes.append(("cursor", value))
            self.requested_cursor = value
        @property
        def start_time(self):
            return self.requested_marker if self.seek_settled else 8.0
        @start_time.setter
        def start_time(self, value):
            self.seek_writes.append(("marker", value))
            self.requested_marker = value
    song.__class__ = LaggingSong
    song.stop_playing = lambda: pytest.fail("repeated Stop must not reset a pending absolute seek")
    params = {"token": "a" * 32, "start_beat": 17.4, "end_beat": 26.1}
    assert bridge._rpc_native_in_mix_prepare(params)["pending"] == "transport_seek"
    assert bridge._rpc_native_in_mix_prepare(params)["pending"] == "transport_seek"
    song.seek_settled = True
    assert bridge._rpc_native_in_mix_prepare(params)["prepared"]
    assert song.seek_writes == [("cursor", 17.4), ("marker", 17.4)]


def test_native_capture_refuses_playing_transport_before_mutation(native_env, tmp_path):
    bridge = NativeBridge(tmp_path)
    bridge.transport["playing"] = True
    original = dict(bridge.transport)
    with pytest.raises(RuntimeError, match="requires stopped transport"):
        capture.capture_in_mix(bridge, native_env)
    assert bridge.transport == original
    assert not any(method == "native_in_mix_prepare" for method, _ in bridge.calls)


def test_recording_bound_and_begin_ack_are_durable_before_polling(native_env, tmp_path):
    seen = []
    class InspectingBridge(NativeBridge):
        def request(self, method, params):
            if method in ("native_in_mix_begin", "native_in_mix_status", "native_in_mix_stop"):
                manifest_path = next(Path(native_env["output_directory"]).glob("*/manifest.json"))
                stored = json.loads(manifest_path.read_text())
                assert stored["last_rpc"] == {"method": method, "params": params, "outcome": "submitted"}
                if method == "native_in_mix_begin":
                    assert params["max_duration_seconds"] == 2.5
                    assert stored["native_clock"]["watchdog_duration_seconds"] == 2.5
                    assert "begin_ack" not in stored
                else:
                    assert stored["begin_ack"]["begun"]
                    assert stored["native_acquisition"]["recording_start"]["begun"]
                seen.append(method)
            return super().request(method, params)
    result = capture.capture_in_mix(InspectingBridge(tmp_path), {**native_env, "max_duration_seconds": 300})
    assert result["ok"] and seen[:2] == ["native_in_mix_begin", "native_in_mix_status"]
    assert result["native_clock"]["watchdog_duration_seconds"] == 2.5


def return_plan():
    return {"tracks": [{"kind": "track", "ref": {"id": 1}},
                       {"kind": "return", "ref": {"id": 2, "path": "live_set return_tracks 0"}},
                       {"kind": "return", "ref": {"id": 3, "path": "live_set return_tracks 1"}},
                       {"kind": "master", "ref": {"id": 4}}],
            "source_contexts": [{"marker": "track"}, {"marker": "returnA"}, {"marker": "returnB"}]}


def test_return_selector_pairs_contexts_and_preserves_master():
    selected = capture._select_returns(return_plan(), [{"path": "live_set return_tracks 1"}])
    assert [entry["ref"]["id"] for entry in selected["tracks"]] == [1, 3, 4]
    assert selected["source_contexts"] == [{"marker": "track"}, {"marker": "returnB"}]
    empty = capture._select_returns(return_plan(), [])
    assert [entry["ref"]["id"] for entry in empty["tracks"]] == [1, 4]


@pytest.mark.parametrize("refs", [[{"id": 1}], [{"id": 99}], [{"id": 2}, {"id": 2}], [{"id": True}], [{"id": 2.1}]])
def test_return_selector_refuses_nonreturn_unknown_duplicate_or_boolean_id(refs):
    with pytest.raises(ValueError):
        capture._select_returns(return_plan(), refs)


def test_return_selector_flag_conflict_precedes_bridge_calls(native_env, tmp_path):
    bridge = NativeBridge(tmp_path)
    with pytest.raises(ValueError, match="cannot be combined"):
        capture.capture_in_mix(bridge, {**native_env, "return_refs": [], "include_returns": False})
    assert not bridge.calls


def test_explicit_null_return_selector_is_rejected_before_bridge_calls(native_env, tmp_path):
    bridge = NativeBridge(tmp_path)
    with pytest.raises(ValueError, match="return_refs must be a list"):
        capture.capture_in_mix(bridge, {**native_env, "return_refs": None})
    assert not bridge.calls


def profile_fixture(monkeypatch):
    bridge, song, _ = make_bridge(monkeypatch)
    for track in list(song.tracks) + list(song.return_tracks) + [song.master_track]:
        track.input_routing_type = SimpleNamespace(display_name="Ext. In")
        track.input_routing_channel = SimpleNamespace(display_name="")
        track.available_input_routing_channels = []
        track.output_routing_type = SimpleNamespace(display_name="Main")
        track.current_monitoring_state = 1
        track.mixer_device.sends = [SimpleNamespace(value=0.0)] if track is not song.master_track else []
        track.mixer_device.volume = SimpleNamespace(value=0.85)
        track.mixer_device.panning = SimpleNamespace(value=0.0)
        for device in track.devices:
            device.can_have_chains = False
            device.is_active = True
    class ProfileBridge:
        def request(self, method, params):
            assert method == "exec"
            return bridge._rpc_exec(params)
    return bridge, song, ProfileBridge()


def test_routing_profile_excludes_exact_owned_but_keeps_parent_music(monkeypatch):
    bridge, song, reader = profile_fixture(monkeypatch)
    first, second = song.tracks
    bridge._in_mix_offset_owned = {"offset": [first]}
    bridge._audio_roles_owned = {"parent": [second]}
    before = capture.read_routing_profile(reader)
    ids = [entry["ref"]["id"] for entry in before["profile"]["tracks"]]
    assert bridge._audio_capture_ref(first)["id"] not in ids
    assert bridge._audio_capture_ref(second)["id"] in ids
    assert before["evidence"]["excluded_refs"] == [bridge._audio_capture_ref(first)]
    second.mixer_device.volume.value = 0.4
    second.mixer_device.panning.value = 1.0
    after = capture.read_routing_profile(reader)
    assert after["sha256"] == before["sha256"]
    second.current_monitoring_state = 0
    assert capture.read_routing_profile(reader)["sha256"] != before["sha256"]


def test_routing_profile_retains_unknown_latency_and_nested_topology(monkeypatch):
    bridge, song, reader = profile_fixture(monkeypatch)
    device = song.tracks[0].devices[0]
    device.can_have_chains = True
    child = SimpleNamespace(name="Nested", class_name="NestedEffect", parameters=[], is_active=True, can_have_chains=False)
    device.chains = [SimpleNamespace(name="Chain", devices=[child], mute=False, solo=False)]
    before = capture.read_routing_profile(reader)
    node = before["profile"]["tracks"][0]["devices"][0]
    assert node["latency_in_samples"] is None
    assert node["chains"][0]["devices"][0]["class_name"] == "NestedEffect"
    assert before["profile"]["unknown_fields"]
    assert not before["profile"]["critical_unknown_fields"]
    child.latency_in_samples = 64
    assert capture.read_routing_profile(reader)["sha256"] != before["sha256"]


def test_routing_profile_changes_fail_capture_and_still_cleanup(native_env, monkeypatch, tmp_path):
    profiles = iter([{"profile": {"critical_unknown_fields": []}, "sha256": "before", "evidence": {}},
                     {"profile": {"critical_unknown_fields": []}, "sha256": "changed", "evidence": {}}])
    monkeypatch.setattr(capture, "read_routing_profile", lambda bridge, **kwargs: next(profiles))
    result = capture.capture_in_mix(NativeBridge(tmp_path), native_env)
    assert not result["complete"] and result["cleanup_complete"]
    assert not result["routing_profile_stable"] and "profile changed" in result["error"]


def test_profile_binds_lookahead_but_not_gain_cutoff_or_envelope_automation(monkeypatch):
    _, song, reader = profile_fixture(monkeypatch)
    device = song.tracks[0].devices[0]
    controls = [SimpleNamespace(name="Lookahead", value=3.0, automation_state=0),
                SimpleNamespace(name="Output Gain", value=0.5, automation_state=1),
                SimpleNamespace(name="Filter Cutoff", value=0.5, automation_state=1),
                SimpleNamespace(name="Envelope Attack", value=0.5, automation_state=1)]
    device.parameters.extend(controls)
    before = capture.read_routing_profile(reader)
    names = [parameter["name"] for parameter in before["profile"]["tracks"][0]["devices"][0]["parameters"]]
    assert names == ["Device On", "Lookahead"]
    for control in controls[1:]:
        control.value = 0.75
    assert capture.read_routing_profile(reader)["sha256"] == before["sha256"]
    controls[0].value = 6.0
    assert capture.read_routing_profile(reader)["sha256"] != before["sha256"]
    controls[0].automation_state = 1
    dynamic = capture.read_routing_profile(reader)
    assert any("automated_critical_parameter:Lookahead" in key for key in dynamic["profile"]["critical_unknown_fields"])


def test_profile_binds_rack_returns_chain_sends_and_sc_on(monkeypatch):
    bridge, song, reader = profile_fixture(monkeypatch)
    rack = song.tracks[0].devices[0]
    rack.can_have_chains = True
    sc = SimpleNamespace(name="SC On", value=0.0, automation_state=0)
    rack.parameters.append(sc)
    effect = SimpleNamespace(name="Return Limiter", class_name="Limiter", parameters=[], is_active=True, can_have_chains=False, latency_in_samples=64)
    returned = SimpleNamespace(name="Rack Return", devices=[effect], mute=False, solo=False, mixer_device=SimpleNamespace(sends=[]),
                               output_routing_type=SimpleNamespace(display_name="Rack Output"), output_routing_channel=None,
                               available_output_routing_channels=[])
    regular = SimpleNamespace(name="Pad", devices=[], mute=False, solo=False, mixer_device=SimpleNamespace(sends=[SimpleNamespace(value=0.25)]))
    rack.chains, rack.return_chains = [regular, returned], [returned]
    before = capture.read_routing_profile(reader)
    node = before["profile"]["tracks"][0]["devices"][0]
    assert len(node["chains"]) == len(node["return_chains"]) == 1
    assert node["return_chains"][0]["devices"][0]["latency_in_samples"] == 64
    assert node["chains"][0]["sends"][0] == {"target_ref": bridge._audio_capture_ref(returned), "value": 0.25}
    assert "SC On" in [p["name"] for p in node["parameters"]]
    assert not before["profile"]["critical_unknown_fields"]
    sc.value = 1.0
    assert capture.read_routing_profile(reader)["sha256"] != before["sha256"]
    sc.value = 0.0
    effect.latency_in_samples = 128
    assert capture.read_routing_profile(reader)["sha256"] != before["sha256"]
    effect.latency_in_samples = 64
    regular.mixer_device.sends[0].value = 0.5
    assert capture.read_routing_profile(reader)["sha256"] != before["sha256"]
    regular.mixer_device.sends = []
    regular.mixer_device = None
    with pytest.raises(ValueError, match="send topology is unreadable"):
        capture.read_routing_profile(reader)


def test_profile_uses_stable_ids_across_all_refs_when_index_paths_shift(monkeypatch):
    bridge, song, reader = profile_fixture(monkeypatch)
    parent, child_track = song.tracks
    parent.is_foldable = True
    child_track.is_grouped, child_track.group_track = True, parent
    rack = parent.devices[0]
    rack.can_have_chains = True
    port = SimpleNamespace(routing_type=SimpleNamespace(display_name="Sidechain Source"), routing_channel=SimpleNamespace(display_name="1/2"))
    nested = SimpleNamespace(name="Nested", class_name="NestedEffect", parameters=[], is_active=True, can_have_chains=False, audio_inputs=[port])
    returned = SimpleNamespace(name="Rack Return", devices=[], mute=False, solo=False, mixer_device=SimpleNamespace(sends=[]))
    rack.chains = [SimpleNamespace(name="Pad", devices=[nested], mute=False, solo=False,
                                   mixer_device=SimpleNamespace(sends=[SimpleNamespace(value=0.25)]))]
    rack.return_chains = [returned]
    offset = [0]
    original = bridge._audio_capture_ref
    def indexed_reference(obj, path=None):
        value = original(obj, path)
        return None if value is None else {**value, "path": "live_set tracks " + str(offset[0]) + " object " + str(value["id"])}
    monkeypatch.setattr(bridge, "_audio_capture_ref", indexed_reference)
    before = capture.read_routing_profile(reader)
    offset[0] = 17
    after = capture.read_routing_profile(reader)
    assert after["sha256"] == before["sha256"]
    def check_refs(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("ref", "parent_ref", "target_ref") and item is not None:
                    assert set(item) == {"id"}
                check_refs(item)
        elif isinstance(value, list):
            for item in value:
                check_refs(item)
    check_refs(after["profile"])
    child_track.output_routing_type = SimpleNamespace(display_name="Sends Only")
    assert capture.read_routing_profile(reader)["sha256"] != before["sha256"]


def test_profile_pins_applicable_inputs_monitoring_and_audio_port_channels(monkeypatch):
    _, song, reader = profile_fixture(monkeypatch)
    track = song.tracks[0]
    track.input_routing_type = None
    assert any("input_type" in name for name in capture.read_routing_profile(reader)["profile"]["critical_unknown_fields"])
    track.input_routing_type = SimpleNamespace(display_name="Ext. In")
    track.input_routing_channel = None
    # A known empty choice list means the absent channel is structurally N/A.
    assert not capture.read_routing_profile(reader)["profile"]["critical_unknown_fields"]
    track.current_monitoring_state = None
    assert any("monitoring" in name for name in capture.read_routing_profile(reader)["profile"]["critical_unknown_fields"])
    track.current_monitoring_state = 2
    port = SimpleNamespace(routing_type=SimpleNamespace(display_name="Sidechain"), routing_channel=None,
                           available_routing_channels=["1", "2"])
    track.devices[0].audio_inputs = [port]
    assert capture.read_routing_profile(reader)["profile"]["critical_unknown_fields"]
    port.available_routing_channels = []
    track.is_foldable = True
    track.current_monitoring_state = None
    song.return_tracks[0].current_monitoring_state = None
    song.master_track.current_monitoring_state = None
    assert not capture.read_routing_profile(reader)["profile"]["critical_unknown_fields"]


def test_profile_pins_actual_audio_output_capability_as_boolean(monkeypatch):
    _, song, reader = profile_fixture(monkeypatch)
    track = song.tracks[0]
    before = capture.read_routing_profile(reader)
    assert before["profile"]["tracks"][0]["has_audio_output"] is True
    track.has_audio_output = False
    silent = capture.read_routing_profile(reader)
    assert silent["profile"]["tracks"][0]["has_audio_output"] is False
    assert silent["sha256"] != before["sha256"]
    assert not silent["profile"]["critical_unknown_fields"]
    track.has_audio_output = None
    unknown = capture.read_routing_profile(reader)
    assert unknown["profile"]["tracks"][0]["has_audio_output"] is None
    assert any("has_audio_output" in key for key in unknown["profile"]["critical_unknown_fields"])
