# Independent review: multi-track audio capture

Reviewed `AUDIO_CAPTURE_PLAN.md`, `AUDIO_UNDERSTANDING_GOALS.md`, the tap patch/JS/builder, relevant bridge/server code and repository instructions. Review only; no Live operations or timing experiments performed.

**Verdict:** Reusing the existing tap is the right direction. Independent recorders and honest signal-point/timing labels are necessary. The plan postpones useful capture behind an unspecified synchronization architecture, while leaving Arrangement ownership and the actual mix measurement point underspecified.

## Ranked findings

### 1. Goal gap: end-of-device captures do not establish in-mix balance or the delivered master

- **Location:** First deliverable; Phase 1 steps 1–2/exit gate; Phase 3 manifest; goals lines 11–17 and 22–24.
- **Issue:** The plan correctly allows post-device/pre-mixer captures, but still presents these as the input for broad mixing/mastering assessment. The patch records `plugin~` directly into `sfrecord~ 2`, before the device's own `plugout~`. Neither JS nor bridge captures mixer output. Even an end-of-chain master tap does not, by placement alone, prove it captures the final master gain/output path. A master end tap also supplies no pre-mastering comparison.
- **Consequence:** Quiet/muted parts can be misread as prominent; master delivery level and automated balance can be mismeasured. A mixer snapshot cannot repair this, as the plan already acknowledges.
- **Smallest fix:** Keep pre-mixer track/group/return recordings, but explicitly limit their interpretation. In the signal-point experiment, establish the master tap's relationship to master fader/output and label it precisely. If it is not the final mix, record one verified final-mix path before advertising final-output measurements. Defer configurable pre/post processing taps until comparison work needs them.
- **Status:** Blocker for final-output/in-mix claims; not a blocker for honestly labelled source captures.

### 2. Correctness: seeking and playing do not guarantee Arrangement playback

- **Location:** First deliverable; Phase 3 sequence steps 1, 4 and 5.
- **Issue:** `_rpc_transport` only seeks through `jump_by` and calls start/continue/stop (`bridge.py:815–861`). It does not establish that Session clips are no longer overriding Arrangement tracks. The plan never explicitly addresses that state.
- **Consequence:** A successful eight-bar capture may contain Session material rather than the requested Arrangement passage. Restoring selection/loop settings does not restore displaced Session playback.
- **Smallest fix:** For the first tool, require Arrangement ownership and report a clear precondition failure if Session overrides are active. Add an explicit takeover/restoration policy later if needed. Guard Arrangement/Session recording and automation-writing states before seeking; UI changes do not authorize altering musical content.
- **Status:** Blocker for the stated Arrangement contract.

### 3. Feasibility: synchronization is an experiment, not an implemented design

- **Location:** Phase 1 steps 3–5 and exit gate; Phase 3 steps 4–5.
- **Issue:** “Shared audio-domain timing reference” does not yet identify its producer, Live beat/playing connection, per-recorder frame relationship, or behavior across compensation, start/stop, tempo automation and jumps. Merely recording the same clock on multiple files does not prove that the corresponding musical audio is aligned. The current JS has only a 100 ms polling task and a 500 ms delayed start (`agent_audio_tap.js:16–20,114–118`); these are not timing evidence.
- **Consequence:** The high-level tool is gated on an unspecified potentially substantial mechanism. Offline trimming cannot recover accurate beat boundaries without a demonstrated mapping. Conversely, requiring sample-perfect capture before any useful tool exceeds the immediate eight-bar recording goal.
- **Smallest fix:** Time-box a two-recorder timing spike and write down measured error, including a latency-bearing path. If only bounded approximate boundaries are established, ship that mode with extra leading/trailing recording and an explicit error bound; reject precision-dependent analysis. Retain sample-alignment work as an enhancement unless the measured error prevents useful capture. Do not substitute initial-BPM sleeps or JS arrival times for verified boundaries.
- **Status:** Blocker for accurate synchronized-boundary claims; sample perfection is a later enhancement.

### 4. Dependency order: the timing test itself first needs isolated recorders

- **Location:** Phase 1 before Phase 2; Phase 2 independent control.
- **Issue:** The existing builder injects one command-file path (`build_agent_audio_tap.py:29–40`), and polling dispatches the same command/path to every matching tap (`agent_audio_tap.js:24–50`). A shared start-with-path cannot safely produce independent files. The patch also retains `notein` → `sel 60 61` → start/stop and a shared status send, so separating command files alone is not full control isolation.
- **Consequence:** The prerequisite multi-tap test can collide on output paths. If MIDI reaches that branch, musical notes can start/stop capture outside the take lifecycle. Current status goes to a Max send, not a durable per-instance file, and discards the command ID before reporting.
- **Smallest fix:** Before the timing experiment, add only instance-specific command/status paths, unique IDs, two distinct outputs and matching acknowledgements. Disable the MIDI recording triggers for orchestrated taps; remove/disable UDP there if files are the chosen control path. Preserve legacy behavior only in the legacy device, rather than forcing it into the new capture path.
- **Status:** Blocker for multi-recorder testing and reliable take ownership.

