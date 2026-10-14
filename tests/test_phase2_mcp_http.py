"""Real loopback HTTP and fresh stdio processes, with no Live connection."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
BOOT = '''
import json, sys, time
from server import make_server
from mcp_stdio import Tool
from mcp_http import StreamableHttpServer
class FakeBridge:
    def request(self, method, args):
        return {"method": method, "arguments": args, "name": "Grüße"}
registry = make_server(FakeBridge())
active = completed = 0
def slow(args):
    global active, completed
    active += 1
    concurrency = active
    time.sleep(args.get("seconds", .4))
    active -= 1
    completed += 1
    return {"ok":True,"settled":True,"concurrency":concurrency}
registry.add_tool(Tool("slow", "Blocking fake tool", {"type":"object"}, slow))
registry.add_tool(Tool("count", "Completed fake operations", {"type":"object"}, lambda args: {"completed":completed}))
if sys.argv[1] == "stdio":
    registry.serve()
else:
    with StreamableHttpServer(registry, port=0) as http:
        print(http.server_port, flush=True)
        http.serve_forever()
'''


def start(mode):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    return subprocess.Popen([sys.executable, "-u", "-c", BOOT, mode], cwd=ROOT, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8")


@pytest.fixture
def endpoint():
    process = start("http")
    try:
        line = process.stdout.readline()
        assert line, process.stderr.read() if process.poll() is not None else "HTTP failed to start"
        yield int(line)
    finally:
        process.terminate()
        process.wait(timeout=5)


def post(port, message, sid=None, version="2025-06-18", **headers):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    common = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
              "MCP-Protocol-Version": version}
    if sid:
        common["MCP-Session-Id"] = sid
    common.update(headers)
    connection.request("POST", "/mcp", json.dumps(message, ensure_ascii=False).encode("utf-8"), common)
    response = connection.getresponse()
    body = response.read().decode("utf-8")
    result = (response.status, dict(response.getheaders()), body)
    connection.close()
    return result


def initialize(port, version="2025-06-18"):
    status, headers, body = post(port, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "local-test", "version": "1"}}}, version=version)
    assert status == 200
    result = json.loads(body)["result"]
    assert result["protocolVersion"] == version
    assert result["_meta"]["ableton-live-mcp/identity"]["executable"]
    sid = headers["MCP-Session-Id"]
    assert post(port, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid, version)[0] == 202
    return sid


@pytest.mark.parametrize("version", ["2025-03-26", "2025-06-18"])
def test_http_handshake_utf8_and_lifecycle(endpoint, version):
    sid = initialize(endpoint, version)
    status, _, body = post(endpoint, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "live_ping", "arguments": {}}}, sid, version)
    assert status == 200
    payload = json.loads(body)["result"]
    assert json.loads(payload["content"][0]["text"])["name"] == "Grüße"
    assert ("structuredContent" in payload) == (version == "2025-06-18")
    assert post(endpoint, {"jsonrpc": "2.0", "id": 3, "method": "ping"}, sid, "2024-11-05")[0] == 400
    assert post(endpoint, {"jsonrpc": "2.0", "id": 3, "method": "ping"}, "unknown", version)[0] == 404
    connection = http.client.HTTPConnection("127.0.0.1", endpoint)
    connection.request("GET", "/mcp")
    assert connection.getresponse().status == 405
    connection.close()
    connection = http.client.HTTPConnection("127.0.0.1", endpoint)
    connection.request("DELETE", "/mcp", headers={"MCP-Session-Id": sid, "MCP-Protocol-Version": "2025-06-18" if version == "2025-03-26" else "2025-03-26"})
    assert connection.getresponse().status == 400
    connection.close()
    connection = http.client.HTTPConnection("127.0.0.1", endpoint)
    connection.request("DELETE", "/mcp", headers={"MCP-Session-Id": sid, "MCP-Protocol-Version": version})
    assert connection.getresponse().status == 200
    connection.close()
    assert post(endpoint, {"jsonrpc": "2.0", "id": 4, "method": "ping"}, sid, version)[0] == 404


def test_http_rejects_untrusted_headers_before_dispatch(endpoint):
    message = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    for headers, status in [({"Origin": "https://evil.example"}, 403), ({"Host": "evil.example"}, 403),
                            ({"Accept": "application/json,text/event-stream;q=0"}, 406),
                            ({"Content-Type": "application/json;charset=latin1"}, 415)]:
        assert post(endpoint, message, **headers)[0] == status
    assert post(endpoint, message)[0] == 400
    assert post(endpoint, [], version="2025-06-18")[0] == 400
    connection = http.client.HTTPConnection("127.0.0.1", endpoint)
    connection.request("POST", "/mcp", json.dumps(message).encode("utf-16"), {
        "Content-Type": "application/json", "Accept": "application/json,text/event-stream"})
    response = connection.getresponse()
    assert response.status == 400 and json.loads(response.read())["error"]["code"] == -32700
    connection.close()


def test_http_march_batch_and_june_rejection(endpoint):
    batch = [{"jsonrpc": "2.0", "id": n, "method": "ping"} for n in (10, 11)]
    sid = initialize(endpoint, "2025-03-26")
    status, _, body = post(endpoint, batch, sid, "2025-03-26")
    assert status == 200 and {m["id"] for m in json.loads(body)} == {10, 11}
    june = initialize(endpoint)
    assert post(endpoint, batch, june)[0] == 400


def test_http_progress_cancel_control_remains_responsive(endpoint):
    sid = initialize(endpoint)
    connection = http.client.HTTPConnection("127.0.0.1", endpoint, timeout=5)
    message = {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
        "name": "slow", "arguments": {}, "_meta": {"progressToken": "p"}}}
    connection.request("POST", "/mcp", json.dumps(message), {
        "Content-Type": "application/json", "Accept": "application/json,text/event-stream",
        "MCP-Session-Id": sid, "MCP-Protocol-Version": "2025-06-18"})
    response = connection.getresponse()
    assert response.status == 200 and response.getheader("Content-Type") == "text/event-stream"
    first = []
    while True:
        line = response.readline().decode()
        first.append(line)
        if line == "\n":
            break
    assert "Tool execution started" in "".join(first)
    began = time.monotonic()
    assert post(endpoint, {"jsonrpc": "2.0", "id": 5, "result": {"unsolicited": True}}, sid)[0] == 202
    assert post(endpoint, {"jsonrpc": "2.0", "id": 5, "error": {"code": "invalid"}}, sid)[0] == 400
    assert post(endpoint, {"jsonrpc": "2.0", "id": 6, "method": "ping"}, sid)[0] == 200
    assert post(endpoint, {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 5}}, sid)[0] == 202
    assert time.monotonic() - began < .35
    remaining = response.read().decode()
    events = [json.loads(line[6:]) for line in remaining.splitlines() if line.startswith("data: ")]
    final = next(e for e in events if e.get("id") == 5)
    assert final["result"]["structuredContent"]["settled"] is True
    connection.close()


def test_fresh_stdio_process_and_offline_identity():
    process = start("stdio")
    try:
        def exchange(message, response=True):
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            process.stdin.flush()
            return json.loads(process.stdout.readline()) if response else None
        result = exchange({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
        identity = result["result"]["_meta"]["ableton-live-mcp/identity"]
        exchange({"jsonrpc": "2.0", "method": "notifications/initialized"}, False)
        answer = exchange({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "live_ping", "arguments": {}}})
        assert answer["result"]["structuredContent"]["name"] == "Grüße"
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        check = subprocess.run([sys.executable, "-m", "server", "--version"], env=env, cwd=ROOT,
                               capture_output=True, text=True, encoding="utf-8", timeout=10, check=True)
        assert json.loads(check.stdout) == identity
    finally:
        process.stdin.close()
        process.wait(timeout=5)


def test_http_multi_session_serializes_handlers(endpoint):
    first, second = initialize(endpoint), initialize(endpoint)
    responses = []
    def run(sid):
        _, _, body = post(endpoint, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "slow", "arguments": {}}}, sid)
        responses.append(json.loads(body)["result"]["structuredContent"])
    threads = [threading.Thread(target=run, args=(sid,)) for sid in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert len(responses) == 2 and all(item["concurrency"] == 1 for item in responses)


def test_http_disconnect_does_not_replay_or_abandon(endpoint):
    sid = initialize(endpoint)
    connection = http.client.HTTPConnection("127.0.0.1", endpoint, timeout=5)
    connection.request("POST", "/mcp", json.dumps({"jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": "slow", "arguments": {}, "_meta": {"progressToken": "disconnect"}}}), {
            "Content-Type": "application/json", "Accept": "application/json,text/event-stream",
            "MCP-Session-Id": sid, "MCP-Protocol-Version": "2025-06-18"})
    response = connection.getresponse()
    assert response.status == 200
    while response.readline() != b"\n":
        pass
    response.close()
    connection.close()
    _, _, body = post(endpoint, {"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {
        "name": "count", "arguments": {}}}, sid)
    assert json.loads(body)["result"]["structuredContent"]["completed"] == 1


@pytest.mark.parametrize("batch", [False, True])
def test_queued_cancellation_closes_http_and_batch_without_execution(endpoint, batch):
    version = "2025-03-26" if batch else "2025-06-18"
    first, queued = initialize(endpoint, version), initialize(endpoint, version)
    connection = http.client.HTTPConnection("127.0.0.1", endpoint, timeout=5)
    connection.request("POST", "/mcp", json.dumps({"jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": "slow", "arguments": {"seconds": 1}, "_meta": {"progressToken": "hold"}}}), {
            "Content-Type": "application/json", "Accept": "application/json,text/event-stream",
            "MCP-Session-Id": first, "MCP-Protocol-Version": version})
    response = connection.getresponse()
    while response.readline() != b"\n":
        pass
    message = {"jsonrpc": "2.0", "id": 20, "method": "tools/call", "params": {"name": "slow", "arguments": {}}}
    cancellation = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 20}}
    if batch:
        request = [message, cancellation, {"jsonrpc": "2.0", "id": 21, "method": "ping"}]
        status, _, body = post(endpoint, request, queued, version)
        assert status == 200 and [e["id"] for e in json.loads(body)] == [21]
    else:
        message["params"]["_meta"] = {"progressToken": "queued"}
        waiting = http.client.HTTPConnection("127.0.0.1", endpoint, timeout=5)
        waiting.request("POST", "/mcp", json.dumps(message), {
            "Content-Type": "application/json", "Accept": "application/json,text/event-stream",
            "MCP-Session-Id": queued, "MCP-Protocol-Version": version})
        queued_response = waiting.getresponse()
        assert queued_response.status == 200
        assert post(endpoint, cancellation, queued, version)[0] == 202
        assert queued_response.read() == b""
        waiting.close()
    response.read()
    connection.close()
    _, _, body = post(endpoint, {"jsonrpc": "2.0", "id": 30, "method": "tools/call", "params": {"name": "count", "arguments": {}}}, first, version)
    assert json.loads(json.loads(body)["result"]["content"][0]["text"])["completed"] == 1


@pytest.mark.skipif(importlib.util.find_spec("hatchling") is None, reason="Package build backend is not installed in this interpreter")
def test_package_metadata_uses_runtime_version(tmp_path):
    from email.parser import Parser
    from server import __version__
    assert tmp_path.is_dir()
    result = subprocess.run([sys.executable, "-c", "from hatchling.build import prepare_metadata_for_build_wheel; import sys; print(prepare_metadata_for_build_wheel(sys.argv[1]))", str(tmp_path)],
                            cwd=ROOT, capture_output=True, text=True, timeout=30, check=True)
    metadata = Parser().parsestr((tmp_path / result.stdout.strip() / "METADATA").read_text(encoding="utf-8"))
    assert metadata["Version"] == __version__


@pytest.mark.parametrize("delete", [False, True])
def test_graceful_http_shutdown_waits_for_accepted_tool_cleanup(delete):
    from mcp_http import StreamableHttpServer
    from mcp_stdio import Tool
    from server import make_server
    entered, release, cleaned, closed = (threading.Event() for _ in range(4))
    def block(args):
        entered.set()
        try:
            assert release.wait(timeout=5)
            return {"settled": True}
        finally:
            cleaned.set()
    registry = make_server(object())  # No fake or actual bridge method is invoked.
    registry.add_tool(Tool("block_shutdown", "Shutdown ownership probe", {"type": "object"}, block))
    listener = StreamableHttpServer(registry, port=0)
    serving = threading.Thread(target=listener.serve_forever, daemon=True)
    serving.start()
    answers = []
    try:
        sid = initialize(listener.server_port)
        client = threading.Thread(target=lambda: answers.append(post(listener.server_port, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "block_shutdown", "arguments": {}}}, sid)))
        client.start()
        assert entered.wait(timeout=2)
        if delete:
            deletion = http.client.HTTPConnection("127.0.0.1", listener.server_port)
            deletion.request("DELETE", "/mcp", headers={"MCP-Session-Id": sid, "MCP-Protocol-Version": "2025-06-18"})
            assert deletion.getresponse().status == 200
            deletion.close()
        listener.shutdown()
        closing = threading.Thread(target=lambda: (listener.server_close(), closed.set()))
        closing.start()
        assert not closed.wait(timeout=.05)
        release.set()
        closing.join(timeout=3)
        client.join(timeout=3)
        assert closed.is_set() and cleaned.is_set()
        assert json.loads(answers[0][2])["result"]["structuredContent"]["settled"] is True
    finally:
        release.set()
        listener.shutdown()
        listener.server_close()
        serving.join(timeout=3)
