# Feature 4 — dynamics and impact: physical/public validation

## Scope and retained evidence (2026-10-09)

Real Live 12.4.6/Windows experiments passed all five measurement clauses:
transient strength observations, attack/body/tail relationships, crest,
processing-associated envelope modulation, and before/after compression/limiting
contrasts. These are qualified **same-source experiments**, not human punch
approval or a current `live_audio_assess` acquisition certificate.

Evidence root:
`C:\Users\Linus V2\.ableton-live-mcp\audio_dynamics_validation\6b612a6edaec4a56a9058913424f3c51`

- `fixture.json`: initial transport, source identities and original set snapshot.
- `inspect.json`, `configure.json`: actual device parameters and observed strings.
- `capture.json`, `capture_carrier.json`: full native manifests, stable routing
  profiles, process-bound PDC settings, receiver routes, runtime and cleanup.
- `capture/b1fb29b2931c4414be7135e4c0a04fb4/manifest.json`: percussion take.
- `capture_carrier/d2772a266ef64ab38aebfe5c9abd3389/manifest.json`: sustained take.
- `percussive_alignment_measured.json`, `carrier_alignment_measured.json`:
  original/capture SHA256, marker frame recovery, fitted gains/residuals and
  adjacent-lag correlation. Both original inputs and all acquisition WAVs remain.
- `percussive_public_requests.json`, `carrier_public_requests.json`: exact
  initialize, tools/list and tools/call requests sent through fresh `python -m
  server` stdio processes. Corresponding `_public_responses.json` and
  `_reports.json` retain full responses. Eight paired calls passed.
- `percussive_independent_numbers.json`, `carrier_independent_numbers.json`:
  independently computed NumPy crest/regional energy/contrasts/modulation.
- `cleanup.json`, `verify_restore.json`: owned-only removal and asserted final
  original identities, selection and stopped-position restoration.

## Actual Live setup and physical timing evidence

The initial nonblank Ableton-only screenshot
`C:\Users\Linus V2\.ableton-live-mcp\ableton_window_1791567500594.png`
showed an unsaved Untitled set, one empty MIDI track, five existing returns and
no modal. `.venv\Scripts\ableton-live-mcp-validate.exe --timeout 3
--strict-timeout` reported `runtime_current:true`, `live_mutations_safe:true`,
current installed Remote Script and current companion hosts. The system Python
environment initially lacked package/visual dependencies; all actual experiments
used the existing `.venv`. No restart/reload/discard was needed.

Five owned audio tracks played the **same file**, unwarped/unlooped at Arrangement
beat zero, centered, zero sends, with native Post Mixer receiver recording in one
simultaneous pass. Baseline and processor tracks were unity; gain control was
-4 dB. Existing tracks/returns/Main were not modified. Receiver outputs were
Sends Only, all sends zero and monitor Off. Master was not an analysis target;
these duplicate experimental paths are not disjoint stems to sum.

Source: deterministic stereo-identical 180 Hz decaying bursts with short noise
attacks every 0.5 s from 2–9.5 s; 2048-sample independent pseudorandom markers at
0.5 and 10.5 s, far below processing thresholds. Second source additionally
contains a sustained 0.025-amplitude 601 Hz carrier over 2–10 s. Both captures
are 44.1 kHz stereo PCM24. Percussion files contain 594688 frames/13.484989 s;
carrier files contain 594432 frames/13.479184 s. Within each simultaneous take,
all five paired paths have equal lengths; between-take lengths are not treated
as alignment evidence. Peak < unity in every
retained source/contribution; no acquisition clipping was used as evidence.

For **both takes and all five paths**, marker correlation recovered source frame
22050 at file frame 22050 and source frame 463050 at file frame 463050. Relative
integer offset is therefore zero, checked before and after the musical passage,
not inferred from equal lengths. At the initial marker the four unity paths are
identical within PCM24 quantization (maximum residual approximately 6e-8);
gain-only marker gain is approximately 0.630957. Exact-lag correlations exceed
adjacent +/-1-sample values by roughly 20–27 times. The long-release final marker
is still attenuated by compressor release; its measured gain/residual are
retained instead of normalizing away that creative recovery. No waveform shifting
or resampling was performed. This establishes discrete relative alignment for
these pinned same-clock captures; it is not a universal latency certificate,
sample-exact onset detector, true-peak measurement or proof for future routing.

Native manifests remain `alignment.verified:false`: the acquisition wrapper
does not manufacture qualification. Public paired requests reference the
separately measured marker evidence, not the removed historical calibration rig.
For the carrier test, identical frame slices `[88200:441000]` from every raw
recording were written as float64 WAVs with no gain/resampling. Their common time
zero is raw file second 2; both raw files and exact slice recipe remain.

Actual settings (observed labels, not assumed normalized parameter semantics):

| Path | Observed settings |
|---|---|
| Compressor | Threshold -16.0 dB; 20:1; attack 0.01 ms; release 127 ms; Peak; 0 dB knee; makeup off; sidechain EQ off; 100% wet; lookahead 0 ms |
| Limiter | Ceiling -14 dB; input 0 dB; release 100 ms; Standard; lookahead 1.5 ms; auto off |
| Long release | Threshold -20.6 dB; 20:1; attack 0.01 ms; release 742 ms; Peak; 0 dB knee; makeup off; sidechain EQ off; 100% wet; lookahead 0 ms |
| Gain-only | No devices; Post Mixer attenuation -4 dB |

