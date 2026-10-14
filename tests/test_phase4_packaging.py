"""Real distribution and clean installed-runtime checks; no Live connection."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                          check=True, timeout=120).stdout


@pytest.mark.skipif(importlib.util.find_spec("hatchling") is None,
                    reason="Run in an isolated environment with hatchling and pip installed")
def test_real_distributions_and_installed_runtime(tmp_path):
    from in_mix_qualification import code_hashes
    from server import __version__

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    run([sys.executable, "-m", "hatchling", "build", "-t", "wheel", "-t", "sdist",
         "--directory", str(artifacts)], ROOT)
    wheel = next(artifacts.glob("*.whl"))
    sdist = next(artifacts.glob("*.tar.gz"))
    shipped = {p.relative_to(ROOT).as_posix(): p for folder in ("Ableton_Live_MCP", "m4l", "scripts")
               for p in (ROOT / folder).rglob("*") if p.is_file()
               and "__pycache__" not in p.parts and "generated" not in p.parts}
    shipped.update({p.name: p for p in (ROOT / "src").glob("*.py")})
    with zipfile.ZipFile(wheel) as archive:
        for name, source in shipped.items():
            assert archive.read(name) == source.read_bytes(), name
        assert not any("__pycache__" in n or n.endswith(".pyc") for n in archive.namelist())
    source_dir = tmp_path / "source"
    with tarfile.open(sdist) as archive:
        prefix = archive.getnames()[0].split("/")[0]
        for name in ("README.md", "WORKFLOWS.md", "RELEASE_ACCEPTANCE.md", "pyproject.toml"):
            assert archive.extractfile(prefix + "/" + name).read() == (ROOT / name).read_bytes()
        archive.extractall(source_dir, filter="data")
    rebuilt = tmp_path / "rebuilt"
    rebuilt.mkdir()
    run([sys.executable, "-m", "hatchling", "build", "-t", "wheel", "--directory", str(rebuilt)],
        source_dir / prefix)
    with zipfile.ZipFile(next(rebuilt.glob("*.whl"))) as archive:
        for name, source in shipped.items():
            assert archive.read(name) == source.read_bytes(), name

    installation = tmp_path / "installation"
    run([sys.executable, "-m", "venv", "--without-pip", str(installation)], tmp_path)
    python = installation / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run([sys.executable, "-m", "pip", "--python", str(python), "install", "--no-deps",
         "--no-index", str(wheel)], tmp_path)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    probe = run([str(python), "-I", "-c", """
import hashlib, importlib.metadata, json
from pathlib import Path
import agent_m4l, audio_tap, in_mix_qualification, mcp_http, workflows, workflow_history, server
from install_remote_script import remote_script_root
dist = importlib.metadata.distribution('ableton-live-mcp')
root = remote_script_root()
assert agent_m4l.ROOT == audio_tap.ROOT == in_mix_qualification.ROOT == root
assets = ['m4l/agent_m4l_host.js', 'm4l/agent_audio_tap.js', 'm4l/AgentAudioTap.maxpat',
          'm4l/AgentAudioTap.amxd', 'Ableton_Live_MCP/bridge.py']
assert agent_m4l.HOST_JS.is_file()
print(json.dumps({'version': dist.version, 'runtime': server.__version__,
  'origin': str(Path(server.__file__).resolve()), 'hashes': in_mix_qualification.code_hashes(),
  'assets': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in assets},
  'entrypoints': {e.name: e.value for e in dist.entry_points if e.group == 'console_scripts'}}))
