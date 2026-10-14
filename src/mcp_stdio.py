from __future__ import annotations

import json
import math
import sys
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, TextIO


Json = dict[str, Any]
Handler = Callable[[Json], Any]
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")


class ProtocolError(ValueError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class RequestContext:
    request: Json
    progress_token: str | int | float | None = None
    started: bool = False
    cancelled: bool = False
    response: Json | None = None
    delivery_error: str | None = None
    response_sink: Callable[[Json | None], None] | None = None
    settled: threading.Event = field(default_factory=threading.Event)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: Json
    handler: Handler

    def as_mcp(self) -> Json:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class StdioMcpServer:
    def __init__(self, name: str, version: str, instructions: str | None = None, *, initialize_meta: Json | None = None) -> None:
        self.name = name
        self.version = version
        self.instructions = instructions
        self.initialize_meta = initialize_meta
        self.tools: dict[str, Tool] = {}
        # A bridge/capture operation can make several calls: lock the whole tool,
        # across transport sessions, rather than each individual bridge request.
        self.execution_lock = threading.RLock()

    def create_session(self, emit: Callable[[Json], None], *, strict_lifecycle: bool = True,
                       supported_versions: tuple[str, ...] = SUPPORTED_PROTOCOL_VERSIONS) -> RequestDispatcher:
        return RequestDispatcher(self, emit, strict_lifecycle=strict_lifecycle, supported_versions=supported_versions)

    def add_tool(self, tool: Tool) -> None:
        # The MCP spec requires every tool's inputSchema to be a JSON Schema
        # object (type == "object"). Strict clients (e.g. Claude Code) reject the
        # entire tools/list when any single tool violates this, which silently
        # disables every tool on the server. Fail loudly at registration so a
        # malformed schema surfaces at startup on any client -- including lenient
        # ones -- instead of only when a strict client connects.
        schema = tool.input_schema
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ValueError(
                f"Tool {tool.name!r} has an invalid inputSchema: MCP requires a "
                f'JSON Schema object with "type": "object" (got {schema!r}). '
                "Build it with schema(...) or loose_schema()."
            )
        self.tools[tool.name] = tool

    def serve(self, stdin: TextIO | None = None, stdout: TextIO | None = None, *, strict_lifecycle: bool = True) -> None:
        in_stream = stdin or sys.stdin
        out_stream = stdout or sys.stdout
        output_lock = threading.Lock()

        def emit(response: Json) -> None:
            with output_lock:
                out_stream.write(json.dumps(response, separators=(",", ":")) + "\n")
                out_stream.flush()

        session = self.create_session(emit, strict_lifecycle=strict_lifecycle)
        try:
            for line in in_stream:
                if not line.strip():
                    continue
                try:
                    request = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                except ValueError as exc:
                    emit(self._error(None, -32700, f"Parse error: {exc}"))
                else:
                    session.submit(request)
        finally:
            # EOF stops intake, but running edits and capture cleanup must finish.
            session.close()

    def handle(self, request: Json, *, protocol_version: str = "2025-06-18", strict: bool = False) -> Json | None:
        """Synchronous compatibility entry point; transports use create_session."""
        if isinstance(request, dict) and "method" not in request and ("result" in request or "error" in request):
            return None if self._valid_response(request) else self._error(None, -32600, "Invalid JSON-RPC response")
        req_id = request.get("id") if isinstance(request, dict) else None
        try:
            self._validate_request(request, strict=strict)
            method = request["method"]
            params = request.get("params", {})
            if "id" not in request:
                return None  # Notifications never execute tools or receive errors.
            if method == "initialize":
                requested = params.get("protocolVersion", "2024-11-05")
                if not isinstance(requested, str):
                    raise ProtocolError(-32602, "protocolVersion must be string")
                result = {
                    "protocolVersion": requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[-1],
                    "serverInfo": {"name": self.name, "version": self.version},
                    "capabilities": {"tools": {}},
                }
                if self.instructions:
                    result["instructions"] = self.instructions
                if self.initialize_meta:
                    result["_meta"] = self.initialize_meta
                return self._result(req_id, result)
            if method == "ping":
                return self._result(req_id, {})
            if method == "tools/list":
                if params.get("cursor") is not None:
                    raise ProtocolError(-32602, "Invalid tools cursor; this catalogue is returned in one page")
                return self._result(req_id, {"tools": [tool.as_mcp() for tool in self.tools.values()]})
            if method == "tools/call":
                name = params.get("name")
                if not isinstance(name, str) or name not in self.tools:
                    raise ProtocolError(-32602, f"Unknown tool: {name}")
                tool = self.tools[name]
                arguments = params.get("arguments", {})
                try:
                    _validate(arguments, tool.input_schema, "arguments")
                except ValueError as exc:
                    raise ProtocolError(-32602, str(exc)) from exc
                with self.execution_lock:
                    result = tool.handler(arguments)
                batch_outcome = None
                if name == "live_batch" and isinstance(result, list):
                    failures = [item for item in result if isinstance(item, dict) and item.get("ok") is False]
                    if failures:
                        batch_outcome = "uncertain" if any(item.get("outcome") == "uncertain" for item in failures) else ("partial" if any(item.get("ok") is True for item in result if isinstance(item, dict)) else "failed")
                    else:
                        batch_outcome = "pending" if any(item.get("outcome") == "pending" for item in result if isinstance(item, dict)) else "success"
                if not isinstance(result, dict):
                    # MCP requires structuredContent to be a JSON object. Tools can
                    # return non-object values -- live_call on a void setter like
                    # delete_device yields None; live_eval/live_exec yield whatever
                    # the code evaluates to (str/int/bool/list); collection tools
                    # return lists -- which would otherwise emit a non-object
                    # structuredContent and fail strict client validation (Claude
                    # Code rejects the whole call: "expected record, received
                    # <type>"), even though the call ran. Wrap any non-object return
                    # in a success record so the value is always addressable under
                    # .result and never mistaken for a failure. None is just the
                    # void case of this rule -> {"ok": true, "result": null}.
                    result = {"ok": True, "result": result}
                if batch_outcome:
                    result.update({"ok": batch_outcome in ("success", "pending"), "outcome": batch_outcome})
                payload = {
                    "content": [{"type": "text", "text": json.dumps(result, separators=(",", ":"))}],
                }
                if protocol_version == "2025-06-18":
                    payload["structuredContent"] = result
                if result.get("ok") is False or result.get("outcome") in ("failed", "partial", "uncertain"):
                    payload["isError"] = True
                return self._result(req_id, payload)
            raise ProtocolError(-32601, f"Unsupported MCP method: {method}")
        except Exception as exc:  # MCP requires structured errors instead of crashing stdio.
            if isinstance(request, dict) and "id" not in request and request.get("jsonrpc") == "2.0" and isinstance(request.get("method"), str):
                return None
            error = {"code": getattr(exc, "code", -32000), "message": str(exc)}
            if callable(getattr(exc, "to_dict", None)):
                error["data"] = exc.to_dict()
            return {"jsonrpc": "2.0", "id": req_id, "error": error}

    @staticmethod
    def _valid_response(message: Json) -> bool:
        if message.get("jsonrpc") != "2.0" or isinstance(message.get("id"), bool) or not isinstance(message.get("id"), (str, int)):
            return False
        if ("result" in message) == ("error" in message):
            return False
        if "result" in message:
            return isinstance(message["result"], dict)
        error = message["error"]
        return (isinstance(error, dict) and isinstance(error.get("code"), int)
                and not isinstance(error["code"], bool) and isinstance(error.get("message"), str))

    @staticmethod
    def _validate_request(request: Any, *, strict: bool = True) -> None:
        if not isinstance(request, dict) or (request.get("jsonrpc") != "2.0" and (strict or "jsonrpc" in request)):
            raise ProtocolError(-32600, "Invalid JSON-RPC request")
        if not isinstance(request.get("method"), str):
            raise ProtocolError(-32600, "method must be string")
        if "id" in request and (isinstance(request["id"], bool) or not isinstance(request["id"], (str, int))):
            raise ProtocolError(-32600, "id must be string or integer")
        if "params" in request and not isinstance(request["params"], dict):
            raise ProtocolError(-32602, "params must be object")
        meta = request.get("params", {}).get("_meta", {})
        if not isinstance(meta, dict):
            raise ProtocolError(-32602, "_meta must be object")
        token = meta.get("progressToken")
        if token is not None and (isinstance(token, bool) or not isinstance(token, (str, int, float)) or isinstance(token, float) and not math.isfinite(token)):
            raise ProtocolError(-32602, "progressToken must be string or finite number")

    @staticmethod
    def _error(req_id: Any, code: int, message: str) -> Json:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

    @staticmethod
    def _result(req_id: Any, result: Any) -> Json:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}


