# Musical development (goal 8)

Goal: describe measured balance, density, dynamics and contrast between explicitly
named musical sections, retaining intentional differences and identified audio paths.

## Proposed public contract

`analyze_development(args)` / `live_audio_development` (offline only):

- Required `source: {name,path,signal_path}` and `sections` (2–32 unique
  `{name,start_seconds,end_seconds}` entries; file-relative seconds).
- Optional `brief: {description}` and `expected_contrasts` (at most 32 entries:
  `{from_section,to_section,metric,expected_delta,tolerance}`). Metrics initially
  `integrated_lufs`, `rms_dbfs`, `crest_factor_db`, `centroid_hz`, and
  `onset_candidates_per_second`, and `effective_occupied_band_count`; units reported per metric. Departures require
  both explicit intent and expectation. No inferred quality targets.
- Optional `balance` uses the existing `analyze_balance` contract, with programme
  required to identify the same source path and sections supplied by this wrapper.
  This retains declared aligned, disjoint in-mix contribution evidence and listener
  conditions; without it, actual part balance remains explicitly unavailable.

Reuse existing dynamics levels/crest/onset evidence and tonal section spectra;
compute adjacent-section contrasts from those outputs. Onset candidate rate is
an explicitly limited acoustic-event-density observation, never note density,
polyphony, arrangement complexity, or a loudness-derived density claim. Preserve
candidate omissions/truncations and do not report an exhaustive density when the
detector coverage is incomplete. Silence and insufficient spectra remain null.
Spectral density is exp(Shannon entropy) of the existing six broad-band energies,
normalized over covered bands after numerical-floor exclusion. It describes coarse
spectral spread, not sounds/notes; retain Nyquist coverage and Welch omissions.
Existing balance is included only when requested. Features 5–7 are independent
dimensions, not dependencies of this bounded section-development assessment.

## Acceptance

1. Original-level LUFS/RMS/crest and supported tonal evidence identify every
   requested section, signal path, duration and units.
2. Contrasts explicitly use later minus earlier; unavailable evidence stays null.
3. Expected contrasts classify measured departures only against caller intent;
   intentional variation never becomes an automatic mix/arrangement fault.
4. Density is supported by detector events and coverage, never inferred from
   amplitude or track names. Actual part balance requires existing in-mix evidence.
5. Reuse existing analysis limits; reject excessive sections, expectations,
   invalid bounds/numbers and unknown keys before processing. Bound combined work.
6. Synthetic checks cover gain contrast, event-rate contrast, silence, incomplete
   detector coverage, intent gates, malformed input and budget limits. No Live calls.
7. No arrangement-quality score, human approval, causality or keep/revert decision.

Nested balance pins the same programme path and zero programme offset to retain
file-relative section coordinates; part offsets may use the existing contract.
Combined work is reserved before decode under 96 million scalar sample-work units.

Parent approved this scope. Implemented with chronological nonoverlapping sections,
original-level part-balance contrasts, and a nested balance subset excluding gain
scenarios and separate expectations. Optional listener conditions retain the existing
balance model. Public schema exports are `tool_properties()` and `TOOL_REQUIRED`.
Focused verification: five tests passed using `python -m pytest
tests/test_audio_development.py -q --basetemp=<accessible temporary directory>`.
Default pytest temp directory was inaccessible on this Windows environment;
the explicit temporary directory resolved fixture setup without code changes.

Owned files: this plan,
`src/audio_development.py`, `tests/test_audio_development.py`.
