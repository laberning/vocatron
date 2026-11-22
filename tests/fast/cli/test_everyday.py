"""Stage 1: the whole batch on fakes for every engine, as the everyday workflow (ADR-0006).

A folder of tiny songs with canned stems, log-probabilities and lyrics goes through every stage:
skip and force, a changed lyrics file, a song that ends ``review``, one that ends ``failed``, the
safety limit with a fake clock, a disk that fills up, Ctrl-C as a stop flag, the exit codes, and
the summary and the report file as golden text.
"""

from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from syrupy.assertion import SnapshotAssertion

from fakes.lyrics import ENTCHEN, ENTCHEN_MESSY, HAENSCHEN
from fakes.separation import FAKE_SECONDS
from fakes.songs import FakeWorld
from fakes.streams import CLONE, Streams
from fakes.summary import summary_line
from vocatron.cli.commands import run_lyrics, run_make, run_status
from vocatron.core.progress import ProgressFile, Timings
from vocatron.core.report import ReportFile
from vocatron.core.song import Tags
from vocatron.core.status import SongStatus
from vocatron.engines.protocols import SeparationRequest
from vocatron.stages.batch import Options

MUSIC = Path("/music")
OUT = MUSIC / "karaoke"
TOOK = 125.0  # seconds the fake separation "takes" in the tests that show times


def work(name: str) -> Path:
    return OUT / name


@pytest.fixture
def library(world: FakeWorld) -> FakeWorld:
    """Three songs: one that is fine, one with lyrics that need a look, one that cannot be read."""
    world.add_song(MUSIC / "a.mp3", tags=Tags("Volkslied", "Entchen", 185), lyrics=ENTCHEN)
    world.add_song(MUSIC / "b.mp3", tags=Tags("Volkslied", "Messy", 240), lyrics=ENTCHEN_MESSY)
    world.add_song(MUSIC / "c.mp3", tags=None)
    world.separator.during = lambda request: world.clock.wait(TOOK)
    return world


def flat(text: str) -> str:
    """Return ``text`` on one line, so that the wrapping of the console does not matter."""
    return " ".join(text.split())


def make(world: FakeWorld, *, force: bool = False) -> tuple[int, Streams]:
    """Run ``vocatron make`` on the library: the exit code and the captured consoles."""
    streams = Streams(world)
    code = run_make(
        MUSIC, output=None, config_file=None, options=Options(force=force), edges=streams.edges
    )
    return code, streams


def test_a_folder_goes_from_audio_to_tracks_with_one_summary_line_per_song(
    library: FakeWorld, snapshot: SnapshotAssertion
) -> None:
    code, streams = make(library)
    assert code == 1  # one song failed
    assert streams.out.getvalue() == snapshot
    for name in ("Volkslied - Entchen", "Volkslied - Messy"):
        assert library.store.size(OUT / f"{name}.mp4") is not None  # review songs get a track too


def test_the_report_file_has_the_same_lines_and_the_date(
    library: FakeWorld, snapshot: SnapshotAssertion
) -> None:
    make(library)
    assert library.store.read_text(OUT / "vocatron-report.txt") == snapshot


def test_status_prints_the_same_lines_from_the_stored_reports_without_running(
    library: FakeWorld,
) -> None:
    _, made = make(library)
    library.store.writes.clear()
    streams = Streams(library)
    assert run_status(MUSIC, output=None, config_file=None, edges=streams.edges) == 1
    lines = flat(streams.out.getvalue())
    shown = flat(
        "\n".join(
            line for line in made.out.getvalue().splitlines() if not line.startswith(("[", "  "))
        )
    )
    assert lines == shown
    assert " 3 songs: 1 ok, 1 review, 1 failed" in f" {lines}"
    assert library.store.writes == []


