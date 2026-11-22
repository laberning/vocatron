---
id: ADR-0017
status: accepted
date: 2026-11-01
superseded_by: null
---
# ADR-0017: Short words are judged on their held length

Supersedes ADR-0013 in part: which length of a measured word the quality checks use to call it too short. Adds to ADR-0008 (quality report).

## Context and problem

ADR-0013 holds a measured word until its voice stops and lets the quality checks judge word lengths on the heard part, the time until the model last heard one of its letters. A word of one letter is heard on about one frame (20 ms), below the 60 ms limit for a too short word. In English such words are common ("I", "a"), so every measured English song had more than five words of odd length and was marked `review`; the demo song "Knock" had 27. German songs have few one-letter words and were hardly affected.

## Considered options

1. **Keep judging both limits on the heard part**, and accept that English songs need review.
2. **Lower the short limit** below one frame.
3. **Judge "too short" on the held length (to the word's end) and "too long" on the heard part.**

## Decision

Option 3. A measured word is too short when its start-to-end length, including the hold of ADR-0013, is under 60 ms, and too long when its heard part is over 3 s.

- A short word that the singer holds is plausible; a short word that is not held either (the next word starts right away, or the voice is not used) still counts.
- A held note still does not count as too long.
- Lowering the limit (option 2) would no longer catch any implausible short word, since one frame is the shortest the model hears.

## Consequences

- On the demo song "Knock", too short words drop from 27 to 1; the measured English songs have 0 to 6.
- German verdicts change slightly: a few short words that are held no longer count.
- The alignment stage raises its version, since its quality report changes, so songs are aligned again.
