# Independent implementation and ponytail review

Reviewed 2026-10-08 by a separate agent. No implementation files were changed
and no Live calls were made during the review.

## Correctness findings

### P2: incomplete gate blocks bias integrated LUFS

Location: `src/audio_analysis.py:44`, shared `_measure`; also affects named
sections measured at `src/audio_analysis.py:93`.

The installed pyloudnorm 0.1.1 backend rounds the number of overlapping gating
blocks. For some durations not aligned to its 100 ms hop, this includes an
incomplete final block whose energy is normalized by a full 400 ms duration.
Consequently the integrated LUFS result is biased despite the reference BS.1770
measurement claim. Arbitrary section durations expose this in ordinary use.

Independent reproduction: a 0.46-second mono 1 kHz sine at amplitude 0.1 and
48 kHz measured **-23.227 LUFS** through this implementation, versus **-23.0 LUFS**
with FFmpeg `ebur128`. A complete 0.4-second block measured -23.004 LUFS.

Minimal recommended fix: in `_measure`, supply integrated_loudness only the
interval ending at the last complete 400 ms block on the 100 ms hop grid. Keep
reported duration, RMS, sample peak, and continuous local windows based on the
original data. Add a non-hop-aligned short-file and section oracle regression.

### P2: incomplete-capture restore diagnostics are dropped

Location: `src/audio_analysis.py:202`, compact capture provenance.

`src/audio_capture.py:301-302` records restore failures as `restore_error`.
Its completion logic can mark a take incomplete for this reason even when every
track was successfully captured. The analyzer preserves the incomplete flag but
drops `restore_error`, leaving all entries analyzed and no reported explanation
for the incomplete capture.

Minimal recommended fix: preserve `restore_error` in compact capture provenance
and test a manifest whose only failure is a restore error. Preserving
`passage_observed_complete` would also clarify the passage completion context
without returning the large observations log.

## Ponytail review

**No actionable over-engineering findings.** The implementation is already lean:
it reuses WAV validation and established numerical/backend libraries and adds no
speculative abstractions or Live orchestration. No complexity cuts recommended.

## Checks and scope

- Read the current diff, new analysis module and tests, implementation report,
  goals, capture/manifest implementation, package configuration, and installed
  pyloudnorm integrated-loudness and filter code.
- Analysis and tool integration tests: **19 passed**.
- MCP server tests: **153 passed**.
- Total targeted tests: **172 passed**, including existing FFmpeg oracle tests.
- Independently reproduced the non-hop-aligned loudness discrepancy above.

No additional correctness or integration findings were identified. Resource
bounds precede sample allocation; decoder resources are managed; per-entry
failures remain explicit; optional imports are lazy; local K-weighting preserves
continuity and correctly sums mono/stereo channel weights.

Unsupported LRA, true peak, aligned part-to-master comparisons, perceived
prominence/masking, and judgments about intentional contrast are clearly stated
limitations. The delivery is explicitly the measurable loudness foundation of
goal 1 rather than complete perceptual balance assessment.

This review did not independently exercise Live or inspect the retained capture.
The implementation's Live experiment was reviewed as documented evidence only.
An official ITU/EBU full conformance corpus and cross-platform dependency
installation were not tested.

## Resolution before the feature commit

Both P2 findings were fixed in the shared measurement/provenance paths. Integrated
loudness now excludes incomplete gating blocks while RMS, peak, duration and local
windows still use the original data. Capture reports preserve `restore_error` and
`passage_observed_complete`. Regression tests cover the 0.46-second file and named
section, an additional FFmpeg oracle case, and restore-only capture failure.
