"""Bounded, process-local workflow evidence; recovery is conditional compensation."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import json
import uuid


RETENTION = 32
MAX_PAYLOAD_BYTES = 262144


class WorkflowHistory:
    def __init__(self, capacity=RETENTION, max_payload_bytes=MAX_PAYLOAD_BYTES):
        self.capacity = capacity
        self.max_payload_bytes = max_payload_bytes
        self.snapshots = OrderedDict()
        self.entries = OrderedDict()

    def _retain(self, store, item, prefix):
        item = deepcopy(item)
        key = prefix + uuid.uuid4().hex
        item["snapshot_id" if prefix == "snapshot-" else "workflow_id"] = key
        item["retention"] = {"process_local": True, "capacity": self.capacity,
                             "restart_loses_history": True, "max_payload_bytes": self.max_payload_bytes}
        encoded = json.dumps(item, ensure_ascii=True, allow_nan=False, default=str)
        if len(encoded.encode("utf-8")) > self.max_payload_bytes:
            item = {k: item[k] for k in ("snapshot_id", "workflow_id", "context", "retention", "outcome", "recovery_of") if k in item}
            item.update(payload_truncated=True, recovery_eligible=False,
                        unavailable=["Payload exceeded retention bound; complete evidence unavailable"])
        store[key] = item
        while len(store) > self.capacity:
            store.popitem(last=False)
        return deepcopy(item)

    def snapshot(self, result):
        return self._retain(self.snapshots, result, "snapshot-")

    def record(self, result):
        result = dict(result)
        touched = result.get("touched") or []
        dynamic_routing = any(t.get("field") in ("input_routing_type", "output_routing_type") and t.get("before") != t.get("after") for t in touched)
        missing_parameter_identity = any((t.get("field") in ("volume", "pan") or str(t.get("field", "")).startswith("send:")) and not t.get("parameter_id") for t in touched)
        result["recovery_eligible"] = bool(
            result.get("outcome") == "success" and touched
            and result.get("ok") is True
            and result.get("results")
            and result.get("context", {}).get("anchors_valid")
            and all(r.get("reversible") and r.get("verified") and r.get("outcome") == "success" for r in result["results"])
            and all(t.get("verified") and t.get("reversible") and "before" in t and "after" in t for t in touched)
            and not result.get("payload_truncated")
            and not dynamic_routing
            and not missing_parameter_identity
        )
        result["recovery_reasons"] = []
        if not result.get("context", {}).get("anchors_valid"):
            result["recovery_reasons"].append("Identity validity anchors unsupported")
        if dynamic_routing:
            result["recovery_reasons"].append("Routing type restoration changes available channels; inverse channel options cannot be verified before writes")
        if missing_parameter_identity:
            result["recovery_reasons"].append("Mixer parameter lifetime identity unavailable")
        if not result["recovery_eligible"] and not result["recovery_reasons"]:
            result["recovery_reasons"].append("Irreversible, uncertain, unverified or incomplete workflow evidence")
        result["recovery_limitations"] = ["Requires supported retained identity anchors, current membership and exact touched-field after values", "Physical set-replacement acceptance remains unverified", "No compensation for uncertain or irreversible operations"]
        return self._retain(self.entries, result, "workflow-")

    def get(self, key, snapshots=False):
        store = self.snapshots if snapshots else self.entries
        if key not in store:
            raise ValueError("Unknown, evicted, or previous-process %s" % ("snapshot" if snapshots else "workflow"))
        return deepcopy(store[key])

    def list(self, limit=16):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= RETENTION:
            raise ValueError("limit must be an integer from 1 to 32")
        keys = list(self.entries)[-limit:][::-1]
        return {"entries": [{k: self.entries[key].get(k) for k in ("workflow_id", "label", "outcome", "recovery_eligible", "recovery_of", "recovery_attempt")} for key in keys],
                "process_local": True, "restart_loses_history": True, "capacity": self.capacity}

    def snapshot_context(self, snapshot_id):
        snapshot = self.get(snapshot_id, snapshots=True)
        if snapshot.get("payload_truncated") or not snapshot.get("context", {}).get("anchors_valid"):
            raise ValueError("Snapshot context unavailable or evidence truncated")
        return {k: snapshot["context"][k] for k in ("bridge_nonce", "generation")}

    def diff(self, before_id, after_id):
        before, after = self.get(before_id, True), self.get(after_id, True)
        left, right = before.get("context", {}), after.get("context", {})
        if not left.get("anchors_valid") or not right.get("anchors_valid"):
            raise ValueError("Identity anchors unavailable or invalid; snapshots are read-only evidence")
        if any(not left.get(k) or left.get(k) != right.get(k) for k in ("bridge_nonce", "generation")):
            raise ValueError("Snapshots belong to different bridge/set contexts")
        result = {"before_id": before_id, "after_id": after_id, "added": [], "removed": [], "changed": [], "incomparable": [],
                  "identity_limitations": "Retained measured anchors only; no current Live probe or physically demonstrated replacement boundary",
                  "coverage_limitations": "Metadata only; notes, automation and device contents are unmeasured"}
        for field in sorted(set(before.get("overview", {})) | set(after.get("overview", {})) | set(before.get("overview_unavailable", {})) | set(after.get("overview_unavailable", {}))):
            if field not in before.get("overview", {}) or field not in after.get("overview", {}):
                result["incomparable"].append({"collection": "overview", "field": field, "reason": "Overview field unavailable or unmeasured"})
                continue
            x, y = before["overview"][field], after["overview"][field]
            if x != y:
                result["changed"].append({"collection": "overview", "field": field, "before": x, "after": y})
        a, b = before.get("collections", {}), after.get("collections", {})
        for name in sorted(set(a) | set(b)):
            ca, cb = a.get(name), b.get(name)
            if not ca or not cb or ca.get("scope") != cb.get("scope"):
                result["incomparable"].append({"collection": name, "reason": "Missing or different scope"})
                continue
            ai = {str(x["id"]): x for x in ca.get("items", [])}
            bi = {str(x["id"]): x for x in cb.get("items", [])}
            complete = ca.get("complete") and cb.get("complete") and not before.get("payload_truncated") and not after.get("payload_truncated")
            if complete:
                result["added"].extend({"collection": name, "item": bi[i]} for i in sorted(set(bi) - set(ai)))
                result["removed"].extend({"collection": name, "item": ai[i]} for i in sorted(set(ai) - set(bi)))
            else:
                result["incomparable"].append({"collection": name, "reason": "Enumeration incomplete; additions/removals unavailable"})
            for identity in sorted(set(ai) & set(bi)):
                x, y = ai[identity], bi[identity]
                for field in sorted(set(x.get("fields", {})) | set(y.get("fields", {}))):
                    if field not in x.get("fields", {}) or field not in y.get("fields", {}):
                        result["incomparable"].append({"collection": name, "id": x["id"], "field": field, "reason": "Field unmeasured"})
                    elif x["fields"][field] != y["fields"][field]:
                        result["changed"].append({"collection": name, "id": x["id"], "field": field, "before": x["fields"][field], "after": y["fields"][field]})
                if x.get("index") != y.get("index"):
                    result["changed"].append({"collection": name, "id": x["id"], "field": "index", "before": x.get("index"), "after": y.get("index")})
                for field in sorted(set(x.get("unavailable", {})) | set(y.get("unavailable", {}))):
                    result["incomparable"].append({"collection": name, "id": x["id"], "field": field, "reason": "Unsupported or failed read"})
        if before.get("payload_truncated") or after.get("payload_truncated"):
            result["incomparable"].append({"reason": "Retained payload truncated"})
        return result


HISTORY = WorkflowHistory()


SNAPSHOT_TAIL = r'''
context = wf_context(payload.get("context"))
scope = payload["scope"]
collections = {}
omissions = ["MIDI note contents", "automation", "device state", "audio sample contents"]
remaining_items = [512]
def snapshot_item(obj, kind, index, fields, parent_id=None, slot_index=None):
    target = {"kind": kind, "id": wf_id(obj)}
    if parent_id is not None: target["parent_id"] = parent_id
    if slot_index is not None: target["slot_index"] = slot_index
    values, unavailable = {}, {}
    try:
        resolved = wf_pin(**target)
        pin_error = None
    except Exception as exc:
        resolved, pin_error = None, str(exc)[:240]
    for field in fields:
        try:
            if pin_error is not None:
                raise ValueError(pin_error)
            value = wf_read_resolved(resolved, [field])[field]
            if len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode()) > 4096:
                raise ValueError("Field payload exceeds snapshot bound")
            values[field] = value
        except Exception as exc: unavailable[field] = str(exc)[:240]
    return {"id": target["id"], "native_id": this._object_id(obj), "target": target, "index": index, "fields": values, "unavailable": unavailable}
def collection(name, objects, limit, kind, fields, parent_id=None, selector="all"):
    objects = list(objects)
    bound = min(limit, remaining_items[0])
    remaining_items[0] -= min(len(objects), bound)
    collections[name] = {"scope": selector, "complete": len(objects) <= bound,
                         "total": len(objects), "items": [snapshot_item(o, kind, i, fields, parent_id) for i,o in enumerate(objects[:bound])]}
    return objects[:bound]
tracks = list(song.tracks)
selected = scope.get("track_ids")
if selected is not None:
    tracks = [t for t in tracks if wf_id(t) in selected]
track_fields = ["name", "mute", "solo", "arm", "color"]
if scope["mixer"]:
    track_fields += ["volume", "pan"] + ["send:" + str(wf_id(t)) for t in list(song.return_tracks)[:64]]
    if len(song.return_tracks) > 64: omissions.append("Send fields beyond 64 return tracks")
if scope["routing"]:
    for direction in ("input", "output"):
        for part in ("type", "channel"):
            track_fields += [direction + "_routing_" + part, "available_" + direction + "_routing_" + part + "s"]
measured = collection("tracks", tracks, scope["track_limit"], "track", track_fields, selector=selected if selected is not None else "all")
for item in collections["tracks"]["items"]:
    item["index"] = next(i for i,t in enumerate(song.tracks) if wf_id(t) == item["id"])
if selected is not None and len(tracks) != len(selected):
    collections["tracks"]["complete"] = False
    collections["tracks"]["unavailable"] = "Requested track is no longer present"
if scope["include_returns"]:
    measured += collection("returns", song.return_tracks, scope["track_limit"], "track", track_fields)
if scope["include_master"]:
    measured += collection("master", [song.master_track], 1, "track", ["name", "volume", "pan"])
if scope["scenes"]:
    collection("scenes", song.scenes, scope["scene_limit"], "scene", ["name", "color"])
clip_fields = ["name", "muted", "looping", "loop_start", "loop_end", "start_marker", "end_marker"]
for track in measured:
    tid = wf_id(track)
    if scope["session"]:
        try:
            slots = list(track.clip_slots)
            items, clips = [], []
            slot_bound = min(scope["slot_limit"], remaining_items[0] // 2)
            for i, slot in enumerate(slots[:slot_bound]):
                item = {"id": wf_id(slot), "index": i, "fields": {"has_clip": bool(slot.has_clip)}, "unavailable": {}}
                if i < len(song.scenes): item["fields"]["scene_id"] = wf_id(song.scenes[i])
                if slot.has_clip:
                    clip = snapshot_item(slot.clip, "clip", i, clip_fields, tid, i)
                    item["fields"]["clip_id"] = clip["id"]
                    clips.append(clip)
                else: item["fields"]["clip_id"] = None
                items.append(item)
            remaining_items[0] -= len(items) + len(clips)
            collections["slots:" + str(tid)] = {"scope": {"parent_id": tid}, "complete": len(slots) <= slot_bound, "total": len(slots), "items": items}
            collections["clips:" + str(tid)] = {"scope": {"parent_id": tid}, "complete": len(slots) <= slot_bound, "items": clips}
        except Exception as exc:
            collections["slots:" + str(tid)] = {"scope": {"parent_id": tid}, "complete": False, "items": [], "unavailable": str(exc)[:240]}
    if scope["arrangement"]:
        try: collection("arrangement:" + str(tid), track.arrangement_clips, scope["arrangement_limit"], "clip", clip_fields + ["start_time", "end_time"], tid)
        except Exception as exc:
            collections["arrangement:" + str(tid)] = {"scope": "all", "complete": False, "items": [], "unavailable": str(exc)[:240]}
overview, overview_unavailable = {}, {}
for field in ("tempo", "signature_numerator", "signature_denominator"):
    try: overview[field] = getattr(song, field)
    except Exception as exc: overview_unavailable[field] = str(exc)[:240]
result = {"context": context, "scope": scope, "overview": overview, "overview_unavailable": overview_unavailable, "collections": collections, "omissions": omissions,
          "identity_limitations": "Measured retained anchors only; physical set-replacement acceptance unverified"}
if len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode()) > 200000:
    result["collections"] = {}
    result["payload_truncated"] = True
    result["omissions"].append("Snapshot payload exceeded 200000 bytes; all collection comparison unavailable")
'''


RECOVERY_TAIL = r'''
entry = payload["entry"]
try:
    context = wf_context(entry.get("context"))
    if not context.get("anchors_valid"):
        raise ValueError("Recovery requires supported valid retained identity anchors")
    for touched in entry["touched"]:
        target = touched["target"]
        wf_pin(**target)
        current = wf_read(target, [touched["field"]])[touched["field"]]
        if current != touched["after"]:
            raise ValueError("Recovery conflict on touched field " + touched["field"])
        if "parameter_id" in touched:
            parameter = wf_parameter(target, touched["field"])
            if wf_id(parameter) != touched["parameter_id"]:
                raise ValueError("Recovery mixer parameter lifetime changed")
    for operation in payload["request"]["operations"]:
        if operation["op"] == "routing.set":
            target, direction = operation["target"], operation["direction"]
            obj = wf_pin(**target)
            current_type = wf_read(target, [direction + "_routing_type"])[direction + "_routing_type"]
            if current_type != operation["type"]:
                raise ValueError("Routing type-changing compensation cannot preflight inverse channel options before writes")
            wf_select(getattr(obj, "available_" + direction + "_routing_types"), operation["type"])
            wf_select(getattr(obj, "available_" + direction + "_routing_channels"), operation["channel"])
except Exception as exc:
    result = {"ok": False, "outcome": "failed", "phase": "recovery_preflight", "mutation_attempted": False,
              "error": str(exc)[:4096], "results": [], "touched": [], "applied_prefix": 0}
else:
    result = wf_run(payload["request"])
'''


def inverse_operations(entry):
    if not entry.get("recovery_eligible") or entry.get("payload_truncated"):
        raise ValueError("Entry contains irreversible, uncertain, unverified or incomplete evidence")
    # Coalesce repeated writes: guard final after, restore original before once.
    touched = OrderedDict()
    for item in entry["touched"]:
        key = (json.dumps(item["target"], sort_keys=True), item["field"])
        if key in touched:
            if touched[key]["after"] != item["before"]:
                raise ValueError("Discontinuous touched-field evidence")
            if touched[key].get("parameter_id") != item.get("parameter_id"):
                raise ValueError("Mixer parameter lifetime changed within retained evidence")
            touched[key]["after"] = item["after"]
        else:
            touched[key] = deepcopy(item)
    operations, routing, properties = [], OrderedDict(), OrderedDict()
    for item in reversed(list(touched.values())):
        target, field = item["target"], item["field"]
        if field in ("volume", "pan") or field.startswith("send:"):
            operation = {"op": "mixer.set", "target": target, "parameter": field.split(":")[0], "value": item["before"], "expected_value": item["after"]}
            if field.startswith("send:"): operation["return_id"] = int(field.split(":")[1])
            operations.append(operation)
        elif field in ("input_routing_type", "input_routing_channel", "output_routing_type", "output_routing_channel"):
            direction, _, part = field.split("_")
            key = (json.dumps(target, sort_keys=True), direction)
            operation = routing.setdefault(key, {"op": "routing.set", "target": target, "direction": direction, "expected": {}})
            operation[part] = item["before"]
            operation["expected"][part] = item["after"]
        elif target["kind"] in ("track", "scene", "clip") and field in ("name", "mute", "solo", "arm", "muted", "looping", "loop_start", "loop_end"):
            key = json.dumps(target, sort_keys=True)
            operation = properties.setdefault(key, {"op": target["kind"] + ".set", "target": target, "values": {}, "expected": {}})
            operation["values"][field] = item["before"]
            operation["expected"][field] = item["after"]
        else:
            raise ValueError("Unsupported compensation field " + field)
    for operation in routing.values():
        # Type changes can silently change channel; require both inverse fields.
        if "type" in operation and "channel" not in operation:
            raise ValueError("Routing type restoration requires verified channel evidence")
        if "type" not in operation:
            raise ValueError("Routing restoration requires verified type evidence")
        operations.append(operation)
    operations.extend(properties.values())
    return list(touched.values()), operations


def recover(bridge, entry_id, history=HISTORY):
    from workflows import execute_callback, validate_workflow
    entry = history.get(entry_id)
    if entry.get("recovery_attempt"):
        raise ValueError("Recovery already attempted; repeated, partial or uncertain compensation cannot be replayed")
    touched, operations = inverse_operations(entry)
    entry["touched"] = touched
    attempt = "recovery-" + uuid.uuid4().hex
    request = {"mode": "apply", "operations": operations, "context": entry.get("context"), "undo": "group_if_supported", "label": "Recover " + entry_id}
    request["context"] = {k: entry["context"][k] for k in ("bridge_nonce", "generation")}
    validate_workflow(request)
    # Mark before sending: a lost response must never permit a second write.
    history.entries[entry_id]["recovery_attempt"] = attempt
    try:
        result = execute_callback(bridge, {"entry": entry, "request": request}, RECOVERY_TAIL)
    except Exception as exc:
        diagnostic = exc.to_dict() if callable(getattr(exc, "to_dict", None)) else {"message": str(exc), "outcome": "uncertain"}
        result = {"outcome": diagnostic.get("outcome", "uncertain"), "error": diagnostic, "verification": "unavailable", "touched": [], "results": []}
    result = dict(result, recovery_of=entry_id, recovery_attempt=attempt)
    original = history.entries[entry_id]
    original["recovery_eligible"] = False
    retained = history.record(result)
    original["recovery_result_id"] = retained["workflow_id"]
    if entry_id not in history.entries:
        history.entries[retained["workflow_id"]]["original_entry_evicted"] = True
        retained["original_entry_evicted"] = True
    return retained


def take_snapshot(bridge, arguments, history=HISTORY):
    from workflows import execute_callback
    scope = {"track_limit": 32, "scene_limit": 32, "slot_limit": 32, "arrangement_limit": 32,
             "include_returns": True, "include_master": True, "scenes": True, "session": True,
             "arrangement": False, "mixer": True, "routing": True}
    provided = arguments.get("scope", {})
    if set(provided) - (set(scope) | {"track_ids"}):
        raise ValueError("Unknown snapshot scope field")
    scope.update(provided)
    for name in ("track_limit", "scene_limit", "slot_limit", "arrangement_limit"):
        if isinstance(scope[name], bool) or not isinstance(scope[name], int) or not 1 <= scope[name] <= 64:
            raise ValueError(name + " must be an integer from 1 to 64")
    for name in ("include_returns", "include_master", "scenes", "session", "arrangement", "mixer", "routing"):
        if not isinstance(scope[name], bool): raise ValueError(name + " must be boolean")
    if "track_ids" in scope:
        ids = scope["track_ids"]
        if not isinstance(ids, list) or len(ids) > 64 or any(isinstance(i, bool) or not isinstance(i, int) or i == 0 or abs(i) > 9007199254740991 for i in ids) or len(ids) != len(set(ids)):
            raise ValueError("track_ids must contain at most 64 distinct nonzero signed safe-integer workflow IDs")
        scope["track_ids"] = sorted(ids)
    return history.snapshot(execute_callback(bridge, {"scope": scope, "context": arguments.get("context")}, SNAPSHOT_TAIL))


def tool_specs(bridge, history=None):
    from workflows import ID
    # Server-owned closure: duck/slotted bridge implementations need no attributes.
    history = WorkflowHistory() if history is None else history
    scope_properties = {name: {"type": "integer", "minimum": 1, "maximum": 64} for name in ("track_limit", "scene_limit", "slot_limit", "arrangement_limit")}
    scope_properties.update({name: {"type": "boolean"} for name in ("include_returns", "include_master", "scenes", "session", "arrangement", "mixer", "routing")})
    scope_properties["track_ids"] = {"type": "array", "maxItems": 64, "uniqueItems": True, "items": ID}
    def history_handler(args):
        action = args["action"]
        if action == "list": return history.list(args.get("limit", 16))
        if action == "get": return history.get(args["workflow_id"])
        if action == "recover": return recover(bridge, args["workflow_id"], history)
        raise ValueError("Unknown history action")
    return [
        {"name": "live_snapshot", "description": "One-callback bounded metadata snapshot with measured identity and explicit omissions; process-local retention.",
         "inputSchema": {"type": "object", "additionalProperties": False, "properties": {"scope": {"type": "object", "additionalProperties": False, "properties": scope_properties}, "context": {"type": "object", "additionalProperties": False, "required": ["bridge_nonce", "generation"], "properties": {"bridge_nonce": {"type": "string", "maxLength": 256}, "generation": {"type": "string", "maxLength": 256}}}}}, "handler": lambda args: take_snapshot(bridge, args, history)},
        {"name": "live_snapshot_diff", "description": "Local-only retained snapshot diff. Add/remove requires complete matching coverage. Physical set-replacement boundary unverified.",
         "inputSchema": {"type": "object", "additionalProperties": False, "required": ["before_id", "after_id"], "properties": {"before_id": {"type": "string"}, "after_id": {"type": "string"}}},
         "handler": lambda args: history.diff(args["before_id"], args["after_id"])},
        {"name": "live_workflow_history", "description": "List/get process-local workflow evidence or explicitly attempt conditional compensation. Recovery requires supported valid retained anchors; physical replacement acceptance unverified. Never retries unknown or partial writes.",
         "inputSchema": {"type": "object", "required": ["action"], "additionalProperties": False, "properties": {"action": {"enum": ["list", "get", "recover"]}, "workflow_id": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 32}}, "oneOf": [
             {"type": "object", "additionalProperties": False, "required": ["action"], "properties": {"action": {"const": "list"}, "limit": {"type": "integer", "minimum": 1, "maximum": 32}}},
             {"type": "object", "additionalProperties": False, "required": ["action", "workflow_id"], "properties": {"action": {"enum": ["get", "recover"]}, "workflow_id": {"type": "string"}}}]}, "handler": history_handler},
    ]
