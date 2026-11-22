---
id: ADR-0038
status: accepted
date: 2026-11-03
superseded_by: "ADR-0039 (in part: where a short group sits in its block)"
---
# ADR-0038: Lines turn in blocks

Adds to ADR-0009 (style profiles and the presentation rules) and ADR-0034 (rows after a break).

## Context and problem

In line mode every line takes the slot whose line ended first and is replaced on its own. With four rows the eye jumps after every line, although songs are often sung in pairs of lines.

## Considered options

1. **A profile key `block`: the slots form blocks of that many neighbouring rows, and the lines turn a block at a time.**
2. Detect the pairs of the song (pauses, rhymes) and turn by them.
3. Keep turning one line at a time.

## Decision

Option 1.

- Line mode gains `block` (1 to 3, default 1, which is today's behaviour). The slots, and the CD+G slots if the look has a CD+G section, must be a multiple of it, with at least two blocks. Page and scroll mode refuse it.
- Lines are grouped in sung order: a group holds `block` rows, a split line counts by its rows. After a gap where the screen is cleared the grouping starts again, in the top block.
- A group goes into the block whose lines ended first. Its lines appear together, once the block is free (its lines sung and the next line started, as for a slot), and the lines in that block go together at the same moment.
- When no block is free because every block still holds a line that is being sung, that one group turns line by line instead, each line taking the slot whose line ended first as with `block: 1`; the blocks go on with the next group.
- `lead_in.min` is kept for every line; `lead_in.max` counts for the first line of a group only, as for the first line of a page.
- A scene rule checks that a group shares its block, appears together and goes together.
- The look `four-line-stack` turns in blocks of two.

## Consequences

- `four-line-stack` reads in pairs; its pictures, snapshots and golden frames are redrawn, on video and CD+G. The layout stage raises its version.
- Own looks can turn in blocks; looks without the key are unchanged.
