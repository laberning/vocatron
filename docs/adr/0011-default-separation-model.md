---
id: ADR-0011
status: accepted
date: 2026-10-29
superseded_by: null
---
# ADR-0011: Default separation model

Supersedes ADR-0002 in part: the vocals/instrumental model `model_bs_roformer_ep_317_sdr_12.9755` is no longer the default.

## Context and problem

ADR-0002 chose the BS-Roformer checkpoint ep_317 (published March 2024) for the vocals/instrumental split, from an A/B listening test in October 2026. Newer open checkpoints have appeared since. A two-stage comparison followed: objective scores against true instrumentals, then blind listening by the maintainer.

## Considered options

1. **Keep ep_317.**
2. **BS-Roformer Leap** by unwa (published June 2026, no licence stated).
3. **An ensemble** of two models (for example Leap with Leap Xe inst, fuller), or another single candidate (Leap Xe inst, Mel-Band deux, Mel-Band FlowersV10).

## Decision

Option 2. **Leap is the default vocals/instrumental model; ep_317 stays registered and selectable** with `separation.model`. The lead/backing split (anvuew karaoke model on the vocal stem) and its order are unchanged.

Evidence:

- **Measured** against true instrumentals on 20 songs (6 German songs with official instrumentals, 14 by Josh Woodward): Leap scores higher than ep_317 on every song (+0.29 dB SDR on average, +0.39 dB on the German songs), with less voice leftover (bleedless +2.0) and the same fullness.
- **Speed:** Leap separates the vocals 2.3× faster (0.22 against 0.51 s per second of audio); the whole separation stage takes about 0.56 instead of 0.86 s per second; peak VRAM 2.3 GiB.
- **Listening:** in a blind test the maintainer heard only a very small difference and preferred ep_317 in 18 of 22 judgements, probably for its slightly fuller treble (about 0.2 dB more energy above 8 kHz). Given how small the audible difference is, the maintainer chose the newer, objectively cleaner and faster model, and keeps ep_317 for anyone who prefers its sound.
- Ensembles and fuller models did not win: the fuller ensemble lost to Leap by ear (7 of 22), and the clean ensembles add only about 0.03 dB over Leap at two to three times the runtime. Running the karaoke model on the full mix made no audible difference.

## Consequences

- New songs are separated with Leap; songs already processed are separated again on the next run, because the model is part of the separation stage's fingerprint.
- `vocatron models download` fetches Leap for the default German set; ep_317 is downloaded only when chosen.
- The sync benchmark is re-run with Leap and its baseline renewed.
- Leap states no licence, like ep_317; it is downloaded at runtime and documented (ADR-0010).
