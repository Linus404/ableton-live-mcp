# Multi-track audio capture implementation plan

## First deliverable

One MCP tool captures an Arrangement passage across all audio-capable tracks,
groups, returns, and the master in a single playback pass. It returns local WAV
paths and a manifest identifying the signal paths, musical interval, and timing
accuracy. UI changes are acceptable while the agent works.

Example request: capture eight bars starting at 1.1.1, including returns and
master. In 4/4 this is the half-open interval [0, 32) in Live's quarter-note units.
Live supplies audio; the MCP owns the recordings and subsequent analysis.

## Existing implementation to reuse

- `m4l/AgentAudioTap.maxpat`: transparent stereo pass-through plus `sfrecord~ 2`.
- `m4l/agent_audio_tap.js`: command-file polling and recording control.
- `scripts/build_agent_audio_tap.py`: role-correct AMXD build/install and path discovery.
- `Ableton_Live_MCP/bridge.py`: track resolution, device loading, transport control.
- `src/server.py`: tool registration and Python-side orchestration patterns.

Current gaps: shared command file/UDP port; no durable per-instance acknowledgement;
a fixed 500 ms delay before recording; no coordinated timing or file-completion
verification. Setup stops transport by default and can solo tracks.

## Phase 1 — Prove timing and measurement points

Use a disposable set with two identical impulse sources, a group, a return, and
master processing. This is a prerequisite experiment, not production scaffolding.

1. Verify end-of-chain tap placement on audio tracks, instruments, groups,
   returns, and master. MIDI-only tracks without audio are explicitly skipped.
2. Change fader, pan, mute, sends, and upstream/downstream processing to establish
   exactly which changes each tap captures. Record the result, especially the
   distinction between post-device/pre-mixer audio and final track contribution.
3. Prototype a shared audio-domain timing reference, recorded as non-audible
   metadata/extra channels alongside the stereo audio. Verify its relationship
   to Live transport and device latency compensation. File-poll or UDP arrival
   times are not sample timestamps.
4. Arm/open recorders while transport is stopped, await readiness, then play.
   Recover common passage boundaries from the timing reference and trim outside
   Live. Test repeated starts and a latency-inducing device on one path.
5. Measure alignment error using identical source impulses. Preserve actual
   relative musical/effect timing; do not align unrelated tracks by waveform
   correlation or shift away intentional delays.

Exit gate: a demonstrated common timeline and documented capture points. If the
timing prototype fails, resolve the recorder architecture before building the
high-level tool. Never advertise sample alignment based on a shared JS message.
If captures are pre-mixer, label them accordingly; do not reconstruct final
contributions from one snapshot of fader/pan settings or claim final-output stems.

## Phase 2 — Make taps independently controllable

Extend the existing builder, patch, JS, and low-level tools rather than introducing
another generated-device host.

- Assign an instance ID and separate command/status paths to every tap. Generate
  instance-specific installed wrappers with the existing builder; reuse matching
  loaded taps. Names identify devices, not audio sources; manifest refs identify tracks.
- Prefer command files; omit UDP initially. Preserve legacy single-tap calls.
- Add `arm`, `stop`, and `status` acknowledgements containing instance ID, take ID,
  command ID, runtime version, recorder state, paths, and timing metadata.
- Replace the unconditional 500 ms start delay with a verified readiness sequence.
  Opening a file and reporting an event must not be mistaken for recording readiness.
- Confirm file closure through recorder completion where available, then validate
  WAV headers/data length outside Live. A JS `stop` event alone is insufficient.
- Cancel pending starts on stop/cancel; reject conflicting takes. Add bounded
  recording limits so an abandoned MCP request cannot record indefinitely.
- Specify a supported high-headroom recording format, preferably float WAV;
  verify it can preserve signals above 0 dBFS without capture-induced clipping.
- Keep timing channels out of the audible pass-through and out of analyzed stereo.

Exit gate: two taps can record independently, with no cross-talk between commands
or output paths, and every lifecycle transition has a matching acknowledgement.

