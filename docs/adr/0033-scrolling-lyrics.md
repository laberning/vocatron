---
id: ADR-0033
status: accepted
date: 2026-11-02
superseded_by: "ADR-0036 (in part: a line never moves while sung; the jump without silence); ADR-0040 (in part: the break notice in the current place)"
---
# ADR-0033: Scrolling lyrics

Adds to ADR-0009 (style profiles), ADR-0019 (the profile check), ADR-0029 (the CD+G section of a style profile) and ADR-0032 (effects for video-only looks).

## Context and problem

The layout has two modes: `line` (fixed slots, a line replaced when it has been sung) and `page` (a page of lines, cleared when done). In both, every line stays in one place for its whole time on screen, and the scene rules assume it. Current lyric apps show a scrolling column instead: the line being sung in a fixed place, the sung lines above it and the next lines below. libass can move text (`\move`), so a video can do this; CD+G cannot move text smoothly.

## Considered options

1. **Stop and glide:** the column stands still while a line is sung and glides up in a short move (about 0.4 s) before the next line starts.
2. **Continuous scroll** at a speed that follows the song.
3. **No scrolling**; only the fixed modes.

## Decision

Option 1.

- A third layout mode, `scroll`, with a `scroll` section in the profile: `current` (the height of the line being sung in the safe area), `before` (sung lines kept above, 0 to 2), `after` (upcoming lines below, 1 to 4) and `glide` (seconds, 0.2 to 1.0, default 0.4). Sung and upcoming lines are dimmed with the dimming of ADR-0032; all lines have the same size.
- Each line in the scene has a path: keyframes of time and height. Between glides nothing moves. A glide ends before the lead-in of the line it brings to the current place, so a line never moves while it is being sung. A long line wraps onto two rows that move together.
- A long break glides on to the break notice in the current place, then on to the next line; the countdown sits just above the current place. The title card and the end screen are as in the other modes; after the title, the column glides in from below.
- The glide is the only motion of a scrolling look: a profile with `mode: scroll` and a `transition` section is refused. When a line follows the one before without silence, there is no time for a glide, so the column moves in one step. Where a wipe is shifted earlier (`wipe.offset`) and the gap is too short for both, the glide may overlap the start of the shifted wipe.
- The break notice is a still card in the current place: it appears when the glide to it ends and is gone when the next glide starts.
- Singer colours are as in every look; all lines are centred.
- The scene rules that assume fixed slots get a scroll variant, and a new rule checks the paths: rows never overlap at a keyframe or during a glide, the line being sung stands still at its place from its first syllable to its last, and no sung row leaves the safe area.
- Scroll mode is MP4 only: a profile with `mode: scroll` and a `cdg` section is refused (ADR-0029).
- One built-in look uses it: `lyric-scroll`, in the style of `lyric-video`.

## Consequences

- Looks can scroll by profile, own profiles included, and are checked like every other look.
- The scene and `layout.json` gain the path; the layout stage raises its version. The existing looks draw exactly as before.
- The ASS writer draws a moving line as one event per still part and one per glide, continuing the wipe across them.
- Singer 2 on the right, as some apps show it, is not part of this decision.
