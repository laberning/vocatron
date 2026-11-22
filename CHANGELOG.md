# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - unreleased

The first public release: a song and its lyrics become a karaoke video, locally, from one command.
German and English songs are supported.

### Lyrics

- Uses the lyrics file next to the song (`Song.lrc` or `Song.txt`), or looks them up on LRCLIB and
  writes them next to the song; `lyrics.lookup: false` never asks.
- Cleans the lyrics for the timing: section headings, repeat markers and credit lines are removed
  and reported; a symbol the bundled font cannot draw is dropped and the song is marked for review
  with the line and the character.
- Detects the language of the text (German or English), or takes `--language`.
- Reads singer marks (`{1}` to `{5}`, `{all}`, groups such as `{1,3}`) for duets and groups, with
  singer names and colours in the lyrics file; a mark may change the singer inside a line.
- Reads `.lrc` line times as hints and checks them against the singing; a lyrics file that Vocatron
  wrote carries a mark, so it is told apart from your own file.
- Gives every song a lyrics status (`ok` or `review`, with the reasons); `vocatron lyrics show` and
  `vocatron lyrics approve` look at the lyrics and approve them without the heavy stages.

### Vocals

- Separates the lead vocals, the backing vocals and the instrumental with BS-Roformer models and
  writes the karaoke track (the instrumental plus the backing vocals, or without them with
  `--no-backing`) as 24-bit FLAC stems.
- Runs the models in a child process with a timeout, a 75 % GPU memory cap and half precision; on
  the CPU when there is no usable GPU (`--device auto|cuda|cpu`), about 20 times slower.
- Lets you choose the models with `separation.model` and `separation.karaoke_model`, also an
  ensemble of two vocals models.
- Downloads each model the first time a song needs it, resumable and checked against a stored
  SHA-256; `vocatron models` lists them with state, size and licence, `vocatron models download`
  fetches them in advance, and `--offline` never downloads. Without a name or a language it
  fetches the models of an English song (`--language de` for German).

### Timing

- Times every word and every syllable to the lead vocals with an own CTC alignment on wav2vec2
  (`wav2vec2-en` for English, `wav2vec2-de` for German); numbers are spelled out for the model and
  shown as written, syllables come from hyphenation dictionaries.
- Guides the alignment with the `.lrc` line times and the loudness of the lead vocals, and also
  listens to the backing vocals where the lead is silent.
- Places an estimated word where the singing voice sounds, and ends a measured word where the voice
  stops, so held notes are highlighted as long as they are sung.
- Measures the tempo of every song for the countdown.
- Writes a quality report that feeds the status of the song.

### Video and looks

- Renders an MP4 (H.264 and AAC, 960x720 at 30 frames per second by default) with the lyrics
  highlighted syllable by syllable, a title screen, a countdown, break and end screens, and duets
  in colours; the enhanced LRC with the same timing is written next to it.
- Comes with ten looks: seven classic ones (`four-line-stack`, the default, `two-line-turns`,
  `full-page`, `blue-page`, `one-line-preview`, `tall-page`, `three-line`) and three modern ones for
  the video only (`neon`, `lyric-video`, `lyric-scroll`). Single values change with
  `profile_overrides`, and your own looks are YAML files that `vocatron profiles check` checks
  without rendering.
- Offers the output presets `4x3-720` (default), `16x9-720`, `16x9-1080`, `av1-720` and
  `4x3-720-nvenc`; the look is laid out again for the frame size of each.
- Writes the tags of the video itself: title, artist, the genre `Karaoke` and a comment; a song
  with two to five singers in its lyrics also gets the field `TAG` with `Duet`, `Trio`, `Quartet`
  or `Quintet`.
- Writes only the video and the lyrics by default; `audio.export: m4a` or `flac` also keeps the
  karaoke audio as a file of its own.
- Encodes the audio with `fdkaac` (or ffmpeg's own AAC encoder when you set it) and draws all text
  in the bundled Noto Sans Bold inside the TV-safe area.
- Shows each look in a picture on the Looks page and in an overview of all ten, and the default look
  as a short animation at the top of the README and the start page.

### CD+G

- Makes `Song.mp3` and `Song.cdg` from the same layout with `outputs: [mp4, cdg]` or `--cdg`;
  `cdg_zip: true` packs the pair into one zip. The MP3 carries the same tags as the video.
- Draws the seven classic looks on the 300x216 CD+G screen of 16 colours and checks it with
  `vocatron profiles check`; a dense song falls back in fixed steps and is marked for review when
  it is still not in time.

### Commands and status

- `vocatron make` runs the whole pipeline on a song or a folder, with `--output`, `--config`,
  `--force`, `--language`, `--no-backing`, `--device`, `--profile`, `--preset`, `--cdg`, `--log`
  and `--offline`; a failing song does not stop the others.
- `vocatron render` makes the video again from the work folders without the AI stages.
- Gives every song one summary line (`ok`, `review` or `failed`, with the reasons) and writes them
  to `vocatron-report.txt`; `vocatron status` prints them without running anything.
- Makes only what changed when you fix a lyrics file or a setting and run again.
- `vocatron profiles`, `vocatron models` and `vocatron doctor` list the looks and the models and
  check that the machine is ready.

### Installation

- `make setup` creates the environment, installs PyTorch (CUDA or CPU) and checks ffmpeg and
  `fdkaac`; everything stays inside the project folder.
- `make install` links the `vocatron` command into `~/.local/bin` (or `BINDIR`) so it works from any
  folder, and `make uninstall` removes the link.
- `make demo-songs` downloads two freely licensed demo songs, the English duet "My Favorite
  Regret" by Josh Woodward feat. Katie Pederson (CC BY 4.0) and the German "Verdächtig" by
  Systemabsturz (CC0); their lyrics are in `tests/data/demo/`.
- Runs on Linux, WSL2 included, with an NVIDIA GPU of 6 GiB or more recommended; it is run from a
  clone and not on PyPI. Vocatron is MIT licensed; the models are downloaded, never shipped, and
  keep their own licences (several state none, one is GPL-3.0; see `THIRD_PARTY.md`).