Live PDC enabled and Reduced Latency When Monitoring disabled were retained from
the process-bound menu evidence. Before/end routing hashes matched on both takes.
Unexposed SDK latency/track-delay fields remain unknown; marker timing, not null
SDK fields, supplies alignment evidence. Calls were strictly sequential.

## Numerical acceptance

Explicit events define attack 0–20 ms, body 20–100 ms and tail 100–300 ms at each
source onset. Those operational regions are disclosed, not universal perceptual
definitions. Original whole baseline: -20.159 LUFS, -25.262 RMS dBFS,
-0.803 sample-peak dBFS, 24.459 dB crest. After-minus-before results:

| Percussion path | Whole crest delta dB | First-event attack/body RMS contrast delta dB | First-event tail/body contrast delta dB | Whole LUFS-match peak delta dB |
|---|---:|---:|---:|---:|
| Compressor | -2.370 | -2.593 | +6.197 | -1.421 |
| Limiter | -3.049 | -4.690 | +5.460 | -2.100 |
| Long release | -0.816 | -0.191 | +2.656 | -0.351 |
| Gain-only | 0.000 | 0.000 | 0.000 | 0.000 |

Compressor peak fell -14.010 dB and Limiter peak -13.038 dB in original levels.
Their matched first-event attack RMS changes were -0.251/-0.973 dB; body changes
+2.342/+3.717 dB. Thus lower peak/attack prominence remains after mathematical
LUFS matching; this is not merely a quieter signal. Tail contrast changes retain
real processor release behavior. Gain-only changed RMS/peak/LUFS exactly -4.000
dB and returned matched zero differences, unchanged crest and regional contrasts.
No file gain was applied by analysis. This negative control prevents treating a
simple level change as dynamics improvement; it does not constitute listener
approval of the processed versions.

Sustained carrier interval: 800 contiguous full 10 ms cells, all measurable;
8.000 s coverage with 0.125 Hz frequency resolution. Long-release comparison's
after-minus-before log-RMS level-change envelope has dominant **2.000 Hz**,
**2.885 dB** peak Fourier-component amplitude and **2.591 dB** standard deviation.
The source itself has intentional 2 Hz bursts, so source envelope periodicity
alone is not diagnosed as pumping. The aligned difference and actual long-release
experiment establish processing-associated cyclical envelope change. Compressor
and Limiter difference component amplitudes were 3.879/2.773 dB at 2 Hz.
Gain-only difference variation rounds to 0.000 dB and its final reported frequency
is null (`no_measurable_variation`). A real acquisition exposed tiny PCM
quantization residue; the corrected backend requires amplitude/variation to reach
the declared 0.0005 dB reporting floor rather than inventing a frequency. Final
eight public paired calls were rerun successfully after that correction.

Independent checks use sample-domain mean channel power, direct 20 ms regional
energy, `20*log10(peak/RMS)`, and a separately implemented Hann rFFT of 800 log-RMS
differences. Assertions match production crest and first attack/body contrast
within 0.001 dB, verify compression/limiting crest reductions and gain invariance.
They do not import production measurement helpers.

## Cleanup and remaining gates

Both native acquisitions report complete/cleanup complete and stable profiles;
all ten owned receivers were removed by the capture helper. The five named
validation sources were then removed by retained object identity only.
`verify_restore.json` confirms original MIDI/return/Main IDs/names, selected
E-Delay, stopped transport, original beat **1.094240395021645**, 174 BPM, original
loop false and all recording/automation-writing flags false. The immediate
cleanup response temporarily reported beat zero; a subsequent snapshot verified
actual settled restoration rather than accepting the lagging response.

## Local implementation and deployment gates

The implementation owner ran `.venv\Scripts\python.exe -m pytest -q` with
permitted explicit basetemp `C:\Users\LINUSV~1\AppData\Local\Temp\opencode\dynamics-final-full`:
**569 tests passed in 100.38 seconds** after the final reporting-floor fix.
The targeted dynamics + compact-schema guard run passed **11 tests**; dynamics
and tonal tests together previously passed **20 tests** after coverage fixes.
The ten dynamics tests cover analytic crest and pulse duty-cycle energy,
channel-power stereo/DC/above-unity handling, direct event energy and contrasts,
limiter and gain-only comparisons, known 2 Hz modulation, PCM24 quantization
residue, silence/floors/partial cells, candidate caps and shared boundaries,
offsets/fractional sections, request-work guards and real public MCP dispatch
with a bridge stub refusing any Live call.

Independent code review found and verified fixes for crossing-cell omissions,
contiguous-run modulation coverage, explicit partial-cell evidence and floor-limited
paired ratios. Physical validation additionally exposed and verified fixes for
NumPy-bool JSON serialization and quantization-residue modulation frequencies.
The public tools/list payload is 31,003 bytes including the new schema; its bounded
compactness regression allowance is now 32,000 bytes. No unrelated schemas were
expanded. Deployment succeeded using `uv pip install --python .venv\Scripts\python.exe
-e ".[audio-analysis]"`; this virtualenv has no `pip` module, so uv performed the
same editable installation. Fresh public stdio processes loaded the new schema.

`AUDIO_DYNAMICS_PONYTAIL_REVIEW.md` records final simplicity acceptance with no
required cuts. `AUDIO_DYNAMICS_REVIEW.md` records the final independent **PASS**
for all five scoped measurement goals and the retained physical experiment:
eight fresh paired stdio calls, source/ten-acquisition-WAV hashes, direct zero-lag
marker checks, independently derived crest/event energy and a non-FFT 2 Hz
carrier oracle passed. Historical evidence remains valid offline after owned-rig
removal; it cannot qualify future captures with changed profiles or establish
human listening approval.
