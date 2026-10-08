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
