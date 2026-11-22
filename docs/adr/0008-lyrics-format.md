---
id: ADR-0008
status: accepted
date: 2026-10-28
superseded_by: "ADR-0018 (in part: singer marks)"
---
# ADR-0008: Lyrics format

## Context and problem

The lyrics are the most important input of the sync: the alignment can only be as good as the text. Users write and edit lyrics files by hand, Vocatron writes them when it finds lyrics online, and the same file must say who sings which line in duets and groups. Many music players read `.lrc` files, so an `.lrc` written or edited for Vocatron must keep playing elsewhere. The only existing duet convention for LRC is the `M:`/`F:`/`D:` prefix of one player family; no other convention exists.

## Considered options

1. **Plain text and LRC with line prefixes**, singer names in a header (text) or in extra LRC tags.
2. **A Vocatron-specific YAML or JSON lyrics format.**
3. **Enhanced LRC only**, with word times as input.

## Decision

Option 1.

- **Files:** the lyrics are a sidecar next to the audio, `Song.txt` (plain text) or `Song.lrc` (LRC), UTF-8. If both exist, `Song.lrc` wins. One line per sung phrase; every repeat written out (no "(2x)"); blank lines separate blocks.
- **Singers:** a line may start with a singer prefix: `1:` to `5:`, `all:`, or a group of singers such as `1,3:`. `M:`, `F:` and `D:` are accepted as aliases for `1:`, `2:` and `all:`. A line without a prefix keeps the singer of the line before it; the first line defaults to `1:`.
- **Singer names and colours in `Song.txt`:** an optional YAML block at the top between two `---` lines:
  ```text
  ---
  singers:
    1: {name: Anna, colour: "#e0b000"}
    2: Ben
  ---
  1: First line sung by Anna
  2: Then Ben
  all: Both together
  ```
- **Singer names and colours in `Song.lrc`:** extra ID tags `[singer1: Anna, #e0b000]`, which players that do not know them ignore; the line prefixes come after the time tag: `[01:12.30] 2: Then Ben`. The standard LRC tags (`ti`, `ar`, `al`, `length`, `offset`, …) are read; word time tags of enhanced LRC are ignored on input.
- **Line times of an `.lrc` are hints, never the truth:** the alignment places every word from the audio. The line times only narrow its search, after a check against the separated vocals: a consistent offset is corrected, inconsistent times are ignored and the song is marked for review. Vocatron never changes a user's lyrics file.
- **Duet flag:** a song is treated as a duet when its file name matches a configurable pattern (default: contains `duet` or `duett`, any case) or its tags say so. A duet without singer prefixes is marked for review.
- **Names and colours** from the file override the style profile; without them, the profile's singer colours apply. How a group line is drawn is decided by the style profile.
- **Written by Vocatron:** when no sidecar exists, Vocatron writes `Song.lrc` if the found lyrics are synced and their length fits the song within 2 seconds, otherwise `Song.txt`. Such a file carries a mark in the file itself, so its origin survives a lost work folder: `[re: Vocatron <check>]` as the first row of an `.lrc` (the standard `re` tag, ignored by players), `written_by: "Vocatron <check>"` in the header of a `.txt`, where `<check>` is a short SHA-256 of the file without the mark. A file that differs from what Vocatron wrote (any edit, or a missing or mismatching mark) counts as approved by the user.

## Consequences

- Fans edit lyrics in any text editor; `.lrc` files stay playable in normal players, which may show the `2:` prefixes as text.
- The parser and writer are pure functions with a round-trip property: parsing a valid file and writing it back gives the same file.
- More than five singers needs a new ADR; so far no use case needs it.
- The check of `.lrc` line times against the vocals happens in the alignment stage, where the separated vocals exist.
