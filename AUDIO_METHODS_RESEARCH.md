# Audio methods: standards, useful estimators, and next improvements

Research date: **2026-10-10**. Read-only method review; no Live experiments or implementation changes were performed for this report.

## Bottom line

The eight implemented solutions are a **credible, deliberately bounded evidence toolkit**, but calling them collectively “the best available” would overstate the evidence. Loudness has an accepted measurement standard; most other requested qualities have several task-dependent estimators and no universal best method. The current code correctly distinguishes many measured facts from predictions and musical judgments.

The largest gap is between **spectral prominence estimates and actually predicting whether a listener can follow an instrument**. The MPEG-1-adapted model is a useful research-grounded diagnostic, not a standardized partial-loudness model, source-recognition model, or demonstrated instrument-audibility detector. The next most material gaps are sparse/transient coverage, perceptual onset detection, and true-peak conformance evidence. Replacing all modules or adding a large audio-AI stack is not justified by these findings.

One genuinely useful addition beyond the listed eight goals is **automatic passage navigation**: repetition/self-similarity and structural-change candidates that direct the agent to comparable musical passages. This improves where the existing tools look, without inventing musical quality scores.

## What was inspected

- `AUDIO_UNDERSTANDING_GOALS.md`, `AUDIO_REMAINING_FEATURES_PLAN.md`, and repository `AGENTS.md`.
- Actual implementations in `src/audio_analysis.py`, `audio_masking.py`, `audio_balance.py`, `audio_tonal.py`, `audio_dynamics.py`, `audio_compatibility.py`, `audio_stereo.py`, `audio_integrity.py`, and `audio_development.py`.
- The implemented method descriptions, constants, limits, source/alignment contracts, and historical validation documentation. Existing test evidence is useful but is not automatically an EBU/ITU conformance suite or perceptual validation study.

The verdicts below concern the implemented algorithms and their claims. They do not independently requalify a current Live capture session or establish comparative performance on a musical listening dataset.

## Feature-by-feature verdict

### 1. Loudness and balance

**Implemented:** BS.1770-style DeMan K-weighting through pyloudnorm, gated integrated LUFS; ungated 400 ms and 3 s measurements; RMS and sample peak; aligned programme/part differences; explicit section expectations; isolated hypothetical LUFS matching and headroom. In-mix assessment additionally requires acquisition qualification and retained contribution provenance.

**Verdict:** The correct standard-based foundation for programme loudness. “Best available” is defensible only in the narrow sense that BS.1770 is the accepted interoperable measurement basis, not that a particular library is uniquely best or that LUFS measures instrument prominence. R128 specifies a broadcast normalization practice, not a universal music-mastering target [1–4].

**Material improvements:**

- Validate against the EBU minimum-requirements signals and tolerances, including time behavior, not just sine checks or agreement with one other implementation [2]. Agreement with FFmpeg is useful independent evidence but not a substitute for the relevant standards vectors.
- Distinguish sampled momentary/short-term maxima from exhaustive maxima: the output cap and sampling step can miss intervening level changes.
- Optional **Loudness Range (LRA)** would be a small, standard-based addition for sufficiently long passages [3]. It needs its own 3 s sampling, absolute/relative gating, and percentile rules; crest or the largest short-term jump is not LRA. It should remain unavailable or explicitly weak for very short excerpts, not become another compulsory score.

**Keep:** Independently gated integrated part/programme differences are descriptive, not additive energy fractions. Changing a contribution through nonlinear bus/master processing requires a fresh actual render; scaling an isolated file cannot predict the resulting programme.

### 2. Audibility and masking

**Implemented:** Symmetric roex auditory-filter powers and competitor ratios; a descriptive competition-fraction interval threshold of 0.5; with explicit listening conditions, a 1024-point FFT adaptation of MPEG Model 1 using tonal/noise maskers, Bark spreading, quiet thresholds and threshold-excess summaries. Competitor thresholds sum incoherently, and channels are evaluated independently.

**Verdict:** Useful **competition and simultaneous spectral-prominence diagnostics**, not the best available model for the actual goal “when a part is buried.” The 0.5 rule is a report-selection heuristic, not a experimentally validated audibility boundary. MPEG Model 1 originates in perceptual coding; copying its spreading equations does not establish instrument distinguishability [5].

**Why the distinction matters:**

