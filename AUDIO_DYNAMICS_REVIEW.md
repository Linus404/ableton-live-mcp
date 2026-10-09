# Feature 4 — independent scientific/correctness/completeness review

## Verdict (2026-10-09)

**PASS for the bounded dynamics/impact measurement feature and the retained
same-source Live experiments. No unresolved blocking finding.** This is not a
human punch judgment, a recommendation to keep/revert a processor, or a reusable
acquisition qualification certificate.

Reviewed `AUDIO_UNDERSTANDING_GOALS.md`, `AUDIO_DYNAMICS_PLAN.md`,
`src/audio_dynamics.py`, the `src/server.py` public contract,
`tests/test_audio_dynamics.py`, the compact schema regression, and
`AUDIO_DYNAMICS_VALIDATION.md` plus its retained physical artifacts. Review made
no Live calls, production edits, commits or pushes.

## Contract, correctness and bounds

- Offline dispatch imports the analyzer lazily and does not request Live work.
  Exactly one required source and at most one same-source comparison are supported.
  Source names, paths and signal paths are validated; unknown arguments, boolean
  numbers, nonfinite times, duplicate region names, collapsed sample intervals,
  mismatched layouts/rates and incomplete alignment declarations are rejected.
- Paired intervals require caller-declared verified zero-uncertainty alignment;
  source-name offsets are integer frame indices. Equal lengths alone are not
  represented as measured timing proof. Leading/trailing exclusions and the
  common-time basis remain visible.
- Header/decoder metadata agreement and decoded finite samples are checked.
  Limits remain two mono/stereo files, 8–192 kHz, 128 MiB, 600 seconds and
  12 million scalar samples per file; 32 sections, 120 events/windows and a
  pre-decode 96 million reserved sample-work guard bound repeat analysis.
  Contiguous modulation output is additionally capped at 120 eligible runs.
- Crest uses sample peak over mean channel-power RMS, with separate channel
  values. Opposite-polarity stereo is not folded down. DC and original levels
  remain visible. Sample peak is not true peak, crest is not LRA/perceived punch.
- Event energy/RMS/peak are measured directly from samples. Unequal-duration
  energy is not mislabeled level contrast. Attack/body/tail definitions and
  sample-rounded boundaries are explicit; candidate events use disclosed
  10 ms/6 dB/50 ms rules, shared source boundaries, and visible cap/truncation
  evidence rather than an exhaustive onset claim.
- Numerical-floor-limited regional contrasts and paired level ratios are null;
  original sample measurements remain available. Ten-millisecond envelope cells
  are assigned once by start, including crossing cells and the actual final
  partial cell. Summaries expose represented counts and actual cell spans.
- Modulation analyzes complete contiguous eligible runs of at least four
  seconds, never interpolates silent gaps, reports timed runs and unmeasured
  duration, and separately exposes amplitude/variation/frequency resolution.
  The strongest reported run supplies the summary. A periodic envelope does
  not diagnose compressor pumping or objectionable sound.
- The 0.0005 dB modulation reporting floor is explicit. Independent tests retain
  real 2 Hz modulation at 3 dB and 0.01 dB depths and suppress a 0.00001 dB
  numerical-scale depth. Both standard deviation and the selected in-band
  component must clear the declared threshold; this is reporting-resolution
  qualification, not a perceptual audibility threshold.
- Before/after differences retain original levels and mathematical LUFS-match
  predictions, with peak headroom and no file gain application. Unavailable LUFS
  does not become an RMS fallback. Crest and regional contrasts stay gain
  invariant; the level-change envelope is not literal samplewise gain reduction.

## Independent runnable checks

Reviewer oracle retained at
`C:\Users\LINUSV~1\AppData\Local\Temp\opencode\dynamics_review_oracle.py`.
It uses scalar squared-sample sums and explicit equations for regional energy
and crest, and sinusoidal correlations rather than production helpers/FFT for
the modulation-frequency oracle.

- Controlled modulated signal: independently derived crest **9.232887123 dB**,
  attack/body/tail sample energies and dominant **2 Hz** all agree with output.
- Fractional 0.013-second reporting bins represent **100/100** internal cells.
  A separate final **41-frame** partial cell agrees with direct RMS and all
  frames are represented exactly once.
- Five eligible seconds followed by a 10 ms gap and one eligible second report
  the five-second run and **1.01 seconds unmeasured**, rather than discarding
  the valid run or interpolating the gap.
