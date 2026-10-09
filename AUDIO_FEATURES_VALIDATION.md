# First two audio-understanding goals: validation ledger

Scope: loudness/balance and audibility/masking, as defined by
`AUDIO_FEATURES_ACCEPTANCE.md`. This ledger separates delivered local behavior,
measured Live evidence, supported conditions and retained acceptance results.

**Status: complete for the first two goals under the supported conditions below
(2026-10-09).** Public native regular/group/return calibration and both explicit
and default MCP capture-to-assessment workflows passed. Independent acceptance
review found no remaining blocker, and the original Live set was restored.
Historical raw-tap validation is separate from this native qualification.

## Local implementation evidence

- Offline BS.1770 programme/part integrated, local and section loudness;
  caller-declared expected section contrasts; retained original/gain scenarios;
  explicit isolated loudness-match gain/headroom reporting.
- Separate measured auditory-filter excitation and modeled MPEG-1
  Psychoacoustic Model 1 adaptation: tonal/noise maskers, Bark spreading,
  absolute hearing threshold, time/frequency threshold margins and source
  attribution under explicit calibrated or assumed listening conditions.
- Strict native-manifest assessment: valid experimental qualification required;
  complete capture/cleanup; all selected entries retained; unique identities;
  finalized native metadata; bounded exact float64 equality to interleaved
  derivative channels, including a PCM32 least-significant-bit regression.
- The interleaved DOUBLE file is a frame-faithful derivative of retained native
  recordings, not a multichannel acquisition clock proof. All native, routing,
  normalization and qualification evidence is retained in the assessment report.
- Integration/server/settings checks: **188 passed** before subsequent PID-guard
  additions. Native settings helper checks subsequently passed **16 tests**.
  Return-selector MCP dispatch/schema checks passed **6 tests**. The current
  combined integration/server/settings suite then passed **196 tests** using
  `pytest-audio-current-integration` under the approved temporary directory.
  These are local
  results, not substitutes for the physical evidence below.
- After adding verified group-coverage and non-audio scope guards, the combined
  integration/server/settings suite passed **220 tests** in
  `pytest-audio-final-partition-integration`; `git diff --check` passed.
- The explicit-selection alias fix then passed **228 integration tests** in
  `pytest-audio-final-alias-integration`; `git diff --check` passed. When regular
  selection is supplied, any excluded regular source is rejected irrespective
  of `song`/`live_set` or numeric-index path aliases. Default group/non-audio
  partition cases retain the qualified graph/capability requirements above.
- The final combined local suite passed **465 tests**, including native PCM16
  refusal, acquisition-clipping guards, routing/profile qualification and
  independent numerical checks. Independent correctness, completeness and
  ponytail review accepted the first-two-goal workflow.
- Independent reviewer confirmed the adapter's exact comparisons and native
  PCM32/DOUBLE handling. The multiple-Live-instance menu identity finding was
  routed to capture/qualification owners: settings must belong to the actual
  bridge-serving PID, with trust-guard code included in certificate hashes.
- Default partition exclusions are checked only after qualification: actual
  group-ID/output-route chains must reach a captured terminal group. Explicit
  selections, external/No Output audio paths and ambiguous routes are rejected.
  Unrequested non-audio controls require actual pinned `has_audio_output: false`,
  never a silence heuristic. The manager's two final SDK profile reads matched
  SHA-256 `ae1b88b583d17db3eaffa17336f5eb0cb47a5563bc64b753f2b84043a15a639a`,
  with no critical unknown fields: MIDI source `1844500616` was false and the ten
  other sources true. This readback establishes capability evidence, not a fresh
  acquisition certificate after the helper change.

## Historical native regular-track acquisition

The manager reported seven actual MCP calibration scenarios passing, with
`qualified: true` and complete owned-resource cleanup. Retained experiment:

`C:\Users\Linus V2\.ableton-live-mcp\in_mix_calibration\01ebec5661a947479947137fcd48799e\experiment.json`

Reported certificate SHA-256 prefix: `893341c74d`. The certificate and experiment
files carry the full identities; this prefix is a locator, not a verification
substitute.

