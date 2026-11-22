---
id: ADR-0018
status: accepted
date: 2026-11-01
superseded_by: null
---
# ADR-0018: Singer marks in braces, and duet lines never merged

Supersedes ADR-0008 in part (how a lyrics file marks who sings) and ADR-0009 in part (overlapping lines of different singers drawn merged as a group line, and the profile's duet handling). Names and colours of the singers, and everything else of both, stay as they are.

## Context and problem

ADR-0008 marks the singer with a prefix at the start of a line: `1:` to `5:`, `all:`, a group such as `1,3:`, and the aliases `M:`, `F:` and `D:`. Duets on classic karaoke discs often switch singers inside a line (one of five marked duets does so in five lines), which a line prefix cannot say. The same prefix form inside a line would be ambiguous: `all:` occurs in ordinary lyrics ("that's all: …"), and a time such as "4:30" contains `4:`. The prefixes have not been published yet, so no user file depends on them.

ADR-0009 draws overlapping lines of different singers merged, syllable by syllable, into one group line, which jumbles different texts.

## Considered options

1. **Line prefixes as before, and the same form inside a line.**
2. **Line prefixes as before, and a braced mark only inside a line.**
3. **A braced mark as the only singer mark, at the start of a line and inside it.**

## Decision

Option 3.

- A singer mark is `{1}` to `{5}`, `{all}`, or a group such as `{1,3}`. It may stand at the start of a line or before any word inside it; from there on, the marked singers sing, also on the following lines, until the next mark. The first word of the lyrics without a mark is sung by singer 1.
- Only these exact forms are marks. Any other text in braces, and any text such as `1:` or `M:` at the start of a line, is ordinary lyrics; there is no special handling of the old prefixes.
- In an `.lrc`, a mark at the start of a line comes after the time tag: `[01:12.30] {2} Then Ben`.
- Lines are never merged. A line sung together (`{all}` or a group) is one line in the group colour; a word is drawn in the colours of its singers, so a line can change colour at a word; overlapping lines of different singers keep their own slots. The profile setting for duet handling goes away.

## Consequences

- One form for every singer change; a line can switch singers at a word, and the layout can colour each word by its singers.
- Braces almost never occur in lyrics and are used by no LRC convention, so a mark is not confused with text or with LRC tags; other players show the marks as text, as they showed the prefixes.
- The duet convention of one player family (`M:`, `F:`, `D:`) is no longer read; such files need marks added.
- Existing duet files with the old prefixes are converted once; the parser has no code for the old form.
- The lyrics file and the stage files that carry singers change, so their schema versions and the stage versions go up; every song is aligned again once.
- A profile or `profile_overrides` that still sets `duet` no longer loads.
