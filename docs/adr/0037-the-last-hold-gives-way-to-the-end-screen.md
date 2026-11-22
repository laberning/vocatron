---
id: ADR-0037
status: accepted
date: 2026-11-03
superseded_by: null
---
# ADR-0037: The last hold gives way to the end screen

Adds to ADR-0009 (style profiles and the presentation rules).

## Context and problem

After the last line the lyrics stay `clear.hold` seconds; the end screen starts `ending.start_after` seconds after the singing stops. A look may set a hold longer than that wait, and then the last lines are drawn over the end screen. No rule and no profile check catches it.

## Considered options

1. **The hold gives way: the lyrics go at the latest when the end screen starts.**
2. Refuse a look whose `clear.hold` is longer than `ending.start_after` in the profile check.
3. Start the end screen after the hold instead.

## Decision

Option 1.

- The lyrics stay after the last line for `clear.hold`, but never after the end screen starts, in every mode (line, page and scroll); they never go before the singing stops.
- This holds whenever the look shows an end screen (`ending.end_screen`), also where the song is too short after the last line for the end screen to be drawn.
- The scene rules check that nothing of the lyrics is on screen once the end screen has started.

## Consequences

- Own looks with a long hold keep working; the built-in looks do not change.
- The layout stage raises its version.