## Phase 3 — Orchestrate one complete take

Add Python-side orchestration in `src/audio_capture.py` and register
`live_audio_capture` in `src/server.py`. Keep waits, file parsing, trimming, and
manifest writes outside the Remote Script's Live main-thread callbacks.

Initial inputs:
- `start_beat`, `length_beats`: explicit quarter-note units, supporting the
  eight-bar use case without ambiguous bar conversion across meter changes.
- Optional track refs; default all audio-capable regular/group tracks.
- `include_returns`, `include_master`: default true.
- Optional pre-roll and tail duration; stored separately from the requested passage.

Sequence:
1. Validate runtime health, inputs, available disk space, and target capabilities.
   Enumerate tracks once and snapshot transport, loop/record state, and relevant
   selection. Reject active recording rather than disturb a recording take.
2. Stop playback for this deliberate passage capture; install/reuse taps sequentially
   at verified end-of-chain positions. Never solo, unmute, or rewrite routing.
3. Create a unique take directory under the discovered state directory; arm every
   recorder and require every ready acknowledgement before starting playback.
4. Seek, play, and capture the requested interval using the proven timing mechanism.
   Respect tempo automation; do not derive the interval from initial BPM and sleep.
   Avoid accidental loop wrap and detect premature transport stop or timeline jumps.
5. Stop recorders, verify completion, trim to the common interval, and write the
   manifest. Stop playback at completion; restore prior loop/selection settings.
   Return prior transport state and any remaining changes explicitly rather than
   unexpectedly relaunching playback. Temporary setup failures restore changed state.
6. Return compact results: take ID, manifest path, interval, per-track outcome,
   skipped tracks, timing accuracy, and failures. Keep audio bytes out of tool output.

Serialize Live API calls. Parallel recording happens inside Live, not through
concurrent bridge calls. After a sent-call timeout, treat mutation status as unknown;
inspect acknowledgements before retrying. Abort the take if required readiness fails.

Manifest fields: track ref/name/type, group ancestry, routing and mixer snapshot,
tap instance/index, capture-point semantics, sample rate/format/frame count,
requested and actual interval, alignment evidence/error, pre-roll/tail, file path,
completion status, and runtime versions. Mixer snapshots are context, not evidence
of constant mixer values during automation. Groups/returns/master overlap with
upstream captures and must not be blindly summed.

Retain successful takes for downstream analysis. Support explicit cleanup of
owned files/devices; do not delete unrelated devices or recordings. Disk/running
time limits bound each take, and interrupted takes remain clearly incomplete.

## Phase 4 — Validate and document

- Extend existing builder, fake-Live bridge, and MCP tests for instance isolation,
  command acknowledgements, invalid inputs, partial readiness, cancellation,
  transport interruption, and state restoration. Add WAV/manifest checks with
  known synthetic signals and offsets; no new test framework.
- Run `python -m pytest tests/test_agent_audio_tap_build.py tests/test_remote_bridge_fake_live.py tests/test_mcp_server.py`
  plus the new focused orchestration tests.
- Rebuild/install tap devices and companion JS. Reinstall the Remote Script after
  bridge edits; ask authorization before reloading the Control Surface or Live.
  Require `runtime_current: true` and `live_mutations_safe: true` for Live checks.
- In the disposable set capture eight bars across tracks, group, return, and
  master. Verify shared passage boundaries, nonzero/silent paths as expected,
  timing error, latency effects, mute/fader semantics, float headroom, and tails.
- Repeat on a larger set, measuring CPU/disk load and dropped/incomplete captures.
  Verify taps do not audibly change pass-through and do not duplicate on reuse.
- Document setup, prerequisites (Max for Live), capture-point limitations,
  retention/cleanup, and the new tool in `README.md` and `AGENTS.md`.

## Next feature

Analyze the captured take outside Live: loudness, peaks, dynamics, spectral and
stereo evidence with local time ranges. Choose established measurement libraries
then. Capture alone is not an audio-understanding report; it supplies trustworthy
input for it. Masking and perceptual judgments require additional evidence.
