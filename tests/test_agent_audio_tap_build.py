from __future__ import annotations

import json
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

import audio_tap


def load_builder():
    path = Path("scripts/build_agent_audio_tap.py")
    spec = importlib.util.spec_from_file_location("build_agent_audio_tap", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_agent_audio_tap_sources_are_valid_json():
    patch = json.loads(Path("m4l/AgentAudioTap.maxpat").read_text(encoding="utf-8"))
    boxes = patch["patcher"]["boxes"]
    texts = {box["box"].get("text") for box in boxes}
    assert "sfrecord~ 2" in texts
    assert "js agent_audio_tap.js" in texts
    assert "notein" in texts


def test_agent_audio_tap_builds_amxd_container(tmp_path):
    builder = load_builder()
    output = tmp_path / "AgentAudioTap.amxd"
    command_file = tmp_path / "agent_audio_tap_command.json"
    builder.build_amxd(Path("m4l/AgentAudioTap.maxpat"), output, command_file)
    data = output.read_bytes()
    original_mtime = output.stat().st_mtime_ns
    builder.build_amxd(Path("m4l/AgentAudioTap.maxpat"), output, command_file)
    assert output.stat().st_mtime_ns == original_mtime
    assert data.startswith(b"ampf\x04\x00\x00\x00aaaameta")
    assert b"Agent Audio Tap" in data
    assert b"sfrecord~ 2" in data
    patch = json.loads(data[data.index(b'{'):].rstrip(b'\x00'))
    assert any(builder.max_arg(command_file) in item["box"].get("text", "") for item in patch["patcher"]["boxes"])


def test_agent_audio_tap_js_has_cross_platform_command_file_default():
    source = Path("m4l/agent_audio_tap.js").read_text(encoding="utf-8")
    assert "jsarguments" in source
    assert "scheduleStartRecording" in source
    assert "startTask.schedule(500)" in source
    assert "/tmp/agent_audio_tap_command.json" not in source


def test_isolated_instances_have_distinct_files_and_no_incidental_triggers(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_tap, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(audio_tap, "default_user_library", lambda: tmp_path / "library")
    patches = []
    def build(source, output, role):
        patches.append(json.loads(source.read_text(encoding="utf-8")))
        output.write_bytes(b"test wrapper")
        assert role == "audio_effect"
    monkeypatch.setattr(audio_tap, "build_role_amxd", build)
    one = audio_tap.build_instance("one")
    companion = Path(one["device_path"]).with_name("agent_audio_tap.js")
    original_mtime = companion.stat().st_mtime_ns
    two = audio_tap.build_instance("two")
    assert companion.stat().st_mtime_ns == original_mtime
    assert all(one[key] != two[key] for key in one)
    for patch, info, instance in zip(patches, [one, two], ["one", "two"]):
        boxes = {item["box"]["id"]: item["box"] for item in patch["patcher"]["boxes"]}
        texts = [box.get("text", "") for box in boxes.values()]
        assert not any("udpreceive" in text or "notein" == text or "sel 60 61" == text for text in texts)
        assert "obj-status-send" not in boxes
        assert boxes["obj-js"]["text"].endswith(" " + instance)
        assert audio_tap.max_arg(info["command_file"]) in boxes["obj-js"]["text"]
        assert audio_tap.max_arg(info["status_file"]) in boxes["obj-js"]["text"]
        assert sum(line["patchline"]["destination"][0] == "obj-plugout" for line in patch["patcher"]["lines"]) == 2
    with pytest.raises(ValueError):
        audio_tap.build_instance("../bad")


def test_send_command_waits_for_matching_ack(tmp_path, monkeypatch):
    command = tmp_path / "command.json"
    status = tmp_path / "status.json"
    status.write_text(json.dumps(dict(command_id="old", instance_id="one")))
    sleeps = []
    def acknowledge(delay):
        sleeps.append(delay)
        payload = json.loads(command.read_text())
        status.write_text(json.dumps(dict(command_id=payload["id"], instance_id="one", event="start", state="starting", command_only=True)))
    monkeypatch.setattr(audio_tap.time, "sleep", acknowledge)
    result = audio_tap.send_command(command, status, "start", instance_id="one", take_id="take", path=tmp_path / "take.wav", max_duration_seconds=1)
    assert sleeps and result["state"] == "starting" and result["command_only"] is True
    assert result["command_id"] == json.loads(command.read_text())["id"]
    with pytest.raises(ValueError):
        audio_tap.send_command(command, status, "start", instance_id="one", path="a.wav", take_id="take", max_duration_seconds=float("inf"))


def test_js_isolated_lifecycle():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the mocked Max JS lifecycle check")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('m4l/agent_audio_tap.js', 'utf8');
function host(id) {
  const files = {}, outputs = [], tasks = [];
  const context = {
    jsarguments: ['agent_audio_tap.js', id+'_command', id+'_status', id],
    outlet: (...args) => outputs.push(args),
    Task: function(fn) { this.fn=fn; this.cancelled=false; tasks.push(this);
      this.schedule=(ms)=>{this.ms=ms; this.cancelled=false;};
      this.cancel=()=>{this.cancelled=true;}; this.repeat=()=>{}; },
    File: function(path, mode) { this.isopen=mode==='write'||path in files;
      this.readstring=()=>files[path]; this.writestring=(text)=>{files[path]=text;}; this.close=()=>{}; }
  };
  vm.createContext(context); vm.runInContext(source, context);
  return {context, outputs, tasks, files, ack:()=>JSON.parse(files[id+'_status']),
    send:(cmd)=>{files[id+'_command']=JSON.stringify(cmd); context.pollCommandFile();}};
}
const a=host('one'), b=host('two');
const start={id:'start-a',instance_id:'one',take_id:'take',command:'start',path:'a.wav',max_duration_seconds:2,
  expires_at_unix_ms:Date.now()+1000,stop_at_unix_ms:Date.now()+1900};
a.send(start); b.send(start);
assert.equal(a.ack().state,'starting'); assert.equal(a.ack().event,'start');
assert.equal(a.ack().command_only,true); assert(!b.outputs.some(o=>o[0]===0&&o[1]!==0));
a.send({id:'unowned-stop',instance_id:'one',command:'stop'});
assert.equal(a.ack().error,'take_mismatch'); assert.equal(a.context.state,'starting');
a.send({id:'stop-a',instance_id:'one',take_id:'take',command:'stop'});
assert.equal(a.ack().command_id,'stop-a'); assert.equal(a.ack().state,'stopped');
assert(a.tasks.every(t=>t.cancelled));
assert(!a.outputs.some(o=>o[0]===0&&o[1]===1));
a.send({...start,id:'start-b'});
a.send({id:'snapshot',instance_id:'one',command:'status'});
a.context.startTask.fn(); assert.equal(a.context.state,'recording'); assert.equal(a.ack().command_id,'snapshot');
a.context.stopTask.fn(); assert.equal(a.context.state,'stopped'); assert.equal(a.ack().command_id,'snapshot');
a.send({id:'after-bound',instance_id:'one',command:'status'});
assert.equal(a.ack().state,'stopped'); assert.equal(a.ack().reason,'max_duration');
a.send({...start,id:'invalid',max_duration_seconds:0});
assert.equal(a.ack().event,'error');
a.send({...start,id:'expired',expires_at_unix_ms:Date.now()-1});
assert.equal(a.ack().error,'expired_or_invalid_start');
a.files.one_command=JSON.stringify({...start,id:'stale'});
vm.runInContext(source,a.context); a.context.pollCommandFile();
assert.equal(a.context.lastCommandId,'stale'); assert.equal(a.context.state,'idle');
console.log('isolated lifecycle OK');
'''
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


def test_command_replace_retries_only_before_delivery(tmp_path, monkeypatch):
    command = tmp_path / "command.json"
    status = tmp_path / "status.json"
    replace = audio_tap.os.replace
    attempted = []
    clock = [0.0]
    monkeypatch.setattr(audio_tap.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(audio_tap.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    def initially_busy(source, target):
        payload = json.loads(source.read_text())
        attempted.append(payload)
        if len(attempted) == 1:
            raise PermissionError("recorder has file open")
        replace(source, target)
        status.write_text(json.dumps(dict(command_id=payload["id"], instance_id="one", event="status")))
    monkeypatch.setattr(audio_tap.os, "replace", initially_busy)
    result = audio_tap.send_command(command, status, "status", instance_id="one", timeout=1)
    assert result["command_id"] == attempted[0]["id"]
    assert len(attempted) == 2 and attempted[0] == attempted[1]
    assert not list(tmp_path.glob("*.tmp"))
    def permanently_busy(source, target):
        raise PermissionError("locked")
    monkeypatch.setattr(audio_tap.os, "replace", permanently_busy)
    before = clock[0]
    with pytest.raises(PermissionError):
        audio_tap.send_command(command, status, "status", instance_id="one", timeout=1)
    assert 0.49 <= clock[0] - before <= 0.51
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads(command.read_text())["id"] == result["command_id"]