class RequestDispatcher:
    """Transport-session state with responsive intake and non-interrupting tools.

    submit returns a context for a tool request. Its eventual response is retained
    even when a disconnected transport cannot receive emit. Queues are bounded;
    all sessions share the server lock for the entire blocking tool operation.
    """

    def __init__(self, server: StdioMcpServer, emit: Callable[[Json], None], *,
                 strict_lifecycle: bool = True,
                 supported_versions: tuple[str, ...] = SUPPORTED_PROTOCOL_VERSIONS) -> None:
        if not supported_versions or any(v not in SUPPORTED_PROTOCOL_VERSIONS for v in supported_versions):
            raise ValueError("supported_versions must select supported protocol revisions")
        self.server = server
        self.emit = emit
        self.strict_lifecycle = strict_lifecycle
        self.supported_versions = supported_versions
        self.protocol_version: str | None = None
        self.initialized = False
        self.closed = False
        self.pending: dict[str | int, RequestContext] = {}
        self._seen_ids: set[str | int] = set()
        self._lock = threading.RLock()
        self._output_lock = threading.RLock()
        self._queue: queue.Queue[RequestContext | None] = queue.Queue(maxsize=32)
        self._worker = threading.Thread(target=self._run, name="mcp-tools", daemon=True)
        self._worker.start()

    def _emit(self, message: Json) -> None:
        with self._output_lock:
            self.emit(message)

    def submit(self, request: Any, *, response_sink: Callable[[Json | None], None] | None = None) -> RequestContext | None:
        emit = response_sink or self._emit
        with self._lock:
            if isinstance(request, dict) and "method" not in request and ("result" in request or "error" in request):
                # This server sends no client requests. Unsolicited responses
                # have no matching operation and must never terminate a tool ID.
                if not self.server._valid_response(request):
                    emit(self.server._error(None, -32600, "Invalid JSON-RPC response"))
                return None
            if response_sink is None and isinstance(request, list) and request and self.protocol_version in ("2024-11-05", "2025-03-26"):
                # Older revisions permit wire batches; June removed them.
                remaining = sum(not (isinstance(item, dict) and (
                                     ("id" not in item and item.get("jsonrpc") == "2.0" and isinstance(item.get("method"), str))
                                     or ("method" not in item and self.server._valid_response(item))))
                                for item in request)
                responses = []
                batch_lock = threading.Lock()

                def collect(response: Json | None) -> None:
                    nonlocal remaining
                    with batch_lock:
                        if response is not None:
                            responses.append(response)
                        remaining -= 1
                        if remaining == 0 and responses:
                            emit(responses)

                for item in request:
                    self.submit(item, response_sink=collect)
                return None
            try:
                self.server._validate_request(request)
            except ProtocolError as exc:
                # Well-formed notifications have no response, including bad params.
                if isinstance(request, dict) and "id" not in request and request.get("jsonrpc") == "2.0" and isinstance(request.get("method"), str):
                    return None
                req_id = request.get("id") if isinstance(request, dict) else None
                if isinstance(req_id, bool) or not isinstance(req_id, (str, int)):
                    req_id = None
                emit(self.server._error(req_id, exc.code, str(exc)))
                return None
            req_id = request.get("id")
            method = request["method"]
            params = request.get("params", {})
            notification = "id" not in request
            if notification:
                if method == "notifications/initialized" and self.protocol_version:
                    self.initialized = True
                elif method == "notifications/cancelled":
                    target = params.get("requestId")
                    if isinstance(target, (str, int)) and not isinstance(target, bool):
                        context = self.pending.get(target)
                        if context:
                            context.cancelled = True
                return None
            if self.closed:
                emit(self.server._error(req_id, -32000, "Session is closed"))
                return None
            if req_id in self._seen_ids:
                emit(self.server._error(req_id, -32600, "Duplicate request id within session"))
                return None
            self._seen_ids.add(req_id)
            if method == "initialize":
                if self.protocol_version is not None:
                    emit(self.server._error(req_id, -32600, "Session already initialized"))
                    return None
                if self.strict_lifecycle:
                    info = params.get("clientInfo")
                    if (not isinstance(params.get("protocolVersion"), str)
                            or not isinstance(params.get("capabilities"), dict)
                            or not isinstance(info, dict)
                            or not isinstance(info.get("name"), str)
                            or not isinstance(info.get("version"), str)):
                        emit(self.server._error(req_id, -32602, "initialize requires protocolVersion, capabilities and clientInfo"))
                        return None
                response = self.server.handle(request, strict=True)
                if response and "result" in response:
                    requested = params.get("protocolVersion")
                    self.protocol_version = requested if requested in self.supported_versions else self.supported_versions[-1]
                    response["result"]["protocolVersion"] = self.protocol_version
                if response:
                    emit(response)
                return None
            if self.strict_lifecycle and not self.initialized and method != "ping":
                emit(self.server._error(req_id, -32000, "Session initialization is not complete"))
                return None
            if method != "tools/call":
                response = self.server.handle(request, protocol_version=self.protocol_version or "2025-06-18", strict=True)
                if response:
                    emit(response)
                return None
            context = RequestContext(request, params.get("_meta", {}).get("progressToken"), response_sink=response_sink)
            self.pending[req_id] = context
            try:
                self._queue.put_nowait(context)
            except queue.Full:
                self.pending.pop(req_id)
                emit(self.server._error(req_id, -32000, "Tool request queue is full; no tool started"))
                return None
            return context

    def _progress(self, context: RequestContext, value: int, message: str) -> None:
        if context.progress_token is not None:
            try:
                self._emit({"jsonrpc": "2.0", "method": "notifications/progress", "params": {
                    "progressToken": context.progress_token, "progress": value, "total": 1, "message": message,
                }})
            except Exception as exc:
                context.delivery_error = str(exc)

    def _run(self) -> None:
        while True:
            with self._lock:
                if self.closed and self._queue.empty():
                    return
            context = self._queue.get()
            try:
                if context is None:
                    return
                # Waiting for another session's operation is still cancellable.
                with self.server.execution_lock:
                    with self._lock:
                        if context.cancelled:
                            continue
                        context.started = True
                    self._progress(context, 0, "Tool execution started")
                    context.response = self.server.handle(context.request, protocol_version=self.protocol_version or "2025-06-18", strict=True)
                if context.cancelled and context.response:
                    # Actual bridge outcomes remain untouched: cancellation cannot
                    # undo a sent edit or interrupt capture's cleanup ownership.
                    target = context.response.get("result")
                    if target is None:
                        target = context.response["error"].setdefault("data", {})
                        if not isinstance(target, dict):
                            target = {"diagnostics": target}
                            context.response["error"]["data"] = target
                    target.setdefault("_meta", {})["cancellation"] = {"requested": True, "operationInterrupted": False}
                self._progress(context, 1, "Tool execution settled")
                if context.response:
                    (context.response_sink or self._emit)(context.response)
            except Exception as exc:
                # Transport delivery failure never retries the operation.
                if context is not None:
                    context.delivery_error = str(exc)
            finally:
                if context is not None:
                    if context.cancelled and not context.started and context.response_sink:
                        try:
                            context.response_sink(None)
                        except Exception as exc:
                            context.delivery_error = str(exc)
                    with self._lock:
                        self.pending.pop(context.request["id"], None)
                    context.settled.set()
                self._queue.task_done()

    def wait(self) -> None:
        self._queue.join()

    def close(self, wait: bool = True) -> None:
        with self._lock:
            if self.closed:
                worker = self._worker
            else:
                self.closed = True
                worker = self._worker
                try:
                    self._queue.put_nowait(None)
                except queue.Full:
                    pass  # Worker notices closed after draining the bounded queue.
        if wait:
            worker.join()


