"""Source callbacks execute through the real Remote exec/batch against fake LOM."""
import types

import pytest

import workflow_history as history_module
from workflow_history import WorkflowHistory, inverse_operations, recover, take_snapshot, tool_specs
from workflows import run_workflow
from mcp_stdio import _validate
from test_remote_bridge_fake_live import FakeClip, FakeClipSlot, FakeParameter, FakeSong, FakeTrack, make_bridge


class LocalBridge:
    def __init__(self, remote):
        self.remote = remote
        self.calls = 0

    def request(self, method, args):
        assert method == "exec"
        self.calls += 1
        return self.remote._rpc_exec(args)


@pytest.fixture
def rig(monkeypatch):
    remote, song, _ = make_bridge(monkeypatch)
    live = remote._rpc_exec.__globals__["Live"]
    live.Base = types.SimpleNamespace(liveobj_valid=lambda obj: not getattr(obj, "invalid", False))
    for track in list(song.tracks) + list(song.return_tracks) + [song.master_track]:
        track.mixer_device.volume = FakeParameter("Volume", 0.5)
        track.mixer_device.panning = FakeParameter("Pan", 0, -1, 1)
        track.mixer_device.sends = [FakeParameter("Send", 0.2)]
    return LocalBridge(remote), song, WorkflowHistory()


def snapshot(rig, **scope):
    bridge, _, store = rig
    return take_snapshot(bridge, {"scope": scope}, store)


def apply(rig, operations):
    bridge, _, store = rig
    result = run_workflow(bridge, {"mode": "apply", "operations": operations})
    assert result["outcome"] == "success", result
    return store.record(result)


def target(rig, index=0):
    bridge, song, _ = rig
    obj = song.tracks[index]
    bridge.remote._objects[bridge.remote._object_id(obj)] = obj
    return {"kind": "track", "id": bridge.remote._object_id(obj)}


def test_snapshot_one_exec_registered_ids_and_readonly(rig):
    bridge, song, _ = rig
    before = [t.name for t in song.tracks]
    snap = snapshot(rig, arrangement=True)
    assert bridge.calls == 1
    assert [t.name for t in song.tracks] == before
    item = snap["collections"]["tracks"]["items"][0]
    assert item["fields"]["name"] == "Track 1"
    assert item["fields"]["volume"] == 0.5
    assert snap["context"]["anchors_valid"]
    assert snap["context"]["physical_verified"] is False
    assert "MIDI note contents" in snap["omissions"]
    assert item["target"]["id"] in bridge.remote._objects


def test_diff_rename_reordering_and_complete_add_remove(rig):
    _, song, store = rig
    a = snapshot(rig)
    original = song.tracks[0]
    original.name = "Renamed"
    song.tracks.reverse()
    song.tracks.append(FakeTrack("New"))
    b = snapshot(rig)
    diff = store.diff(a["snapshot_id"], b["snapshot_id"])
    assert any(c["field"] == "name" and c["after"] == "Renamed" for c in diff["changed"])
    assert any(c["field"] == "index" for c in diff["changed"])
    assert [i["item"]["fields"]["name"] for i in diff["added"] if i["collection"] == "tracks"] == ["New"]
    song.tracks.clear()
    c = snapshot(rig)
    removed = store.diff(b["snapshot_id"], c["snapshot_id"])
    assert len([i for i in removed["removed"] if i["collection"] == "tracks"]) == 3
    assert c["context"]["generation"] == a["context"]["generation"]


def test_diff_incomplete_scope_unavailable_not_deleted(rig):
    _, song, store = rig
    a = snapshot(rig, track_limit=1)
    song.tracks.pop()
    b = snapshot(rig, track_limit=1)
    diff = store.diff(a["snapshot_id"], b["snapshot_id"])
    assert not [r for r in diff["removed"] if r["collection"] == "tracks"]
    assert any(r.get("collection") == "tracks" for r in diff["incomparable"])
    c = snapshot(rig, track_ids=[a["collections"]["tracks"]["items"][0]["id"]])
    assert store.diff(a["snapshot_id"], c["snapshot_id"])["incomparable"]


