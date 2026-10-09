# Feature 2: audibility and masking evidence

`live_audio_masking` provides offline time/frequency-localized measured competition
and optional Model-1-adapted masking thresholds for a target and 1–8 competing WAV contributions. It uses the existing
`audio-analysis` extra and never calls Live. See README.md and AGENTS.md for the
input contract and examples.

## Evidence contract

- Sources must be declared disjoint contributions at actual in-mix levels, with
  explicit signal-path provenance and verified zero-uncertainty alignment source.
- Verification is caller-declared, not independently established by the tool.
  Matching file lengths alone are not alignment evidence.
- Mono/stereo layouts and sample rates must match. Optional per-source file frame
  offsets identify common time zero; analysis uses the shortest common remaining
  interval. Without offsets, frame counts must also match.
- Raw approximate multi-track taps are uncalibrated and pre-mixer; they do not
  satisfy this contract. Source/group/master overlap and duplicated shared
  contributions must not be declared disjoint.

## Measurements and estimate

Hann-window-corrected one-sided FFT powers are integrated through symmetric
roex auditory filters. Filter centers are one ERB-rate step apart from 50 Hz to
below the lower of 16 kHz and Nyquist. ERB bandwidths use the Glasberg–Moore
formula; the roex filter parameter is `p = 4 * center_frequency / ERB`.

Stereo is processed by averaging **powers**, avoiding phase cancellation from
waveform downmix. Competitor powers are added incoherently; the tool does not
simulate waveform mixing, correlation, binaural unmasking, or nonlinear buses.

Measured evidence includes the three strongest target-filter powers (dBFS),
target-to-competitor ratios (dB), and each competitor's power and attribution
share. The separate `competition_fraction` proxy is the excitation-weighted
fraction of active target filters where summed competitor excitation is at least
as strong as target excitation. Merged intervals select adjacent windows whose
proxy is at least 0.5. This rule is descriptive, not a calibrated masking or
audibility threshold. There is no claim that a part is inaudible or musically bad.

Optional source `gain_db` values form explicit counterfactual scenarios without
changing Live or normalizing audio. Displayed powers/ratios retain `original_*`
evidence alongside adjusted measurements.

Windows are contiguous 100–1000 ms, with at most 120 windows. Oversized requests
are rejected rather than sparsely sampled; final tails shorter than 100 ms are
explicitly unmeasured. Numerical floors and transient limitations are reported.
File/sample/duration/computation budgets are enforced before large analysis
allocations. Cached kernels avoid repeating filter construction every window.

The report explicitly provides actual filter-center count, spacing and frequency
range. Out-of-center-range frequencies may excite filter tails; they are not
uniformly assessed, and reported centers are not inferred source-frequency peaks.
`inactive_target_windows` counts modeled/windowed filter inactivity rather than
literal source silence. A Hann endpoint can suppress a real impulse completely.

## Scientific references

- Glasberg & Moore (1990), *Derivation of auditory filter shapes from notched-noise
  data*, Hearing Research 47:103–138, DOI: `10.1016/0378-5955(90)90170-T`.
- Patterson et al. (1982), *The deterioration of hearing with age: Frequency
  selectivity, the critical ratio, the audiogram, and speech threshold*, JASA
  72:1788–1803, DOI: `10.1121/1.388652`.

Auditory-filter bandwidths/shapes ground the excitation measurements; they do not
validate the competition proxy as a probability of inaudibility. With explicit
`listening_condition: {kind: "calibrated"|"assumed", db_spl_at_0_dbfs_rms, source}`,
the additional MPEG-1 Psychoacoustic Model 1 adaptation distinguishes tonal/noise
maskers, applies Bark-domain spreading and absolute hearing threshold, and reports
localized threshold margins and likely contributor attribution. Preserve measured
listener calibration versus assumed monitor level. This is a research-grounded
spectral model adaptation, not an ISO conformance claim, standardized partial
loudness, audibility probability, or human listening approval. Normal-hearing
assumptions, incoherent powers, transient windows, no binaural/temporal masking,
and no shared nonlinear processing remain explicit limits.

`live_audio_balance` runs the model per contribution with aligned loudness facts;
`live_audio_assess` accepts only a complete qualified in-mix manifest and preserves
capture proof. Model implementation alone does not qualify the Live capture path.
Acceptance requires the physical experiments and independent checks in
`AUDIO_FEATURES_ACCEPTANCE.md`; these remain separate from the historical proxy
validation below.

## Final first-two-goal acceptance

The full qualified native acquisition-to-assessment workflow passed independent
acceptance review on 2026-10-09. Actual explicit and default MCP assessments
retained all sources, assumptions and original evidence; B's +6 dB counterfactual
changed modeled all-active-components-below-threshold intervals from 1–11 s to
1–6 s with Group/F-return attribution, while the programme remained original.
All parts had complete window coverage. The listening reference was explicitly
assumed, not measured calibration, and these outcomes are not human approval.
See `AUDIO_FEATURES_VALIDATION.md` for certificates, retained physical evidence,
465 final tests, independent review, restored original state and exact supported
conditions. Future changed profiles need applicable recalibration.

## Historical excitation-proxy validation

2026-10-08, Windows, checkout virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp="C:\Users\LINUSV~1\AppData\Local\Temp\opencode\pytest-masking-full" -q
```

Initial integration result: **394 passed**. Focused analysis checks cover
same-band versus separated-frequency competition, gain direction and original
evidence, different-time competitors, silence, multiple-source attribution,
antiphase stereo, explicit offsets, partial tails, malformed audio, provenance
refusals, resource bounds, and no-Live MCP dispatch.

An additional check exercised the real MCP handler with one-second float WAVs
generated on the same 48 kHz sample grid. The target was a 1 kHz sine at amplitude
0.01; its competitor had amplitude 0.1 and occurred only during 0.4–0.8 seconds.

| Scenario | Central-window proxy | Target/competitor ratio | Selected intervals |
| --- | ---: | ---: | --- |
| Competitor at 1 kHz | 1.0 | -20.000 dB | 0.4–0.8 s |
| Competitor at 8 kHz | 0.0 | null (below floor in strongest target filter) | none |
| 1 kHz competitor reduced 40 dB | 0.0 | +20.000 dB | none |

Evidence files: `C:\Users\LINUSV~1\AppData\Local\Temp\opencode\masking-validation`
(source WAVs and three full JSON reports). This demonstrates signal-driven
competition localization and counterfactual behavior, not human listening
approval. No Live state was changed for this offline feature validation.

Independent review and any resolutions are recorded in `AUDIO_MASKING_REVIEW.md`.

Historical proxy outcome: both independent reporting findings were fixed, independently
rechecked (**25 focused tests passed**), and covered by regression tests. The full
suite passed **396 tests** after those fixes; the known-audio MCP scenarios above
were repeated successfully and `git diff --check` passed. Ponytail review found
no actionable over-engineering. The prior loudness feature is committed as
`b481798` (`Add offline loudness and balance analysis`).