Independent physical review decoded **21 WAVs**, verified retained hashes and
measured a correlation lag of **88,200 samples** across all seven scenarios.
The experiments exercised native recording epoch, Post Mixer gain/pan/mute,
programme reference, shared timing and mixer/device-latency behavior. Keep their
numerical measurements and per-scenario checks in the retained experiment rather
than inferring qualification from acknowledgement flags.

Source track-delay fields and Master mute were unavailable and remain `null`.
They were not assumed zero or false: functional nonzero-reference and current
fixed-offset sum evidence provide the relevant checks. The measured pan-left
residual floor was approximately **1e-5**, not mathematically zero silence.

## Final public calibration and actual MCP assessments

Public `live_audio_capture_in_mix_calibrate` completed with `qualified: true`
and `cleanup_complete: true` on the final frozen source. Retained experiment:

`C:\Users\Linus V2\.ableton-live-mcp\in_mix_calibration\24b4d302241e413c8dcb52d63ec2ee21\experiment.json`

Certificate SHA-256:
`0130cd432e60a5a000b84570e523030cffdd3c3dd1c23b00348095c2d87b91b2`.

Qualification includes actual native recording epoch, mixer gain/pan/mute and
latency experiments, repeated current group/existing-return measurements,
source-ID offsets bound to stable routing/latency/capability profiles, and
fixed-offset verification on each current capture. Return processing is retained.
The certificate is not a global promise about arbitrary routing, devices or
future changed sets.

Independent review verified **22 public calibration takes**: seven base
mixer/latency takes, twelve return takes (six existing returns × two epochs),
two group takes (one existing group × two epochs), and one full original-set
admission take. These retained **70 native stereo WAV copies**: 21 base, 24 return,
16 group and 9 final admission files. Generator fixtures and constructed DOUBLE
derivatives are excluded from that native-acquisition count. Certificate evidence
contains 62 hashes: 61 native copies plus the base fixture; the nine admission
files were independently sample/hash checked in their retained manifest.

Two actual public MCP capture/assessment runs retained full requests/responses:

| Run | Retained directory under approved temporary `audio-feature-final-mcp` | Native paths | Contributions | Common file duration |
| --- | --- | ---: | ---: | ---: |
| Explicit Group + B + F + Main | `20261009-154510` | 4 | 3 | 12.904467 s |
| Default Group + B + all six returns + Main | `20261009-154800` | 9 | 8 | 12.927687 s |

Each directory contains `02_live_audio_capture_in_mix.json`, original and B+6 dB
counterfactual `04_live_audio_assess.json` / `05_live_audio_assess.json`, fresh
before/after set snapshots, native captures and `section_provenance.json`.
Both captures/cleanup and all four assessments completed successfully. All parts
had complete modeled-window coverage with zero unmeasured tail; 0.5 s windows
were used. The default run retained five silent existing returns and preserved
the two legitimate exclusions: the pinned non-audio MIDI control track and the
audio child whose actual output fed the captured terminal group.
The two assessment acquisitions add **13 native stereo WAVs** (4 + 9), bringing
the distinct native references across these public workflows to **83**. Re-decoding
the same files during another check is not counted as new acquisition evidence.

| Actual reported evidence | Explicit run | Default run |
| --- | ---: | ---: |
| Programme integrated LUFS | -24.464 | -24.464 |
| Original B integrated LUFS | -44.064 | -44.064 |
| B +6 dB scenario integrated LUFS | -38.064 | -38.064 |
| Programme local-section contrast (LU) | -0.029 | +0.055 |
| B early-section integrated LUFS | -48.050 | -48.050 |
| B late-section integrated LUFS | -42.114 | -42.030 |

The caller's controlled-fixture programme expectation was **0 ±1 LU**; both
observed contrasts were within that declared expectation. B's largest adjacent
sampled short-term change was **+1.760 LU from common-time 6.0 to 6.5 s**.
These are level observations, not automatic mixing errors. Sections were caller-
defined in each aligned common-file interval, with
`arrangement_mapping_verified: false`; no exact Arrangement/source-position
claim or cross-capture window correspondence is inferred.

The declared listening level was explicitly **assumed 100 dB SPL at 0 dBFS RMS**,
not measured monitor calibration. B's modeled all-active-components-below-
threshold interval changed from **1–11 s** to **1–6 s** under the +6 dB scenario.
Positive masking-threshold attribution came from the captured Group and F return.
This is a spectral model response, not human audibility approval.

