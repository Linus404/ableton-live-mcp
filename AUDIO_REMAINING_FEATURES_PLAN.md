# Remaining audio-understanding features (goals 5–8)

Scope follows the fifth through eighth bullets of `AUDIO_UNDERSTANDING_GOALS.md` exactly. All new analysis is bounded, offline analysis of existing WAVs; no Live calls, recording, mutations, AI models, universal quality scores, or human listening approval.

## Public contracts

- Goal 5: `live_audio_compatibility`, module `audio_compatibility.py`, entry `analyze_compatibility(args)`.
- Goal 6: `live_audio_stereo`, module `audio_stereo.py`, entry `analyze_stereo(args)`.
- Goal 7: `live_audio_integrity`, module `audio_integrity.py`, entry `analyze_integrity(args)`.
- Goal 8: `live_audio_development`, module `audio_development.py`, entry `analyze_development(args)`.
- Each owner exports lightweight `tool_properties()` returning the JSON-schema property dictionary and `TOOL_REQUIRED` listing required keys. Importing modules for discovery must not import optional numerical/audio dependencies; those belong inside analysis calls. Integration uses these directly rather than duplicating schemas. Runtime validation remains mandatory.
- Sources use `{name, path, signal_path}`: nonempty bounded strings, existing mono/stereo WAV, explicit identified signal path. Extra fields only when the feature genuinely needs them; schema and validation agree.
- Sections use `{name, start_seconds, end_seconds}` in file-relative seconds, or common-time seconds for explicitly aligned multiple sources. Unique names; finite nonnegative strictly ordered boundaries; at most 32; nonempty sample spans contained in analyzed audio.
- Simultaneous/paired sources require explicit `alignment: {verified: true, source: <evidence>, uncertainty_samples: 0, offsets_samples?: {<every source name>: <nonnegative file frame index>}}`, identical sample rate/channel layout, and equal lengths without offsets. Analyze only common remaining frames. Names are unique. Declarations are caller evidence, not physical qualification.
- Any in-mix audibility/attribution estimate additionally requires disjoint actual in-mix contributions and retained `provenance: {disjoint_contributions: true, in_mix_levels: true, signal_path: <description>}`. Reject overlap; raw tap timing/pre-fader signals do not establish this evidence. Listening-dependent estimates require explicit calibrated/assumed listening conditions as in existing masking/balance.
- Reuse existing `audio_analysis`, `audio_capture`, tonal/dynamics/masking/balance helpers where appropriate. No shared framework is required. New dependencies need demonstrated necessity; installed numpy/soundfile/scipy/pyloudnorm cover the intended DSP.
- Baseline limits: 128 MiB, 600 seconds, 12 million scalar samples per file, 8–192 kHz mono/stereo; at most 120 bounded local windows. Multiple-source requests additionally bound total decoded and repeated analysis work (96 million scalar sample-work maximum, tighter limits permitted). Reserve work before expensive decode/DSP; report tails, capped candidates and unmeasured coverage explicitly.
- Finite float64 processing; silence and numerical-floor conditions produce null/unavailable with reasons, never infinite ratios or fabricated values. Preserve original levels. Any loudness matching is a reported counterfactual gain/headroom, not a file change. Unrelated references are independent passages, never assumed aligned.
- Results separate `measured_facts`, `perceptual_estimates`, conditional interpretations/possible causes and musical judgments where applicable. Retain method, units, provenance, coverage and limitations. Successful processing does not establish exhaustive coverage or qualification.

## Goal 5 — Compatibility between sounds

Exact request: frequency competition, timing overlap, harmonic relationships, roughness, and whether important parts remain distinguishable together.

Acceptance: analyze explicit aligned real sources; report local time/frequency competition and co-activity, bounded harmonic/pitch evidence with confidence/unsupported cases, and research-grounded roughness estimates with model limitations. Distinguish harmonic relationships from subjective compatibility. Address distinguishability using qualified modeled prominence/competition evidence where valid and explicit unavailable outcomes otherwise; spectral overlap and roughness do not prove masking or bad sound. Preserve source attribution, silence, transients and frequency coverage. Synthetic checks must differentiate simultaneous vs separated activity, consonant vs beating partials, silence and invalid alignment/provenance.

## Goal 6 — Stereo and translation

Exact request: frequency-dependent width, phase relationships, mono cancellation, and changes in important-part audibility when folded to mono.

Acceptance: report broadband/local/section and frequency-dependent mid/side or equivalent width evidence, L/R phase/correlation with silence handling, and actual arithmetic mono-fold cancellation at retained original levels. Define mono convention and its gain explicitly. Important-part mono audibility changes need aligned disjoint in-mix programme/contributions and explicit listening conditions; reuse established masking/prominence logic for stereo-vs-mono evidence without converting estimates into listening approval. Single-source analysis must explicitly state contribution attribution/audibility unavailable. Check centered mono, hard-panned, anti-phase and frequency-dependent stereo fixtures plus retained-part fold comparisons.

## Goal 7 — Technical integrity

Exact request: true peaks, clipping, DC offset, unintended silence, clicks, abrupt edits, and final-file delivery measurements.

Acceptance: research-grounded oversampled true-peak estimate with explicit interpolation, edge/coverage/accuracy limits distinct from sample peak; clipping/sample rails and finite floating overs distinguish evidence from proof; channel DC; timed silence, discontinuity/click and abrupt-edit candidates with thresholds/limitations. Intentional silence/edit judgments require caller expectations and remain distinct from detections. Final-file metadata and original LUFS/peak/headroom/delivery checks concern the identified final file only; targets are explicit caller constraints, never universal defaults. Check intersample peak, rails, DC, silence, impulses/edit boundaries, float-above-unity and short/silent files. No automatic repair.

## Goal 8 — Musical development

Exact request: how balance, density, dynamics, and contrast change between sections, respecting intentional differences.

Acceptance: explicit named sections summarize programme/parts balance, temporal/spectral activity density with defined proxy, dynamics and inter-section contrast. Reuse completed goals 1–4 first; use 5–7 only if a needed section interaction/stereo/integrity observation cannot otherwise be supported. Retain original section levels and source evidence; distinguish intentional contrast from explicitly declared expectation departures. Density proxies are not note counts, arrangement understanding or musical quality. Explicit expectations/brief make conditional goal-progress/tradeoff evidence possible; no autonomous keep/revert or human approval claim. Check contrasting and intentionally equal sections, declared expected differences, short/silent regions, attribution availability and resource limits.

## Integration and verification

Feature owners own their module, feature-focused tests and individual scope plan. The exclusive validator owns `AUDIO_REMAINING_FEATURES_VALIDATION.md`. Integration owner owns `src/server.py`, `tests/test_mcp_server.py`, `README.md`, `AGENTS.md` and this plan. Each owner sends stable schema/entry readiness before registration. Run focused numerical/adversarial tests, editable local installation with existing audio-analysis extras and full repository tests; preserve failures and limitations. Physical Live qualification is outside this offline phase and belongs only to the designated Live owner. New feature commits/pushes require parent authorization.
