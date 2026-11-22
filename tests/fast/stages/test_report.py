"""Stage 1: reading the stage files into a report, and the summary rows of stored songs."""

from datetime import timedelta
from pathlib import Path

from fakes.songs import FakeWorld
from vocatron.core.progress import ProgressFile
from vocatron.core.report import ReportFile
from vocatron.core.status import SongStatus
from vocatron.stages.report import (
    REPORT_FILE,
    REPORT_TEXT,
    findings_of,
    make_report,
    stored_row,
    write_report_text,
)

MUSIC = Path("/music")
WORK = MUSIC / "karaoke" / "Artist - Title"


def made(world: FakeWorld) -> FakeWorld:
    world.add_song(MUSIC / "a.mp3")
    assert world.run(MUSIC / "a.mp3").state == "ok"
    return world


def test_the_findings_come_from_the_stage_files(world: FakeWorld) -> None:
    made(world)
    found = findings_of(world.song(MUSIC / "a.mp3"), world.store)
    assert found.duration == 180.0
    assert found.lyrics == "ok"
    assert found.quality is not None
    assert found.quality.words > 0
    assert found.rails in {"used", "ignored", "none"}
    assert found.outputs[0] == "Artist - Title.mp4"


def test_stage_files_that_are_missing_or_broken_leave_the_findings_empty(world: FakeWorld) -> None:
    made(world)
    world.store.add(WORK / "alignment.json", b"{broken")
    world.store.files.pop(WORK / "render.json")
    found = findings_of(world.song(MUSIC / "a.mp3"), world.store)
    assert (found.quality, found.rails, found.outputs) == (None, None, ())
    assert found.duration == 180.0


def test_a_work_folder_that_cannot_be_written_still_gives_the_report(world: FakeWorld) -> None:
    made(world)
    song = world.song(MUSIC / "a.mp3")
    status = SongStatus.model_validate_json(world.store.read_text(WORK / "status.json") or "")
    world.store.files.pop(WORK / REPORT_FILE)
    world.store.full.add(WORK)
    report = make_report(song, status, {"probe": 1.5}, world.store)
    assert (report.status, report.stage_seconds) == ("ok", {"probe": 1.5})
    assert WORK / REPORT_FILE not in world.store.files


def test_the_report_of_an_earlier_run_gives_the_times_of_skipped_stages(world: FakeWorld) -> None:
    made(world)
    song = world.song(MUSIC / "a.mp3")
    first = ReportFile.model_validate_json(world.store.read_text(WORK / REPORT_FILE) or "")
    status = SongStatus.model_validate_json(world.store.read_text(WORK / "status.json") or "")
    second = make_report(song, status, {"render": 9.0}, world.store)
    assert second.stage_seconds["render"] == 9.0
    assert {k: v for k, v in second.stage_seconds.items() if k != "render"} == {
        k: v for k, v in first.stage_seconds.items() if k != "render"
    }


def test_a_song_never_run_has_a_not_run_row(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    assert stored_row(world.song(MUSIC / "a.mp3"), world.engines).state == "not run"


def test_a_finished_song_has_its_row_from_the_report(world: FakeWorld) -> None:
    made(world)
    row = stored_row(world.song(MUSIC / "a.mp3"), world.engines)
    assert (row.state, row.length, row.detail) == ("ok", 180.0, "")  # the track has the song's name


def test_a_song_with_a_status_but_no_report_has_a_row_from_the_status(world: FakeWorld) -> None:
    made(world).store.files.pop(WORK / REPORT_FILE)
    row = stored_row(world.song(MUSIC / "a.mp3"), world.engines)
    assert (row.state, row.length, row.seconds) == ("ok", 180.0, None)


def running(world: FakeWorld, updated: str) -> None:
    made(world)
    status = SongStatus.model_validate_json(world.store.read_text(WORK / "status.json") or "")
    died = status.model_copy(update={"state": "running", "current": "alignment"})
    world.store.add(WORK / "status.json", died.model_dump_json().encode())
    live = ProgressFile(stage="alignment", fraction=0.25, left=65.0, updated=updated)
    world.store.add(WORK / "progress.json", live.model_dump_json().encode())


def test_a_running_song_with_fresh_progress_shows_stage_percentage_and_time_left(
    world: FakeWorld,
) -> None:
    running(world, (world.clock.now() + timedelta(seconds=-20)).isoformat())
    row = stored_row(world.song(MUSIC / "a.mp3"), world.engines)
    assert (row.state, row.detail) == ("running", "alignment 25%, about 1m 05s left")


def test_a_running_song_with_old_progress_was_interrupted(world: FakeWorld) -> None:
    running(world, "2020-01-01T00:00:00+00:00")
    row = stored_row(world.song(MUSIC / "a.mp3"), world.engines)
    assert (row.state, row.detail) == ("interrupted", "interrupted in alignment")


def test_the_report_text_is_written_into_the_output_folder_and_overwritten(
    world: FakeWorld,
) -> None:
    made(world)
    song = world.song(MUSIC / "a.mp3")
    row = stored_row(song, world.engines)
    write_report_text(song.output_dir, [row], 12.0, world.clock.now(), world.store)
    first = world.store.read_text(song.output_dir / REPORT_TEXT) or ""
    assert first.startswith("Vocatron report, 2026-01-02")
    write_report_text(song.output_dir, [row, row], 99.0, world.clock.now(), world.store)
    assert world.store.read_text(song.output_dir / REPORT_TEXT) != first


def test_a_report_text_that_cannot_be_written_is_no_error(world: FakeWorld) -> None:
    made(world)
    song = world.song(MUSIC / "a.mp3")
    world.store.full.add(song.output_dir)
    write_report_text(song.output_dir, [], 1.0, world.clock.now(), world.store)


def test_the_report_names_the_lines_of_a_second_voice_and_where_each_came_from(
    world: FakeWorld,
) -> None:
    world.add_song(MUSIC / "a.mp3", lyrics="eins zwei\n{&} drei vier\nfünf sechs\n")
    world.acoustic.backing_only = frozenset({2, 3})  # the words of the marked line
    assert world.run(MUSIC / "a.mp3").state == "ok"
    report = ReportFile.model_validate_json(world.store.read_text(WORK / REPORT_FILE) or "")
    assert [(x.line, x.source) for x in report.second_voice] == [(2, "mark")]
    assert report.schema_version == 3


def test_a_song_with_one_voice_has_no_second_voice_in_its_report(world: FakeWorld) -> None:
    made(world)
    report = ReportFile.model_validate_json(world.store.read_text(WORK / REPORT_FILE) or "")
    assert report.second_voice == []
