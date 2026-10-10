# Independent compatibility/stereo review

## Status

2026-10-10: implementation/numerical and retained public-dispatch/physical-source
review **PASS for this bounded historical take**. No unresolved blocker for goals
5/6's disclosed measurement/model contracts. Reviewer performed no Live
calls, production edits, commits or pushes.

## Scope and independent checks

Reviewed original `AUDIO_UNDERSTANDING_GOALS.md`, remaining-feature plan,
compatibility/stereo plans, both owner modules and focused tests. Ran:

```powershell
python -m pytest tests/test_audio_compatibility.py tests/test_audio_stereo.py -q --basetemp "C:\Users\LINUSV~1\AppData\Local\Temp\opencode\review-compat-stereo-pytest"
```

Result: **53 passed in 9.92 s**. Initial invocation using pytest's default
temporary directory failed at fixture creation with Windows access denied;
explicit approved temporary parent resolves that environmental issue.

Separately called public analysis entry points on float64 48 kHz, one-second
synthetic WAVs using independent algebra rather than production metric helpers:

| Stereo fixture | Expected/observed side fraction | Correlation | Mono change |
| --- | --- | --- | --- |
| L=R, 400 Hz | 0 | 1 | 0 dB |
| L=-R | 1 | -1 | exact zero; null dB with floor bound |
| L only | 0.5 | unavailable inactive R | -3.010300 dB |
| sine L/cosine R | 0.5 | approximately 0 | -3.010300 dB |

Quadrature low-mid band cross phase was +90 degrees, consistent with the
documented `conj(L)*R` convention. Opposite polarity returned -180 degrees,
equivalent to +180. Direct mid/side transforms avoid catastrophic cancellation
from subtracting nearly equal auto/cross powers.

Equal-amplitude 400 Hz target against 400/420/800 Hz competitors independently
matched `0.5*(exp(-3.5*d)-exp(-5.75*d))`, with
`d=0.24*abs(f-g)/(0.0207*min(f,g)+18.96)`, to better than 1e-8:
0, 0.08832568327905249, and 0.0000021972390384408475 respectively.
This checks the disclosed normalized Sethares-kernel adaptation, not subjective
consonance, standardized roughness units or listening approval.

## Findings and dispositions

- Compatibility initially reserved only two decoded passes after masking DSP.
  Owner corrected this to a conservative metadata preflight bound: five scalar
  traversals, seven with overlapping perceptual spectra, capped at 96 million
  before analysis. Existing roex computation bound remains. Current focused
  tests exercise rejection before invoking masking DSP.
- Resolved FFT-bin maxima, top-12 retained partials/top-three cross pairs,
  integer-ratio cents and one-bin sensitivity intervals are appropriately
  described as bounded spectral-partial evidence, not f0/key/chord recognition
  or statistical pitch confidence. Noise/transient maxima remain qualified.
- Compatibility timing uses direct channel-mean numerical activity, including
  partial 10 ms cells; original timing is retained under gain scenarios. Window
  peak-relative/absolute floors and boundary quantization are disclosed.
- Roughness is stationary-window, retained-peak, pair-normalized cross-source
  interaction. It can describe two sources active at different moments within
  one reporting window; timing evidence must be read separately. It excludes
  noise residuals, self-roughness, phase and temporal/binaural effects.
- Stereo band normalized real cross-power is not magnitude-squared coherence
  or a delay estimate. Band-summed phase may conceal frequency-specific phase
  differences; inactive/floor-limited results are null. Native mono stays at
  original level and stereo evidence is unavailable.
- Important-part modeling requires full programme/contribution alignment,
  unique names/paths, declared disjoint actual-in-mix provenance and explicit
  listener conditions. Programme is not counted as a competitor. Arithmetic
  fold preserves declared gains/SPL reference rather than silently matching
  loudness. Incoherent powers cannot model correlated waveform interference.
- Nyquist bands, short Welch intervals/tails, bounded local windows/sections,
  sample/work budgets and finite-data checks have explicit outcomes. Processing
  success does not imply full spectral coverage.
- Neither feature establishes human distinguishability/audibility, playback
  translation guarantees, musical quality or automatic keep/revert decisions.

## Final retained evidence review

Reviewed `AUDIO_REMAINING_FEATURES_VALIDATION.md` and the retained evidence root
`C:\Users\Linus V2\.ableton-live-mcp\audio_remaining_validation\1361fde991d144fca61dc637abedf343`.
The shared-spectrum extraction was inspected and preserves the reviewed stereo
algorithm; the integrator additionally reports 248 impacted tests passing.

Independent read-only recomputation, without production measurement helpers:

- All five retained original/native WAV SHA256 values match the ledger. All
  eleven current runtime module SHA256 values match final public-dispatch hashes.
- Actual native target+competitor equals native Main at every retained frame:
  maximum residual **1.1920928955078125e-7**, below three PCM24 quanta.
- Each native source and summed programme matches its independent 2048-frame
  source marker at exact file frames 22050 and 507150. All six fitted gains are
  within 1e-6 of unity and residuals below 7e-8. Retained neighbor-lag tests reject
  adjacent positions by 47–99 times. No alignment/gain correction was applied.
- Independently read actual native samples: [1,3] and [3,5] have 2 seconds joint
  activity/zero target exposure; [5,7] has zero joint activity/1 second exposure.
- Public native harmonic/beating roughness matches independent equal-amplitude
  analytic kernels **0.0006811154501498891** and **0.06487423407783438** within
  1e-5. Request 5's gain scenario retains request 4's original roughness exactly.
- Native [7,9] target correlation is **-0.6000000266231397** and arithmetic-fold
  power difference **-6.989700332417254 dB**, matching independent -0.6 and
  `10*log10(0.2)` algebra. Retained bass/upper-mid reports distinguish centered
  and opposite-polarity components. Folded Model-1 threshold-excess changes
  -6.947 dB in four windows; this is model response, not human audibility proof.
- Public stdio responses 4/5 (compatibility) and 6/7 (stereo) exactly equal their
  retained standalone reports. Responses 12/13 correctly refuse false alignment
  and missing listener evidence. Public before/after set summaries are identical.

Manifest completeness, receiver cleanup, routing/settings stability and current/
safe runtime flags are retained. The two actual source routes have empty device
chains, zero sends and Main output; the existing MIDI source is strictly
non-audio. Actual whole-frame sum plus source-marker transfer supports the scoped
unity/disjoint in-mix declaration rather than merely assuming it from mixer
parameter values. Process-bound settings observations retain **PDC off** and
Reduced Latency When Monitoring off. Unknown SDK track delays remain null.

The manifest correctly remains **unqualified**, with alignment/provenance flags
false and no manufactured certificate. The public offline declarations cite the
additional take-specific measured experiment, not a rewritten manifest. Accept
this historical direct empty-device recording only; it does not qualify the
PDC-enabled certificate workflow, future captures, arbitrary groups/returns/
device latency, or continuous sub-sample delay. Removing the rig prevents profile
transfer. Assumed 100 dB SPL reference is not monitor calibration. No remaining
blocker is found within those explicitly limited claims.
