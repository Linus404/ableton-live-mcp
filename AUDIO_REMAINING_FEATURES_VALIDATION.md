# Goals 5–8 — actual Live and public offline validation

## Scope and status (2026-10-10)

The four public offline tools passed retained actual-audio experiments for the
bounded measurement contracts in `AUDIO_REMAINING_FEATURES_PLAN.md` and the four
individual feature plans. Eight successful fresh public stdio calls and two
expected evidence-gate refusals passed on the final stable implementation,
including the shared masking/stereo helper and common-interval correction.
Independent sample-domain/public-result assertions passed. Independent final
reviews **PASS** in `AUDIO_COMPATIBILITY_STEREO_REVIEW.md` and
`AUDIO_INTEGRITY_DEVELOPMENT_REVIEW.md`.

These results establish measured compatibility, stereo/mono, integrity and
section-development evidence. Modeled prominence and roughness remain estimates;
they do not establish human distinguishability, musical improvement, playback
translation approval or a keep/revert decision.

Evidence root:

`C:\Users\Linus V2\.ableton-live-mcp\audio_remaining_validation\1361fde991d144fca61dc637abedf343`

Key retained files:

- `fixture.json`: initial set snapshot, exact owned IDs and generated source paths.
- `target.wav`, `competitor.wav`: actual imported FLOAT source files, not counted
  as native acquisition recordings.
- `capture.json`: exact acquisition arguments and direct Python-wrapper result.
- `capture/34444716dd2943f8a4df3ea162488b19/manifest.json`: full native acquisition,
  routing/device/settings/runtime evidence, finalized files and receiver cleanup.
- `independent_physical.json`: all five original/native WAV hashes, six measured
  marker recoveries, gain/residual/neighbor-lag checks and actual programme sum.
- `public_requests.json`, `public_responses.json`: exact initialize, tools/list,
  all tool calls and read-only before/after set summaries from a fresh stdio process.
- `4_live_audio_compatibility.json` through `11_live_audio_development.json`:
  standalone successful reports corresponding to those request IDs.
- `public_source_hashes.json`, `public_runtime_sources/`: exact archived source
  bytes and SHA256 for eleven relevant source files; hashes were checked
  unchanged throughout the final public process.
- `public_independent_assertions.json`: independent raw RMS/crest/DC, timing,
  roughness kernel, stereo algebra, pulse/sine interpolation and delivery checks.
- `cleanup.json`, `restored.json`, `final_health.json`: owned-only source removal,
  exact original snapshot restoration and final strict current/safe runtime probe.

The runnable helpers are `validation/remaining_physical.py` (approved owned rig),
`validation/remaining_verify.py` (offline marker/sum oracle),
`validation/remaining_public.py` (fresh public process),
`validation/remaining_audit.py` (offline assertions), and
`validation/remaining_health.py` (sequential final health retention).
Do not rerun rig creation/capture without authorization for another experiment.

## Actual acquisition and deliberately limited qualification

Initial and final strict validation passed `runtime_current:true` and
`live_mutations_safe:true` for Live 12.4.6, process **22236**, song **130097952**.
The inspected nonblank Ableton-only screenshot was
`C:\Users\Linus V2\.ableton-live-mcp\ableton_window_1791639535131.png`:
Untitled, one empty MIDI track, original five returns, no modal. No restart,
Control Surface reload, save or discard was needed.

Only two uniquely owned audio tracks were added, with zero sends, centered pan,
unity mixer gain, no devices and unwarped/unlooped Arrangement clips at beat zero.
The original MIDI/returns/Main were not edited. Native monitor-Off Post Mixer
receivers and separate Main Resampling recorded one simultaneous pass; receivers
output Sends Only with zero sends. Source IDs were **130041808/130040688**.
Main had no devices and its actual unity route was tested, not inferred from a
normalized parameter. Requested passage was 13 seconds; raw untrimmed native files
retain **626176 frames / 14.1990022676 seconds**, stereo PCM24 at 44.1 kHz.
The source recipes contain 12 seconds. The difference in total file duration is
not an exact capture-end claim.

