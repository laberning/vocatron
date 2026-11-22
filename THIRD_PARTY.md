# Third-party software, models and assets

Versions are those of `uv.lock` on 2026-10-31; `uv.lock` is authoritative. `make licenses` reads the licence of every installed runtime dependency from its package metadata and fails on a copyleft (GPL, AGPL) or non-commercial licence, or one it does not know, unless the package is a documented exception (the NVIDIA CUDA runtime, below). LGPL and MPL are allowed.

Vocatron is licensed under the MIT licence. It uses the software below as libraries or as separate programs, downloads the model weights below at runtime, and bundles only the assets listed under "Bundled". **No model weights and no songs are shipped in this repository.**

The MIT licence covers Vocatron's code. Model weights keep their own licences, which bind whoever uses them (ADR-0010): some are permissive, one is GPL-3.0, some state no licence, and models marked **non-commercial** may not be used for commercial purposes. Vocatron warns whenever it runs a non-commercial model.

## Copied code

| Code | Origin | Licence | Where |
|---|---|---|---|
| BS-Roformer and Mel-Band Roformer model definitions (`bs_roformer.py`, `mel_band_roformer.py`, `attend.py`), trimmed to inference | ZFTurbo, Music-Source-Separation-Training (<https://github.com/ZFTurbo/Music-Source-Separation-Training>), itself based on Phil Wang's BS-RoFormer (<https://github.com/lucidrains/BS-RoFormer>) | MIT (Copyright (c) 2024 Roman Solovyev (ZFTurbo); Copyright (c) 2023 Phil Wang) | `src/vocatron/engines/separation/roformer/`, taken from upstream commit `6fdad13686bb7e84d029ec66f9dbe76e65c93ebf` (the Mel-Band file only while a Mel-Band candidate is under test, see ADR-0002), with both notices kept in the file headers |

## Runtime dependencies

| Package | Version | Licence | Used for |
|---|---|---|---|
| torch | 2.14 | BSD-3-Clause (plus bundled components under Apache-2.0, BSD-2-Clause and others) | running the models |
| transformers | 5.21 | Apache-2.0 | wav2vec2 and Whisper |
| huggingface-hub | 2.3 | Apache-2.0 | installed as a dependency of transformers; Vocatron downloads models with its own downloader |
| einops | 0.8 | MIT | Roformer model code |
| rotary-embedding-torch | 0.9 | MIT | Roformer model code |
| numpy | 2.5 | BSD-3-Clause (plus 0BSD, MIT, Zlib, CC0-1.0 parts) | audio arrays |
| pillow | 12.3 | MIT-CMU (HPND), bundles FreeType (FreeType licence) and HarfBuzz and Raqm (MIT) | measuring text in the bundled font for the layout, and drawing it (coverage maps) for the CD+G output (ADR-0023) |
| soundfile | 0.14 | BSD-3-Clause; bundles libsndfile (LGPL-2.1+) | WAV and FLAC |
| pydantic | 2.14 | MIT | config, profiles, stage files |
| ruamel.yaml | 0.19 | MIT | YAML config and profiles |
| cyclopts | 5.3 | Apache-2.0 | command line |
| rich | 15.0 | MIT | console output |
| tinytag | 2.3 | MIT | reading tags |
| urllib3 | 2.8 | MIT | lyrics lookup |
| lingua-language-detector | 2.2 | Apache-2.0 | language detection |
| pyphen | 0.18 | GPL-2.0+ / LGPL-2.1+ / MPL-1.1, used under **MPL-1.1** | syllables |

### Other packages installed with them

Not imported by Vocatron's own code, but installed as requirements of the packages above (checked by `make licenses`; versions of 2026-10-31). Licences as in the package metadata.

| Package | Licence |
|---|---|
| annotated-doc, annotated-types, anyio, attrs, click, docstring-parser, filelock, fsspec, h11, httpcore2, httpx2, idna, jinja2, markdown-it-py, markupsafe, mdurl, mpmath, networkx, pycparser, pydantic-core, pygments, pyyaml, rich-rst, setuptools, shellingham, sympy, tomli, triton, truststore, typer, typing-inspection | MIT, BSD (2 or 3 clauses), ISC or similar permissive |
| cffi | MIT-0 |
| packaging | Apache-2.0 or BSD-2-Clause |
| regex | Apache-2.0 and CNRI-Python |
| tqdm | MPL-2.0 and MIT |
| typing-extensions | PSF-2.0 |
| cuda-bindings, cuda-pathfinder, hf-xet, safetensors, tokenizers | Apache-2.0 |
| torchaudio (development and stage 2 only, installed with the PyTorch extras) | BSD-2-Clause |

### NVIDIA CUDA runtime (CUDA build only)

On Linux with an NVIDIA GPU, `make setup` installs the CUDA build of PyTorch, and with it the
`nvidia-*` and `cuda-toolkit` packages: proprietary NVIDIA runtime libraries under NVIDIA's own
licence, which allows use and redistribution with applications. They are not part of the CPU
build, not bundled in this repository, and installed by the user's own `make setup`. They are the
documented exception of `make licenses`.

### Hyphenation dictionaries (shipped inside pyphen)

| Dictionary | Licence |
|---|---|
| `hyph_de_DE` (German, reformed spelling, 2017-01-12) | based on TeX hyphenation tables (LPPL); the OpenOffice.org adaptation is LGPL-2.0+ |
| `hyph_en_US` (American English, 2011-10-07; used for English) | BSD-style: unlimited copying, redistribution and modification are permitted with the copyright and licence information (stated in `README_hyph_en_US.txt` inside pyphen); based on the Plain TeX tables (`hyphen.tex`: unlimited copying; a modified file must not be named `hyphen.tex`) and the TUGboat hyphenation exceptions (free to use, modify and distribute) |
| `hyph_en_GB` (British English) | not used |

## External programs

| Program | Licence | Notes |
|---|---|---|
| ffmpeg ≥ 8 with libass and libx264 | LGPL-2.1+ core; GPL if built with libx264/libx265; libass ISC | installed by the user and called as a separate program; not bundled, so its build options do not affect Vocatron's licence; `libx264` is the video encoder of the default preset (ADR-0009) |
| fdkaac (Fraunhofer FDK AAC) | FDK AAC licence (free to use; not GPL-compatible, so not part of standard ffmpeg builds) | installed by the user (`sudo apt install fdkaac`) and called as a separate program for the AAC audio (ADR-0009); not bundled |
| libmp3lame (LAME) in ffmpeg | LGPL-2.0+ | the MP3 of the CD+G pair is encoded by ffmpeg with libmp3lame (ADR-0024); installed by the user with ffmpeg, called as a separate program, not bundled |

### Optional test tools (never installed for users, never in git)

| Tool | Version | Licence | Used for |
|---|---|---|---|
| Node.js | 20 or newer | MIT (and others) | runs the optional stage 2 test of the third CD+G decoder (ADR-0025); installed by the developer, never needed to use Vocatron |
| cdgraphics (npm), a JavaScript CD+G player | 7.0.0 | permissive: the `LICENSE` file in the tarball is the MIT licence, `package.json` says ISC | `make cdg-js` downloads the one tarball `cdgraphics-7.0.0.tgz` from the npm registry into `.tools/cdgraphics-7.0.0/` (git-ignored), checks its sha512 integrity against the value pinned in the `Makefile` and unpacks it; the test runs `dist/cdgraphics.js` unchanged in Node and compares its frames with ours. The code is used, never ported or copied, and never distributed with Vocatron. |

## Models (downloaded at runtime)

Each model is pinned by source, revision and SHA-256 and downloaded into the project cache on first use or by a command. Licence as stated by the publisher on 2026-10-28.

| Use | Model | Source | Licence |
|---|---|---|---|
| Vocals / instrumental (selectable, the earlier default) | `model_bs_roformer_ep_317_sdr_12.9755` (ckpt SHA-256 `5b84f37e8d444c8cb30c79d77f613a41c05868ff9c9ac6c7049c00aefae115aa`) | GitHub release `TRvlvr/model_repo` `all_public_uvr_models`; config from `TRvlvr/application_data` | **no licence stated** by the author; downloaded by the user's program, never redistributed |
| Vocals / instrumental (**default**, ADR-0011) | `bs_roformer_leap_voc` (ckpt SHA-256 `8c0e4bfff6be150a12582a7c236379aa42102b7f43831900df5b2addf924da7c`) | Hugging Face `pcunwa/BS-Roformer-Leap`, revision `4e47d666` | **no licence stated** by the author; downloaded by the user's program, never redistributed |
| Lead / backing vocals | `karaoke_bs_roformer_anvuew` (ckpt SHA-256 `206d04757cb5f75ca3b55f8a0a48f5c26aa2351d4ff3c7adbfc9affa30ea3ae4`) | Hugging Face `anvuew/karaoke_bs_roformer`, revision `0d4423d4` | **GPL-3.0**; weights are data loaded at runtime, not linked code |
| Vocals / instrumental (candidate, instrumental output) | `bs_leap_xe_inst` (ckpt SHA-256 `33ee9415f491d257fa7a79f6e92a80d647bc71ed622bfef9a137b6e4250307d3`) | Hugging Face `pcunwa/BS-Roformer-Leap`, folder `Xe`, revision `4e47d666` | **no licence stated** by the author; downloaded by the user's program, never redistributed |
| Vocals / instrumental (candidate, Mel-Band Roformer) | `becruily_deux` (ckpt SHA-256 `10255c02295bf3e3865d4ee50ff752d7b19b124ed5fd93b147babc4333eda3aa`) | Hugging Face `becruily/mel-band-roformer-deux`, revision `402dd9a1` | **CC BY-NC 4.0** (non-commercial) per the model card; weights are data loaded at runtime, not redistributed |
| Vocals / instrumental (candidate, Mel-Band Roformer) | `inst_gaboxFlowersV10` (ckpt SHA-256 `fe3aa51927beb60ff345b8b672c11760fb8bdaa6039d8c61631416a5b4f7a047`) | Hugging Face `GaboxR67/MelBandRoformers`, folder `melbandroformers/instrumental`, revision `7860d31d` | **no licence stated** by the author; downloaded by the user's program, never redistributed |
| Lead / backing vocals (candidate) | `bs_roformer_karaoke_frazer_becruily` (ckpt SHA-256 `eb90ee24c1154d83fbcfd27e96182f19e061557cc6e4746953125e08c29389f9`) | Hugging Face `becruily/bs-roformer-karaoke`, revision `0d66103c` | **no licence stated** by the author; downloaded by the user's program, never redistributed |
| Alignment, German | `jonatasgrosman/wav2vec2-large-xlsr-53-german` (`pytorch_model.bin` SHA-256 `bff6d75ab89d8ca9cd103df9beb9c10f547501cf5a34aeabea1c8d736c1b81cb`) | Hugging Face, revision `4b8a0295` | Apache-2.0 |
| Alignment, English | `facebook/wav2vec2-large-960h-lv60-self` (`pytorch_model.bin` SHA-256 `00b604cf4d28e86559e8adaeb3a186daa89dc37f5ab216771a0a15a26db0de9f`) | Hugging Face, revision `54074b1c` | Apache-2.0 |
| Transcription (fallback) | `openai/whisper-large-v3-turbo` | Hugging Face, revision `41f01f3f` | MIT |

## Bundled assets

| Asset | Version | Licence | Where |
|---|---|---|---|
| Noto Sans Bold (static TrueType, unhinted) | 2.015 | SIL Open Font License 1.1 | `src/vocatron/fonts/NotoSans-Bold.ttf` with `OFL.txt` |

The font comes from the official release `NotoSans-v2.015` of the Noto Project
(<https://github.com/notofonts/latin-greek-cyrillic/releases/tag/NotoSans-v2.015>), file
`NotoSans/unhinted/ttf/NotoSans-Bold.ttf` of `NotoSans-v2.015.zip` (SHA-256 of the zip
`0c34df072a3fa7efbb7cbf34950e1f971a4447cffe365d3a359e2d4089b958f5`). SHA-256 of the bundled files:
`NotoSans-Bold.ttf` `87cb2d84472a7d66da659ee47b6cdb9552326e8c128245231f191b6ac72529d9`, `OFL.txt`
`cee9892f9f0cc8fe882c9e9537ee6a89621d86ee7ceaf70b02e2b2b1c25c061a`. It is the static instance of the
family and not the variable font: libass draws the bold weight of a variable font as the regular
one, so the layout would measure a font that the video does not use. Vocatron points libass at this
folder only and fails a render in which libass chose another font.

## Demo songs (downloaded, never in git)

The audio is not part of the repository: `make demo-songs` downloads it into the git-ignored
`.corpus/demo/` and checks its SHA-256. The lyrics files and the credits are in `tests/data/demo/`
(`CREDITS.md`), under the licence of their song.

| Song | Licence | Source |
|---|---|---|
| Systemabsturz, "Verdächtig" (German; album "Überwachung zum Mitsingen", 2021) | CC0 1.0 Universal (the band's website); CC BY 3.0 on Bandcamp and Wikimedia Commons, which the credit also satisfies | <https://systemabsturz.band/> |
| Josh Woodward feat. Katie Pederson, "My Favorite Regret" (English duet; album "Addressed to the Stars", 2016) | CC BY 4.0 | <https://www.joshwoodward.com/song/MyFavoriteRegret> |

## Data from online services

| Service | Terms |
|---|---|
| LRCLIB (<https://lrclib.net>) | no licence is stated for the lyrics data. Vocatron fetches lyrics only into the user's own sidecar files and never redistributes them. |

## Development dependencies (not installed for users)

Versions as locked in `uv.lock` on 2026-10-28; none is shipped and `make licenses` does not check them. The `dev` dependency group holds:

| Package | Version | Licence | Used for |
|---|---|---|---|
| pytest | 9.2.0 | MIT | tests |
| pytest-randomly | 5.0.0 | MIT | random test order |
| pytest-xdist | 3.8.0 | MIT | parallel tests |
| pytest-timeout | 2.4.0 | MIT | per-test timeout |
| pytest-socket | 0.8.1 | MIT | network blocked in tests |
| pytest-cov | 7.1.0 | MIT | coverage in pytest |
| coverage | 7.17.0 | Apache-2.0 | branch coverage |
| diff-cover | 11.0.0 | Apache-2.0 | coverage of changed lines |
| Hypothesis | 6.170.13 | MPL-2.0 | property tests |
| syrupy | 6.1.1 | MIT | golden files |
| Ruff | 0.17.3 | MIT | format and lint |
| Pyrefly | 1.4.0 | MIT | type check |
| ty | 0.0.93 | MIT | advisory type check |
| import-linter | 2.15 | BSD-2-Clause | layer contracts |
| deptry | 0.25.1 | MIT | dependency check |
| vulture | 2.16 | MIT | dead code |
| jscpd | 5.4.2 | MIT | duplicate code |
| mutmut | 3.8.1 | BSD-3-Clause | mutation testing |
| Zensical | 0.0.73 | MIT | documentation site |
| mkdocstrings-python | 2.0.10 | ISC | API reference from docstrings |

Other build and test tools: uv 0.13.7 (Apache-2.0 or MIT; downloaded by `make env` into `.tools/`), make. torchaudio 2.11 (BSD-2) is a development dependency only: the stage 2 test compares our CTC alignment with its `forced_align`. It is not imported by Vocatron itself.
