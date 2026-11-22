---
id: ADR-0045
status: accepted
date: 2026-11-06
superseded_by: "ADR-0049 (in part: the moments \"a line sung together\" and \"a line change\", in song order); ADR-0050 (in part: the front page animation is the title screen and the first singing)"
---
# ADR-0045: Pictures of the looks from the duet demo song

Supersedes ADR-0019 in part: the pictures of the looks show six moments of the English demo song
instead of four moments of a public-domain folk song. Everything else of ADR-0019 stays as it is.

## Context and problem

The pictures of ADR-0019 show four moments (start screen, a line being sung, a line or page
change, the countdown) of a made-up timing of a folk song. They do not show the break screen,
the end screen or real singing, and a reader cannot see the looks at a glance. The README shows
only a still picture. The English demo song is now a duet with a long intro, a 27 s instrumental
break and gaps of 5 s and more, under CC BY 4.0.

## Considered options

1. Keep the folk song and add two moments.
2. Draw the pictures from the English demo song: from its committed timing, on the CPU, without
   the GPU and without the audio.
3. Render a video of every look.

## Decision

Option 2.

- The timing of the demo song (lines, syllable times, singers, tempo, length), exported from an
  accepted demo run, is committed next to its lyrics and feeds the pictures.
- Each look has a 3×2 sheet of six moments: start screen, a line being sung (the first line of the
  second singer), a line change, the break screen, the countdown and the end screen. Five are at
  the same song time in every look; the line change depends on the look's own turn and is taken
  just after the look's first change once both singers sing together. CD+G looks also have a
  3×2 CD+G sheet.
- An overview picture shows every look at the same moment, with its name.
- A looping GIF of the default look (about 10 s of the song) opens the README and the docs start
  page.
- Every picture credits the song (title, Josh Woodward feat. Katie Pederson, CC BY 4.0).

## Consequences

- A new demo run of the English song that changes its timing needs a new export and new pictures;
  the input digests in `docs/assets/profiles/SHA256SUMS` (the pictures) and `docs/assets/SHA256SUMS`
  (the animation) show when they are stale.
- The folk song stays in the tests' sample scenes.