def _validate(value: Any, schema: Json, path: str) -> None:
    if not schema:
        return
    if "oneOf" in schema:
        errors = []
        matches = 0
        for option in schema["oneOf"]:
            try:
                _validate(value, option, path)
                matches += 1
            except ValueError as exc:
                errors.append(str(exc))
        if matches != 1:
            raise ValueError("%s must match exactly one allowed shape: %s" % (path, "; ".join(errors)))
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                _validate(value, option, path)
                break
            except ValueError:
                pass
        else:
            raise ValueError("%s does not match any allowed shape" % path)
    expected = schema.get("type")
    if expected:
        _validate_type(value, expected, path)
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("%s must be one of: %s" % (path, ", ".join(map(str, schema["enum"]))))
    if "const" in schema and (value != schema["const"] or isinstance(value, bool) != isinstance(schema["const"], bool)):
        raise ValueError("%s must equal %s" % (path, schema["const"]))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError("%s must be finite" % path)
        for keyword, fails, symbol in (
            ("minimum", lambda bound: value < bound, ">="),
            ("maximum", lambda bound: value > bound, "<="),
            ("exclusiveMinimum", lambda bound: value <= bound, ">"),
            ("exclusiveMaximum", lambda bound: value >= bound, "<"),
        ):
            if keyword in schema and fails(schema[keyword]):
                raise ValueError("%s must be %s %s" % (path, symbol, schema[keyword]))
    if isinstance(value, list):
        for keyword, fails in (("minItems", lambda bound: len(value) < bound), ("maxItems", lambda bound: len(value) > bound)):
            if keyword in schema and fails(schema[keyword]):
                raise ValueError("%s violates %s=%s" % (path, keyword, schema[keyword]))
    if isinstance(value, str):
        for keyword, fails in (("minLength", lambda bound: len(value) < bound), ("maxLength", lambda bound: len(value) > bound)):
            if keyword in schema and fails(schema[keyword]):
                raise ValueError("%s violates %s=%s" % (path, keyword, schema[keyword]))
    if isinstance(value, dict):
        if schema.get("additionalProperties") is False:
            allowed = set(schema.get("properties", {}).keys())
            extra = sorted(set(value.keys()) - allowed)
            if extra:
                raise ValueError("%s has unknown fields: %s" % (path, ", ".join(extra)))
        for name in schema.get("required", []):
            if name not in value:
                raise ValueError("%s.%s is required" % (path, name))
        for name, item in value.items():
            child_schema = schema.get("properties", {}).get(name)
            if child_schema:
                _validate(item, child_schema, "%s.%s" % (path, name))
            elif isinstance(schema.get("additionalProperties"), dict):
                _validate(item, schema["additionalProperties"], "%s.%s" % (path, name))
    elif expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            _validate(item, schema["items"], "%s[%s]" % (path, index))


def _validate_type(value: Any, expected: str, path: str) -> None:
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
    }
    check = checks.get(expected)
    if check and not check(value):
        raise ValueError("%s must be %s" % (path, expected))
