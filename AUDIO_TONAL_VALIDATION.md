# Tonal balance — feature 3 verification

**Complete for the bounded offline tonal-evidence scope (2026-10-09).**
The final full repository suite passed **559 tests**; independent numerical and
ponytail reviews accepted the corrected implementation. Fresh public MCP stdio
calls passed on retained actual Live recordings without changing the open set.

## Implemented contract

`live_audio_tonal` accepts real identified WAVs, preserves original levels and
signal-path descriptions, and returns whole, section and local tonal evidence.
Welch's averaged periodogram (Hann 250 ms, 50% overlap; scipy density scaling)
is the established spectral estimator. Stereo channels contribute mean power,
not phase-cancelling mono samples. Frequency-bin cells are proportionally
integrated into bounded musical-region and octave bands, with explicit Nyquist
coverage. Centroid and 85% power rolloff describe spectral brightness; they do
not model perceived brightness. Narrow peak prominence/width and local recurrence
provide candidate resonance evidence without diagnosing resonance causes.

Brief band ranges supply explicit musical expectations. Reports separate actual
departures, conditional muddiness/harshness interpretations, and unmade musical
judgments. An independently chosen reference supplies spectral-shape deltas;
whole reference vs source sections/windows is deliberately not an aligned event
comparison. Gain-normalized shape and original LUFS/RMS/peak measurements remain
separate. Predicted gain/headroom for reference LUFS matching never changes audio.

## Runnable numerical and MCP checks

```powershell
python -m pytest tests/test_audio_tonal.py -q
```

The numerical suite verifies:

- A 1 kHz sine has the expected -23.0103 dBFS mean-square power, frequency and
  centroid; opposite-polarity stereo preserves power and recurrence.
- A -20 dB copy retains equal normalized band shapes while original loudness
  differs by 20 LU and the predicted matching gain remains separate.
- Bass/bright passages localize to named sections and local windows; only an
  explicit band expectation yields above/below-brief facts.
- Silence and <250 ms audio produce null/unavailable spectra; an 8 kHz source
  has partial upper-mid/unsupported high coverage, never fabricated missing treble.
- Seeded white noise has bandwidth-proportional band power and expected centroid/
  rolloff; independent dark reference is accepted without alignment declarations.
- Invalid arguments, too many windows and repeated-section work budgets fail
  before unbounded analysis.
- Real MCP discovery/dispatch analyzes a WAV while a bridge stub rejects any
  attempt to call Live.

Targeted result: **10 tonal tests passed**; tonal, audio tool and MCP suites together
passed **167 tests** using `.venv\Scripts\python.exe`. Windows default pytest temp storage was
permission-blocked; the same tests passed with an explicit permitted basetemp
under `C:\Users\LINUSV~1\AppData\Local\Temp\opencode\tonal-tests`.

## Acquisition and external validation

Bounded strict validation confirmed Live 12.4.6, PID 1040, current Remote Script
and `live_mutations_safe: true`. No restart was needed. The feature changes no
Remote Script and analysis is offline.

Final fresh UTF-8 JSON-RPC stdio initialization, discovery and tool calls analyzed
historical native take `f0385709f0264059b7ea169e5e641389`, retained under the
approved temporary directory's
`audio-feature-final-mcp/20261009-154800/capture/`. All nine original PCM24 stereo
44.1 kHz WAV hashes matched their manifest. Before/after compact Live set summaries
were exactly equal; there was no new acquisition or set mutation. The validation
rig was previously removed: its historical qualification is not transferred to
the current set. Identified signal paths are retained in every request.

| Actual retained signal | Integrated LUFS | RMS dBFS | Sample peak dBFS |
| --- | ---: | ---: | ---: |
| Post Mixer B, `001.wav` | -44.064 | -48.107 | -41.938 |
| Post Mixer Group, `000.wav` | -28.041 | -32.065 | -26.348 |
| Master Resampling, `008.wav` | -24.464 | -28.489 | -22.062 |

