"""Stage 1: the commands on fakes, with the console output as golden text."""

from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from fakes.songs import FakeWorld
from fakes.streams import Streams
from vocatron.cli.commands import run_make, run_status
from vocatron.core.song import Tags
from vocatron.core.status import SongStatus
from vocatron.stages.batch import Options

MUSIC = Path("/music")


@pytest.fixture
def mixed(world: FakeWorld) -> FakeWorld:
    world.add_song(MUSIC / "a.mp3", tags=Tags("Queen", "Radio Ga Ga", 240))
    world.add_song(MUSIC / "b.mp3", tags=None)
    world.add_song(MUSIC / "c.mp3", tags=Tags("Queen", "Radio Ga Ga", None))
    return world


def test_make_prints_one_line_per_song_progress_and_a_summary(
    mixed: FakeWorld, snapshot: SnapshotAssertion
) -> None:
    streams = Streams(mixed)
    code = run_make(MUSIC, output=None, config_file=None, edges=streams.edges)
    assert code == 1
    assert streams.out.getvalue() == snapshot


def test_status_prints_the_stored_status_without_running(
    mixed: FakeWorld, snapshot: SnapshotAssertion
) -> None:
    before = Streams(mixed)
    assert run_status(MUSIC, output=None, config_file=None, edges=before.edges) == 0
    assert "not run" in before.out.getvalue()
    assert mixed.store.writes == []
    run_make(MUSIC, output=None, config_file=None, edges=Streams(mixed).edges)
    after = Streams(mixed)
    assert run_status(MUSIC, output=None, config_file=None, edges=after.edges) == 1
    assert after.out.getvalue() == snapshot


def test_a_batch_without_failures_exits_with_zero(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    streams = Streams(world)
    assert (
        run_make(
            MUSIC / "a.mp3",
            output="out",
            config_file=None,
            options=Options(force=True),
            edges=streams.edges,
        )
        == 0
    )
    assert "1 song: 1 ok, 0 review, 0 failed" in streams.out.getvalue()
    assert Path("/work/out/Artist - Title/status.json") in world.store.files  # relative to cwd


def test_usage_errors_exit_with_two_and_go_to_the_error_console(world: FakeWorld) -> None:
    streams = Streams(world)
    code = run_make(MUSIC / "nope.mp3", output=None, config_file=None, edges=streams.edges)
    assert code == 2
    assert "does not exist" in streams.err.getvalue()
    assert streams.out.getvalue() == ""


def test_config_errors_exit_with_two_and_name_the_position(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    world.store.add(Path("/work/vocatron.yaml"), b"probe:\n  min_duration: soon\n")
    streams = Streams(world)
    assert run_status(MUSIC, output=None, config_file=None, edges=streams.edges) == 2
    assert "/work/vocatron.yaml:2:3: probe.min_duration" in streams.err.getvalue()


def test_status_reports_an_interrupted_song_and_exits_with_one(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    run_make(MUSIC, output=None, config_file=None, edges=Streams(world).edges)
    path = MUSIC / "karaoke" / "Artist - Title" / "status.json"
    stored = SongStatus.model_validate_json(world.store.files[path])
    interrupted = stored.model_copy(update={"state": "running", "current": "probe"})
    world.store.add(path, interrupted.model_dump_json().encode())
    streams = Streams(world)
    assert run_status(MUSIC, output=None, config_file=None, edges=streams.edges) == 1
    assert streams.out.getvalue().splitlines() == [
        "running   3:00        -  Artist - Title  interrupted in probe",
        "1 song: 0 ok, 0 review, 0 failed, 1 interrupted in 0s",
    ]


def test_an_output_folder_that_cannot_be_created_is_a_usage_error(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    world.store.unwritable.add(Path("/locked"))
    streams = Streams(world)
    code = run_make(MUSIC, output="/locked/out", config_file=None, edges=streams.edges)
    assert code == 2
    assert streams.err.getvalue().strip() == (
        "error: cannot create the output folder /locked/out: Permission denied"
    )
    assert streams.out.getvalue() == ""
    assert world.store.writes == []
