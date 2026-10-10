# Audio capability extensions: decision value beyond the eight goals

Research date: 2026-10-10. Read-only investigation; no Live calls, installation,
implementation, or fresh physical validation. Internet research was authorized
by the parent session. This report distinguishes repository evidence from proposed
capabilities and published model claims.

## Recommendation

Prioritize **repeatable real before/after experiments and broader acquisition
qualification**, then **audio-derived pitch/rhythm/structure**. These improve the
agent's ability to attribute changes and answer musical questions. A larger list
of spectral statistics would mostly duplicate existing tools.

Learned timbre embeddings are a useful optional extension for searching and
describing references. Transcription and separation are secondary adapters, not
prerequisites and not replacements for native Live contributions. The original
`AUDIO_UNDERSTANDING_GOALS.md` explicitly requires that no audio AI model be needed.
Preserve the deterministic path and make learned backends opt-in.

### Ranked shortlist

| Priority | Capability | Classification | Decision newly supported | Relative effort |
|---|---|---|---|---|
| 1 | Repeatable intervention experiment with variation/sensitivity evidence | Cross-cutting improvement to the original evidence/comparison requirements | Did this particular change produce the intended measurable effect beyond take variation, and what measurable tradeoff followed? | Medium; acquisition/state restoration dominates |
| 2 | Broader, reusable acquisition/routing/timing qualification | Improvement to existing capture and goals 1, 2, 5, 6 | Which current files and paths actually support in-mix attribution and aligned comparisons? | High physical-validation effort |
| 3 | Audio-derived F0/voicing, rhythmic timing, repetition and structure | New semantic layer; closes part of goals 5 and 8 | Is the bass actually following the intended pitch? Is an onset late relative to an explicit beat grid? Is a motif returning? | Medium for bounded monophonic/event use; high for general mixtures |
| 4 | Qualified render/delivery verification pipeline | Improvement to goal 7 and comparison workflow | Is this exact exported/encoded deliverable compliant and free of newly introduced problems? | Low–medium offline; high if reliable Live export automation is required |
| 5 | Blind human audition and brief-specific preference evidence | New evidence channel; closes subjective portions of multiple goals | Can the listener detect the difference, prefer it for the brief, or recognize the intended part? | Low–medium tooling; listener time required |
| 6 | Learned audio–text/timbre retrieval | Genuinely new optional semantic capability | Which reference/candidate resembles the requested texture, instrument role or timbral description? | Medium integration; substantial model/runtime footprint |
| 7 | Optional transcription; separation only when native sources are unavailable | New optional adapters feeding the semantic layer | What approximate notes exist in an audio-only part/reference? What hypotheses can be formed about unavailable reference sources? | Medium–high; errors need independent evaluation |

Effort is an ordering estimate, not a schedule. Priorities 1–2 are prerequisites
for trustworthy automatic mix interventions, rather than nine more measurement tools.

## What exists, and where the original goals remain partial

Reviewed the original goals, source contracts in `src/audio_*.py`,
`src/in_mix_qualification.py`, calibration code, and the current validation ledgers.
All eight areas have implemented tools and numerical/physical evidence; that does
not mean every perceptual or musical phrase in the original goals is established.

