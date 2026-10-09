import json

from server import make_server


class NoLive:
    def request(self, *args):
        raise AssertionError("offline masking analysis must not call Live")


ARGUMENTS = {
    "target": {"name": "lead", "path": "lead.wav"},
    "competitors": [{"name": "pad", "path": "pad.wav"}],
    "alignment": {"verified": True, "source": "same-start renders", "uncertainty_samples": 0},
    "provenance": {"disjoint_contributions": True, "in_mix_levels": True, "signal_path": "Independent post-fader contributions"},
}


def test_masking_tool_schema_and_offline_dispatch(monkeypatch):
    import audio_masking
    monkeypatch.setattr(audio_masking, "analyze_masking", lambda args: {"received": args})
    server = make_server(NoLive())
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    tool = next(tool for tool in tools if tool["name"] == "live_audio_masking")
    assert set(tool["inputSchema"]["required"]) == {"target", "competitors", "alignment", "provenance"}
    assert {"listening_condition", "sections"} <= set(tool["inputSchema"]["properties"])
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "live_audio_masking", "arguments": ARGUMENTS,
    }})
    assert not response["result"].get("isError")
    result = json.loads(response["result"]["content"][0]["text"])
    assert result["received"]["target"]["path"] == "lead.wav"


def test_masking_contract_failures_are_mcp_errors_without_live():
    server = make_server(NoLive())
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "live_audio_masking", "arguments": {**ARGUMENTS,
            "alignment": {**ARGUMENTS["alignment"], "verified": False}},
    }})
    assert response["error"]["code"] == -32000
    assert "alignment" in response["error"]["message"]
