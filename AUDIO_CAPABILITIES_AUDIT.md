# Audio capabilities audit

Read-only audit of the implementation, original goals, git history and retained
acceptance/review documents, 2026-10-10. This document is the only audit change.
No Live calls, implementation changes, commits or pushes were made. The reported
639-test run and physical experiments are retained acceptance evidence, not runs
repeated by this audit. Historical runtime validation is not current Live health.

## Direct answers

| Question | Answer |
|---|---|
| Are all features committed separately? | **No.** Goals 1–4 are committed, but 1–2 share infrastructure and acceptance commits. Goals 5–8 and their integration/evidence are still working-tree changes. |
| Are all eight original features done? | **All eight have bounded implementations and retained acceptance evidence. The entire original aspiration is not fully delivered.** Several clauses are modeled estimates, proxies or explicitly unavailable, and the cross-feature decision/comparison workflow is incomplete. |
| Are these the best implemented solutions? | **They are reasonable, lean, reviewed measurement solutions for their declared scope; “best” is not established.** There is no comparative method benchmark or perceptual validation establishing superiority or general human prediction accuracy. |

The original source is `AUDIO_UNDERSTANDING_GOALS.md`, especially lines 11–18
(eight features) and 20–40 (comparisons, decisions and desired outcome). A narrower
feature plan passing acceptance does not erase broader clauses in that source.

## Actual commit mapping

| Goal | Commits and actual boundaries |
|---|---|
| Shared acquisition prerequisite | `4ba0961` — raw multi-track Arrangement capture, tap companions, bridge/server integration and original goals. Raw taps are not qualified in-mix contributions. |
| 1. Loudness/balance | `b481798` — offline loudness backend and public analyze tool; `17b3ff4` — balance plus masking backend; `a20f972` — shared native capture/calibration; `43eb98c` — public assessment/integration and goals 1–2 acceptance. |
| 2. Audibility/masking | `17b3ff4` — masking **and** programme balance; `a20f972` — shared qualification; `43eb98c` — public masking/balance/capture/assessment integration and shared acceptance. This is not an independent single-feature commit chain. |
| 3. Tonal balance | `99f9290` — analyzer, public tool and tests; `8d5e78e` — workflow and independently verified evidence. Separate from other features, split into code and documentation. |
| 4. Dynamics/impact | `f211e87` — analyzer, paired processing/public tool and tests; `13de6f4` — workflow, plan/reviews and independently verified evidence. Separate from other features, split into code and documentation. |
| 5–8 | **No commits yet.** Four new `src/audio_{compatibility,stereo,integrity,development}.py` modules and matching tests/plans are untracked. Shared registration/tests, README/AGENTS and the masking helper change are tracked modifications. Shared reviews, validation document and five `validation/remaining_*.py` helpers are untracked. |

The observed HEAD is `13de6f4`. Existing commits are logical implementation
layers, not eight isolated feature commits. Goals 5–8 need dependency-aware
staging: stereo imports the new masking helper; registration currently adds all
four tools together. A commit containing registration without its required modules
would not be a working intermediate revision. Separate future commits can retain
feature boundaries while including the shared prerequisites they actually need.

## Goal-by-goal capability versus original wording

“Full measurement” below means the stated numerical observation is implemented,
not exhaustive coverage, perception equivalence or musical approval.