def test_identity_identical_replacement_invalid_master_recycled_pointer_and_reload(rig):
    bridge, song, store = rig
    song._live_ptr = 10
    song.master_track._live_ptr = 11
    a = snapshot(rig)
    old_master = song.master_track
    old_master.invalid = True
    # Root singleton survives; new master reuses its native pointer.
    song.master_track = FakeTrack("Main")
    song.master_track._live_ptr = 11
    b = snapshot(rig)
    with pytest.raises(ValueError, match="different"):
        store.diff(a["snapshot_id"], b["snapshot_id"])
    replacement = FakeSong()
    song.invalid = True
    bridge.remote.song = lambda: replacement
    c = snapshot(rig)
    with pytest.raises(ValueError): store.diff(b["snapshot_id"], c["snapshot_id"])
    del bridge.remote._workflow_context_anchor
    d = snapshot(rig)
    with pytest.raises(ValueError): store.diff(c["snapshot_id"], d["snapshot_id"])


def test_missing_validity_readonly_snapshot_no_diff_or_recovery(rig):
    bridge, _, store = rig
    del bridge.remote._rpc_exec.__globals__["Live"].Base
    a = snapshot(rig)
    assert not a["context"]["anchors_valid"]
    with pytest.raises(ValueError, match="anchors"):
        store.diff(a["snapshot_id"], a["snapshot_id"])


def test_retention_truncation_restart_and_independent_payload_bounds():
    store = WorkflowHistory(capacity=2, max_payload_bytes=1024)
    first = store.snapshot({"context": {}, "collections": {}})
    store.snapshot({"context": {}, "collections": {}})
    huge = store.snapshot({"context": {}, "collections": {"large": "x" * 2000}})
    assert huge["payload_truncated"] and "collections" not in huge
    with pytest.raises(ValueError, match="evicted"): store.get(first["snapshot_id"], True)
    with pytest.raises(ValueError): WorkflowHistory().get(huge["snapshot_id"], True)


def test_recover_two_fields_same_target_unrelated_edit_and_no_replay(rig):
    bridge, song, store = rig
    entry = apply(rig, [{"op": "track.set", "target": target(rig), "values": {"name": "Changed", "mute": True}}])
    song.tempo += 5
    song.tracks.reverse()
    recovered = recover(bridge, entry["workflow_id"], store)
    assert recovered["outcome"] == "success", recovered
    original = next(t for t in song.tracks if t.name == "Track 1")
    assert original.mute is False and song.tempo == 125
    assert store.get(entry["workflow_id"])["recovery_result_id"] == recovered["workflow_id"]
    with pytest.raises(ValueError, match="already attempted"):
        recover(bridge, entry["workflow_id"], store)


def test_recover_property_conflict_preflights_whole_restore(rig):
    bridge, song, store = rig
    entry = apply(rig, [{"op": "track.set", "target": target(rig), "values": {"name": "Changed", "mute": True}},
                        {"op": "track.set", "target": target(rig, 1), "values": {"solo": True}}])
    song.tracks[0].name = "User Edit"
    result = recover(bridge, entry["workflow_id"], store)
    assert result["phase"] == "recovery_preflight" and not result["mutation_attempted"]
    assert song.tracks[0].mute is True and song.tracks[1].solo is True


def test_recover_missing_target_and_expired_bridge(rig):
    bridge, song, store = rig
    entry = apply(rig, [{"op": "track.set", "target": target(rig), "values": {"name": "Changed"}}])
    song.tracks.pop(0)
    result = recover(bridge, entry["workflow_id"], store)
    assert result["outcome"] == "failed" and not result["mutation_attempted"]
    entry2 = apply(rig, [{"op": "track.set", "target": target(rig), "values": {"name": "Changed2"}}])
    del bridge.remote._workflow_context_anchor
    result2 = recover(bridge, entry2["workflow_id"], store)
    assert result2["outcome"] == "failed" and song.tracks[0].name == "Changed2"


def test_mixed_irreversible_and_uncertain_never_recover(rig):
    _, _, store = rig
    entry = apply(rig, [{"op": "track.set", "target": target(rig), "values": {"name": "Changed"}}])
    for outcome in ("uncertain", "partial", "failed"):
        bad = store.record(dict(entry, outcome=outcome))
        assert not bad["recovery_eligible"]
        with pytest.raises(ValueError, match="irreversible"): inverse_operations(bad)
    mixed = store.record(dict(entry, results=entry["results"] + [{"outcome": "success", "reversible": False}]))
    assert not mixed["recovery_eligible"]


