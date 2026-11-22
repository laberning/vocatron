---
id: ADR-0039
status: accepted
date: 2026-11-04
superseded_by: null
---
# ADR-0039: A short group sits next to the middle

Supersedes ADR-0038 in part: where a group with fewer rows than its block sits in the block.
Everything else of ADR-0038 stays as it is.

## Context and problem

With blocks (ADR-0038) a group with fewer rows than its block (a line before a split line, before
a break, at the end of the song) takes the block's top slot. In the top block an empty row then
stays between that line and the lines of the block below.

## Considered options

1. **The group takes the slots of its block next to the middle of the stack.**
2. It takes the slots next to whichever block holds lines at that moment.
3. Keep the top slot.

## Decision

Option 1.

- A block that lies wholly in the upper half of the slots fills from its bottom slot up; every
  other block fills from its top slot down. Inside the group the rows stay in sung order.
- It applies to every short group, also before a break and at the end of the song. After a break
  the first group still goes into the top block (ADR-0034).
- A group that turns line by line, because no block is free, is not affected.
- The scene rule for blocks checks it.

## Consequences

- With two blocks no empty row stays between lines on screen; with three blocks the middle block
  keeps filling from its top.
- The layout stage raises its version. Pictures and golden frames of looks with blocks change
  where they show a short group (those of `four-line-stack` show only full pairs and stay as they
  are). Looks without blocks (`block: 1`) are unchanged.
- Option 2 was not taken: it would depend on the timing of the moment and be harder to predict
  and to check.