- Two below-floor tones retain original levels but return null paired ratios.
- Final reviewer run:
  `python -m pytest tests/test_audio_dynamics.py tests/test_mcp_server.py::test_tool_list_stays_compact -q --basetemp C:\Users\LINUSV~1\AppData\Local\Temp\opencode\dynamics-review-final-pytest-20261009`
  — **11 passed in 3.36 s**. An earlier default pytest temp-directory permission
  failure was resolved by using the approved explicit basetemp.
- Independently replayed both retained request sequences through fresh
  `python -m server` processes with `PYTHONPATH=src`: initialize, tools/list and
  **eight paired tools/call requests passed**, with no Live mutations.
  Compact tools/list measures **31,003 bytes**; the **32,000-byte** regression
  ceiling remains bounded and accommodates the additional public tool schema.
- `git diff --check` passed. The implementation owner's final full-repository
  run, recorded in the validation artifact, is **569 passed in 100.38 s**;
  the reviewer did not duplicate that full run.

## Retained Live evidence independently inspected

Evidence root:
`C:\Users\Linus V2\.ableton-live-mcp\audio_dynamics_validation\6b612a6edaec4a56a9058913424f3c51`.

Both original source SHA256s and all ten recorded contribution SHA256s agree
with retained evidence. Decoded files are finite and below acquisition clipping.
Percussion files have **594688 frames**; carrier files have **594432 frames**.
Each simultaneous paired take has equal lengths; no between-take alignment is
inferred. The validation document was corrected to state these distinct lengths.

Independent direct marker correlations over nearby integer shifts recover
**zero relative integer lag** at source frames **22050 and 463050** for every
path in both takes. Exact-lag versus adjacent-lag separation is approximately
**20.6–26.6 times**. Marker recovery uses original samples, not normalized or
time-shifted processed music. Long-release marker attenuation remains evidence
of processor recovery, not an alignment correction. Same-source unwarped paths,
stable routing/settings, simultaneous native recordings and two bracketing
markers support this pinned discrete same-clock experiment. They do not
establish future routing applicability or a general fractional-delay certificate.

Retained manifests explicitly remain acquisition-unqualified; public requests
refer to the separate measured marker evidence. Carrier derivatives are exact
float64 frame slices, not gain-adjusted/resampled recordings. Manifest routing
and Live settings are stable, with process-bound PDC-on/reduced-latency-off
observations; unexposed SDK fields are not substituted with zeros.

Independent reads of retained WAVs reproduce crest and first-event attack
energy within the declared precision. Percussion compressor/limiter crest
deltas are **-2.370/-3.049 dB**, with attack/body contrast deltas
**-2.593/-4.690 dB**. The gain-only control preserves crest/contrasts and has
zero matched differences. Original and LUFS-matched evidence demonstrate
altered dynamics separately from simple level changes.

The sustained carrier supplies **800 complete cells over eight seconds**.
An independent non-FFT sinusoidal-correlation oracle reproduces the long-release
paired level-change dominant **2 Hz**. Retained component amplitude is
**2.885 dB** and standard deviation **2.591 dB**. Gain-only correctly has no
reported modulation frequency despite PCM24 residue. Dry percussion modulation
may remain unavailable; the sustained test supplies its distinct coverage gate.
This supports processing-associated cyclical change, not listener-approved
"punch" or a diagnosis from source rhythmic periodicity alone.

Capture cleanup is complete in both manifests. `verify_restore.json` matches
the initial snapshot's original track identities, selected track and transport,
including stopped state, **1.094240395021645 beats**, 174 BPM and recording/
automation flags false. Retained owned-only cleanup and settled restoration
support preservation of the original set.

## Findings resolved during review

1. Boundary-crossing paired envelope cells were silently discarded: fixed by
   once-only start-time assignment and explicit span/count evidence.
2. Any silent cell previously invalidated the entire modulation passage:
   fixed by timed contiguous eligible-run analysis and coverage disclosure.
3. Computed final partial-cell measurements were not returned: fixed with
   explicit frame interval/RMS/peak evidence.
4. Paired ratios ignored regional numerical-floor status: fixed in the shared
   delta function, retaining original levels and nulling unavailable ratios.
5. Physical documentation claimed identical between-take frame counts:
   corrected; within-take paired alignment evidence was unaffected.

All five goal clauses have measurements and actual retained audio evidence.
No fabricated alignment, universal punch score or human keep/revert judgment
is needed for this scoped acceptance.
