# Lyrics

Where the lyrics come from, how to write them, and how to approve them. Good lyrics are the most
important input: the sync can only be as good as the text.

Vocatron uses your lyrics file if there is one, otherwise it looks the lyrics up, and in both
cases it tells you how far they can be trusted.

## Where the lyrics come from

1. **Your file** next to the song with the same name: `Song.lrc` or `Song.txt` (`Song.lrc` wins if
   both exist). The name is exactly the song's, only the extension differs, and upper and lower
   case count (only a Windows drive or a Mac, whose file systems ignore case, also find another
   case): `Queen - Bicycle Race.mp3` takes `Queen - Bicycle Race.txt`. It is always used, and
   Vocatron never changes it.
2. **A lookup** on [LRCLIB](https://lrclib.net), otherwise. See below.
3. **Nothing:** the song fails with `no lyrics found`; put a `Song.txt` next to it.

### The lookup

- It searches by artist, title and length (from the tags, the file name as fallback).
- Records of another artist or title are dropped, the remaining versions are grouped by text and
  the version most of them agree on is used.
- The result is written next to the song: `Song.lrc` if LRCLIB has synced lyrics whose length is
  within 2 seconds of your recording, else `Song.txt`. This is the only file Vocatron writes into
  your song folder.
- Its first row marks it as Vocatron's, with a check of its content: `[re: Vocatron 3f2a…]` in an
  `.lrc` (the usual creator tag, which players ignore) or `written_by: "Vocatron 3f2a…"` in a
  `---` block at the top of a `.txt`. So Vocatron still knows the file is its own in a work folder
  that does not remember writing it. Once you change the file in any way (even its line endings),
  the check does not fit and the file is yours.
- LRCLIB has no stated licence for its data, so the lyrics are fetched for your own files and are
  not meant to be shared. Set `lyrics.lookup: false` to never ask.

### Cleaning and language

The lyrics stage cleans what it found for the alignment:

- Section headings (`[Chorus]`, `Refrain:`), repeat markers (`(2x)`, `x2`) and credit lines
  (`Written by ...`) are removed, and each removal is reported.
- Lines without a letter or digit (`---`, `♪`) are dropped like empty lines.
- A symbol that Vocatron's font cannot draw (for example `√` or a heart in the middle of a line)
  is dropped from its line, and the song is marked for review with the line and the character.
  Note signs (`♩ ♪ ♫ ♬`) are decoration and are dropped without a reason; the invisible parts
  of an emoji go with a dropped emoji, and a tab becomes a plain space.
  A letter, accent or digit that the font cannot draw (a script it does not cover, such as Thai)
  stops the song at once, with the line and the character.
- The original text stays in `lyrics.json` in the work folder.

It also detects the language (German and English, see [Languages](languages.md)); a song in
another language fails with a message that names the language. To skip the detection, name the
language with `lyrics.language: de` in the [configuration](config.md) or `--language de` on the
command line.

## The format

Plain text or LRC, UTF-8, **one line per sung phrase, every repeat written out** (no `(2x)`);
blank lines separate blocks.

```text
Alle meine Entchen
schwimmen auf dem See
schwimmen auf dem See

Köpfchen in das Wasser
Schwänzchen in die Höh
```

### Duets and groups

A singer mark is written in braces: `{1}` to `{5}`, `{all}`, or a group such as `{1,3}` (no
spaces; `all` in lower case).

- Put it at the start of a line or in front of a word inside a line.
- From there on the marked singers sing, also on the following lines, until the next mark.
- Words before the first mark are sung by singer 1.
- So a line can change singers at a word: `{1} walk with me {2} hold me`.

```text
---
singers:
  1: {name: Anna, colour: "#e0b000"}
  2: Ben
---
{1} Hänschen klein
{2} ging allein
{all} in die weite Welt hinein
{1,2} Stock und Hut
steht {1} ihm gut
```

Rules for marks:

- Only these exact forms are marks. Any other text in braces is ordinary lyrics.
- A line that starts with `1:`, `all:`, `M:`, `F:` or `D:` is ordinary lyrics too.
- A mark glued to the front of a word (`{2}hold`) counts; one glued to its end (`hold{2}`) does not.
- A mark at the end of a line holds from the next line.
- Marks are never shown on screen. The singer marks never reach the alignment; the voice mark
  `{&}` does (see below).

The optional block between two `---` lines names the singers and may give their colours
(`#rrggbb`). Names and colours in the file win over those of the style profile. Lines are never
merged: a line sung together is one line in the group colour, and a word is drawn in the colours
of its singers.

### Two voices at once

In some songs a second voice sings a different line while the first is still singing, or starts
before it has finished. Vocatron times each voice on its own, so no line is cut short. The second
voice comes from the file or from the audio:

- **The same time:** two lines of an `.lrc` with the same time tag are sung together; the later
  one is the second voice. Of three lines with one time only the second counts.
- **`{&}` at the start of a line** puts that line on the second voice by hand, for a `.txt` file
  and for what the audio does not find. It can stand before or after a singer mark
  (`{&} {2} ging allein`). In the middle of a line it is ordinary text.
- **The audio:** with line times that fit the recording, a line that the backing vocals hear
  clearly better than the lead, while the lead does not sing it and its lines come faster than
  usual, goes to the second voice too ([Synchronising the lyrics](sync.md)).

In the video, lines of the two voices that are sung at once are on screen together, each in its
own place, and light up at the same time ([The video](video.md)). A second-voice line with a
singer mark at its start keeps that singer's colour; one without a mark there is drawn in the
colour of singer 2, so it stands out from the first voice's line, and a mark in the middle of the
line changes the colour from that word on. A second voice never makes a song a duet:
the title screen, the intro and the `TAG` ignore it. The lines of the second voice and where each
came from (`mark`, `time` or `audio`) are in `report.json`, and the timed lyrics (`.lrc`) mark
each of them with `{&}`, also those the audio found.

A song is a **duet** when its file name or title tag matches `lyrics.duet_pattern` (default
`duet(t)?`, any case). A duet whose lyrics have no singer marks is marked for review.

### `.lrc` files

An `.lrc` file has line times, and Vocatron reads the usual tags (`[ar:]`, `[ti:]`, `[length:]`,
...). Singer marks come after the time tag; names and colours are extra tags that other
players ignore (not tested with every player):

```text
[ti: Hänschen klein]
[length: 03:00]
[singer1: Anna, #e0b000]
[singer2: Ben]
[00:05.00] {1} Hänschen klein
[00:09.00] {2} ging allein
[00:13.50] {all} in die weite {1} Welt hinein
```

The line times are hints, never the truth: the alignment places every word from the audio.

- **Out of order:** a line time later than the time of the next line is reported by
  `vocatron lyrics` and `vocatron lyrics show` as a warning with the line number (counting the
  sung lines) and the time tag. The alignment skips that time and uses the others
  ([Synchronisation](sync.md)).
- **Word times** of enhanced LRC are ignored.
- **`[offset: +500]`** (milliseconds) is applied to every line time: a positive offset shows the
  lyrics earlier, so `[00:05.00]` becomes 4.5 seconds.
- **Review:** a `[length:]` that differs from your recording by more than 2 seconds, or a line that
  starts after the end of the song, marks the song for review.

## Status and review

| Status | Meaning |
|---|---|
| `ok` | The lyrics can be trusted. |
| `review` | The song goes on, but look at the lyrics. The reasons are shown in the song status. |
| `missing` | No lyrics; the song fails. |

Reasons for review:

| Reason | Meaning |
|---|---|
| `unsure match` | Found lyrics of an artist or title that is not exactly the song's. |
| `single source` | Found lyrics that no second version agrees with. |
| `section markers removed` | The cleaning removed section headings. |
| `repeat markers removed` | The cleaning removed repeat markers. |
| `credits removed` | The cleaning removed credit lines. |
| `line 45: dropped U+221A SQUARE ROOT (not in the font)` | The cleaning dropped a symbol the font cannot draw, naming the character and every line it stood in (`lines 3, 7: ...`). |
| `the .lrc does not fit the recording` | See [`.lrc` files](#lrc-files). |
| `duet without singer marks` | The song is a duet, the lyrics have no marks. |
| `found online by an earlier run whose checks are not known here` | A file Vocatron wrote, met in a work folder that does not remember the lookup. |

Lyrics in your own file are trusted, apart from the cleaning, dropped-symbol, `.lrc` and duet reasons.

## Approving

Look at the lyrics file, fix what is wrong and save it. **A changed file counts as approved**
(Vocatron remembers what it wrote, and the mark in the file stops fitting): the song is `ok` at
the next run. If the file is right as it is, approve it without changing it:

```sh
vocatron lyrics show ~/Music/party        # status, reasons and the flagged lines of every song
vocatron lyrics approve ~/Music/party/Queen.mp3
vocatron lyrics ~/Music/party             # probe and lyrics only, without the heavy stages
```

`vocatron lyrics show` prints, for each song, the status, the reasons and the lines that were
removed, with their line numbers in your file (for lyrics that were looked up: in the text as it
was found, which `lyrics.json` keeps). The findings stay on record in `lyrics.json` after
approval.
