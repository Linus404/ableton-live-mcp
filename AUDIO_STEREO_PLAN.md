# Goal 6 — Stereo and translation

Authoritative goal: frequency-dependent width, phase relationships, mono cancellation,
and changes in important-part audibility when folded to mono.

## Public contract

`audio_stereo.analyze_stereo(args)` backs offline `live_audio_stereo`.
Required `source: {name,path,signal_path}` identifies a mono/stereo WAV. Native
mono retains its level unchanged under fold; stereo-width/phase evidence is
explicitly unavailable. Optional
`sections: [{name,start_seconds,end_seconds}]`, `window_seconds` (0.1–1, default 1),
and `max_windows` (1–120) provide local coverage. Optional `target` and
`competitors` (1–8), each `{name,path,gain_db?}`, enable important-part comparisons
only with explicit zero-uncertainty `alignment` including the programme source
(including optional file-frame
`offsets_samples`), disjoint actual-in-mix `provenance`, and explicit calibrated
or assumed `listening_condition`, matching the masking tool contract. Source is
an independent programme observation and is not included in competition powers.

## Evidence and acceptance

- Whole, local and section measurements: original channel/mean RMS powers,
  mid `(L+R)/2`, side `(L-R)/2`, normalized L/R cross-power correlation,
  side fraction, and mono-fold power change relative to mean channel power.
- Six existing tonal bands: actual L/R auto/cross spectra, mid/side powers,
  normalized real coherence and aggregate cross-phase (not a delay estimate).
  Report Nyquist coverage, numerical floor and omitted spectral tails explicitly.
- Important-part original stereo versus arithmetic mono-fold Model-1-adapted
  threshold-margin/prominence evidence reuses the existing perceptual helper.
  Retain original gains and explicit listening/alignment/routing declarations;
  independent-channel stereo modeling is not binaural listening prediction.
- Exact in-phase, opposite-polarity, one-sided and frequency-selective test
  signals establish algebra/phase/cancellation; aligned competing signals test
  folded prominence and mandatory evidence gates. Silence/floors, partial
  tails, bounds, invalid metadata and nonfinite samples have explicit outcomes.
- No Live calls, temporary rendered audio, correction edits, human approval,
  universal width target, playback-device translation guarantee or keep/revert
  decision. Correlation alone never proves audibility.

Bounds: source plus at most nine mono/stereo contribution WAVs; identical
contribution rate/layout, 128 MiB/file, 120 seconds/file, 12 million scalar
samples/file, 48 million total decoded scalars and 96 million reserved sample
work (including repeated sections/model transforms), 32 sections, 120 windows.
Dependency set remains the existing audio-analysis extra.

## Implemented evidence

`src/audio_stereo.py` exports the agreed function and lean schema; native mono
is supported. Target mode includes programme in alignment and requires identical
channel layouts/sample rates. Acquisition declarations are retained, not promoted
to physical qualification. Important-part estimates retain original levels and
explicit optional gain counterfactuals. No fold loudness normalization is applied.
Reserved sample-work includes whole/local/section Welch/cross spectra and
contribution stereo/mono transforms; that bound can reject a long/repeated-section
request even when its per-file and window bounds individually pass.

`tests/test_audio_stereo.py`: 30 focused checks passed within the integrator's
248-test impacted suite (14.35 seconds), including exact centered,
hard-panned, inverted, quadrature and band-dependent stereo algebra, DC convention,
native mono, floors/silence, float headroom, local/section timing, spectral tails,
Nyquist coverage, retained-part fold modeling, strict alignment/provenance/listener
gates and work/metadata/value rejection. Initial default pytest temp directory had
a Windows ACL failure; using the approved OpenCode temp parent resolved it.
