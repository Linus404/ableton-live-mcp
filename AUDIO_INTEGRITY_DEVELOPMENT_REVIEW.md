# Independent review — goals 7 and 8

Reviewed 2026-10-10 against `AUDIO_UNDERSTANDING_GOALS.md`, the shared remaining-feature plan, both individual plans, implementation/tests, and `AUDIO_REMAINING_FEATURES_VALIDATION.md`.

## Verdict

**Pass for the bounded, offline integrity and section-development contracts. No unresolved correctness or scientific blocker found.** This is not certified true-peak compliance, a general capture qualification, causal attribution, human listening approval, or an autonomous keep/revert verdict.

The sole concrete completeness finding was development discarding onset-candidate truncation/region outcomes from its reused dynamics result. The owner fixed it with bounded per-section candidate summaries; independent end-of-file transient checks confirm the truncation is retained. Unknown nested alignment/provenance keys now fail closed locally.

## Code and numerical acceptance

- Integrity distinguishes sample peaks from its explicit 4x, 81-tap Kaiser finite-FIR estimate, retains zero-extension/boundary/near-Nyquist limitations, and uses real surrounding samples for interior sections. It never claims a verified continuous-wave maximum.
- Subtype-aware PCM rails, repeated rail runs and float unity observations remain possible-clipping evidence. DC, timed all-channel silence and discontinuity candidates retain original measurements and unknown intent. Explicit delivery constraints concern the exact identified file; absent constraints introduce no defaults.
- Development retains sample-rounded section times, original LUFS/RMS/crest and tonal coverage. Temporal density is a disclosed nonexhaustive acoustic-candidate proxy; capped rates become unavailable. Broad-band entropy is spectral spread, not note/source count. Expected departures require explicit brief/expectation; original intentional contrasts are not arrangement faults.
- Nested balance pins the programme to the source path and zero programme offset, requires declared aligned disjoint actual in-mix contributions, and retains the reused balance/listener evidence. Missing balance remains unavailable. Combined dynamics/tonal and conservative nested-balance sample-work reservations occur before analysis decode.
- Independently ran `python -m pytest tests/test_audio_integrity.py tests/test_audio_development.py -q --basetemp "C:\Users\LINUSV~1\AppData\Local\Temp\opencode\review-integrity-development"`: **11 passed**. The first default-temp run failed at fixture setup due to Windows temporary-directory ACLs, not analysis assertions.
- Independent synthetic public-function oracles (no production DSP helper used to calculate expectations): Fs/4 phase-pi/4 sine amplitude 0.9 gives analytic sample peak -3.925450 dBFS and continuous peak -0.915150 dB; reported sample -3.925 and interior estimate -0.900. The whole-file estimate -0.800 includes disclosed finite-boundary ringing and is not substituted for the interior oracle. A same-sine 2x gain gives analytic +6.020600 dB, reported RMS +6.020/LUFS +6.021 and within explicit tolerance. PCM_U8/16/24/32 positive/negative rail counts, exact DC 0.125, retained final-transient truncation and finite JSON also passed.

## Retained actual-audio and public-dispatch review

Evidence root:

`C:\Users\Linus V2\.ableton-live-mcp\audio_remaining_validation\1361fde991d144fca61dc637abedf343`

Independently read the retained acquisition, physical oracle, fresh public request/response, standalone reports, source archives, and final health evidence; performed only offline reads/computation, no Live calls or production edits.

1. All **five original/native WAV SHA256 hashes** match `independent_physical.json`. All **eleven current source files and archived source copies** match `public_source_hashes.json`, including integrity hash `1029ed26948970e912c32a71cb24f7ad3a5b209bae3342d21d9e1c6e2724a4ef` and development hash `d61247b9d5ad50e631ea41d563c7d46789af287b50ad27e2289633b78f08a329`.
2. Recomputed all-frame native target + competitor minus programme: maximum absolute residual **1.1920928955078125e-7**, below the declared three-PCM24-quantum bound **3.5762786865234375e-7**. Independently checked all six beginning/end marker locations against original templates: exact integer lag wins over both neighboring lags, fitted gains within 1e-6 of unity.
3. Public responses **8/9 integrity and 10/11 development** are successful and exactly equal their standalone retained JSON reports. The two expected evidence refusals are retained JSON-RPC errors; before/after public set-summary results are exactly equal. Retained final health exits zero and contains `runtime_current:true` and `live_mutations_safe:true`.
4. Actual quarter-rate sine section reports sample **-16.990 dBFS**, 4x **-13.964 dBTP**, against analytic **-13.979400 dB**. Whole-file -13.864 is correctly treated separately as termination/interpolation evidence. This tone is Fs/4, not near Nyquist, and establishes no near-Nyquist accuracy guarantee.
5. Independently reconstructed the actual pulse with a **513-sample sinc sum at 64x fractional positions**: **-7.744324 dB**, versus reported 4x **-7.739 dBTP**, within 0.03 dB. Raw sample RMS/DC match both integrity reports, and all five programme-section RMS/crest match development within 0.001 dB. Actual recordings have zero PCM rail contacts; clipping-positive/float-over examples remain synthetic evidence only.
6. Nested-development balance includes both real retained disjoint contributions and explicit take-specific provenance; the no-balance request remains unavailable. Harmonic/beating RMS contrast meets the explicit zero +/-0.01 dB expectation. Density, spectrum omissions and region truncation remain visible rather than being promoted into exhaustive arrangement knowledge.

## Physical scope and limitations

The actual native PCM24 take used two unprocessed unity sources, zero sends and unprocessed unity Main. PDC was observed **off**, unchanged; the capture manifest remains unqualified with false alignment/sample-clock status and was not converted into a certificate or passed to `live_audio_assess`. Independent markers, sum and stable routing support the explicit historical offline declarations for this particular take. They do not qualify future captures, arbitrary devices/groups/returns, dynamic latency or continuous sub-sample delay. The original set restoration and current/safe final runtime are retained by the exclusive validator.

The ledger accurately separates synthetic rails, actual unclipped acquisition, exact-file delivery observations, finite interpolation estimates and assumed listening conditions. No unsupported musical causality, intended-defect classification, released-master identity, certified-meter claim or human approval was found. Additional physical experiments are unnecessary for the stated bounded contracts.
