import json
import struct
from pathlib import Path

import pytest

import audio_capture
import audio_tap
from server import make_server


def wav(path, code=3):
    fmt = struct.pack("<HHIIHH", code, 2, 48000, 384000, 8, 32)
    body = b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", 16) + b"\0" * 16
    Path(path).write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)


class Bridge:
    def __init__(self):
        self.calls = []
        self.transport = dict(playing=False, time=0, tempo=120, loop=True, record_mode=False,
                              session_record=False, arrangement_overdub=False,
                              session_automation_record=False, back_to_arranger=False)
        self.polls = [dict(playing=True, time=1, tempo=80), dict(playing=True, time=2, tempo=160)]
        self.tracks = [dict(name="Audio", ref={"id": 2, "path": "live_set tracks 0"}, kind="track", has_audio_output=True, is_frozen=False),
                       dict(name="Frozen", ref={"id": 3}, kind="track", has_audio_output=True, is_frozen=True)]
        self.fail_play = False

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "audio_capture_snapshot":
            if params.get("track_refs") == []:
                return {"transport": self.polls.pop(0)}
            return {"transport": dict(self.transport), "tracks": self.tracks,
                    "song_ref": {"id": 1}, "selected_track": {"id": 2}}
        if method == "agent_audio_tap_setup":
            return {"ok": True, "end_verified": True}
        if method == "transport" and self.fail_play:
            raise TimeoutError("sent timeout")
        if method == "audio_capture_restore":
            return {"playing": False, "restored": True}
        return {"prepared": True}


@pytest.fixture
def capture_env(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_capture, "_require_runtime", lambda bridge: {"runtime_current": True, "live_mutations_safe": True})
    monkeypatch.setattr(audio_capture.time, "sleep", lambda _: None)
    monkeypatch.setattr(audio_capture, "_completed_wav", audio_capture.validate_wav)
    monkeypatch.setattr(audio_tap, "build_instance", lambda instance: dict(device_name=instance, command_file="command", status_file="status", device_path="device"))
    commands = []
    paths = {}
    states = {}

    def command(command_file, status_file, action, **kw):
        commands.append((action, kw))
        instance = kw["instance_id"]
        if action == "start":
            paths[instance] = kw["path"]
            wav(kw["path"])
            states[instance] = "recording"
        if action == "stop":
            states[instance] = "stopped"
        return dict(runtime_version=audio_tap.RUNTIME_VERSION, event=action,
                    command_only=True, take_id=kw.get("take_id"), path=paths.get(instance),
                    state=states.get(instance, "idle"))

    monkeypatch.setattr(audio_tap, "send_command", command)
    return dict(start_beat=0, length_beats=2, output_directory=str(tmp_path)), commands


def test_capture_sequential_completion_and_manifest(capture_env):
    args, commands = capture_env
    bridge = Bridge()
    result = audio_capture.capture_audio(bridge, args)
    assert result["complete"] and result["transport_stopped"]
    assert [action for action, _ in commands] == ["status", "start", "status", "stop"]
    assert result["tracks"][1]["reason"] == "frozen"
    methods = [method for method, _ in bridge.calls]
    assert methods.index("audio_capture_prepare") < methods.index("agent_audio_tap_setup") < methods.index("transport")
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["raw_untrimmed"] and not manifest["sample_aligned"]
    assert manifest["sample_uncertainty"] is None
    assert len(manifest["observations"]) == 2
    assert "command-only" in manifest["readiness"]


def test_sent_timeout_stops_locally_without_live_retry(capture_env):
    args, commands = capture_env
    bridge = Bridge()
    bridge.fail_play = True
    result = audio_capture.capture_audio(bridge, args)
    assert not result["complete"]
    assert [action for action, _ in commands][-1] == "stop"
    assert [method for method, _ in bridge.calls].count("transport") == 1
    assert not any(method == "audio_capture_restore" for method, _ in bridge.calls)
    assert Path(result["manifest_path"]).exists()


def test_premature_stop_and_jump_are_incomplete(capture_env):
    args, commands = capture_env
    for polls in ([dict(playing=False, time=1, tempo=120)],
                  [dict(playing=True, time=100, tempo=120), dict(playing=True, time=0, tempo=120)]):
        bridge = Bridge()
        bridge.polls = polls
        result = audio_capture.capture_audio(bridge, {**args, "length_beats": 200})
        assert not result["complete"] and result["error"]
        assert commands[-1][0] == "stop"


def test_deadline_and_local_recorder_bound(capture_env, monkeypatch):
    args, commands = capture_env
    ticks = iter(i / 10 for i in range(1000))
    monkeypatch.setattr(audio_capture.time, "monotonic", lambda: next(ticks))
    bridge = Bridge()
    bridge.polls = [dict(playing=True, time=0.1, tempo=120)] * 20
    result = audio_capture.capture_audio(bridge, {**args, "max_duration_seconds": 1})
    assert not result["complete"] and "deadline" in result["error"]
    starts = [kw for action, kw in commands if action == "start"]
    assert starts and 0 < starts[0]["max_duration_seconds"] <= 1
    assert commands[-1][0] == "stop"


def test_all_unknown_or_frozen_have_explicit_outcomes(capture_env):
    args, commands = capture_env
    bridge = Bridge()
    bridge.tracks[0]["is_frozen"] = None
    result = audio_capture.capture_audio(bridge, args)
    assert not result["complete"] and not commands
    assert [item["reason"] for item in result["tracks"]] == ["unknown_capability", "frozen"]
    assert all(item["outcome"] == "unsupported" for item in result["tracks"])
    assert not any(method == "audio_capture_prepare" for method, _ in bridge.calls)


