# Completion criteria: loudness/balance and audibility/masking

Scope is the first two bullets of `AUDIO_UNDERSTANDING_GOALS.md`. This checklist
defines required behavior for implementation and independent review; it is not
a claim that the unfinished work has passed.

## Required end-to-end behavior

1. Obtain real programme and disjoint part/group/return contributions at actual
   in-mix gains, with verified sample-clock alignment and identified signal paths.
   Preserve original music/routing/mute/solo state; record unsupported topology
   explicitly. Programme is a reference, not another independent contribution.
2. Report integrated and local loudness for programme, sections and parts, with
   aligned part-to-programme differences and timestamps.
3. Estimate in-mix prominence using a perceptual model rather than isolated
   loudness ranking. Separate modeled estimates from measured levels.
4. Identify level-change observations and assess unexpected section differences
   against caller-provided expected contrasts, without declaring intentional
   differences mixing errors.
5. Estimate audibility/masking using research-grounded masking thresholds,
   not spectral-overlap thresholds. Report affected times/frequencies, likely
   competing contributors, listening-level/calibration conditions and limits.
6. Support bounded original-versus-gain-scenario comparisons retaining original
   measurements and explicit level-matching conditions. A louder result alone
   must not establish improvement.

## Required verification

- Controlled audio checks for standards loudness and perceptual threshold/model
  equations, tonal/noise behavior, silence, time/frequency localization, source
  attribution, stereo handling, gains and malformed/resource-bound inputs.
- Live experiments verifying post-mixer volume/pan/mute/solo behavior, shared-clock
  capture, latency/signal-path behavior, programme reference, finalized files and
  owned-resource cleanup. Status declarations alone do not establish calibration.
- Independent correctness and feature-completeness review, independent numerical
  checks, and ponytail review. Resolve findings and record remaining supported
  conditions before claiming completion.

No model is human listening approval. Explicit normal-hearing/listening-level
assumptions and known physiological/model limits remain necessary even after the
required features are implemented; they must not disguise missing behavior.
