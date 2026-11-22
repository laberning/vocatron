# Stage 2: slow tests

Real engines, GPU and the local corpus (ADR-0004, ADR-0015). Run with `make slow` or
`make check-all`; `make slow-cpu` runs the tests that need no GPU (part of every
change) on four workers, one test file per worker (`--dist loadfile`: the files must share no state
or path outside their own `tmp_path`; `reports/` files have one writer each). Tests that need a GPU carry the marker `gpu` and are skipped with a reason where there
is none. A test that reads the corpus is skipped with a reason when there is no corpus at all
(`VOCATRON_CORPUS`, default `.corpus/`); when the corpus folder a test reads is missing, the test is
skipped too, and its message names `docs/dev/corpus.md`, which lists what each corpus folder must
hold; when the folder is there but a file the test needs is missing, the test fails and names the
file, so a moved or converted file is never a silent skip.
`make slow-cpu` is no CI job for that reason: without the private corpus most of it would skip. The tests find corpus files with `corpus_path` and songs with `corpus_song`
in `tests/realworld.py`: a song by its name in any supported audio format in `.corpus/songs`, or
in `.corpus/mp3` for the tests whose references were made from the earlier MP3 versions.

- `test_models_real.py`: the real downloader and `doctor` on this machine (network; the doctor
  test needs the GPU).
- `test_video_real.py`: a public-domain song laid out and rendered with the real ffmpeg, libass
  and font against the golden images in `golden/`, and a short video with the real encoders. No
  GPU, no corpus.
- `test_language_real.py`: lingua on public-domain text.
- `test_separation_real.py`: the two separation models on the GPU against the reference stems of
  "Denkmal" in `.corpus/reference/denkmal` (at least 35 dB), and one whole song through the
  stage and its worker process. It takes about six minutes and uses the GPU: capped at 75 % of
  its memory, half precision, a timeout per test, and a log in `.cache/logs/` that is synced
  after every line. The models are downloaded into `.cache/models` first
  (`vocatron models download bs-roformer-leap bs-roformer-ep317 bs-roformer-karaoke`, and the
  candidates for the candidate test); the tests do not download.
- `test_alignment_real.py`: the acoustic model on the GPU and the alignment on "Denkmal": our
  Viterbi against torchaudio's `forced_align` on real log-probabilities (frame for frame), pieces
  of 30 seconds against one pass and against another overlap, and the end-to-end median line-start
  error without guide rails (at most the trial's 236 ms). It uses the reference lead vocals in
  `.corpus/reference/denkmal`, the MP3 version of the song in `.corpus/mp3` (from which those
  references were made) and the German model in `.cache/models` (downloaded by
  `vocatron models download wav2vec2-de`; the tests do not download). It takes about a minute.
- `test_make_real.py`: `vocatron make` end to end on two short songs of `.corpus/songs` (with
  their lyrics files), copied into `.corpus/make-real/songs`: separation and alignment on the GPU, the
  video with the real tools, a report per song, the summary, the learnt speeds in
  `.cache/timings.json`, and a second run that skips everything. It reports counts, sizes and
  times only, and takes about six minutes on the GPU (same safety as above; log in
  `.cache/logs/stage2-make.log`).
- `test_word_voice_corpus.py`: the lead and the backing stem of the stored work folder of one real song against its alignment, by numbers: no sweep starts before the voice that sings it or crosses a silence in both stems. No GPU.
- `test_voices_corpus.py`: two voices at once (ADR-0052). The lyrics stage puts the later line of one `.lrc` time in "Stumblin' In" on the second voice (no GPU); on the GPU, "Auf uns" splits its overlapping lines 53 to 59 into two voices with at most one estimated word, and the line after the pair in "Stumblin' In" starts within 0.3 s of its line time. Numbers only.
- `test_unheard_real.py`: the outro of a real song, which the model does not hear, placed at its
  line times on the stems of an earlier run (`.corpus/unheard`, GPU).
- `test_video_corpus.py`: "Denkmal" laid out and rendered with the real tools from the work
  folder of the benchmark (`.corpus/bench/work`, made from the song in `.corpus/songs`), against
  the golden frames in `.corpus/reference/denkmal/golden` (`VOCATRON_UPDATE_GOLDEN=1` makes them
  anew). The lyrics stage runs again on the CPU, so `lyrics.json` is in the current schema. No
  GPU; numbers and verdicts only.
- `test_duets_corpus.py`: the marked duets of `.corpus/duets` (`.lrc`, singer marks in braces,
  ADR-0018) through the lyrics stage on fakes, words timed evenly from the line times (a line never
  starting before the one before has ended, as in the alignment), and the
  layout in `two-line-turns` and `full-page`: every word keeps its singers and their colours from
  the file to the scene, also with added changes inside lines, and the scene rules hold. No GPU;
  counts only; a duet without marks is skipped.
- `test_cdg_corpus.py`: the CD+G decoder and analysis on the discs in `.corpus/cdg/<vendor>/`
  (robustness: every file decodes, wiped lines and a wipe speed are found). No GPU; numbers and
  file names only; skipped while the folder has no `.cdg` file.
- `test_demo_real.py`: `vocatron make` end to end on the demo songs, once per language, which
  need no private corpus: the German "Verdächtig" (CC0) and the English duet "My Favorite
  Regret" (CC BY 4.0).
  `make demo-songs` downloads them into `.corpus/demo/` (SHA-256 checked); the lyrics files are
  in `tests/data/demo/` (credits in `CREDITS.md`), and the language is detected, not set. Each
  song is made in `.corpus/demo/make-<code>`. The word starts are compared with
  `golden/demo/<code>/words.json` (median error at most 100 ms, no word more than 1 s off) and
  five frames with `golden/demo/<code>/*.png`. A song is skipped without a GPU, without the
  downloaded song, or while its references are missing; `make demo-accept` writes the English
  ones and `make demo-accept LANGUAGE=de` the German ones (`VOCATRON_DEMO_ACCEPT=1`,
  `VOCATRON_DEMO_LANGUAGE`), and they are committed only after the video has been watched.
  About three minutes per song on the GPU, same safety as above (log in
  `.cache/logs/stage2-demo-<code>.log`); numbers and verdicts only.
- `test_language_real.py`: the real language detector (lingua) on public-domain German and
  English song texts, with a short text and a German text holding one English line. No GPU.