def test_partial_restore_preserves_prefix_unknown_no_replay(rig):
    bridge, song, store = rig
    entry = apply(rig, [{"op": "track.set", "target": target(rig), "values": {"name": "A"}},
                        {"op": "track.set", "target": target(rig, 1), "values": {"name": "B"}}])
    old_set = bridge.remote._rpc_set
    writes = []
    def fail_second(params):
        writes.append(params)
        if len(writes) == 2:
            old_set(params)
            raise RuntimeError("failure after mutation")
        return old_set(params)
    bridge.remote._rpc_set = fail_second
    result = recover(bridge, entry["workflow_id"], store)
    assert result["outcome"] == "uncertain"
    assert result["applied_prefix"] == 1
    assert len(result["results"]) == 2
    with pytest.raises(ValueError, match="already attempted"): recover(bridge, entry["workflow_id"], store)
    assert len(writes) == 2


def test_lost_recovery_reply_records_linked_uncertain_no_replay(rig):
    bridge, _, store = rig
    entry = apply(rig, [{"op": "track.set", "target": target(rig), "values": {"name": "Changed"}}])
    def lost(method, args):
        bridge.remote._rpc_exec(args)
        raise OSError("response lost after send")
    bridge.request = lost
    result = recover(bridge, entry["workflow_id"], store)
    assert result["outcome"] == "uncertain" and result["recovery_of"] == entry["workflow_id"]
    with pytest.raises(ValueError, match="already attempted"): recover(bridge, entry["workflow_id"], store)


def test_schema_nested_bounds_and_no_caller_qualification(rig):
    bridge, _, _ = rig
    specs = {s["name"]: s for s in tool_specs(bridge)}
    schema = specs["live_snapshot"]["inputSchema"]
    _validate({"scope": {"track_limit": 1, "arrangement": True}}, schema, "arguments")
    for bad in ({"scope": {"track_limit": 0}}, {"scope": {"unknown": True}}, {"context": {"physical_verified": True}}):
        with pytest.raises(ValueError): _validate(bad, schema, "arguments")
    history_schema = specs["live_workflow_history"]["inputSchema"]
    for good in ({"action": "list"}, {"action": "get", "workflow_id": "x"}, {"action": "recover", "workflow_id": "x"}):
        _validate(good, history_schema, "arguments")
    for bad in ({"action": "get"}, {"action": "list", "workflow_id": "x"}, {"action": "recover", "workflow_id": "x", "limit": 1}):
        with pytest.raises(ValueError): _validate(bad, history_schema, "arguments")


def test_recovery_oldest_entry_capacity_edge_retains_outcome(rig):
    bridge, _, store = rig
    entry = apply(rig, [{"op": "track.set", "target": target(rig), "values": {"name": "Changed"}}])
    for _ in range(31): store.record({"outcome": "failed", "touched": []})
    result = recover(bridge, entry["workflow_id"], store)
    assert result["outcome"] == "success" and result["original_entry_evicted"]
    assert store.get(result["workflow_id"])["recovery_of"] == entry["workflow_id"]
    with pytest.raises(ValueError, match="evicted"): store.get(entry["workflow_id"])


def test_unsupported_identity_not_advertised_recoverable(rig):
    bridge, _, store = rig
    del bridge.remote._rpc_exec.__globals__["Live"].Base
    entry = apply(rig, [{"op": "track.set", "target": target(rig), "values": {"name": "Changed"}}])
    assert not entry["recovery_eligible"]
    with pytest.raises(ValueError, match="unverified"): recover(bridge, entry["workflow_id"], store)


def test_overview_read_failure_incomparable_and_bridge_stores_isolated(rig):
    bridge, song, store = rig
    a = snapshot(rig)
    del song.signature_numerator
    b = snapshot(rig)
    assert "signature_numerator" in b["overview_unavailable"]
    diff = store.diff(a["snapshot_id"], b["snapshot_id"])
    assert any(x.get("field") == "signature_numerator" for x in diff["incomparable"])
    own, other = WorkflowHistory(), WorkflowHistory()
    own.snapshot({"context": {}, "collections": {}})
    assert not other.snapshots
    own_tools = {s["name"]: s for s in tool_specs(bridge, own)}
    other_tools = {s["name"]: s for s in tool_specs(bridge, other)}
    key = next(iter(own.snapshots))
    with pytest.raises(ValueError, match="anchors"):
        own_tools["live_snapshot_diff"]["handler"]({"before_id": key, "after_id": key})
    with pytest.raises(ValueError, match="Unknown"):
        other_tools["live_snapshot_diff"]["handler"]({"before_id": key, "after_id": key})


