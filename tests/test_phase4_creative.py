"""Bounded transforms through actual Remote exec/batch/update callbacks."""
import copy
import types

import pytest

from test_workflows import rig, set_op
from workflows import run_workflow, validate_workflow, execute_callback
from workflow_history import SNAPSHOT_TAIL, WorkflowHistory, recover
from test_remote_bridge_fake_live import FakeClip, FakeTrack, FakeParameter


def note_rig(monkeypatch, arrangement=False):
    client, remote, song, targets = rig(monkeypatch)
    track = song.tracks[0]
    clip = track.clip_slots[0].clip
    if arrangement:
        track.arrangement_clips.append(clip)
        track.clip_slots[0].clip = None
        track.clip_slots[0].has_clip = False
    target = {"kind":"clip", "id":remote._object_id(clip), "parent_id":targets[0]["id"]}
    remote._objects[target["id"]] = clip
    if not arrangement:
        target["slot_index"] = 0
    return client, remote, song, targets, clip, {"op":"clip.notes.transform", "target":target, "velocity_delta":12}


def plan(client, op):
    report = run_workflow(client, {"mode":"plan", "operations":[op]})
    assert report["ok"], report
    return report["preflight"][0]["note_transform"]


def apply(client, op):
    op = dict(op, expected_notes_digest=plan(client, op)["inspected_notes_digest"])
    return run_workflow(client, {"mode":"apply", "operations":[op]})


@pytest.mark.parametrize("arrangement", [False, True])
def test_pure_plan_subset_full_fields_fractional_transform(monkeypatch, arrangement):
    client, remote, song, targets, clip, op = note_rig(monkeypatch, arrangement)
    original = copy.deepcopy(clip._notes[0].__dict__)
    clip._notes.append(types.SimpleNamespace(**dict(original, note_id=2, probability=0.3)))
    writes = []
    clip.apply_note_modifications = lambda notes: writes.append(notes)
    op.update(transpose=12, velocity_delta=0.5, note_ids=[1])
    evidence = plan(client, op)
    assert clip._notes[0].__dict__ == original and not writes
    assert evidence["selected_count"] == evidence["changed_count"] == 1
    assert evidence["inspected_count"] == 2
    result = run_workflow(client, {"mode":"apply", "operations":[dict(op, expected_notes_digest=evidence["inspected_notes_digest"])]})
    assert result["ok"] and result["results"][0]["verified"] and len(writes) == 1
    assert clip._notes[0].pitch == 72 and clip._notes[0].velocity == 40.5
    assert clip._notes[1].__dict__ == dict(original, note_id=2, probability=0.3)
    assert not result["recovery_eligible"] and not result["touched"]


@pytest.mark.parametrize("change", [{"transpose":128}, {"transpose":True}, {"velocity_delta":True}, {"velocity_delta":float("inf")}, {"note_ids":[1,1]}, {"note_ids":[True]}, {"transpose":0,"velocity_delta":0}, {"expected_notes_digest":"bad"}])
def test_strict_input_validation(monkeypatch, change):
    *_, op = note_rig(monkeypatch)
    with pytest.raises(ValueError):
        validate_workflow({"mode":"plan", "operations":[dict(op, **change)]})


def test_apply_digest_required_and_unselected_conflict(monkeypatch):
    client, remote, song, targets, clip, op = note_rig(monkeypatch)
    with pytest.raises(ValueError, match="requires expected"):
        run_workflow(client, {"mode":"apply", "operations":[op]})
    clip._notes.append(types.SimpleNamespace(**dict(clip._notes[0].__dict__, note_id=2)))
    op["note_ids"] = [1]
    digest = plan(client, op)["inspected_notes_digest"]
    clip._notes[1].release_velocity += 1
    report = run_workflow(client, {"mode":"apply", "operations":[set_op(targets[1], mute=True), dict(op, expected_notes_digest=digest)]})
    assert not report["ok"] and not song.tracks[1].mute and clip._notes[0].velocity == 40


