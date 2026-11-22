---
id: ADR-0041
status: accepted
date: 2026-11-04
superseded_by: null
---
# ADR-0041: CD+G page changes without mixed letters

Supersedes ADR-0029 in part: the fallback steps get a first step for page looks, and a song that
is still late after the last step needs review instead of only a warning in its log. Everything
else of ADR-0029 stays as it is.

## Context and problem

Page mode turns the page at the earliest when the old page has been sung; when the next page's
first line follows without a pause, the turn is at that line's first syllable. The video draws a
page at once. CD+G sends about 300 packets a second, and a page takes about 650 of them, so the
new page arrives over two seconds after its first line should be sung. Meanwhile the writer
redraws every tile straight from the old text into the new one, so letters of both pages share
the screen. This happens at every page change, also after a pause, and in a short form wherever a
line takes the place of another.

The CD+G check did not see it: a deadline (a line fully drawn when it is sung) was judged against
the frame of the tick before, which still showed the old page, and the sample songs always paused
before a new page. The fallback steps of ADR-0029 (more lead-in, a coarser wipe) cannot help,
because a page turn never comes before the old page is sung.

## Considered options

1. Keep the whole-page turn, but clear the screen first and draw the new page from the top. No
   mixed letters, but without a pause the first line is still about half a second late.
2. Turn page looks line by line on CD+G: once a line of the old page is sung, the line of the new
   page for that slot takes its place. Classic CD+G discs commonly do this. As the default of every
   CD+G page look, or as a fallback step only for the songs that are late with whole-page turns.
3. Turn line by line in the video too.

## Decision

Option 2 as a fallback step, and the clearing of option 1 for the page looks.

- A profile key `page.turn` (`page` or `line`, default `page`, only with `mode: page`). With
  `line`, inside a run of lines between long gaps (`breaks.clear_after`), the line of the next
  page for a slot appears once the old page's line in that slot has been sung plus
  `clear.replace_after`, and never after its own first syllable; a slot the old page did not use
  is filled when the old page's first line is freed. After a long gap the whole page turns as
  before. The built-in looks do not set the key, so the video does not change.
- For page looks the CD+G fallback gets a first step "line by line" right after the look as
  declared; the later steps (lead-in, coarser wipe) keep it. A song that is in time with
  whole-page turns keeps them, so a song never mixes both kinds of turn.
- The CD+G writer clears before it draws in page looks (`mode: page`): a tile of text that
  appears or goes whose screen shows anything but the background is filled with the background
  first, then drawn; tiles stay in row order, so new text arrives from the top. Line looks keep
  the direct redraw: the clearing costs one packet more per tile, and looks that replace a line
  within half a second (one-line-preview, four-line-stack) then miss the timing of the CD+G check.
- A deadline is judged against the frame in which the line is first shown, if that is later than
  the tick before it is sung, so a line that appears only when it is sung fails until it is drawn.
- A song that is still late after the last fallback step needs review: the `cdg` stage gives the
  reason "CD+G not in time" with the late lines and the wipe lag. The log line stays.

## Consequences

- No mixed letters at page changes on CD+G, and new pages complete in time where a song allows
  it; songs in time keep their page turns, but every CD+G file of a page look changes a little
  through the clearing (one more packet per changed tile). The CD+G files of line looks do not
  change; a line that replaces another may still show parts of both for a moment there.
- On a late page-look song the top of the screen shows the next page while the bottom is still
  sung; sung and unsung colours keep them apart.
- A song denser than CD+G can draw (a new line about every half second, as in the ending of the
  German demo song) stays late in places even line by line; it needs review.
- Rule 10 (pages) checks the line turn when `page.turn` is `line`: a page may be torn, but every
  line appears after its slot is free and before it is sung.
- The `cdg` stage version rises; the layout stage gives the same `layout.json` as before.