class RoutingTrack(FakeTrack):
    def __init__(self):
        super().__init__("Routes")
        self.types = [types.SimpleNamespace(display_name="A", identifier="a"), types.SimpleNamespace(display_name="B", identifier="b")]
        self.channels = {"a": [types.SimpleNamespace(display_name="1", identifier="a1")], "b": [types.SimpleNamespace(display_name="2", identifier="b2")]}
        self.output_routing_type = self.types[0]
        self.output_routing_channel = self.channels["a"][0]

    @property
    def available_output_routing_types(self): return self.types

    @property
    def available_output_routing_channels(self): return self.channels[self.output_routing_type.identifier]


def routing_entry(rig):
    _, song, _ = rig
    track = RoutingTrack()
    song.tracks[:] = [track]
    entry = apply(rig, [{"op": "routing.set", "target": target(rig), "direction": "output",
                         "type": {"identifier": "b"}, "channel": {"identifier": "b2"}}])
    return entry, track


def same_type_routing_entry(rig):
    _, song, _ = rig
    track = RoutingTrack()
    track.channels["a"].append(types.SimpleNamespace(display_name="3", identifier="a3"))
    song.tracks[:] = [track]
    entry = apply(rig, [{"op": "routing.set", "target": target(rig), "direction": "output",
                         "type": {"identifier": "a"}, "channel": {"identifier": "a3"}}])
    return entry, track


def test_routing_same_type_recovery_actual_objects(rig):
    bridge, _, store = rig
    entry, track = same_type_routing_entry(rig)
    result = recover(bridge, entry["workflow_id"], store)
    assert result["outcome"] == "success", result
    assert track.output_routing_type is track.types[0]
    assert track.output_routing_channel is track.channels["a"][0]


def test_routing_ambiguous_type_preflight_no_write(rig):
    bridge, _, store = rig
    entry, track = same_type_routing_entry(rig)
    track.types.append(types.SimpleNamespace(display_name="A", identifier="a"))
    result = recover(bridge, entry["workflow_id"], store)
    assert result["outcome"] == "failed" and result["applied_prefix"] == 0
    assert track.output_routing_type.identifier == "a" and track.output_routing_channel.identifier == "a3"


def test_routing_type_changed_ineligible_without_any_inverse_write(rig):
    bridge, _, store = rig
    entry, track = routing_entry(rig)
    track.channels["a"] = []
    assert not entry["recovery_eligible"]
    assert any("channel" in reason for reason in entry["recovery_reasons"])
    calls = bridge.calls
    with pytest.raises(ValueError, match="irreversible"): recover(bridge, entry["workflow_id"], store)
    assert track.output_routing_type.identifier == "b" and bridge.calls == calls


def test_routing_changed_channel_options_preflight_whole_restore(rig):
    bridge, _, store = rig
    entry, track = same_type_routing_entry(rig)
    track.channels["a"] = [track.channels["a"][1]]
    result = recover(bridge, entry["workflow_id"], store)
    assert result["outcome"] == "failed" and not result["mutation_attempted"]
    assert track.output_routing_channel.identifier == "a3"


def test_invalidated_member_recycled_pointer_cannot_redirect_compensation(rig):
    bridge, song, store = rig
    original = song.tracks[0]
    original._live_ptr = 999
    entry = apply(rig, [{"op": "track.set", "target": target(rig), "values": {"name": "Changed"}}])
    original.invalid = True
    replacement = FakeTrack("Changed")
    replacement._live_ptr = 999
    song.tracks[0] = replacement
    bridge.remote._objects[999] = replacement
    result = recover(bridge, entry["workflow_id"], store)
    assert result["outcome"] == "failed" and not result["mutation_attempted"]
    assert replacement.name == "Changed"


def test_recovery_transport_error_retains_structured_outcome(rig):
    from bridge import AbletonBridgeError
    bridge, _, store = rig
    entry = apply(rig, [{"op": "track.set", "target": target(rig), "values": {"name": "Changed"}}])
    def fail(method, args):
        raise AbletonBridgeError("connection lost", outcome="uncertain", request_id=123, method=method)
    bridge.request = fail
    result = recover(bridge, entry["workflow_id"], store)
    assert result["outcome"] == "uncertain"
    assert result["error"]["request_id"] == 123 and result["error"]["method"] == "exec"