Offline inspection checked **560 B component records** across the two runs for
finite SPL values, threshold-margin arithmetic and classification. Matched
components gained exactly 6 dB of threshold margin while competitor thresholds
remained unchanged; scenario `original_perceptual_estimate` values matched the
baseline. Entire original measurements and capture evidence were retained, and
the programme report was unchanged by the counterfactual.

Isolated fair loudness matching suggested **+21.064 dB** for B at -23 LUFS, with
predicted sample peak **-20.874 dBFS**. The gain was **not applied**. Neither this
suggestion nor the louder scenario establishes musical improvement, and the
counterfactual does not pretend to recompute nonlinear master processing.

The full report audit is reproducible with the approved-temporary offline
`audit_audio_feature_reports.py`; it imports no Live modules and makes no Live
calls. Independent reviewers accepted the physical and model evidence.

Independent numerical review checked **1,248 local values**, **572 model windows**
and **7,688 model component records** across the four assessment reports, plus
40 original B tonal FFT windows. A separate K-weighting/BS.1770 gating, local and
section loudness, RMS/peak implementation differed by at most
**0.000498718 LU/dB**. Physical review checked all 22 current sums against the
PCM-quantum/float-Higham bound and fourteen role epochs using correlation plus
neighbor-offset rejection. Controlled independent references covered TwoLAME
spreading branches, ATH/Bark equations, noise/stereo/gain behavior and Parseval
agreement (maximum error approximately `1.22e-15`); the 48 kHz sine oracle was
-23.00359556 LUFS against the reported -23.004.

The independent review and exact methods/scope are retained in the approved
temporary `independent_audio_features_final_review.md`. Its 191 focused local
checks are separate from the final 465-test combined suite, not an additional
465+191 unique-test claim.

## Measured return-path timing observations

An owned return without effects showed approximately one sample of acquisition
lag relative to its corresponding Master contribution: about **23 microseconds**
at 44.1 kHz. Further controlled changes produced offsets **65, 129, 193 and 257
samples** with Limiter/device latency, child latency and even a non-sending
128-sample-latency source elsewhere in the set.

These are **acquisition delays**, not instructions to remove musical delay,
echo or reverb tails. Calibration must compare the same processed return signal
with its programme contribution. Preserve creative processing; establish a
measured, profile-bound acquisition offset. A regular-track certificate cannot
be reused as proof of return/group timing, and each musical take must not become
an unconstrained alignment search.

## Supported conditions and limits

Current physical evidence is scoped to stopped transport, Delay Compensation
enabled, Reduced Latency When Monitoring disabled, an unprocessed unity Main
path, no existing armed tracks, recording/automation writing or solos, and
verified Windows English native-menu state from the bridge-serving Live process.
Native physical qualification additionally requires PCM24/PCM32 or
float32/float64 recording preferences. PCM16 failed the fixed physical-reference
relative-floor checks independently and is explicitly unsupported for qualified
native capture/assessment: calibration rejects it after the first take, before
the remaining scenarios, and current-native sum verification enforces the same
gate. A higher-resolution certificate is not transferable to PCM16. Standalone
offline PCM16 analysis and unqualified recording remain available; tolerances
were not globally loosened to conceal this acquisition limit.
Current-native sum verification also rejects PCM samples at `<= -1` or
`>= 1 - LSB`, preserving possible acquisition clipping as an unsupported linear-
proof condition. Identical clipped part/programme files are not valid sum evidence.
Finite floating-point values above unity remain supported. The owner reported
**28 passing focused tests**, including an identical clipped-PCM refusal and a
float 1.1 acceptance regression, before freezing this guard.
Capture runs one real-time passage and restores the stopped position/insertion
marker. Active-playback restoration is unsupported.

Unknown source latency/track delay remains unknown. Exposed known nonzero track
delay requires measured qualification before support. Upstream device identities
are retained evidence, not a device whitelist. Shared processing and creative
return tails must not be silently removed to fit a timing model.