- The prominence fraction denominator is retained target components above quiet threshold, not all target energy. A high fraction can coexist with substantial omitted/unsupported content.
- The current `_model_power` averages spectra over analysis windows before classification; short attacks and changing masker relationships can be diluted.
- Fixed 1024-point FFT and bin-index tonal neighborhoods vary substantially in physical Hz/time resolution across the supported sample rates. At 48 kHz one bin is about 46.9 Hz; at 192 kHz it is 187.5 Hz. The code exposes adaptation limits, but sample-rate-equivalence validation and physical-frequency neighborhood design are high-value next checks.
- An absolute SPL mapping is necessary for hearing-threshold predictions but does not supply listener hearing status, room/headphone transfer, spatial unmasking, attention, informational masking, or temporal masking.

**Material improvements:** First characterize the present estimator on controlled target/background mixtures, transient cases, sample-rate changes and listening-level sensitivity. If reliable prominence judgments are important, add a **time-varying partial-loudness research model** as an optional validated estimator, rather than renaming threshold-excess power “partial loudness.” Cambridge-model authors describe separate target/background excitation, nonlinear loudness transformation and temporal integration explicitly [6]. Their review also describes binaural-model development.

**Standards caution:** ISO 532-1/-2 concern loudness calculation methods; citing them alone does not certify this code's masking output, arbitrary stem audibility, or time-varying partial loudness. This research could not retrieve the ISO normative texts and makes no conformance claim. Even a more complete model still requires perceptual validation for musical-source audibility.

### 3. Tonal balance

**Implemented:** Channel-mean Welch power with 250 ms Hann windows and 50% overlap, approximately 4 Hz FFT-bin spacing; power integration by FFT-bin-cell overlap; broad/octave bands, centroid, rolloff, bounded local peaks, independent-reference shape comparisons and optional caller-defined expectations.

**Verdict:** A strong, transparent method for descriptive spectral energy. There is no universal ideal spectral curve and no universally best single-resolution analysis. Existing gain-invariance, Nyquist coverage, DC exclusion from tonal normalization, and explicit original levels are important safeguards.

**Material improvements:**

- Add a complementary short-window transient view only where the agent needs onset brightness; retain the existing long-window energy view for low-frequency discrimination. Longer frequency resolution and shorter time resolution trade off; changing the single global FFT length cannot optimize both.
- Rank local peaks by persistence, prominence relative to a local baseline, and agreement with the user's reference/brief before surfacing them as suspected resonances. A harmonic peak itself is not a fault.
- Preserve omitted Welch-tail and sub-250 ms interval evidence. A completed computation is not complete passage coverage; zero-padding a short interval cannot manufacture real spectral resolution.

**Keep:** Partially unsupported high bands at low sample rates must not be described as missing treble. Reference shape deltas require compatible covered normalization ranges. Centroid and unweighted power are not perceived brightness or harshness verdicts.

### 4. Dynamics and impact

**Implemented:** Original RMS/peak/crest, explicit or automatically proposed attack/body/tail regions, paired after-minus-before and predicted LUFS-matched measurements, 10 ms envelope cells, and bounded 0.5–10 Hz envelope modulation. Automatic onset candidates use a >=6 dB RMS rise with 50 ms refractory time and default 20/100/300 ms regions.

**Verdict:** Good physically interpretable comparisons when event boundaries and alignment are known; the automatic onset detector is a deliberately simple level-rise heuristic. It is not the best general detector for legato notes, overlapping instruments, soft attacks, or new notes without a large overall amplitude increase.

**Material improvements:** Add a complementary spectral-flux or complex-domain onset candidate detector, with local adaptive peak picking and an explicit confidence/coverage report. Authoritative MIR teaching and implementation resources describe these alternatives and their limitations [7–8]. Prefer caller-defined event boundaries when known; do not replace them with an automatic detector.

**Keep:** Envelope periodicity can reflect tempo, tremolo, ducking, or note patterns; it does not prove unwanted compressor pumping. Crest is not LRA or perceived punch. Short isolated hits legitimately lack four seconds of eligible modulation evidence. Comparing compressed audio requires unchanged source/routing plus verified timing; the difference envelope is not literal gain reduction through a nonlinear processor.

### 5. Compatibility between sounds

**Implemented:** Existing masking/competition evidence and timed coactivity; up to 12 resolved Hann FFT peaks above a relative -40 dB power cutoff; top-three cross-source amplitude-product frequency-ratio pairs with bounded small-integer approximations; a normalized cross-source Sethares-like roughness kernel.

**Verdict:** Appropriate exploratory **resolved-partial relationships and roughness proxies**, but substantially narrower than harmonic compatibility, pitch/chord recognition, or whether the listener can distinguish both parts. The author’s work supports the dependence of sensory dissonance on spectrum/timbre and frequency relationships, not universal musical goodness [9]. The code's normalization and peak selection make this a custom dimensionless index, not a calibrated roughness quantity.

