---
id: ADR-0046
status: accepted
date: 2026-11-06
superseded_by: null
---
# ADR-0046: Characters the bundled font cannot draw

## Context and problem

Vocatron draws all text in its bundled font and fails a render in which libass chose another
font (ADR-0002), so that the layout measures the font the video shows. A lyrics line with one
character the font lacks (a mathematical sign in a lyrics file found online) made libass fall
back to a system font: the song failed only at the render, after the slow stages, with a message
that named neither the character nor the line.

## Considered options

1. Keep failing at the render, but name the character and the line.
2. Check every character against the bundled font when the lyrics are read: fail early for all.
3. Check early; drop symbols the font cannot draw with a review reason, fail early for letters
   and digits the font cannot draw.

## Decision

Option 3.

- The characters of the bundled font are read from its character map.
- Lyrics cleaning removes every character of a line that the font cannot draw and that is not a
  letter, a mark or a digit (Unicode categories other than L, M and N), and reports each removal
  with its line and code point (`U+221A SQUARE ROOT`); the song needs review. A line left without
  a letter or digit is dropped as today.
- Note signs (U+2669 to U+266C, decoration in lyrics found online) are dropped without a report,
  and so are variation selectors, the marks of a dropped symbol and white space the font lacks.
- A letter, mark or digit the font cannot draw fails the lyrics stage with the line and the code
  point, before the slow stages.
- The text of the start screen (title, artist, singer names) follows the same rule in the layout
  stage: symbols are dropped with a review reason, a letter the font lacks fails the stage.
- The render's font check stays as the last safety net, and its message names the characters the
  font lacks.

## Consequences

- No song fails late on a stray symbol; the review reason says what was dropped and where.
- Songs in a script the font does not cover fail at once with a clear message.
- The lyrics and layout stages change their results for such songs and raise their versions.
