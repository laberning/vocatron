---
id: ADR-0027
status: accepted
date: 2026-11-02
superseded_by: null
---
# ADR-0027: Place unheard lines at their `.lrc` time

Adds to ADR-0021 (uncertain words keep the model's position): the keep rule does not apply to unheard lines.

## Context and problem

The aligner keeps the model's position for uncertain words when the vocals are voiced there (ADR-0021). In some lines the model hears nothing at all: no word reaches the confidence limit, for example when a phrase is sung only in the backing stem over a busy mix, or in a quiet intro. The model's path through such a line is arbitrary, and keeping it puts whole lines seconds away from where they are sung. In a measurement over the corpus, 42 lines with an `.lrc` time were unheard, 28 of them more than half a second off, while heard lines had a median error of 0.02 to 0.12 seconds per song. The `.lrc` time of a line is then the best evidence left.

## Considered options

1. **Place unheard lines at their `.lrc` time**: the line's first word starts at the `.lrc` time plus the song's rails offset, never before the start of the last measured word before it; its words are placed on the voice up to the next line, else shared by letters. An unheard line with little voice at that time also gets a review reason.
2. **Only mark the song for review** and keep the model's positions.
3. **Keep the current behaviour.**

## Decision

Option 1. A line is unheard when it has an `.lrc` time and every word in it is estimated. Lines are processed last to first; the word before an unheard line is cut so it does not overlap. Lines without an `.lrc` time and lines with at least one heard word are unchanged. An unheard line whose window from its start has less than half voice gets a review reason naming the line number. The maintainer listened to old and new renders of the eight songs the rule changes and judged every moved line better.

## Consequences

- Unheard lines follow the lyrics file instead of an arbitrary model path; this trusts the `.lrc` over the audio only where the model hears nothing.
- A wrong `.lrc` time now shows directly in such lines; the review reason flags the cases with little voice.
- The alignment stage version and the `alignment.json` schema version are raised, so stored alignments are made again.
