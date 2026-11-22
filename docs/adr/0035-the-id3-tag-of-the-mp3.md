---
id: ADR-0035
status: accepted
date: 2026-11-03
superseded_by: "ADR-0047 (in part: the MP4 tags are written by Vocatron, not ffmpeg; the MP3 also has a TXXX frame for TAG)"
---
# ADR-0035: Vocatron writes the ID3 tag of the MP3

Adds to ADR-0031 (artist and title tags in the outputs) and ADR-0024 (the MP3 of the CD+G pair).

## Context and problem

ADR-0031 puts a title, an artist, the genre `Karaoke` and a comment into the MP4 and the MP3. ffmpeg writes the standard MP4 fields, but in the MP3 it writes the comment as a user-defined text frame (`TXXX` named `comment`), whatever key or ID3 version it is given, not as the standard comment frame (`COMM`). Windows Explorer and many players read only `COMM`, so they show no comment.

## Considered options

1. **ffmpeg writes the MP3 without a tag; Vocatron writes the whole ID3v2.4 tag itself** (`TIT2`, `TPE1`, `TCON`, `COMM`) and puts it in front of the audio.
2. **An ID3 library.** The common ones are GPL-licensed, which does not fit an MIT project, for four frames.
3. **ffmpeg's tag plus a `COMM` frame patched in** afterwards: two writers for one tag.

## Decision

Option 1.

- The tag values still come from one place, the song's media tags (ADR-0031). The MP4 keeps ffmpeg's tags; the MP3's tag is built by a pure function in `core` (ID3v2.4, UTF-8 text, the comment in English with an empty description) and written by the MP3 engine in front of ffmpeg's tag-less audio.
- The `cdg` stage raises its version.

## Consequences

- Every tag of the MP3 is a standard frame that players and Windows read.
- Vocatron owns a small ID3 writer; it is tested against fixed bytes and read back with ffprobe on a real file.
