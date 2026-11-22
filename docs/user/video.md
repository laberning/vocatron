# The karaoke video

What the video contains, how it looks and how to make it again. `vocatron make` ends with an MP4
that plays anywhere, with the instrumental (and the backing vocals, unless you take them out) and
the lyrics in the classic karaoke style, drawn onto a plain black background, which suits players
that decorate the video. `vocatron render` makes the video again from the work folder in seconds,
for example with another look or another size; no AI stage runs again.

## What you get

All files go to the output folder and are named after the song:

| File | Content |
|---|---|
| `Artist - Title.mp4` | The karaoke video: H.264 and AAC, 960×720 (4:3) at 30 frames per second by default. |
| `Artist - Title.lrc` | The timed lyrics as enhanced LRC: a time tag per line and one per word, the lines in time order, and `{&}` before a line the second voice sings. Players and editors that know only plain LRC ignore the word times. |

Only the video and the lyrics are made by default. For the karaoke audio as a file of its own,
set `audio.export: m4a` (the very same AAC stream that is in the video, not encoded a second time)
or `audio.export: flac` (the lossless karaoke audio) in the [configuration](config.md). When you
make a song again with the export off, Vocatron deletes the export it made for it, and no other
file. An export with the very name of the song file (`Artist - Title.m4a` made from
`Artist - Title.m4a`) is left, so that the song itself is never at risk.

Tags: the video carries tags, so players and libraries show it by name.

- The title, the artist (left out when the song has none), the genre `Karaoke` and the comment
  `Karaoke version made with Vocatron`.
- Title and artist are those of the file name and the title card: your file's own tags first, else
  the `Artist - Title` of its file name. Nothing else of your file's tags (album, year, cover) is
  copied.
- A song with two to five singers in its lyrics also gets the field `TAG` with `Duet`, `Trio`,
  `Quartet` or `Quintet`, which tag editors such as Mp3tag show as `TAG`. The count is the number of
  different singer numbers in the marks; lines sung by `all` or by a group (`1,3`) add none. A song
  with one singer, or without marks, gets no `TAG`, even when its name says duet.
- Vocatron writes the tags of the MP4 itself after the encoder has finished.

CD+G: for karaoke players that expect it, add `cdg` to `outputs` (see [CD+G](cdg.md)); the MP3 and
the graphics file are made from the same layout.

Vocatron never writes over your song or its lyrics file: if the output folder is the folder of the
song, the render stops with an `output-collision` error and asks for another `--output`.

## What it looks like

There are ten looks (profiles), chosen by name with `profile` in the [configuration](config.md) or
`--profile` on the command line. The default is `four-line-stack` (`profile: two-line-turns` gives
the plainer two-line look).
[Looks](looks.md) shows a picture of each, lists them with `vocatron profiles` and tells how to
make your own.

The text below describes `two-line-turns`, the plainest of them. It has two lines of large, edged white text in the lower third of the screen.

- The sung part of a line turns blue, pink, green, orange or orchid for singers 1 to 5, or yellow
  for `{all}` and for words of several singers.
- It sweeps left to right in time with each syllable.
- A line whose singers change at a word is drawn in each singer's colour from that word on.
- Lyrics-file colours (`[singer1: Anna, #22aa55]`) replace the profile's colours; see
  [Lyrics](lyrics.md).

### Two lines sung at once

When two voices sing different lines at the same time, or the second starts before the first has
finished ([Lyrics](lyrics.md)), both lines are on screen before either starts and light up at the
same time. The second voice's line stands in the slot below the first voice's line, also when it
starts first. A line that is too long for one row and is split into rows is shown with all its
rows: the rows of the second voice's line stand below the rows of the first voice's line. In
`four-line-stack`, which turns two lines at a time, a first-voice line and a second-voice line of
two rows do not fit one block of two lines; they take both blocks while they are sung, and the
next lines wait until both are sung. A line that comes while the second voice is still singing
takes a place whose line has been sung already; in `four-line-stack` the lines of a group also come one
by one when their block would only be free less than a second before they start while the other
voice is still singing, so they are not shown late. Where a place below is still taken by a line being sung, the
line comes as soon as that line ends; where not enough places next to each other are free or the
look has too few lines for all the rows, the lines of the two voices take a place each. A
second-voice line that is sung over two lines of the first voice keeps its place until it ends;
the next line of the first voice takes the next free place. A line is never
replaced while it is being sung. A second-voice line without a singer mark at its start is drawn in
the colour of singer 2. The looks with several lines (`four-line-stack`, `two-line-turns`,
`three-line`, `neon` and `lyric-video`) do this; the page looks, `one-line-preview` and
`lyric-scroll` have no place for two lines at once yet, and show such lines one after the other,
each until the next one starts. The layout notes it in the log of the song.

