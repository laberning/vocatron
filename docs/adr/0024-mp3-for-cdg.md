---
id: ADR-0024
status: accepted
date: 2026-11-01
superseded_by: null
---
# ADR-0024: The MP3 of the CD+G pair is encoded by LAME through ffmpeg

Adds to ADR-0002 (ffmpeg) and ADR-0023.

## Context and problem

A CD+G track is an MP3 next to the `.cdg`. The MP4's audio is AAC made by fdkaac (ADR-0009), which cannot write MP3.

## Considered options

1. **ffmpeg with libmp3lame** (LAME, the reference MP3 encoder).
2. **ffmpeg with libshine** (fixed-point, lower quality).
3. **A Python MP3 package** as a new dependency.

## Decision

Option 1: the karaoke audio, with the silent intro (ADR-0020), is encoded by ffmpeg with libmp3lame at 192 kbit/s, 44.1 kHz stereo, the usual quality of MP3+G tracks.

## Consequences

- No new dependency; ffmpeg builds without libmp3lame cannot make CD+G, and the stage says so.
- LAME's encoder delay (about 25 ms) is accepted; it is within the timing accuracy of the alignment.
