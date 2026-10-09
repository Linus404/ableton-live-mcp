Ever wanted to control Ableton with just your voice? Me too! I made this MCP server so I could just ask Codex to do anything in Ableton Live for me, while I was nap-trapped by my baby.

Unlike other Ableton MCPs I tried, this one can do pretty much anything that is possible via Ableton's Object model; the agent can just eval arbitrary python that runs inside Ableton. It also has some tools defined for common tasks so those work faster and more reliably. I had Codex CLI optimize this for hours with the new `/goal` command to prioritize low end-to-end latency, high reliability, low token usage, while maintaining full flexibility.

Things you can use it for: create MIDI clips, insert audio files, general Ableton questions (with this, your agent can see your whole live set), add tracks with different devices and effects, analyze harmony, analyze audio signals at any point in the signal chain, generate spectrograms, clip automation, setting up mastering or vocal processing chains, insert MIDI the agent finds from the web... it's very general purpose, I'm not sure what the limits are.

## How to setup

Just tell your AI agent (Codex, Claude Code, Cursor, Copilot, Gemini, etc.) to:

`Set up the https://github.com/bschoepke/ableton-live-mcp MCP server for me`

It should work on Mac and Windows with recent Ableton versions, but I have only tested it on Ableton Live Suite 12.3.8 on macOS Tahoe.

Back up your Live Set before using this. The MCP can edit your set directly and could corrupt it.

## How to update

`git pull` this repo or ask your agent to:

`Update the https://github.com/bschoepke/ableton-live-mcp MCP server for me`

## Demos
Here are a couple examples of live sets made from scratch with Codex in just a few minutes, along with their prompts. After it makes something, you can ask for follow up changes.

