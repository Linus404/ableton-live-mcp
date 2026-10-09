# Feature 4 plan — dynamics and impact

## Ordered source and scope

`AUDIO_UNDERSTANDING_GOALS.md`, **What we want to understand**, is the original
ordered list: (1) loudness/balance, (2) audibility/masking, (3) tonal balance,
(4) dynamics/impact, (5) compatibility between sounds, (6) stereo/translation,
(7) technical integrity, (8) musical development.
`AUDIO_FEATURES_ACCEPTANCE.md` covers only goals 1–2; their completion is recorded
in `AUDIO_FEATURES_VALIDATION.md`. `AUDIO_TONAL_VALIDATION.md` records feature 3
complete. The exact next goal is:

> **Dynamics and impact:** transient strength, attack/body/tail relationships,
> crest factor, pumping, and changes in punch caused by compression or limiting.

Deliver bounded offline measurements and qualified before/after evidence for
all five clauses. No universal punch score, inferred compressor settings, or
human keep/revert judgment. A crest-factor-only tool does not satisfy this goal.
PLAN ONLY: this document makes no implementation or new Live-validation claim.

## Smallest reusable implementation

Add `src/audio_dynamics.py:analyze_dynamics(args)` and `live_audio_dynamics` in
`src/server.py`, following `live_audio_tonal`'s lazy import/offline dispatch.
Reuse `audio_capture.validate_wav`, `audio_analysis._seconds`, `_finite`, `_db`
and `_measure`, and existing source/section schema shapes. NumPy, SoundFile,
pyloudnorm and its existing SciPy dependency suffice; no new dependencies,
capture mode, M4L device, Remote Script command or analysis framework.
Keep dynamics-specific envelope/events/comparison logic in the new module.
Do not invoke the masking analyzer simply to validate alignment. Reuse its
contract; extract a tiny shared validator only if it truly simplifies both
callers without broad refactoring.

### Public request

- `source: {name,path,signal_path}` required; existing mono/stereo WAV only.
- Optional `comparison` with the same shape: after-processing version of the
  same source passage, not an arbitrary musical reference.
- Optional `alignment: {verified:true,source,uncertainty_samples:0,
  offsets_samples?}` required for any paired comparison. Offsets map both unique
  source names to frame indices at common time zero; otherwise lengths must
  match. Require identical sample rates/channel layouts and a nonempty common
  interval. Declarations are caller evidence, not independent verification.
- Optional `sections: [{name,start_seconds,end_seconds}]`, at most 32, in source
  file seconds for standalone analysis or common-time seconds for comparisons.
- Optional `events` (at most 120), each `{name,start_seconds,attack_end_seconds,
  body_end_seconds,end_seconds}` with strictly ordered, in-range boundaries.
  Explicit events let a musical brief define what attack/body/tail means.
- Optional `window_seconds` (0.01–600), contiguous aggregate output capped at
  120 windows; default adapts to duration. This is reporting granularity, not
  the internal envelope resolution.
- Optional `brief: {description}` retained as intent; no invented target rules.

### Measurement contract

1. Whole, section and local original RMS, sample peak, integrated LUFS and
   crest factor (`peak dBFS - RMS dBFS`). Include per-channel crest and pooled
   channel-power crest; never fold stereo to mono. Silence yields null ratios
   with reasons, not zero-dB crest. Preserve existing LUFS gating/duration limits.
2. One continuous 10 ms nonoverlapping RMS/sample-peak envelope per file/common
   passage, plus the final partial cell with its actual duration. Perform event
   sample peak/RMS/energy measurements directly from samples, not envelope
   approximations. Report time quantization and any incomplete comparisons.
3. Without explicit events, bounded candidate onsets: >=6 dB RMS rise against
   the preceding 100 ms RMS, above an explicit numerical floor, 50 ms refractory
   period. Silence-to-signal is separately marked. Default attack/body/tail
   spans are 0–20/20–100/100–300 ms after onset, truncated at the next onset or
   file end, with missing spans unavailable. These are disclosed operational
   regions, not instrument-independent perceptual attack definitions. Candidate
   counts, truncation and omitted events must be visible; never silently present
   the first 120 as complete. Events in paired mode are source-defined and shared,
   so processing cannot change which events are compared.
4. Per event: regional sample peak, RMS, energy, duration, attack/body and
   tail/body RMS contrasts, attack peak/body RMS contrast, peak time and
   envelope rise time where measurable. Ratios of unequal-duration energy must
   not be mislabeled level contrast. Fixed regions do not establish physical
   decay constants or instrument identity. Boundary/overlap cases carry status.
5. Pumping evidence: report envelope variation and dominant modulation in
   0.5–10 Hz from the mean-removed RMS-level envelope on eligible nonsilent
   intervals (>=4 s), with numerical floor, frequency resolution and coverage.
   Label as amplitude-modulation evidence, not detected compression pumping:
   notes, tremolo, arrangement and intentional ducking can create it.
6. Paired mode additionally reports after-minus-before short-cell RMS level
   differences only when both cells have measurable energy. Describe these as
   level-change envelopes, not samplewise gain reduction: nonlinear processing,
   tails and changed waveform content break a literal gain interpretation.
   Modulation of this difference strengthens processing-change evidence but
   still does not diagnose objectionable pumping or sidechain causes.
7. Paired event/local/section deltas retain original levels and an explicitly
   computed comparison gain to source integrated LUFS. Apply that gain only
   mathematically to level comparisons; expose predicted sample-peak headroom
   and `gain_applied_to_files:false`. Gain-invariant crest/attack-body contrasts
   remain separate. Null LUFS means matched comparison unavailable, not an RMS
   fallback disguised as fair loudness matching. No waveform files are rewritten.

