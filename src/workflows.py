"""Bounded typed workflows compiled to one existing Remote exec callback."""
from __future__ import annotations

import json
import math
from pathlib import Path

from mcp_stdio import _validate


def _object(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


NUMBER = {"type": "number"}
BEAT = {"type": "number", "minimum": 0}
ID = {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 9007199254740991},
                {"type": "integer", "minimum": -9007199254740991, "maximum": -1}]}
NAME = {"type": "string", "maxLength": 256}
TARGET = _object({"kind": {"enum": ["track", "scene", "clip", "slot"]}, "id": ID,
                  "parent_id": ID, "slot_index": {"type": "integer", "minimum": 0}}, ("kind", "id"))
SELECTOR = _object({"display_name": NAME, "identifier": {"anyOf": [{"type": "string"}, {"type": "integer"}]}})
SELECTOR["anyOf"] = [{"required": ["display_name"]}, {"required": ["identifier"]}]
NOTE = _object({"pitch": {"type": "integer", "minimum": 0, "maximum": 127},
                "start_time": BEAT, "duration": {"type": "number", "exclusiveMinimum": 0},
                "velocity": {"type": "number", "minimum": 1, "maximum": 127},
                "mute": {"type": "boolean"}}, ("pitch", "start_time", "duration", "velocity"))


def _variant(op, properties, required=()):
    if "target" in properties:
        kind = op.split(".")[0]
        if op == "clip.create":
            kind = "slot"
        elif kind in ("mixer", "routing") or op == "arrangement.import":
            kind = "track"
        elif op == "arrangement.duplicate":
            kind = "clip"
        target = _object({**TARGET["properties"], "kind": {"const": kind}},
                         ("kind", "id", "parent_id", "slot_index") if kind == "slot" else
                         ("kind", "id", "parent_id") if kind == "clip" else ("kind", "id"))
        properties = {**properties, "target": target}
    return _object({"op": {"const": op}, **properties}, ("op", *required))


OPERATION_SCHEMAS = []
for kind, fields in (("track", {"name": NAME, "mute": {"type": "boolean"}, "solo": {"type": "boolean"}, "arm": {"type": "boolean"}}),
                     ("scene", {"name": NAME}),
                     ("clip", {"name": NAME, "muted": {"type": "boolean"}, "looping": {"type": "boolean"}, "loop_start": BEAT, "loop_end": BEAT})):
    values = _object(fields)
    values["minProperties"] = 1
    OPERATION_SCHEMAS.append(_variant(kind + ".set", {"target": TARGET, "values": values, "expected": _object(fields)}, ("target", "values")))
for kind in ("track", "scene"):
    props = {"index": {"type": "integer", "minimum": -1}, "name": NAME}
    if kind == "track":
        props["type"] = {"enum": ["midi", "audio"]}
    OPERATION_SCHEMAS.append(_variant(kind + ".create", props, ("type",) if kind == "track" else ()))
for kind in ("track", "scene", "clip"):
    OPERATION_SCHEMAS.append(_variant(kind + ".delete", {"target": TARGET, "confirm_delete": {"const": True}}, ("target", "confirm_delete")))
for op in ("scene.launch", "clip.launch", "clip.stop"):
    OPERATION_SCHEMAS.append(_variant(op, {"target": TARGET}, ("target",)))
OPERATION_SCHEMAS.extend([
    _variant("clip.notes.transform", {
        "target": TARGET,
        "transpose": {"type": "integer", "minimum": -127, "maximum": 127, "description": "At least one nonzero transpose or velocity_delta is required; resulting pitches strictly 0..127, no clamp."},
        "velocity_delta": {"type": "number", "minimum": -126, "maximum": 126, "description": "Additive finite offset, fractional values supported; resulting velocities strictly 1..127, no clamp."},
        "note_ids": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 9007199254740991}, "minItems": 1, "maxItems": 512, "uniqueItems": True},
        "expected_notes_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "Required for apply, optional for plan. SHA256 of all nine declared note fields, including unselected notes; not expression/automation."},
    }, ("target",)),
    _variant("clip.create", {"target": TARGET, "expected_clip_id": {"anyOf": [ID, {"const": None}]},
                            "length": {"type": "number", "exclusiveMinimum": 0},
                            "notes": {"type": "array", "items": NOTE, "maxItems": 512},
                            "name": NAME, "replace": {"type": "boolean"}}, ("target", "expected_clip_id", "length", "notes")),
    _variant("arrangement.duplicate", {"target": TARGET, "destination_time": BEAT}, ("target", "destination_time")),
    _variant("arrangement.import", {"target": TARGET, "file_path": {"type": "string", "minLength": 1, "maxLength": 4096},
                                    "destination_time": BEAT, "name": NAME}, ("target", "file_path", "destination_time")),
    _variant("mixer.set", {"target": TARGET, "parameter": {"enum": ["volume", "pan", "send"]}, "return_id": ID,
                           "value": NUMBER, "expected_value": NUMBER}, ("target", "parameter", "value")),
    _variant("routing.set", {"target": TARGET, "direction": {"enum": ["input", "output"]}, "type": SELECTOR,
                             "channel": SELECTOR, "expected": _object({"type": SELECTOR, "channel": SELECTOR})}, ("target", "direction", "type")),
])
WORKFLOW_SCHEMA = _object({"mode": {"enum": ["plan", "apply"]},
                          "operations": {"type": "array", "items": {"oneOf": OPERATION_SCHEMAS}, "minItems": 1, "maxItems": 32},
                          "label": NAME, "expected_set_signature": {"type": "string", "maxLength": 256},
                          "context": _object({"bridge_nonce": NAME, "generation": NAME}, ("bridge_nonce", "generation")),
                          "snapshot_id": NAME,
                          "undo": {"enum": ["none", "group_if_supported", "required_group"],
                                   "description": "Required grouping requires native begin/end and the candidate field scope (track mute). Participation remains unverified; other fields/actions are explicitly excluded."}}, ("mode", "operations"))


