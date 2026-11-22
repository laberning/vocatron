---
id: ADR-0034
status: accepted
date: 2026-11-03
superseded_by: null
---
# ADR-0034: Rows after a break and the order in which lines leave

Adds to ADR-0009 (style profiles and the presentation rules).

## Context and problem

In line mode the row of a line is the one whose line ended first. This memory runs through the whole song, so after an instrumental break the next line can land in the bottom row while the top row stays empty during the countdown; that line appears only after the countdown. A line also leaves only when its row is needed again or before the next long gap; in looks with three or four rows, a short line among split lines can take a row that is not needed again and stay on screen for half a minute. The scene rules allowed both.

## Considered options

1. **Start again at the top after every gap where the screen is cleared, and let lines leave in the order they were sung.**
2. Start again at the top after every gap long enough for a countdown, even if the screen is not cleared.
3. Keep the row memory and only limit how long a sung line may stay.

## Decision

Option 1.

- After a gap of at least `breaks.clear_after`, the lines fill the rows from the top, as at the start of the song. The rows count as free from the moment the screen is cleared; no line of the new phrase appears before that, and the lines appear with their normal lead-in. Where the gap leaves less room after the clearing than `lead_in.target`, the lead-in is that room, never less than `lead_in.min`: if needed, the hold before the clearing gives way, but the screen never clears before the singing stops.
- Shorter gaps keep the flow: the row memory carries on there.
- No line stays on screen after a line that was sung after it has gone, and no line goes before its own singing ends.
- The scene rules check both: rule 9 holds the new ending, and a rule checks the restart at the top after a clearing gap.
- This applies to every line look; page and scroll mode are not affected.

## Consequences

- After a break the countdown stands above the first line of the new phrase, in every line look and on CD+G.
- Built-in looks with three or four rows change where lines leave; their pictures, snapshots and golden frames are redrawn. The layout stage raises its version.
