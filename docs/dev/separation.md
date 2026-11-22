# Copied model code

The network that separates the vocals, BS-Roformer, is the one piece of code Vocatron copies
instead of using as a library ([ADR-0002](../adr/0002-tech-stack.md)). It lives in
`src/vocatron/engines/separation/roformer/`:

| File | Origin |
|---|---|
| `bs_roformer.py`, `attend.py` | `models/bs_roformer/` of ZFTurbo's Music-Source-Separation-Training at commit `6fdad13686bb7e84d029ec66f9dbe76e65c93ebf`, itself based on Phil Wang's BS-RoFormer. MIT; the file headers carry both copyright notices (ZFTurbo, Phil Wang) and the licence text, and `THIRD_PARTY.md` lists the commit. |
| `mel_band_roformer.py` | `models/bs_roformer/mel_band_roformer.py` of the same repository and commit. MIT, both notices in the header. It reuses the blocks of `bs_roformer.py` (transformer, band split, mask estimator, and `AxialRoformer`: the axial transformers, the STFT in and the inverse STFT out, which both networks share) and takes the mel filter bank from `vocatron.core.mel` instead of librosa (the same Slaney filters; a stage 2 test compares it with torchaudio). |
| `config.py` | Vocatron's own: reads the `model` section of a model's YAML configuration into `ModelConfig` or `MelModelConfig` (shared keys in `RoformerConfig`); each network takes its configuration object. |

## What was trimmed

Only the inference path is kept: no loss, no dropout, no checkpointing, no linear attention, no
PoPE, no `beartype`. The layer structure and the names of all weights are unchanged, so the
checkpoints (`bs-roformer-leap` (default), `bs-roformer-ep317`, `bs-roformer-karaoke`, and the candidates of the
registry) load with
`strict=True`; a stage 2 test checks that. Where upstream has a `Dropout`, an `Identity` stands
in, because the position of a layer in an `nn.Sequential` is part of its weight names.

`config.py` knows which keys of the configuration are training only (`IGNORED`, each with the
reason). A key it has never heard of is an error, so a new model with a new feature fails loudly
instead of silently running a different network. `mask_estimator_depth` means what it means
upstream, which differs between the two files: the number of linear layers of a mask network in
the BS-Roformer, the number of its hidden layers in the Mel-Band Roformer.

## Updating

To take a newer upstream version, fetch both files at the new commit, redo the trim, change the
commit in the headers and in `THIRD_PARTY.md`, and run the stage 2 tests: they compare the stems
with the reference stems of the trial of ADR-0002 (at least 35 dB).

## The loop around the network

The rules are in `vocatron/core/separation/rules.py`, the stage file `separation.json` and the stem
names in `file.py`, and the messages to the worker in `job.py`. The metrics, the evaluation and
the listening test are research code in `vocatron.lab.separation` ([ADR-0042](../adr/0042-module-map.md)).

`vocatron.core.separation.rules` plans the chunks (the chunk size and overlap come from the pin of
the model in the registry), blends the results with linear fades and normalises by the summed
windows, so a model that returns its input gives the input back exactly; a property test checks
this. `vocatron.engines.separation.inference` runs the network over the chunks.

The vocals model runs first; the instrumental is the song minus the vocals. The vocals, scaled
to a peak of 0.9, go through the karaoke model, which returns the lead vocals; the backing
vocals are what remains of the vocals.

Variants, all chosen by settings and part of the fingerprint only when they differ from the
default (`PinnedFromMix` keeps the fingerprint of the default order, so stored results stay
current):

- A model whose pin says `"target": "instrumental"` returns the instrumental as its first output;
  the vocals are then the song minus it (`combine_estimates`). The Mel-Band `deux` model returns
  two stems, vocals first, and counts as a vocals model.
- `separation.model` as a list of two models averages their instrumentals on the waveform; the
  vocals are the song minus the average. The default order and results are unchanged for one model.
- `separation.karaoke_input: mix` gives the karaoke model the whole song (at the same 0.9 peak)
  instead of the vocals. The vocals model still runs, for the instrumental and backing stems. The
  karaoke mix is the song minus the lead vocals either way.

`mel_band_roformer.py` always returns the stem dimension (upstream drops it for one stem), so
`inference.separate_target` takes the first stem of both architectures the same way. The
configuration decides the architecture: `num_bands` means Mel-Band Roformer.

The fade length, the 0.9 peak of the karaoke model's input and the headroom rule are constants
in `vocatron.core.separation.rules`, not part of a model pin, so they are not in the fingerprint: a
change to one of them changes the stems and must bump `SeparationStage.version`.

## Measuring separation models

`tools/separation_eval.py` measures vocals models against true instrumentals; nothing it reads or
writes is in git (`.corpus/`). `fetch` downloads Josh Woodward's songs (CC BY, with their
instrumental mixes, from the Internet Archive mirror, SHA-1 checked); the official instrumentals in
`.corpus/instrumentals/` and every `.corpus/*/items.json` are material too. `run` separates all
material with each candidate in child processes (timeout, 75 % VRAM cap, fp16, fsynced log), keeps
the estimated instrumentals as float WAV in `.corpus/eval/<model>/`, resumes where it stopped and
records a candidate that does not fit or fails to load in `failures.jsonl` before going on. `report`
lines each estimate up with its true instrumental by cross-correlation and prints mean and standard
error of SDR, SI-SDR, fullness and bleedless over all material and per group, the speed and peak
VRAM, the ensembles formed from the cached outputs of two members, the MP3-against-Ogg check and the
proposed finalists. The measures are pure functions (`vocatron.lab.separation.metrics`, after the definitions
of Music-Source-Separation-Training at the pinned commit) with property tests. MVSep's multisong set
cannot be scored: MVSep keeps its references secret.

## Comparing variants by listening

`tools/listening_test.py` compares *systems* (a vocals model, an ensemble, the order of the
lead/backing split, the karaoke model) blind on the local corpus; nothing it writes is in git.
`prepare` runs the separation stage once per system into `.corpus/listening/work/<system>` (a
folder may be a link to a work folder that already holds the separation). `build` takes the hardest
passages of each song (the densest 10 s of the current system's lead stem, plus any
`--extra "<song>@<seconds>"`), levels the original and every system's karaoke mix, writes lossless
FLAC clips with opaque ids, `key.json` and a static `index.html`. The page has its own Web Audio
player: the original and both versions start in the same instant and loop, and the buttons A, B and
Original song switch by gains with a 5 ms ramp, so they stay at the same position; the listener
picks the better version (or "can't tell") and may compare four criteria. Every candidate is judged
twice per passage with A and B swapped, the second judgements in later sessions of about 25
minutes, plus hidden pairs in which both buttons play the same version. Judgements stay in the
browser per build; "Save results" downloads `results.json`. `score` merges the files of the
sessions, reveals the key and prints per candidate the wins, losses and ties, the sign test, how
the two orders agree, the guesses on the hidden pairs, the criteria, the separation speed and peak
GPU memory per system, the sync benchmark (offset-corrected where measured, like the gate) and the
verdict of `vocatron.lab.separation.listening.decide`: preferred in at least 20 of 30 judgements, no passage
on which the reference won both orders, no worse sync and a fit within the 75 % cap. The rules are
pure and tested in `tests/fast/lab/separation/test_listening.py`.

The benchmark runs with another model by `VOCATRON_BENCH_MODEL=<model> make bench`; the result is
kept in `.corpus/bench/last-<model>.json`, and the accepted baseline stays as it is.