The process-bound native-menu observations found **PDC disabled** and Reduced
Latency When Monitoring disabled, unchanged before/after. No setting was altered
to satisfy a gate. The acquisition manifest correctly keeps
`alignment.verified:false`, `sample_aligned:false`, `shared_sample_clock:false`
and unqualified provenance. It was not rewritten into a certificate and was not
passed to `live_audio_assess`. Unexposed SDK latency/track-delay remains null.

Instead, the public offline declarations cite this particular independent
experiment. Each original file has independent seeded 2048-frame stereo random
markers at source frames **22050** and **507150**. Correlation on each native
source and the independently summed programme template recovered those exact
file frames both before and after the musical material. Relative integer offset
is zero for all three paths. Correct-lag correlation magnitude exceeds adjacent
lags by **47–99 times**. Marker fitted gains are within `8.7e-8` of unity and
maximum residual is about `6.01e-8`, consistent with PCM24 quantization.

Across **every retained frame**, native target + native competitor equals native
Main within maximum absolute residual **1.1920928955078125e-7**. The conservative
three-PCM24-quantum bound is **3.5762786865234375e-7**. Fitted master gain is
**1.0000001313764126**; no fitting gain was applied to files or analysis inputs.
Before/end routing profiles are stable. Actual two disjoint routes, zero sends,
unprocessed unity Main, original empty/non-audio source and these measured
markers/sum establish the scoped in-mix contribution evidence for this take.
Equal lengths or a capture status flag alone do not establish it.

This is a take-specific direct empty-device-path experiment with PDC off, not
the supported PDC-enabled native acquisition certificate workflow. It cannot
qualify future captures, arbitrary device/group/return paths, dynamic latency,
or continuous sub-sample delay. Removing the owned rig does not invalidate the
historical offline WAV evidence but prevents transferring its profile to new audio.
The listening declaration is explicitly **assumed 100 dB SPL at 0 dBFS RMS**,
not a measured monitor calibration or human listening test.

### Retained SHA256 (native acquisition files)

| File | Path/role | SHA256 |
|---|---|---|
| `000.wav` | actual target Post Mixer | `d5fae8e4083304dc23b8c058c6f51c2aa185bb830514d96e6988aba38ef090de` |
| `001.wav` | actual competitor Post Mixer | `a3e21c61fbe41da86a2d2a8ed6b01d7aae14e8d0a22cd2179f0d46c9871b09f3` |
| `002.wav` | actual Main Resampling | `33216e84ac51b1cd02a504bdc5701cf184d7fc82b90a203fb43660eb6b1af7a4` |

Source FLOAT hashes are `9d569cbc3dab2f719495c3fb912212886ada4512e2d44b937ce9276af32032cd`
and `b6441c402bc07cde24b43915fa5dc625dfb71fbce0486ce040c7227a0c64926c`.

## Goal 5 — compatibility evidence

The common-file sections are harmonic [1,3], beating [3,5], alternating [5,7],
frequency-selective stereo [7,9] and impact [9,11] seconds. Markers are excluded
from these musical sections. The 0.5-second reporting windows give 2 Hz resolved
partial-bin spacing; no fundamental/key/chord recognition is inferred.

| Controlled actual parts | Joint activity | Target exposed | Resolved relationship | Cross-partial roughness |
|---|---:|---:|---|---:|
| 440 + 660 Hz [1,3] | 2.0 s | 0 s | 3:2, 0 cents | 0.00068111545015 |
| 440 + 450 Hz [3,5] | 2.0 s | 0 s | near 1:1, +38.905773 cents | 0.06487423407783 |
| Alternating 440 Hz bursts [5,7] | 0 s | 1.0 s | retained 1:1 partials | 0 |

Direct original-level 10 ms activity checks agree with the intentional overlap
and exposure controls. An independently evaluated disclosed Sethares kernel
agrees with both steady-tone roughness values within `1e-5` (actual differences
approximately `4e-16`). The higher beating estimate is not a bad-sound verdict;
nonoverlapping sources can still share retained window partials, so temporal
exposure must be read separately from stationary spectral relationships.

