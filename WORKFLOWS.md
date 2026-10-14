# Everyday workflows

The focused workflow tools share the existing MCP dispatcher and bridge. General
`live_get`, `live_call`, `live_set`, `live_exec`, `live_batch`, clip helpers and
audio/M4L tools remain available. Refresh the MCP client/server to discover the
new schemas; a client's cached tool list cannot expose new tools.

## Plan and apply

`live_workflow` accepts `mode: "plan"|"apply"`, 1–32 typed `operations`, optional
`label`, `expected_set_signature`, `context` or retained `snapshot_id`, and
`undo: "none"|"group_if_supported"|"required_group"`.

Plan inspects current capabilities and preconditions without editing Live. Apply
repeats validation; a plan is not a reservation. A workflow executes in one
generated callback using the existing Remote handlers. All statically resolvable
targets are checked before editing, and dynamic preconditions are checked again
as the workflow progresses. A later failure can leave an applied prefix. No
automatic undo, rollback or replay occurs.

Targets use qualified object IDs from current inspection, rather than display names
or indexes: `{ "kind": "track", "id": 123 }`. Clip targets additionally need
`parent_id`; Session-slot targets need parent track ID and `slot_index`. A target
must still belong to the current set. Renaming or reordering another track cannot
redirect the edit. IDs in the examples are placeholders, not executable targets.

First registrations retain native positive IDs; a fresh object reusing a retained
native pointer receives a stable negative bridge-local alias. The original strong
registration remains authoritative and is never rebound to the replacement.
Use the returned target ID, including a negative alias, for focused workflows and
bridge `ref.id` helpers. Aliases resolve to original objects inside the bridge;
they are not native LOM IDs to pass directly into unrelated SDK/Max APIs.
The focused workflow registry checks original validity/membership and restores
its authoritative registration before dispatch. General LOM helpers retain their
existing native-ID/cache behavior; arbitrary stale positive generic references
are not made lifetime-safe by this focused registry.
Snapshot `native_id` is diagnostic interop metadata, not the qualified target ID.
IDs are nonzero JavaScript-safe integers; unknown negative aliases are refused.
Use snapshot/context guards across set or bridge changes. The 4096-registration
ledger is bridge-lifetime-bounded with no eviction/rebinding; capacity refusal is
explicit and does not authorize dropping old identity claims.
Creation preflight checks capacity for all known new registrations before the
first edit, then rechecks dynamically before each creation.

```json
{
  "mode": "plan",
  "label": "Bass balance",
  "undo": "group_if_supported",
  "operations": [
    {"op":"track.set","target":{"kind":"track","id":123},
     "values":{"name":"Bass","mute":false}},
    {"op":"mixer.set","target":{"kind":"track","id":123},
     "parameter":"volume","value":0.65}
  ]
}
```

Use the same request with `mode: "apply"` after reviewing the plan. Native mixer
values are parameter units, not dB. Inspect the parameter's range and displayed
label rather than converting normalized values as though they were decibels.

### Supported operation families

| Area | Operations | Important preconditions |
|---|---|---|
| Tracks | `track.create`, `track.set`, `track.delete` | Create MIDI/audio with optional name/index; delete requires `confirm_delete:true`. |
| Scenes | `scene.create`, `scene.set`, `scene.launch`, `scene.delete` | IDs distinguish duplicate scene names; delete requires explicit confirmation. |
| Session clips | `clip.create`, `clip.set`, `clip.launch`, `clip.stop`, `clip.delete` | Creation pins slot/parent and `expected_clip_id` (null means empty); occupied replacement also requires `replace:true`. Notes use the extended API. |
| Existing MIDI notes | `clip.notes.transform` | Session or Arrangement clip/parent IDs; deterministic transpose/velocity offset, whole declared-note digest from plan required on apply; extended API only. |
| Arrangement | `arrangement.duplicate`, `arrangement.import`, applicable `clip.set` metadata | Positions are nonnegative beats. Duplicate requires a Session clip; import requires an existing local audio file and supported track API. |
| Mixing | `mixer.set` | Choose volume/pan/send; sends require stable `return_id`. Optional `expected_value` guards the touched field. |
| Routing | `routing.set` | Select actual available input/output type/channel by unambiguous display name or identifier. Routing objects are assigned inside Live; strings are not assigned as objects. |