def test_ack_error_cannot_be_success(capture_env, monkeypatch):
    args, commands = capture_env
    original = audio_tap.send_command

    def command(*positional, **kwargs):
        ack = original(*positional, **kwargs)
        if positional[2] == "stop":
            ack["error"] = "wrong_take"
        return ack

    monkeypatch.setattr(audio_tap, "send_command", command)
    result = audio_capture.capture_audio(Bridge(), args)
    assert not result["complete"] and result["tracks"][0]["outcome"] == "incomplete"


def test_gross_truncation_remains_incomplete(capture_env, monkeypatch):
    args, _ = capture_env
    ticks = iter(range(1000))
    monkeypatch.setattr(audio_capture.time, "monotonic", lambda: next(ticks))
    result = audio_capture.capture_audio(Bridge(), args)
    assert not result["complete"]
    assert "grossly shorter" in result["tracks"][0]["error"]
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["tracks"][0]["duration_sanity"]["minimum_seconds"] > 1


def test_every_recorder_stopped_before_wav_wait(capture_env, monkeypatch):
    args, commands = capture_env
    bridge = Bridge()
    bridge.tracks[1]["is_frozen"] = False
    original = audio_capture._completed_wav

    def completed(path):
        assert sum(action == "stop" for action, _ in commands) == 2
        return original(path)

    monkeypatch.setattr(audio_capture, "_completed_wav", completed)
    result = audio_capture.capture_audio(bridge, args)
    assert result["complete"]


def test_reordering_track_path_reuses_same_tap(capture_env):
    args, commands = capture_env
    bridge = Bridge()
    assert audio_capture.capture_audio(bridge, args)["complete"]
    first = [kw["instance_id"] for action, kw in commands if action == "start"][-1]
    bridge = Bridge()
    bridge.tracks[0]["ref"]["path"] = "live_set tracks 9"
    assert audio_capture.capture_audio(bridge, args)["complete"]
    second = [kw["instance_id"] for action, kw in commands if action == "start"][-1]
    assert first == second


def test_existing_playback_is_stopped_before_loading(capture_env):
    args, _ = capture_env
    bridge = Bridge()
    bridge.transport["playing"] = True
    result = audio_capture.capture_audio(bridge, args)
    assert result["complete"]
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["prior_transport"]["playing"] is True


def test_accepted_stop_lag_waits_readonly_before_completing_phase(capture_env):
    args, _ = capture_env

    class LagBridge(Bridge):
        def __init__(self):
            super().__init__()
            self.pending = None
            self.pending_polls = 0
            self.phases = {}

        def request(self, method, params):
            if method in ("audio_capture_prepare", "audio_capture_restore"):
                self.calls.append((method, params))
                result_key = "prepared" if method.endswith("prepare") else "restored"
                self.phases[method] = self.phases.get(method, 0) + 1
                if self.phases[method] == 1:
                    self.pending = method
                    self.pending_polls = 0
                    return {result_key: False, "settled": False, "pending": "transport_stop", "playing": True}
                assert self.pending_polls == 2
                self.pending = None
                return {result_key: True, "settled": True, "playing": False}
            if method == "audio_capture_snapshot" and self.pending:
                self.calls.append((method, params))
                assert params["track_refs"] == []
                self.pending_polls += 1
                return {"transport": {"playing": self.pending_polls == 1, "time": 0, "tempo": 120}}
            return super().request(method, params)

    bridge = LagBridge()
    result = audio_capture.capture_audio(bridge, args)
    assert result["complete"] and result["transport_stopped"]
    assert bridge.phases == {"audio_capture_prepare": 2, "audio_capture_restore": 2}
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert [item["phase"] for item in manifest["observations"] if "phase" in item] == ["prepared", "prepared", "restored", "restored"]


def test_loaded_runtime_fingerprint_required(monkeypatch):
    import install_remote_script
    monkeypatch.setattr(install_remote_script, "remote_script_status", lambda: dict(current=True, target="installed", source_bridge_sha256="expected", source_runtime_version="v1", source_runtime_code_sha256="expected-code"))

    class RuntimeBridge:
        def request(self, method, params):
            if method == "exec":
                return {"runtime_code_sha256": "expected-code"}
            return {"remote_script": dict(runtime_version="v1", runtime_code_sha256="old-code", bridge_sha256="expected")}

    with pytest.raises(RuntimeError, match="runtime_code_hash_mismatch"):
        audio_capture._require_runtime(RuntimeBridge())


@pytest.mark.parametrize("mode", ["record_mode", "session_record", "arrangement_overdub", "session_automation_record", "back_to_arranger"])
def test_ownership_guard_before_mutation(capture_env, mode):
    args, commands = capture_env
    bridge = Bridge()
    bridge.transport[mode] = True
    with pytest.raises(RuntimeError, match="recording"):
        audio_capture.capture_audio(bridge, args)
    assert not commands and len(bridge.calls) == 1


@pytest.mark.parametrize("args", [dict(start_beat=float("nan"), length_beats=1), dict(start_beat=0, length_beats=0), dict(start_beat=0, length_beats=1, precision="sample_aligned")])
def test_invalid_inputs_before_live(args):
    bridge = Bridge()
    with pytest.raises(ValueError):
        audio_capture.capture_audio(bridge, args)
    assert not bridge.calls


@pytest.mark.parametrize("code", [1, 3])
def test_riff_pcm_and_float(tmp_path, code):
    path = tmp_path / "capture.wav"
    wav(path, code)
    assert audio_capture.validate_wav(path)["frames"] == 2
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError):
        audio_capture.validate_wav(path)


def test_server_registration():
    tool = make_server(Bridge()).tools["live_audio_capture"].as_mcp()
    assert tool["inputSchema"]["type"] == "object"
    assert "AGENTS.md" in tool["description"]
