# Goal 5: compatibility between sounds

Authoritative goal: frequency competition, timing overlap, harmonic relationships,
roughness, and whether important parts remain distinguishable together.

## Public contract

`audio_compatibility.analyze_compatibility(args)`; MCP `live_audio_compatibility`.
Use the existing masking contract: required `target`, 1–8 `competitors`,
zero-uncertainty declared `alignment`, disjoint actual-in-mix `provenance`;
optional `window_seconds` (0.1–1), `max_windows` (1–120),
`listening_condition`, `sections`, and `brief: {description}`.
Sources are `{name,path,signal_path,gain_db?}`. Gains are explicit offline scenarios, never
automatic loudness matching or Live changes. Bounds and offset semantics match
`analyze_masking`; no new dependencies or Live operations.

## Minimal faithful implementation

- Reuse `analyze_masking` for resource/provenance/alignment validation, roex
  frequency competition, attribution, and optional threshold-based target
  prominence. Retain its original-level evidence and full limitations.
- For each target/competitor pair and reporting window measure direct 10 ms
  channel-mean RMS activity, joint activity duration and separate activity counts.
  Explicit absolute/relative floors define activity, not human audibility.
  Partial cells are measured with their actual durations; no inferred onsets.
- Analyze channel-mean Hann spectral power in each reporting window, extract
  at most 12 resolved local peaks per source (20 Hz–Nyquist, -40 dB relative
  peak floor). Report strongest cross-source peak ratios, cents from nearest
  low-order integer ratio (1–8), and extraction/retention coverage. These are
  partial-frequency relationships, not detected fundamentals, keys or chords.
- Calculate Sethares-style cross-source spectral roughness from retained peaks:
  critical-band-scaled exponential interaction weighted by normalized peak
  amplitudes. Report dimensionless model estimate and original-level/scenario
  variants, no pleasantness score; no self-roughness, binaural or temporal model.
- Distinguishability evidence combines target competition, optional listening-
  condition prominence, and timing exposure. Human recognition/separation remains
  explicitly unestablished; there is no automatic keep/revert judgment.
- Local times are caller-declared common-time seconds; retain sections and brief.
  Short spectral tails are explicitly unmeasured, never silently padded.

## Acceptance

Independent numerical synthetic WAV checks: staggered bursts versus simultaneous
bursts; unison/octave versus detuned resolved sinusoids; roughness rises for nearby
partials and falls at wider separation; silence returns unavailable harmonic
evidence; stereo anti-phase preserves channel-mean evidence; gains retain
original measurements. Validate explicit offsets, unknown arguments, ambiguous
provenance, incompatible layouts, window/resource bounds and nonfinite samples.
Every model reports units, research basis, frequency/time coverage and limits.
Passing local tests establishes numerical behavior, not physical acquisition or
human approval. Parent approved this plan; implementation and 24 focused checks
are complete. `tool_properties()` and `TOOL_REQUIRED` provide lean schema exports.

## Implemented measurement conditions

The existing masking pass imposes 120 seconds/file, 12M scalar samples/file,
48M aggregate decoded samples, 128 MiB/file, and its independent 300M filter
computation bound. Before DSP the wrapper additionally reserves five full-file
scalar-sample traversals (two decodes, roex spectrum, partial spectrum, direct
timing), or seven when overlapping perceptual spectra are requested, against
96M sample-work. Explicit offsets can reduce analyzed time but do not reduce
this conservative reservation. Sources are streamed in the second pass.

Timing always retains original file levels under gain scenarios. Activity uses
the disclosed per-source/reporting-window peak 10ms-cell relative floor of -80dB
plus absolute power floor 1e-20; this is numerical activity, not audibility.
Sections label overlapping reporting windows, not exact section summaries.
Roughness uses normalized cross-amplitude products, not standardized dissonance
units; both original and explicit gain-scenario estimates remain distinct.

Focused command (Windows default pytest temp directory was inaccessible):
`python -m pytest tests/test_audio_compatibility.py -q --tb=short --basetemp="C:\Users\LINUSV~1\AppData\Local\Temp\opencode\compatibility-tests"`.
