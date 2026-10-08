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

## Ideas

- Control your external synthesizers and other hardware with the MCP
- Ask it questions like "why does my mix sound muddy?" or "how do I sidechain my bass track?"
- Ask it to do things like "add a chord track that fits with my melody" or "give me a basic backing track for me to noodle on my guitar with"
- You can tell it use third party plugins (VSTs, audio units) like Serum and Keyscape
- Tell your agent to incorporate your existing vocal samples, including asking it to trim silence and transcribe your audio samples before creatively incorporating them into your live set
- Ask your agent to set up crazy user controlled DJ effects
- Experiment with VJ plugins like Videosync to make music videos driven by your live set
