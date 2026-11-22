# Stage 3: benchmark

Sync quality against hand-made reference timings on the local corpus (ADR-0004). Run with
`make bench`; skipped with a reason when the corpus (`VOCATRON_CORPUS`, default `.corpus/`) is
missing. `make bench-accept` accepts the last run as the baseline (`make bench LANGUAGE=en` and
`make bench-accept LANGUAGE=en` for English).

- `test_sync.py`: one run per language (`.corpus/songs` for German, `.corpus/songs-en` for
  English; the other languages' file names append `-<code>`, see `bench_files`), each reported
  under its own heading and gated on its own; a song whose lyrics are in another language than
  its folder's fails. For one language, every song of its folder goes through the whole pipeline with the line times of
  its `.lrc` switched off as hints (only an `.lrc` put next to the song by hand is a reference,
  never looked-up lyrics); line-start errors per song and overall, absolute and offset-corrected
  (each line's error minus the song's median signed error, so a reference `.lrc` shifted as a
  whole does not count against the sync), the share of estimated words, and the change of the
  corrected median against `.corpus/bench/baseline.json`. It fails above 200 ms overall corrected
  median error, or more than 50 ms worse than the baseline's corrected median; a baseline from
  before the corrected values existed is compared against the 200 ms limit only (the report says
  so; `make bench-accept` replaces it). The output is numbers only,
  never lyrics. It uses the GPU (capped at 75 % of its memory, half precision, timeouts and
  synced logs) and takes about a quarter of an hour the first time.

`VOCATRON_BENCH_MODEL=bs-roformer-leap make bench` runs the same benchmark with another separation
model: its stage files go to `.corpus/bench/work-<model>`, its result to
`.corpus/bench/last-<model>.json`, and it is compared with the accepted baseline, which no such run
changes.