| Original goal | Existing direct evidence | Still an estimate, proxy, or missing judgment |
|---|---|---|
| 1. Loudness/balance | BS.1770 levels; actual qualified native contributions; local/section differences; explicit expectation departures | In-mix prominence is an adapted auditory model, not perceived balance approval. Separately gated part/programme LUFS are not additive loudness shares. |
| 2. Audibility/masking | Roex-filter power competition, attribution, explicit listener-level Model-1-adapted threshold margins | No human audibility probability, recognition or proof that a part is buried; temporal and binaural masking unsupported. |
| 3. Tonal balance | Welch spectra, band power, peaks, centroid/rolloff, explicit brief ranges and independent reference shape | Muddiness/harshness and undesirable resonance remain conditional interpretations; spectra do not prove an EQ correction or listener preference. |
| 4. Dynamics/impact | Explicit event-region RMS/peak/energy, crest, envelopes and modulation; physically aligned same-source experiments | Perceived punch and compressor pumping are not established by crest or modulation alone; after-minus-before envelope is not literal processor gain reduction. |
| 5. Compatibility | Timed activity, spectral competition, resolved partial ratios, cross-source roughness and optional modeled prominence | Source explicitly returns `human_distinguishability_unavailable`. Top spectral partials are not F0, chord/key recognition, or voicedness; roughness is not compatibility approval. |
| 6. Stereo/translation | Frequency-dependent M/S and phase evidence; defined arithmetic mono fold; modeled mono/stereo prominence comparisons | No speaker/headphone/room translation guarantee, binaural hearing model, or measured human mono audibility. |
| 7. Integrity | True-peak estimate, rail/DC/silence/discontinuity observations and caller-defined final-file requirements | Clicks/unintended silence are candidates without intent; codec overshoot and certified true-peak accuracy unsupported. Physical validation inspected retained recording files, not an actual released export. |
| 8. Development | Explicit section-level tonal/dynamics/balance evidence and expectation departures | Temporal density counts RMS-rise candidates; spectral density is six-band entropy. Neither is note count, polyphony, active instrument count or arrangement understanding. |

The most important common gap is the original requirement to assess whether an
edit improves the stated goal, what it compromises, and whether to retain/revert.
The tools intentionally return observations and unavailable musical judgments.
An explicit measurable objective can support a bounded technical decision; a
subjective musical objective still needs user evidence or a clearly labeled
heuristic. A universal quality score would contradict the original specification.

## 1. Repeatable intervention and uncertainty: reuse the existing analyzers

The repository already has paired dynamics analysis, explicit expected section
differences, original-level retention and predicted loudness-matched measurements.
What is missing is a common **experiment record**, not another paired-statistics
tool: identified passage, baseline state, single intended intervention, actual
after render, comparable routing/timing evidence, objective/tolerance, and restore
outcome.

Recommended bounded experiment:

1. Capture/render A, repeat A without the intervention to expose instrument/random
   modulation and acquisition variation, then produce B; counterbalance/repeat if
   stochastic behavior makes order consequential.
2. Preserve actual master outputs for both conditions. Do not reconstruct a
   nonlinear mastered result by multiplying/summing old contribution files.
3. Reuse tonal, dynamics, balance, stereo and integrity reports for declared
   objectives/tradeoffs. Retain original levels and identify any comparison gain.
4. Report effect sizes, repeated-take ranges, missing coverage and sensitivity to
   alignment/listening-level/model assumptions. A model's probability, an FFT-bin
   interval and repeatability variation are three different quantities.
5. Recommend only the bounded technical outcome supported by the objective;
   preserve listener preference as separate evidence.

Acceptance example: an EQ intervention reduces an explicitly identified resonance
over the intended events; repeat-A variation is smaller than the observed change;
programme level and mono loss remain inside caller limits. A simple gain-only B
must not be called improved dynamics. Nonrepeatable synth takes should return
inconclusive rather than acquire a fabricated confidence percentage.

Do not bootstrap highly overlapping analysis windows as independent observations.
Use independent takes or justified block units; a statistical interval from one
stationary passage does not prove generalization to the whole song.

## 2. Expand qualification before attributing more things to sources

`live_audio_capture` raw taps remain approximate, untrimmed end-of-chain captures;
groups/returns/master overlap and pre-mixer recordings cannot establish actual
post-fader shares. Native capture plus `live_audio_assess` is a substantial existing
solution: retained WAVs, experimentally measured timing, exact derivative checks,
stable routing identities and fail-closed certificates. Do not describe alignment
qualification as entirely missing.

