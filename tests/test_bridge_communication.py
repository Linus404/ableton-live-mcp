import json
import socket
import threading
import time

import pytest

from bridge import AbletonBridgeClient, AbletonBridgeError, BridgeConfig


class SocketStub:
    def __init__(self, reply, send_error=None):
        self.reply = reply
        self.send_error = send_error
        self.sent = []
        self.closed = False

    def settimeout(self, timeout):
        pass

    def sendall(self, data):
        self.sent.append(data)
        if self.send_error:
            raise self.send_error

    def recv(self, size):
        if isinstance(self.reply, Exception):
            raise self.reply
        reply, self.reply = self.reply, b""
        return reply

    def close(self):
        self.closed = True


@pytest.mark.parametrize("reply", [
    b"", ConnectionResetError("reset"), b'{"id":1', b"not json\n",
    b'{"jsonrpc":"2.0","id":2,"result":true}\n',
    b'{"jsonrpc":"2.0","id":true,"result":true}\n',
    b'{"jsonrpc":"2.0","id":null,"error":{"message":"timed out"}}\n',
    b'{"jsonrpc":"2.0","id":1,"result":true,"error":{}}\n',
    b'{"jsonrpc":"2.0","id":1,"result":true}\ntrailing',
    b"x" * 129 + b"\n",
])
def test_uncertain_response_never_replays(monkeypatch, reply):
    sock = SocketStub(reply)
    connections = []
    monkeypatch.setattr(socket, "create_connection", lambda *args: connections.append(args) or sock)
    client = AbletonBridgeClient(BridgeConfig(max_response_bytes=128))
    with pytest.raises(AbletonBridgeError) as error:
        client.request("call", {"method": "create_midi_track"})
    assert error.value.to_dict()["outcome"] == "uncertain"
    assert error.value.request_id == 1
    assert error.value.method == "call"
    assert len(sock.sent) == len(connections) == 1
    assert sock.closed


def test_partial_send_is_not_replayed(monkeypatch):
    sock = SocketStub(b"", BrokenPipeError("partial send"))
    monkeypatch.setattr(socket, "create_connection", lambda *args: sock)
    with pytest.raises(AbletonBridgeError) as error:
        AbletonBridgeClient().request("call")
    assert error.value.outcome == "uncertain"
    assert len(sock.sent) == 1


def test_cooldown_rejection_identifies_unsent_request(monkeypatch):
    sock = SocketStub(socket.timeout("no response"))
    monkeypatch.setattr(socket, "create_connection", lambda *args: sock)
    client = AbletonBridgeClient()
    with pytest.raises(AbletonBridgeError):
        client.request("call")
    with pytest.raises(AbletonBridgeError) as error:
        client.request("set")
    assert error.value.outcome == "failed"
    assert error.value.request_id == 2
    assert error.value.method == "set"
    assert len(sock.sent) == 1


def test_connection_failure_retry_is_safe_and_bounded(monkeypatch):
    connections = []

    def connect(*args):
        connections.append(args)
        raise ConnectionRefusedError("not listening")

    monkeypatch.setattr(socket, "create_connection", connect)
    with pytest.raises(AbletonBridgeError) as error:
        AbletonBridgeClient(BridgeConfig(connect_timeout=0.01)).request("call")
    assert error.value.outcome == "failed"
    assert len(connections) == 2
    assert all(args[1] == 0.01 for args in connections)


@pytest.mark.parametrize("outcome", ["failed", "pending", "uncertain"])
def test_remote_error_retains_operation_outcome(monkeypatch, outcome):
    reply = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "operation stopped", "data": {"outcome": outcome}}}
    monkeypatch.setattr(socket, "create_connection", lambda *args: SocketStub(json.dumps(reply).encode() + b"\n"))
    with pytest.raises(AbletonBridgeError) as error:
        AbletonBridgeClient().request("call")
    assert error.value.outcome == outcome


def test_serialized_long_running_requests_keep_matching_results(monkeypatch):
    client_sock, server_sock = socket.socketpair()
    monkeypatch.setattr(socket, "create_connection", lambda *args: client_sock)
    client = AbletonBridgeClient(BridgeConfig(timeout=0.01))
    results = []
    errors = []

    def serve():
        with server_sock, server_sock.makefile("rb") as stream:
            for _ in range(2):
                request = json.loads(stream.readline())
                time.sleep(0.03)
                server_sock.sendall((json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": request["params"]["token"]}) + "\n").encode())

    def call(token):
        try:
            results.append((token, client.request("exec", {"timeout": 0.1, "strict_timeout": True, "token": token})))
        except Exception as exc:
            errors.append(exc)

    server = threading.Thread(target=serve)
    callers = [threading.Thread(target=call, args=(token,)) for token in ("first", "second")]
    server.start()
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(3)
    server.join(3)
    client.close()
    assert not errors
    assert sorted(results) == [("first", "first"), ("second", "second")]
    assert not server.is_alive()