| Original goal | Implemented evidence and entry points | Honest scope / remaining gap |
|---|---|---|
| **1. Loudness and balance** | `live_audio_analyze`: gated BS.1770 LUFS, momentary/short-term, RMS/peak and sections. `live_audio_balance` / `live_audio_assess`: original part/programme levels, aligned local/section contrasts, explicit expected level changes, gain scenarios and modeled prominence. | **Full bounded level measurements; modeled prominence.** LUFS differences are not additive part shares or perceived balance. Standardized partial loudness and LRA are unavailable. Reliable in-mix use requires applicable physical acquisition qualification. |
| **2. Audibility and masking** | `live_audio_masking`: timed roex excitation competition, frequency/source attribution, and optional Model-1-adapted thresholds under explicit listener assumptions. Qualified manifest assessment exposes that evidence. | **Measured competition + perceptual estimate, not demonstrated burial/audibility.** No human detectability/recognition probability, temporal/binaural unmasking or correlated/nonlinear bus prediction. The >=0.5 competition rule is descriptive, not an audibility threshold. |
| **3. Tonal balance** | `live_audio_tonal`: broad/octave-band energy, centroid/rolloff, qualifying peak widths/recurrence, timed sections/windows, explicit brief departures and independent reference shape/LUFS-match predictions. | **Full bounded spectral observations; conditional interpretations.** Resonance versus intended harmonics and muddiness/harshness are not proven. 250 ms Welch, 4 Hz nominal resolution, transient weighting, Nyquist coverage and omitted tails limit evidence. Reference comparison is whole independent passage, not aligned before/after events. |
| **4. Dynamics and impact** | `live_audio_dynamics`: original crest/levels, explicit or detected attack/body/tail events, quantized rise/envelopes, eligible modulation runs, aligned same-source before/after and predicted LUFS-matched differences. | **Full bounded dynamics observations; proxy for punch/pumping.** Modulation can be intentional; envelope level change is not literal gain reduction. No perceived punch or causal compressor diagnosis from arbitrary recordings. Sustained >=4 s eligible runs are needed for modulation; event detection is nonexhaustive. |
| **5. Compatibility between sounds** | `live_audio_compatibility`: existing competition/model plus original-level 10 ms coactivity/exposure, retained FFT partial relationships and normalized cross-partial Sethares-kernel roughness, local windows and gain scenarios. | **Bounded requested interactions; modeled distinguishability.** Partial ratios supply a limited form of the requested harmonic relationships. Top-12 partials/top-three cross pairs do not imply f0/key/chord recognition (those were not explicitly requested) or reliable human distinguishability. Roughness omits residual noise/self-roughness/phase/temporal effects. Section names label overlapping windows, not exact section aggregates. |
| **6. Stereo and translation** | `live_audio_stereo`: frequency-dependent M/S energy, normalized cross-power/phase, arithmetic `(L+R)/2` cancellation and optional aligned important-part stereo/mono prominence model. | **Full bounded stereo/fold observations; audibility/translation estimate.** In-mix target mode requires aligned disjoint contributions and listener conditions. No room/speaker/headphone translation guarantee or human mono audibility proof. Comparison retains actual gains/SPL; it is not a loudness-matched listening comparison. |
| **7. Technical integrity** | `live_audio_integrity`: 4x polyphase peak estimate and times, sample peaks, DC, PCM rail/float-unity observations, timed silence/jump candidates and explicit metadata/LUFS/DC/peak delivery checks. | **Bounded diagnostics, not certified true-peak/delivery compliance.** Kaiser FIR/fourfold grid lacks a proven continuous-maximum error bound; near-Nyquist/edge maxima remain limited. Rail contact is not proven clipping; silence/click/edit intent is unknown. Checks concern the identified WAV, not automatically the final export. |
| **8. Musical development** | `live_audio_development`: explicit named section levels/dynamics/tonal contrasts, acoustic candidate rate, effective broad-band entropy, optional actual-part balance, and caller-declared expected contrasts. | **Section measurement and density proxies, not arrangement comprehension.** Candidate rate is not note/source/polyphony count; band entropy is spectral spread. Intent is respected through expectations, not inferred. No independent musical-quality or keep/revert judgment. |

Schemas and implementations are present in `src/server.py`, the above modules,
`src/audio_analysis.py`, `src/audio_balance.py`, `src/audio_masking.py` and
`src/audio_assessment.py`. The qualified adapter calls
`in_mix_qualification.verify_qualification`; standalone analyzers generally
validate caller declarations rather than independently proving acquisition.

## What the retained evidence establishes

- `AUDIO_FEATURES_VALIDATION.md` and `AUDIO_FEATURES_ACCEPTANCE.md` close the
  bounded goals 1–2 workflow under measured conditions: stopped transport,
  PDC enabled, Reduced Latency When Monitoring disabled, unprocessed unity Main,
  applicable route/device profiles and supported native PCM24/PCM32/float.
  PCM16 acquisition qualification and possible clipped-PCM linear proof are
  unsupported; SDK fields that were not exposed remain null. A removed calibration
  rig does not provide a reusable certificate for future changed music/routing.
