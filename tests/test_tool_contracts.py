"""Discovery and call validation must agree without connecting to Live."""
import ast
import math
from pathlib import Path

import pytest

import mcp
import mcp_stdio
from server import make_server, _should_retry_agent_m4l_load, retry_agent_m4l_load
from validate import mcp_tool_schema_status


class NoLive:
    def request(self, method, args):
        raise AssertionError("Contract checks must not call Live")


def test_every_published_tool_has_discoverable_properties():
    server = make_server(NoLive())
    assert mcp.StdioMcpServer is mcp_stdio.StdioMcpServer
    assert mcp_tool_schema_status()["checked"] == len(server.tools)
    assert mcp_tool_schema_status()["ok"]
    empty = {name for name, tool in server.tools.items() if not tool.input_schema["properties"]}
    assert empty == {"live_browser_roots", "live_browser_capabilities"}


def test_note_transform_published_contract_and_apply_guard_before_live():
    server = make_server(NoLive())
    schema = server.tools["live_workflow"].input_schema
    variants = schema["properties"]["operations"]["items"]["oneOf"]
    transform = next(v for v in variants if v["properties"]["op"]["const"] == "clip.notes.transform")
    props = transform["properties"]
    assert {"target", "transpose", "velocity_delta", "note_ids", "expected_notes_digest"} <= props.keys()
    assert {"kind", "id", "parent_id"} <= set(props["target"]["required"])
    assert props["note_ids"]["maxItems"] == 512
    assert props["expected_notes_digest"]["pattern"] == "^[0-9a-f]{64}$"
    assert "Required for apply" in props["expected_notes_digest"]["description"]
    response = server.handle({"id": 1, "method": "tools/call", "params": {
        "name": "live_workflow", "arguments": {"mode": "apply", "operations": [
            {"op": "clip.notes.transform", "target": {"kind": "clip", "id": 1, "parent_id": 2},
             "velocity_delta": 12}]}}})
    assert "expected_notes_digest" in response["error"]["message"]


def test_forwarded_rpc_arguments_are_discoverable():
    server = make_server(NoLive())
    source = Path(__file__).parents[1] / "Ableton_Live_MCP" / "bridge.py"
    for fn in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("_rpc_"):
            continue
        tool = server.tools.get("live_" + fn.name.removeprefix("_rpc_"))
        if tool is None:
            continue  # Private capture acquisition RPCs are not public MCP tools.
        names = set()
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "params"
                    and node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant)):
                names.add(node.args[0].value)
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id == "params" and isinstance(node.slice, ast.Constant)):
                names.add(node.slice.value)
        assert names <= tool.input_schema["properties"].keys(), (tool.name, names - tool.input_schema["properties"].keys())


@pytest.mark.parametrize("value,schema", [
    (False, {"type": "boolean", "const": True}),
    (True, {"const": 1}),
    (0, {"type": "number", "exclusiveMinimum": 0}),
    (2, {"type": "integer", "maximum": 1}),
    (math.inf, {"type": "number"}),
    ([], {"type": "array", "minItems": 1}),
    ([1, 2], {"type": "array", "maxItems": 1}),
    ("", {"type": "string", "minLength": 1}),
    ("abc", {"type": "string", "maxLength": 2}),
    ({}, {"anyOf": [{"required": ["path"]}, {"required": ["id"]}]}),
    (1, {"oneOf": [{"type": "number"}, {"type": "integer"}]}),
])
def test_published_constraints_are_enforced(value, schema):
    with pytest.raises(ValueError):
        mcp_stdio._validate(value, schema, "arguments")


@pytest.mark.parametrize("arguments", [None, False, 0, [], ""])
def test_non_object_arguments_do_not_become_empty_objects(arguments):
    response = make_server(NoLive()).handle({"id": 1, "method": "tools/call", "params": {
        "name": "live_browser_roots", "arguments": arguments,
    }})
    assert "must be object" in response["error"]["message"]


def test_audio_xor_and_provenance_are_validated_before_processing():
    server = make_server(NoLive())
    for arguments in ({}, {"path": "a.wav", "manifest_path": "b.json"}):
        with pytest.raises(ValueError):
            mcp_stdio._validate(arguments, server.tools["live_audio_analyze"].input_schema, "arguments")
    provenance = server.tools["live_audio_masking"].input_schema["properties"]["provenance"]
    with pytest.raises(ValueError):
        mcp_stdio._validate({"disjoint_contributions": False, "in_mix_levels": True, "signal_path": "bus"}, provenance, "arguments.provenance")


def test_m4l_bespoke_graph_web_and_list_object_state_remain_freeform():
    contract = make_server(NoLive()).tools["live_agent_m4l_device"].input_schema
    values = {"steps": [1, 0, 0.5], "scene": {"mesh": {"vertices": [1, 2, 3]}}}
    patch = {
        "objects": [{"id": "bespoke", "text": "multislider", "box_attrs": {"custom": [1, 2]},
                     "list_message": "set", "ui_bind": {"target": "pattern", "source_settable": True, "custom": "extension"}}],
        "connections": [{"from": "bespoke", "to": "pattern", "inlet": 0, "outlet": 0}],
        "ui_bindings": [{"source": "probe", "target": "meter", "report": False, "source_settable": False}],
        "webui": [{"id": "scene", "html": "<canvas></canvas>", "assets": {"mesh.json": {"content": "{}"}}, "custom": {"future": True}}],
        "bespoke_extension": {"anything": [False, {"x": 1}]},
    }
    mcp_stdio._validate({"patch": patch, "values": values, "custom_host_control": values}, contract, "arguments")
    objects = contract["properties"]["patch"]["properties"]["objects"]["items"]["properties"]
    assert {"list_message", "object_message", "ui_bind"} <= objects.keys()
    assert "source_settable" in objects["ui_bind"]["properties"]


