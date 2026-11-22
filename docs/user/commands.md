# Commands

Every command, its options, the song states and the exit codes. Read it when you need the exact form.

```sh
vocatron --help
vocatron --version
vocatron make <path>
vocatron render <path>
vocatron status <path>
vocatron lyrics <path>
vocatron lyrics show <path>
vocatron lyrics approve <path>
vocatron models
vocatron models download [name...]
vocatron profiles
vocatron profiles check <name or file>
vocatron profiles copy <built-in> [<name or file>]
vocatron doctor
```

Help for every command comes from the same text as the code documentation: `vocatron make --help`.
What an option overrides, and which value wins, is on the [configuration](config.md#which-value-wins) page.

## make

Runs the pipeline on one song or on every song of a folder.

```sh
vocatron make ~/Music/party
vocatron make ~/Music/party/Queen.mp3 --output ~/karaoke
vocatron make ~/Music/party --profile neon --preset 16x9-1080
```

| Option | Meaning |
|---|---|
| `<path>` | An audio file, or a folder. Of a folder only the audio files directly in it are used (`.mp3 .flac .wav .ogg .opus .m4a`), never subfolders and never the output folder. |
| `--output <folder>` | Output folder; a relative path is relative to the current folder. Overrides `output.folder` of the [configuration](config.md). |
| `--config <file>` | Configuration file; default `vocatron.yaml` in the current folder. |
| `--force` | Run every stage again, even if its result is current. |
| `--language <code>` | The language of the songs (ISO 639-1, for example `de`) instead of the one detected from the lyrics; overrides `lyrics.language`. An unsupported language exits with 2. |
| `--no-backing` | Take the backing vocals out of the karaoke track too; overrides `separation.keep_backing`. See [Separating the vocals](separation.md). |
| `--device auto\|cuda\|cpu` | Where the vocal separation and the alignment run; overrides `separation.device` and `alignment.device`. Default `auto`: the GPU when at least 2 GiB of its memory are free, else the CPU. |
| `--profile <name or file>` | The style profile: a built-in or own name, or a YAML file (relative to the current folder); overrides `profile`. See [Looks](looks.md). |
| `--preset <name>` | The output preset (`4x3-720`, `16x9-720`, `16x9-1080`, `av1-720`, `4x3-720-nvenc`); overrides `preset`. An unknown name exits with 2. |
| `--cdg` | Also make `Song.mp3` and `Song.cdg` in this run: adds `cdg` to `outputs`. See [CD+G](cdg.md). |
| `--log` | Show the log of each song (`log.txt`, including the lines of the separation and alignment processes) as it is written, with the name of the song in front, instead of the live progress display. |
| `--offline` | Never download models. A stage whose models are missing fails and the message names the command that fetches them (`vocatron models download`). Without it, a missing model is downloaded the first time a stage needs it. |

### How a run behaves

- **Stages:** each song goes through them one by one. A stage is skipped when what it reads and the
  settings it depends on are unchanged since it last ran: a second `make` on the same folder does
  nothing, and editing a stage file by hand re-runs only what follows it.
- **Console:** on a terminal, a live line for the batch (songs done, percentage, time elapsed and
  left) and one for the song in work (stage, its progress, time left), with the finished songs
  above them. Without a terminal, one plain line per finished stage and song.
- **Summary:** every finished song gets one line (state, length, processing time, the shortened
  name, and the reasons or the error), cut to the width of the terminal; then a total follows. The
  same lines go, uncut, to `vocatron-report.txt` in the output folder.

```text
ok        5:55   7m 12s  Queen - Radio Ga Ga
failed       -       0s  Broken               probe: cannot read Broken.mp3: unsupported format
2 songs: 1 ok, 0 review, 1 failed in 7m 13s
```

- **Failures:** a song that fails, runs past its safety limit or cannot write its work folder does
  not stop the others; its error is in the summary, the status and its log file.
- **Ctrl-C:** the first one finishes the stage that is running and stops; a second one stops at once.
- **Output folder:** one that cannot be created (no permission, or a file in its place) stops the
  command before any song, with exit code 2.

[Everyday use](everyday.md) walks through the workflow.

## render

Makes the [video](video.md) of a song or of every song of a folder again from the work folders,
without the AI stages. It runs only the probe, the tempo, the layout, the render and the cdg stage
(which does nothing unless `outputs` has `cdg`, see [CD+G](cdg.md)).

```sh
vocatron render ~/Music/party/Song.mp3 --profile looks/mine.yaml --preset 16x9-720
```

| Option | Meaning |
|---|---|
| `<path>`, `--output`, `--config`, `--profile`, `--preset` | As for `make`. |
| `--force` | Render again even if nothing changed. |

A song that was never made fails with the hint to run `vocatron make` first.

## profiles

Lists the [looks](looks.md): the built-in profiles and your own, each with its description, mode,
number of slots, whether it is made for [CD+G](cdg.md) (`yes` or `no`) and source (`built in` or
the file).

- The look the configuration chooses is marked with `*`.
- A file of your profiles folder that does not load is listed as invalid, with a pointer to
  `check`.
- Your own profiles are the `.yaml` files of the folder `profiles_folder` names.

```sh
vocatron profiles
vocatron profiles check mine
vocatron profiles copy blue-page mine
```

| Option | Meaning |
|---|---|
| `--config <file>` | Configuration file; default `vocatron.yaml` in the current folder. |

### profiles check

`vocatron profiles check <name or file>` checks a profile without rendering anything (no ffmpeg
is needed).

| Check | What it tests |
|---|---|
| Name | It loads and names itself (its `name` is the name of its file). |
| Contrast | Its colours pass the contrast rules. |
| Safe area | Its lines fit the safe area in every output preset. |
| Layout | The layout rules hold on sample lyrics and the folk songs. |

The `profile_overrides` of the configuration are applied first and named in the output.

A look made for CD+G (a `cdg` section with `made_for_cdg: true`, [CD+G](cdg.md)) is checked on the
CD+G screen too; an MP4-only look is not:

| CD+G check | Key |
|---|---|
| The colours fit the 16 entries with all five singers and the group | `cdg.colours` |
| The contrast rules hold on the 12-bit colours | `cdg.colours.<singer>.<part>` |
| No line is too wide at the smallest size | `cdg.min_font_px` |
| The slots fit the text area | `cdg.slots` |
| On the sample songs and one dense invented song every line is fully drawn before its first syllable | `cdg.font_px` |
| The sweep is at most 50 ms behind | `cdg.wipe_columns` |

The last two run after the same fallback steps the `cdg` stage takes.

A problem a key causes prints as `file:line:column: key: message`; a broken layout rule prints
with file and preset. A clean profile prints `ok`.

| Exit code | Meaning |
|---|---|
| 0 | Fine. |
| 1 | Problems. |
| 2 | Configuration or usage error (an unknown name, a name that is built in and in the profiles folder, a file that cannot be read). |

### profiles copy

`vocatron profiles copy <built-in> [<name or file>]` writes an editable copy of a built-in
profile with a header comment (the source and the Vocatron version) and `name:` set to the new name.

- A bare name goes into `profiles_folder` (an error without one).
- A path (relative to the current folder) is used as it is.
- Without a second argument the copy is called `my-<built-in>`.
- It never overwrites a file (exit code 1).
- Exit code 2 on a usage error (an unknown built-in, a name that is not a plain name, a bare name
  without `profiles_folder`).

## status

Prints the summary lines of a song or of every song of a folder from what is stored (the
`report.json` of each song), without running anything. It takes `<path>`, `--output` and
`--config` like `make`.

| Song | Shows |
|---|---|
| Never run | `not run` |
| Run interrupted | `running` and the stage it stopped in |
| Made by another terminal right now | its stage, percentage and time left |

```text
ok        5:55   7m 12s  Queen - Radio Ga Ga
running   3:01        -  Queen - Bicycle Race  separation 41%, about 3m 20s left
running   6:30        -  Queen - Innuendo      interrupted in alignment
3 songs: 1 ok, 0 review, 0 failed, 1 running, 1 interrupted in 7m 12s
```

## lyrics

Finds and checks the lyrics of a song or of every song of a folder; see [Lyrics](lyrics.md) for
the file format.

| Command | Does |
|---|---|
| `vocatron lyrics <path>` | Runs the probe and the lyrics stage only and prints a line per song (`--output`, `--config`, `--force` and `--language` as for `make`). |
| `vocatron lyrics show <path>` | Prints the status, the reasons and the flagged lines of each song without running anything. |
| `vocatron lyrics approve <path>` | Approves the lyrics file next to the song as it is and updates the song status the same way. Give it the `--language` you gave `vocatron lyrics`. It needs a run first and refuses a file that changed since (an edited file counts as approved at the next run by itself). |

`vocatron lyrics` replaces only the results of these two stages in the song status. What later
stages recorded stays if their result is still current.

- A later stage whose result no longer matches its inputs (new lyrics, say) is `outdated`.
- One that was running when an earlier run died is `interrupted`.
- Either makes the song `review` with the reason "not finished, run `vocatron make`".

## models

Lists every AI model Vocatron can use with its state, size and licence; see [Models](models.md).

`vocatron models download [name...]` fetches models into the model folder and checks their
checksums. Without names it fetches what an English song needs; `--language de` fetches what a
German song needs (the separation models and `wav2vec2-de`; an unsupported language exits with
2). Both commands take `--config`.

## doctor

Checks that this machine is ready and prints one line per check, with what to fix:

```text
✓ ffmpeg         version 8.0.1-3ubuntu2
✓ libass         built in
✓ encoders       aac and H.264
✓ PyTorch        2.14.1+cu130, CUDA 13.0
✓ GPU            NVIDIA GeForce RTX 4060 Laptop GPU, 8.0 GiB
✗ models         0 of 3 present; bs-roformer-leap (missing), ...
                 fix: Run 'vocatron models download bs-roformer-leap ...'.
✓ output folder  ~/karaoke
1 of 7 checks need attention
```

| Check | What it tests |
|---|---|
| ffmpeg | Version 8 or newer, libass, an H.264 encoder (libx264 or h264_nvenc), an AAC encoder, and libmp3lame when `outputs` contains `cdg`. |
| PyTorch | With the GPU name and its total memory. A GPU of at least 6 GiB is recommended; without a usable one `doctor` prints a note, not a failure, because the separation falls back to the CPU. |
| Models | The models for a song in the configured `lyrics.language` (when none is set, those of an English song, which `models download` fetches without names or `--language`), with their checksums. |
| Output folder | Whether it can be written (`--output` or `output.folder`; the default `karaoke` is checked in the current folder). |

It takes `--output` and `--config` like `make`. Exit code 0 when everything is ready, 1 when
something needs fixing, 2 on a configuration error.

## Song states

| State | Meaning |
|---|---|
| `running` | The song is being made right now (`status` shows the stage, percentage and time left), or its run was interrupted (a crash, a kill or Ctrl-C) in the stage shown. Run `make` again. |
| `ok` | All stages ran (or were current) and found nothing to check. |
| `review` | A track exists, but a stage gave reasons to look at the song; they are listed in brackets. |
| `failed` | A stage failed, the song ran past its safety limit ("time limit"), or its work folder could not be written; the stage and the error are shown. |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Every song is `ok` or `review`. |
| 1 | At least one song is `failed`, or one was interrupted (also by Ctrl-C), or `status` found one that was interrupted (songs that were not run yet do not count), or `doctor` found something to fix, or a model download failed. |
| 2 | The command was used wrongly (an unknown model name, for example), the configuration is wrong (a message names the file, line and column), or the output folder cannot be created. |
