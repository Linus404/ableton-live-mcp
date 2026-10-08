"""Isolated file-controlled taps; acknowledgements prove commands, not WAV readiness."""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

from ableton_paths import default_user_library, state_dir
from agent_m4l import build_amxd as build_role_amxd

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_VERSION = "audio-tap-2"


def max_arg(value: Path | str) -> str:
    text = str(value).replace("\\", "/")
    return '"%s"' % text.replace('"', '\\"') if any(char.isspace() for char in text) else text


def patch_text(source: Path, command_file: Path | str, status_file=None, instance_id=None) -> str:
    patch = json.loads(source.read_text(encoding="utf-8"))
    args = [command_file] if instance_id is None else [command_file, status_file, instance_id]
    removed = set()
    for item in patch["patcher"]["boxes"]:
        box = item["box"]
        if box.get("text") == "js agent_audio_tap.js":
            box["text"] += " " + " ".join(max_arg(arg) for arg in args)
        if instance_id is not None:
            if box["id"] in {"obj-udp", "obj-tosymbol", "obj-notein", "obj-stripnote", "obj-midi-select", "obj-midi-start", "obj-midi-stop", "obj-status-send"}:
                removed.add(box["id"])
            if box["id"] == "obj-note":
                box["text"] = "Isolated file control; audio passes through unchanged."
    patch["patcher"]["boxes"] = [item for item in patch["patcher"]["boxes"] if item["box"]["id"] not in removed]
    patch["patcher"]["lines"] = [item for item in patch["patcher"]["lines"] if not ({item["patchline"]["source"][0], item["patchline"]["destination"][0]} & removed)]
    return json.dumps(patch, indent=2)


def build_tap(source: Path, output: Path, command_file: Path | str, status_file=None, instance_id=None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        patched = Path(tmpdir) / source.name
        patched.write_text(patch_text(source, command_file, status_file, instance_id), encoding="utf-8")
        built = Path(tmpdir) / output.name
        build_role_amxd(patched, built, "audio_effect")
        data = built.read_bytes()
        if not output.exists() or output.read_bytes() != data:
            output.write_bytes(data)


def build_instance(instance_id: str) -> dict:
    if not isinstance(instance_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", instance_id):
        raise ValueError("instance_id must contain 1-80 ASCII letters, digits, underscores or hyphens")
    name = "AgentAudioTap_" + instance_id
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    command_file = folder / (name + "_command.json")
    status_file = folder / (name + "_status.json")
    device_path = default_user_library() / "Presets" / "Audio Effects" / "Max Audio Effect" / (name + ".amxd")
    build_tap(ROOT / "m4l" / "AgentAudioTap.maxpat", device_path, command_file, status_file, instance_id)
    companion = device_path.with_name("agent_audio_tap.js")
    source = (ROOT / "m4l" / "agent_audio_tap.js").read_bytes()
    if not companion.exists() or companion.read_bytes() != source:
        companion.write_bytes(source)
    return dict(device_name=name, command_file=str(command_file), status_file=str(status_file), device_path=str(device_path))


def send_command(command_file, status_file, command: str, *, instance_id: str, take_id=None, path=None, max_duration_seconds=None, timeout: float = 5.0) -> dict:
    if command not in {"open", "start", "stop", "status"}:
        raise ValueError("unsupported tap command")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if command == "start":
        if not path or not take_id or max_duration_seconds is None or not math.isfinite(max_duration_seconds) or not 0 < max_duration_seconds <= 86400:
            raise ValueError("start requires path, take_id and max_duration_seconds in (0, 86400]")
    if command == "open" and not path:
        raise ValueError("open requires path")
    if command == "stop" and not take_id:
        raise ValueError("stop requires the owned take_id")
    payload = dict(id=uuid.uuid4().hex, instance_id=instance_id, command=command)
    payload.update({key: value for key, value in dict(take_id=take_id, path=str(path) if path is not None else None, max_duration_seconds=max_duration_seconds).items() if value is not None})
    if command == "start":
        now = time.time() * 1000
        payload.update(expires_at_unix_ms=now + timeout * 1000, stop_at_unix_ms=now + max_duration_seconds * 1000)
    target = Path(command_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + payload["id"] + ".tmp")
    deadline = time.monotonic() + timeout
    replace_deadline = min(deadline, time.monotonic() + 0.5)
    try:
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        while True:
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                remaining = replace_deadline - time.monotonic()
                if remaining <= 0:
                    raise
                # Max can briefly hold the destination open. Retry only before delivery.
                time.sleep(min(0.01, remaining))
    finally:
        temporary.unlink(missing_ok=True)
    while time.monotonic() < deadline:
        try:
            status = json.loads(Path(status_file).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            status = {}
        if status.get("command_id") == payload["id"] and status.get("instance_id") == instance_id:
            return {key: status.get(key) for key in ("command_id", "instance_id", "take_id", "event", "state", "reason", "runtime_version", "path", "command_only", "error")}
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    raise TimeoutError("Tap command acknowledgement timed out: " + payload["id"])