In the page looks the whole page goes at once, then the next page comes: it appears when the page
before has been sung and the hold is over, but not later than the target lead-in before its first
line (the hold gives way to the lead-in). Pages are cut at every long pause and otherwise where
the singing pauses longest. Where the singing runs on without a pause, the first line of a new
page may have less lead-in than the minimum, and the song log says so.

All text stays inside the TV-safe area (90 % of the picture), whatever the size of the video.

### What is on screen when

#### Intro

A song whose first word is sung too early gets silence at the start, only as much as is missing.

- The first word comes after eight seconds in a song with one singer, after nine in a duet or group
  (more than one singer, or lines sung together). A song that starts late enough gets none.
- The silence is in everything Vocatron writes: the video, the audio in the MP4 and the M4A, the
  FLAC export, and the times and `length` of the `.lrc`, so the `.lrc` fits the video, not the
  original audio file. Your own lyrics file stays as it is.
- The `intro` setting of the look changes the two times, and `0` switches the intro off; see
  [Looks](looks.md).

#### Title screen

Shown from the start. In the default form (`title.form: wordmark`) it is the same in every look:
the Vocatron wordmark (eight banded letters with a glowing cyan edge) at the top on its own dark
field, and below it a rounded cyan frame with the song title in white, a short amber rule, the
artist in amber (both in capitals) and, where the lyrics file names singers, their names in their
colours. The look's background starts when the screen ends. With `title.form: plain` the screen
is a card of centred text in the colours of the look: title, artist and the singers' names. The
[CD+G](cdg.md#the-start-screen) output follows `title.form` too, in a pixel form. The setting
also decides the [break screen](#break-screen) and the [end screen](#end-screen) in the video:
`wordmark` gives the mark on all three, `plain` on none.

- A screen that lasts at least four seconds builds up in about two seconds, then stands still: the
  edge of the letters fades in, the colour bands fill VO, then CA, then TRON, then the frame and
  the texts wipe in from the left. A shorter screen (the singing starts early) shows the finished
  screen from its first frame.
- A song with lines sung together also lists the group in the group colour: the singers' names
  joined by "&" (Anna & Ben), or, for a group of all singers, the word of the song's language
  ("Beide" or "Alle", "Both" or "All"). A group is listed only when all its members have names.
- With the wordmark, a title or artist too wide for the frame is first wrapped onto two lines at
  a word (the one nearest its middle, as a sung line is); the two lines have one size and stand
  closer together than separate texts. Only if that is not enough, or with many singers, are the
  texts made smaller until everything fits inside the frame; the plain card makes a long title or
  artist smaller until it fits on the screen. A single long word is made smaller. With the
  wordmark the singers' names (and the group) stand side by side, as many to a row as fit and
  spread evenly over as few rows as needed (two and two rather than three and one); one name to a
  row only when that gives larger text.
- It is shown until the first line appears: at least six seconds if the song leaves room for it,
  shortened (down to four seconds) if the singing starts early. With the intro it has five seconds
  in a song with one singer and six in a duet. A look of your own sets these with `title.min` and
  `title.min_short`; a `title.min` below four seconds also lowers `title.min_short` to it unless
  the look sets that too.

#### Lead-in

- A line is on screen up to five seconds before its first syllable (one second at the least), the
  first line after the title three seconds, as on classic karaoke discs.
- The next line takes the place of the line that finished first, as soon as the other line has
  started to be sung, or earlier if it would otherwise get less than one second.
- With three lines or more on screen, the parts of a line split because it is too long sit in
  neighbouring places, from the top down, so they read in order.

#### Hold

- A sung line stays until its place is needed, so the screen is never empty in a pause under five
  seconds.
- Before a longer pause the lines stay for two seconds after the singing stops.
- Lines leave in the order they were sung. After a longer pause the lines fill the places from the
  top again, as at the start of the song, and appear with their normal lead-in.

#### Countdown

Before the first line and after every gap of five seconds or more: a bar above the lines (or dots,
or blocks) that counts four beats of the song's tempo and ends one beat before the line is sung, so
you come in on the next beat, as when a band counts in. The dots or blocks go out one per beat, and
the bar shrinks over the same time.

- The look's `countdown.count` is the number of beats and of steps ([Looks](looks.md)).
- Vocatron measures the tempo of every song (stage `tempo`, file `tempo.json`) from the
  instrumental.
- A beat that would make four beats shorter than 1.5 seconds or longer than four is doubled or
  halved, so a countdown always lasts between 1.5 and four seconds.
- A countdown never starts while the line before is still sung: where that line, the title or the
  break screen leaves less room, the countdown starts on the first whole beat after it and has
  fewer steps; with less than one beat of room there is none. This matters only in an own look
  whose `countdown.min_gap` is shorter than its countdown.
- If the tempo is unclear (a song without a steady beat, or one whose tempo changes), the
  countdown runs over a fixed number of seconds (2.4 by default) instead, ending when the line is
  sung; `report.json` says which it was, and the song is still `ok`.

#### Break screen

The text "Instrumental" after a gap of fifteen seconds or more.

- In the default form (`title.form: wordmark`) the V of the Vocatron wordmark stands above the
  text, finished as on the start screen: the seven colour bands, the glowing cyan edge and the
  thin light line, but without the dark field and without a build-up. It is about one and a half
  text rows high, with half a row between it and the text, and the text keeps the colours of the
  look. With `title.form: plain` the screen is the text alone.
- A look can add a progress bar under it (`breaks.form: progress`) or the whole seconds until the
  next lines appear, counting down (`breaks.form: timer`, the look `three-line`). The timer goes
  with the screen, which ends when the next lines appear. They stay below the text; the V belongs
  to the text and stands above it.
- In a scrolling look the break screen stands alone and still in the middle as well: the lines
  fade out before it and the column glides in from below when it ends; see [Looks](looks.md).

#### End screen

Two seconds after the last line, fading out at the end. The last lines are gone by the time it
starts, even in a look that holds them longer. In the default form (`title.form: wordmark`) it is
the title screen as it stands when it is finished: the wordmark on its dark field, the frame
with title, artist and the singers' names, without the build-up. Field, letters and frame fade
out together. With `title.form: plain` it is title and artist as a card of centred text in the
colours of the look. The [CD+G](cdg.md) output has the plain card here.

#### Duets

- Lines are never merged. A line sung together is one line in the group colour, and a line that
  changes singers at a word changes colour there.
- Lines that are too long are split at the word nearest the middle (each half keeps its singers),
  and shrunk only if one word alone does not fit.
- With `line_rows: 2` (the look `one-line-preview`) such a line is instead wrapped onto two rows
  that stay on screen together; see [Looks](looks.md).
- In page mode `page.slot_per_row` gives each row a slot of its own, so six rows of a page can hold
  three lines of two rows (the look `tall-page`).

## Presets: the shape of the file

A preset chooses the frame size, frame rate and video codec. Select one with `preset` in the
[configuration](config.md) or `--preset` on the command line.

| Preset | Frame | Video | Notes |
|---|---|---|---|
| `4x3-720` | 960×720 | H.264 (libx264, CRF 18) | the default; classic karaoke is 4:3 |
| `16x9-720` | 1280×720 | H.264 | for modern screens |
| `16x9-1080` | 1920×1080 | H.264 | |
| `av1-720` | 960×720 | AV1 (SVT-AV1) | opt-in; many players cannot play AV1 |
| `4x3-720-nvenc` | 960×720 | H.264 (NVENC) | opt-in; needs an NVIDIA GPU, faster |

The look is laid out again for the frame you choose (the sizes are shares of the safe area), so
the same style fits 4:3 and 16:9.

Every video is converted to the BT.709 colour space with limited (TV) range and carries those
tags, so that players show the colours of a look alike.

## The audio

The karaoke audio is encoded once, as AAC with the Fraunhofer FDK encoder (`fdkaac`) at 192
kbit/s, and that stream goes into the MP4, and into the `.m4a` if you ask for the export, unchanged.

`fdkaac` is a program you install (see [Installation](install.md)); `vocatron doctor` checks it.
There is no automatic fallback, so that the same song and settings give the same file on every
machine. If you cannot install `fdkaac`, say so explicitly:

```yaml
audio:
  encoder: ffmpeg-aac   # ffmpeg's own AAC encoder, 256 kbit/s unless you set audio.bitrate
```

## Changing the look

Choose another built-in look, override single values, or make your own look in a file: see
[Looks](looks.md). A profile that breaks the contrast rules still renders, and the song is marked
`review` with the colours that are hard to read as its reasons. `vocatron profiles check` finds
such problems before a song is made.

## Making the video again

```sh
vocatron render ~/Music/party/Song.mp3 --profile looks/mine.yaml
vocatron render ~/Music/party --preset 16x9-720
```

- `vocatron render` runs the layout and the render only. The song must have been made with
  `vocatron make` before.
- A new profile or preset takes a moment for the layout and about the length of the song for the
  video; the separation and the alignment are not touched.
- Changing the profile file, `profile`, `profile_overrides`, `preset` or `audio` in the
  configuration and running `vocatron make` again does the same: only the stages that depend on
  the change run.