**Material improvements:**

- Show how much resolved spectral power/peak inventory is retained when interpreting roughness. Twelve peaks can omit interactions in dense, noisy or broadband timbres.
- Add sub-bin frequency estimation and multi-frame stability checks before treating a ratio departure as meaningful. At the 100 ms lower window bound, roughly 10 Hz bin spacing is especially coarse for low partials; disclose resolution rather than claiming accurate tuning.
- Fundamental/pitch tracking is justified only when the agent really needs note/harmonic structure. Resolved peaks are not fundamentals; a nearest integer ratio among selected peaks is not a chord estimate.
- If roughness becomes a decision-driving feature, compare the current index with a validated temporal roughness model and listening data. Do not infer that a newer or larger model will universally outperform it on all music.

### 6. Stereo and translation

**Implemented:** Broadband and frequency-dependent mid/side power, correlation/phase observations, a defined arithmetic mono fold, and paired stereo/mono modeled prominence using actual disjoint in-mix contributions when supplied.

**Verdict:** Solid deterministic analysis of signal geometry and arithmetic mono cancellation. There is no single standardized width score that captures perceived spaciousness or every playback system. Important-part prominence inherits the limitations of the shared masking model.

**Material improvements:** Distinguish energetic cancellation from psychoacoustic spatial separation. If spatial audibility is required, introduce an explicitly qualified binaural listening model with a defined listening geometry; two independent channel thresholds are not binaural unmasking. Different mono/downmix conventions and speaker/headphone conditions should remain explicit caller conditions, not hidden assumptions.

**Keep:** Broadband positive correlation does not rule out narrow-band cancellation. Mid/side energy is exact for the declared transform but is not source attribution or perceived location. A mono fold must retain its gain convention to make comparisons meaningful.

### 7. Technical integrity

**Implemented:** Sample peaks; fourfold `scipy.signal.resample_poly` interpolation using an 81-tap Kaiser-beta-5 FIR and zero-extension outside the file; sample rail/unity observations, channel mean DC, thresholded silence and adjacent-sample discontinuity candidates, explicit final-file delivery requirements.

**Verdict:** Good diagnostic evidence, but **not a demonstrated BS.1770-conformant true-peak meter**. Fourfold oversampling alone is insufficient: interpolation response, sampling-grid under-read and required tolerances also matter [1–2]. The code correctly labels its result as a finite-FIR estimate, including uncertainty near Nyquist and boundaries.

**Material improvements:**

- Highest priority for delivery use: implement or reuse a standards-conformant true-peak path and run published conformance vectors/tolerances. Report estimator uncertainty for borderline limits; a noncertified estimate being below a limit cannot guarantee actual compliance.
- Add adaptive discontinuity candidates relative to local level and neighboring waveform/envelope behavior. An absolute adjacent-sample jump can flag legitimate bright material and miss low-level clicks. Preserve “candidate,” not “unintended edit” or “proven clipping.”
- Optional codec encode/decode preview is valuable only when delivery actually targets a specified codec/settings; PCM true peak alone does not predict every codec overshoot.

**Keep:** PCM rail hits and finite float samples above unity are observations, not proof of destructive clipping. File mean can include slow musical energy and is not automatically a DC defect. The identified final render is the appropriate delivery evidence; a tap upstream of the final processing is not.

### 8. Musical development

**Implemented:** Caller-named sections, adjacent section contrasts, reused loudness/tonal/dynamics evidence, optional actual-part balance, onset-candidate rate and effective occupied-band count as density proxies; departures require explicit expectations.

**Verdict:** Honest and useful section-comparison evidence. It does not yet infer musical form, arrangement density, instrument changes, or whether a build/drop works. No universal best descriptor exists for these goals. The onset-density proxy inherits the simple detector's biases, and spectral entropy measures distribution of band energy rather than polyphony.

**Material improvements:** First improve onset candidates and passage coverage upstream. Then add automatic structural-change/repetition suggestions as navigation aids [10–11]. Keep the user's named sections and intended contrasts authoritative; inferred section boundaries should be suggestions with timestamps, not automatically labeled verse/chorus or quality errors.

## Cross-cutting limits that matter more than a model name

