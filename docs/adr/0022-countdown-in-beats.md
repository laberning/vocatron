---
id: ADR-0022
status: accepted
date: 2026-11-01
superseded_by: "ADR-0028 (in part: where a countdown in beats ends)"
---
# ADR-0022: The countdown counts beats of the song's tempo

Adds to ADR-0006 (a new stage and its file). Supersedes ADR-0009 in part: what the countdown settings of a profile mean.

## Context and problem

The countdown before a line runs for a fixed number of seconds (`countdown.duration`). Singers think in beats: a countdown that ticks on the beat of the song tells them when to come in, one in seconds only roughly. Vocatron has no tempo of the song yet.

## Considered options

1. **Keep the countdown in seconds.**
2. **Track the beats** (tempo and the position of every beat) and tick on them.
3. **Estimate only the tempo** and count back from the line's start, so the last beat lands where the singing starts.

## Decision

Option 3.

- A new stage `tempo` runs after `separation`. It estimates one tempo for the song from the instrumental stem with Vocatron's own code (NumPy, no new dependency) and writes `tempo.json`: the tempo in beats per minute, or none when it is unclear, and a clarity number.
- When the tempo is clear, a countdown lasts `countdown.count` beats and ends at the start of the line; its dots or blocks go out one per beat. The beat is doubled or halved until `count` beats last between 1.5 and 4 seconds. Where a title or break screen leaves less room, the countdown starts on the first whole beat after it, with fewer steps; with no whole beat, there is none.
- When the tempo is unclear, the countdown runs over `countdown.duration` seconds as before. The report notes the tempo and whether beats or seconds were used; this is not a reason for review.
- The rule applies to every countdown, the one after the silent intro (ADR-0020) included, in every look.

## Consequences

- `count` is now the number of beats as well as of dots; `duration` is the length used without a tempo. No built-in look changes its values.
- Only the tempo is estimated, so a song whose tempo changes comes out unclear and keeps the seconds; beats inside a line are not used.
- The layout reads `tempo.json`; the layout stage and the scene raise their versions, the report its schema.
