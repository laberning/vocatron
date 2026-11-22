# Models

Which AI models Vocatron uses, their licences, and how they are downloaded. Read it before a first
run, or when you choose other models.

- The weights are not part of Vocatron and are never shipped with it. Vocatron downloads them at
  runtime, from the pinned source and revision, and checks every file against a stored SHA-256
  checksum.
- Nothing else is ever downloaded, and no account or token is needed.
- Vocatron's own code is MIT-licensed; each model keeps its own licence, listed below and by
  `vocatron models`.
- A model marked non-commercial may only be used for non-commercial purposes: if you use Vocatron
  commercially, choose other models. Vocatron warns in the log whenever it runs a non-commercial
  model.

## The models

`vocatron models` lists them with their state, size and licence:

| Name | Used for | Licence | Size |
|---|---|---|---|
| `bs-roformer-leap` | vocals / instrumental separation (default) | no licence stated by the author | 227 MB |
| `bs-roformer-ep317` | vocals / instrumental separation (the earlier default, slightly fuller treble) | no licence stated by the author | 610 MB |
| `bs-roformer-leap-inst` | vocals / instrumental separation (candidate, instrumental output) | no licence stated by the author | 255 MB |
| `mel-band-deux` | vocals / instrumental separation (candidate, Mel-Band Roformer) | CC BY-NC 4.0 (non-commercial) | 415 MB |
| `mel-band-flowersv10` | vocals / instrumental separation (candidate, Mel-Band Roformer, instrumental output) | no licence stated by the author | 467 MB |
| `bs-roformer-karaoke` | lead / backing vocals separation | GPL-3.0 | 195 MB |
| `bs-roformer-karaoke-frazer` | lead / backing vocals separation (candidate) | no licence stated by the author | 195 MB |
| `wav2vec2-de` | alignment of German lyrics | Apache-2.0 | 1.2 GB |
| `wav2vec2-en` | alignment of English lyrics (`facebook/wav2vec2-large-960h-lv60-self`) | Apache-2.0 | 1.2 GB |
| `whisper-turbo` | transcription when no lyrics exist | MIT | 1.5 GB |

- The candidates can be chosen with `separation.model` (vocals models) and
  `separation.karaoke_model` (karaoke models). The defaults are `bs-roformer-leap` and
  `bs-roformer-karaoke`.
- `vocatron models download` without a name fetches the defaults; `bs-roformer-ep317` is downloaded
  only when you name it.
- The state is `present`, `missing`, `partial` (a download was interrupted), or `checksum mismatch`
  (a file is not the pinned one).
- The weights are data that Vocatron loads, not linked code, so the GPL-3.0 and the unlicensed
  model do not change the licence of Vocatron; they keep their own, and you are responsible for
  how you use their output.
- `mel-band-deux` forbids commercial use; the separation warns whenever it runs with it.
- The sources, revisions and checksums are in `THIRD_PARTY.md`, next to the licences of the
  libraries.

## Download

```sh
vocatron models download                    # what an English song needs
vocatron models download --language de      # what a German song needs
vocatron models download wav2vec2-en        # one model by name
vocatron models download --config my.yaml   # with another model folder
```

- `--language <code>` adds the alignment model of that language to the two separation models; with
  names it adds the language's models to them.
- A song needs only the alignment model of its own language, and Vocatron fetches it just before it
  aligns the song, so you never download the English model for a German-only folder. With
  `--offline` the song fails with the command that fetches it.
- The licence of each model is printed before its files are fetched.
- A download goes to a `.part` file next to the target, so an interrupted download (a lost
  connection, Ctrl+C) is resumed from where it stopped the next time.
- A file that fails its checksum is deleted and the command fails with a message; run it again,
  and if it keeps failing, the source may have changed.

### Automatic download

A stage that needs a model downloads it the first time, and writes that to the log of the song.
Before each stage only the sizes of the model files are compared, so that a song does not wait for
gigabytes to be hashed; `vocatron models` and `vocatron doctor` compare the full checksums. Use
`vocatron make --offline` to forbid this: a song whose models are missing then fails, and the
message names the command to run first.

## The model folder

The default is `.cache/models/` in the clone of Vocatron, one folder per model. Move it with the
`models.folder` setting of the [configuration](config.md):

```yaml
models:
  folder: /data/vocatron-models
```

- A relative path is relative to the folder of the configuration file.
- Models are never written to `/tmp`, which is cleared on restart on some systems.
- To free the space, delete the folder; models are downloaded again when needed.