Public request 4 retains local roex competition, source attribution and Model-1
prominence; request 5 supplies an explicit target -6 dB counterfactual. Every
original roughness measurement remains identical in that scenario. There is no
automatic normalization/file mutation. Human distinguishability and musical
judgment remain unavailable. Request 12 refuses `alignment.verified:false`.

## Goal 6 — stereo and mono translation evidence

The target's [7,9] section contains centered 220 Hz at 0.02 amplitude and
opposite-polarity 3000 Hz at 0.04 amplitude. The actual native stereo file gives
L/R normalized cross-power **-0.6000000266**, consistent with the independent
algebraic **-0.6**, and arithmetic mono-fold change **-6.9897003324 dB**,
consistent with `10*log10(0.2)`. Its frequency-dependent band reports distinguish
centered bass and side-heavy upper-mid energy/phase instead of imposing a width
target. In-phase sections fold with 0 dB change. Original channel power is
preserved rather than mistaking anti-phase content for source silence.

Request 6 models the target against its independent centered 3000 Hz competitor
at actual in-mix gains, including the separately aligned programme. In all four
[7,9] windows, mono minus stereo threshold-excess prominence is **-6.947 dB**;
retained above-quiet-threshold component counts change **12 to 2**. This is a
Model-1 spectral-prominence response to the fold, not a human audibility verdict.
Request 7 is single-source width/phase evidence and explicitly leaves important-
part attribution unavailable. Request 13 refuses missing listener conditions.
Welch tail omissions remain explicit (`spectral_coverage_complete:false`);
processing success is not complete spectral passage coverage.

## Goal 7 — integrity and delivery evidence

The competitor's actual native [9.1,9.9] second section is an 11025 Hz tone at
44.1 kHz, phase pi/4, ideal continuous amplitude 0.2. Sample peak is
**-16.990 dBFS**, while the 4x polyphase estimate is **-13.964 dBTP**.
The independent analytic continuous sine is **-13.9794000867 dB**; the
0.0154 dB difference remains estimator/finite-boundary evidence, not certified
true-peak compliance. The whole-file maximum is **-13.864 dBTP** near the tone
termination: it is not substituted for the steady-sine oracle. Reported filter,
zero-extension, boundary and continuous-maximum limitations remain explicit.

The target's deliberately inserted one-sample pulse at **10.25 s** produces two
localized jump candidates of approximately **0.4000** and **0.3969** full scale
at 10.25 and 10.2500226757 seconds under threshold 0.25. Its measured 4x peak is
also checked against an independent local **513-sample sinc reconstruction at
64x fractional positions**, within 0.03 dB. This is a distinct sample-domain
check, not a call into the production interpolation helper.

Direct float64 sample means/RMS agree with the reported original levels/DC.
The intentional [10,10.5] target DC/pulse region and leading, inter-burst and
trailing silence are localized rather than hidden by whole-file averaging.
The fixture explicitly intends those silences and transients; detector reports
still say intent unknown rather than declaring them unintended faults.
Actual PCM24 files have zero rail contacts and no claimed proven clipping.
Positive/negative rails and float-above-unity behavior are numerical fixture
acceptance tests, not falsely attributed to this unclipped physical take.

Request 8 checks explicit 44.1 kHz/stereo/PCM24 metadata and DC requirement,
while its deliberately strict **-20 dBTP** limit reports a departure. Request 9
has no delivery requirements and invents no default target. These concern the
identified retained recording files, not a released master/export or certified
delivery meter. No automatic audio repair or gain change is performed.

## Goal 8 — section development evidence

Request 10 retains the five named sections, caller intent, an explicitly equal
RMS expectation for harmonic versus beating, and nested balance from the same
aligned programme plus both actual disjoint contributions. Request 11 omits
nested balance/expectations and preserves explicit unavailable attribution and
no expectation judgment instead of inventing missing-part or arrangement claims.