Perceptual thresholds are normal-hearing spectral estimates under an explicit
listening level, not standardized partial loudness, an audibility probability or
human listening approval. Binaural/temporal masking and unknown nonlinear master
gain recomputation remain unsupported. Section judgments apply only to declared
expected contrasts; louder gain scenarios are not automatically better.

## Acceptance and restoration closed

All six behavior items and the verification items in
`AUDIO_FEATURES_ACCEPTANCE.md` passed independent review for this supported
workflow. Regular, group and existing-return calibration is repeatable through
the public tool; explicit/default manifests reached real measured-level and
perceptual-model assessment, including original-versus-gain evidence and declared
section expectations. Numerical/correctness and ponytail findings were resolved.

All four owned musical validation actors were removed. Group deletion cascaded
to its owned child; a temporary cleanup-script ordering retry did not change
repository source. The authoritative settled read-only restoration proof is:

`C:\Users\LINUSV~1\AppData\Local\Temp\opencode\audio_roles_final_restoration_verified.json`

It confirms the original sole MIDI track ID `1844500616`, original five return
IDs, stopped/non-recording transport, original time `1.094240395021645`, insertion
marker 0, loop disabled with original start 8/length 16, punches disabled,
selected E return `1844888696` and device `1844890416`, and empty role,
calibration, offset and capture registries. The earlier immediate cleanup
snapshot showed a lagging position; the settled follow-up is authoritative.

The manager's final strict health probe **after cleanup** passed with
`runtime_current: true` and `live_mutations_safe: true`, for Live process `1040`
and song ID `128917144`. This confirms current bridge health after restoration;
it does not transfer the removed rig's certificate to the changed current profile.

The retained certificate and reports describe the historical validation profile.
Removing the owned rig changed the current profile; future captures must obtain
applicable current-profile calibration rather than reuse that certificate.
Offline verification preserves the historical evidence and its scope.

## MCP invocation examples for final acceptance

The examples below describe the public tool path; they are not records of
completed physical calls. Replace placeholders with the retained current manifest
path and actual captured contribution names. Section bounds must fall inside the
common file interval; the example's +6 LU expectation is appropriate only for a
  fixture intentionally authored with that contrast. Do not invent an expectation
for the user's music. The listening reference is explicitly assumed, not measured.

First run `live_audio_capture_in_mix_calibrate` with `{}` or an optional
`output_directory`. A stale certificate after capture/helper/bridge trust-guard
changes must not be reused. The public calibration must measure supported roles
and current routing/latency profiles; a successful older regular-only experiment
does not establish a changed return/group path.

Then `live_audio_capture_in_mix` can record a stopped-transport passage:

```json
{
  "start_beat": 0,
  "length_beats": 16,
  "track_refs": [{"path": "live_set tracks 0"}],
  "return_refs": [],
  "include_master": true,
  "max_duration_seconds": 120
}
```

Use actual current track references; an empty return selector deliberately
selects none. For return acceptance, select the physically qualified existing
return references instead. Preserve complete capture/cleanup and qualification
proof before passing the resulting manifest to `live_audio_assess`:

```json
{
  "manifest_path": "<current-qualified-manifest.json>",
  "listening_condition": {
    "kind": "assumed",
    "db_spl_at_0_dbfs_rms": 100,
    "source": "Explicit normal-hearing monitor-level assumption; no measured SPL calibration"
  },
  "sections": [
    {"name": "low", "start_seconds": 0, "end_seconds": 2},
    {"name": "high", "start_seconds": 2, "end_seconds": 4}
  ],
  "expected_section_differences": [
    {"from_section": "low", "to_section": "high", "expected_delta_lu": 6, "tolerance_lu": 0.1}
  ],
  "gains_db": {"<captured contribution name>": -3},
  "fair_loudness_match": {"target_lufs": -23},
  "window_seconds": 0.5,
  "max_windows": 120,
  "window_step_seconds": 0.5
}
```

Inspect original and gain-scenario measurements, aligned local/section differences,
section-expectation judgments, per-part perceptual-model output and complete
coverage. Preserve modeled prominence/threshold estimates separately from level
facts. `capture_evidence` must retain the actual native sources, constructed
derivative, qualification, routing/menu/runtime evidence and cleanup outcomes.
Refusals for stale/unqualified or unsupported captures are expected fail-closed
behavior, not a successful final assessment.
