---
id: ADR-0050
status: accepted
date: 2026-11-09
superseded_by: null
---

# ADR-0050: The front page animation is the title screen and the first singing

Supersedes ADR-0045 in part: the animation on the front page is no longer one window of about ten
seconds.

## Context and problem

The front page shows a looping animation of the default look. A visitor should see in a few
seconds how a karaoke track starts and how the words light up with the singing. Jumping between
far-apart parts of the song looks hectic; the singing of the demo song only starts after a long
intro, so the first seconds of the song alone show no singing.

## Considered options

1. **The title screen, then one hard cut to just before the singing starts**, which runs on
   without a cut until the first pause after about ten seconds of singing.
2. **Three short cuts** from the moments of the look pictures (ADR-0049): the title screen, a line
   sung together, and the break with its countdown.
3. **One window from the start of the song**, which would show only the title and the intro, or
   well over half a minute to reach some singing.

## Decision

Option 1.

- The title screen for 3 seconds from the start; then from 3 seconds before the first word to
  1 second after the end of the first line that is followed by a pause of at least 3 seconds (or by
  nothing), once at least 10 seconds have been sung. One hard cut, looping; about 24 seconds for
  the demo song.
- The cuts are computed from the timing of the song, so a new demo song needs no new choice.
- Frames stay 640×480; the pages show the animation 480 pixels wide.

## Consequences

- The animation shows how a track starts and how the singing runs, calmly, in one short loop.
- Breaks, duets sung together and the end screen are left to the look pictures.