def test_each_song_has_a_report_with_verdict_numbers_times_and_outputs(library: FakeWorld) -> None:
    make(library)
    text = library.store.read_text(work("Volkslied - Entchen") / "report.json")
    assert text is not None
    report = ReportFile.model_validate_json(text)
    assert (report.status, report.reasons, report.duration) == ("ok", [], 185.0)
    assert report.outputs[0] == "Volkslied - Entchen.mp4"
    assert report.quality is not None and report.quality.words > 0
    assert report.lyrics == "ok"
    assert report.stage_seconds["separation"] == TOOK
    review = ReportFile.model_validate_json(
        library.store.read_text(work("Volkslied - Messy") / "report.json") or ""
    )
    assert review.status == "review"
    assert all(reason.startswith("lyrics: ") for reason in review.reasons)
    broken = ReportFile.model_validate_json(
        library.store.read_text(work("c") / "report.json") or ""
    )
    assert (broken.status, broken.error is not None, broken.outputs) == ("failed", True, [])


def test_a_second_run_skips_everything_and_force_runs_everything(library: FakeWorld) -> None:
    make(library)
    runs = len(library.renderer.requests)
    _, again = make(library)
    assert len(library.renderer.requests) == runs == 2
    assert again.out.getvalue().count("separation: skipped") == 2
    assert "ran" not in again.out.getvalue().replace("ran in", "").replace("rank", "")
    make(library, force=True)
    assert len(library.renderer.requests) == 2 * runs
    assert len(library.separator.requests) == 4


def test_a_second_run_keeps_the_processing_time_of_the_first(library: FakeWorld) -> None:
    make(library)
    _, again = make(library)
    assert "2m 05s" in again.out.getvalue()  # the skipped separation still counts


def test_a_changed_lyrics_file_runs_only_the_stages_that_depend_on_it(library: FakeWorld) -> None:
    make(library)
    separations = len(library.separator.requests)
    library.store.add((MUSIC / "a.txt"), HAENSCHEN.encode())
    _, streams = make(library)
    assert len(library.separator.requests) == separations  # the audio did not change
    log = "\n".join(library.store.log_lines(work("Volkslied - Entchen") / "log.txt"))
    last_run = log.split("probe: skipped, output is current")[-1]
    for stage in ("lyrics", "alignment", "syllables", "layout", "render", "cdg"):
        assert f"{stage}: done" in last_run
    assert "separation: skipped" in last_run
    assert "Volkslied - Messy" in streams.out.getvalue()


def test_a_song_that_outlasts_its_safety_limit_fails_and_the_batch_goes_on(
    library: FakeWorld,
) -> None:
    def slow(request: SeparationRequest) -> None:
        library.clock.wait(10 * 185 + 600 + 1 if request.audio.name == "a.mp3" else 1)

    library.separator.during = slow
    code, streams = make(library)
    assert code == 1
    status = SongStatus.model_validate_json(
        library.store.read_text(work("Volkslied - Entchen") / "status.json") or ""
    )
    assert status.state == "failed"
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("tempo", "time-limit")
    assert "time limit of 40m 50s" in status.error.message  # 10 x 185 s + 10 minutes
    assert library.acoustic.requests  # the next song went on to its alignment
    assert "Volkslied - Messy" in streams.out.getvalue()
    assert library.store.size(OUT / "Volkslied - Messy.mp4") is not None


def test_the_time_left_of_the_song_reaches_the_engines(library: FakeWorld) -> None:
    seen: list[float | None] = []
    library.separator.during = lambda request: seen.append(request.watch.time_left())
    make(library)
    assert seen[0] == 10 * 185 + 600  # nothing has passed on the fake clock yet
    assert seen[1] == 10 * 240 + 600


def test_a_work_folder_that_cannot_be_written_fails_its_song_and_the_batch_goes_on(
    library: FakeWorld,
) -> None:
    library.store.full.add(work("Volkslied - Entchen"))
    code, streams = make(library)
    assert code == 1
    out = flat(streams.out.getvalue())
    assert (
        "failed - 0s Volkslied - Entchen probe: cannot write the work folder: No space left" in out
    )
    assert library.store.size(OUT / "Volkslied - Messy.mp4") is not None
    assert "3 songs: 1 ok, 1 review, 1 failed" not in out
    assert "2 failed" in out  # the unreadable one, and this one