[![Ableton Live MCP demo](https://img.youtube.com/vi/8dRRrIY7NI0/maxresdefault.jpg)](https://youtu.be/8dRRrIY7NI0)

https://www.youtube.com/watch?v=8dRRrIY7NI0

The chat messages I sent to Codex to make this:

_in ableton, make a self reflective song, with audio vocals (via macos say) and chip tunes and 80's drum machines. should be a real edm banger_

Follow up prompts:

_i want midi for everything but vocals please, with ableton devices. not prerendered audio for instruments_

_needs some fills_

_and should hit way harder after "3-2-1 i become the sound"_

_the vocals are squished too much (read too quickly), give them a little more length_

_add some dynamics, the song is basically one volume. and some pumping side chain_

_improve dynamics of the clap, seems a bit flat and indistinguished, want it harder after the 3-2-1 drop_

_introduce a new element on a new track after the 3-2-1 drop, that comes in but then recedes before the final exit_

_doesn't seem like the new thing has any notes_

_the element is a bit muddy/indistinct. perhaps it needs simplification and more space, different instrument choice, i dunno_

[![Ableton Live MCP piano demo](https://img.youtube.com/vi/cLCHEV1jWQo/maxresdefault.jpg)](https://youtu.be/cLCHEV1jWQo)
https://youtu.be/cLCHEV1jWQo

Prompt used to make this:

_In Ableton, make a piano duet that tells the story of people debating the positive and negative merits of AI. The composition should be both beautiful and dynamic but surprising and fresh. Use Keyscape devices._

## Built in Agent Audio Tap Max for Live device
The MCP includes an "Agent Audio Tap" Max for Live device that enables the agent to capture audio signals at any part of the signal processing chain. This gives the agent a full feedback loop for mixing and mastering tasks: it can capture audio signals for further processing with custom python, then tweak your Ableton devices, and then repeat.

Example usage where I asked Codex to generate a spectrogram of two piano tracks I had:
<img width="3768" height="1028" alt="piano_tracks_first10_spectrograms" src="https://github.com/user-attachments/assets/6d2b6d9f-9a2c-4552-aa6c-91153de9df44" />

### Real-time multi-track passage capture

`live_audio_capture` records audio-capable tracks, groups, returns, and the master
in one Arrangement playback pass using independently controlled Max for Live taps.
For eight bars from 1.1.1 in 4/4, use:

```json
{"start_beat": 0, "length_beats": 32}
```

Times are quarter-note beats, not bar numbers. Optional `pre_roll_beats` plays
earlier context, clamped to beat zero; `post_roll_beats` continues playback beyond
the passage and is not an isolated effect-decay tail. Neither recreates arbitrary
earlier instrument or effect history. The tool follows observed transport beats
rather than estimating duration from the initial tempo.

The result identifies retained local WAV files and a manifest, including failed
or unsupported targets. Frozen tracks are unsupported; MIDI-only tracks without
audio output are skipped. Max for Live and current installed/running Remote Script
code are required. Active recording, automation writing, or Session overrides
block capture. Playback stops after capture; loop and track selection are restored
where possible. Tap devices remain in the set for reuse. Routing, solos, mutes,
and musical clips are preserved.

**Measurement limits:** files are raw, untrimmed recorder captures. Command
acknowledgements do not establish audio readiness or sample timestamps. Boundaries
and inter-file alignment are uncalibrated; do not use these files for
precision-dependent comparisons. An end-of-device-chain tap measures that signal
point, not a proven post-mixer contribution or final master output. Groups,
returns, and master overlap upstream paths and must not be summed as independent
stems. Mixer automation cannot be reconstructed from a settings snapshot.

In the Live 12.4.6 disposable-set check, source taps retained signal with their
track faders at zero or tracks muted, and the master tap retained signal with the
master fader at zero. These recordings must not be treated as final-output stems.
See `AUDIO_CAPTURE_IMPLEMENTATION.md` for measured evidence and timing limitations.

Local regression tests do not establish Live recording, headroom, pass-through,
or timing accuracy. Those require a current-runtime Live experiment with known
sources and latency-bearing paths before stronger measurement claims.

### Loudness and balance evidence

Install the optional numerical analysis backend:

```sh
python -m pip install -e ".[audio-analysis]"
```

`live_audio_analyze` analyzes an existing mono/stereo WAV or the manifest returned
by `live_audio_capture`, without contacting or changing Live:

```json
{"manifest_path": "<capture result's manifest_path>"}
```

For a standalone WAV, named sections use **file-relative seconds**:

```json
{"path": "C:/audio/mix.wav", "sections": [{"name": "verse", "start_seconds": 0, "end_seconds": 16}, {"name": "chorus", "start_seconds": 16, "end_seconds": 32}]}
```

The compact report contains gated integrated LUFS for each file and section,
ungated trailing 400 ms momentary and 3 s short-term LUFS, unweighted RMS dBFS,
sample peaks dBFS, and descriptive local level changes with timestamps. Silence
and unavailable measurements are JSON `null` with status/conditions. No universal
loudness target or musical-quality score is imposed. Loudness range (LRA) and
true peak are not implemented.

Integrated loudness uses complete overlapping 400 ms blocks with 100 ms hops;
any incomplete final gating block is excluded. RMS, sample peak, duration, and
local windows retain the original file or section interval.

Exactly one of `path` or `manifest_path` is required. Optional
`window_step_seconds` controls local sampling; at most 120 windows are returned
per file. Limits are 32 sections, 64 manifest entries, 600 seconds and 12 million
scalar samples per file, and 96 million scalar samples per request. At 48 kHz
stereo the per-file sample bound permits 125 seconds. Longer audio must be
supplied as shorter files. Failed/incomplete/unsupported entries remain explicit.

These are **signal-point level measurements**, not proof of perceived prominence
or masking. Raw capture files have uncalibrated starts and stops; the analyzer
preserves that provenance and does not invent synchronized part-to-master
comparisons or map file times to Arrangement sections. Analyze known, aligned
rendered passages separately when assessing their measured levels; pre-mixer
tap values cannot establish actual fader balance. Captured groups, returns, and
master paths are never summed.

### Audibility and masking evidence

`live_audio_masking` compares a target with 1–8 competing **aligned, disjoint
in-mix contributions**. It runs offline with the same `audio-analysis` extra.
Supply explicit alignment evidence and signal-path provenance:

```json
{
  "target": {"name": "lead", "path": "C:/audio/lead.wav"},
  "competitors": [{"name": "pad", "path": "C:/audio/pad.wav"}],
  "alignment": {"verified": true, "source": "Same-start aligned rendered contributions; latency compensated", "uncertainty_samples": 0},
  "provenance": {"disjoint_contributions": true, "in_mix_levels": true, "signal_path": "Post-fader contributions at their actual mix gains, before shared bus processing"},
  "window_seconds": 0.1,
  "listening_condition": {"kind": "assumed", "db_spl_at_0_dbfs_rms": 100, "source": "Example monitor-level assumption, not measured calibration"}
}
```

Those declarations must describe actual evidence; they do not make recordings
aligned or turn pre-mixer taps into in-mix contributions. Raw
`live_audio_capture` files do **not** currently satisfy this contract. Do not
include a source alongside its containing group/master path, double-count shared
returns, or use isolated loudness to claim audibility. The tool does not verify
caller assertions or automatically resample, cross-correlate, or align files.

Files must have identical sample rate and mono/stereo layout. Equal frame counts
are required unless `alignment.offsets_samples` maps **every source name** to the
file frame corresponding to common time zero. With offsets, analysis covers the
shortest common remaining interval; outside audio is excluded. Optional source
`gain_db` (−60 to +60) describes an explicit counterfactual, not an automatically
loudness-matched comparison.

The report retains auditory roex-filter powers and the descriptive excitation
competition proxy. With `listening_condition`, it also estimates masking using
an MPEG-1 Psychoacoustic Model 1 adaptation: tonal/noise masker classification,
Bark spreading, absolute hearing threshold and target threshold margins. The SPL
reference is measured (`calibrated`) or explicitly `assumed`, with evidence in
`source`. Threshold excess is a spectral prominence indicator, **not standardized
partial loudness or human listening approval**. Binaural/temporal masking,
correlation/interference and shared nonlinear bus processing are not modeled.

Windows are contiguous, 0.1–1 second, capped at 120 (`max_windows` may lower the
cap). The tool refuses excessive counts instead of silently sampling sparsely.
Final tails shorter than 100 ms are explicitly unmeasured. Other bounds are
120 seconds/file, 12 million scalar samples/file, 48 million/request, and
128 MiB/file. Follow report coverage and numerical-floor limitations; short
edge transients and quiet target detail may be underrepresented.

The report includes actual filter-center frequency coverage; centers do not
uniformly cover extreme bass or upper treble, and roex filters have tails rather
than hard band boundaries. A reported center is not an inferred source pitch or
spectral peak. `inactive_target_windows` counts modeled filter inactivity, not
literal WAV silence: Hann weighting can erase an impulse at a window endpoint.

### Programme/parts balance and qualified capture assessment

`live_audio_balance` accepts `programme: {name?,path}`, `parts: [{name,path,gain_db?}]`
(1–8), the same alignment/provenance contract, and explicit listening conditions.
It reports aligned integrated/local/section part-to-programme differences and
separate modeled prominence/masking. Programme is a reference, never another
competing contribution. `sections` use common file-relative seconds.
`expected_section_differences` specifies `from_section`, `to_section`,
`expected_delta_lu`, and `tolerance_lu`; only deviations from declared musical
expectations receive a judgment. `fair_loudness_match: {target_lufs}` reports
isolated comparison gain/peak implications without normalizing files or claiming
that a louder scenario is better. Original measurements are retained.

`live_audio_capture_in_mix` takes `start_beat`, `length_beats`, optional `track_refs`,
`return_refs` (existing return-track refs), returns/master switches, pre/post-roll,
`max_duration_seconds` and output directory. Omitting `return_refs` retains the
default selection of all returns when returns are enabled.
An empty list selects none; `return_refs` cannot be combined with
`include_returns: false` (omit the selector when disabling returns).
Selected return paths require measured role/routing-profile qualification; their timing is not inferred
from regular-track calibration or discovered by searching each musical take.
It records native Live clips on owned Post Mixer receivers and a separate Master
Resampling programme. Native acquisition WAV copies are retained unchanged; a
float64 interleaved derivative preserves their frames without gain/resampling.
This derivative is not acquisition clock evidence. Supported topology and cleanup failures stay explicit.
Experimental native qualification supports PCM24/PCM32 and float32/float64
recording preferences. PCM16 remains available for offline file analysis and
unqualified recording, but is explicitly unsupported for qualified capture and
manifest assessment; a PCM24 certificate must not be reused for PCM16.
Qualified PCM acquisition also rejects samples at either digital rail as possible
clipping: a clipped part and programme can falsely satisfy a linear sum check.
Finite floating-point samples above unity remain supported; the PCM rail guard
is not a universal 0 dBFS threshold for floating-point recording.
Start with stopped transport: capture plays one real-time passage, then restores
the original stopped position and insertion marker. Restoring ongoing playback
is unsupported until its distinct playback-cursor behavior is experimentally
qualified.
Physical qualification is required before treating files as aligned in-mix audio.

`live_audio_capture_in_mix_calibrate` runs repeatable physical calibration with
optional `output_directory`: it creates/removes owned calibration audio tracks
and temporarily plays audio, preserving existing music. It requires stopped
transport, no recording and no solos. A failed or unavailable qualification
remains explicit; it never becomes a certificate from caller declarations.

`live_audio_assess` accepts `manifest_path`, `listening_condition`, balance options
and optional `gains_db: {captured_part_name: gain_db}`. Offline assessment requires
complete files/cleanup, one programme plus 1–8 complete contributions, matching
finalized metadata, verified alignment/disjoint in-mix provenance and a valid
experimental qualification certificate. It refuses unsupported entries and legacy
raw taps. After full qualification, a default partition may retain excluded
nonterminal children only when the stable routing graph proves their actual
output route reaches a captured terminal group. Explicitly requested exclusions,
external/No Output paths, unknown routes and ambiguous group names are rejected;
all exclusion evidence remains in the report.
Unrequested MIDI-only control tracks may also remain explicit exclusions when
their pinned, unchanged routing profile proves `has_audio_output: false`.
Unknown capability and audio-capable silent/muted/frozen tracks are not covered
by this exception; an explicitly requested non-audio source is rejected.
Every stereo file must match its frame-for-frame channels in the retained
finalized interleaved derivative (or explicitly normalized copy); raw normalization
evidence remains in the report. Public calibration establishes applicable current-
profile qualification; matching frames or caller booleans do not qualify a capture.
The first two audio-understanding goals passed actual regular/group/return capture,
explicit/default assessment and independent acceptance review under the conditions
in `AUDIO_FEATURES_VALIDATION.md`. Changed routing/profiles require recalibration.
These tools reuse the `audio-analysis` extra.

### Tonal balance evidence

`live_audio_tonal` measures an identified mono/stereo WAV offline using the same
`audio-analysis` extra. It returns absolute/relative broad-band and octave power,
brightness (centroid/85% rolloff), prominent spectral peaks and their recurrence,
whole-passage, named-section and contiguous local-window evidence. It does not
prescribe a universal tonal curve or decide whether a sound is muddy or harsh.

```json
{
  "source": {"name": "mix", "path": "mix.wav", "signal_path": "Exported Main after processing; bars 9–17"},
  "reference": {"name": "reference", "path": "reference.wav", "signal_path": "Independent reference excerpt selected for similar instrumentation"},
  "sections": [{"name": "first_half", "start_seconds": 0, "end_seconds": 4}],
  "window_seconds": 1,
  "brief": {
    "description": "Keep bass weight, but avoid low-mid dominance relative to this selected reference",
    "band_expectations": [{"band": "low_mid", "min_relative_db": -30, "max_relative_db": -10}]
  }
}
```

`reference`, `sections`, `window_seconds` and `brief` are optional. Brief ranges
are caller-selected expectations in dB relative to covered 20 Hz–20 kHz power,
not recommended defaults. Bands: sub 20–60, bass 60–250, low_mid 250–500,
mid 500–2000, upper_mid 2000–6000 and high 6000–20000 Hz. Octave bands give
additional descriptive resolution. Read coverage before interpreting missing
energy: Nyquist-truncated bands are partial/unsupported. Reference comparisons
require identical covered normalization ranges and full coverage of each band.
Each band reports a measurement status. A below-numerical-floor band retains
null measured energy and a conservative relative-power upper bound; it can be
`below_brief` only when that bound is strictly below the stated minimum and
the target band has full coverage. Whole-file silence remains unavailable.
`complete`/`processing_complete` mean processing succeeded, not full spectral
passage coverage. Check `spectrum_coverage_complete`, incomplete reasons and
each spectrum's covered duration/omitted tail before interpreting end transients.

Reference comparison uses independent whole-passage normalized spectral shapes;
it needs no alignment assertion and does not compare corresponding musical times.
Original LUFS/RMS/sample peaks remain intact; the reference gain needed to match
source LUFS and predicted sample peak are reported without modifying audio.
For before/after work, supply musically corresponding rendered passages and retain
their acquisition/alignment evidence separately; this tool does not verify it.
Use qualified retained programme or part WAVs from `live_audio_capture_in_mix`
when appropriate, carrying their signal path into the source description. Raw
tap files remain isolated signal-point evidence and cannot establish source
contribution to the mix. See `AUDIO_TONAL_VALIDATION.md` for verification scope.

### Dynamics and impact evidence

`live_audio_dynamics` analyzes identified mono/stereo WAVs offline with the
`audio-analysis` extra. It reports original LUFS/RMS/sample peaks, pooled and
per-channel crest, attack/body/tail levels and energy, and log-RMS envelope
modulation. These are measurements, not a perceived punch score or pumping diagnosis.

```json
{
  "source": {"name": "before", "path": "before.wav", "signal_path": "Same-source baseline Post Mixer recording"},
  "comparison": {"name": "after", "path": "after.wav", "signal_path": "Same source through Compressor; recorded Post Mixer"},
  "alignment": {"verified": true, "source": "Retained measured sync-marker experiment; equal native-clock files", "uncertainty_samples": 0},
  "events": [{"name": "hit", "start_seconds": 1, "attack_end_seconds": 1.02, "body_end_seconds": 1.1, "end_seconds": 1.3}],
  "sections": [{"name": "passage", "start_seconds": 0, "end_seconds": 4}],
  "brief": {"description": "Preserve attack relative to body while controlling peaks"}
}
```

Only `source` is required. Paired processing comparisons require identical rates/
channel layouts and explicit zero-uncertainty alignment evidence. Different file
epochs/lengths need `alignment.offsets_samples` mapping both unique source names
to file frame indices at common time zero; only the common remaining interval is
analyzed. Equal lengths or caller declarations alone do not verify physical alignment.
Sections/events use common-time seconds in paired mode, file seconds otherwise.
Optional `window_seconds` sets contiguous reporting windows (0.01–600 seconds,
at most 120). Explicit events define musical attack/body/tail regions; omitted
events use disclosed 6 dB-rise candidates and 20/100/300 ms default boundaries.
Read candidate omissions/truncation: onset detection is not exhaustive.

Modulation estimates analyze contiguous runs of at least four seconds of complete
10 ms cells above the numerical floor, with timed run/omission coverage; silence
gaps and shorter runs are unavailable, not interpolated. Envelope summaries assign
every cell once by its start time, expose spans crossing reporting boundaries and
retain explicit final partial-cell RMS/peak evidence.
The final partial cell is retained in ordinary measurements but omitted from
modulation. Below-reporting-resolution modulation (<0.0005 dB) has no fabricated
frequency. Notes, tremolo and intentional ducking can resemble pumping.
Paired level-change envelopes are not literal gain reduction for nonlinear
processing. Before/after deltas retain original levels and separately predict
LUFS-matched levels/headroom; no files are rewritten. Matching is unavailable
when either integrated LUFS is unavailable. Sample peak is not true peak, DC
is retained, and lower crest alone does not establish lost musical impact.
See `AUDIO_DYNAMICS_VALIDATION.md` for the current verification ledger.

## Ideas

- Control your external synthesizers and other hardware with the MCP
- Ask it questions like "why does my mix sound muddy?" or "how do I sidechain my bass track?"
- Ask it to do things like "add a chord track that fits with my melody" or "give me a basic backing track for me to noodle on my guitar with"
- You can tell it use third party plugins (VSTs, audio units) like Serum and Keyscape
- Tell your agent to incorporate your existing vocal samples, including asking it to trim silence and transcribe your audio samples before creatively incorporating them into your live set
- Ask your agent to set up crazy user controlled DJ effects
- Experiment with VJ plugins like Videosync to make music videos driven by your live set
