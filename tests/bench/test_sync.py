"""Stage 3: how well the lyrics are synchronised on the local corpus (ADR-0004).

Every language has its own corpus folder (``.corpus/songs`` for German, ``.corpus/songs-en`` for
English, see ``bench_files``), judged and reported on its own. Every song goes through the whole
pipeline with the line times of its ``.lrc`` switched off as hints; the line starts found are
compared with those times. A song whose lyrics are in another language than its folder's fails.
The result goes to ``.corpus/bench/last.json`` (``last-en.json``); ``make bench-accept`` makes it
the baseline (``make bench-accept LANGUAGE=en``). The output is numbers only, never a line of
the lyrics (AGENTS.md). It uses the GPU (capped at 75 % of its memory, half precision, a timeout
per worker and a synced log per song) and takes about a quarter of an hour on the first run,
since the separation of every song is part of it; later runs reuse the stage files whose inputs
did not change.

With ``VOCATRON_BENCH_MODEL=<name>`` the run uses that separation model, keeps its stage files in
``work-<name>`` and its result in ``last-<name>.json`` (compared with the same baseline); the
accepted baseline and ``last.json`` stay as they are. With ``VOCATRON_BENCH_LANGUAGE=<code>``
(``make bench LANGUAGE=<code>``) only that language runs.
"""

import os

import pytest

from conftest import corpus_dir
from realworld import CORPUS_PAGE, chosen_language, real_config
from vocatron.cli.app import real_engines
from vocatron.core.bench import bench_files, failures
from vocatron.core.languages import LANGUAGES
from vocatron.engines.files import LocalFileStore
from vocatron.stages.bench import read_run, report, run_bench, write_run
from vocatron.stages.songs import discover

BENCH = corpus_dir() / "bench"
MODEL = os.environ.get("VOCATRON_BENCH_MODEL") or None
ONLY = chosen_language("VOCATRON_BENCH_LANGUAGE")


@pytest.mark.parametrize("language", list(LANGUAGES))
def test_the_line_starts_against_the_human_references(language: str) -> None:
    files = bench_files(language, MODEL)
    songs_dir = corpus_dir() / files.songs
    if ONLY is not None and language != ONLY:
        pytest.skip(f"only the language {ONLY} was asked for (VOCATRON_BENCH_LANGUAGE)")
    if not songs_dir.is_dir():
        pytest.skip(f"needs the songs in {songs_dir}; see {CORPUS_PAGE}")
    config = real_config(BENCH / files.work, use_lrc_times=False, model=MODEL)
    engines = real_engines()
    store = LocalFileStore()
    songs = discover(songs_dir, config, engines)
    run = run_bench(songs, config, engines, language)
    baseline = read_run(store, BENCH / bench_files(language).baseline)
    write_run(store, BENCH / files.last, run)
    print()
    print("\n".join(report(run, baseline, language)))
    assert failures(run, baseline) == []