def test_a_disk_that_fills_up_in_the_middle_of_a_song_fails_that_song(library: FakeWorld) -> None:
    def fill(request: SeparationRequest) -> None:
        if request.audio.name == "a.mp3":
            library.store.full.add(work("Volkslied - Entchen"))

    library.separator.during = fill
    code, streams = make(library)
    out = streams.out.getvalue()
    line = summary_line(out, "failed", "Volkslied - Entchen")
    assert line is not None
    assert "separation: No space left on device" in line
    assert code == 1
    assert library.store.size(OUT / "Volkslied - Messy.mp4") is not None


def test_the_first_ctrl_c_finishes_the_stage_and_keeps_the_work(library: FakeWorld) -> None:
    streams = Streams(library)
    library.separator.during = lambda request: streams.edges.stop.request()
    code = run_make(MUSIC, output=None, config_file=None, edges=streams.edges)
    assert code == 1
    out = streams.out.getvalue()
    assert "interrupted in tempo" in out  # the separation was finished, the next stage not begun
    assert "stopped on request" in out
    assert len(library.separator.requests) == 1  # the other songs never started
    assert library.store.size(work("Volkslied - Entchen") / "stems" / "lead.flac") is not None
    assert library.store.logs[work("Volkslied - Entchen") / "log.txt"].closed == 1
    assert library.store.read_text(OUT / "vocatron-report.txt") is not None

    library.separator.during = lambda request: library.clock.wait(TOOK)
    _, again = make(library)  # a new run: the finished separation is not repeated
    assert len(library.separator.requests) == 2  # a.mp3 is not repeated; b.mp3 is new
    assert summary_line(again.out.getvalue(), "ok", "Volkslied - Entchen")


def test_the_second_ctrl_c_stops_at_once_and_leaves_the_song_interrupted(
    library: FakeWorld,
) -> None:
    def second(request: SeparationRequest) -> None:
        raise KeyboardInterrupt

    library.separator.during = second
    streams = Streams(library)
    assert run_make(MUSIC, output=None, config_file=None, edges=streams.edges) == 1
    out = streams.out.getvalue()
    assert "interrupted in separation" in out
    assert "stopped on request" in out
    status = SongStatus.model_validate_json(
        library.store.read_text(work("Volkslied - Entchen") / "status.json") or ""
    )
    assert (status.state, status.current) == ("running", "separation")
    assert library.store.logs[work("Volkslied - Entchen") / "log.txt"].closed == 1


def test_the_live_progress_is_written_for_status_and_removed_when_the_song_is_done(
    library: FakeWorld,
) -> None:
    shown: list[str] = []

    def look(request: SeparationRequest) -> None:
        if request.audio.name != "a.mp3":
            return
        library.clock.wait(3)  # past the two seconds between writes
        request.watch.progress(0.75)
        file = ProgressFile.model_validate_json(
            library.store.read_text(work("Volkslied - Entchen") / "progress.json") or ""
        )
        assert (file.stage, file.fraction) == ("separation", 0.75)
        streams = Streams(library)
        run_status(MUSIC, output=None, config_file=None, edges=streams.edges)
        shown.append(streams.out.getvalue().splitlines()[0])

    library.separator.during = look
    make(library)
    assert summary_line(shown[0], "running", "Volkslied - Entchen")
    assert "separation 75%, about " in shown[0]
    assert "interrupted" not in shown[0]
    assert library.store.size(work("Volkslied - Entchen") / "progress.json") is None


def test_an_old_progress_file_belongs_to_a_run_that_died(library: FakeWorld) -> None:
    make(library)
    path = work("Volkslied - Entchen")
    stale = ProgressFile(
        stage="render", fraction=0.5, left=10.0, updated="2020-01-01T00:00:00+00:00"
    )
    library.store.add(path / "progress.json", stale.model_dump_json().encode())
    status = SongStatus.model_validate_json(library.store.read_text(path / "status.json") or "")
    died = status.model_copy(update={"state": "running", "current": "render"})
    library.store.add(path / "status.json", died.model_dump_json().encode())
    streams = Streams(library)
    run_status(MUSIC, output=None, config_file=None, edges=streams.edges)
    assert "interrupted in render" in streams.out.getvalue()


