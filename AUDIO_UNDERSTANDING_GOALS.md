# Audio understanding for text-only music agents

## Goal

Enable a non-multimodal, text-only agent to assess recorded sound, understand how parts work together, and make evidence-based mixing and mastering decisions in Ableton Live. No audio AI model should be required.

The agent should receive meaningful descriptions and quantitative evidence about the actual audio, rather than infer sound from track names, device settings, or MIDI alone.

## What we want to understand

- **Loudness and balance:** how loud the programme, sections, and individual parts are; their perceived prominence within the mix; unexpected level changes.
- **Audibility and masking:** when a part is buried, which competing parts may obscure it, and where those interactions occur in time and frequency. Isolated loudness alone must not be treated as in-mix audibility.
- **Tonal balance:** low-end accumulation, missing or excessive frequency regions, resonances, brightness, and evidence consistent with muddiness or harshness.
- **Dynamics and impact:** transient strength, attack/body/tail relationships, crest factor, pumping, and changes in punch caused by compression or limiting.
- **Compatibility between sounds:** frequency competition, timing overlap, harmonic relationships, roughness, and whether important parts remain distinguishable together.
- **Stereo and translation:** frequency-dependent width, phase relationships, mono cancellation, and changes in important-part audibility when folded to mono.
- **Technical integrity:** true peaks, clipping, DC offset, unintended silence, clicks, abrupt edits, and final-file delivery measurements.
- **Musical development:** how balance, density, dynamics, and contrast change between sections, respecting intentional differences.

## Evidence and comparisons

- Findings must concern real audio from an identified signal path and musical passage, including individual tracks, groups, the full mix, and pre/post-mastering audio where relevant.
- Findings should identify affected times or musical sections and distinguish whole-track averages from local problems.
- Before/after and reference comparisons must support fair, aligned, loudness-matched assessment while retaining original-level measurements.
- The agent should be able to judge whether an edit improves the stated goal, what it compromises, and whether it should be retained or reverted.
- Suspected problems should be attributable to relevant sources or interactions where evidence permits, rather than only described at the master bus.
- Results should be compact, readable by a text model, and explicit about units, measurement conditions, uncertainty, and limitations.

## Quality expectations

- Use established signal-analysis and psychoacoustic research as the basis for meaningful evidence about perception.
- Separate measured facts, perceptual estimates, possible causes, and musical judgments.
- Do not treat spectral overlap as proof of masking, roughness as proof of bad sound, or louder as automatically better.
- Respect the user's musical brief, intended sound, and references rather than impose universal loudness, spectral, or dynamics targets.
- Do not claim a universal numerical score for musical quality or human listening approval.
- Preserve the user's music and Live state during assessment.

## Desired outcome

A text-only agent can explain what is happening in the audio, identify supported mix/mastering issues, assess interactions between parts, and verify whether its changes improve the track against the user's goals—all without an audio AI model.