def test_tool_registration_accepts_bare_and_slotted_duck_bridges_without_calls():
    class Slotted:
        __slots__ = ()
        def request(self, *_): raise AssertionError("Registration cannot call bridge")
    for bridge in (object(), Slotted()):
        specs = {s["name"]: s for s in tool_specs(bridge)}
        result = specs["live_workflow_history"]["handler"]({"action": "list"})
        assert result["entries"] == []


def test_slotted_duck_server_all_four_tools_share_retention(rig):
    from server import make_server
    bridge, song, _ = rig
    class Slotted:
        __slots__ = ("wrapped",)
        def __init__(self, wrapped): self.wrapped = wrapped
        def request(self, method, arguments): return self.wrapped.request(method, arguments)
    server = make_server(Slotted(bridge))
    def call(name, args): return server.tools[name].handler(args)
    before = call("live_snapshot", {})
    entry = call("live_workflow", {"mode": "apply", "snapshot_id": before["snapshot_id"], "operations": [
        {"op": "track.set", "target": target(rig), "values": {"name": "Changed"}}]})
    after = call("live_snapshot", {})
    assert call("live_snapshot_diff", {"before_id": before["snapshot_id"], "after_id": after["snapshot_id"]})["changed"]
    assert call("live_workflow_history", {"action": "get", "workflow_id": entry["workflow_id"]})["outcome"] == "success"
    recovered = call("live_workflow_history", {"action": "recover", "workflow_id": entry["workflow_id"]})
    assert recovered["outcome"] == "success" and song.tracks[0].name == "Track 1"
    assert len(call("live_workflow_history", {"action": "list"})["entries"]) == 2
    other = make_server(Slotted(bridge))
    assert not other.tools["live_workflow_history"].handler({"action": "list"})["entries"]


def test_fresh_clip_reusing_deleted_slot_native_id_enrolls_without_old_pin_rebinding(rig):
    bridge, song, store = rig
    old_slot = song.tracks[0].clip_slots[0]
    old_slot._live_ptr = 31337
    before = snapshot(rig)
    tid = before["collections"]["tracks"]["items"][0]["id"]
    old_clip = before["collections"]["clips:" + str(tid)]["items"][0]
    entry = apply(rig, [{"op": "clip.set", "target": old_clip["target"], "values": {"name": "Old edit"}}])
    old_slot.invalid = True
    old_slot.clip.invalid = True
    clip = FakeClip("New clip")
    clip._live_ptr = old_slot._live_ptr
    song.tracks[0].clip_slots[0] = FakeClipSlot(clip)
    bridge.remote._objects[clip._live_ptr] = clip
    after = snapshot(rig)
    fresh = after["collections"]["clips:" + str(tid)]["items"][0]
    assert fresh["id"] < 0 and fresh["native_id"] == 31337
    diff = store.diff(before["snapshot_id"], after["snapshot_id"])
    assert any(i["item"]["id"] == old_clip["id"] for i in diff["removed"])
    assert any(i["item"]["id"] == fresh["id"] for i in diff["added"])
    again = snapshot(rig)
    assert again["collections"]["clips:" + str(tid)]["items"][0]["id"] == fresh["id"]
    fresh_entry = apply(rig, [{"op": "clip.set", "target": fresh["target"], "values": {"name": "Fresh edit"}}])
    assert clip.name == "Fresh edit"
    refused = recover(bridge, entry["workflow_id"], store)
    assert refused["outcome"] == "failed" and not refused["mutation_attempted"]
    assert clip.name == "Fresh edit"
    restored = recover(bridge, fresh_entry["workflow_id"], store)
    assert restored["outcome"] == "success" and clip.name == "New clip"


