---
id: ADR-0013
status: accepted
date: 2026-10-31
superseded_by: "ADR-0017 (in part: which length judges a word too short)"
---
# ADR-0013: Word ends at the end of the voice

Adds to ADR-0002 (alignment and confidence per word) and builds on ADR-0012 (voice activity).

## Context and problem

A measured word ends where the acoustic model last heard one of its letters; that last letter lasts about one frame (20 ms median on twelve songs). So a word ends before the singer stops: the wipe of a held note finishes early, and between the words of a sung phrase the wipe stops for a moment at almost every word boundary. ADR-0012 left extending word ends as a separate decision.

Measured on eleven benchmark songs and the demo song, the end of the last letter lies inside a voiced stretch for 85–99 % of measured words. Moving each end to where that voice stops would move 85–96 % of the words, typically by 0.06–0.16 s; about nine in ten of those moves stop at the next word's start, because the voice sounds through a whole phrase. Line ends move by up to about 1 s on held notes.

## Considered options

1. **Keep the ends where the last letter was heard.**
2. **Extend only words followed by a pause** (line ends, held notes), leaving the short gaps inside phrases.
3. **Extend every measured word to where its voice stops**, never past the next word's start and at most a fixed maximum hold.

## Decision

Option 3. A measured word whose last letter ends inside a voiced stretch ends where that stretch ends, or at the next word's start, or 4 s after the last letter, whichever comes first; ends only move later. The voice activity is the one of ADR-0012, with its voice source (`vocals` by default) and its plausibility rules; where it is not used, ends stay as they are.

- The wipe then runs continuously through a sung phrase, as on classic karaoke discs; real pauses (from about 0.15 s) stay visible, and held notes are wiped until they end.
- Using the same voice source as ADR-0012 keeps one loudness per song and one place for its rules. A song whose backing harmonies stretch line ends (seen on one of twelve songs) can use `voice_source: lead`.
- The 4 s maximum is a guard against an outro or ad-lib, not a tuned value.

## Consequences

- Words of a phrase touch: the heard end of a word stays available (its last letter), and the quality checks judge word lengths on the heard part, so held notes do not count as odd lengths; gaps inside lines are judged on the held ends.
- The last syllable of a word gets the held time; earlier syllables keep theirs.
- Line starts do not change, so the sync benchmark is unaffected; the hold before long gaps and the start of break and end screens come later by the held time.
- The alignment and syllables stages raise their versions, so songs are aligned again.