def test_exception_diagnostics_survive_mcp_error_response():
    class DiagnosticError(RuntimeError):
        def to_dict(self):
            return {"outcome": "uncertain", "request_id": 9, "method": "set"}

    class FailingBridge:
        def request(self, method, args):
            raise DiagnosticError("connection lost")

    response = make_server(FailingBridge()).handle({"id": 1, "method": "tools/call", "params": {
        "name": "live_set", "arguments": {"ref": {"id": 1}, "property": "name", "value": "Track"},
    }})
    assert response["error"]["data"] == {"outcome": "uncertain", "request_id": 9, "method": "set"}


@pytest.mark.parametrize("children,outcome,is_error", [
    ([{"ok": True, "outcome": "pending", "result": {"command_id": "x"}}], "pending", False),
    ([{"ok": True}, {"ok": False, "outcome": "failed"}], "partial", True),
    ([{"ok": False, "outcome": "uncertain"}], "uncertain", True),
    ([{"ok": False, "outcome": "failed"}], "failed", True),
])
def test_batch_keeps_prefix_and_operation_outcomes(children, outcome, is_error):
    class BatchBridge:
        def request(self, method, args):
            return children

    response = make_server(BatchBridge()).handle({"id": 1, "method": "tools/call", "params": {
        "name": "live_batch", "arguments": {"operations": []},
    }})["result"]
    assert response["structuredContent"]["result"] == children
    assert response["structuredContent"]["outcome"] == outcome
    assert response.get("isError", False) == is_error


def test_undo_preserves_applied_steps_when_later_request_fails():
    class Failure(RuntimeError):
        def to_dict(self):
            return {"outcome": "failed", "method": "eval", "request_id": 3}

    class UndoBridge:
        calls = 0

        def request(self, method, args):
            self.calls += 1
            if self.calls == 3:
                raise Failure("pre-send failure")
            return True

    response = make_server(UndoBridge()).handle({"id": 1, "method": "tools/call", "params": {
        "name": "live_undo", "arguments": {"steps": 2},
    }})["result"]
    assert response["isError"]
    assert response["structuredContent"]["performed"] == 1
    assert response["structuredContent"]["outcome"] == "partial"


@pytest.mark.parametrize("metadata,retry", [
    ({}, False),
    ({"load_outcome": "uncertain", "load_retryable": True}, False),
    ({"load_outcome": "failed", "load_retryable": False}, False),
    ({"load_outcome": "failed", "load_retryable": True}, True),
])
def test_m4l_load_retry_requires_proven_pre_edit_failure(metadata, retry):
    assert _should_retry_agent_m4l_load({"target_track": {"id": 1}}, {
        "loaded": False, "load_error": "load did not finish", **metadata,
    }) is retry


def test_m4l_retry_loop_stops_if_next_load_outcome_is_uncertain():
    class LoadBridge:
        calls = 0

        def request(self, method, args):
            self.calls += 1
            return {"loaded": False, "load_error": "insert may have occurred", "load_outcome": "uncertain", "load_retryable": False}

    bridge = LoadBridge()
    result = retry_agent_m4l_load(bridge, {"target_track": {"id": 1}}, {
        "loaded": False, "load_error": "not indexed", "load_outcome": "failed", "load_retryable": True,
    }, 1, 0.001)
    assert bridge.calls == 1
    assert result["load_outcome"] == "uncertain"
    assert result["load_retryable"] is False


def test_m4l_load_retry_preserves_set_guard_and_deadline_controls():
    class LoadBridge:
        def request(self, method, args):
            assert args["expected_set_signature"] == "original-set"
            assert args["timeout"] == 3
            assert args["strict_timeout"] is True
            assert args["timeout_strict"] is True
            return {"loaded": True}

    result = retry_agent_m4l_load(LoadBridge(), {
        "target_track": {"id": 1}, "expected_set_signature": "original-set",
        "timeout": 3, "strict_timeout": True, "timeout_strict": True,
    }, {"command_id": "load1"}, 1, 0)
    assert result["loaded"] is True


def test_guarded_m4l_direct_command_is_checked_before_writing(tmp_path):
    command = tmp_path / "guarded.json"

    class GuardBridge:
        def request(self, method, args):
            assert method == "agent_m4l_device"
            assert args["expected_set_signature"] == "stale-set"
            assert not command.exists()
            assert not Path(str(command) + ".recovery.json").exists()
            raise RuntimeError("set signature mismatch")

    response = make_server(GuardBridge()).handle({"id": 1, "method": "tools/call", "params": {
        "name": "live_agent_m4l_device", "arguments": {
            "load": False, "build": False, "command": "update", "command_file": str(command),
            "patch": {"objects": []}, "expected_set_signature": "stale-set",
        },
    }})
    assert "set signature mismatch" in response["error"]["message"]
    assert not command.exists()
    assert not Path(str(command) + ".recovery.json").exists()
