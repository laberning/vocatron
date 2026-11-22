---
id: ADR-0047
status: accepted
date: 2026-11-07
superseded_by: null
---

# ADR-0047: Vocatron writes the tags of every output itself, with Duet to Quintet in `TAG`

Adds to ADR-0031 (artist and title tags in the outputs) and supersedes ADR-0035 in part (the MP4
keeps ffmpeg's tags; every tag of the MP3 is a standard frame).

## Context and problem

A song with several singers is worth finding in a karaoke library. Karaoke collections mark such
songs in a user-defined field named `TAG` with `Duet`, `Trio` and so on, as tag editors like Mp3tag
write it: in an ID3v2.4 MP3 a `TXXX` frame with the description `TAG`, in an MP4 an iTunes freeform
atom `----:com.apple.iTunes:TAG`. Vocatron knows the singers from the marks in the lyrics.

ffmpeg cannot write such a field into an MP4: it drops keys it does not know, and with
`-movflags use_metadata_tags` it writes QuickTime `mdta` keys instead and moves the standard
fields (such as the genre) there too, where many players do not look. The MP3 already gets its tag
from Vocatron's own ID3 writer (ADR-0035), the MP4 from ffmpeg: two ways for one list of tags.

## Considered options

1. **Vocatron writes the tags of the MP4 too**, from the same list as the MP3; ffmpeg writes none.
2. **Only the MP3 gets the `TAG` field**; the MP4 keeps ffmpeg's tags without it.
3. **The MP4 gets the word in the standard grouping field** (`©grp`), which ffmpeg can write but
   tag editors show as GROUPING, not `TAG`.

## Decision

Option 1.

- **The word:** the number of different singer numbers in the singer marks of the lyrics (lines
  and changes inside lines); lines of `all` or of a group add none. Two singers give `Duet`, three
  `Trio`, four `Quartet`, five `Quintet`; one singer or none gives no `TAG`. A song flagged as a duet
  only by its name, without marks, gets none. The words are English for every song, like the genre
  `Karaoke`.
- **One list:** the word is a `tag` entry of the song's media tags after the comment (ADR-0031), so
  the MP4 and the MP3 of the CD+G pair carry the same values. The audio export and the LRC carry
  none.
- **MP3:** the ID3 writer writes `tag` as `TXXX` with the description `TAG` (UTF-8).
- **MP4:** ffmpeg writes no tags. A pure function in `core` builds `udta/meta/ilst` with `©nam`,
  `©ART`, `©gen`, `©cmt` and the freeform `----` atom for `TAG`, replaces ffmpeg's `udta` in `moov`
  and shifts the chunk offsets (`stco`, `co64`) by the change in size, since fast start puts `moov`
  before the media. The render engine writes the result in front of the unchanged rest of the file.
- The render and `cdg` stages raise their versions.

## Consequences

- Every output's tags come from one list and one writer per format, tested on bytes.
- Duets to quintets can be found by the `TAG` field in tag editors and libraries that show it.
- Vocatron owns a small MP4 box writer; an error in the chunk offsets would break playback, so it
  is guarded by a property test and a decode of a real file to the end.
