---
id: ADR-0026
status: accepted
date: 2026-11-02
superseded_by: null
---
# ADR-0026: A countdown never starts before the line before it ends

Adds to ADR-0022 (where a countdown in beats or seconds may start).

## Context and problem

A countdown appears when the silence before a line is at least `countdown.min_gap` long. With a tempo it lasts up to `countdown.count` beats, at most four seconds; without one, `countdown.duration` seconds. ADR-0022 lets only a title or break screen cut it short. The built-in looks have a `min_gap` of five seconds, so their countdowns always fit into the silence. An own look with a shorter `min_gap` can get a countdown that starts while the line before is still sung, which tells the singer to wait while they are singing.

## Considered options

1. **The end of the line before is a floor too**, like the title and break screens: the countdown starts on the first whole beat after it and counts the beats that are left; with less than one beat of room there is none. Without a tempo the seconds are cut there.
2. **The profile check refuses a `min_gap` under four seconds.** It forbids looks that are fine for fast songs, and the limit depends on `MAX_COUNTDOWN`, not on the look.

## Decision

Option 1. The earliest a countdown may start is the latest of: the end of the line before, the end of the title screen, the end of the break screen before the line. Rule 13 checks the same floor. The built-in looks do not change.

## Consequences

- An own look with a short `min_gap` gets shorter countdowns, on the beat, after short gaps, and none where less than a beat is left.
- The layout stage version is raised, so stored layouts are made again.
