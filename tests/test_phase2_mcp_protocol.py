"""Local-only protocol/session checks: no Ableton connection or validation."""
import io
import json
import threading

import pytest

from mcp_stdio import StdioMcpServer, Tool, SUPPORTED_PROTOCOL_VERSIONS


def request(method, id=1, **params):
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params}


def ready(server, messages, version="2025-06-18"):
    session = server.create_session(messages.append)
    session.submit(request("initialize", 0, protocolVersion=version,
                           capabilities={}, clientInfo={"name": "test", "version": "1"}))
    session.submit({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return session


def server_with(handler):
    server = StdioMcpServer("test", "1")
    server.add_tool(Tool("local", "local test", {"type": "object"}, handler))
    return server


@pytest.mark.parametrize("version", [*SUPPORTED_PROTOCOL_VERSIONS, "2099-01-01"])
def test_negotiation_and_revision_result_shape(version):
    server = server_with(lambda args: {"ok": True, "outcome": "pending"})
    messages = []
    session = ready(server, messages, version)
    try:
        negotiated = version if version in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[-1]
        assert messages[0]["result"]["protocolVersion"] == negotiated
        session.submit(request("tools/call", 2, name="local"))
        session.wait()
        payload = messages[-1]["result"]
        assert ("structuredContent" in payload) == (negotiated == "2025-06-18")
        assert json.loads(payload["content"][0]["text"])["outcome"] == "pending"
    finally:
        session.close()


@pytest.mark.parametrize("message,code", [
    ([], -32600), ({"jsonrpc": "1.0", "id": 1, "method": "ping"}, -32600),
    (request("ping", True), -32600), (request("ping", None), -32600),
    ({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []}, -32602),
    (request("unknown"), -32601),
])
def test_jsonrpc_errors(message, code):
    server = server_with(lambda args: pytest.fail("no tool expected"))
    messages = []
    session = ready(server, messages)
    try:
        session.submit(message)
        assert messages[-1]["error"]["code"] == code
        if code == -32600 and isinstance(message, dict) and isinstance(message.get("id"), bool):
            assert messages[-1]["id"] is None
    finally:
        session.close()


def test_lifecycle_notifications_and_invalid_params_never_execute():
    calls = []
    server = server_with(lambda args: calls.append(args))
    messages = []
    session = server.create_session(messages.append)
    try:
        session.submit(request("tools/call", name="local"))
        assert messages[-1]["error"]["code"] == -32000
        session.submit(request("initialize", 2))
        assert messages[-1]["error"]["code"] == -32602
        session.submit(request("initialize", 3, protocolVersion="2025-06-18", capabilities={}, clientInfo={"name": "t", "version": "1"}))
        session.submit(request("tools/call", 4, name="local"))
        assert messages[-1]["error"]["code"] == -32000
        session.submit({"jsonrpc": "2.0", "method": "notifications/initialized"})
        count = len(messages)
        session.submit({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "local"}})
        session.submit({"jsonrpc": "2.0", "method": "unknown", "params": []})
        assert len(messages) == count
        session.submit(request("tools/call", 5, name="local", arguments=[]))
        session.wait()
        assert messages[-1]["error"]["code"] == -32602
        assert calls == []
    finally:
        session.close()


def test_responsive_control_queued_cancel_running_outcome_and_duplicates():
    started = threading.Event()
    release = threading.Event()
    calls = []

    def handler(args):
        calls.append(args)
        started.set()
        assert release.wait(3)
        return {"ok": False, "outcome": "uncertain", "request_id": 77}

    server = server_with(handler)
    messages = []
    session = ready(server, messages)
    try:
        running = session.submit(request("tools/call", 2, name="local", _meta={"progressToken": "run"}))
        assert started.wait(2)
        queued = session.submit(request("tools/call", 3, name="local"))
        session.submit(request("tools/call", 2, name="local"))
        assert messages[-1]["error"]["code"] == -32600
        session.submit(request("ping", 4))
        assert messages[-1] == {"jsonrpc": "2.0", "id": 4, "result": {}}
        count = len(messages)
        session.submit({"jsonrpc": "2.0", "id": 2, "result": {}})
        assert len(messages) == count  # A client response cannot settle tool 2.
        session.submit({"jsonrpc": "2.0", "id": 2, "result": {}, "error": {}})
        assert messages[-1]["id"] is None
        for target in (2, 3):
            session.submit({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": target}})
        release.set()
        session.wait()
        assert len(calls) == 1
        assert queued.cancelled and not queued.started and queued.response is None
        payload = running.response["result"]
        assert payload["structuredContent"] == {"ok": False, "outcome": "uncertain", "request_id": 77}
        assert payload["isError"]
        assert payload["_meta"]["cancellation"]["operationInterrupted"] is False
        progress = [m["params"] for m in messages if m.get("method") == "notifications/progress"]
        assert [m["progress"] for m in progress] == [0, 1]
        assert all(m["progressToken"] == "run" for m in progress)
    finally:
        release.set()
        session.close()


def test_global_serialization_and_disconnected_result_retention():
    first_started = threading.Event()
    release = threading.Event()
    calls = []

    def handler(args):
        calls.append(args)
        first_started.set()
        assert release.wait(3)
        return {"ok": True, "applied": True}

    server = server_with(handler)
    left = ready(server, [])
    right = ready(server, [])
    try:
        left.submit(request("tools/call", 2, name="local"))
        assert first_started.wait(2)
        context = right.submit(request("tools/call", 2, name="local", _meta={"progressToken": 1}))
        right.emit = lambda message: (_ for _ in ()).throw(BrokenPipeError("disconnected"))
        right.close(wait=False)
        assert calls == [{}]
        release.set()
        left.wait()
        right.wait()
        assert len(calls) == 2
        assert context.response["result"]["structuredContent"]["applied"]
        assert context.delivery_error == "disconnected"
    finally:
        release.set()
        left.close()
        right.close()


def test_stdio_parse_failure_and_strict_boundary():
    server = server_with(lambda args: pytest.fail("no tool expected"))
    output = io.StringIO()
    server.serve(io.StringIO("bad json\n[]\n" + json.dumps(request("tools/list")) + "\n"), output)
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [r["error"]["code"] for r in responses] == [-32700, -32600, -32000]


def test_modern_metadata_and_http_revision_subset():
    server = StdioMcpServer("test", "1", initialize_meta={"instance": "abc"})
    messages = []
    session = server.create_session(messages.append, supported_versions=("2025-03-26", "2025-06-18"))
    try:
        session.submit(request("initialize", protocolVersion="2024-11-05", capabilities={}, clientInfo={"name": "t", "version": "1"}))
        assert session.protocol_version == "2025-06-18"
        assert messages[-1]["result"]["_meta"] == {"instance": "abc"}
    finally:
        session.close()


@pytest.mark.parametrize("version", ["2024-11-05", "2025-03-26", "2025-06-18"])
def test_revision_specific_wire_batch(version):
    calls = []
    server = server_with(lambda args: calls.append(args) or {"ok": True})
    messages = []
    session = ready(server, messages, version)
    try:
        session.submit([request("ping", 2),
                        {"jsonrpc": "2.0", "method": "unknown"},
                        request("tools/call", 3, name="local"), 7])
        session.wait()
        if version == "2025-06-18":
            assert messages[-1]["error"]["code"] == -32600
            assert calls == []
        else:
            responses = messages[-1]
            assert len(responses) == 3
            assert {r["id"] for r in responses} == {2, 3, None}
            assert calls == [{}]
            assert next(r for r in responses if r["id"] is None)["error"]["code"] == -32600
    finally:
        session.close()


def test_legacy_all_notification_batch_is_silent():
    messages = []
    session = ready(server_with(lambda args: pytest.fail("notification tool")), messages, "2025-03-26")
    try:
        before = len(messages)
        session.submit([{"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "local"}},
                        {"jsonrpc": "2.0", "method": "unknown"},
                        {"jsonrpc": "2.0", "id": "unsolicited", "result": {}}])
        session.wait()
        assert len(messages) == before
    finally:
        session.close()


def test_bounded_queue_and_queued_batch_cancellation_settles():
    started = threading.Event()
    release = threading.Event()
    calls = []

    def handler(args):
        calls.append(args)
        started.set()
        assert release.wait(3)
        return {"ok": True}

    server = server_with(handler)
    messages = []
    session = ready(server, messages, "2025-03-26")
    try:
        session.submit(request("tools/call", 2, name="local"))
        assert started.wait(2)
        session.submit([request("tools/call", 3, name="local"), request("ping", 4)])
        for id in range(5, 37):
            session.submit(request("tools/call", id, name="local"))
        assert messages[-1]["error"]["message"] == "Tool request queue is full; no tool started"
        for id in range(3, 37):
            session.submit({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": id}})
        session.close(wait=False)
        release.set()
        session.wait()
        session.close()
        assert calls == [{}]
        assert [{"jsonrpc": "2.0", "id": 4, "result": {}}] in messages
    finally:
        release.set()
        session.close()


def test_cancelled_started_exception_keeps_uncertain_diagnostics():
    started = threading.Event()
    release = threading.Event()

    class Failure(RuntimeError):
        def to_dict(self):
            return {"outcome": "uncertain", "request_id": 9}

    def handler(args):
        started.set()
        assert release.wait(3)
        raise Failure("connection lost")

    session = ready(server_with(handler), [])
    try:
        context = session.submit(request("tools/call", 2, name="local"))
        assert started.wait(2)
        session.submit({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 2}})
        release.set()
        session.wait()
        error = context.response["error"]
        assert error["data"]["outcome"] == "uncertain"
        assert error["data"]["request_id"] == 9
        assert error["data"]["_meta"]["cancellation"]["operationInterrupted"] is False
    finally:
        release.set()
        session.close()


def test_completed_request_id_cannot_be_reused_in_session():
    messages = []
    session = ready(server_with(lambda args: {"ok": True}), messages)
    try:
        session.submit(request("ping", 2))
        session.submit(request("tools/call", 2, name="local"))
        assert messages[-1]["error"]["code"] == -32600
        assert "Duplicate request id" in messages[-1]["error"]["message"]
        assert session.submit(request("tools/call", 3, name="local")) is not None
        session.wait()
        session.submit(request("ping", 3))
        assert messages[-1]["error"]["code"] == -32600
    finally:
        session.close()
