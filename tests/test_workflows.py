"""Compiler checks exercise the actual Remote exec and private batch handlers."""
import sys
import types

import pytest

from test_remote_bridge_fake_live import make_bridge, FakeTrack, FakeParameter, FakeClipSlot
from workflows import execute_callback, run_workflow, validate_workflow


class LocalClient:
    def __init__(self, remote):
        self.remote = remote
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, params))
        assert method == "exec"
        return self.remote._rpc_exec(params)


def rig(monkeypatch):
    remote, song, _ = make_bridge(monkeypatch)
    sys.modules["Live"].Base = types.SimpleNamespace(liveobj_valid=lambda o: not getattr(o, "invalid", False))
    client = LocalClient(remote)
    targets = []
    for t in song.tracks:
        ident = remote._object_id(t)
        remote._objects[ident] = t
        targets.append({"kind": "track", "id": ident})
    return client, remote, song, targets


def set_op(target, **values):
    return {"op": "track.set", "target": target, "values": values}


def test_plan_zero_writes_actual_private_batch_apply_signature_once(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    signature = remote._set_signature()
    ops = [set_op(targets[0], name="renamed"), set_op(targets[1], mute=True)]
    planned = run_workflow(client, {"mode": "plan", "operations": ops, "expected_set_signature": signature})
    assert planned["outcome"] == "planned"
    assert song.tracks[0].name == "Track 1" and not song.tracks[1].mute
    result = run_workflow(client, {"mode": "apply", "operations": ops, "expected_set_signature": signature})
    assert result["ok"] and result["applied_prefix"] == 2
    assert song.tracks[0].name == "renamed" and song.tracks[1].mute
    assert result["touched"][0]["after"] == "renamed"
    assert len(client.calls) == 2  # exactly one exec per workflow


def test_all_preflight_before_mutation_and_stale_entry(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    result = run_workflow(client, {"mode": "apply", "operations": [set_op(targets[0], name="bad"),
        {"op":"mixer.set", "target":targets[1], "parameter":"volume", "value":999}]})
    assert result["outcome"] == "failed" and song.tracks[0].name == "Track 1"
    result = run_workflow(client, {"mode":"apply", "operations":[set_op(targets[0], mute=True)], "expected_set_signature":"stale"})
    assert not result["ok"] and not song.tracks[0].mute


def test_reorder_pinned_id_and_missing_membership(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    original = song.tracks[0]
    song.tracks.reverse()
    result = run_workflow(client,{"mode":"apply", "operations":[set_op(targets[0],name="pinned")]})
    assert result["ok"] and original.name == "pinned"
    song.tracks.remove(original)
    result = run_workflow(client,{"mode":"apply", "operations":[set_op(targets[0],name="missing")]})
    assert not result["ok"] and original.name == "pinned"


def test_partial_side_effect_uncertain_child_closes_group_skips_suffix(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    events = []
    song.begin_undo_step = lambda: events.append("begin")
    song.end_undo_step = lambda: events.append("end")
    original = remote._rpc_set
    def setter(params):
        value = original(params)
        if params["property"] == "solo":
            raise RuntimeError("after side effect")
        return value
    remote._rpc_set = setter
    ops = [set_op(targets[0],name="prefix"), set_op(targets[1],solo=True), set_op(targets[0],mute=True)]
    result = run_workflow(client,{"mode":"apply", "operations":ops, "undo":"group_if_supported"})
    assert result["outcome"] == "uncertain" and result["applied_prefix"] == 1
    assert result["results"][1]["substeps"][0]["outcome"] == "uncertain"
    assert song.tracks[1].solo and not song.tracks[0].mute
    assert result["skipped"] == [2] and events == ["begin","end"]
    assert not result["recovery_eligible"]
    assert result["grouping"]["excluded_operations"] == [0,1]


def test_required_group_rejects_nonparticipating_name_before_writes(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    events = []
    song.begin_undo_step = lambda: events.append("begin")
    song.end_undo_step = lambda: events.append("end")
    operations = [set_op(targets[0],name="excluded",mute=True)]
    result = run_workflow(client,{"mode":"apply","operations":operations,"undo":"required_group"})
    assert result["outcome"] == "failed" and not events
    assert song.tracks[0].name == "Track 1" and not song.tracks[0].mute
    assert result["grouping"]["excluded_fields"][0]["field"] == "name"
    result = run_workflow(client,{"mode":"apply","operations":operations,"undo":"group_if_supported"})
    assert result["ok"] and events == ["begin","end"]
    assert song.tracks[0].name == "excluded" and song.tracks[0].mute
    assert result["grouping"]["excluded_operations"] == [0]
    assert not result["grouping"]["whole_workflow_undo_claim"]


def test_required_group_accepts_two_track_mute_writes_with_honest_boundary(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    events = []
    song.begin_undo_step = lambda: events.append("begin")
    song.end_undo_step = lambda: events.append("end")
    result = run_workflow(client,{"mode":"apply", "undo":"required_group",
        "operations":[set_op(targets[0],mute=True),set_op(targets[1],mute=True)]})
    assert result["ok"] and result["applied_prefix"] == 2 and events == ["begin","end"]
    assert all(t.mute for t in song.tracks)
    assert not result["grouping"]["excluded_fields"] and result["grouping"]["closed"]
    assert result["grouping"]["participation"] == "unverified"  # fake closure is not physical one-step proof


def test_undo_begin_and_end_failure_truthful(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    def fail():
        raise RuntimeError("boundary")
    song.begin_undo_step = fail
    song.end_undo_step = lambda: pytest.fail("end after failed begin")
    result = run_workflow(client,{"mode":"apply","operations":[set_op(targets[0],mute=True)],"undo":"required_group"})
    assert not result["ok"] and not song.tracks[0].mute and not result["grouping"]["end_attempted"]
    song.begin_undo_step = lambda: None
    song.end_undo_step = fail
    result = run_workflow(client,{"mode":"apply","operations":[set_op(targets[0],mute=True)],"undo":"required_group"})
    assert song.tracks[0].mute and result["applied_prefix"] == 1
    assert result["outcome"] == "partial" and not result["grouping"]["closed"] and result["grouping"]["end_error"]


def test_connection_failure_never_replays(monkeypatch):
    client, _, _, targets = rig(monkeypatch)
    def fail(method, params):
        client.calls.append((method,params))
        raise TimeoutError("sent but no response")
    client.request = fail
    result = run_workflow(client,{"mode":"apply","operations":[set_op(targets[0],mute=True)]})
    assert result["outcome"] == "uncertain" and len(client.calls) == 1


def test_snapshot_ids_registered_and_context_invalidation(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    result = execute_callback(client, {}, "result = {'id':wf_id(song.master_track), 'context':wf_context()}")
    assert result["id"] in remote._objects and result["context"]["anchors_valid"]
    old = song.master_track
    old.invalid = True
    song.master_track = FakeTrack("Main")
    failed = run_workflow(client,{"mode":"apply","operations":[set_op(targets[0],mute=True)],
        "context":{k:result["context"][k] for k in ("bridge_nonce","generation")}})
    assert failed["outcome"] == "failed" and not song.tracks[0].mute
    context = execute_callback(client, {}, "result = wf_context()")
    assert context["anchors_valid"] and context["generation"] != result["context"]["generation"]
    assert not context["physical_verified"]


def test_nested_schemas_finite_destructive_and_safely_serialized(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    name = "'); song.tracks[0].mute=True; #\n\""
    result = run_workflow(client,{"mode":"apply","operations":[set_op(targets[0],name=name)]})
    assert result["ok"] and song.tracks[0].name == name and not song.tracks[0].mute
    for op in ({"op":"track.delete","target":targets[0],"confirm_delete":False},
               {"op":"track.set","target":targets[0],"values":{"typo":1}},
               {"op":"mixer.set","target":targets[0],"parameter":"volume","value":float("nan")},
               {"op":"mixer.set","target":targets[0],"parameter":"send","value":0.5},
               {"op":"unknown"}):
        with pytest.raises(ValueError):
            validate_workflow({"mode":"apply","operations":[op]})


def test_clip_slot_occupancy_and_parent_guard(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    track = song.tracks[0]
    track.has_midi_input = True
    slot = track.clip_slots[0]
    slot_id = remote._object_id(slot)
    remote._objects[slot_id] = slot
    target = {"kind":"slot","id":slot_id,"parent_id":targets[0]["id"],"slot_index":0}
    op = {"op":"clip.create","target":target,"expected_clip_id":None,"length":4,"notes":[]}
    result = run_workflow(client,{"mode":"apply","operations":[set_op(targets[1],mute=True),op]})
    assert result["outcome"] == "failed" and not song.tracks[1].mute
    target["parent_id"] = targets[1]["id"]
    result = run_workflow(client,{"mode":"plan","operations":[op]})
    assert result["outcome"] == "failed"


def test_create_uses_native_call_args_and_returns_registered_id(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    def create(index):
        assert isinstance(index,int)
        song.tracks.insert(len(song.tracks) if index == -1 else index, FakeTrack("new"))
    song.create_midi_track = create
    result = run_workflow(client,{"mode":"apply","operations":[{"op":"track.create","type":"midi","name":"created"}]})
    assert result["ok"] and song.tracks[-1].name == "created"
    assert result["results"][0]["created_target"]["id"] in remote._objects


def test_recycled_member_pointer_refused_after_generic_cache_overwrite(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    old = song.tracks[0]
    old._live_ptr = 123456
    remote._objects[123456] = old
    target = {"kind":"track", "id":123456}
    first = run_workflow(client,{"mode":"apply","operations":[set_op(target,name="same")]})
    assert first["ok"]
    old.invalid = True
    replacement = FakeTrack("same")
    replacement._live_ptr = 123456
    song.tracks[0] = replacement
    remote._objects[123456] = replacement  # low-level inspection/cache can recycle IDs
    result = run_workflow(client,{"mode":"apply","operations":[set_op(target,mute=True)]})
    assert result["outcome"] == "failed" and not replacement.mute
    alias = execute_callback(client,{},"result = wf_id(song.tracks[0])")
    assert alias < 0 and alias != target["id"]
    assert execute_callback(client,{},"result = wf_id(song.tracks[0])") == alias
    assert remote._workflow_member_anchors[target["id"]] is old
    fresh = {"kind":"track","id":alias}
    result = run_workflow(client,{"mode":"apply","operations":[set_op(fresh,mute=True)]})
    assert result["ok"] and replacement.mute


def test_uncertain_child_and_end_failure_both_retained(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    song.begin_undo_step = lambda: None
    def fail_end():
        raise RuntimeError("end failure")
    song.end_undo_step = fail_end
    original = remote._rpc_set
    def setter(params):
        original(params)
        raise RuntimeError("after write")
    remote._rpc_set = setter
    result = run_workflow(client,{"mode":"apply","operations":[set_op(targets[0],mute=True)],"undo":"required_group"})
    assert result["outcome"] == "uncertain" and song.tracks[0].mute
    assert result["results"][0]["outcome"] == "uncertain"
    assert result["grouping"]["end_error"] == "end failure" and not result["grouping"]["closed"]


def test_loop_metadata_uses_safe_intermediate_order(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    class StrictClip:
        name = "strict"
        def __init__(self):
            self._start, self._end = 0, 4
        @property
        def loop_start(self):
            return self._start
        @loop_start.setter
        def loop_start(self, value):
            if value >= self._end:
                raise ValueError("invalid intermediate start")
            self._start = value
        @property
        def loop_end(self):
            return self._end
        @loop_end.setter
        def loop_end(self, value):
            if value <= self._start:
                raise ValueError("invalid intermediate end")
            self._end = value
    clip = StrictClip()
    song.tracks[0].clip_slots[0].clip = clip
    ident = remote._object_id(clip)
    remote._objects[ident] = clip
    target = {"kind":"clip","id":ident,"parent_id":targets[0]["id"],"slot_index":0}
    for values in ({"loop_start":8,"loop_end":12}, {"loop_end":4,"loop_start":0}):
        result = run_workflow(client,{"mode":"apply","operations":[{"op":"clip.set","target":target,"values":values}]})
        assert result["ok"]
        assert (clip.loop_start,clip.loop_end) == (values["loop_start"],values["loop_end"])


def test_routing_real_object_selection_mixer_send_and_dynamic_channel(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    track = song.tracks[0]
    a = types.SimpleNamespace(display_name="A",identifier="a")
    b = types.SimpleNamespace(display_name="B",identifier="b")
    channel = types.SimpleNamespace(display_name="1/2",identifier="12")
    track.available_output_routing_types = [a,b]
    track.available_output_routing_channels = [channel]
    track.output_routing_type, track.output_routing_channel = a, channel
    op = {"op":"routing.set","target":targets[0],"direction":"output","type":{"identifier":"b"},"channel":{"identifier":"12"}}
    plan = run_workflow(client,{"mode":"plan","operations":[op]})
    assert plan["preflight"][0]["dynamic_preconditions"]
    result = run_workflow(client,{"mode":"apply","operations":[op]})
    assert result["ok"] and track.output_routing_type is b and track.output_routing_channel is channel
    return_id = remote._object_id(song.return_tracks[0])
    track.mixer_device.sends = [FakeParameter("Send A",0)]
    result = run_workflow(client,{"mode":"apply","operations":[{"op":"mixer.set","target":targets[0],"parameter":"send","return_id":return_id,"value":0.25}]})
    assert result["ok"] and result["touched"][0]["field"] == "send:"+str(return_id)
    track.available_output_routing_types = [b, types.SimpleNamespace(display_name="B",identifier="b")]
    result = run_workflow(client,{"mode":"apply","operations":[op]})
    assert result["outcome"] == "failed"


def framework_validity(monkeypatch, helper):
    for name in ("ableton", "ableton.v2", "ableton.v2.base"):
        module = types.ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules,name,module)
    if helper is not None:
        sys.modules["ableton.v2.base"].liveobj_valid = helper
    monkeypatch.delattr(sys.modules["Live"],"Base")


def test_shipped_framework_validity_native_none_equality_invalidation(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    framework_validity(monkeypatch, lambda obj: obj != None)
    class NativeTrack(FakeTrack):
        def __eq__(self, other):
            return bool(getattr(self,"invalid",False)) if other is None else self is other
        def __ne__(self, other):
            return not self.__eq__(other)
    master = NativeTrack("Main")
    master._live_ptr = 987654
    song.master_track = master
    context = execute_callback(client,{},"result = wf_context()")
    assert context["anchors_valid"] and context["validity_source"] == "ableton.v2.base.liveobj_valid"
    assert not context["physical_verified"]
    master.invalid = True
    assert bool(master)  # native validity must not be replaced with Python truthiness
    song.master_track = NativeTrack("Main")
    song.master_track._live_ptr = master._live_ptr
    result = run_workflow(client,{"mode":"apply","operations":[set_op(targets[0],mute=True)],
        "context":{k:context[k] for k in ("bridge_nonce","generation")}})
    assert result["outcome"] == "failed" and not song.tracks[0].mute
    context2 = execute_callback(client,{},"result = wf_context()")
    assert context2["anchors_valid"] and context2["generation"] != context["generation"]
    member = NativeTrack("member")
    member._live_ptr = 654321
    song.tracks.append(member)
    remote._objects[654321] = member
    target = {"kind":"track","id":654321}
    assert run_workflow(client,{"mode":"apply","operations":[set_op(target,name="retained")]})["ok"]
    member.invalid = True
    replacement = NativeTrack("retained")
    replacement._live_ptr = 654321
    song.tracks[-1] = replacement
    remote._objects[654321] = replacement
    result = run_workflow(client,{"mode":"apply","operations":[set_op(target,mute=True)]})
    assert result["outcome"] == "failed" and not replacement.mute


def test_missing_native_validity_reports_unsupported_not_truthiness(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    framework_validity(monkeypatch,None)
    context = execute_callback(client,{},"result = wf_context()")
    assert context["validity_source"] == "unavailable" and not context["anchors_valid"]
    result = run_workflow(client,{"mode":"plan","operations":[set_op(targets[0],mute=True)],
        "context":{k:context[k] for k in ("bridge_nonce","generation")}})
    assert result["outcome"] == "failed" and not song.tracks[0].mute


@pytest.mark.parametrize("category", ["slot", "parameter"])
def test_acknowledged_clip_creation_adopts_cross_category_native_collision(monkeypatch, category):
    client, remote, song, targets = rig(monkeypatch)
    old = FakeClipSlot() if category == "slot" else FakeParameter("old",0)
    old._live_ptr = 424242
    remote._objects[424242] = old
    assert execute_callback(client,{},"result = wf_id(this._objects[424242])") == 424242
    old.invalid = True
    slot = FakeClipSlot()
    slot._live_ptr = 434343
    song.tracks[0].clip_slots.append(slot)
    song.tracks[0].has_midi_input = True
    original_create = slot.create_clip
    def create(length):
        original_create(length)
        slot.clip._live_ptr = 424242
    slot.create_clip = create
    remote._objects[434343] = slot
    target = {"kind":"slot","id":434343,"parent_id":targets[0]["id"],"slot_index":2}
    notes = [{"pitch":60+i,"start_time":i,"duration":0.5,"velocity":90} for i in range(4)]
    result = run_workflow(client,{"mode":"apply","operations":[{"op":"clip.create","target":target,
        "expected_clip_id":None,"length":4,"notes":notes,"name":"qualified"}]})
    assert result["ok"] and result["results"][0]["substeps"][0]["result"]["note_api"] == "extended"
    created = result["results"][0]["created_target"]
    assert created["id"] < 0 and len(slot.clip.get_all_notes_extended()) == 4
    assert remote._workflow_member_anchors[424242] is old
    assert execute_callback(client,{},"result = wf_id(song.tracks[0].clip_slots[2].clip)") == created["id"]
    renamed = run_workflow(client,{"mode":"apply","operations":[{"op":"clip.set","target":created,"values":{"name":"fresh"}}]})
    assert renamed["ok"] and slot.clip.name == "fresh"


def test_published_original_overrides_generic_cache_and_unknown_alias_rejected(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    target = targets[0]
    assert run_workflow(client,{"mode":"plan","operations":[set_op(target,mute=True)]})["ok"]
    remote._objects[target["id"]] = FakeTrack("wrong generic occupant")
    result = run_workflow(client,{"mode":"apply","operations":[set_op(target,mute=True)]})
    assert result["ok"] and song.tracks[0].mute
    assert remote._objects[target["id"]] is song.tracks[0]
    result = run_workflow(client,{"mode":"apply","operations":[set_op({"kind":"track","id":-999},mute=True)]})
    assert result["outcome"] == "failed"


def test_aliases_tombstones_survive_set_refresh_and_cap_never_evicts(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    first = song.tracks[0]
    first._live_ptr = 515151
    assert execute_callback(client,{},"result = wf_id(song.tracks[0])") == 515151
    first.invalid = True
    second = FakeTrack("second")
    second._live_ptr = 515151
    song.tracks[0] = second
    alias1 = execute_callback(client,{},"result = wf_id(song.tracks[0])")
    execute_callback(client,{},"result = wf_context()")
    song.master_track.invalid = True
    song.master_track = FakeTrack("new master")
    second.invalid = True
    third = FakeTrack("third")
    third._live_ptr = 515151
    song.tracks[0] = third
    alias2 = execute_callback(client,{},"wf_context()\nresult = wf_id(song.tracks[0])")
    assert alias2 < alias1 < 0 and remote._workflow_member_anchors[515151] is first
    remote._objects[515151] = third
    result = run_workflow(client,{"mode":"apply","operations":[set_op({"kind":"track","id":515151},mute=True)]})
    assert result["outcome"] == "failed" and not third.mute
    before = dict(remote._workflow_member_anchors)
    for i in range(4096-len(before)):
        remote._workflow_member_anchors[1000000+i] = FakeTrack("retained")
    with pytest.raises(ValueError,match="never evicted"):
        execute_callback(client,{},"result = wf_id(song.return_tracks[0])")
    assert all(remote._workflow_member_anchors[k] is v for k,v in before.items())


def test_return_alias_send_selection_and_retained_parameter_identity(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    old_return = song.return_tracks[0]
    old_return._live_ptr = 616161
    assert execute_callback(client,{},"result = wf_id(song.return_tracks[0])") == 616161
    old_return.invalid = True
    current_return = FakeTrack("fresh return")
    current_return._live_ptr = 616161
    song.return_tracks[0] = current_return
    alias = execute_callback(client,{},"result = wf_id(song.return_tracks[0])")
    parameter = FakeParameter("send",0)
    song.tracks[0].mixer_device.sends = [parameter]
    result = run_workflow(client,{"mode":"apply","operations":[{"op":"mixer.set","target":targets[0],
        "parameter":"send","return_id":alias,"value":0.25}]})
    assert result["ok"] and parameter.value == 0.25
    touched = result["touched"][0]
    assert touched["field"] == "send:"+str(alias) and touched["parameter_id"] == remote._object_id(parameter)


def test_creation_capacity_preflight_prevents_predictable_native_orphan(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    native_creates, group_events = [], []
    def create(index):
        native_creates.append(index)
        song.tracks.append(FakeTrack("would orphan"))
    song.create_audio_track = create
    song.begin_undo_step = lambda: group_events.append("begin")
    song.end_undo_step = lambda: group_events.append("end")
    execute_callback(client,{},"result = wf_id(song)")
    for i in range(4096-len(remote._workflow_member_anchors)):
        remote._workflow_member_anchors[2000000+i] = FakeTrack("tombstone")
    count = len(song.tracks)
    operations = [{"op":"track.create","type":"audio","name":"no orphan"}]
    for mode in ("plan","apply"):
        result = run_workflow(client,{"mode":mode,"undo":"group_if_supported","operations":operations})
        assert result["outcome"] == "failed" and "capacity" in result["error"]
    assert not native_creates and not group_events and len(song.tracks) == count


def test_whole_create_capacity_checked_after_static_ref_registration(monkeypatch):
    client, remote, song, targets = rig(monkeypatch)
    native_creates = []
    song.create_audio_track = lambda index: native_creates.append(index)
    execute_callback(client,{},"result = wf_id(song)")
    for i in range(4095-len(remote._workflow_member_anchors)):
        remote._workflow_member_anchors[3000000+i] = FakeTrack("tombstone")
    operations = [{"op":"track.create","type":"audio"},{"op":"track.create","type":"audio"}]
    result = run_workflow(client,{"mode":"apply","operations":operations})
    assert result["outcome"] == "failed" and "capacity" in result["error"] and not native_creates