def validate_workflow(args):
    _validate(args, WORKFLOW_SCHEMA, "arguments")
    # JSON-schema number constraints alone do not reject all nonfinite Python values.
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("workflow numbers must be finite")
        if isinstance(value, dict):
            for child in value.values():
                finite(child)
        elif isinstance(value, list):
            for child in value:
                finite(child)
    finite(args)
    if len(json.dumps(args, allow_nan=False).encode()) > 256_000:
        raise ValueError("workflow payload exceeds 256000 bytes")
    for op in args["operations"]:
        name = op["op"]
        if name == "clip.notes.transform":
            if not op.get("transpose", 0) and not op.get("velocity_delta", 0):
                raise ValueError("note transform requires a nonzero transpose or velocity_delta")
            if args["mode"] == "apply" and "expected_notes_digest" not in op:
                raise ValueError("note transform apply requires expected_notes_digest from plan")
            digest = op.get("expected_notes_digest")
            if digest is not None and (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
                raise ValueError("expected_notes_digest must be a lowercase SHA256 hex digest")
            if "note_ids" in op and len(set(op["note_ids"])) != len(op["note_ids"]):
                raise ValueError("note_ids must be distinct")
        target = op.get("target", {})
        expected_kind = name.split(".")[0]
        if name == "clip.create":
            expected_kind = "slot"
        elif expected_kind in ("mixer", "routing") or name == "arrangement.import":
            expected_kind = "track"
        elif name == "arrangement.duplicate":
            expected_kind = "clip"
        if target and target["kind"] != expected_kind:
            raise ValueError("wrong target kind for " + name)
        if target.get("kind") in ("clip", "slot") and "parent_id" not in target:
            raise ValueError("clip/slot targets require parent_id")
        if target.get("kind") == "slot" and "slot_index" not in target:
            raise ValueError("slot target requires slot_index")
        if name == "mixer.set" and (op["parameter"] == "send") != ("return_id" in op):
            raise ValueError("return_id is required only for sends")
        if name == "clip.create" and op["expected_clip_id"] is not None and not op.get("replace"):
            raise ValueError("occupied slot creation requires explicit replace")
        if name == "arrangement.import" and not Path(op["file_path"]).is_file():
            raise ValueError("audio import file does not exist")
        if name.endswith(".create") and "length" in op and op["length"] <= 0:
            raise ValueError("clip length must be positive")
        for note in op.get("notes", []):
            if note["duration"] <= 0:
                raise ValueError("note duration must be positive")
        if not op.get("values", {"_": 1}):
            raise ValueError("values must not be empty")
    return args


# Fixed source only: request data is separately JSON serialized; no authored code.
RUNTIME_CODE = r'''
import uuid
import hashlib
import math

def wf_validity():
    valid = getattr(getattr(Live, 'Base', None), 'liveobj_valid', None)
    if callable(valid):
        return valid, 'Live.Base.liveobj_valid'
    try:
        from ableton.v2.base import liveobj_valid
    except ImportError:
        return None, 'unavailable'
    if callable(liveobj_valid):
        return liveobj_valid, 'ableton.v2.base.liveobj_valid'
    return None, 'unavailable'

def wf_id(value):
    native_id = this._object_id(value)
    if native_id <= 0 or native_id > 9007199254740991:
        raise ValueError('native object ID outside positive safe integer namespace')
    anchors = getattr(this, '_workflow_member_anchors', None)
    if anchors is None:
        anchors = {}
        this._workflow_member_anchors = anchors
    native_aliases = getattr(this, '_workflow_native_aliases', None)
    if native_aliases is None:
        # Adopt previously retained native registrations without discarding claims.
        native_aliases = {key:[key] for key in anchors if key > 0}
        this._workflow_native_aliases = native_aliases
    valid, validity_source = wf_validity()
    if callable(valid) and not valid(value):
        raise ValueError('cannot register invalid fresh object')
    published = native_aliases.get(native_id, [])
    for object_id in published:
        old = anchors[object_id]
        if callable(valid) and not valid(old):
            continue
        if old is value or (callable(valid) and old == value):
            this._objects[object_id] = old
            return object_id
    if published and not callable(valid):
        raise ValueError('cannot qualify reused native ID without native validity helper')
    if len(anchors) >= 4096:
        raise ValueError('workflow identity retention bound reached; originals are never evicted')
    if not published:
        object_id = native_id
    else:
        object_id = getattr(this, '_workflow_alias_counter', 0) - 1
        while object_id in this._objects or object_id in anchors:
            object_id -= 1
        if object_id < -9007199254740991:
            raise ValueError('workflow alias namespace exhausted')
        this._workflow_alias_counter = object_id
    anchors[object_id] = value
    native_aliases.setdefault(native_id, []).append(object_id)
    this._objects[object_id] = value
    return object_id

def wf_context(expected=None):
    valid, validity_source = wf_validity()
    retained = getattr(this, '_workflow_context_anchor', None)
    current = song.master_track
    if retained is None:
        retained = {'bridge_nonce': uuid.uuid4().hex, 'generation': uuid.uuid4().hex,
                    'song': song, 'master': current}
        this._workflow_context_anchor = retained
    anchors_valid = (callable(valid) and bool(valid(retained['song'])) and bool(valid(retained['master']))
                     and bool(valid(song)) and bool(valid(current)))
    same = (anchors_valid and retained['song'] == song and retained['master'] == current
            and this._object_id(retained['song']) == this._object_id(song)
            and this._object_id(retained['master']) == this._object_id(current))
    if not same and expected:
        raise ValueError('workflow context expired or anchors unsupported')
    if not same and callable(valid):
        retained = dict(retained, generation=uuid.uuid4().hex, song=song, master=current)
        this._workflow_context_anchor = retained
        anchors_valid = bool(valid(song)) and bool(valid(current))
    context = {'bridge_nonce': retained['bridge_nonce'], 'generation': retained['generation'],
               'anchors_valid': bool(anchors_valid), 'physical_verified': False,
               'validity_source': validity_source,
               'capability': 'measured_validity_anchors' if anchors_valid else 'unavailable_validity_anchors'}
    if expected and (expected.get('bridge_nonce') != context['bridge_nonce'] or expected.get('generation') != context['generation']):
        raise ValueError('workflow context mismatch')
    return context

def wf_pin(kind, id, parent_id=None, slot_index=None):
    original = getattr(this, '_workflow_member_anchors', {}).get(id)
    if id < 0 and original is None:
        raise ValueError('unknown qualified workflow alias')
    obj = original if original is not None else this._resolve({'id': id})
    valid, validity_source = wf_validity()
    if original is not None and callable(valid) and not valid(original):
        raise ValueError('original pinned member invalidated or replaced')
    if kind == 'track':
        members = list(song.tracks) + list(song.return_tracks) + [song.master_track]
    elif kind == 'scene':
        members = list(song.scenes)
    elif kind in ('slot', 'clip'):
        if parent_id is None:
            raise ValueError('missing parent_id')
        parent = wf_pin('track', parent_id)
        slots = list(parent.clip_slots)
        if kind == 'slot':
            if slot_index is None or slot_index >= len(slots) or slots[slot_index] != obj:
                raise ValueError('slot position or membership changed')
            members = [slots[slot_index]]
        else:
            members = [s.clip for s in slots if s.has_clip] + list(getattr(parent, 'arrangement_clips', ()))
            if slot_index is not None and (slot_index >= len(slots) or not slots[slot_index].has_clip or slots[slot_index].clip != obj):
                raise ValueError('Session clip occupancy changed')
    else:
        raise ValueError('unsupported target kind')
    if not any(member == obj and wf_id(member) == id for member in members):
        raise ValueError('target no longer belongs to current set/parent')
    valid, validity_source = wf_validity()
    if callable(valid) and not valid(obj):
        raise ValueError('target invalidated')
    wf_id(obj)
    this._objects[id] = obj
    return obj

def wf_route(value):
    result = {'display_name': str(value.display_name)[:256]}
    identifier = getattr(value, 'identifier', None)
    if isinstance(identifier, (str, int)):
        result['identifier'] = identifier
    return result

def wf_select(options, selector):
    matches = [o for o in options if all(wf_route(o).get(k) == v for k,v in selector.items())]
    if len(matches) != 1:
        raise ValueError('routing option absent or ambiguous')
    return matches[0]

def wf_parameter(target, field):
    track = wf_pin(**target)
    return wf_parameter_resolved(track, field)

def wf_parameter_resolved(track, field):
    mixer = track.mixer_device
    if field == 'volume':
        return mixer.volume
    if field == 'pan':
        return mixer.panning
    if field.startswith('send:'):
        return_id = int(field.split(':')[1])
        returns = list(song.return_tracks)
        indexes = [i for i,t in enumerate(returns) if wf_id(t) == return_id]
        if len(indexes) != 1 or indexes[0] >= len(mixer.sends):
            raise ValueError('send return membership changed')
        return mixer.sends[indexes[0]]
    raise ValueError('unsupported mixer field')

def wf_read(target, fields):
    obj = wf_pin(**target)
    return wf_read_resolved(obj, fields)

def wf_read_resolved(obj, fields):
    result = {}
    for field in fields:
        if field in ('volume', 'pan') or field.startswith('send:'):
            value = wf_parameter_resolved(obj, field).value
        elif field.startswith('available_') and '_routing_' in field:
            options = list(getattr(obj, field))
            if len(options) > 128:
                raise ValueError('routing options exceed evidence bound')
            value = [wf_route(option) for option in options]
        elif field in ('input_routing_type', 'input_routing_channel', 'output_routing_type', 'output_routing_channel'):
            value = wf_route(getattr(obj, field))
        else:
            value = getattr(obj, field)
        if not isinstance(value, (str, int, float, bool, type(None), dict, list)):
            raise ValueError('non scalar workflow evidence')
        if isinstance(value, str) and len(value) > 256:
            raise ValueError('workflow evidence too long')
        result[field] = value
    return result

def wf_batch(operations):
    return this._rpc_batch({'operations': operations, 'max_depth': 12, 'max_items': 1024, 'max_string_length': 4096})

def wf_set_op(obj, field, value):
    return {'method': 'set', 'params': {'ref': {'id': wf_id(obj)}, 'property': field, 'value': value}}

def wf_call_op(obj, method, args=()):
    return {'method': 'call', 'params': {'ref': {'id': wf_id(obj)}, 'method': method, 'args': list(args)}}

def wf_creation_capacity(count):
    if 4096 - len(getattr(this, '_workflow_member_anchors', {})) < count:
        raise ValueError('insufficient workflow identity capacity for fresh created objects')

def wf_notes(obj, remaining=512):
    if not getattr(obj, 'is_midi_clip', False):
        raise ValueError('note transform requires a MIDI clip')
    if not all(callable(getattr(obj, method, None)) for method in ('get_all_notes_extended', 'apply_note_modifications')):
        raise ValueError('note transform requires extended note APIs; refusing legacy API')
    native = obj.get_all_notes_extended()
    # Native acquisition is full-vector, not streaming; refuse before Python expansion.
    count = len(native)
    if count > remaining:
        raise ValueError('note inspection exceeds 512-note workflow bound')
    summaries = [this._note_summary(note) for note in native]
    if len(summaries) != count:
        raise ValueError('incomplete native note vector evidence')
    ids = set()
    for note in summaries:
        ident = note['note_id']
        if isinstance(ident, bool) or not isinstance(ident, int) or not 0 <= ident <= 9007199254740991 or ident in ids:
            raise ValueError('invalid or duplicate native note_id')
        ids.add(ident)
        if not isinstance(note['mute'], bool):
            raise ValueError('invalid native note mute')
        for field in ('pitch', 'start_time', 'duration', 'velocity', 'probability', 'velocity_deviation', 'release_velocity'):
            value = note[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError('incomplete or nonfinite native note evidence')
    return sorted(summaries, key=lambda note: note['note_id'])

def wf_notes_digest(notes):
    return hashlib.sha256(json.dumps(notes, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()

def wf_prepare(op, remaining_notes=512):
    name = op['op']
    target = op.get('target')
    obj = wf_pin(**target) if target else None
    before = {}
    calls = []
    reversible = False
    dynamic = []
    if name.endswith('.set') and name not in ('mixer.set', 'routing.set'):
        before = wf_read(target, list(op['values']))
        for field, expected in op.get('expected', {}).items():
            if wf_read(target, [field])[field] != expected:
                raise ValueError('touched property conflict: ' + field)
        merged = dict(before, **op['values'])
        if 'loop_start' in merged or 'loop_end' in merged:
            start = merged.get('loop_start', obj.loop_start)
            end = merged.get('loop_end', obj.loop_end)
            if end <= start:
                raise ValueError('loop_end must exceed loop_start')
        ordered = list(op['values'].items())
        if 'loop_start' in op['values'] and 'loop_end' in op['values']:
            ordered = [(k,v) for k,v in ordered if k not in ('loop_start','loop_end')]
            loop_order = ('loop_end','loop_start') if merged['loop_start'] >= obj.loop_end else ('loop_start','loop_end')
            ordered.extend((k,op['values'][k]) for k in loop_order)
        calls = [wf_set_op(obj, k, v) for k,v in ordered]
        reversible = True
    elif name == 'mixer.set':
        field = 'send:' + str(op['return_id']) if op['parameter'] == 'send' else op['parameter']
        parameter = wf_parameter(target, field)
        value = op['value']
        if value < parameter.min or value > parameter.max or (parameter.is_quantized and int(value) != value):
            raise ValueError('invalid native parameter value')
        before = {field: parameter.value}
        if 'expected_value' in op and parameter.value != op['expected_value']:
            raise ValueError('mixer touched value conflict')
        calls = [{'method':'parameter_set', 'params':{'ref':{'id':wf_id(parameter)}, 'value':value}}]
        reversible = True
    elif name == 'routing.set':
        direction = op['direction']
        type_field, channel_field = direction + '_routing_type', direction + '_routing_channel'
        before = wf_read(target, [type_field, channel_field])
        for field, selector in op.get('expected', {}).items():
            actual = before[direction + '_routing_' + field]
            if any(actual.get(k) != v for k,v in selector.items()):
                raise ValueError('routing touched value conflict')
        wf_select(getattr(obj, 'available_' + direction + '_routing_types'), op['type'])
        if all(before[type_field].get(k) == v for k,v in op['type'].items()) and 'channel' in op:
            wf_select(getattr(obj, 'available_' + direction + '_routing_channels'), op['channel'])
        elif 'channel' in op:
            dynamic.append('channel availability/ambiguity can only be checked after routing type assignment')
        reversible = True
    elif name in ('track.create', 'scene.create'):
        method = 'create_' + op['type'] + '_track' if name == 'track.create' else 'create_scene'
        index = op.get('index', -1)
        members = song.tracks if name == 'track.create' else song.scenes
        if index < -1 or index > len(members):
            raise ValueError('creation index outside current collection')
        if not callable(getattr(song, method, None)):
            raise ValueError('creation capability unavailable')
        calls = [wf_call_op(song, method, [index])]
    elif name in ('track.delete', 'scene.delete'):
        members = list(song.tracks if name == 'track.delete' else song.scenes)
        if obj not in members:
            raise ValueError('only regular tracks/scenes can be deleted')
        method = 'delete_track' if name == 'track.delete' else 'delete_scene'
        calls = [wf_call_op(song, method, [members.index(obj)])]
    elif name == 'clip.create':
        occupancy = wf_id(obj.clip) if obj.has_clip else None
        if occupancy != op['expected_clip_id']:
            raise ValueError('slot occupancy changed')
        parent = wf_pin('track', target['parent_id'])
        if not getattr(parent, 'has_midi_input', False):
            raise ValueError('MIDI clip requires MIDI track')
        if not callable(getattr(obj, 'create_clip', None)):
            raise ValueError('clip creation unavailable')
        if obj.has_clip and not op.get('replace'):
            raise ValueError('occupied slot requires explicit replacement')
        if obj.has_clip and not callable(getattr(obj, 'delete_clip', None)):
            raise ValueError('clip replacement unavailable')
        if not callable(getattr(getattr(Live, 'Clip', None), 'MidiNoteSpecification', None)):
            raise ValueError('extended MIDI note API unavailable')
        before = {'clip_id': occupancy}
        calls = [{'method':'clip_add_notes', 'params':{'ref':{'id':target['id']}, 'notes':op['notes'],
                  'create_clip_length':op['length'], 'replace_existing_clip':bool(op.get('replace'))}}]
    elif name == 'clip.notes.transform':
        notes = wf_notes(obj, remaining_notes)
        digest = wf_notes_digest(notes)
        if 'expected_notes_digest' in op and op['expected_notes_digest'] != digest:
            raise ValueError('whole-clip notes digest conflict')
        selected = set(op.get('note_ids', [note['note_id'] for note in notes]))
        if selected.difference(note['note_id'] for note in notes):
            raise ValueError('unknown note_id in transform selection')
        fields = [field for field, delta in (('pitch', op.get('transpose', 0)), ('velocity', op.get('velocity_delta', 0))) if delta]
        proposed, updates = [], []
        for note in notes:
            after = dict(note)
            if note['note_id'] in selected:
                after['pitch'] += op.get('transpose', 0)
                after['velocity'] += op.get('velocity_delta', 0)
                if not 0 <= after['pitch'] <= 127 or not 1 <= after['velocity'] <= 127:
                    raise ValueError('resulting pitch or velocity outside native range')
                if after != note:
                    updates.append(dict({'note_id': note['note_id']}, **{field:after[field] for field in fields}))
            proposed.append(after)
        before = {'notes': notes, 'notes_digest': digest}
        if updates:
            calls = [{'method':'clip_update_notes', 'params':{'ref':{'id':target['id']}, 'updates':updates}}]
        note_evidence = {'inspected_notes_digest':digest, 'predicted_notes_digest':wf_notes_digest(proposed),
                         'proposed_notes':proposed, 'selected_count':len(selected), 'changed_count':len(updates),
                         'inspected_count':len(notes), 'affected_fields':fields, 'note_api':'extended',
                         'coverage':'Nine declared note fields only; expression and automation unmeasured',
                         'acquisition_limitation':'Native full-vector acquisition is not streaming/bounded'}
    elif name == 'clip.delete':
        parent = wf_pin('track', target['parent_id'])
        slots = [s for s in parent.clip_slots if s.has_clip and s.clip == obj]
        if len(slots) != 1:
            raise ValueError('clip deletion requires current Session slot')
        calls = [wf_call_op(slots[0], 'delete_clip')]
    elif name in ('scene.launch', 'clip.launch', 'clip.stop'):
        calls = [wf_call_op(obj, 'stop' if name == 'clip.stop' else 'fire')]
    elif name == 'arrangement.duplicate':
        parent = wf_pin('track', target['parent_id'])
        if not any(s.has_clip and s.clip == obj for s in parent.clip_slots):
            raise ValueError('duplication requires current Session clip')
        if not callable(getattr(parent, 'duplicate_clip_to_arrangement', None)):
            raise ValueError('Arrangement duplication unavailable')
        calls = [{'method':'clip_duplicate_to_arrangement', 'params':{'track':{'id':wf_id(parent)}, 'clip':{'id':wf_id(obj)}, 'destination_time':op['destination_time']}}]
    elif name == 'arrangement.import':
        if not callable(getattr(obj, 'create_audio_clip', None)):
            raise ValueError('Arrangement import unavailable')
        calls = [{'method':'track_create_audio_clip', 'params':{'ref':{'id':wf_id(obj)}, 'file_path':op['file_path'], 'destination_time':op['destination_time']}}]
        if 'name' in op:
            calls[0]['params']['name'] = op['name']
    else:
        raise ValueError('unsupported workflow operation')
    for call in calls:
        if call['method'] == 'call' and not callable(getattr(this._resolve(call['params']['ref']), call['params']['method'], None)):
            raise ValueError('method capability unavailable')
        if not callable(getattr(this, '_rpc_' + call['method'], None)):
            raise ValueError('Remote handler unavailable')
    if name in ('track.create','scene.create','clip.create'):
        wf_creation_capacity(1)
    prepared = {'before':before, 'calls':calls, 'reversible':reversible, 'dynamic_preconditions':dynamic}
    if name == 'clip.notes.transform':
        prepared['note_transform'] = note_evidence
    return prepared

def wf_run(request):
    operations = request['operations']
    grouping = {'requested':request.get('undo', 'none'), 'supported': callable(getattr(song,'begin_undo_step',None)) and callable(getattr(song,'end_undo_step',None)),
                'begun':False, 'end_attempted':False, 'closed':False, 'participation':'unverified'}
    # A closed native group does not prove each setter participates in undo.
    # Track.mute is a candidate from scoped physical testing, not universal proof;
    # Track.name did not participate in that test. Participation stays unverified.
    excluded_fields = []
    for i, op in enumerate(operations):
        if op['op'] in ('track.set','scene.set','clip.set'):
            for field in op['values']:
                if op['op'] != 'track.set' or field != 'mute':
                    reason = 'Native track name setter did not participate in the tested environment' if field == 'name' and op['op'] == 'track.set' else 'Undo participation unverified'
                    excluded_fields.append({'operation':i, 'field':field, 'reason':reason})
        else:
            excluded_fields.append({'operation':i, 'field':None, 'reason':'Undo participation unverified or transport action'})
    excluded = sorted(set(item['operation'] for item in excluded_fields))
    grouping['excluded_operations'] = excluded
    grouping['excluded_fields'] = excluded_fields
    grouping['candidate_field_scope'] = {'track.set':['mute']}
    grouping['whole_workflow_undo_claim'] = False
    report = {'ok':False, 'mode':request['mode'], 'context':None, 'operations':operations,
              'results':[], 'touched':[], 'applied_prefix':0, 'skipped':list(range(len(operations))), 'grouping':grouping,
              'coverage':{'touched_fields':True, 'notes':False, 'automation':False, 'devices':False}}
    try:
        report['context'] = wf_context(request.get('context'))
        this._check_expected_set_signature({'expected_set_signature':request.get('expected_set_signature')})
        if grouping['requested'] == 'required_group' and (not grouping['supported'] or excluded):
            raise ValueError('required grouping unsupported or contains unproven participating operations')
        # Reject conflicting authored writes before mutation; subsequent dynamic guards still rerun.
        keys = {}
        for op in operations:
            if op.get('target'):
                key = (op['target']['kind'], op['target']['id'])
                if op['op'] in ('track.set','scene.set','clip.set'):
                    fields = set(op['values'])
                elif op['op'] == 'mixer.set':
                    fields = {'send:'+str(op.get('return_id')) if op['parameter']=='send' else op['parameter']}
                elif op['op'] == 'routing.set':
                    fields = {op['direction']+'_routing_type', op['direction']+'_routing_channel'}
                else:
                    fields = {'*'}
                previous = keys.get(key, set())
                if previous and ('*' in previous or '*' in fields or previous.intersection(fields)):
                    raise ValueError('workflow operations have conflicting touched targets/fields')
                keys[key] = previous.union(fields)
        prepared, remaining_notes = [], 512
        for op in operations:
            if request['mode'] == 'apply' and op['op'] == 'clip.notes.transform' and 'expected_notes_digest' not in op:
                raise ValueError('note transform apply requires expected_notes_digest from plan')
            item = wf_prepare(op, remaining_notes)
            remaining_notes -= item.get('note_transform', {}).get('inspected_count', 0)
            prepared.append(item)
        wf_creation_capacity(sum(op['op'] in ('track.create','scene.create','clip.create') for op in operations))
        if request['mode'] == 'plan':
            report.update(ok=True, outcome='planned', preflight=prepared)
            return report
        if grouping['requested'] != 'none' and grouping['supported']:
            song.begin_undo_step()
            grouping['begun'] = True
        for index, op in enumerate(operations):
            item = {'index':index, 'op':op['op'], 'before':prepared[index]['before'], 'after':{}, 'verified':False, 'reversible':prepared[index]['reversible']}
            report['results'].append(item)
            report['skipped'] = list(range(index+1, len(operations)))
            attempted = False
            try:
                current = wf_prepare(op)
                if current['before'] != prepared[index]['before']:
                    raise ValueError('touched fields changed after workflow preflight')
                if op['op'] == 'mixer.set' and current['calls'][0]['params']['ref'] != prepared[index]['calls'][0]['params']['ref']:
                    raise ValueError('mixer parameter identity changed after preflight')
                calls = current['calls']
                if op['op'] == 'clip.notes.transform':
                    item['note_transform'] = current['note_transform']
                if op['op'] == 'mixer.set':
                    item['parameter_id'] = calls[0]['params']['ref']['id']
                if op['op'] == 'routing.set':
                    # Routing objects cannot be passed as display-name strings. Assign actual objects.
                    obj = wf_pin(**op['target'])
                    direction = op['direction']
                    attempted = True
                    choice = wf_select(getattr(obj,'available_'+direction+'_routing_types'), op['type'])
                    setattr(obj, direction+'_routing_type', choice)
                    item['substeps'] = [{'ok':True, 'outcome':'success', 'field':direction+'_routing_type'}]
                    if 'channel' in op:
                        choice = wf_select(getattr(obj,'available_'+direction+'_routing_channels'), op['channel'])
                        setattr(obj, direction+'_routing_channel', choice)
                        item['substeps'].append({'ok':True,'outcome':'success','field':direction+'_routing_channel'})
                else:
                    attempted = bool(calls)
                    item['substeps'] = wf_batch(calls) if calls else []
                    if any(not child.get('ok') for child in item['substeps']):
                        item.update(ok=False, outcome=item['substeps'][-1].get('outcome','uncertain'))
                        report['outcome'] = item['outcome']
                        break
                    if op['op'] in ('track.create', 'scene.create'):
                        members = list(song.tracks if op['op'] == 'track.create' else song.scenes)
                        pos = op.get('index', -1)
                        created = members[-1 if pos == -1 else pos]
                        item['created_target'] = {'kind':op['op'].split('.')[0], 'id':wf_id(created)}
                        if 'name' in op:
                            children = wf_batch([wf_set_op(created,'name',op['name'])])
                            item['substeps'].extend(children)
                            if not children[0].get('ok'):
                                item.update(ok=False,outcome=children[0].get('outcome','uncertain'))
                                report['outcome'] = item['outcome']
                                break
                    elif op['op'] == 'clip.create':
                        slot = wf_pin(**op['target'])
                        item['created_target'] = {'kind':'clip','id':wf_id(slot.clip),'parent_id':op['target']['parent_id'],'slot_index':op['target']['slot_index']}
                        if 'name' in op:
                            children = wf_batch([wf_set_op(slot.clip,'name',op['name'])])
                            item['substeps'].extend(children)
                            if not children[0].get('ok'):
                                item.update(ok=False,outcome=children[0].get('outcome','uncertain'))
                                report['outcome'] = item['outcome']
                                break
                item.update(ok=True,outcome='success')
                report['applied_prefix'] += 1
                if op['op'] == 'clip.notes.transform':
                    item['write_acknowledged'] = bool(calls)
                    item['outcome'] = 'success' if calls else 'no_change'
                    try:
                        notes = wf_notes(wf_pin(**op['target']))
                        item['after'] = {'notes':notes, 'notes_digest':wf_notes_digest(notes)}
                        if notes != current['note_transform']['proposed_notes']:
                            raise ValueError('declared note fields differ from predicted state after write')
                        item['verified'] = True
                    except Exception as exc:
                        item.update(ok=False, outcome='uncertain', verification_error=str(exc)[:4096])
                        report['outcome'] = 'uncertain'
                        break
                if item['reversible']:
                    try:
                        item['after'] = wf_read(op['target'], list(item['before']))
                        if op['op'] == 'mixer.set' and wf_id(wf_parameter(op['target'], next(iter(item['before'])))) != item['parameter_id']:
                            raise ValueError('mixer parameter identity changed after acknowledged write')
                        item['verified'] = True
                        if op['op'] == 'routing.set':
                            type_field = op['direction'] + '_routing_type'
                            if item['before'][type_field] != item['after'][type_field]:
                                item['reversible'] = False
                                item['recovery_reason'] = 'Routing type changed; inverse channel availability cannot be proven before restoration'
                        for field, before in item['before'].items():
                            touched = {'target':op['target'], 'field':field, 'before':before,
                              'after':item['after'][field], 'verified':True, 'operation':index, 'reversible':item['reversible']}
                            if 'parameter_id' in item:
                                touched['parameter_id'] = item['parameter_id']
                            report['touched'].append(touched)
                    except Exception as exc:
                        item['verification_error'] = str(exc)[:4096]
                        item['reversible'] = False
            except Exception as exc:
                item.update(ok=False, outcome='uncertain' if attempted else 'failed', error=str(exc)[:4096])
                report['outcome'] = item['outcome']
                break
        else:
            report.update(ok=True, outcome='success')
    except Exception as exc:
        report.update(ok=False, outcome='failed', error=str(exc)[:4096])
    finally:
        if grouping['begun']:
            grouping['end_attempted'] = True
            try:
                song.end_undo_step()
                grouping['closed'] = True
            except Exception as exc:
                grouping['end_error'] = str(exc)[:4096]
                report['ok'] = False
                if report.get('outcome') != 'uncertain':
                    report['outcome'] = 'partial'
    report['recovery_eligible'] = bool(report['ok'] and report['results'] and all(r.get('reversible') and r.get('verified') for r in report['results']))
    return report
'''


def execute_callback(bridge, payload, tail_code):
    serialized = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    code = "import json\nrequest = json.loads(" + repr(serialized) + ")\npayload = request\n" + RUNTIME_CODE + "\n" + tail_code
    result = bridge.request("exec", {"code": code, "max_depth": 20, "max_items": 2048, "max_string_length": 8192})
    def truncated(value):
        if isinstance(value, dict):
            return bool(value.get("__truncated__") or (value.get("truncated") is True and ("reason" in value or "omitted" in value))) or any(truncated(v) for v in value.values())
        if isinstance(value, list):
            return any(truncated(v) for v in value)
        return False
    if isinstance(result, dict) and truncated(result):
        result["payload_truncated"] = True
        result["recovery_eligible"] = False
        if any(op.get("op") == "clip.notes.transform" for op in payload.get("operations", [])):
            result["note_verification"] = "unavailable_truncated"
            for item in result.get("results", []):
                if item.get("op") == "clip.notes.transform":
                    item["verified"] = False
                    item["verification_error"] = "Complete declared note evidence unavailable: response truncated"
            if payload.get("mode") == "apply" and result.get("ok"):
                result.update(ok=False, outcome="uncertain")
    return result


def run_workflow(bridge, args):
    validate_workflow(args)
    try:
        return execute_callback(bridge, args, "result = wf_run(request)")
    except Exception as exc:
        diagnostic = exc.to_dict() if callable(getattr(exc, "to_dict", None)) else {"message": str(exc), "outcome": "uncertain"}
        return {"ok": False, "mode": args["mode"], "outcome": diagnostic.get("outcome", "uncertain"),
                "operations": args["operations"], "results": [], "error": diagnostic,
                "verification": "unavailable", "recovery_eligible": False}