1. **Evidence provenance precedes perception.** The repository's qualified native capture is much stronger than raw uncalibrated taps for in-mix attribution. Stable selection/routing/device profiles, physical timing experiments, finalized WAV identity and cleanup are substantive safeguards. Offline `alignment.verified` and provenance declarations in general tools remain caller evidence; copying flags does not recreate physical calibration.
2. **Scope certificates to their actual experiments.** Removing a rig or changing a routed/latent/processed path cannot transfer its qualification to future captures. Equal frame counts, an interleaved derivative and a shared recording clock alone do not prove timing or linear decomposition. Nonlinear shared bus processing prevents naive contribution summation or hypothetical master reconstruction.
3. **Incomplete coverage is not negative evidence.** The 120-window/candidate bounds, Hann endpoint suppression, excluded short tails and numerical floors can hide real events. “No measured event” differs from “no event.” Sparse summaries must not be presented as exhaustive maxima or complete frequency/time coverage.
4. **Thresholds have different roles.** BS.1770 gating has standard-defined purposes. Competition >=0.5, onset rise >=6 dB, top-12 peaks, relative -40 dB peak selection, and discontinuity/silence thresholds are operational heuristics. Expose sensitivity and musical scope rather than presenting them as hearing or quality thresholds.
5. **DC and Nyquist are not footnotes.** Original level/integrity metrics retain DC; tonal normalization intentionally excludes DC/out-of-band energy. Reference comparisons need compatible normalization coverage. Unsupported bands and numerical-floor upper bounds must retain their distinct meanings.
6. **No unsupported comparative-performance claim.** Standards, author papers and implementation tests justify methods and limitations. They do not prove this particular implementation outperforms alternatives on the user's material. That requires relevant test signals, comparison implementations, and where perceptual claims matter, listener evidence.

## Prioritized upgrades: smallest changes with the greatest practical value

| Priority | Improvement | Why it pays off | Required evidence before stronger claims |
|---|---|---|---|
| 1 | EBU loudness/true-peak conformance vectors and explicit estimator uncertainty | Strengthens measurement/delivery decisions without changing the public architecture | Published responses/tolerances; adversarial near-Nyquist and boundary signals |
| 2 | Event-aware, multiresolution coverage plus spectral/complex onset candidates | Improves dynamics, transient tonality, compatibility and development together | Annotated varied attacks/overlaps, sample-rate cases, false-positive/negative and omitted-coverage reporting |
| 3 | Validate masking on controlled target/background cases; optional time-varying partial loudness if needed | Addresses the largest gap between current metrics and “part buried” | Listening-level conditions, separate actual inputs, reference-model checks, relevant perceptual data |
| 4 | Compact uncertainty/sensitivity evidence around heuristic thresholds | Prevents brittle agent decisions near arbitrary cutoffs | Same passage under reasonable window/threshold/listening-level variants |
| 5 | Automatic repetition/novelty passage navigator | Adds useful analysis capability outside the eight lists and reduces wrong-passage comparisons | Known repeated/changed passages; timing/feature-scale limitations; no semantic section-label promise |
| 6 | Optional LRA for suitable long passages; pitch tracking only for explicit harmonic tasks | Fills specific standard/semantic gaps without making all analyses heavier | EBU LRA requirements; pitch-task-specific ground truth and explicit polyphonic limits |

Do not prioritize a universal mix-quality scalar, source separation from the master when qualified stems are available, a decorative “AI ear,” or an architecture rewrite. None supplies missing ground truth. A listening/A-B evidence workflow is valuable for final approval; ITU subjective-testing standards describe controlled assessments of audio-system impairments, not an automatic music-composition judge [12–14].

## Sources and exactly what they support

All retrieval attempts below were made on **2026-10-10**. Primary standard PDFs were downloaded and text-extracted in an analysis subprocess; their binary bodies were not treated as readable text. EBU publication landing pages returned HTTP 403, but the listed PDF URLs were accessible. ISO normative text was not retrieved.

