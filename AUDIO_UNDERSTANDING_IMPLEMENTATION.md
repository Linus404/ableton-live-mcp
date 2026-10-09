# Feature 1: loudness and balance evidence

**Complete for the first-two-goal qualified workflow under its measured supported
conditions.** Actual native regular/group/return acquisition and explicit/default
MCP assessments passed independent review; the final combined suite passed
465 tests and the original Live set was restored. See
`AUDIO_FEATURES_VALIDATION.md` for retained evidence, conditions and recalibration
requirements. Historical foundation experiments below are separate evidence.

Implemented `live_audio_analyze`, an offline measurement tool for existing WAVs
and `live_audio_capture` manifests. No audio AI model or running Live is needed
for analysis. See README.md and AGENTS.md for arguments and measurement limits.

## Delivered measurements

- BS.1770 reference DeMan K-weighting and gated integrated LUFS for files and
  named sections, using pyloudnorm.
- Ungated trailing 400 ms momentary and 3 s short-term LUFS with file-relative
  timestamps, plus the largest adjacent sampled short-term change.
- Unweighted RMS dBFS, sample peak dBFS, section-to-whole integrated differences.
- Explicit silence/short-duration conditions and retained capture provenance,
  including unsupported, incomplete and failed per-entry outcomes.
- Optional `audio-analysis` installation extra: NumPy, SoundFile, pyloudnorm.
  Core server startup remains independent of those optional imports.

Measured loudness provides level evidence, not perceived prominence. Raw pre-mixer
captures still cannot establish fader balance, temporal correspondence or delivery
loudness, so `live_audio_analyze` keeps part-to-master comparisons unavailable.
LRA and true peak are unsupported; no proxy is substituted.

## Complete workflow integration and qualification gate

`live_audio_balance` adds aligned programme/part integrated, local and section
loudness differences and separate Model-1-adapted prominence/masking estimates.
It accepts 1–8 disjoint actual in-mix contributions plus a separate programme,
verified alignment/provenance and explicit calibrated or assumed listening level.
Section differences are judged only against `expected_section_differences`:
from/to sections, expected LU contrast and tolerance. `fair_loudness_match`
reports isolated comparison gain/peak headroom without applying it. Explicit
gain scenarios retain original evidence and do not reconstruct nonlinear master
processing or claim louder means better.

`live_audio_capture_in_mix` records native Live clips on owned Post Mixer receivers
and a separate Master Resampling programme. Original acquisition WAV copies are
retained unchanged; a float64 interleaved derivative is constructed without
gain/resampling and is not an acquisition clock proof.
Capture requires stopped transport, performs one real-time passage, and restores
the original stopped position and insertion marker. Active-playback restoration
is unsupported; Live's playback cursor and stopped insertion position differ.
`live_audio_assess`
adapts its complete manifest offline, checks finalized WAV metadata/frame counts,
rejects incomplete/unsupported entries, and calls `verify_qualification` before
passing strict alignment/provenance to analysis. The wrapper attaches qualification
only through an experimentally established current certificate. Matching clocks,
file lengths and status declarations are insufficient evidence. Historical raw-tap
experiments below do not qualify this new path; physical in-mix qualification and
independent numerical/model review are required by `AUDIO_FEATURES_ACCEPTANCE.md`.

Local integration check (2026-10-09): **228 passed** across
`tests/test_audio_assessment.py`, `tests/test_audio_analysis_tool.py`,
`tests/test_audio_masking_tool.py`, `tests/test_live_settings.py`, and
`tests/test_mcp_server.py`; `git diff --check`
passed. This checks discoverable schemas, offline dispatch, strict refusal of
unqualified/incomplete/inconsistent manifests and a real offline balance run.
The adapter validates the actual finalized interleaved recording (preferring
`normalized_interleaved_path` when present) and checks bounded frame-for-frame
split-channel equality, refusing same-metadata file replacement. Full raw and
normalization evidence is retained.
Test qualification proofs are explicitly mocked; they are not Live certificates.
The adapter uses float64 channel comparisons to preserve native PCM32 least-
significant bits and accepts supported native PCM and float acquisition formats.
Physical qualification is limited to PCM24/PCM32 and float32/float64: native
PCM16 is rejected by calibration/current-sum qualification, while standalone
offline PCM16 file analysis remains available. No tolerance relaxation substitutes
for the unsupported acquisition format.
The Windows-only read-only menu helper dynamically discovers English native
Options labels and verifies the Ableton process/window before and after reading
PDC/RLWM checkbox states. Unsupported menus/platforms return unknown settings;
test probes are mocked. Real menu evidence can establish observed preference
state, not physical acquisition epoch or routing calibration.

## Historical loudness-foundation validation

2026-10-08, Windows, Python virtual environment in this checkout:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp="C:\Users\LINUSV~1\AppData\Local\Temp\opencode\pytest-loudness-full" -q
```

Result: **368 passed**. The analysis tests include calibrated mono/stereo sine
levels, silence, gain steps, section comparisons, relative gating, malformed or
unsupported audio, resource bounds, quiet audio after loud audio, null gaps, and
three independent FFmpeg EBU R128 oracle comparisons. Integration tests verify
tool discovery/schema and that analysis does not contact Live.

Before committing the feature, both independent-review findings were fixed:
integrated loudness excludes incomplete gating blocks, and capture provenance
retains restore failures and passage completion. Added regressions, including a
0.46-second FFmpeg oracle case, passed with the full first-feature suite:
**371 passed**. See `AUDIO_UNDERSTANDING_REVIEW.md` for findings and resolutions.

## Live experiment

Live 12.4.6 was open with a stopped, MIDI-only track and five returns. Strict
validation before and after the experiment reported `runtime_current: true`
and `live_mutations_safe: true`. No restart or Control Surface reload was needed.

A temporary owned audio track received an 18-second stereo 1 kHz PCM source:
amplitude 0.05 for six seconds, then 0.1 (expected +6.0206 dB). A 36-beat passage
was recorded with the existing capture workflow, selecting only that track.
The capture completed and finalized a 44.1 kHz stereo PCM WAV of 15.389025 seconds.
That raw duration includes recorder context; it does not prove exact passage
boundaries or timing calibration.

Analysis was exercised through the MCP `tools/call` handler:

| File-relative section | Integrated LUFS | RMS dBFS | Sample peak dBFS |
| --- | ---: | ---: | ---: |
| Low, 2–5 seconds | -26.016 | -29.036 | -26.028 |
| High, 10–12 seconds | -19.995 | -23.015 | -20.005 |

Measured difference: **+6.021 LU**, within 0.05 LU of the known gain step.
Whole raw capture: -21.890 LUFS integrated, -25.414 dBFS RMS, -20.005 dBFS sample
peak. These are source-chain measurements, not final master measurements.

Retained local evidence:

- Take ID: `9f296239fd744c46ab28a23577468ae2`.
- Manifest: `<state_dir>/audio_captures/9f296239fd744c46ab28a23577468ae2/manifest.json`.
- Source: `<state_dir>/loudness_validation/known_gain_step.wav`.

Both temporary tracks created during validation were removed (the first setup
attempt was rejected for an unregistered reference ID before clip insertion;
the second used a path reference). Final snapshot confirmed the original regular
track count, selected return, stopped transport, loop state, and playhead position.
No user clips or mixer settings were edited. The generated tap disappeared with
its owned track; capture files remain on disk for inspection.
