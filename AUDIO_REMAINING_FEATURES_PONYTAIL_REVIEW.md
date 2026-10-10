# Ponytail review — remaining audio features 5–8

## Scope

Independent complexity-only review of the original goals, shared and four individual
plans, `audio_compatibility.py`, `audio_stereo.py`, `audio_integrity.py`,
`audio_development.py`, their focused tests, and shared MCP registration/docs/tests.
Required science, provenance, coverage, resource reservations and input gates are
preserved. Correctness and physical acceptance belong to their separate reviews.

## Ranked actionable findings

1. `src/audio_stereo.py:L9,L226–227` / `src/audio_masking.py:L15,L287`:
   **shrink:** duplicated 1024-frame Hann / 512-hop, final-edge-aligned Model-1
   power averaging. Replace both implementations with one private masking helper;
   retain stereo's short-window unavailable outcome and masking's existing
   short-window error. **Resolved:** masking owns the shared helper and stereo
   imports it; the reviewer verified both reference the same function object.
2. `tests/test_audio_compatibility.py`:
   **delete:** unused `copy` import. Replacement: nothing. **Resolved** by owner.

## Review evidence

- Compatibility delegates existing masking/provenance/alignment/model behavior;
  its streaming second pass supplies distinct direct timing and resolved partial
  evidence. Removing it would remove requested evidence.
- Stereo reuses existing perceptual estimates, band definitions and validators;
  direct mid/side spectra preserve cancellation precision.
- Integrity uses SciPy interpolation and existing level/WAV/region helpers;
  the small interval helper provides bounded required silence/rail-run evidence.
- Development composes existing dynamics, tonal and optional balance analysis;
  direct section contrasts and explicit expectations need no additional framework.
- Registration consumes module-owned lightweight schemas directly; focused
  numerical/adversarial tests and dependency-free discovery checks are purposeful.
- An independent offline check found the duplicate Model-1 implementation
  bit-identical for seeded stereo arrays of 1024, 1100 and 4800 frames, and verified
  the proposed helper returns null below 1024 frames.
- Independent focused verification: **64 passed** across all four feature test
  files using `.venv\\Scripts\\python.exe -m pytest` with an explicit writable
  `--basetemp`. The initial default-temp attempt had 63 fixture setup errors from
  Windows access denial; the corrected run passed. This is local numerical
  evidence, not Live/physical acceptance.

## Final verdict

**PASS — Lean already. Ship from the complexity perspective.** Both actionable
findings are resolved and rechecked. No additional actionable complexity cuts
found; no new dependency or shared schema/analysis framework is warranted.

net: -9 lines applied by these cuts (14 removed from stereo, 6 added net to
masking, 1 unused import removed); 0 further lines proposed.