`track.set` supports name/mute/solo/arm; `scene.set` supports name; `clip.set`
supports name/muted/looping/loop start/end. Optional `expected` values guard
property edits. Unsupported Live APIs and ambiguous routing options are reported
instead of inventing an implementation. A routing type change refreshes channel
options before selection; its later failure may leave the type changed.
Arrangement destination/start/end positions use beats. Clip loop/marker values
retain native API units: beats for MIDI/warped audio and seconds for unwarped audio.
Arrangement import/duplication may move Live's stopped insertion marker; inspect
and explicitly restore transport/view position when that is part of the workflow.

Creation returns fresh object evidence for the next request. There is no symbolic
cross-operation alias language. Complex free-form work can still use the existing
LOM tools.

### Existing-note transformations

Plan a deterministic edit to an existing MIDI clip using its qualified target:

```json
{"mode":"plan","operations":[
  {"op":"clip.notes.transform","target":{"kind":"clip","id":123,"parent_id":456},
   "transpose":12,"velocity_delta":8}
]}
```

Targets here are placeholders. For Session clips an optional `slot_index` also
guards occupancy; Arrangement targets omit it. Review the plan's complete note
preview and `preflight[0].note_transform.inspected_notes_digest`, then apply the
same transform with that value as `expected_notes_digest` and retained context.
Plan is not a reservation; apply rereads notes.

`transpose` is an integer -127…127; `velocity_delta` is a finite number
-126…126. At least one must be nonzero. Optional `note_ids` selects1–512 distinct
nonnegative JavaScript-safe native note IDs from that clip; these are clip-local
note IDs, not workflow object aliases. Omission selects all notes. Resulting pitch
must be0–127 and velocity1–127; invalid results reject the whole workflow before
the first edit, with no implicit clamping, wrapping or note deletion. Fractional
velocity is preserved where the native extended API supports it.

The SHA256 digest covers complete declared nine-field summaries sorted by note ID
with fixed-key compact JSON: `note_id`, `pitch`, `start_time`, `duration`,
`velocity`, `mute`, `probability`, `velocity_deviation`, `release_velocity`.
Unselected notes participate, so their concurrent changes also invalidate the
guard. It is not an MPE/expression/automation/full-clip hash. Apply requires the
plan digest and repeats original clip/parent/current-membership checks immediately
before writing. Another operation targeting the same clip in that workflow is
refused to avoid ambiguous sequential note/metadata dependencies.

At most512 notes are inspected across all transforms in one workflow. Oversized
or incomplete evidence refuses before authored writes; the native full-note
vector acquisition itself is not streaming or a bounded query. Existing32-operation
and256000-byte request limits also apply. Empty clips return an explicit no-change
result with zero native note writes. Selected/changed counts are separate.

Writes reuse native extended note modifications and preserve note IDs and all
untouched declared fields. Acknowledgement and exact nine-field readback verification
are separate evidence. Mismatch, failed readback or unknown native execution stops
later actions and retains prefix/uncertainty; no replay or automatic undo occurs.
Truncated previews/readbacks report `payload_truncated` and
`note_verification: "unavailable_truncated"`, clear note `verified` claims, and
turn an acknowledged apply into uncertainty while retaining its applied prefix.
These operations are non-compensable, including mixed note+metadata entries;
metadata snapshots/diffs still omit notes. Required undo grouping excludes them;
an optional group provides no note undo-participation promise.

## Undo boundaries

`none` requests no undo grouping. `group_if_supported` attempts a single Live
undo boundary and reports fallback and excluded fields. `required_group` rejects
unsupported grouping or operations outside the narrow eligible field scope before editing.
Currently only `track.set` of `mute` is an eligible candidate. Native name writes
were observed not to participate in undo on Windows Live12.4.6; other fields and
operation families are unproven and excluded from required grouping. This is an
empirically scoped candidate policy, not universal participation certification.
Begin and end occur
inside one callback; end is attempted in `finally` only after begin succeeds.

Grouping is not atomicity. `whole_workflow_undo_claim:false`, excluded operations/
fields and participation evidence remain explicit. A failed child can leave changes within a closed group;
an end failure is retained separately. Launch/stop actions are excluded from the
grouped-edit promise. Method availability is separate from physical evidence that
every particular action participates in Live undo.

