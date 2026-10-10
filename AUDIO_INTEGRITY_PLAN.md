# Goal 7 — Technical integrity

Authoritative goal: true peaks, clipping, DC offset, unintended silence, clicks,
abrupt edits, and final-file delivery measurements on identified real audio.

## Public contract proposed for approval

`audio_integrity.analyze_integrity(args)` / MCP `live_audio_integrity` (offline).
Required `source: {name,path,signal_path}`; optional `sections` with unique
`{name,start_seconds,end_seconds}` in file-relative seconds (maximum 32).
Optional `silence_threshold_dbfs` (-120 to -20, default -90),
`min_silence_seconds` (0.001–600, default 0.1), and
`discontinuity_threshold` (linear full-scale adjacent-sample difference,
0.01–2, default 0.5). Optional `delivery` requires `description` and accepts
`sample_rate`, `channels`, `subtype`, `max_true_peak_dbtp`,
`integrated_lufs_min`, `integrated_lufs_max`, `max_abs_dc`.
Delivery requirements are explicitly caller supplied; no default compliance target.

## Evidence and acceptance

- Retain WAV format, original sample peak/RMS/integrated BS.1770 LUFS and
  per-channel mean DC. Measure whole file and requested sections independently.
- Estimate intersample/true peak with explicit 4x polyphase FIR interpolation,
  zero extension and finite-filter limitations. Report estimated dBTP, sample
  peak, per-channel peak times, and distinction from certified BS.1770 true-peak
  conformance. Never label the estimator a guaranteed continuous-wave maximum.
- Count PCM rail contacts (subtype-aware positive LSB) separately from float
  samples at/above unity and sustained repeated near-rail runs. These are
  possible clipping observations, not proof of processing history.
- Report contiguous all-channel below-threshold intervals, including leading
  and trailing silence, threshold and minimum duration. Intent is unknown;
  never declare silence unintended automatically.
- Report localized adjacent-sample jump candidates, including beginning/end
  zero-extension boundary jumps. Identify click/edit candidates without
  declaring intentional percussion, square waves or transients defective.
- Bound interval/candidate output to 120 entries with total/omitted counts.
- Compare final-file metadata, estimated true peak, integrated LUFS and DC
  against only declared requirements. Preserve unavailable measurement outcomes
  and distinguish estimated checks from final delivery certification. Caller
  signal path is provenance, not proof the WAV is the released master.
- Mono/stereo WAV, 8–192 kHz, <=128 MiB, <=600 s, <=12M scalar samples;
  reserve <=96M sample-work before decode including 4x interpolation and
  overlapping sections. Reject nonfinite samples, malformed/unknown fields,
  resource excess and metadata/decoder disagreement.
- Reuse existing optional NumPy/SciPy/soundfile/pyloudnorm backend and WAV,
  level/validation helpers; no Live calls, writes, new dependency or capture rig.

Independent checks: analytic phase-shifted sine intersample peaks, positive and
negative PCM rails, float over-unity, known DC, exact silence intervals,
single impulse/edit candidates and intentional-transient interpretation,
caller delivery bounds and unavailable short/silent loudness, overlapping-section
budget rejection, nonfinite/unknown fields, strict JSON serialization.

Not inferred: human approval, edit keep/revert, source attribution beyond supplied
signal path, standardized true-peak compliance, dithering history, lossy-codec
overshoot, LUFS matching applied to integrity checks, or acquisition qualification.

## Implementation evidence

Implemented approved contract in `src/audio_integrity.py`, including lightweight
`tool_properties()` and `TOOL_REQUIRED`. Section FIR interpolation includes up
to 10 real neighboring frames, so section cuts do not introduce artificial
zero-extension discontinuities. File boundary context remains explicitly
unverified; shorter-than-20-frame files return a null supported interior interval.

`tests/test_audio_integrity.py`: six focused checks passed with
`python -m pytest tests/test_audio_integrity.py -q --basetemp="C:\Users\LINUSV~1\AppData\Local\Temp\opencode\integrity-owner-tests"`.
The normal pytest temp directory produced an OS permission error before tests;
the approved opencode temp parent resolved that environment blocker.
Numerical/physical limits remain as above; independent review and aggregate
repository verification are tracked by their designated owners.
