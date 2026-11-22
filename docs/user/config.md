# Configuration

Every setting, its default and what it does. Read it when you want to change how Vocatron works.

Settings come from three places, later ones win:

1. the defaults on this page,
2. a file `vocatron.yaml` in the current folder, or the file given with `--config`,
3. command-line options, named in the Option column of the tables below.

See [Which value wins](#which-value-wins).

There is no user-wide file and there are no environment variables. Unknown keys and wrong values
are errors that name the file, the line and the column:

```text
error: vocatron.yaml:4:3: probe.min_duration: Input should be a valid number
```

## Example

```yaml
output:
  folder: karaoke
models:
  folder: .cache/models
probe:
  min_duration: 1.0
lyrics:
  lookup: true
  duet_pattern: duet(t)?
  language: null
separation:
  model: bs-roformer-leap
  karaoke_model: bs-roformer-karaoke
  karaoke_input: vocals
  keep_backing: true
  device: auto
  timeout_factor_gpu: 2.0
  timeout_factor_cpu: 30.0
alignment:
  use_lrc_times: true
  voice_activity: true
  voice_source: vocals
  hear_backing: true
  device: auto
  timeout_factor_gpu: 1.0
  timeout_factor_cpu: 15.0
batch:
  time_limit_factor: 10.0
  time_limit_base: 600.0
profile: four-line-stack
profile_overrides: {}
profiles_folder: null
preset: 4x3-720
audio:
  encoder: fdkaac
  bitrate: null
  export: none
outputs: [mp4]
cdg_zip: false
```

## Settings and defaults

Changing a setting re-runs exactly the stages whose result it changes; the section of a stage has
the stage's name. A relative path in the file is relative to the folder of the file
(see [relative output folders](#relative-output-folders)).

### Folders and input

| Key | Default | Option | Meaning |
|---|---|---|---|
| `output.folder` | `karaoke` | `--output` | Output folder. The default is inside the folder that holds the songs. |
| `models.folder` | `.cache/models` |  | Where the downloaded [models](models.md) are kept. The default is inside the clone of Vocatron. |
| `probe.min_duration` | `1.0` |  | Songs shorter than this many seconds fail in the `probe` stage. |
| `lyrics.duet_pattern` | `duet(t)?` |  | A song whose file name or title tag matches this regular expression (any case) is a duet; a duet without singer marks in its lyrics is marked for review. |
| `lyrics.language` | `None` | `--language` | The language of the songs as an ISO 639-1 code (`de`); `None` (in the file: `null`) detects it from the lyrics of each song. A set language skips the detection (`de` or `en`, see [Languages](languages.md)); an unsupported language is a configuration error. `--language` overrides it. |
| `lyrics.lookup` | `True` |  | Look the lyrics up on LRCLIB when no `.txt` or `.lrc` lies next to the song. Set `false` to work offline. |

### Separation

See [Separating the vocals](separation.md).

| Key | Default | Option | Meaning |
|---|---|---|---|
| `separation.model` | `bs-roformer-leap` |  | The [model](models.md) that takes the vocals out of the song. Only registered vocals models are accepted. A list of two different models (an *ensemble*) averages their instrumentals on the waveform and takes the time of both. A changed model re-runs the separation. |
| `separation.karaoke_model` | `bs-roformer-karaoke` |  | The [model](models.md) that splits the vocals into lead and backing; only registered karaoke models are accepted. A changed model re-runs the separation. |
| `separation.karaoke_input` | `vocals` |  | What the karaoke model gets: `vocals` (the vocals stem of the vocals model) or `mix` (the whole song). With `mix` the vocals model still runs, for the instrumental and backing stems. A changed value re-runs the separation. |
| `separation.keep_backing` | `True` | `--no-backing` | Keep the backing vocals in the karaoke track. `false` (or `--no-backing`) removes them too; the lead vocals are always removed. Changing it re-runs the separation. |
| `separation.device` | `auto` | `--device` | `auto` takes the GPU when at least 2 GiB of its memory are free and otherwise the CPU (with a warning; about 20 times slower); `cuda` and `cpu` force the device. `--device` overrides it. The device does not change the result, so changing it re-runs nothing. |
| `separation.timeout_factor_gpu` | `2.0` |  | The separation is stopped after this many song lengths plus two minutes when it runs on the GPU. |
| `separation.timeout_factor_cpu` | `30.0` |  | The same on the CPU. |

### Alignment

See [Synchronising the lyrics](sync.md).

| Key | Default | Option | Meaning |
|---|---|---|---|
| `alignment.use_lrc_times` | `True` |  | Use the line times of an `.lrc` next to the song as guide rails, after checking them against the singing. `false` aligns without them. Changing it re-runs the alignment. |
| `alignment.voice_activity` | `True` |  | Place words the acoustic model could not hear where the singing voice sounds in the separated vocals, instead of spreading them over the time between their neighbours, and end the words the model did hear where the voice stops, so held notes are highlighted as long as they are sung. `false` gives the earlier placement and ends words where the model last heard a letter. Changing it re-runs the alignment. |
| `alignment.hear_backing` | `True` |  | Let the acoustic model also hear the backing vocals, but only in frames where the lead vocals are silent and the backing vocals sound, so words the separation put into the backing (a word shouted by several voices) are measured instead of estimated. Where the lead sings, nothing changes; a song without such frames gives the same result. `false` aligns on the lead vocals alone. Changing it re-runs the alignment. |
| `alignment.voice_source` | `vocals` |  | Where the loudness for `voice_activity` is measured: `vocals` (lead and backing vocals added, so shouted or doubled words that the separation put into the backing vocals are found) or `lead` (the lead vocals alone, for a song whose backing harmonies mislead it). It does not change what the acoustic model hears (the lead vocals, and the backing vocals only where `hear_backing` allows). Changing it re-runs the alignment. |
| `alignment.device` | `auto` | `--device` | Where the acoustic model runs, as for `separation.device`; `--device` overrides it as well. The device does not change the result, so changing it re-runs nothing. |
| `alignment.timeout_factor_gpu` | `1.0` |  | The acoustic model is stopped after this many song lengths plus two minutes when it runs on the GPU. |
| `alignment.timeout_factor_cpu` | `15.0` |  | The same on the CPU. |

### Batch

| Key | Default | Option | Meaning |
|---|---|---|---|
| `batch.time_limit_factor` | `10.0` |  | The safety limit of a song: it may take this many song lengths in all stages together, plus `batch.time_limit_base`. A song that takes longer is stopped, ends `failed` with "time limit", and the batch goes on. |
| `batch.time_limit_base` | `600.0` |  | The seconds added to the safety limit of every song (10 minutes by default). |

### Look and video

See [Looks](looks.md) and [The karaoke video](video.md).

| Key | Default | Option | Meaning |
|---|---|---|---|
| `profile` | `four-line-stack` | `--profile` | The style of the lyrics: the name of one of the ten built-in profiles (`four-line-stack`, `two-line-turns`, `full-page`, `blue-page`, `one-line-preview`, `tall-page`, `three-line`, `neon`, `lyric-video` or `lyric-scroll`) or of an own profile in `profiles_folder`, or the path of a YAML file (relative to the folder of the configuration file). A value without a path separator and without `.yaml` or `.yml` at the end is a name; anything else is a path. `--profile` overrides it. A changed profile, or a changed profile file, re-runs only the layout and the render. |
| `profile_overrides` | `{}` |  | Values that replace those of the profile, with the same keys, for example `font: {size: 0.1}`. An invalid value is an error that names the key. |
| `profiles_folder` | `None` |  | A folder with your own profiles (YAML files), relative to the folder of the configuration file; `None` (in the file: `null`) means no own profiles. A file `mine.yaml` in it is chosen with `profile: mine`, like a built-in profile. A name that is both built in and in the folder is an error: change single values of a built-in profile with `profile_overrides`, or start your own from it with `vocatron profiles copy`. |
| `preset` | `4x3-720` | `--preset` | The output preset: frame size and video codec (`4x3-720`, `16x9-720`, `16x9-1080`, `av1-720`, `4x3-720-nvenc`). `--preset` overrides it. The frame size re-runs the layout and the render. |

### Audio and outputs

| Key | Default | Option | Meaning |
|---|---|---|---|
| `audio.encoder` | `fdkaac` |  | The AAC encoder of the karaoke audio: `fdkaac` (the Fraunhofer FDK encoder, a program you install) or `ffmpeg-aac` (ffmpeg's own; chosen explicitly, there is no fallback). |
| `audio.bitrate` | `None` |  | The audio bitrate in kbit/s; `None` (in the file: `null`) takes 192 for `fdkaac` and 256 for `ffmpeg-aac`. |
| `audio.export` | `none` |  | What is kept next to the video besides the enhanced LRC: `none` (nothing), `m4a` (the AAC audio of the video) or `flac` (the lossless karaoke audio). When the song is made again and the setting no longer asks for an export Vocatron made, that file is deleted. |
| `outputs` | `['mp4']` | `--cdg` | What a run makes. `mp4` is always there: the video and the enhanced LRC (and the audio export, if `audio.export` asks for one). `--cdg` on `vocatron make` adds `cdg` for one run. Add `cdg` (`outputs: [mp4, cdg]`) for `Song.mp3` and `Song.cdg` next to the video, for karaoke players and software that play [CD+G](cdg.md). Turning `cdg` on or off never renders the video again. The look must be made for CD+G. An unknown name, or a list without `mp4`, is a configuration error. |
| `cdg_zip` | `False` |  | Pack `Song.mp3` and `Song.cdg` into one `Song.zip` instead of writing them loose, as MP3+G collections are shared. Only used while `cdg` is in `outputs`. The zip has the same bytes for the same inputs (fixed member order and file times). Changing it runs only the `cdg` stage again. |

## Which value wins

A command-line option wins over `vocatron.yaml`, and `vocatron.yaml` wins over the default on this
page. A setting without an option can only be set in the file. An option holds for one run and
never changes the file. `--device` sets both `separation.device` and `alignment.device`, and
`--cdg` adds `cdg` to `outputs` for the run. `--no-backing` only turns the backing vocals off;
there is no option to turn them on, so use `separation.keep_backing`. The
[options of each command](commands.md) are listed there.

## Relative output folders

| Where | Relative to | Example |
|---|---|---|
| The default | the folder that holds the songs | `~/Music/party/karaoke` |
| The file (`output.folder`) | the folder of the file | `folder: tracks` in `~/vocatron.yaml` gives `~/tracks` |
| The option (`--output`) | the current folder | `--output out` in `~/` gives `~/out` |

A relative `--config` file is relative to the current folder as well.
