"""Stage 1: the benchmark driver on fakes: measures, compares with the baseline, prints numbers."""

from pathlib import Path

import pytest

from fakes.lyrics import ENTCHEN, HAENSCHEN, synced_of
from fakes.songs import FakeWorld
from vocatron.core.bench import BenchRun, SongResult, bench_files, failures, run_of
from vocatron.core.errors import StageError
from vocatron.core.lyrics.versions import Candidate
from vocatron.stages.bench import read_run, report, run_bench, write_run
from vocatron.stages.config import AlignmentSettings, Config, OutputSettings
from vocatron.stages.songs import discover

MUSIC = Path("/music")


@pytest.fixture
def corpus(world: FakeWorld) -> FakeWorld:
    """Two songs with an .lrc and one with plain lyrics."""
    for name, text in (("a", ENTCHEN), ("b", HAENSCHEN)):
        world.add_song(MUSIC / f"{name}.mp3", lyrics=None)
        world.store.add(
            MUSIC / f"{name}.lrc", ("[length: 03:01]\n" + synced_of(text, step=5.0)).encode()
        )
    world.add_song(MUSIC / "c.mp3", lyrics=ENTCHEN)
    return world


def bench(world: FakeWorld, output: str | None = None) -> BenchRun:
    config = Config(alignment=AlignmentSettings(use_lrc_times=False))
    if output is not None:  # a new work folder that remembers no earlier run
        config = config.model_copy(update={"output": OutputSettings(folder=output)})
    return run_bench(discover(MUSIC, config, world.engines), config, world.engines)


def with_corrected(run: BenchRun, error_ms: float) -> BenchRun:
    """The run with every compared line at the given corrected error."""
    return run_of(
        {
            name: result.model_copy(update={"corrected_errors_ms": [error_ms] * result.compared})
            for name, result in run.songs.items()
        }
    )


def test_the_line_starts_are_compared_with_the_lrc_without_using_it(corpus: FakeWorld) -> None:
    corpus.acoustic.shift = 0.3  # sung 300 ms after the human line times
    run = bench(corpus)
    assert list(run.songs) == ["a.mp3", "b.mp3", "c.mp3"]
    a, b, c = run.songs.values()
    assert (a.status, a.lines, a.compared) == ("ok", 5, 5)
    assert a.errors_ms == pytest.approx([300.0] * 5)
    assert a.offset_ms == pytest.approx(300.0)
    assert a.corrected_errors_ms == pytest.approx([0.0] * 5)
    assert (b.lines, b.compared) == (6, 6)
    assert (c.lines, c.compared, c.errors_ms, c.offset_ms) == (5, 0, [], None)  # no reference
    assert a.estimated_share == 0.0
    assert (run.overall.count, run.overall.median_ms) == (11, pytest.approx(300.0))
    assert run.overall.within_200_ms == 0.0
    assert run.overall.within_500_ms == 1.0
    assert run.overall_corrected is not None
    assert (run.overall_corrected.median_ms, run.overall_corrected.within_200_ms) == (0.0, 1.0)


def test_a_failing_song_is_reported_and_the_others_still_run(corpus: FakeWorld) -> None:
    corpus.acoustic.fail_with = StageError("out-of-memory", "no memory")
    run = bench(corpus)
    assert {r.status for r in run.songs.values()} == {"failed"}
    assert run.songs["a.mp3"].reasons == ["alignment failed: out-of-memory"]
    assert run.songs["a.mp3"].compared == 0


def test_a_second_run_costs_only_what_changed(corpus: FakeWorld) -> None:
    bench(corpus)
    bench(corpus)
    assert len(corpus.acoustic.requests) == 3
    assert len(corpus.separator.requests) == 3


def test_the_report_has_a_line_per_song_numbers_only_and_what_fails(corpus: FakeWorld) -> None:
    corpus.acoustic.shift = 0.3
    lines = report(bench(corpus), None)
    assert len(lines) == 3 + 1 + 1
    assert lines[0].startswith("a.mp3: ok, 5/5 lines compared, median 300 ms, within 200 ms 0%")
    assert (
        "within 500 ms 100%, corrected median 0 ms, within 200 ms 100%, within 500 ms 100%"
        in (lines[0])
    )
    assert ", estimated words 0%, offset 300 ms" in lines[0]
    assert lines[2].startswith("c.mp3: ok, 0/5 lines compared, median -, within 200 ms -")
    assert lines[3].startswith("overall: 11 lines, median 300 ms")
    assert "; corrected median 0 ms, within 200 ms 100%, within 500 ms 100%" in lines[3]
    assert lines[4] == "no accepted baseline yet: 'make bench-accept' accepts this run"
    text = "\n".join(lines)
    for line in ENTCHEN.splitlines() + HAENSCHEN.splitlines():
        assert line not in text  # no lyrics in the report


