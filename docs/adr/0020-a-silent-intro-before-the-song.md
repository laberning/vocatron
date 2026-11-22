---
id: ADR-0020
status: accepted
date: 2026-11-01
superseded_by: null
---
# ADR-0020: A silent intro before the song

Adds to ADR-0009 (style profiles, title screen) and ADR-0005 (language modules).

## Context and problem

The video starts with the song. When the singing starts within a few seconds, the title screen is gone after a moment, and in a duet nobody has time to learn which colour belongs to which singer. The title screen lists the singers' names in their colours, but not the colour of lines sung together.

## Considered options

1. **Keep the video as long as the song**, and shorten the title screen when the singing starts early.
2. **Add silence before the song where the singing starts too early**, decided by the layout and applied to every output.
3. **Hold the first frame** of the video while the audio already plays.

## Decision

Option 2.

- A profile sets the minimum time from the start of the video to the first sung word: `intro: {solo: 8.0, group: 9.0}`, the second for a song with more than one singer or with lines sung together. Silence is added only for what is missing; `0` switches the intro off.
- The title screen lasts at least four seconds even when the singing starts early (`title.min_short: 4`); the intro is long enough for that and the lead-in of the first line in every built-in look.
- The layout decides the amount once and stores it in the scene; every output is shifted by it: the video, the karaoke audio in the MP4 and the M4A, the FLAC export, and the `.lrc` that Vocatron writes. The user's lyrics file, the stems and the stored results of the other stages stay unshifted.
- The title screen of a song with lines sung together also lists each group once in the group colour: a group by its singers' names ("Anna & Ben"), a group of every singer by a word from the language module ("Beide"/"Both" for two singers, "Alle"/"All" for more). A group is listed only when all its members have names.

## Consequences

- Every song has time to show its title, and a duet time to show its colours; the usual countdown runs in the added silence when it is long enough.
- The `.lrc` Vocatron writes fits the video, no longer the original audio file, when silence was added.
- A language module supplies the words for lines sung together; the language conformance kit checks them.
- The layout and render stages raise their versions; no stage before them runs again.