def test_replacement_track_alias_selected_scope_and_fresh_recovery(rig):
    bridge, song, store = rig
    old = song.tracks[0]
    old._live_ptr = 41414
    before = snapshot(rig)
    old_id = before["collections"]["tracks"]["items"][0]["id"]
    entry = apply(rig, [{"op": "track.set", "target": {"kind": "track", "id": old_id}, "values": {"name": "Old edit"}}])
    old.invalid = True
    replacement = FakeTrack("Replacement")
    replacement._live_ptr = old._live_ptr
    song.tracks[0] = replacement
    bridge.remote._objects[old_id] = replacement
    after = snapshot(rig)
    item = after["collections"]["tracks"]["items"][0]
    assert item["id"] < 0 and item["native_id"] == old_id
    selected = snapshot(rig, track_ids=[item["id"]])
    assert selected["collections"]["tracks"]["complete"]
    assert selected["collections"]["tracks"]["items"][0]["target"] == item["target"]
    fresh = apply(rig, [{"op": "track.set", "target": item["target"], "values": {"name": "Fresh"}}])
    assert recover(bridge, entry["workflow_id"], store)["outcome"] == "failed"
    assert replacement.name == "Fresh"
    assert recover(bridge, fresh["workflow_id"], store)["outcome"] == "success"
    assert replacement.name == "Replacement"


def test_mixer_parameter_replacement_same_native_id_same_value_blocks_whole_restore(rig):
    bridge, song, store = rig
    old = song.tracks[0].mixer_device.volume
    old._live_ptr = 51515
    entry = apply(rig, [{"op": "mixer.set", "target": target(rig), "parameter": "volume", "value": 0.7},
                        {"op": "track.set", "target": target(rig, 1), "values": {"name": "Changed"}}])
    assert entry["touched"][0]["parameter_id"] == 51515
    old.invalid = True
    replacement = FakeParameter("Volume", 0.7)
    replacement._live_ptr = 51515
    song.tracks[0].mixer_device.volume = replacement
    result = recover(bridge, entry["workflow_id"], store)
    assert result["outcome"] == "failed" and not result["mutation_attempted"]
    assert "parameter lifetime" in result["error"]
    assert replacement.value == 0.7 and song.tracks[1].name == "Changed"


def test_mixer_missing_parameter_identity_not_recoverable(rig):
    _, _, store = rig
    entry = apply(rig, [{"op": "mixer.set", "target": target(rig), "parameter": "volume", "value": 0.7}])
    assert entry["recovery_eligible"]
    del entry["touched"][0]["parameter_id"]
    retained = store.record(entry)
    assert not retained["recovery_eligible"]
    assert "Mixer parameter lifetime identity unavailable" in retained["recovery_reasons"]


def test_snapshot_scope_signed_workflow_id_schema_and_zero_rejection(rig):
    bridge, _, _ = rig
    schema = {s["name"]: s for s in tool_specs(bridge)}["live_snapshot"]["inputSchema"]
    _validate({"scope": {"track_ids": [-1, 123]}}, schema, "arguments")
    for bad in ([0], [9007199254740992], [-9007199254740992]):
        with pytest.raises(ValueError): _validate({"scope": {"track_ids": bad}}, schema, "arguments")
        with pytest.raises(ValueError): take_snapshot(bridge, {"scope": {"track_ids": bad}})


def test_recycled_return_identity_uses_qualified_send_dependency(rig):
    bridge, song, store = rig
    old_return = song.return_tracks[0]
    old_return._live_ptr = 61616
    before = snapshot(rig)
    entry = apply(rig, [{"op": "mixer.set", "target": target(rig), "parameter": "send", "return_id": 61616, "value": 0.6}])
    old_return.invalid = True
    replacement = FakeTrack("Replacement return")
    replacement._live_ptr = 61616
    song.return_tracks[0] = replacement
    bridge.remote._objects[61616] = replacement
    after = snapshot(rig)
    return_id = after["collections"]["returns"]["items"][0]["id"]
    assert return_id < 0
    assert "send:" + str(return_id) in after["collections"]["tracks"]["items"][0]["fields"]
    diff = store.diff(before["snapshot_id"], after["snapshot_id"])
    assert any(x["collection"] == "returns" and x["item"]["id"] == 61616 for x in diff["removed"])
    blocked = recover(bridge, entry["workflow_id"], store)
    assert blocked["outcome"] == "failed" and not blocked["mutation_attempted"]
    assert song.tracks[0].mixer_device.sends[0].value == 0.6
    fresh = apply(rig, [{"op": "mixer.set", "target": target(rig), "parameter": "send", "return_id": return_id, "value": 0.4}])
    assert fresh["touched"][0]["field"] == "send:" + str(return_id)
    assert recover(bridge, fresh["workflow_id"], store)["outcome"] == "success"
    assert song.tracks[0].mixer_device.sends[0].value == 0.6