def test_a_run_that_is_off_by_more_than_the_limit_after_the_correction_fails(
    corpus: FakeWorld,
) -> None:
    worse = with_corrected(bench(corpus), 250.0)
    assert any(
        line == "FAIL: overall corrected median error 250 ms is above the 200 ms limit"
        for line in report(worse, None)
    )


def test_the_report_shows_the_change_against_the_baseline_and_fails_on_a_regression(
    corpus: FakeWorld,
) -> None:
    corpus.acoustic.shift = 0.3
    last = bench(corpus)
    worse, better = with_corrected(last, 180.0), with_corrected(last, 100.0)
    lines = report(worse, better)
    assert "(+80 ms against the baseline)" in lines[0]
    assert any(
        line.startswith("FAIL: overall corrected median error 180 ms is 80 ms worse")
        for line in lines
    )
    assert not any("no accepted baseline" in line for line in lines)


def test_a_baseline_without_corrected_values_is_noted_and_not_compared(corpus: FakeWorld) -> None:
    corpus.acoustic.shift = 0.3
    last = bench(corpus)
    old = run_of({"a.mp3": SongResult(status="ok", errors_ms=[10.0])})
    lines = report(last, old)
    assert (
        "the baseline has no corrected values: only the 200 ms limit applies, "
        "'make bench-accept' accepts this run as a new baseline"
    ) in lines
    assert not any(line.startswith("FAIL") for line in lines)


def test_review_reasons_of_a_song_are_listed_under_it(corpus: FakeWorld) -> None:
    corpus.acoustic.jitter = {1: 3.0, 2: -2.0, 3: 6.0}
    run = run_of(
        {"x.mp3": SongResult(status="review", reasons=["alignment: lyrics times do not fit"])}
    )
    assert "    review: alignment: lyrics times do not fit" in report(run, None)


def test_runs_are_stored_and_read_back_and_a_broken_file_counts_as_none(
    corpus: FakeWorld,
) -> None:
    run = run_of({"a.mp3": SongResult(status="ok", errors_ms=[100.0])})
    path = Path("/bench") / bench_files("de").baseline
    assert read_run(corpus.store, path) is None
    write_run(corpus.store, path, run)
    assert read_run(corpus.store, path) == run
    corpus.store.add(path, b"{not json")
    assert read_run(corpus.store, path) is None


def test_line_times_of_looked_up_lyrics_are_no_reference(corpus: FakeWorld) -> None:
    corpus.add_song(MUSIC / "d.mp3", lyrics=None)
    corpus.lyrics.records = [
        Candidate.model_validate(
            {"source_id": n, "artist": "Artist", "title": "Title", "duration": 180.0,
             "plain": ENTCHEN, "synced": synced_of(ENTCHEN)}
        )
        for n in (1, 2)
    ]  # fmt: skip
    for _ in range(2):  # the second run reads back the file the lookup wrote next to the song
        d = bench(corpus).songs["d.mp3"]
        assert (d.lines, d.compared, d.errors_ms) == (5, 0, [])
        assert d.estimated_share == 0.0

    d = bench(corpus, "/other-work").songs["d.mp3"]  # the file carries Vocatron's mark
    assert (d.lines, d.compared, d.errors_ms) == (5, 0, [])


def test_a_song_in_another_language_than_its_folder_fails_and_is_not_compared(
    corpus: FakeWorld,
) -> None:
    config = Config(alignment=AlignmentSettings(use_lrc_times=False))
    songs = discover(MUSIC, config, corpus.engines)
    run = run_bench(songs, config, corpus.engines, "en")  # the fake detector says German
    assert {r.status for r in run.songs.values()} == {"failed"}
    a = run.songs["a.mp3"]
    assert a.reasons[0] == "the lyrics are in language de, this corpus folder is for en"
    assert (a.compared, a.errors_ms, a.offset_ms) == (0, [], None)
    assert failures(run, None)  # the run as a whole fails
    german = run_bench(songs, config, corpus.engines, "de")
    assert {r.status for r in german.songs.values()} == {"ok"}


def test_a_report_starts_with_the_language_when_it_has_one() -> None:
    run = run_of({"x.mp3": SongResult(status="ok", errors_ms=[100.0])})
    assert report(run, None)[0].startswith("x.mp3:")
    assert report(run, None, "en")[0] == "== English (en) =="
    assert report(run, None, "de")[0] == "== German (de) =="
    assert report(run, None, "xx")[0] == "== xx (xx) =="
    assert report(run, None, "en")[1:] == report(run, None)