Current physical evidence is scoped to stopped transport, PDC enabled, Reduced
Latency When Monitoring disabled, an unprocessed unity Main path, supported native
PCM24/PCM32/float formats and pinned regular/group/return profiles. Windows English
process-bound settings evidence is part of that scope. Calibration removal does
not qualify a future changed set. Feedback routing, frozen raw-capture targets,
unsupported selection and ambiguous timing need explicit unavailable outcomes.

Useful extensions are experimentally admitted device/route profiles, portable
settings evidence, stable assessment of long passages within resource bounds,
and separately qualified pre/post-master capture. A nonlinear master does not
have an additive stem decomposition: preserve upstream contribution evidence and
separate mastered programme evidence instead of relaxing sum-proof tolerances.

Acceptance should cover real latency-bearing processing, creative return tails,
dynamic routing/profile changes, automation, negative/ambiguous alignment cases,
cleanup after failure and certificate invalidation. Repeatable sync markers and
independent reference measurements should remain physical evidence, not status
flags. Qualification is an existing mechanism to expand, not a reason to replace
it with cross-correlation on arbitrary music.

## 3. Pitch, rhythm and musical semantics without requiring ML

Start with isolated audio-capable sources already obtainable from Live. Monophonic
F0 plus voiced/unvoiced evidence addresses a real blind spot: the current
compatibility analyzer retains top 12 FFT peaks and three cross-source peak pairs,
not a time-varying fundamental. **pYIN** supplies F0, voicing flags and voiced-frame
probability using YIN candidates and Viterbi decoding [S1]. It needs declared pitch
bounds and validation on the actual source class; its probability is not a globally
calibrated musical correctness confidence. Octave ambiguity, noisy attacks,
inharmonic/percussive sounds and polyphony require unsupported/uncertain results.

Add source-onset times against an explicit tempo map/beat grid before trying general
beat inference. Live MIDI and Arrangement metadata can provide intended events,
but sound onsets include synthesis envelopes, processing and delay: report
intended-versus-measured timing, not MIDI as proof of the audible event.
Beat-synchronous chroma and recurrence can describe repeated pitch-class textures
and candidate structural changes [S2, S3]. They do not autonomously name a chorus,
recognize every chord, or determine harmonic appropriateness.

Acceptance: missing fundamental and octave distractors, vibrato/glides, tuned and
inharmonic bass, noise/transients, octave-doubled sources, swing and tempo changes,
repeated motifs with changed instrumentation. Report cents/timing errors and
coverage against authored or annotated truth. This layer closes specific portions
of goals 5/8 while adding pitch-following and motif/structure queries beyond them.

## 4. Verify actual deliverables and translation scenarios

Goal 7 already provides final-WAV metadata/loudness/peak/DC checks. The extension is
artifact acquisition and regression: hash the exact exported master; retain export
settings; compare expected duration/start/end/tails; analyze the final file rather
than the pre-export recording; optionally encode/decode an explicitly specified
codec and measure the decoded artifact. Codec priming/padding and delay need a
common-time mapping before paired local comparison.

Use ITU BS.1770 as the measurement basis [S4]. FFmpeg's `ebur128` scanner can be an
independent implementation check with true-peak mode enabled [S5], not certified
compliance by agreement alone. Its `loudnorm` filter modifies audio and should not
be mistaken for an analysis-only operation. Add sample-rate/codec-specific fixtures
and independently established meter tolerances, preserving existing estimator
edge/tail limits. Broadening to full-song/encoded-file processing may require
streaming rather than weakening current byte/sample-work bounds.

Speaker/phone/headphone transfer functions or room responses can support explicit
translation *scenarios*, not a guarantee of real-world translation. These improve
goal 6; they are not an independent music-quality model.

## 5. Human feedback where it supplies genuinely missing evidence