1. **ITU-R BS.1770-5 (2023), Algorithms to measure audio programme loudness and true-peak audio level.** [Recommendation](https://www.itu.int/rec/R-REC-BS.1770-5-202311-I/en); [English PDF](https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1770-5-202311-I!!PDF-E.pdf). Retrieved. Supports K-weighting, channel weighting, gated programme loudness and true-peak algorithms/oversampling considerations. Does not standardize mix balance, musical punch or source audibility.
2. **EBU Tech 3341, Loudness Metering: EBU Mode.** [PDF](https://tech.ebu.ch/docs/tech/tech3341.pdf). Retrieved/text-extracted. Supports momentary/short-term/integrated behavior and minimum-requirements meter tests/tolerances. Does not make any library conformant merely because it uses 400 ms/3 s windows.
3. **EBU Tech 3342, Loudness Range.** [PDF](https://tech.ebu.ch/docs/tech/tech3342.pdf). Retrieved/text-extracted. Supports the 3 s short-term distribution, gating and 10th-to-95th percentile LRA calculation, minimum requirements and sampling/overlap conditions. Not equivalent to crest or maximum local loudness change.
4. **EBU R128 and Tech 3343.** [R128 PDF](https://tech.ebu.ch/docs/r/r128.pdf); [Tech 3343 production guidelines PDF](https://tech.ebu.ch/docs/tech/tech3343.pdf). Retrieved/text-extracted. Support the broadcast loudness-normalization practice and practical programme-production guidance. The -23 LUFS R128 target is not a mandatory target for all music distribution or individual stems.
5. **TwoLAME `psycho_1.c`, primary implementation of an MPEG Model-1 psychoacoustic path.** [Source](https://raw.githubusercontent.com/njh/twolame/main/libtwolame/psycho_1.c). Retrieved. Supports tracing the inherited tonal/noise masking and spreading calculations to an actual encoder implementation. Not an ISO normative copy, listening validation of this repository's adaptation, or partial-loudness standard.
6. **B. C. J. Moore (2014), Development and Current Status of the “Cambridge” Loudness Models.** [Open full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC4227665/). Retrieved. Author's research review describes specific/partial loudness, threshold predictions, time-varying target/background processing and binaural extensions; links the original model papers. Supports the substantive differences between those models and threshold-excess spectral power. Not evidence that one estimator will identify every buried musical source.
7. **M. Müller / AudioLabs, Onset Detection and Spectral-Based Novelty.** [Onsets](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C6/C6S1_OnsetDetection.html); [spectral novelty](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C6/C6S1_NoveltySpectral.html). Retrieved. Research-author teaching/algorithm resources explain acoustic onset candidates, spectral novelty and time/frequency limitations. They justify candidate methods, not a promised performance advantage on untested material.
8. **Music Technology Group, Universitat Pompeu Fabra, Essentia OnsetDetection.** [Documentation](https://essentia.upf.edu/reference/streaming_OnsetDetection.html). Retrieved. Primary project documentation describes HFC, complex-domain, flux and other methods and points to the onset literature. Cited as implementation/method reference; adding Essentia as a dependency is not required.
9. **W. A. Sethares, Relating Tuning and Timbre.** [Author-hosted article](https://sethares.engr.wisc.edu/consemi.html). Retrieved. Supports spectrum-dependent dissonance relationships and timbre/tuning dependence. Does not validate this repository's top-12-peak normalization as perceptual roughness in calibrated units or establish aesthetic compatibility.
10. **M. Müller / AudioLabs, Self-Similarity Matrix.** [Resource](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C4/C4S2_SSM.html). Retrieved. Supports feature-based comparison/repetition navigation across a recording. Not proof of semantic music-section recognition.
11. **M. Müller / AudioLabs, Novelty-Based Segmentation.** [Resource](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C4/C4S4_NoveltySegmentation.html). Retrieved. Supports structural-change candidate extraction from self-similarity; explains dependence on representation and scale. Not a universal best segmentation algorithm.
12. **ITU-R BS.1116, Methods for the subjective assessment of small impairments in audio systems.** [Recommendation](https://www.itu.int/rec/R-REC-BS.1116/en). Official scope page retrieved. Supports the existence/scope of controlled listening assessment, not automatic musical approval; normative procedures were not audited here.
13. **ITU-R BS.1534, Method for the subjective assessment of intermediate quality level of audio systems (MUSHRA).** [Recommendation](https://www.itu.int/rec/R-REC-BS.1534/en). Official scope page retrieved. Appropriate research reference for controlled audio-system quality comparisons; not a mix-quality metric or procedure validated in this repository.
14. **ITU-R BS.1387, Method for objective measurements of perceived audio quality (PEAQ).** [Recommendation](https://www.itu.int/rec/R-REC-BS.1387/en). Official scope page retrieved. Identifies a standardized reference-based perceptual audio-quality task. It is not automatically applicable to evaluating an intentionally changed musical mix against an unchanged reference.

### Access and evidence limits

- ISO 532-2/ISO browser pages were blocked during retrieval; no wording or conformance requirement from an unread normative ISO document is asserted.
- Direct full-text retrieval of the Bello onset tutorial failed. Crossref verified the paper title and DOI [10.1109/TSA.2005.851998](https://doi.org/10.1109/TSA.2005.851998); the report's operational onset-method discussion relies on the retrieved author/project resources [7–8], not an imagined reading of that PDF.
- Research-author resources [6–11] are method foundations, not head-to-head benchmarks of this code. Claims of “best,” actual human audibility and preferred artistic edits remain unestablished without a defined task and appropriate evidence.