@pytest.mark.parametrize("fault", ["range", "unknown", "audio", "api", "parent", "replacement", "invalid", "oversize"])
def test_preflight_refusals_zero_earlier_writes(monkeypatch, fault):
    client, remote, song, targets, clip, op = note_rig(monkeypatch)
    digest = plan(client, op)["inspected_notes_digest"]
    if fault == "range": op["velocity_delta"] = 126
    if fault == "unknown": op["note_ids"] = [999]
    if fault == "audio": clip.is_midi_clip = False
    if fault == "api": clip.apply_note_modifications = None
    if fault == "parent": op["target"]["parent_id"] = targets[1]["id"]
    if fault == "replacement": song.tracks[0].clip_slots[0].clip = None
    if fault == "invalid": clip.invalid = True
    if fault == "oversize": clip._notes = [types.SimpleNamespace(**dict(clip._notes[0].__dict__, note_id=i)) for i in range(513)]
    report = run_workflow(client, {"mode":"apply", "operations":[set_op(targets[1], mute=True), dict(op, expected_notes_digest=digest)]})
    assert not report["ok"] and not song.tracks[1].mute


def test_empty_zero_write_and_required_group_refusal(monkeypatch):
    client, remote, song, targets, clip, op = note_rig(monkeypatch)
    clip._notes = []
    clip.apply_note_modifications = lambda notes: pytest.fail("empty write")
    result = apply(client, op)
    assert result["ok"] and result["results"][0]["outcome"] == "no_change"
    assert result["results"][0]["verified"] and not result["results"][0]["write_acknowledged"]
    song.begin_undo_step = lambda: pytest.fail("begin excluded group")
    song.end_undo_step = lambda: None
    result = run_workflow(client, {"mode":"apply", "undo":"required_group", "operations":[dict(op, expected_notes_digest=plan(client,op)["inspected_notes_digest"])]})
    assert not result["ok"] and result["grouping"]["excluded_operations"] == [0]


@pytest.mark.parametrize("fault", ["native", "readback", "mismatch"])
def test_write_uncertainty_ack_prefix_no_replay(monkeypatch, fault):
    client, remote, song, targets, clip, op = note_rig(monkeypatch)
    digest = plan(client, op)["inspected_notes_digest"]
    writes = []
    def writer(notes):
        writes.append(1)
        if fault == "native": raise RuntimeError("after side effect")
        if fault == "mismatch": clip._notes[0].release_velocity += 1
        if fault == "readback": clip.get_all_notes_extended = lambda: (_ for _ in ()).throw(RuntimeError("readback failed"))
    clip.apply_note_modifications = writer
    report = run_workflow(client, {"mode":"apply", "operations":[set_op(targets[1],name="prefix"), dict(op, expected_notes_digest=digest), set_op(targets[1], mute=True)]})
    assert report["outcome"] == "uncertain" and not report["ok"] and writes == [1]
    assert report["applied_prefix"] == (1 if fault == "native" else 2)
    assert report["skipped"] == [2] and not song.tracks[1].mute
    assert not report["recovery_eligible"] and clip._notes[0].velocity == 52


def test_aggregate_note_budget_before_metadata(monkeypatch):
    client, remote, song, targets, clip, op = note_rig(monkeypatch)
    other = FakeClip("Other")
    song.tracks[1].clip_slots[0].clip = other
    song.tracks[1].clip_slots[0].has_clip = True
    other_target = dict(op["target"], id=remote._object_id(other), parent_id=targets[1]["id"])
    remote._objects[other_target["id"]] = other
    for c in (clip,other):
        c._notes = [types.SimpleNamespace(**dict(c._notes[0].__dict__, note_id=i)) for i in range(257)]
    op2 = dict(op,target=other_target)
    ops = [dict(o, expected_notes_digest=plan(client,o)["inspected_notes_digest"]) for o in (op,op2)]
    summaries = []
    original_summary = remote._note_summary
    remote._note_summary = lambda note: (summaries.append(note.note_id), original_summary(note))[1]
    report = run_workflow(client, {"mode":"apply", "operations":[set_op(targets[0], mute=True), *ops]})
    assert not report["ok"] and "inspection exceeds" in report["error"] and not song.tracks[0].mute
    assert len(summaries) == 257  # second native vector refuses before expansion


