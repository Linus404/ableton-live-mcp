import json
import sys
from types import SimpleNamespace

from server import make_server


def test_audio_analysis_is_schema_discoverable_and_offline(monkeypatch):
    class NoLive:
        def request(self, *args):
            raise AssertionError("offline analysis must not call Live")

    import audio_analysis
    monkeypatch.setattr(audio_analysis, "analyze_audio", lambda args: {"received": args})
    server = make_server(NoLive())
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    tool = next(tool for tool in tools if tool["name"] == "live_audio_analyze")
    assert {"path", "manifest_path", "sections", "window_step_seconds"} == set(tool["inputSchema"]["properties"])
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "live_audio_analyze", "arguments": {"path": "take.wav"},
    }})
    assert not response["result"].get("isError")
    assert "take.wav" in response["result"]["content"][0]["text"]


def test_balance_and_assessment_are_discoverable_and_offline(monkeypatch):
    import audio_balance
    import audio_assessment
    class NoLive:
        def request(self, *args):
            raise AssertionError("offline balance/assessment must not call Live")
    monkeypatch.setattr(audio_balance, "analyze_balance", lambda args: {"received": args})
    monkeypatch.setattr(audio_assessment, "assess_audio", lambda args: {"received": args})
    server = make_server(NoLive())
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    for name in ("live_audio_balance", "live_audio_assess"):
        tool = next(t for t in tools if t["name"] == name)
        assert "listening_condition" in tool["inputSchema"]["required"]
        assert "expected_section_differences" in tool["inputSchema"]["properties"]
        arguments = {"listening_condition": {"kind": "assumed", "db_spl_at_0_dbfs_rms": 100, "source": "test"}}
        if name == "live_audio_assess":
            arguments["manifest_path"] = "manifest.json"
        else:
            arguments.update(programme={"path": "master.wav"}, parts=[{"name": "lead", "path": "lead.wav"}],
                alignment={"verified": True, "source": "test", "uncertainty_samples": 0},
                provenance={"disjoint_contributions": True, "in_mix_levels": True, "signal_path": "test"})
        response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": name, "arguments": arguments}})
        assert json.loads(response["result"]["content"][0]["text"])["received"] == arguments


def test_in_mix_capture_dispatches_and_qualifies(monkeypatch):
    import in_mix_capture
    calls = []
    bridge = object()
    monkeypatch.setattr(in_mix_capture, "capture_in_mix", lambda b, args: calls.append((b, args)) or {"complete": True})
    monkeypatch.setitem(sys.modules, "in_mix_qualification", SimpleNamespace(attach_qualification=lambda result: {**result, "qualified": "test"}))
    server = make_server(bridge)
    arguments = {"start_beat": 0, "length_beats": 4, "return_refs": [{"path": "live_set return_tracks 0"}]}
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "live_audio_capture_in_mix", "arguments": arguments}})
    assert calls == [(bridge, arguments)]
    assert json.loads(response["result"]["content"][0]["text"])["qualified"] == "test"


def test_capture_calibration_dispatch_and_precision_schema(monkeypatch):
    calls = []
    bridge = object()
    monkeypatch.setitem(sys.modules, "in_mix_calibration", SimpleNamespace(
        calibrate_in_mix=lambda b, args: calls.append((b, args)) or {"verified": False}))
    server = make_server(bridge)
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    calibration = next(t for t in tools if t["name"] == "live_audio_capture_in_mix_calibrate")
    assert set(calibration["inputSchema"]["properties"]) == {"output_directory"}
    balance = next(t for t in tools if t["name"] == "live_audio_balance")
    assert balance["inputSchema"]["properties"]["expected_section_differences"]["items"]["properties"]["tolerance_lu"]["minimum"] == 0.001
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "live_audio_capture_in_mix_calibrate", "arguments": {}}})
    assert calls == [(bridge, {})]
    assert json.loads(response["result"]["content"][0]["text"])["verified"] is False