B's strongest qualifying peak was 1016 Hz, recurrent in 10/10 eligible local
windows; the Group peak was 996 Hz. Independent whole-file B-minus-Group
normalized high-band contrast was -46.578 dB. Suggested reference matching gain
was -16.023 dB, with predicted sample peak -42.371 dBFS; no gain was applied.
B's file-relative early [2,5] and late [8,11] sections differed by +6.020 LU while
both spectral centroids were 1015 Hz. This intentional level contrast was not
classified as a tonal fault.

Successful reports had `processing_complete: true` but
`spectrum_coverage_complete: false`: the 12.933515 s file's whole spectrum covered
12.876145 s, omitting a 0.057370 s final Welch tail. Local and section omission
evidence also remained explicit. A caller-declared deliberately mismatching brief
classified measured B bass/high shares as below brief; no brief meant no
departure classification. An actually silent retained return had null levels,
shape, comparisons and match gain, with no invented absence judgment. Missing
signal path, outside-file section and reversed brief ranges were refused.

Final artifacts under `C:\Users\LINUSV~1\AppData\Local\Temp\opencode`:

- `tonal_final_stdio_results.json`: exact schemas, requests/responses and snapshots.
- `tonal_final_verified_summary.json` and `tonal_final_live_validation_notes.md`:
  hash/state checks, numerical assertions and acquisition scope.
- `tonal_stdio_probe.py`, `tonal_stdio_requests.json`, `tonal_verify_retained.py`:
  runnable public MCP checks; the `tonal_final` prefix selects final artifacts.
- `tonal_independent_review.md` and `tonal_review_oracle.py`: independent analytic
  two-tone, gain, stereo, silence, parser and numerical-floor checks, plus manual
  NumPy Hann/rFFT analysis of B/Group/Main agreeing within 0.001 dB and 0.001 Hz.
- `tonal-ponytail-review.md`: final acceptance, no remaining complexity findings.

Reviews resolved roundoff-only spectral ghosts, conservative floor-limited
missing-band evidence and processing-versus-coverage semantics. The redundant
test-fixture write identified by ponytail review was removed. Qualification and
spectral evidence do not establish human listening approval.

## Limits and interpretation

Numerical roundoff is not tonal evidence: analyzed power must exceed both
1e-30 absolute power (-300 dBFS mean-square) and 1e-24 times the original
channel-mean-square power. Spectral/band values at or below that combined floor
are unavailable. Raw analyzed power, original RMS/peak and per-channel DC remain
available. DC-only and out-of-band Nyquist-only signals therefore do not create
invented brightness/peaks; a -203 dBFS real tone remains measurable in the check.
Bands and octaves carry explicit measured/below-floor/unsupported status. When
the analyzed total is non-silent, a below-floor band's conservative relative-power
upper bound (rounded upwards) may establish a below-brief departure only if the
entire target band is covered and that bound is strictly below the minimum. The
measured value stays null. Whole silence is never classified as below brief.

`complete`/`processing_complete` concern successful processing only, not full
passage spectral measurement. `spectrum_coverage_complete` and incomplete-reason
counts expose short intervals and omitted final Welch blocks. For example, an
event only in the last 100 ms of a 1.1-second file may be absent from the whole
spectrum; an explicit final short local window is unavailable, not evidence of
silence. Read interval coverage before drawing conclusions about that event.

250 ms block timing/Hann weighting can suppress short transients and excludes
incomplete final blocks; low-frequency and peak-width resolution is finite.
Each spectrum reports block count, covered duration and omitted tail. Welch
averaging assumes locally stationary statistics; evolving sounds are averaged
rather than resolved into perceptual events. There are no fabricated confidence
probabilities for harshness, muddiness, or resonance diagnosis.
Peak recurrence considers only the five strongest qualifying peaks in each
measured non-silent local window. Broad-band ratios are compositional: changing
another band changes relative energy even if this band's absolute power stays
fixed. dB reporting and brief decisions use 0.001 dB precision. Silence or absent
energy is not evidence of an undesired missing musical part. Partial-frequency
coverage prevents expectation/reference judgments in that band; differing covered
normalization intervals disable all shape deltas. Reference passages must be
musically comparable by the caller's brief; no universal target, masking estimate,
perceived harshness score, automatic EQ correction or keep/revert judgment exists.
