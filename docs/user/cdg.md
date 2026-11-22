# CD+G karaoke files

How to make, play and tune CD+G files. CD+G is the classic karaoke format: an MP3 and a small
graphics file with the same name, played by karaoke players (hardware as well as software) and
many karaoke programs. Vocatron writes it from the same lyrics and timing as the video, so the
lines appear and are sung at the same moments.

## Switch it on

CD+G is off by default. Add `cdg` to `outputs` in the [configuration](config.md):

```yaml
outputs: [mp4, cdg]
```

A run then writes two more files next to the video in the output folder:

| File | Content |
|---|---|
| `Artist - Title.mp3` | The karaoke audio (with the silent intro, if the song has one) as MP3: LAME, 192 kbit/s, 44.1 kHz, stereo. |
| `Artist - Title.cdg` | The graphics: 300 packets per second on a 300×216 screen of 16 colours. |

Tags: the MP3 carries the same tags as the video (ID3 version 2.4).

- Title, artist (left out when the song has none), the genre `Karaoke` and the comment `Karaoke
  version made with Vocatron`.
- They come from the song's identity, the same as the file name and the title card; nothing else
  of your file's tags is copied.
- Vocatron writes the MP3's tag itself, so title, artist, genre and comment show in Windows
  Explorer and in players.
- A song with two to five singers also gets the user-defined field `TAG` (an ID3 `TXXX` frame) with
  `Duet`, `Trio`, `Quartet` or `Quintet`, as in the video: the number of different singer numbers in
  the lyrics, where `all` and groups add none. One singer, or none, gives no `TAG`.

### One zip

With `cdg_zip: true` in the [configuration](config.md) the two files are packed into one
`Artist - Title.zip` instead, as MP3+G collections are usually shared, and are not written loose.

- The zip holds the MP3 and then the graphics under their usual names, with the same MP3 (tags
  included) as the loose file.
- The same song and settings give the same zip, byte for byte.
- The setting is off by default; changing it runs only the `cdg` stage again and never renders
  the video.

### What runs

- `mp4` always stays in the list.
- Turning `cdg` on or off never renders the video again: only a new stage called `cdg` runs, and it
  runs again when the MP3 or the CD+G file is missing.
- The stage never writes over your song or its lyrics file: if the output folder is the folder of
  the song, it stops with `output-collision` and asks for another `--output`.
- `vocatron render` runs it too, so a new look is drawn for the video and for CD+G in one go.
- The MP3 needs an ffmpeg with libmp3lame (the Ubuntu package has it); `vocatron doctor` checks for
  it while `cdg` is in `outputs`.