- `AUDIO_TONAL_VALIDATION.md` records numerical/MCP and actual identified-audio
  evidence; `AUDIO_DYNAMICS_VALIDATION.md` and its independent review record
  physically measured same-source compression/limiting experiments and paired
  public calls. Those experiments are not general human sound judgments.
- `AUDIO_REMAINING_FEATURES_VALIDATION.md` records eight successful public analysis
  calls, two intended evidence refusals, exact archived source hashes, independent
  sample-domain checks and restoration. Goals 5–8 used a **PDC-off, empty-device,
  two-source historical take**, with measured beginning/end markers and whole-frame
  programme-sum residual `1.1920928955078125e-7` below three PCM24 quanta. The
  unqualified acquisition manifest was not rewritten or passed to assessment.
  This supports those exact files, not arbitrary device/group/return calibration.
  Listener level was assumed 100 dB SPL at 0 dBFS RMS, not physically calibrated.
- Compatibility/stereo and integrity/development independent reviews pass their
  bounded contracts; the complexity review confirms reuse and resolves the
  duplicated Model-1 helper. The final validation document reports **639 passing
  tests in 97.15 seconds** and a clean diff check. These counts demonstrate tested
  software behavior, not eight scientifically complete perception capabilities.

## Are the methods the best choice?

For a dependency-light, no-audio-AI evidence toolkit, the architecture is sensible:
established level measurement, direct sample-domain diagnostics, explicitly bounded
spectral methods, reuse of masking for compatibility/stereo, and composition of
tonal/dynamics/balance for development. No blocking unresolved correctness finding
is retained in the cited reviews. There is no evidence-based reason here to replace
the architecture or add speculative frameworks.

The highest-value scientific improvements are narrower: stronger true-peak
conformance/near-Nyquist testing, validated partial-loudness/detectability models,
time-varying pitched/noisy source treatment, and measured listener/acquisition
conditions. Calling the current methods “best” would require comparison against
alternatives and independent perceptual ground truth. The current references and
analytical oracles establish the disclosed mathematics, not that missing benchmark.

## Actionable gaps and follow-on priorities

1. **Finish delivery bookkeeping:** commit goals 5–8 with working intermediate
   revisions and shared evidence/integration assigned explicitly. Use “all eight
   bounded measurement tools implemented and validated” as the completion claim.
2. **Close the original cross-feature experiment workflow:** pin same-source
   before/after identity, section/time basis, route/device/mastering state,
   original levels and fair comparison gains across reports. Dynamics supports a
   paired experiment, tonal supports an independent reference, and balance supports
   gain counterfactuals; there is no unified, remeasured arbitrary-edit comparison
   covering all eight. Unknown nonlinear master effects must be measured again.
3. **Make acquisition broadly reusable where physically possible:** qualify actual
   regular/group/return/pre/post-master paths and changed latency/profile conditions
   rather than transferring the empty-rig take or removed-rig certificates. Retain
   unsupported routing outcomes. This is the principal practical bottleneck to
   attributing findings in real complex sets, not a missing analyzer menu item.
4. **Add goal-conditioned decision support:** combine measured tradeoffs with
   declared expectations and uncertainties into an agent-readable assessment of
   whether the stated measurable objective improved. Keep subjective questions
   unavailable. Do not replace this with a universal score or automatic approval.
5. **Where the original wording needs more than proxies:** improve validated
   perceptual distinguishability, musically interpretable density, and delivery
   accuracy. Partial-loudness and richer harmonic/time-varying analysis are possible
   method improvements, not explicit requirements for f0/chord recognition or a
   particular psychoacoustic model. Accepted bounded implementations remain done;
   completion of their plans does not turn estimates into reliable listening.
6. **Beyond the original list:** retain reusable experiment IDs/content hashes and
   a compact cross-tool report index, expose supported-versus-unsupported workflow
   status before capture, and benchmark perceptual estimates against an independent
   listening dataset. These are useful follow-ons, not retroactive acceptance
   requirements or reasons to discard the existing measured evidence.

Bottom line: the project now has all eight accepted bounded numerical evidence
features. The broader desired outcome of reliably judging sound interactions and
arbitrary edits against musical goals is not fully demonstrated, and a unified
“this edit improved the stated goal, retain it” workflow remains to be built.
