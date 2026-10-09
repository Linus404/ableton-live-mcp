# Independent correctness and ponytail review

Reviewed 2026-10-08 by an agent separate from the implementer. No Live calls or
implementation edits were made by the reviewer. The review covered the masking
module, tests, MCP integration, documentation, reused WAV validation, and prior
loudness-review fixes.

## Initial findings

### P2: modeled inactivity mislabeled as source silence

`src/audio_masking.py` originally returned `silent_target_windows` for windows
with no target-filter excitation above the configured floor. That does not prove
source silence: a full-scale impulse at sample zero of a 4800-frame, 48 kHz window
is erased by the zero-valued Hann boundary. The report counted it as silent while
declaring full temporal coverage.

The estimator's transient limitation was already disclosed. The minimal fix is
to label the count `inactive_target_windows` and explicitly define inactivity as
modeled/windowed filter excitation below the floor, not literal source silence.
Add a boundary-impulse regression; no expanded DSP is needed.

### P3: frequency-center coverage omitted from the standalone report

Filter centers span 50 Hz to below the lower of 16 kHz and Nyquist. At 48 kHz the
last center is 14709.98 Hz. An independent 22 kHz sine probe appeared through that
filter's tail at -88.741 dBFS, despite a source mean-square level of -23.01 dBFS.
These are valid filter-tail measurements, but the original standalone response
did not specify its center range. `full_common_interval` describes time coverage,
not complete frequency coverage.

The minimal fix is to report filter count, first/last center frequencies, and ERB
spacing, and state that centers omit extreme bass/upper treble and that a filter
center is not an inferred source-frequency peak. No extra filter bank is needed.

## Scientific and integration assessment

- Symmetric roex(p) power weighting, `p = 4*fc/ERB`, ERB bandwidth and ERB-rate
  spacing are coherent established auditory-filter approximations.
- Independent FFT Parseval checks passed for DC, even-length Nyquist and
  odd-length noise. No missing one-sided power normalization factor was found.
- Stereo averages powers before filtering, avoiding phase-canceling downmix.
- Gain adjustments, retained original powers/ratios, and incoherent competitor
  attribution behave consistently.
- Alignment/provenance requirements reject absent or false claims but remain
  clearly caller-declared. Raw capture calibration is not fabricated.
- Layout/rate/decoder validation and file/sample/computation budgets precede
  expensive analysis; windows are streamed with bounded kernel caching.
- Explicit offsets, shortest common intervals, and partial tails expose temporal
  coverage appropriately.
- SPL calibration, listener thresholds, temporal/binaural masking, and correlated
  or nonlinear bus behavior are accurately marked unsupported. The custom proxy
  must not be marketed as a masking-threshold detector or audibility probability.
- Both prior loudness-review fixes are present and regression-tested, with no
  identified adverse interaction with masking analysis.

## Ponytail review

**No actionable over-engineering findings; no complexity cuts recommended.**
The pure offline module reuses WAV validation and existing dependencies without
speculative abstractions or additional Live orchestration.

## Independent checks

The checkout virtual environment ran the masking module tests, masking MCP tests,
loudness module tests, and MCP server tests: **197 passed**. The approved pytest
temporary base was `masking-independent-venv-review` under the agent temp folder.
An earlier system-Python run had environmental failures because that interpreter
lacked the project's visual backend; the checkout environment resolved them.

Independent numerical probes checked 20 Hz, 1 kHz, 16/18/22 kHz tones, a Hann-edge
impulse, partial windows and one-frame tails, plus FFT power endpoints. DOI
references resolve; model formulas were reviewed mathematically. No human
listening or absolute/perceptual masking-threshold validation was performed.

## Resolution

Both findings were fixed and **closed by independent recheck**:

- `inactive_target_windows` now describes modeled inactivity. The method and
  limitations explicitly distinguish it from literal source silence, including
  the exact zero-weight endpoint case. A regression compares a boundary impulse
  with an active mid-window impulse.
- `method.frequency_coverage` now reports actual first/last centers, center count,
  one-ERB spacing, intended exclusive upper bound, and non-brickwall filter tails.
  An upper-frequency regression checks disclosure and residual tail excitation.

The reviewer reran masking analysis and MCP integration tests: **25 passed**.
No new findings or unnecessary complexity were introduced. The parent then ran
the full suite: **396 passed**, and repeated the known-audio MCP scenario checks
successfully. `git diff --check` passed. No Live calls were required for these
offline fixes or their validation.