def test_mixed_history_refuses_compensation_and_retains_fields(monkeypatch):
    client, remote, song, targets, clip, op = note_rig(monkeypatch)
    op["expected_notes_digest"] = plan(client, op)["inspected_notes_digest"]
    report = run_workflow(client, {"mode":"apply", "operations":[set_op(targets[1],mute=True), op]})
    store = WorkflowHistory()
    entry = store.record(report)
    assert not entry["recovery_eligible"] and not entry["results"][1]["reversible"]
    assert len(entry["results"][1]["after"]["notes"][0]) == 9
    calls = len(client.calls)
    with pytest.raises(ValueError):
        recover(client, entry["workflow_id"], store)
    assert len(client.calls) == calls and song.tracks[1].mute


def test_dynamic_note_change_after_prefix_refuses_without_note_write(monkeypatch):
    client, remote, song, targets, clip, op = note_rig(monkeypatch)
    op["expected_notes_digest"] = plan(client,op)["inspected_notes_digest"]
    setter = remote._rpc_set
    def changing_setter(params):
        result = setter(params)
        clip._notes[0].probability = 0.5
        return result
    remote._rpc_set = changing_setter
    clip.apply_note_modifications = lambda notes: pytest.fail("stale note write")
    report = run_workflow(client,{"mode":"apply", "operations":[set_op(targets[1],mute=True),op]})
    assert report["applied_prefix"] == 1 and report["outcome"] == "failed"
    assert clip._notes[0].velocity == 40 and not report["results"][1]["verified"]


def test_same_clip_conflicts_and_exact_boundaries(monkeypatch):
    client, remote, song, targets, clip, op = note_rig(monkeypatch)
    result = run_workflow(client,{"mode":"plan","operations":[op,{"op":"clip.set", "target":op["target"],"values":{"name":"conflict"}}]})
    assert not result["ok"] and "conflicting" in result["error"]
    clip._notes[0].pitch, clip._notes[0].velocity = 0, 1.0
    result = apply(client, dict(op, transpose=127, velocity_delta=126))
    assert result["ok"] and clip._notes[0].pitch == 127 and clip._notes[0].velocity == 127
    assert apply(client, dict(op,transpose=-127,velocity_delta=-126))["ok"]
    assert clip._notes[0].pitch == 0 and clip._notes[0].velocity == 1


@pytest.mark.parametrize("mixer", [False,True])
@pytest.mark.parametrize("count", [8,32,64])
def test_snapshot_pin_once_per_item_metadata_and_mixer(monkeypatch,count,mixer):
    client, remote, song, _ = rig(monkeypatch)
    song.tracks = [FakeTrack(str(i)) for i in range(count)]
    for track in song.tracks:
        track.mixer_device.volume = FakeParameter("Volume", 0.5)
        track.mixer_device.panning = FakeParameter("Pan", 0, -1, 1)
        track.mixer_device.sends = [FakeParameter("Send",0.2)]
    scope = {"include_returns":False,"include_master":False,"scenes":False,"session":False,"arrangement":False,"routing":False,"mixer":mixer,"track_limit":64,"scene_limit":64}
    instrument = """
pin_calls = []
original_pin = wf_pin
def wf_pin(*args, **kwargs):
    pin_calls.append((args, kwargs))
    return original_pin(*args, **kwargs)
"""
    result = execute_callback(client,{"scope":scope},instrument + SNAPSHOT_TAIL + "\nresult['pin_calls'] = len(pin_calls)")
    assert result["pin_calls"] == count
    items = result["collections"]["tracks"]["items"]
    assert len(items) == count and items[0]["fields"]["name"] == "0"
    assert "MIDI note contents" in result["omissions"]
    if mixer:
        assert "volume" in items[0]["fields"] and "pan" in items[0]["fields"]


def test_plan_never_assigns_native_note_objects(monkeypatch):
    client, remote, song, targets, clip, op = note_rig(monkeypatch)
    assignments = []
    class NativeNote:
        def __setattr__(self, field, value):
            assignments.append((field,value))
            object.__setattr__(self,field,value)
    note = NativeNote()
    note.__dict__.update(clip._notes[0].__dict__)
    clip._notes = [note]
    clip.apply_note_modifications = lambda notes: pytest.fail("plan native write")
    assert plan(client,dict(op,transpose=12))["changed_count"] == 1
    assert not assignments
    op["expected_notes_digest"] = plan(client,op)["inspected_notes_digest"]
    report = run_workflow(client,{"mode":"apply", "operations":[op,{"op":"mixer.set","target":targets[1],"parameter":"volume","value":999}]})
    assert not report["ok"] and not assignments