A compact audition record can capture user-selected excerpts, anonymized/counter-
balanced A/B order, applied comparison gain, listening conditions and the exact
question. Separate **difference detection**, **part recognition** and **preference
for a stated brief**: successful discrimination does not establish preference;
preference does not prove a part is intelligible.

ITU BS.1116 addresses small impairments and BS.1534/MUSHRA intermediate audio
quality [S6, S7]. Their controlled-testing principles are useful, but a casual
producer A/B is not standards-conformant just because it is blinded. MUSHRA anchors
and impairment scores are not universal creative-mixing targets. A listener
recognition task can directly test a disputed masking hypothesis more usefully
than asking only whether the mix sounds good.

This is an optional evidence channel, not a mandatory approval dialog for every
measurement. It is the strongest addition for the currently unsupported human
audibility/compatibility/punch/translation/preferences claims. Retain unresolved
or contradictory feedback instead of training an instant universal score from it.

## 6. Optional learned timbre/semantic retrieval

**CLAP** maps audio and natural-language descriptions into a shared embedding space
for retrieval/zero-shot classification [S8]. Appropriate use: shortlist references
or patches for a request such as metallic sustained texture, and produce ranked
candidate descriptors for short identified excerpts. This adds semantic context
that centroid, band energy and peak ratios cannot provide.

Keep model/checkpoint identity, preprocessing, excerpt boundaries and competing
descriptions. Embedding similarity is not a probability, an equalization target,
evidence of source identity, perceptual equivalence or mix quality. Small mastering
edits may be below the representation's intended semantic granularity; evaluate
that before using it for before/after recommendations.

The official package uses PyTorch and checkpoint downloads and documents 48 kHz
input for its array API. Repository code is CC0 [S9]; checkpoint/dataset terms must
be checked for the selected distribution rather than inferred from the code
license. Benchmark target-device CPU/GPU latency and memory on bounded excerpts;
do not attach a large model to normal offline measurements by default.

Acceptance: curated timbral contrast and retrieval relevance, nuisance variation
from gain/codec/excerpt boundaries, out-of-domain sounds, misleading descriptions
and near-identical processing edits. Compare against a simple existing-feature
baseline. Only add the model if it answers useful questions that baseline cannot.

## 7. Transcription and separation: useful but lower priority here

**Basic Pitch** offers lightweight polyphonic audio-to-MIDI with pitch bends,
Apache-2.0 licensing and multiple inference formats [S10]. Its authors explicitly
state that it works best on one instrument at a time. Apply it to isolated parts,
retain model activations and uncertain events, and compare note/timing outputs to
known examples before interpreting density, harmony or playing mistakes. It does
not replace audible F0 validation with generated MIDI truth.

**Demucs** provides learned music source separation [S11]. Use it for audio-only
external references or unavailable native parts, not an Ableton set whose native
tracks are accessible. Separated estimates contain leakage/artifacts; they are
not the original mix stems and cannot inherit native routing/alignment provenance
or independently qualify causal masking/source-attribution claims. Preserve a
distinct estimated-source status even if a residual or reconstructed sum is small.

The official Demucs repository says it is no longer maintained; code is MIT [S12]
and inference uses PyTorch. CPU inference is available, while documented GPU
memory needs depend on model/segment settings. Benchmark the chosen maintained
implementation/checkpoint rather than treating published hardware timings as a
local guarantee. Basic Pitch is the more practical first learned adapter here;
separation has lower value when Live already provides the actual sources.

Avoid adopting a large MIR stack solely to obtain one feature. For example,
madmom distinguishes BSD code from generally CC BY-NC-SA model/data files [S13];
Essentia has AGPL/proprietary licensing and describes its distributed models as
CC BY-NC-ND/proprietary [S14]. Package license, weights license and deployment
requirements need separate checks. These are candidate research toolkits, not
recommended new dependencies for the current deterministic core.

## What not to add first

- Another generic score for muddiness, punch, masking, compatibility or musical
  quality built by relabeling the current proxies.
