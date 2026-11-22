---
id: ADR-0052
status: accepted
date: 2026-11-10
superseded_by: null
---

# ADR-0052: Two voices can sing at once

Adds to ADR-0008 (two alignment passes), ADR-0014 (the model hears the backing), ADR-0018 (singer
marks in braces) and ADR-0047 (the tags of the outputs).

## Context and problem

In some songs a second voice sings a different line while the first is still singing: both start
at the same moment, or the second starts before the first has finished. The alignment makes one
path through all words in order, so a line ends where the next begins: the first is cut short and
the next squeezed, and where both start at once the lines after them come late. An `.lrc` gives
only start times, so it shows two lines starting together but not a line that only partly
overlaps the next one; the audio does.

## Considered options

1. **Two voices.** Every line belongs to the first or the second voice. Each voice is aligned in
   its own path, so lines of different voices may overlap; the second voice comes from the file
   or is found in the audio.
2. **Pairs of lines** marked in the file only, the second line of a pair spread over the time of
   the first.
3. **Nothing new**: one path, lines one after the other.

## Decision

Option 1.

- **The file.** Two lines with the same `.lrc` time put the second line on the second voice. A
  mark `{&}` at the start of a line puts that line on the second voice by hand. Singer marks
  (ADR-0018) are unchanged and still decide the colours.
- **The audio.** With line times (`.lrc` and shifted rails, ADR-0008), each line is also heard on
  the model's output for the backing (ADR-0014). A line goes to the second voice only when all
  hold: the backing hears it clearly better than the lead; the lead stem is silent there or the
  lead's model does not hear the line; the line's slot is crowded (far more letters per second
  than the song usually sings), which keeps a choir part in a normal slot on one voice; and the
  second voice is free there. The thresholds are named constants, tuned on the corpus. Without
  line times only the file counts.
- **The alignment.** One monotonic path per voice, each over its own lines and windows: the first
  voice on the lead's output as before (with the backing mixed in where the lead is silent), the
  second on the backing's output. With a second voice singing, the backing carries its words, and
  the first voice, which hears the backing where the lead is silent, can take them and start a line
  seconds after its line time. A first-voice line whose first word starts more than a second after
  its line time (plus the offset of the rails) is therefore treated like a line the model did not
  hear: its words are estimated and it is placed at its line time (ADR-0027). The limit is a named
  constant in the fingerprint. Lines that share one `.lrc` time end at most a fifth of a second
  after the next line's time, so they cannot delay the lines after them. Words the model did not
  hear are estimated inside their own line as before (ADR-0021, ADR-0027).
- **The display.** The lines of the two voices are shown in their own slots, both on screen and
  wiping at the same time. A second-voice line without its own singer mark is drawn in the colour
  of singer 2. A second voice never makes a song a duet in the tags (ADR-0047 counts the singers
  of the file).
- The report names the lines of the second voice and where each came from (file, `.lrc` times or
  audio). Two lines with the same time are not a reason for review, so a duet is not held back.

## Consequences

- Songs with one voice keep their result; songs with an answering voice keep both lines whole.
- The lyrics and alignment stage files carry the voice of each line; their schema and stage
  versions go up, so every song is aligned again once.
- The audio check depends on the separation putting the second voice into the backing; where it
  does not, the `{&}` mark is the way out.
- The thresholds of the audio check are tuned on the corpus and guarded by the benchmark.
- First-voice lines in a part with a second voice may be estimated rather than measured.
