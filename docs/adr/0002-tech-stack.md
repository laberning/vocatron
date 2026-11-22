---
id: ADR-0002
status: accepted
date: 2026-10-28
superseded_by: "ADR-0010 (in part: models are no longer excluded for a non-commercial licence); ADR-0011 (in part: the default vocals/instrumental model); ADR-0016 (in part: the English alignment model)"
---
# ADR-0002: Tech stack

## Context and problem

Vocatron is a Python command-line tool that runs AI models for vocal separation, alignment and transcription on a local NVIDIA GPU (8 GB, Linux including WSL2), calls ffmpeg for audio and video, and must stay MIT-licensed. The guiding principle is to **prefer modern tools that are actively maintained and not at the end of their life, as long as they are stable enough** for a private open-source project: "beta but solid" is acceptable, abandoned or maintenance-only is not. Every dependency must be compatible with an MIT program (permissive, LGPL or MPL used as a library, or a separate program). Model weights are downloaded at runtime and never shipped.

All versions below were checked against PyPI, GitHub, Hugging Face and the project docs on 2026-10-28. Two trial runs on one song were made before deciding (see "Evidence").

## Considered options

The options per area, with the reason for rejection, are listed in the tables of the decision. The two areas that needed more than desk research:

- **Separation runtime:** (a) audio-separator, (b) lucidrains' `BS-RoFormer` package, (c) the `msst` package, (d) the model file of ZFTurbo's Music-Source-Separation-Training (MSST) copied into Vocatron with our own inference loop.
- **Forced alignment:** (a) torchaudio's `forced_align` at runtime, (b) a third-party CTC aligner, (c) our own CTC Viterbi on the model's log-probabilities.

## Decision

### Platform

| Area | Choice | Notes |
|---|---|---|
| Python | CPython 3.14, `requires-python = ">=3.14.2,<3.15"`, `.python-version` | 3.14.1 has a regression that breaks torchvision; free-threaded builds not used |
| Project and environments | uv, `pyproject.toml`, `uv.lock` committed, everything inside the project folder | caches and models never in `/tmp` |
| PyTorch | torch 2.14 (BSD-3) from the `cu130` index via `tool.uv.index` and `tool.uv.sources`; a `cpu` extra with the CPU index and `tool.uv.conflicts` for CI | `--torch-backend` exists only in `uv pip` |
| Task runner | `make` | one entry point for every check |
| External program | ffmpeg ≥ 8 with libass, called as a binary via `subprocess` | not bundled, so its LGPL/GPL build options do not affect Vocatron's licence |

### Runtime libraries

| Area | Choice | Licence | Rejected |
|---|---|---|---|
| CLI | Cyclopts 5.3 (`>=5.3,<6`): help built from Google-style docstrings | Apache-2.0 | Typer (help strings duplicated in `Annotated`, still 0.x) |
| Config, profiles, stage files | Pydantic 2.14; YAML via ruamel.yaml 0.19 (YAML 1.2, line and column per node) with own glue for `file:line:column` errors; stage data as JSON with exported schema | MIT, MIT | TOML; PyYAML (YAML 1.1 booleans, slow); strictyaml (dead); pydantic-yaml (caps Python, no error locations); msgspec (0.x, weaker errors) |
| Console | Rich 15 | MIT | – |
| Audio I/O | ffmpeg for decoding and encoding; soundfile 0.14 for WAV and FLAC; NumPy 2.5 | BSD-3 (libsndfile LGPL), BSD-3 | ffmpeg-python, pydub (unmaintained); torchaudio I/O (moved to torchcodec, maintenance); torchcodec (not needed) |
| Tags | tinytag 2.3 | MIT | mutagen (GPL) |
| HTTP | urllib3 2.8 used directly | MIT | httpx (no stable release since 2024-12); requests (feature-frozen); niquests (not needed for one JSON endpoint) |
| Lyrics source | LRCLIB API only, with a `User-Agent` naming Vocatron; fetched for the user's own files, never redistributed | data licence not stated | NetEase unofficial API (archived for copyright reasons); Genius (no lyrics endpoint); Musixmatch (paid) |
| Language detection | lingua-language-detector 2.2 | Apache-2.0 | – |
| Syllables | pyphen 0.18 under its MPL-1.1 option (tri-licensed GPL-2.0+, LGPL-2.1+, MPL-1.1); dictionaries listed per language in `THIRD_PARTY.md` | MPL-1.1 | – |
| Numbers | own small module per language (cardinals, years) | – | num2words (stale since 2024, classifiers stop at 3.12) |
| Model loading and downloads | transformers 5.21 for wav2vec2 and Whisper, loading from local folders; one own downloader on urllib3 for every model file (Hugging Face `resolve` URLs and GitHub release assets): pinned revision, resume, SHA-256 check | Apache-2.0 | `huggingface-hub` for downloads (a second download path with its own cache layout; still installed as a dependency of transformers, but not used by Vocatron) |
| Separation model code | ZFTurbo's MSST BS-Roformer model file (`bs_roformer.py`, `attend.py`) copied into Vocatron, trimmed to inference, with its MIT notice; dependencies einops and rotary-embedding-torch | MIT | see below |
| Separation inference | own chunked overlap-add loop, fp16, VRAM cap | – | – |
| Alignment | own CTC forced alignment (Viterbi) on wav2vec2 log-probabilities | – | torchaudio `forced_align` at runtime (torchaudio is in maintenance mode); `ctc-forced-aligner` (licence inconsistent, PyPI name is a different project); `ctc-segmentation` (source-only) |
| Transcription (fallback when no lyrics exist) | Whisper large-v3-turbo via the transformers pipeline | – | whisperx (no Python 3.14, pins torch 2.8); faster-whisper (second runtime, no release for a year) |
| Subtitles and video | own ASS writer, rendered by ffmpeg/libass | – | – |
| Font | Noto Sans Bold 2.015 (static instance), bundled | OFL-1.1 | the variable Noto Sans (libass draws its bold weight as regular); Inter (runner-up); Liberation Sans (stale, no Black weight) |