### 5. Correctness: setup/reuse must verify the actual device and insertion point

- **Location:** Phase 1 step 1; Phase 2 wrapper reuse; Phase 3 step 2.
- **Issue:** Existing tap setup finds a device by the exact name `AgentAudioTap`, otherwise browser-loads it, and returns the device-name list (`bridge.py:444–489`). It neither checks end-of-chain placement nor identifies a tap runtime/instance. Frozen tracks and tracks with no audio output need explicit handling; “audio-capable” cannot be inferred from MIDI versus audio track naming.
- **Consequence:** Reuse can silently record before later effects, bind to a renamed/wrong device, or fail on a frozen track. Skipping those tracks without explanation would violate the advertised “all tracks” result.
- **Smallest fix:** Extend/reuse the existing insertion helper (`bridge.py:690–720`) with explicit end index and verify the resulting device ref/instance, position and enabled state. Inspect audio-output capability and frozen state; return per-track unsupported/failed outcomes. Do not unfreeze, flatten or rearrange musical devices automatically. Check capability failures before changing the set where practical.
- **Status:** Blocker for reliable target coverage; frozen-track support may be a documented limitation.

### 6. Semantics: pre-roll and tails need a defined transport policy

- **Location:** Phase 3 optional pre-roll/tail and sequence steps 4–5; Phase 4 tail validation.
- **Issue:** The plan does not say whether tails mean subsequent musical content during continued playback or decay after stopping the source, nor how capture at beat zero obtains pre-roll. Starting midway through a song cannot assume prior reverb, delay or instrument state is already established.
- **Consequence:** Recordings can be aligned yet misrepresent the passage's sound or contain next-section material advertised as a decay tail.
- **Smallest fix:** Initially define pre-roll as actual playback before the requested start, clamped to the song start, and extra post-roll as continued playback context. Label both separately; do not call post-roll an isolated decay. Document that this does not recreate arbitrary earlier device history. Add a distinct source-stop decay mode only when requested.
- **Status:** Required semantics for those options; optional tail modes can wait.

### 7. Reliability versus overengineering: keep concrete guarantees, reduce the protocol surface

- **Location:** Phase 2 acknowledgement fields/exit gate; Phase 3 retention/cleanup; Phase 4 test matrix.
- **Issue:** Durable command matching, stop cancelling delayed starts, file validation, bounded recording and safe partial-failure cleanup address actual defects. The present `stopRecording` does not cancel `startTask` (`agent_audio_tap.js:141–145`), and `isRecording` only reflects JS commands, not recorder confirmation. However, requiring acknowledgements for every lifecycle transition plus a general cleanup feature, full manifest inventory and broad regression matrix makes the first recording tool larger than needed. The current patch provides no recorder-completion feedback, so such feedback must be verified rather than presumed available.
- **Consequence:** A large state machine can delay the eight-bar milestone without proving recording readiness or closed valid audio. Conversely, cutting the real cancellation/timeout safeguards leaves runaway or misleading captures.
- **Smallest fix:** Use one active take per instance, acknowledged arm/start/stop/status commands, a local maximum duration, and an explicit incomplete result. Verify recorder readiness by a supported mechanism/experiment; verify final WAV structure and expected data after stop. Keep a small manifest: source ref, signal point, interval/error, WAV format/frames/path and outcome. Track owned devices/files and roll back only setup changes known to have succeeded. Defer a public cleanup tool, additional diagnostic fields and exhaustive lifecycle tests until those needs arise.
- **Status:** Core safeguards are required; the general lifecycle/management surface is later work.

## Simplified implementation order

1. **Isolate two taps:** reuse the builder and recorder; distinct paths/IDs, durable acknowledgements, disable incidental triggers, cancel delayed starts, bounded stop and verified WAV completion. One focused local test checks isolation and stop-before-delayed-start.
2. **Run the disposable-set spike:** identify track/return/master signal points; record two identical impulse paths plus one latency-bearing path. Establish a usable beat-to-frame mapping and report measured uncertainty, without promising compensation behavior in advance.
3. **Deliver the smallest eight-bar tool:** Arrangement precondition, explicit beats, enumerate regular/group/return/master targets, preflight unsupported tracks, sequential install/reuse, preserve routing/mutes/solos, one playback pass, stop/finalize, compact manifest with per-target outcomes. Verify success and one partial failure.
4. **Validate in Live under repository rules:** authorization for disposable-set work/reloads, current runtime, sequential bridge calls, sanity-check the measurement path and verify taps do not alter pass-through. No local test alone proves timing or signal-point semantics.
5. **Extend only from evidence:** tempo/meter edge cases beyond the tested contract, better synchronization, final-output/pre-master paths as needed, richer retention/cleanup and larger-set stress tests. Then add analysis; do not treat capture as completion of the audio-understanding goal.

Keep the plan's strongest choices: no soloing/routing rewrite, no fader-snapshot reconstruction, no waveform alignment that erases intentional delays, no blind retry after sent-call timeout, and no new generated-device host.
