---
id: ADR-0028
status: accepted
date: 2026-11-02
superseded_by: null
---
# ADR-0028: A countdown in beats ends one beat before the line

Supersedes ADR-0022 in part: where a countdown in beats ends. The tempo stage, the doubling and halving of the beat, the countdown in seconds without a tempo and the floors of ADR-0026 stay as they are.

## Context and problem

A countdown in beats ends at the start of the line (ADR-0022): the last dot or block goes out on the beat where the singing starts. Singers count "one, two, three, four" and come in on the next "one", so the singing should start one beat after the countdown is over, as a band leader counts in. The maintainer compared renders of three songs with both rules, with dots and with the shrinking bar.

## Considered options

1. **Keep the end at the start of the line.**
2. **End one beat before the line**: the countdown lasts the same number of beats, but each step comes one beat earlier; the singing starts on the beat after the last step.

## Decision

Option 2. A countdown in beats ends one beat before the start of the line, in every look and every form (dots, blocks, the shrinking bar). The floors of ADR-0026 (the end of the line before, the title and the break screen) still apply: where they leave less room, the countdown starts on the first whole beat after the floor and counts fewer beats; with no whole beat before the end, there is none. A countdown in seconds, used when the tempo is unclear, still ends at the start of the line, since there is no beat to leave out.

## Consequences

- A countdown needs one beat more of silence than before, so after short gaps it counts one beat less.
- Rule 13 of the scene checks the new end.
- The layout stage version is raised, so stored layouts are made again.
