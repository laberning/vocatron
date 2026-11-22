---
id: ADR-0021
status: accepted
date: 2026-11-01
superseded_by: null
---
# ADR-0021: Uncertain words keep the model's position, and estimated words stay in their line

Supersedes ADR-0012 in part: where estimated words are placed. Voice detection, its plausibility rules, the voice source, the re-estimation of words in silence, the confidence limit, held ends (ADR-0013) and the backing pass (ADR-0014) stay as they are.

## Context and problem

A word whose confidence is below the limit is estimated: its time from the model is thrown away, and ADR-0012 places a run of estimated words from the first voice start in the gap. The model often hears short words in the right place but with low confidence. When the voice already sounds at the start of the gap, often still the held note of the previous line, the word then lights up up to 1.4 s too early. Estimated words at the end of one line and the start of the next form one run across the line break. Measured offline on 17 songs: line starts more than 0.5 s before the human line time fall from 14 to 5 when the model's position is kept and runs stay in their line, while starts within 0.2 s stay as they are.

## Considered options

1. **Keep the placement of ADR-0012.**
2. **Lower the confidence limit**, so more words count as measured.
3. **Keep the model's position of an uncertain word when the voice supports it, and never let a run of estimated words cross a line break.**

## Decision

Option 3.

- With the voice in use, an estimated word keeps the model's start when at least half of its span there is voiced, or when it ends right before the next confident word of its line. A line's first word counts as voiced only when its voice starts after the previous word; the held note of the previous line does not count, unless the model starts the word directly (within 0.1 s) after the previous word ends: then the voice that goes on is the word's own note, as in a sung vocalise that follows its line. A kept word stays estimated.
- With the voice in use, a run of estimated words never crosses a line break. A run that starts a line is placed backwards from the next word, at the last voice start that leaves room, or right before that word; a run that ends a line reaches forward only a short way.
- A word in silence that was estimated and whose voice placement fails goes back to the model's start, as before. Moving it to the voice at the end of its gap instead was tried; it changed one word on the 17 songs and the demo, and that word then started about a second after it is sung (the voice detection had missed its quiet singing).
- Without the voice, the placement is as before.
- Lowering the limit (option 2) would make wrong words count as measured in every song, with confidence and letter times they do not have.

## Consequences

- Short words at line starts no longer light up during the previous line's held note.
- Inside a line, nearly every uncertain word keeps the model's position. The sync benchmark judges line starts only, so this is checked by listening.
- The alignment report counts the kept words; the alignment stage raises its version and its file schema, so songs are aligned again.
