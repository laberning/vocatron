---
id: ADR-0057
status: accepted
date: 2026-11-16
superseded_by: null
---

# ADR-0057: The end and break screens carry the mark

Adds to ADR-0055 (the start screen carries the wordmark) and ADR-0040 (the break screen stands alone in
scroll mode).

## Context and problem

The start screen shows the Vocatron wordmark; the end screen and the break screen are still plain
text. A mark could also stand in a corner while the lyrics run.

## Considered options

1. The mark on the start screen only.
2. The wordmark on the end screen and the V symbol on the break screen.
3. As option 2, plus a small symbol in a corner while the lyrics run.

## Decision

Option 2.

- The end screen is the wordmark screen of the start, without the build-up, and fades out as
  before.
- The break screen shows the V symbol filled with the wordmark's colour bands and its cyan edge,
  drawn complete without a build-up, above the notice; it belongs to the notice's box and stands
  still with it, also in a scrolling look (ADR-0040). The notice keeps the look's colours.
- There is no corner mark: classic karaoke discs have none, it competes with the lines, and the
  free corner differs from look to look.
- `title.form` switches all three screens: `wordmark` gives the mark on each, `plain` on none.
- Video only: the CD+G end and break screens stay plain.

## Consequences

- A track is recognisable at its start, in its long breaks and at its end.
- The break card and the end card in the scene and in `layout.json` change, so the layout file gets
  a new schema version and the layout and render stages raise their versions.