**Separation runtime, in detail.** audio-separator (MIT, active) requires `diffq`, which is archived, ships wheels only up to Python 3.10 and is licensed CC-BY-NC 4.0: a non-commercial dependency is not acceptable in an MIT tool. lucidrains' `BS-RoFormer` changed its architecture in 0.5.0 (hyper-connections, a hard-wired learned value residual); from then on it cannot load the community checkpoints without source changes, and pinning 0.4.1 (2024-04) would mean depending on abandoned code. The `msst` package requires Python < 3.14 and torch < 2.12. ZFTurbo's MSST repository is MIT, active, and the home of the training code these checkpoints come from; its model file loads both checkpoints strictly. Copying that one file is therefore the only way to run the models on the chosen stack, and it is a deliberate exception to "libraries are used, not copied": the copy lives in its own module with the upstream licence notice, is trimmed to inference, and is checked against the checkpoints by a slow test.

### Models

All weights are downloaded at runtime into the project cache, pinned by source, revision and SHA-256, and listed with their licence in `THIRD_PARTY.md`. Inference settings (chunk size, overlap, precision, and input preparation such as the peak normalisation of the vocal stem to 0.9 before the karaoke model, which matches how its reference stems were made) are part of a model's pin; changing one is a new stage version.

| Use | Model | Licence |
|---|---|---|
| Vocals / instrumental | BS-Roformer `model_bs_roformer_ep_317_sdr_12.9755` | none stated by the author |
| Lead / backing vocals | BS-Roformer karaoke by anvuew | GPL-3.0 |
| Alignment, German | `jonatasgrosman/wav2vec2-large-xlsr-53-german` | Apache-2.0 |
| Alignment, English | `jonatasgrosman/wav2vec2-large-xlsr-53-english` | Apache-2.0 |
| Transcription | `openai/whisper-large-v3-turbo` | MIT |

Rejected: MMS_FA and `facebook/mms-300m` (CC-BY-NC 4.0, and much worse on German in our tests); Demucs htdemucs and two Mel-Band Roformer instrumental models (worse in an A/B listening test); the German 1B wav2vec2 (no gain, 2.3× VRAM). Weights are data loaded by the program, not linked code, so neither the GPL-3.0 checkpoint nor the unlicensed one changes Vocatron's licence; both are documented as such. Newer separation checkpoints are evaluated in the separation story by listening tests, not decided here.

### Development tools

Test, lint, type, docs and quality-gate tools and their versions are decided in ADR-0003, ADR-0004 and ADR-0007. In short: pytest 9 with Hypothesis and syrupy, Ruff, Pyrefly as the type gate, import-linter, deptry, vulture, jscpd, mutmut, coverage.py, Zensical with mkdocstrings-python. torchaudio 2.11 (BSD-2) is a development dependency only, as the test oracle for our alignment.

### Evidence

Trials on one 198-second song, RTX 4060 Laptop 8 GB, CPython 3.14.10, torch 2.14.1+cu130, fp16, VRAM capped at 75 %:

- **Separation:** our loop with the MSST model file reproduces audio-separator's stems: vocals 39.8 dB and instrumental 44.3 dB SDR against the reference once gain is matched (the reference was peak-normalised), lead vocals 34.9 dB, backing vocals 27.6 dB. The karaoke model itself varies by about 24 dB on the backing vocals between two chunk settings, so the residual difference is inference settings, not model code. 105 s and 66 s for the two models, peak 1.24 GiB.
- **Alignment:** our CTC Viterbi gives exactly the same path as torchaudio's `forced_align` (all 1670 tokens, every frame) in 0.52 s; wav2vec2 German emissions for the whole song in one pass take 1.2 s at 3.0 GiB peak.

## Consequences

- The whole stack installs on Python 3.14 with one `uv sync`; CI installs the CPU wheels.
- Vocatron owns two small pieces of model-adjacent code (the copied Roformer model file and the CTC aligner) and tests them against the checkpoints and against torchaudio.
- Stems are stored as FLAC, 24-bit, 44.1 kHz stereo (lossless apart from the float-to-24-bit step). Since the raw instrumental can exceed full scale, a stem whose peak is above full scale is scaled down linearly to −0.1 dBFS and the gain is recorded; there is no limiter and no other loudness change.
- The wav2vec2 checkpoints exist only as pickles (`pytorch_model.bin`); they are loaded with `weights_only=True` after the checksum check.
- Every version is pinned in `uv.lock`; upgrades are deliberate and re-run the slow tests.
- Docs on lyrics lookup state that fetched lyrics are for the user's own files and never redistributed.