Use conditional history compensation for metadata such as names even when its
native setter does not participate in Live undo. A closed group alone cannot make
nonparticipating writes undoable.

`live_undo` remains a general escape hatch. Its steps are Live history steps, not
the number of authored operations. GUI edits share that history. A performed-step
count and any partial/uncertain diagnostic must be inspected; neither the command
nor a failed status read proves restoration of the intended workflow.

## Snapshot, diff and history

Snapshots cover declared metadata, mixer values and routing, with bounded scope
and explicit omitted/unavailable fields. They do not capture the whole set,
device DSP state, MIDI note contents, automation or deleted media. Equality of
metadata is not proof those unmeasured contents are unchanged.

`live_snapshot` takes optional `scope` and expected `context`. Scope controls
`track_ids` (up to 64 distinct qualified regular-track IDs), `track_limit`, `scene_limit`,
`slot_limit`, `arrangement_limit` (1–64 each), and `include_returns`,
`include_master`, `scenes`, `session`, `arrangement`, `mixer`, `routing` switches.
Limits default to 32; all switches default true except Arrangement. A maximum of
512 entities and 200000 callback-result bytes bounds acquisition; exceeded
coverage is explicit. Missing requested targets are incomplete scope, not empty
complete collections.

```json
{"scope":{"track_ids":[123],"arrangement":true,"slot_limit":8}}
```

Use the returned `snapshot_id` as `live_workflow.snapshot_id`, or compare two:

```json
{"before_id":"snapshot-…","after_id":"snapshot-…"}
```

`live_workflow_history` accepts `{"action":"list","limit":16}` (1–32),
`{"action":"get","workflow_id":"workflow-…"}`, or
`{"action":"recover","workflow_id":"workflow-…"}`. Snapshots and workflow
entries each retain at most 32 records with a 256 KiB evidence bound per record.
Truncated retained evidence cannot authorize diff/recovery. Each MCP server owns
its store; protocol sessions on that server share it. A new server process or a
separate server instance has no access to another store's IDs.

Set content signature, context identity and target/value guards are different:

- `expected_set_signature` rejects stale inspected content at entry. The existing
  signature is neither a complete snapshot hash nor stable set identity.
- Context identity uses a bridge-lifetime nonce and retained valid set anchors.
  Ordinary structural edits should preserve the context; replacement or invalid
  anchors must invalidate it. Unsupported validity capability fails closed.
- Object membership and expected touched values prevent edits/recovery from
  selecting reordered, replaced or subsequently changed targets.

Snapshot diffs compare retained snapshots within a valid matching context. IDs
distinguish renames/reordering from replacement. Only completely measured matching
collections can support added/removed claims; omitted data is unavailable, not a
deletion. History is bounded, server-process-local and lost on restart/eviction.

Recovery is explicitly requested conditional compensation, not counted undo or
full-set restoration. It is limited to acknowledged, verified reversible property,
mixer and routing changes with complete before/after evidence. Every current
touched value must equal the recorded after-value before any restoration starts;
unrelated changes do not automatically conflict. Missing targets, invalid context,
ambiguous routes, truncated evidence and touched-value conflicts refuse recovery.

Routing compensation is limited to routes whose inverse options can be proven
before any restoration. Same-type channel changes can be restored when their
unambiguous options remain available. Type-changing route restoration is excluded
when its previous channel choices cannot be inspected before selecting the old
type; history reports that limitation instead of probing through temporary edits.

Mixer history also retains the original parameter registration. Equal current
values on a replacement parameter do not qualify its predecessor's compensation;
the parameter identity is checked before any restoration.

Create/delete, note creation/replacement, Arrangement import/duplication and
launch/stop are not compensated from metadata. Mixed irreversible or uncertain
entries have no whole-workflow compensation promise. Recovery itself has retained
prefix/uncertainty evidence and linked history; incomplete/uncertain recovery must
not be blindly repeated.

Physical validation is scoped to Windows Live12.4.6. Session MIDI transformations
were verified in Live; Arrangement transformations have local regression coverage
only. Local fake-backed checks do not establish universal native grouping or set
replacement behavior.