def test_the_speeds_of_the_stages_are_learnt_per_machine_in_the_clone(library: FakeWorld) -> None:
    make(library)
    text = library.store.read_text(CLONE / ".cache" / "timings.json")
    assert text is not None
    learnt = Timings.model_validate_json(text)
    # the fake separation takes 125 s for songs of 185 s and 240 s: the average of both runs
    assert learnt.speeds["separation:cpu"].speed == pytest.approx(
        (TOOK / 185 + TOOK / 240) / 2, rel=1e-6
    )
    assert learnt.speeds["separation:cpu"].runs == 2
    assert FAKE_SECONDS  # the fake's own length is not what is learnt


def test_without_a_terminal_the_output_is_plain_lines(library: FakeWorld) -> None:
    _, streams = make(library)
    out = streams.out.getvalue()
    assert "\x1b" not in out
    assert "[1/3] Volkslied - Entchen ..." in out
    assert "  separation: ran in 2m 05s" in out


def test_on_a_terminal_the_batch_is_shown_live_and_the_summary_stays(library: FakeWorld) -> None:
    streams = Streams(library)
    stream = StringIO()
    live = Console(file=stream, width=100, force_terminal=True, color_system=None)
    edges = replace(streams.edges, console=live)
    assert run_make(MUSIC, output=None, config_file=None, edges=edges) == 1
    shown = stream.getvalue()
    assert "elapsed" in shown  # the live batch line was drawn
    assert "3:05   2m 05s  Volkslied - Entchen" in shown  # and the summary line scrolled above it
    assert "3 songs: 1 ok, 1 review, 1 failed" in shown


def test_the_log_option_follows_the_whole_song_log_instead_of_the_stage_lines(
    library: FakeWorld,
) -> None:
    streams = Streams(library)
    edges = replace(streams.edges, log=True)

    def worker(request: SeparationRequest) -> None:  # the GPU worker writes to the log itself
        stamp = "2026-10-29T12:00:00"
        library.store.open_log(request.log_path).write(f"{stamp} separation worker: piece 1 of 2")

    library.separator.during = worker
    run_make(MUSIC, output=None, config_file=None, edges=edges)
    out = streams.out.getvalue().splitlines()

    def at(start: str, end: str = "") -> int:
        (index,) = [  # each line exactly once
            i for i, line in enumerate(out) if line.startswith(start) and line.endswith(end)
        ]
        return index

    song = "Volkslied - Entchen: "
    worker_line = at(song, " separation worker: piece 1 of 2")
    assert at(song, " separation: running") < worker_line < at(song, " separation: done")
    summary = summary_line("\n".join(out), "ok", "Volkslied - Entchen")
    assert summary is not None
    assert at(song, " render: done") < out.index(summary)  # then its summary
    assert not any(line.startswith("  separation: ran in") for line in out)


def test_a_run_that_stops_before_the_end_leaves_the_report_file_alone(library: FakeWorld) -> None:
    make(library)
    before = library.store.read_text(OUT / "vocatron-report.txt")
    streams = Streams(library)
    run_lyrics(MUSIC, output=None, config_file=None, force=False, edges=streams.edges)
    assert library.store.read_text(OUT / "vocatron-report.txt") == before


def test_a_ctrl_c_in_the_last_stage_of_the_last_song_stops_nothing(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3", tags=Tags("Volkslied", "Entchen", 185), lyrics=ENTCHEN)
    world.store.add(Path("/work/vocatron.yaml"), b"outputs: [mp4, cdg]\n")  # cdg is the last stage
    streams = Streams(world)
    world.mp3.during = lambda request: streams.edges.stop.request()
    assert run_make(MUSIC, output=None, config_file=None, edges=streams.edges) == 0
    out = streams.out.getvalue()
    assert "stopped on request" not in out
    assert summary_line(out, "ok", "Volkslied - Entchen")
