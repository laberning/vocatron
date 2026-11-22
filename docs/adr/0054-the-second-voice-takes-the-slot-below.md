---
id: ADR-0054
status: accepted
date: 2026-11-12
superseded_by: null
---

# ADR-0054: The second voice takes the slot below

Adds to ADR-0052 (two voices can sing at once), ADR-0038 (lines turn in blocks) and ADR-0043
(the four-line stack is the default look).

## Context and problem

ADR-0052 decides that the lines of two voices sung at once are both on screen and wipe at the
same time, each in its own slot. It does not say which slot, and the layout modes differ: line
mode refills slots one line at a time, blocks turn together, pages hold a fixed set of lines,
a one-slot look has no second slot and the scrolling column has one current place.

## Considered options

1. The second-voice line takes the slot below the first-voice line it overlaps, in every mode at
   once.
2. The same, first in line mode and in blocks (the default look); the other modes keep showing the
   lines one after the other until they get their own design.
3. Two columns side by side.

## Decision

Option 2.

- In line mode and in blocks, a second-voice line that overlaps a first-voice line is shown in the
  slot below it, also when the second voice starts first. Both are on screen before either
  starts and both wipe at the same time. In blocks, the two lines belong to one block.
- A line split over several rows is paired with all its rows: the rows of the second-voice line
  are shown below the rows of the first-voice line. In blocks, a pair that does not fit one block
  takes the rows of both blocks while it is sung.
- A line has its own singer mark only when the mark stands at its start; a mark in the middle of
  a line changes the colour from that word on.
- A second-voice line that overlaps two first-voice lines keeps its slot until it ends; the next
  first-voice line takes the next free slot. A slot is never given to a new line while its line is
  being sung.
- In blocks, while a line of the other voice is still being sung, a group whose block frees
  less than the minimum lead-in before it starts is placed line by line (the ADR-0038 fallback),
  so its lines do not wait for a whole block. Songs with one voice do not change.
- Page mode, a one-slot look and scroll mode keep showing such lines one after the other, and the
  layout notes it.
- Two columns were not chosen: they halve the width of every line and do not fit the four-line
  stack.

## Consequences

- The scene rules that assumed one line sung at a time allow two lines of different voices.
- The layout reads the voice of every line, including the voices found in the audio.
- The other modes follow in their own change.
