---
id: ADR-0014
status: accepted
date: 2026-10-31
superseded_by: null
---
# ADR-0014: The model hears the backing vocals where the lead is silent

Adds to ADR-0002 (alignment on the separated vocals) and builds on ADR-0012 (voice activity).

## Context and problem

The acoustic model hears only the lead vocals. The separation sometimes puts sung words into the backing vocals, for example a word shouted by several voices; the lead is then silent there, the model cannot recognise the word, and its timing is estimated. On eleven benchmark songs and the demo song, 161 of 573 estimated words lie mostly in stretches where the lead is silent and the backing sounds (0 to 16 % of a song's frames). Some songs also have quiet lead lines under backing doubles, where swapping in the backing would overwrite words the model recognised in the lead (eight such words on one song).

## Considered options

1. **Lead and backing summed into one track** for the model.
2. **Two model passes, and per frame the backing's output where the lead is silent and the backing sounds.**
3. **Align again only the estimated stretches** on the backing afterwards.

## Decision

Option 2, with guards. The model runs on the lead and on the backing (each normalised on its own, the same frames). After a pass on the lead, a frame takes the backing's output only when the lead is silent there by the voice activity of the lead alone, the backing sounds, the lead's own output in that frame is blank, and the frame lies outside every confidently measured lead word. The alignment then runs on the mixed output; if no frame is swapped, or the lead's voice activity is not plausible, the lead alone is used as before. The setting `alignment.hear_backing` (on by default) switches it off.

- The lead stays untouched wherever it sings, so songs without words in the backing keep their result.
- Summing (option 1) mixes harmonies into every frame; aligning only the estimated stretches (option 3) misses words that the first pass forced into wrong places.
- The second model pass costs 2 to 4 s per song on the GPU.

## Consequences

- Words sung only in the backing can be measured with normal confidence and letter times; the voice placement (ADR-0012) and held ends (ADR-0013) apply to them unchanged.
- The worker runs the model twice and writes the backing's output and the loudness of lead and backing separately; the loudness of ADR-0012 stays as it is.
- The backing is normalised on its own and reaches the model a few dB louder than the lead; this is left untuned unless the benchmark shows harm.
- Lines sung at the same time with different words remain a matter of the duet layout.
