# Feature 1: loudness and balance evidence

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

Measured loudness provides evidence about levels, not proof of perceived
prominence in the mix. Intentional section contrast is not classified as a
problem. Raw pre-mixer captures cannot establish fader balance, exact temporal
correspondence, or final delivery loudness. Part-to-master comparisons therefore
remain explicitly unavailable. LRA and true peak are unsupported; no proxy is
substituted. This delivers the measurable loudness foundation of the first goal,
not a complete perceptual balance or masking assessment.

## Local validation

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
