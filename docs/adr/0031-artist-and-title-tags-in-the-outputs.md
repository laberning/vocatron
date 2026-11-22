---
id: ADR-0031
status: accepted
date: 2026-11-02
superseded_by: null
---
# ADR-0031: Artist and title tags in the outputs

Adds to ADR-0023 and ADR-0024 (the MP3 of the CD+G pair) and to the render of the MP4.

## Context and problem

The MP4 and the MP3 that Vocatron writes carry no artist and no title, so music players, libraries and karaoke software show them as unknown or by file name only. Vocatron already knows the song's artist and title: its identity, from the input's tags or else from the file name, names the output files and is shown on the title card.

## Considered options

1. **Write the identity as tags, plus fixed tags that mark a karaoke version**, and copy nothing else from the input.
2. **Copy all tags of the input** (album, year, track number, cover).
3. **No tags**, as today.

## Decision

Option 1.

- Both the MP4 and the MP3 of the CD+G pair carry `title` and `artist` from the song's identity (no artist tag when the song has no artist), the genre `Karaoke` and the comment `Karaoke version made with Vocatron`.
- The title is not changed; no "(Karaoke)" is added.
- No tags are copied from the inputs.
- The MP3 uses ID3 version 2.4.
- The render and `cdg` stages raise their versions, so existing songs are rendered again on their next run.

## Consequences

- Players and libraries show the karaoke versions by name and, through the genre, apart from the original recordings.
- A wrong tag in the input shows in the file name, on the title card and in the tags alike, and is fixed once in the input.
- Album, year, track number and cover can be added later by a new decision.