- The look must be made for CD+G, see [below](#which-looks-work). A look that is not fails the
  `cdg` stage of each song with `cdg-not-made-for-cdg`; the video is made all the same.

## How to play it

- Keep the two files together and keep their names.
- VLC plays the pair when you open the `.mp3` or the `.cdg`: it looks for the other file with the
  same name.
- Most karaoke players and programs want the same two files side by side, or in one zip
  (`cdg_zip: true`); some players load the zip directly.
- The MP3 starts about 25 ms late on players that do not read the encoder delay that LAME writes
  into the file; that is far inside what you see (the sync is good to about 200 ms).

## What it looks like

CD+G is a small, coarse screen, so the picture is the video's, simplified:

- The text area is the inner 288×192 pixels; the outer ring is the border.
- The same font, drawn at a size in pixels that each look chooses (see below) with one soft edge
  level. A line is 20 to 24 pixels high, 36 in `three-line`, smaller than the large letters of classic
  discs.
- The colours are rounded to 12 bits and there are at most 16 of them. A look whose colours do
  not fit stops the stage with `cdg-palette` and names them; the video is made anyway. The
  built-in looks fit with room for all five singers and the group. The start screen has its own
  16 colours, see [below](#the-start-screen).
- An outline is drawn only where its colour differs from the background, shadows are dropped and
  fades become cuts. There is no key for either.
- The start screen is the video's: the wordmark in pixel letters, see [below](#the-start-screen).
- The seconds timer of a break screen (`breaks.form: timer`) is drawn too: one number a second,
  centred under the text.
- The colour sweep and the countdown move in steps of a few pixels (3 in the built-in looks),
  which a player draws as one small change per step.

## The start screen

A look with `title.form: wordmark` (the default) opens the CD+G with the same screen as the video:
the Vocatron wordmark, a rounded frame with the title, a short rule, the artist and the singers'
names. CD+G has 16 colours for the whole song, so the screen is drawn in its own way:

- The letters are pixel letters, drawn by hand for this size: eight letters of 9 by 11 cells, each
  cell 3 by 3 pixels, banded from yellow through red to violet, with a one-pixel cyan edge, on the
  dark field. The border has the field's colour. The frame has one pixel, the texts are in capitals
  without the soft edge level, the title in white, the artist and the rule in amber, the singers'
  names in the colours of their lines.
- The screen has its own colours: the dark field, the cyan, the seven bands, white and one entry for
  each name colour (room for five singers and a group). When the screen ends, the whole screen is
  cleared and the colours of the song are loaded, so the song looks exactly as it would without
  the start screen. The song's own colours do not count the start screen's.
- There is no build-up: the screen is drawn as fast as the format allows, the wordmark first, and is
  complete within three seconds, also with a long title, a long artist and five singers and a
  group (about two seconds is what the format's bandwidth allows). The start screen of every
  built-in look lasts at least four seconds, and the first lines are drawn after it, within their
  lead-in.
- The texts have sizes of their own, the same in every look and independent of the look's line
  size: the title 22 pixels, the artist 15 and the singers' names 13. A title or artist too wide
  for the frame wraps onto two lines at a word before it is made smaller, as in the video; the two
  lines have one size and stand closer together than separate texts. The singers' names (and the
  group) stand side by side, each in its colour, as many to a row as fit, spread evenly over as few
  rows as needed: four long names stand two and two, not three and one. One name to a row only
  when that gives larger text.
- No text is smaller than 12 pixels. If one would be (a title of about 100 characters, or several
  names too long to stand two to a row), the song gets the plain card of text instead.
  `cdg.min_font_px` does not apply to the start screen.
- A look with `title.form: plain` gets the plain card of text. A look of your own whose
  start screen is shorter than four seconds (a small `title.min_short` and an early first line)
  also gets the plain card on CD+G, because the wordmark screen would not be drawn in time.
- The break and end screens stay the plain card in the song's colours.

## Which looks work

- The seven classic built-in looks are made for CD+G, and `vocatron profiles` says so in its CD+G
  column. [Looks](looks.md) shows each one on the CD+G screen, at twice its size, below its video
  picture: the same six moments of the duet "My Favorite Regret" (Josh Woodward feat. Katie Pederson, CC BY 4.0).
- The three modern looks `neon`, `lyric-video` and `lyric-scroll` are for the video only: glow,
  growing words, fades, a moving background and text that glides cannot be drawn on the CD+G
  screen, so they have no `cdg` section and `outputs: [mp4, cdg]` makes only the video for them.

A look says how it is simplified for CD+G in an optional `cdg` section:

```yaml
cdg:
  made_for_cdg: true   # the marker; without it the look is MP4 only
  slots: 4             # lines on screen at most; may be fewer than the video's
  font_px: 24          # the height of a line in pixels (on the 192 pixel high text area)
  min_font_px: 18      # a line is never made smaller than this
  edge_px: 1           # the outline: 1 or 2 pixels
  wipe_columns: 3      # pixels per step of the sweep: 1, 2, 3 or 6
  colours: {}          # optional #rgb or #rrggbb for the colours that CD+G shows differently
```

- `colours` has the keys of the video's colours (`singer1` to `singer5` and `group`, each with
  `unsung`, `sung` and `edge`) and `background`. A colour you leave out is the video's colour
  rounded to the nearest 12-bit value. `#f0a` is the colour `#ff00aa`.
- The video's `slots`, `font` and `edge.width` do not count on CD+G, nor does `shadow` or
  `ending.fade`; the `cdg` section does. Everything else (mode, countdown, breaks, title, timing)
  is the video's.
- A look without the section, or with `made_for_cdg: false`, is MP4 only. Own looks and the
  looks that come later for the video only leave the section out.
- The section is checked with the rest of the profile and errors name file, line and column,
  also where it breaks a rule of the profile (for example `cdg.slots` below `page.min_lines`).
- `profile_overrides` can change it: `profile_overrides: {cdg: {wipe_columns: 6}}`. An override
  of the video's `slots`, `mode`, `page` or `preview` may need `cdg.slots` changed too; the error
  says so. A section with `made_for_cdg: false` is not used and not held to these rules.

A look with the marker is also checked on the CD+G screen by `vocatron profiles check`
([Commands](commands.md#profiles-check)). Each problem names the `cdg` key that fixes it.

- The colours fit the 16 entries with all five singers and the group.
- The contrast rules hold on the 12-bit colours.
- No line is too wide at `min_font_px`, and the slots fit the text area.
- On the sample songs, one dense invented song and one whose pages follow each other at once, every
  line is fully drawn before its first syllable and the sweep is at most 50 ms behind.

### When a song is too dense

A song can be denser than the samples: lines that follow each other fast leave little time to
draw. The stage then falls back in fixed steps, until every line is drawn before it is sung and
the sweep keeps up.

1. **Line by line** (page looks `blue-page`, `full-page`, `tall-page` only; `page.turn: line`): the
   page turns line by line for the whole song. As soon as a line of the old page has been sung, the
   line of the next page for that slot takes its place, so the next page builds from the top while
   the old one is still sung, and a page that follows with no pause is complete when its first line
   is sung. A song that is in time with whole pages keeps them.
2. The line appears earlier: the look's minimum lead-in raised to its target, then to its maximum.
3. The sweep gets coarser (6 pixels).

`cdg.json` records the step taken and what was used. If no step is enough, the last one is written
all the same, the song log says `cdg: warning: not in time ...` and the song gets the status
`review` with the reason "CD+G not in time" and the number of late lines and the lag of the sweep.
A look that the check passes rarely needs a step.

In a page look (`mode: page`), whatever the step, a change of text never shows old and new letters
together: the writer clears every tile that shows other text (a packet that fills it with the
background) before it draws the new text, clears all changing tiles of a change first and then
draws them from the top. A page therefore needs a little more of the bandwidth than a plain
redraw. Line looks (`mode: line`) redraw a replaced line straight from the old text into the new
one.

## What you find in the work folder

`cdg.json` records the files made (or the zip), the CD+G values used, the fallback step taken and
whether the song was in time, the 16 colours, the number of packets and the longest wait of a
drawing and of a wipe step in seconds (how late a change came after the moment it was due).
With CD+G off it only says so. See [Files and folders](folders.md).

For how it works and how it is tested, see [CD+G: writer, decoder and analysis](../dev/cdg.md).