Output compact scalar summaries, up to 120 aggregate windows/events and a
bounded downsampled modulation summary, not every internal envelope sample.
Record method equations, thresholds, original metadata, signal-path evidence,
alignment evidence, observed facts, conditional interpretations and unmade
musical judgments separately. Distinguish `processing_complete` from event,
envelope and modulation coverage. Ordinary intentional section changes are
observations, never automatic faults.

## Limits, input protection and provenance

Mirror tonal bounds: two files, 128 MiB/600 seconds/12 million scalar samples per
file, 8–192 kHz mono/stereo, 96 million total sample-work including decode,
whole/local/section/event and repeated comparison work. Account for envelope
and modulation arrays/work too; refuse pathological requests before expensive
allocation. Validate all keys, booleans-as-numbers, finite values, duplicate
names, empty/subsample spans, decoder/header disagreement and invalid samples.
Use a documented absolute/relative power floor; floor-limited ratios are null.

Sample peak is not true peak; crest is not LRA or perceived punch. DC can distort
RMS and must be disclosed, not silently removed. Opposite-polarity stereo keeps
channel energy. Ten-millisecond cells and simple onset rules can miss/merge fast
events; no sample-exact onset or human transient-strength claim. A periodic
envelope is not proof of pumping. Rendered upstream/processed path attribution
requires identical source material, routing and measured latency alignment;
caller path strings and equal WAV lengths alone do not establish those facts.
Qualified native files retain their manifest/certificate externally; raw taps
support identified signal-point observations only. Do not manufacture current
qualification from the removed historical rig.

## Acceptance and meaningful checks

Add `tests/test_audio_dynamics.py` using existing pytest/fixture conventions:

- Analytic sine crest = 3.0103 dB; known pulse duty cycle gives its analytic
  peak/RMS crest. Uniform gain changes original levels but not crest/contrasts.
- Known burst/exponential envelopes and explicit regions verify sample energy,
  attack/body/tail values and timestamps; candidate onset checks include
  silence onset, boundary transients, repeated attacks and event-cap coverage.
- Known amplitude modulation localizes at its frequency/depth; steady sine
  has no fabricated pumping, short/silent/floor-limited spans are unavailable.
- An aligned known static limiter/compressor transfer reduces crest/attack
  contrasts as predicted; a louder untouched copy reports no dynamics improvement
  after matching. Known modulation of processing level change is observable.
- Stereo polarity reversal/channel asymmetry, float above unity, DC, final
  partial envelope cells, fractional boundaries and comparison offsets.
- Invalid/unknown arguments, mismatched files, false/absent alignment, changed
  metadata, nonfinite samples, resource/section/event work limits.
- MCP discovery + actual stdio dispatch with a bridge stub that refuses Live
  calls proves this tool stays offline. Independent reviewer derives at least
  crest, regional energy and modulation frequency without production helpers.

Acceptance requires all five goal clauses present with coverage/provenance
limits, targeted tests and affected MCP suites passing, `git diff --check`, and
one full repository test run after fixes. Extend `AGENTS.md`/`README.md` with
the final tool contract and write `AUDIO_DYNAMICS_VALIDATION.md` containing
actual numerical/public MCP/Live evidence; do not claim evidence from this plan.

## Deploy → real Ableton validation → reviews

1. Install editable package with the existing `audio-analysis` extra; restart
   the MCP server/client to refresh tools/list. Offline implementation needs no
   Control Surface reload. If deployment changes Remote Script/companions,
   install the applicable artifacts before runtime validation.
2. Before Live work, inspect Ableton-only UI/modal state and snapshot stopped
   transport, recording/automation, routing and original set state. Validate
   sequentially and require current runtime and `live_mutations_safe:true`.
   User permits using/restarting Live if needed; preserve uncertain unsaved
   work and ask rather than discarding it or declining recovery blindly.
3. Reuse retained real WAVs first for public stdio smoke checks, with hashes and
   identified signal paths. Historical tonal sine recordings alone cannot prove
   compression/limiting or pumping acceptance.
4. Obtain a real controlled Live percussive passage before/after built-in
   compression/limiting: one transparent baseline, one strong attack-reducing
   setting and one deliberate audible-envelope ducking/release setting.
   Use existing acquisition/render workflow and owned validation resources;
   preserve original music and do not assume raw tap startup is aligned.
   Establish same-source identity, gain/routing and measured path offsets from
   retained calibration/sync evidence before paired claims. If valid acquisition
   alignment cannot be established, report a blocker rather than relax the gate.
5. Run fresh public MCP calls on these real files: crest and event contrasts
   should distinguish baseline/processed paths, LUFS matching should separate
   louder from altered dynamics, and deliberate envelope modulation should
   produce time-localized evidence. An unchanged/gain-only control must not
   invent lost punch. Inspect retained sample/envelope evidence independently;
   device parameters or Live meters alone do not pass this step.
6. Remove owned rig, restore set/transport state and retain hashes, exact requests,
   responses, physical alignment evidence and cleanup outcome. Calibration must
   never erase creative processor latency/tails. All Live calls sequential.
7. Independent correctness/scientific/completeness review AND ponytail review;
   fix findings and rerun relevant checks. Reviewer must challenge onset defaults,
   floors, coverage, comparison/matching semantics and actual Live evidence.
   Manager closes only after evidence passes all clauses. No commits/push without
   explicit authorization.

## Current blockers / deployment decisions

No repository blocker to implementing the offline tool. New physical paired
validation is unperformed: the prior qualification rig was removed, and current
runtime/set state has not been probed during planning. Processing attribution
needs actual matched Live acquisitions and measured alignment, not just retained
tonal captures. The deploy worker must establish those conditions and document
unsupported cases before declaring feature 4 complete.
