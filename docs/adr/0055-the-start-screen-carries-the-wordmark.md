---
id: ADR-0055
status: accepted
date: 2026-11-16
superseded_by: null
---

# ADR-0055: The start screen carries the Vocatron wordmark

Adds to ADR-0009 (style profiles), ADR-0020 (the silent intro), ADR-0023 (CD+G output) and
ADR-0032 (effects for video-only looks).

## Context and problem

Classic karaoke discs open every song with the maker's mark, the song title and the artist, on a
colour field that belongs to the maker. Vocatron's start screen is a plain card of text in the
colours of the look, so nothing tells a Vocatron track from any other, and there is no logo for
the README or the docs.

## Considered options

1. Keep the plain start screen; a logo only in the docs.
2. A wordmark on the start screen, drawn in each look's own colours on the look's background.
3. A wordmark with fixed colours on its own dark field, the same in every look, with a profile
   setting that brings the plain start screen back.

## Decision

Option 3.

- **The wordmark** is the name in eight capital block letters with cut corners, filled with seven
  horizontal colour bands from yellow through red to violet and edged with a thin cyan line that
  glows. The letter V alone, drawn the same way, is the symbol. The letters are polygons defined
  in `core`; no font and no artwork from elsewhere is used.
- **The start screen** shows the wordmark at the top and, in a rounded cyan frame below it, the
  song title in white, a short amber rule and the artist in amber, both in capitals; singers'
  names follow in their colours where the lyrics file names them. There is no "in the style of"
  line and no credit line. The screen has its own dark field over the whole picture; the
  background of the look starts when the start screen ends.
- **The build-up** takes about two seconds: the edge of the letters fades in, the bands fill the
  letters in three steps (VO, CA, TRON), then the frame and the texts wipe in from the left.
  It is played only when the start screen lasts at least four seconds; a shorter one shows the
  finished screen at once. The renderer cannot trace an outline or fade a shape along a gradient,
  so the edge is not drawn stroke by stroke and there is no reflection.
- **The setting** `title.form` of a style profile is `wordmark` (the default) or `plain` (the
  start screen as before). The times of the start screen (`title.min`, `title.min_short`) and the
  silent intro do not change.
- **CD+G** keeps the plain start screen for now: its one palette of 16 colours per song has no
  room for the bands next to the colours of a look. A start screen with its own palette is a
  later decision.
- The wordmark and the symbol are also written as SVG files into `docs/assets/`, from the same
  polygons, and the README shows the wordmark.

## Consequences

- Every video opens with the same recognisable screen, whatever the look.
- The title card in the scene and in `layout.json` gains the wordmark and its build-up, so the
  layout file gets a new schema version and the layout and render stages raise their versions.
- The pictures of the looks and the front page animation change, because they show the start
  screen.
- The video and the CD+G of the same song open differently until CD+G gets its own start screen.
- The wordmark is described by what it shows; the repository names no other maker's mark.
