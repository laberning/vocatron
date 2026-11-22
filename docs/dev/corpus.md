# The local corpus

Some tests of stage 2 and the benchmark of stage 3 read real songs. These are copyrighted, so the
folder `.corpus/` of a clone is ignored by git and never enters the repository (the environment
variable `VOCATRON_CORPUS` points elsewhere). Without a corpus these tests are skipped, and so is a
test whose folder below is missing; its message names the folder and this page. When the folder is
there but a file or song the test needs is missing, the test fails and names it, so a renamed or
converted file never turns into a silent skip. The tests and the benchmark report numbers and file names
only, never a line of the lyrics.

The songs of the demo (`make demo-songs`) are freely licensed and need no private corpus; see
[the test harness](harness.md).

## Folders that tests and the benchmark read

| Folder | Must contain | Read by |
|---|---|---|
| `songs/` | German songs, one audio file each (any supported format) with a `.lrc` file of the same name next to it; the songs have human line times | `make bench` (`tests/bench/test_sync.py`), `test_make_real.py`, `test_video_corpus.py`, `test_separation_real.py`, `tools/listening_test.py` |
| `songs-en/` | the same for English songs | `make bench` (language `en`) |
| `bench/` | written by `make bench`: `baseline.json`, `last.json` (and `-en` and `-<model>` variants) and the work folders `work/` with the stage files of every song, among them `alignment.json` and `stems/lead.flac` and `stems/backing.flac`; `Andreas Bourani - Auf uns` is the work folder the voice tests read | `make bench`, `make bench-accept`, `test_video_corpus.py`, `test_word_voice_corpus.py`, `test_voices_corpus.py` (GPU), `tools/listening_test.py`, `tools/word_voice.py` (`make word-voice`) |
| `songs-en-work/` | work folders of an earlier English run, each with `stems/instrumental.flac` | `test_tempo_corpus.py` (together with `bench/work`) |
| `mp3/` | the MP3 versions of songs that are also in `songs/` | `test_alignment_real.py`, `tools/separation_eval.py` |
| `reference/` | one folder per reference song (`denkmal/`): reference stems as WAV files (`anvuew_lead.wav` and others) and a `golden/` folder with golden frames | `test_separation_real.py`, `test_alignment_real.py`, `test_video_corpus.py` |
| `unheard/` | `in/`: the song as an `.ogg` with its `.lrc`; `new/<work name>/stems/`: `lead.flac` and `backing.flac` of an earlier run | `test_unheard_real.py` (GPU), `test_voices_corpus.py` |
| `listen352/` | `in/`: `Andreas Bourani - Auf uns.ogg` with its `.lrc` | `test_voices_corpus.py` (GPU; the stems come from `bench/work`) |
| `make-real/` | nothing; `test_make_real.py` copies two songs of `songs/` here and makes them | `test_make_real.py` (GPU) |
| `duets/` | `.lrc` files with singer marks in braces | `test_duets_corpus.py` |
| `early/` | `Suzi Quatro & Chris Norman - Stumblin' In.lrc` with the line times as they were before a correction (line 34 three seconds early) and the song as an `.ogg` | `test_voices_corpus.py` (GPU; the stems come from `unheard/new`) |
| `cdg/` | one folder per vendor with `.cdg` files | `test_cdg_corpus.py`, `tools/cdg_analyse.py` |
| `demo/` | the demo songs downloaded by `make demo-songs`, and the work folders `make-<code>` | `test_demo_real.py` |

Tools that write or read more material (`tools/separation_eval.py` uses `woodward/`,
`instrumentals/` and writes `eval/`; `tools/listening_test.py` writes `listening/`) create their
folders themselves.
