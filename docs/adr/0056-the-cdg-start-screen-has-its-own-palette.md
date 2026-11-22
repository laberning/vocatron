---
id: ADR-0056
status: accepted
date: 2026-11-16
superseded_by: null
---

# ADR-0056: The CD+G start screen has its own palette

Adds to ADR-0023 (CD+G output), ADR-0029 (the CD+G section of a style profile) and ADR-0055 (the
start screen carries the wordmark).

## Context and problem

The video opens with the wordmark start screen; CD+G kept the plain card because its one palette
of 16 colours per song has no room for the colour bands next to the colours of a look. The
wordmark screen alone needs a dark field, a cyan edge, seven bands and white, and the singers'
names must keep the colours of their lines.

## Considered options

1. Keep the plain start screen on CD+G.
2. A reduced wordmark in the song's palette (fewer bands, no edge).
3. A start screen with its own palette, replaced by the song's palette when the screen ends.

## Decision

Option 3.

- The start screen's palette holds the field, the cyan edge, the seven bands (the amber of the rule
  and the artist is one of them) and white, then the name colours of the song, each once: room for
  five singers and a group. The texts of this screen are pixel text without the smoothing shade,
  which is what leaves that room.
- The letters are pixel letters set on a grid of nine by eleven, scaled by three, banded by rows
  and edged by one pixel of cyan; they are defined in `core` next to the polygons of the wordmark
  and tested against them.
- The stream loads the start screen's palette first. When the start screen ends, one memory preset
  clears the screen and the song's palette is loaded; the song is drawn only after that. The song's
  palette no longer counts the colours of the start screen.
- There is no timed build-up: the screen is drawn as fast as the format allows, wordmark first.
  It is complete within three seconds, well before the start screen ends (at least four seconds);
  with long texts the format's bandwidth does not allow two.
- The texts of this screen have sizes of their own, the same in every look and independent of the
  look's lyric sizes: title 22 px, artist 15 px, names 13 px, and none smaller than 12 px.
- A long title or artist wraps onto two rows at a word before it shrinks; the rows of one text
  share one size and stand closer together than separate texts. The singers' names stand side by
  side, each in its colour, as many to a row as fit, spread evenly over as few rows as needed (two
  and two rather than three and one); one name to a row only when that gives larger text. The
  video's start screen follows the same rules for wrapping and names.
- A screen whose texts would still be smaller than 12 px falls back to the plain card on CD+G.
- Every CD+G look follows its `title.form`. A start screen shorter than four seconds (possible only
  in an own look) gets the plain card. The end screen stays the plain card in the song's palette.

## Consequences

- The video and the CD+G of a song open with the same screen.
- The first lines of a song cannot be drawn while the start screen stands; they are drawn in their
  lead-in after it, and the timing fallback of ADR-0029 applies as before.
- A player shows the start screen's colours only until the palette is replaced; a decoder that
  makes pictures applies the palette in force at each frame.
- The CD+G stage raises its version; the CD+G look pictures change.
