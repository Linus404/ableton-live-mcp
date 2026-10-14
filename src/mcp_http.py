"""Loopback-only, sessionful MCP Streamable HTTP (no legacy SSE/replay)."""
from __future__ import annotations

import json
import math
import queue
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


HTTP_VERSIONS = ("2025-03-26", "2025-06-18")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class _Session:
    def __init__(self, registry):
        self.lock = threading.Lock()
        self.pending = {}
        self.tokens = {}
        self.dispatcher = registry.create_session(self.emit, strict_lifecycle=True,
                                                  supported_versions=HTTP_VERSIONS)

    def emit(self, message):
        with self.lock:
            target = self.pending.get(message.get("id")) if "id" in message else self.tokens.get(
                message.get("params", {}).get("progressToken"))
            if target is not None:
                target.put(message)


class StreamableHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, registry, host="127.0.0.1", port=8765, *, max_sessions=32):
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("HTTP binding must be 127.0.0.1 or localhost")
        self.registry = registry
        self.sessions = {}
        self.retired_sessions = []
        self.closing = False
        self.sessions_lock = threading.Lock()
        self.max_sessions = max_sessions
        self.requests = threading.BoundedSemaphore(64)
        super().__init__(("127.0.0.1", port), _Handler)

    def server_close(self):
        super().server_close()
        with self.sessions_lock:
            self.closing = True
            sessions = list(self.sessions.values()) + self.retired_sessions
            self.sessions.clear()
            self.retired_sessions = []
        for session in sessions:
            session.dispatcher.close(wait=False)
        # Graceful process shutdown retains ownership of accepted work/cleanup.
        for session in sessions:
            session.dispatcher.close(wait=True)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _reply(self, status, value=None, headers=None):
        body = b"" if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        if body:
            self.send_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.close_connection = True
        if body:
            self.wfile.write(body)

    def _guard(self):
        if self.path != "/mcp":
            self._reply(404)
            return False
        try:
            host = urlsplit("//" + self.headers.get("Host", ""))
            if (len(self.headers.get_all("Host", [])) != 1 or host.hostname not in LOOPBACK
                    or host.username or host.password or host.port != self.server.server_port
                    or host.path or host.query or host.fragment):
                raise ValueError("Invalid Host")
            origin = self.headers.get("Origin")
            if origin:
                parsed = urlsplit(origin)
                parsed.port  # Validate malformed/out-of-range ports before accepting an origin.
                if (parsed.scheme not in {"http", "https"} or parsed.hostname not in LOOPBACK
                        or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
                    raise ValueError("Invalid Origin")
            version = self.headers.get("MCP-Protocol-Version", "2025-03-26")
            if version not in HTTP_VERSIONS:
                self._reply(400, {"error": "Unsupported MCP-Protocol-Version"})
                return False
        except ValueError:
            self._reply(403, {"error": "Host and Origin must be loopback origins"})
            return False
        return True

    def _session(self):
        sid = self.headers.get("MCP-Session-Id")
        if not sid:
            self._reply(400, {"error": "MCP-Session-Id required"})
            return None
        with self.server.sessions_lock:
            session = self.server.sessions.get(sid)
        if session is None:
            self._reply(404, {"error": "Unknown MCP session"})
        return session

    def do_GET(self):
        if self._guard():
            self._reply(405, headers={"Allow": "POST, DELETE"})

    def do_DELETE(self):
        if not self._guard():
            return
        session = self._session()
        if session is not None:
            if self.headers.get("MCP-Protocol-Version", "2025-03-26") != session.dispatcher.protocol_version:
                self._reply(400, {"error": "MCP-Protocol-Version differs from negotiated version"})
                return
            with self.server.sessions_lock:
                self.server.sessions.pop(self.headers["MCP-Session-Id"], None)
                # Deleted sessions remain owned until their accepted operations settle.
                self.server.retired_sessions.append(session)
            session.dispatcher.close(wait=False)
            self._reply(200)

    def do_POST(self):
        if not self._guard():
            return
        if not self.server.requests.acquire(blocking=False):
            self._reply(503)
            return
        try:
            self._post()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            # Disconnect is not cancellation: the dispatcher retains operation ownership.
            pass
        finally:
            self.server.requests.release()

    def _post(self):
        accept = set()
        for part in self.headers.get("Accept", "").split(","):
            media, *parameters = part.split(";")
            try:
                quality = next((float(p.strip()[2:]) for p in parameters if p.strip().startswith("q=")), 1)
            except ValueError:
                quality = 0
            if quality > 0:
                accept.add(media.strip().lower())
        if not {"application/json", "text/event-stream"} <= accept:
            self._reply(406)
            return
        content_type = self.headers.get("Content-Type", "").lower().replace(" ", "")
        if content_type.split(";", 1)[0] != "application/json" or any(
                p.startswith("charset=") and p.split("=", 1)[1].strip('"') not in {"utf-8", "utf8"}
                for p in content_type.split(";")[1:]):
            self._reply(415)
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
            if size < 1 or size > 1024 * 1024 or self.headers.get("Transfer-Encoding"):
                raise ValueError()
        except ValueError:
            self._reply(400, {"error": "Bounded Content-Length required (1–1048576 bytes)"})
            return
        self.connection.settimeout(120)
        try:
            message = json.loads(self.rfile.read(size).decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        except (ValueError, UnicodeError):
            self._reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            return
        if isinstance(message, list):
            self._batch(message)
            return
        if not isinstance(message, dict):
            self._reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "JSON-RPC object required"}})
            return
        sid = self.headers.get("MCP-Session-Id")
        new = message.get("method") == "initialize" and not sid
        if new:
            with self.server.sessions_lock:
                if self.server.closing:
                    self._reply(503)
                    return
                self.server.retired_sessions = [s for s in self.server.retired_sessions if s.dispatcher.pending]
                if len(self.server.sessions) + len(self.server.retired_sessions) >= self.server.max_sessions:
                    self._reply(503)
                    return
                sid = secrets.token_urlsafe(24)
                session = _Session(self.server.registry)
                self.server.sessions[sid] = session
        else:
            session = self._session()
            if session is None:
                return
            version = self.headers.get("MCP-Protocol-Version", "2025-03-26")
            if session.dispatcher.protocol_version and version != session.dispatcher.protocol_version:
                self._reply(400, {"error": "MCP-Protocol-Version differs from negotiated version"})
                return
        req_id = message.get("id")
        if message.get("jsonrpc") != "2.0" or ("method" in message and not isinstance(message["method"], str)):
            self._reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid JSON-RPC envelope"}})
            if new:
                with self.server.sessions_lock:
                    self.server.sessions.pop(sid, None)
                session.dispatcher.close(wait=False)
            return
        if "method" not in message:
            error = message.get("error")
            if ("id" not in message or isinstance(req_id, bool) or not isinstance(req_id, (str, int))
                    or (("result" in message) == ("error" in message))
                    or ("error" in message and (not isinstance(error, dict)
                        or isinstance(error.get("code"), bool) or not isinstance(error.get("code"), int)
                        or not isinstance(error.get("message"), str)))):
                self._reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid JSON-RPC response"}})
                return
            # This server sends no client requests; unsolicited responses have no sink.
            self._reply(202)
            return
        if "id" not in message:
            session.dispatcher.submit(message)
            self._reply(202)
            if new:
                with self.server.sessions_lock:
                    self.server.sessions.pop(sid, None)
                session.dispatcher.close(wait=False)
            return
        if isinstance(req_id, bool) or not isinstance(req_id, (str, int)):
            self._reply(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request ID"}})
            if new:
                with self.server.sessions_lock:
                    self.server.sessions.pop(sid, None)
                session.dispatcher.close(wait=False)
            return
        params = message.get("params")
        meta = params.get("_meta") if isinstance(params, dict) else None
        token = meta.get("progressToken") if isinstance(meta, dict) else None
        if isinstance(token, bool) or not isinstance(token, (str, int, float)) or (isinstance(token, float) and not math.isfinite(token)):
            token = None
        events = queue.Queue()
        with session.lock:
            if req_id in session.pending or (token is not None and token in session.tokens):
                self._reply(400, {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32600, "message": "Duplicate in-flight ID or progress token"}})
                return
            session.pending[req_id] = events
            if token is not None:
                session.tokens[token] = events
        try:
            session.dispatcher.submit(message, response_sink=events.put)
            stream = token is not None and message.get("method") == "tools/call"
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
            while True:
                event = events.get()
                if event is None:
                    if not stream:
                        self._reply(202)
                    break
                final = "id" in event
                if stream:
                    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(("event: message\ndata: " + data + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                elif final:
                    self._reply(200, event, {"MCP-Session-Id": sid} if new and "result" in event else None)
                if final:
                    if new and "error" in event:
                        with self.server.sessions_lock:
                            self.server.sessions.pop(sid, None)
                        session.dispatcher.close(wait=False)
                    break
        finally:
            with session.lock:
                session.pending.pop(req_id, None)
                if token is not None:
                    session.tokens.pop(token, None)

    def _batch(self, messages):
        session = self._session()
        if session is None:
            return
        version = self.headers.get("MCP-Protocol-Version", "2025-03-26")
        if version != "2025-03-26" or session.dispatcher.protocol_version != version:
            self._reply(400, {"error": "JSON-RPC batches require negotiated 2025-03-26"})
            return
        if not messages or len(messages) > 32 or any(
                not isinstance(m, dict) or m.get("jsonrpc") != "2.0"
                or not isinstance(m.get("method"), str) or m["method"] == "initialize"
                or ("id" in m and (isinstance(m["id"], bool) or not isinstance(m["id"], (str, int))))
                for m in messages):
            self._reply(400, {"error": "Invalid batch (1–32 requests/notifications; initialize must be separate)"})
            return
        ids = [m["id"] for m in messages if "id" in m]
        if len(ids) != len(set(ids)):
            self._reply(400, {"error": "Duplicate batch IDs"})
            return
        events = queue.Queue()
        tokens = []
        for message in messages:
            params = message.get("params")
            meta = params.get("_meta") if isinstance(params, dict) else None
            token = meta.get("progressToken") if isinstance(meta, dict) else None
            if (token is not None and not isinstance(token, bool) and isinstance(token, (str, int, float))
                    and not (isinstance(token, float) and not math.isfinite(token))):
                tokens.append(token)
        with session.lock:
            if any(i in session.pending for i in ids) or len(tokens) != len(set(tokens)) or any(t in session.tokens for t in tokens):
                self._reply(400, {"error": "Duplicate in-flight batch ID or progress token"})
                return
            session.pending.update((i, events) for i in ids)
            session.tokens.update((t, events) for t in tokens)
        try:
            for message in messages:
                if "id" in message:
                    session.dispatcher.submit(message, response_sink=lambda event, req_id=message["id"]:
                        events.put(event if event is not None else {"_cancelled_id": req_id}))
                else:
                    session.dispatcher.submit(message)
            if not ids:
                self._reply(202)
                return
            stream = bool(tokens)
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
            responses = []
            settled = 0
            while settled < len(ids):
                event = events.get()
                if "_cancelled_id" in event:
                    settled += 1
                    continue
                if "id" in event:
                    responses.append(event)
                    settled += 1
                if stream:
                    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(("event: message\ndata: " + data + "\n\n").encode("utf-8"))
                    self.wfile.flush()
            if not stream:
                self._reply(200, responses) if responses else self._reply(202)
        finally:
            with session.lock:
                for req_id in ids:
                    session.pending.pop(req_id, None)
                for token in tokens:
                    session.tokens.pop(token, None)