- A new unqualified capture path that bypasses existing physical qualification.
- Separation of native Live tracks merely to rediscover already accessible sources.
- Learned embeddings as a replacement for final-file metering or same-source A/B.
- Objective codec-impairment models as creative quality judges. ITU BS.1387/PEAQ
  concerns objective perceived audio quality in its defined scope [S15], not
  whether a composition, timbre choice or mix meets the user's artistic brief.

## Evidence sources

Repository evidence: `AUDIO_UNDERSTANDING_GOALS.md`,
`AUDIO_FEATURES_VALIDATION.md`, `AUDIO_DYNAMICS_VALIDATION.md`,
`AUDIO_REMAINING_FEATURES_VALIDATION.md`, `AUDIO_REMAINING_FEATURES_PLAN.md`,
`src/audio_analysis.py`, `src/audio_balance.py`, `src/audio_masking.py`,
`src/audio_assessment.py`, `src/audio_tonal.py`, `src/audio_dynamics.py`,
`src/audio_compatibility.py`, `src/audio_stereo.py`, `src/audio_integrity.py`,
`src/audio_development.py`, `src/audio_capture.py`, `src/in_mix_calibration.py`,
`src/in_mix_qualification.py`. Historical validation is scoped evidence, not a
fresh claim that the current open set is qualified.

- **S1:** librosa pYIN docs, including the Mauch & Dixon 2014 paper reference:
  https://librosa.org/doc/0.11.0/generated/librosa.pyin.html
- **S2:** Chroma CQT documentation:
  https://librosa.org/doc/0.11.0/generated/librosa.feature.chroma_cqt.html
- **S3:** Recurrence matrix documentation:
  https://librosa.org/doc/0.11.0/generated/librosa.segment.recurrence_matrix.html
- **S4:** ITU-R BS.1770, programme loudness and true-peak measurement:
  https://www.itu.int/rec/R-REC-BS.1770
- **S5:** FFmpeg filter documentation, `ebur128` and `loudnorm`:
  https://ffmpeg.org/ffmpeg-filters.html#ebur128-1
  https://ffmpeg.org/ffmpeg-filters.html#loudnorm
- **S6:** ITU-R BS.1116, subjective assessment of small impairments:
  https://www.itu.int/rec/R-REC-BS.1116
- **S7:** ITU-R BS.1534, intermediate-quality subjective assessment:
  https://www.itu.int/rec/R-REC-BS.1534
- **S8:** CLAP official repository and paper:
  https://github.com/LAION-AI/CLAP
  https://arxiv.org/abs/2211.06687
- **S9:** CLAP repository license:
  https://raw.githubusercontent.com/LAION-AI/CLAP/main/LICENSE
- **S10:** Basic Pitch official documentation and license statement:
  https://github.com/spotify/basic-pitch
  https://raw.githubusercontent.com/spotify/basic-pitch/main/README.md
- **S11:** Demucs official README and hybrid-separation paper (the latter describes
  the earlier hybrid architecture, not a benchmark guarantee for every checkpoint):
  https://raw.githubusercontent.com/facebookresearch/demucs/main/README.md
  https://arxiv.org/abs/2111.03600
- **S12:** Demucs repository license:
  https://raw.githubusercontent.com/facebookresearch/demucs/main/LICENSE
- **S13:** madmom official licensing/model information:
  https://github.com/CPJKU/madmom
- **S14:** Essentia licensing information, including distinct model licensing:
  https://essentia.upf.edu/licensing_information.html
- **S15:** ITU-R BS.1387, objective perceived-audio-quality measurement:
  https://www.itu.int/rec/R-REC-BS.1387

Official docs/repositories and standard landing pages were fetched during this
research. Standard titles/scopes are used to motivate methodology; no standards
conformance, external model benchmark reproduction, or fresh listening result is
claimed. Initial failed URLs were replaced by working versioned documentation or
raw official README links.
