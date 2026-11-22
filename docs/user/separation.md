# Separating the vocals

What the `separation` stage makes, how to choose its models and what to do when it fails. It takes
the lead singer out of the song and keeps the rest. It is the heaviest stage: two AI models (see
[Models](models.md)) run over the whole song, on the GPU if there is one.

## What it makes

Four stems, in the `stems/` folder of the work folder, as 24-bit FLAC at 44.1 kHz stereo:

| File | Content |
|---|---|
| `lead.flac` | The lead vocals alone; the later synchronisation of the lyrics listens to these. |
| `backing.flac` | The backing vocals (choir, gang vocals, harmonies). |
| `instrumental.flac` | Everything except all vocals. |
| `karaoke.flac` | The track to sing to: the instrumental **plus the backing vocals**, or the instrumental alone with `--no-backing`. |

`separation.json` says how they were made: the models, the device, how long it took, the peak
GPU memory and the gains below.

Backing vocals stay in the karaoke track by default, since they carry much of what makes a song
sound right. `--no-backing` (or `separation.keep_backing: false`) takes them out too. Changing it
runs only this stage again; it does not run the lyrics stage again.

## Choosing the models and the order

| Setting | Meaning | Default |
|---|---|---|
| `separation.model` | The model that takes the vocals out (see [Models](models.md)). A list of two models makes an *ensemble*: their instrumentals are averaged on the waveform, which can sound fuller or cleaner than either alone and takes the time of both. | `bs-roformer-leap` |
| `separation.karaoke_model` | The model that splits the vocals into lead and backing. | `bs-roformer-karaoke` |
| `separation.karaoke_input` | What the karaoke model listens to: `vocals`, the vocals stem (today's order), or `mix`, the whole song. With `mix` the vocals model still runs for the instrumental and backing stems. | `vocals` |

All three settings change the stems, so changing one runs this stage again. `bs-roformer-ep317`,
the earlier default, stays selectable for a slightly fuller treble.

An ensemble:

```yaml
separation:
  model: [bs-roformer-leap, bs-roformer-leap-inst]
  karaoke_model: bs-roformer-karaoke
  karaoke_input: vocals   # or: mix
```

`mel-band-deux` is licensed for non-commercial use only (CC BY-NC 4.0). Vocatron runs it when you
choose it, but every run warns about it in the log and in `separation.json`.

## Loud songs: no clipping

The models' output can be louder than full scale, especially the instrumental of a loud master.
Writing it as it is would clip.

- A stem whose peak exceeds full scale is scaled down by one factor so that its peak is -0.1 dBFS;
  nothing else changes (no limiter, no other loudness change).
- The karaoke mix is scaled the same way after mixing.
- The factor of each stem is in `separation.json` under `gains`; `1.0` means the stem is untouched.

## Disk use

About a third of float WAV: four stems of a 4-minute song take about 120 MB.

## Devices

| `--device` / `separation.device` | What happens |
|---|---|
| `auto` (default) | The GPU if at least 2 GiB of its memory are free. Otherwise the CPU, with a warning in the log and in `separation.json`: it is about 20 times slower. |
| `cuda` | The GPU. Fails with a clear message when there is none or less than 2 GiB are free. |
| `cpu` | The CPU. Works on every machine, but a 4-minute song takes tens of minutes. |

On the GPU:

- The models run in half precision and PyTorch may use at most 75 % of the GPU memory, so that an
  overflow becomes an ordinary out-of-memory error instead of taking the machine down.
- A 3-minute song needs about 2 GiB.
- The device does not change the result enough to matter, so changing it does not run the stage
  again.

## When something goes wrong

The work runs in a separate process that Vocatron watches. If it crashes, runs out of GPU memory
or hangs, only that song fails, with a message in `status.json` and the console, and the batch goes
on with the next song. Every step the process takes is written to the log of the song (`log.txt`
in the work folder) and synced to disk, so a crash leaves evidence.

| Error | Cause and what to do |
|---|---|
| `out-of-memory` | The GPU is too full. Close other programs that use it, or use `--device cpu`. |
| `separation-timeout` | The process did not finish in time and was stopped. The limit is 2 song lengths plus 2 minutes on the GPU and 30 song lengths plus 2 minutes on the CPU; change `separation.timeout_factor_gpu` or `timeout_factor_cpu`. |
| `separation-failed` | The process crashed or left no result. The message shows the end of the log. |
| `no-gpu`, `vram-too-small` | `--device cuda` was asked for but cannot work. |