| Native programme section | LUFS | RMS dBFS | Crest dB | Centroid Hz | Candidate/s | Effective broad bands |
|---|---:|---:|---:|---:|---:|---:|
| harmonic | -25.551 | -27.959 | 5.602 | 550.000 | 0.5 | 2.000 |
| beating | -25.625 | -27.959 | 6.018 | 445.000 | 0.0 | 1.000 |
| alternating | -28.638 | -30.969 | 3.010 | 440.000 | 0.0 | 1.000 |
| frequency-selective stereo | -24.186 | -29.788 | 6.677 | 2470.476 | 0.0 | 1.627 |
| impact | -11.277 | -19.746 | 12.001 | 10388.366 | 2.0 | 1.259 |

Independent direct sample RMS/crest match every section within 0.001 dB. The
equal-power steady sections meet **0 +/-0.01 dB** declared RMS contrast; their
different spectral spread gives the analytically expected effective band counts
2 versus 1. Contrast uses later minus earlier. Two part-balance records occur in
each requested section with original levels and relative-to-programme differences.
Intentional lower alternating power and louder/denser impact section are retained
observations, not automatic faults. The impact section also contains the sustained
quarter-rate diagnostic tone; its loudness is not attributed solely to pulses.

Candidate rates are acoustic-detector proxies, not note counts: alternating
same-frequency handoff can have zero programme onset candidates while actual
part activity alternates. Seven whole-file onset candidates are reported with
no cap omission, but the detector is explicitly nonexhaustive. Spectral omissions
and truncated-event region evidence remain available; `complete` concerns
processing, not exhaustive musical or spectral coverage.

## Recovery, cleanup and verification gates

Live initially refused DOUBLE/64-bit WAV import. The first partially created
owned track was removed by retained registry identity and its original snapshot
was verified exactly before retrying FLOAT sources. Failed-attempt evidence is
under sibling directory `65e7739c560f4728ae04fcd8d46e069b` (fixture/cleanup/restored).
The new server was being registered while the first public capture attempt ran;
`make_server` failed on pending `audio_stereo` import before recording. Acquisition
then used the existing direct `capture_in_mix` wrapper, explicitly labeled in
`capture.json`; it is not counted as a public MCP acquisition call. All final
four-feature analysis requests used fresh actual public stdio discovery/dispatch.

The native wrapper removed all three owned receivers. Subsequent owned-only
source cleanup restored exactly the original `audio_capture_snapshot`: sole
MIDI **1844708544**, original five return identities, Main **1844651840**,
selected E return **1845967360**, stopped beat **1.094240395021645**, 174 BPM,
loop false and no recording/automation-writing/Session override. Full compact
set summaries before/after final offline public analysis are exactly equal.
Final retained strict validation passes current/safe runtime on PID22236.

The integrator reported **638 full-suite tests** before helper extraction and
**248 impacted tests** after the final shared-helper/common-interval changes.
The final current-tree full regression passed **639 tests in 97.15 seconds**
with `python -m pytest -q --basetemp C:\Users\LINUSV~1\AppData\Local\Temp\opencode\remaining-final-current-tree`;
`git diff --check` exited zero. No production/source changes followed the
accepted public source hashes.
Those are implementation acceptance gates, not new physical acquisitions or
additional unique counts. This validator reran final public calls and independent
physical/result assertions after those source changes and checked exact source
hash stability. `AUDIO_COMPATIBILITY_STEREO_REVIEW.md` records independent final
**PASS** for goals 5/6: five WAV and eleven current source hashes, public responses
4–7 and refusals 12/13, independently recomputed marker fits, whole-frame sum,
activity, analytic roughness and native stereo algebra. The reviewer explicitly
retains the unqualified PDC-off context and rejects global-certificate inference.
`AUDIO_INTEGRITY_DEVELOPMENT_REVIEW.md` records independent final **PASS** for
goals 7/8: all five WAV/current and archived source hashes, exact public responses
8–11, expected refusals, equal set summaries/current-safe health, independently
reproduced marker/sum/RMS/DC/five-section crest and 64x pulse-sinc checks. The
review confirms that the tone is Fs/4, not near Nyquist, and requires no additional
experiment for this bounded scope.
No unresolved acquisition/public-dispatch blocker remains for
the measured bounded take; broader calibration, human approval and certified
delivery remain outside these claims.
