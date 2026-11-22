---
id: ADR-0040
status: accepted
date: 2026-11-04
superseded_by: null
---

# ADR-0040: The break screen stands alone in scroll mode

Supersedes ADR-0033 in part: that a long break glides on to a still break notice in the current
place. Everything else of ADR-0033 and ADR-0036 stays as it is.

## Context and problem

In scroll mode a long break needs a screen. If the column glides on to it, the lyrics run into
the break screen: the last sung line stands above it and the next lines below, and after the break
the column glides on. The break then does not read as a pause, and the screen differs from the
break screen of every other mode.

## Considered options

1. **The notice is an entry of the column, like a line**, gliding in and out with it.
2. It appears still in the current place between two glides, the column around it.
3. **The column leaves, the break screen stands alone**, and the column starts again after it.

## Decision

Option 3.

- Before a gap of `breaks.notice_after` seconds or more that leaves room for the screen, the lines
  on screen fade out when the other modes clear the screen: `clear.hold` after the singing stops,
  but in time for the next line's lead-in (ADR-0034). They fade over `ending.fade`, the fade of the
  song's end, shortened where the singing would still be on. No line after the break is on screen
  before the break screen ends.
- The break screen is the one of the page and line modes: still and centred in the safe area,
  with its form (`notice`, `progress` or `timer`).
- After it the column starts again as after the title screen: it glides in from below with the
  next line at the current place, and the countdown starts when the column rests.
- Shorter gaps, also those between `breaks.clear_after` and `breaks.notice_after`, glide on as
  before; nothing is cleared there.
- The timing of the glides between lines and the countdown are unchanged.

## Consequences

- A long break reads as a pause in every mode, with the same screen.
- The song in scroll mode is a row of parts, each starting like the song itself; the scene rules
  check that nothing of the column is on screen during a break screen.
- Nothing but the lines moves in a scrolling look; the layout stage raises its version.
- Option 1 was not taken: the lyrics running into the break screen read as a confusing scroll.
  Option 2 keeps the next lines on screen during the break.
