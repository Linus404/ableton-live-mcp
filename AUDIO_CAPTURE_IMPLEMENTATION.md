# Multi-track audio capture implementation and validation

## Implemented

`live_audio_capture` captures one requested Arrangement passage in real time across
audio-capable tracks, groups, returns, and master. For eight 4/4 bars from 1.1.1:

```json
{"start_beat": 0, "length_beats": 32}
```

- `src/audio_capture.py`: sequential orchestration, runtime/Arrangement safety
  checks, beat-observed passage completion, supported/unsupported target outcomes,
  recorder shutdown, WAV structure and gross-duration sanity checks, retained raw
  files and incomplete manifests.
- `src/audio_tap.py`, `m4l/agent_audio_tap.js`, and the existing tap builder:
  isolated per-instance file control, matching command acknowledgements, stable
  session identities, cancellation, stale-start suppression, and a local
  Max-scheduled recording duration limit. Legacy tap control is preserved.
- `Ableton_Live_MCP/bridge.py`: compact capture snapshots, guarded transport
  preparation/restoration, and verified enabled end-of-chain tap placement/reuse.
- `src/server.py`: MCP registration. Arguments/defaults and limitations are in
  `AGENTS.md` and `README.md`.

Routing, mute/solo states, and clips are preserved. Capture intentionally stops
playback; prior loop/selection are restored when the bridge remains healthy.
Owned tap devices and recording files are retained. Frozen and unknown-capability
targets are explicitly unsupported.

## Guarantees and limits

Files are raw/untrimmed. Timing and inter-file alignment are uncalibrated; no
sample-alignment or exact trimming is claimed. Recording-state acknowledgements
prove dispatched commands, not first-sample readiness. The duration sanity check
only rejects gross truncation; it is not timing calibration.

The signal point is the end of the device chain. Post-mixer contributions, master
fader/output behavior, float headroom, and final-output delivery measurements
require experimental evidence. Group/return/master paths overlap upstream
captures and cannot be blindly summed. Post-roll is continued playback context,
not isolated decay.

## Independent review

The independent reviewer found no remaining source-level blocker for this limited
contract after fixes for take ownership, stale-start replay, acknowledgement
overwrites, startup ordering, watchdog expiry, shutdown ordering, gross WAV
truncation, and ID-stable tap reuse. The implementation reuses the existing tap,
role builder, bridge, and validator; no sample-synchronization or stem-reconstruction
architecture was added.

## Local verification

295 tests passed in the planned affected suites after the Live-discovered fixes:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_agent_audio_tap_build.py tests/test_remote_bridge_fake_live.py tests/test_mcp_server.py tests/test_audio_capture.py -q --tb=short --basetemp "C:\Users\LINUSV~1\AppData\Local\Temp\opencode\capture-final2-tests"
```

`git diff --check` passed. An initial system-Python test run encountered an
inaccessible default pytest temporary directory; the final run used the repository
development environment and approved temporary directory. The runtime-marker test
was updated for the new Remote Script version.

## Live validation

The user authorized script installation, Control Surface reload, a disposable set,
and then a normal Live restart when the Control Surface retained cached Python
modules. The existing `Example-Showcase` set was saved before quitting. After
restart, validation reports `runtime_current: true` and `live_mutations_safe: true`
on Live 12.4.6 with Remote Script runtime `audio-capture-1`.

The first disposable-set experiment recorded two synthetic 16-second Arrangement
sources, five returns, and master. All eight stereo PCM16/44.1 kHz WAVs finalized;
their raw durations ranged from 19.30 to 22.50 seconds because starts are sequential.
The first-beat source transients were retained, but source onset offsets differed
by about 0.69 seconds. This is evidence against interpreting raw files as aligned.

Changing one source fader to zero left both source recordings bit-identical over
their detected active intervals. Master active RMS fell from approximately 0.1200
to 0.0848 and peak from 0.6973 to 0.3793. This establishes pre-fader source capture
and a real downstream response in this test; it does not establish final-master
fader/output semantics. One return carried signal; four unsent returns were silent.
Repeat setup retained exactly one tap per path.

The experiment exposed two defects that local mocks had not revealed:

1. Live acknowledges transport stop before `is_playing` necessarily settles.
   Preparation/restoration now return an explicit pending phase, and Python waits
   outside Live's main-thread callback before completing it. The polling window is
   bounded, but an individual bridge call still uses its ordinary response timeout.
2. Windows can briefly deny atomic command-file replacement while Max reads it.
   Only this pre-delivery replacement is retried for at most 0.5 seconds with the
   same command ID. Sent-command acknowledgement failures are never redelivered.

These initial takes remain incomplete because restoration failed under the old
stop implementation. Their evidence is retained at
`C:\Users\LINUSV~1\AppData\Local\Temp\opencode\capture_validation\EVIDENCE.md`.
The user authorized a second restart; the fixed `audio-capture-2` runtime validates
current/safe. A full 32-beat capture starting from already-playing transport then
completed successfully: `complete: true`, `transport_stopped: true`, no error.
Nine paths recorded: the verified source group, two sources, five returns, and
master. The empty MIDI-only track was explicitly unsupported. All nine stereo
PCM16/44.1 kHz WAVs finalized, with raw durations 20.69–24.50 seconds.

Successful manifest:
`C:\Users\LINUSV~1\AppData\Local\Temp\opencode\capture_validation\46f5627a61164921bc436afdd2ea84cd\manifest.json`.

Two additional four-beat takes also completed without errors:

- Muting both sources retained audio at the source taps (active RMS about 0.0848),
  while group, fed return, and master WAVs were exactly silent. Source taps are
  therefore pre-mute as well as pre-fader in this experiment.
- Setting the master fader to zero retained the master tap's signal (peak about
  0.6973; active RMS about 0.1197). **The tested master tap is pre-master-fader and
  is not the final delivered output.**

Group/source meters were identical with taps enabled versus disabled; the master
meter difference was below 0.00030 amid reverb/time variation. This is supporting
pass-through evidence, not an audio null test. Source grouping was verified through
matching Live group refs and nonzero group audio. Nine taps were reused without
duplication. A nonblank Ableton-only focused screenshot showed the correctly
selected group tap.

One four-beat test stopped around beat 6.36: approximately 1.18 seconds of observed
overrun. This is an empirical example, not a guaranteed error bound. Raw files
include sequential-start lead-in and variable trailing context; **do not interpret
the requested interval as sample-accurate WAV boundaries**. PCM16 overload behavior,
float headroom, latency-compensation alignment, tempo-automation stress, large-set
load, and an audio pass-through null test remain unvalidated.

Additional successful manifests:

- `capture_validation\5b5249a5059b4c869f50e32c0daab0db\manifest.json` (muted sources)
- `capture_validation\ddd6aecb4ce74067bce3a9207241e1e0\manifest.json` (master fader zero)

The original saved `Example-Showcase.als` was reopened after discarding only the
generated disposable set. Its original Arrangement/Operator content and clean
saved title were visually verified; Ableton is stopped and its window is maximized.
Final validation after restoration again reports `runtime_current: true` and
`live_mutations_safe: true` with `audio-capture-2`.

This implementation is the capture prerequisite for the analysis features in
`AUDIO_UNDERSTANDING_GOALS.md`; it does not yet implement loudness/balance analysis.
The original goals, plan, and plan review remain preserved. No pushes were made.