"""], tmp_path, env)
    installed = json.loads(probe)
    assert installed["version"] == installed["runtime"] == __version__
    assert Path(installed["origin"]).is_relative_to(installation)
    assert installed["hashes"] == code_hashes()
    for name, digest in installed["assets"].items():
        assert digest == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    assert installed["entrypoints"] == {
        "ableton-live-mcp": "server:main", "ableton-live-mcp-validate": "validate:main",
        "ableton-live-mcp-install-remote-script": "install_remote_script:main",
        "ableton-live-mcp-build-m4l-device": "agent_m4l:main",
        "ableton-live-mcp-sync-m4l-host": "agent_m4l:sync_host_main",
        "ableton-live-mcp-capture-window": "visual_capture:main"}
    for name in installed["entrypoints"]:
        cli = installation / ("Scripts" if os.name == "nt" else "bin") / (name + (".exe" if os.name == "nt" else ""))
        assert "usage:" in run([str(cli), "--help"], tmp_path, env).lower()
    cli = installation / ("Scripts/ableton-live-mcp.exe" if os.name == "nt" else "bin/ableton-live-mcp")
    assert __version__ in run([str(cli), "--version"], tmp_path, env)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "", "capabilities": {}, "clientInfo": {"name": "installed-acceptance", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "live_workflow", "arguments": {"mode": "apply", "operations": [{
                "op": "clip.notes.transform", "target": {"kind": "clip", "id": 123, "parent_id": 124, "slot_index": 0}, "transpose": 1}]}}},
    ]

    def check_responses(responses, version):
        initialized, discovery, refused = responses
        assert initialized["result"]["protocolVersion"] == version
        identity = initialized["result"]["_meta"]["ableton-live-mcp/identity"]
        assert identity["version"] == __version__
        assert Path(identity["executable"]).is_relative_to(installation)
        assert all(Path(p).is_relative_to(installation) for p in identity["modules"])
        tools = discovery["result"]["tools"]
        workflow = next(t for t in tools if t["name"] == "live_workflow")
        schema = json.dumps(workflow["inputSchema"])
        assert all(key in schema for key in ("clip.notes.transform", "transpose", "velocity_delta", "note_ids", "expected_notes_digest"))
        assert "expected_notes_digest" in json.dumps(refused)
        assert refused.get("error") or refused.get("result", {}).get("isError")
        return {"protocol": version, "identity": identity, "tools": len(tools),
                "discovery_bytes": len(json.dumps(discovery["result"], separators=(",", ":")).encode()),
                "workflow_schema_bytes": len(json.dumps(workflow["inputSchema"], separators=(",", ":")).encode())}

    evidence = {"stdio": [], "http": []}
    for version in ("2024-11-05", "2025-03-26", "2025-06-18"):
        messages[0]["params"]["protocolVersion"] = version
        process = subprocess.Popen([str(cli)], cwd=tmp_path, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            stdout, stderr = process.communicate("".join(json.dumps(m) + "\n" for m in messages), timeout=30)
            assert process.returncode == 0, stderr
            evidence["stdio"].append(check_responses([json.loads(line) for line in stdout.splitlines()], version))
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
    http_probe = run([str(python), "-I", "-c", """
import http.client, json, threading
from server import make_server
from mcp_http import StreamableHttpServer
class DenyBridge:
    def request(self, *args, **kwargs):
        raise AssertionError('Live bridge must never be called')
listener = StreamableHttpServer(make_server(DenyBridge()), port=0)
thread = threading.Thread(target=listener.serve_forever)
thread.start()
results = []
def post(message, version, sid=None):
    connection = http.client.HTTPConnection('127.0.0.1', listener.server_port, timeout=10)
    headers = {'Content-Type':'application/json', 'Accept':'application/json, text/event-stream', 'MCP-Protocol-Version':version}
    if sid: headers['MCP-Session-Id'] = sid
    connection.request('POST', '/mcp', json.dumps(message), headers)
    response = connection.getresponse()
    status, session, body = response.status, response.getheader('MCP-Session-Id'), response.read()
    connection.close()
    assert status in (200, 202)
    return session, json.loads(body) if body else None
try:
    for version in ('2025-03-26','2025-06-18'):
        messages = json.loads(__import__('sys').argv[1])
        messages[0]['params']['protocolVersion'] = version
        sid, initialized = post(messages[0], version)
        post(messages[1], version, sid)
        discovery = post(messages[2], version, sid)[1]
        refused = post(messages[3], version, sid)[1]
        results.append([version, [initialized, discovery, refused]])
        connection = http.client.HTTPConnection('127.0.0.1', listener.server_port, timeout=10)
        connection.request('DELETE', '/mcp', headers={'MCP-Session-Id':sid, 'MCP-Protocol-Version':version})
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        connection.close()
finally:
    listener.shutdown()
    thread.join(timeout=10)
    listener.server_close()
    assert not thread.is_alive()
print(json.dumps(results))
""", json.dumps(messages)], tmp_path, env)
    for version, responses in json.loads(http_probe):
        evidence["http"].append(check_responses(responses, version))
    (tmp_path / "installed-client-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
