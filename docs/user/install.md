# Installation

Vocatron is developed and tested on Linux, WSL2 included (see [FAQ and known limits](faq.md)).
Everything except ffmpeg and `fdkaac` is installed into the project folder: the Python
environment, PyTorch, the tools and the AI models. Nothing is written to system locations or to
`/tmp`.

## Requirements

What you need before `make setup`: first the machine, then the disk space, then the tools.

### Hardware

| Part | What Vocatron needs |
|---|---|
| GPU | An NVIDIA GPU with CUDA, 6 GiB of memory at least (8 GiB recommended), and its driver. Only NVIDIA GPUs are used: with an AMD, Intel or Apple GPU Vocatron runs on the CPU. |
| CPU only | Works with the CPU build of PyTorch; the separation then runs about 20 times slower (see [Separating the vocals](separation.md)). |
| Internet | For the first setup, the first use of each model and the lyrics lookup. |

### Disk space

| What | Size |
|---|---|
| PyTorch (in `.venv/`) | about 6 GB |
| The models of one language (separation, lead and backing vocals, alignment) | about 1.6 GB |
| All ten models together | about 6.2 GB |
| The work folders of your songs | grows with the songs you make |

The model sizes are the sizes of the downloaded model files, not of a song, counted like
`vocatron models` counts them (1 GB = 1024 MB). The list is in [Models](models.md).

### Software

Example: Ubuntu 26.04 LTS. Other systems need the same tools from their own package manager.

| What | Why | How to get it |
|---|---|---|
| `git`, `make`, `curl` | `make setup` uses `curl` to fetch uv | `sudo apt install git make curl` |
| **ffmpeg 8 or newer** with libass and libx264 | video rendering | `sudo apt install ffmpeg` |
| **fdkaac** (Fraunhofer FDK AAC encoder) | audio of the karaoke video | `sudo apt install fdkaac` |
| ffmpeg with **libmp3lame** | [CD+G](cdg.md) only; the Ubuntu package has it | checked by `vocatron doctor` when `outputs` contains `cdg` |

If your ffmpeg is older than version 8, install a newer build (for example a static build from the
download page of ffmpeg.org), put it first on your `PATH` and check it with `ffmpeg -version` and
`vocatron doctor`.

`make setup` and `vocatron doctor` check ffmpeg (version and libraries) and `fdkaac` and say what
is missing. Without `fdkaac`, set `audio.encoder: ffmpeg-aac` in the [configuration](config.md) to
use ffmpeg's own AAC encoder; there is no automatic fallback, so that the same song always gives
the same file.

## Install

Set up the environment inside the clone.

1. Clone and enter the folder:

   ```sh
   git clone https://github.com/laberning/vocatron.git
   cd vocatron
   ```

2. Set up:

   ```sh
   make setup
   ```

`make setup` downloads a pinned [uv](https://docs.astral.sh/uv/) into `.tools/`, creates the
environment in `.venv/` with Python 3.14, installs PyTorch and checks ffmpeg. PyTorch comes from
the CUDA index on Linux with an NVIDIA GPU and from the CPU index otherwise; force the CPU build
with `make setup TORCH_EXTRA=cpu`. Run it again at any time; it only does what is missing.

## Put the command on your PATH

Make `vocatron` work in any folder.

```sh
make install
```

| Detail | Behaviour |
|---|---|
| What it does | Creates one link, `vocatron`, in `~/.local/bin`, pointing to the command in the `.venv/` of the clone. Nothing else is written outside the clone. |
| Another folder | `make install BINDIR=/some/folder` |
| Folder not on your `PATH` | `make install` says so and shows the line to add to `~/.profile`; open a new terminal afterwards. |
| New version or `make setup` again | No new install needed: the link follows the clone. |
| Remove | `make uninstall`, also before you delete or move the clone. |

You can skip this step: every command in this documentation also works as `.venv/bin/vocatron`,
typed from the clone folder or with the full path of the clone.

## Check that it works

Ask Vocatron whether the machine is ready.

```sh
vocatron --version
vocatron doctor
```

`vocatron doctor` checks ffmpeg (with libass and the encoder of your preset), `fdkaac`, PyTorch and
the GPU, the models and the output folder, and says what to fix for each. Right after
`make setup` it reports the models as missing: `make setup` does not download them, the first
song does (see the next section).

## Get the models

Vocatron downloads the models the first time a song needs them, checks that they are the right
files and keeps them in `.cache/models/` of the clone, outside the repository. The first
`vocatron make` therefore takes longer, and needs internet access unless you pass `--offline`.

To fetch them in advance (an optional step):

```sh
vocatron models download               # the models of an English song, about 1.6 GB
vocatron models download --language de # the models of a German song
```

Run `vocatron doctor` again afterwards. Without `lyrics.language` in your configuration it checks
the models of an English song, the same ones `vocatron models download` fetches; with
`lyrics.language: de` it checks those of a German song. See [Models](models.md) for the list, the
licences and how to move the folder.

## Your first track

Make a karaoke video from the freely licensed duet "My Favorite Regret" by Josh Woodward feat.
Katie Pederson (CC BY 4.0), which comes with its lyrics.

1. Download the audio into `.corpus/demo/` of the clone (checks its SHA-256):

   ```sh
   make demo-songs
   ```

2. Put the lyrics next to the song, so that Vocatron uses them instead of looking them up (they
   are in `tests/data/demo/`):

   ```sh
   cp "tests/data/demo/Josh Woodward - My Favorite Regret.txt" .corpus/demo/
   ```

3. Make the track:

   ```sh
   vocatron make ".corpus/demo/Josh Woodward - My Favorite Regret.mp3"
   ```

Results go to a `karaoke/` folder next to the song, here `.corpus/demo/karaoke/`, ending with the
video `Josh Woodward - My Favorite Regret.mp4`. The song ends as `ok` or `review`, and the summary line
says why.

| Machine | Time for this 4:27 song |
|---|---|
| Laptop with an 8 GiB NVIDIA GPU, models downloaded (an example, first run) | about three minutes |
| CPU only | much longer: the separation alone is about 20 times slower |

A German song works the same way. The freely licensed Systemabsturz "Verdächtig" (CC0) comes
with its lyrics in `tests/data/demo/`; fetch what it needs with
`vocatron models download --language de` and make it like the first track.

Then try your own:

```sh
vocatron make ~/Music/party/Song.mp3
```

Next: [Everyday use](everyday.md), [The karaoke video](video.md), [Commands](commands.md),
[Configuration](config.md), [Files and folders](folders.md), [FAQ and known limits](faq.md).

## If something does not work

Run `vocatron doctor`: it names what is missing and how to fix it. The log of each song
(`log.txt` in its work folder) names the stage that failed.

| Symptom | Fix |
|---|---|
| ffmpeg without libass, or older than version 8 | install ffmpeg 8 or newer with libass and libx264 (see [Requirements](#software)) |
| `fdkaac` missing | install it, or set `audio.encoder: ffmpeg-aac` |
| GPU driver that PyTorch cannot use | the separation falls back to the CPU and says so; fix the driver for speed |
| A model is missing while `--offline` is set | run `vocatron models download`, or drop `--offline` |
