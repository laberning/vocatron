---
id: ADR-0030
status: accepted
date: 2026-11-02
superseded_by: null
---
# ADR-0030: The MP3+G pair can be packed into one zip

Adds to ADR-0023 (CD+G output) and ADR-0024 (the MP3 of the pair).

## Context and problem

CD+G output writes `Artist - Title.mp3` and `Artist - Title.cdg` next to the video. MP3+G collections are usually shared as one zip per song, and some players load the zip directly. Two loose files per song are easy to separate by mistake.

## Considered options

1. **An optional zip that replaces the loose pair.**
2. **A zip in addition to the loose pair.**
3. **No zip**; users pack the files themselves.

## Decision

Option 1. `cdg_zip: true` in `vocatron.yaml` packs the MP3 and the CD+G file into `Artist - Title.zip` instead of writing them loose. It is an output setting, not part of a look; the default is off. The zip has the same bytes for the same inputs: fixed member order and fixed file times. Changing the setting runs only the `cdg` stage again.

## Consequences

- One file per song when the setting is on; nothing changes when it is off.
- Writing the zip is an engine with a fake, like every other file output.