def test_context_expiry_clip_and_parent_reuse_alias(monkeypatch):
    client, remote, song, targets, old, op = note_rig(monkeypatch)
    old._live_ptr = 424242
    op["target"]["id"] = 424242
    remote._objects[424242] = old
    digest = plan(client,op)["inspected_notes_digest"]
    old.invalid = True
    fresh = FakeClip("Replacement")
    fresh._live_ptr = 424242
    song.tracks[0].clip_slots[0].clip = fresh
    remote._objects[424242] = fresh
    refused = run_workflow(client,{"mode":"apply","operations":[dict(op,expected_notes_digest=digest)]})
    assert not refused["ok"] and fresh._notes[0].velocity == 40
    alias = execute_callback(client,{},"result = wf_id(song.tracks[0].clip_slots[0].clip)")
    assert alias < 0
    new_op = dict(op,target=dict(op["target"],id=alias))
    assert apply(client,new_op)["ok"] and fresh._notes[0].velocity == 52
    context = execute_callback(client,{},"result = wf_context()")
    digest = plan(client,new_op)["inspected_notes_digest"]
    song.master_track.invalid = True
    song.master_track = FakeTrack("New Main")
    refused = run_workflow(client,{"mode":"apply","context":{k:context[k] for k in ("bridge_nonce","generation")},"operations":[dict(new_op,expected_notes_digest=digest)]})
    assert not refused["ok"] and fresh._notes[0].velocity == 52


def test_lost_response_no_replay_and_group_close_after_ack(monkeypatch):
    client, remote, song, targets, clip, op = note_rig(monkeypatch)
    op["expected_notes_digest"] = plan(client,op)["inspected_notes_digest"]
    calls = []
    def lost(method,params):
        calls.append(1)
        remote._rpc_exec(params)
        raise TimeoutError("response lost after modification")
    client.request = lost
    report = run_workflow(client,{"mode":"apply","operations":[op]})
    assert report["outcome"] == "uncertain" and report["verification"] == "unavailable"
    assert calls == [1] and clip._notes[0].velocity == 52
    client.request = lambda method,params: remote._rpc_exec(params)
    del op["expected_notes_digest"]
    op["expected_notes_digest"] = plan(client,op)["inspected_notes_digest"]
    song.begin_undo_step = lambda: None
    song.end_undo_step = lambda: (_ for _ in ()).throw(RuntimeError("close failed"))
    report = run_workflow(client,{"mode":"apply","undo":"group_if_supported","operations":[op]})
    assert report["outcome"] == "partial" and report["applied_prefix"] == 1
    assert report["results"][0]["verified"] and report["results"][0]["write_acknowledged"]
    assert report["grouping"]["end_error"] and not report["recovery_eligible"]


@pytest.mark.parametrize("mode", ["plan","apply"])
def test_truncated_response_retains_ack_but_no_note_verification_claim(monkeypatch,mode):
    client, remote, song, targets, clip, op = note_rig(monkeypatch)
    op["expected_notes_digest"] = plan(client,op)["inspected_notes_digest"]
    def truncated_response(method,params):
        report = remote._rpc_exec(params)
        if mode == "apply":
            report["results"][0]["after"]["notes"] = [{"__truncated__":True}]
        else:
            report["preflight"][0]["note_transform"]["proposed_notes"] = [{"__truncated__":True}]
        return report
    client.request = truncated_response
    report = run_workflow(client,{"mode":mode,"operations":[op]})
    assert report["payload_truncated"] and report["note_verification"] == "unavailable_truncated"
    if mode == "plan":
        assert report["outcome"] == "planned" and clip._notes[0].velocity == 40
        return
    assert report["outcome"] == "uncertain" and not report["ok"]
    assert not report["results"][0]["verified"] and report["results"][0]["write_acknowledged"]
    assert report["applied_prefix"] == 1 and clip._notes[0].velocity == 52
