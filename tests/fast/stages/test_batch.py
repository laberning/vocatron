"""Stage 1: the batch runner on fakes (skip, force, status, errors, logs)."""

import json
from pathlib import Path
from typing import Literal, override

import pytest
from syrupy.assertion import SnapshotAssertion

from fakes.files import MemoryLog
from fakes.models import returning, tiny_spec
from fakes.songs import FakeWorld
from fakes.stages import NeedsModelStage
from vocatron.core.song import Tags
from vocatron.core.stage_file import Fingerprint, StageFile
from vocatron.core.status import SongStatus
from vocatron.engines.protocols import SeparationRequest
from vocatron.stages import batch, models
from vocatron.stages.batch import (
    Hooks,
    Options,
    StopFlag,
    make_song,
    run_batch,
    run_song,
    time_limit,
)
from vocatron.stages.config import BatchSettings, Config, ModelsSettings, ProbeSettings
from vocatron.stages.lyrics import LyricsStage
from vocatron.stages.probe import ProbeStage
from vocatron.stages.progress import NullSink
from vocatron.stages.report import SongResult, stored_row
from vocatron.stages.songs import discover
from vocatron.stages.stage import Song, StageContext, TypedStage

MUSIC = Path("/music")
WORK = MUSIC / "karaoke" / "Artist - Title"


class EchoFile(StageFile):
    SCHEMA_NAME = "echo"
    schema_version: Literal[1] = 1
    title: str


class EchoStage(TypedStage[ProbeSettings]):
    """A second stage that reads ``song.json``; it asks for review of titles with an exclamation."""

    name = "echo"
    version = 1
    inputs = ("song.json",)
    output = "echo.json"
    output_model = EchoFile

    def settings_from(self, config: Config) -> ProbeSettings:
        return config.probe

    def run(
        self, ctx: StageContext, settings: ProbeSettings, fingerprint: Fingerprint
    ) -> StageFile:
        text = ctx.engines.store.read_text(ctx.song.work_dir / "song.json")
        assert text is not None
        title = str(json.loads(text)["title"])
        return EchoFile(
            fingerprint=fingerprint, title=title, reasons=["shouting"] if "!" in title else []
        )


class BoomStage(EchoStage):
    name = "boom"
    output = "boom.json"

    @override
    def run(
        self, ctx: StageContext, settings: ProbeSettings, fingerprint: Fingerprint
    ) -> StageFile:
        raise RuntimeError("kaboom")


class Recorder(NullSink):
    def __init__(self) -> None:
        self.events: list[str] = []

    @override
    def song_started(self, index: int, song: Song) -> None:
        self.events.append(f"start {index} {song.name}")

    @override
    def song_finished(self, index: int, result: SongResult) -> None:
        self.events.append(f"done {index} {result.status.state}")


def songs_of(world: FakeWorld, config: Config | None = None) -> list[Song]:
    return discover(MUSIC, config or Config(), world.engines)


def run_all(
    world: FakeWorld, *, force: bool = False, config: Config | None = None
) -> list[SongStatus]:
    cfg = config or Config()
    hooks = Hooks(Recorder())
    results = run_batch(songs_of(world, cfg), cfg, world.engines, Options(force=force), hooks)
    return [result.status for result in results]


def stage_writes(world: FakeWorld, name: str) -> int:
    return sum(1 for p in world.store.writes if p.name == name)


@pytest.fixture
def one_song(world: FakeWorld) -> FakeWorld:
    world.add_song(MUSIC / "a.mp3")
    return world


def test_first_run_writes_stage_file_status_and_log_in_the_work_folder(one_song: FakeWorld) -> None:
    (status,) = run_all(one_song)
    assert status.state == "ok"
    assert status.stages[0].action == "ran"
    assert {p.name for p in one_song.store.writes} == {
        "song.json",
        "lyrics.json",
        "separation.json",
        "tempo.json",
        "alignment.json",
        "syllables.json",
        "layout.json",
        "lyrics.ass",
        "render.json",
        "cdg.json",
        "Artist - Title.lrc",  # the track itself goes to the output folder
        "status.json",
        "report.json",
    }
    assert all(WORK.parent in p.parents for p in one_song.store.writes)  # the music is untouched
    assert one_song.store.log_lines(WORK / "log.txt")[0].endswith("probe: running")
    assert one_song.store.logs[WORK / "log.txt"].closed == 1


def test_status_json_is_golden(one_song: FakeWorld, snapshot: SnapshotAssertion) -> None:
    run_all(one_song)
    assert one_song.store.read_text(WORK / "status.json") == snapshot
    assert one_song.store.read_text(WORK / "song.json") == snapshot


def test_a_second_run_skips_unchanged_stages(one_song: FakeWorld) -> None:
    run_all(one_song)
    (status,) = run_all(one_song)
    assert status.stages[0].action == "skipped"
    assert stage_writes(one_song, "song.json") == 1
    assert stage_writes(one_song, "status.json") >= 2


def test_changed_audio_reruns_the_stage(one_song: FakeWorld) -> None:
    run_all(one_song)
    one_song.store.add(MUSIC / "a.mp3", b"different audio")
    assert run_all(one_song)[0].stages[0].action == "ran"


def test_changed_settings_rerun_the_stage(one_song: FakeWorld) -> None:
    run_all(one_song)
    config = Config(probe=ProbeSettings(min_duration=2.0))
    assert run_all(one_song, config=config)[0].stages[0].action == "ran"


def test_force_reruns_everything(one_song: FakeWorld) -> None:
    run_all(one_song)
    assert run_all(one_song, force=True)[0].stages[0].action == "ran"
    assert stage_writes(one_song, "song.json") == 2


def test_an_invalid_stored_file_is_replaced(one_song: FakeWorld) -> None:
    run_all(one_song)
    one_song.store.add(WORK / "song.json", b'{"schema_version": 99}')
    assert run_all(one_song)[0].stages[0].action == "ran"
    assert "invalid" in "\n".join(one_song.store.log_lines(WORK / "log.txt"))
    one_song.store.add(WORK / "song.json", b"\xff not text")
    assert run_all(one_song)[0].stages[0].action == "ran"


def test_a_stage_reading_a_stage_file_follows_its_content(
    one_song: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batch, "STAGES", (ProbeStage(), EchoStage()))
    assert [o.action for o in run_all(one_song)[0].stages] == ["ran", "ran"]
    assert [o.action for o in run_all(one_song)[0].stages] == ["skipped", "skipped"]
    song_json = one_song.store.read_text(WORK / "song.json")
    assert song_json is not None
    one_song.store.add(WORK / "song.json", song_json.replace('"Title"', '"Title!"').encode())
    status = run_all(one_song)[0]
    assert [o.action for o in status.stages] == [
        "skipped",
        "ran",
    ]  # a hand edit re-runs what follows
    assert (status.state, status.reasons) == ("review", ["echo: shouting"])
    again = run_all(one_song)[0]
    assert (again.state, again.reasons) == ("review", ["echo: shouting"])  # kept when skipped


def test_status_is_written_before_every_stage_and_at_the_end(
    one_song: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batch, "STAGES", (ProbeStage(), EchoStage()))
    seen: list[tuple[int, str, str | None]] = []
    original = one_song.store.write_text

    def spy(path: Path, text: str) -> None:
        original(path, text)
        if path.name == "status.json":
            status = SongStatus.model_validate_json(text)
            seen.append((len(status.stages), status.state, status.current))

    monkeypatch.setattr(one_song.store, "write_text", spy)
    run_all(one_song)
    assert seen == [(0, "running", "probe"), (1, "running", "echo"), (2, "ok", None)]


class Killed(BaseException):
    """Stands for a kill or a crash of the process: nothing in the frame catches it."""


class KilledStage(EchoStage):
    name = "killed"
    output = "killed.json"

    @override
    def run(
        self, ctx: StageContext, settings: ProbeSettings, fingerprint: Fingerprint
    ) -> StageFile:
        raise Killed


def test_an_interrupted_song_is_left_running_in_its_stage(
    one_song: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batch, "STAGES", (ProbeStage(), KilledStage()))
    with pytest.raises(Killed):
        run_all(one_song)
    text = one_song.store.read_text(WORK / "status.json")
    assert text is not None
    status = SongStatus.model_validate_json(text)
    assert (status.state, status.current, len(status.stages)) == ("running", "killed", 1)
    assert one_song.store.logs[WORK / "log.txt"].closed == 1
    assert SongStatus.model_validate_json(text) == status


def test_a_failing_song_does_not_stop_the_others(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3", tags=Tags("A", "Good", 60))
    world.add_song(MUSIC / "b.mp3", tags=None)
    world.add_song(MUSIC / "c.mp3", tags=Tags("C", "Short", 0.2))
    world.add_song(MUSIC / "d.mp3", tags=Tags("D", "Unknown length", None))
    recorder = Recorder()
    cfg = Config()
    batch_results = run_batch(songs_of(world), cfg, world.engines, Options(), Hooks(recorder))
    results = [result.status for result in batch_results]
    assert [r.state for r in results] == ["ok", "failed", "failed", "review"]
    assert [r.error.kind if r.error else None for r in results] == [
        None,
        "unreadable-audio",
        "too-short",
        None,
    ]
    assert results[3].reasons == ["probe: duration unknown"]
    assert results[1].stages[-1].action == "failed"
    assert recorder.events[:2] == ["start 0 A - Good", "done 0 ok"]
    assert len(recorder.events) == 8


def test_an_unexpected_error_fails_the_song_and_logs_the_traceback(
    one_song: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batch, "STAGES", (ProbeStage(), BoomStage(), EchoStage()))
    status = run_all(one_song)[0]
    assert status.state == "failed"
    assert status.error is not None
    assert (status.error.stage, status.error.kind, status.error.message) == (
        "boom",
        "RuntimeError",
        "kaboom",
    )
    assert [o.stage for o in status.stages] == ["probe", "boom"]  # later stages are not tried
    log = "\n".join(one_song.store.log_lines(WORK / "log.txt"))
    assert "Traceback" in log
    assert "RuntimeError: kaboom" in log
    assert one_song.store.logs[WORK / "log.txt"].closed == 1


def test_a_missing_input_file_fails_the_stage(
    one_song: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batch, "STAGES", (EchoStage(),))
    status = run_all(one_song)[0]
    assert status.error is not None
    assert status.error.kind == "missing-input"
    assert status.current is None


def test_run_song_never_raises_and_returns_the_final_status(one_song: FakeWorld) -> None:
    (song,) = songs_of(one_song)
    assert run_song(song, Config(), one_song.engines, force=False).state == "ok"


def test_the_stored_rows_report_not_run_valid_and_broken_files(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3", tags=Tags("A", "One", 60))
    world.add_song(MUSIC / "b.mp3", tags=Tags("B", "Two", 60))
    world.add_song(MUSIC / "c.mp3", tags=Tags("C", "Three", 60))
    songs = songs_of(world)
    run_song(songs[0], Config(), world.engines, force=False)
    world.store.add(songs[1].work_dir / "status.json", b"{not json")
    world.store.add(songs[2].work_dir / "status.json", b"\xff not text")
    rows = [stored_row(song, world.engines) for song in songs]
    assert [row.state for row in rows] == ["ok", "not run", "not run"]
    assert (
        world.store.writes.count(songs[0].work_dir / "status.json") == 10
    )  # reading wrote nothing


@pytest.fixture
def model_stage(one_song: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> FakeWorld:
    spec = tiny_spec("tiny", {"w.bin": b"weights"})
    one_song.downloader.serve(spec, {"w.bin": b"weights"})
    monkeypatch.setattr(models, "find_model", returning(spec))
    monkeypatch.setattr(batch, "STAGES", (ProbeStage(), NeedsModelStage()))
    return one_song


def test_a_stage_downloads_the_models_it_declares_on_first_use(model_stage: FakeWorld) -> None:
    assert run_all(model_stage)[0].state == "ok"
    assert [url for url, _ in model_stage.downloader.calls] == ["fake://tiny/w.bin"]
    assert ".cache/models/tiny/w.bin" in str(model_stage.downloader.calls[0][1])
    log = "\n".join(model_stage.store.log_lines(WORK / "log.txt"))
    assert "models: downloading tiny" in log
    run_all(model_stage, force=True)
    assert len(model_stage.downloader.calls) == 1  # already there


def test_a_skipped_stage_does_not_fetch_its_models(model_stage: FakeWorld) -> None:
    run_all(model_stage)
    model_stage.store.files = {
        p: d for p, d in model_stage.store.files.items() if "tiny" not in p.parts
    }
    status = run_all(model_stage)[0]
    assert [o.action for o in status.stages] == ["skipped", "skipped"]
    assert len(model_stage.downloader.calls) == 1


def test_offline_fails_the_song_and_names_the_command(model_stage: FakeWorld) -> None:
    (song,) = songs_of(model_stage)
    status = run_song(song, Config(), model_stage.engines, force=False, offline=True)
    assert status.state == "failed"
    assert status.error is not None
    assert status.error.kind == "models-missing"
    assert "vocatron models download tiny" in status.error.message
    assert model_stage.downloader.calls == []


def test_a_model_folder_from_the_configuration_is_used(model_stage: FakeWorld) -> None:
    config = Config(models=ModelsSettings(folder="/elsewhere"))
    run_all(model_stage, config=config)
    assert model_stage.downloader.calls[0][1] == Path("/elsewhere/tiny/w.bin")


def test_a_failed_download_fails_the_song(model_stage: FakeWorld) -> None:
    model_stage.downloader.fail_on = {"fake://tiny/w.bin"}
    status = run_all(model_stage)[0]
    assert status.error is not None
    assert status.error.kind == "model-download"


def test_a_partial_run_keeps_what_the_status_recorded_for_later_stages(
    one_song: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batch, "STAGES", (ProbeStage(), LyricsStage(), EchoStage()))
    config = Config()
    (song,) = songs_of(one_song)
    full = run_song(song, config, one_song.engines, force=False)
    assert [o.stage for o in full.stages] == ["probe", "lyrics", "echo"]
    partial = run_song(song, config, one_song.engines, force=True, until="lyrics")
    assert [(o.stage, o.action) for o in partial.stages] == [
        ("probe", "ran"),
        ("lyrics", "ran"),
        ("echo", "ran"),  # recorded by the full run, not run now
    ]
    assert partial.state == "ok"


def test_a_partial_run_keeps_a_later_failure(
    one_song: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(batch, "STAGES", (ProbeStage(), LyricsStage(), BoomStage()))
    (song,) = songs_of(one_song)
    assert run_song(song, Config(), one_song.engines, force=False).state == "failed"
    partial = run_song(song, Config(), one_song.engines, force=False, until="lyrics")
    assert partial.state == "failed"
    assert partial.error is not None
    assert partial.error.stage == "boom"
    assert [o.action for o in partial.stages] == ["skipped", "skipped", "failed"]


def test_a_partial_run_marks_the_later_stages_outdated_when_their_inputs_changed(
    one_song: FakeWorld,
) -> None:
    (song,) = songs_of(one_song)
    run_song(song, Config(), one_song.engines, force=False)
    one_song.store.add((MUSIC / "a.txt"), b"Ein ganz anderes Lied\nvon der weiten Welt\n")
    partial = run_song(song, Config(), one_song.engines, force=False, until="lyrics")
    assert [(o.stage, o.action) for o in partial.stages] == [
        ("probe", "skipped"),
        ("lyrics", "ran"),
        ("separation", "ran"),  # the stems do not depend on the lyrics: still current
        ("tempo", "ran"),
        ("alignment", "outdated"),
        ("syllables", "outdated"),
        ("layout", "outdated"),
        ("render", "outdated"),
        ("cdg", "outdated"),
    ]
    assert partial.state == "review"
    assert partial.reasons == [
        "alignment: not finished, run `vocatron make`",
        "syllables: not finished, run `vocatron make`",
        "layout: not finished, run `vocatron make`",
        "render: not finished, run `vocatron make`",
        "cdg: not finished, run `vocatron make`",
    ]
    finished = run_song(song, Config(), one_song.engines, force=False)
    assert finished.state == "ok"
    assert [o.action for o in finished.stages][-5:] == ["ran"] * 5


def test_a_partial_run_keeps_later_stages_that_are_still_current(one_song: FakeWorld) -> None:
    (song,) = songs_of(one_song)
    run_song(song, Config(), one_song.engines, force=False)
    partial = run_song(song, Config(), one_song.engines, force=False, until="lyrics")
    assert partial.state == "ok"
    assert [o.action for o in partial.stages][-3:] == ["ran", "ran", "ran"]


def test_a_stage_that_was_running_when_the_earlier_run_died_stays_interrupted(
    one_song: FakeWorld,
) -> None:
    (song,) = songs_of(one_song)
    run_song(song, Config(), one_song.engines, force=False)
    recorded = SongStatus.model_validate_json(
        one_song.store.read_text(song.work_dir / "status.json") or ""
    )
    died = recorded.model_copy(update={"state": "running", "current": "alignment"})
    one_song.store.add(song.work_dir / "status.json", died.model_dump_json().encode())
    partial = run_song(song, Config(), one_song.engines, force=False, until="lyrics")
    assert [(o.stage, o.action) for o in partial.stages][-5:] == [
        ("alignment", "interrupted"),
        ("syllables", "ran"),
        ("layout", "ran"),
        ("render", "ran"),
        ("cdg", "ran"),
    ]
    assert partial.state == "review"
    assert partial.reasons == ["alignment: not finished, run `vocatron make`"]


def test_the_safety_limit_is_a_factor_of_the_song_length_plus_a_base() -> None:
    assert time_limit(Config(), 100.0) == 1600.0
    assert time_limit(Config(), None) is None  # nothing to scale
    tight = Config(batch=BatchSettings(time_limit_factor=1.0, time_limit_base=0.0))
    assert time_limit(tight, 50.0) == 50.0


def test_a_song_over_a_tight_limit_fails_before_the_next_stage(one_song: FakeWorld) -> None:
    tight = Config(batch=BatchSettings(time_limit_factor=1.0, time_limit_base=0.0))
    one_song.separator.during = lambda request: one_song.clock.wait(181.0)  # the song is 180 s
    song = one_song.song(MUSIC / "a.mp3", tight)
    result = make_song(song, tight, one_song.engines, Options())
    assert result.status.state == "failed"
    assert result.status.error is not None
    assert (result.status.error.stage, result.status.error.kind) == ("tempo", "time-limit")
    assert one_song.audio.requests == []
    assert one_song.acoustic.requests == []
    assert result.report is not None
    assert result.report.error == result.status.error


def test_a_song_whose_length_is_unknown_has_no_limit(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3", tags=Tags("A", "B", None))
    world.separator.during = lambda request: world.clock.wait(10**7)
    assert world.run(MUSIC / "a.mp3").state == "review"  # only the unknown duration


def test_a_file_error_in_a_stage_is_a_disk_error_with_the_reason(
    one_song: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Denied(EchoStage):
        name = "denied"
        output = "denied.json"

        @override
        def run(
            self, ctx: StageContext, settings: ProbeSettings, fingerprint: Fingerprint
        ) -> StageFile:
            raise PermissionError(13, "Permission denied", "/music/x")

    monkeypatch.setattr(batch, "STAGES", (ProbeStage(), Denied()))
    status = run_all(one_song)[0]
    assert status.error is not None
    assert (status.error.kind, status.error.message) == (
        "disk-error",
        "Permission denied: /music/x",
    )


def test_a_stop_request_leaves_the_song_running_in_the_next_stage_without_a_report(
    one_song: FakeWorld,
) -> None:
    stop = StopFlag()
    stop.request()
    song = one_song.song(MUSIC / "a.mp3")
    result = make_song(song, Config(), one_song.engines, Options(), Hooks(stop=stop))
    assert (result.status.state, result.status.current) == ("running", "probe")
    assert result.report is None
    assert one_song.store.size(WORK / "report.json") is None
    assert one_song.store.logs[WORK / "log.txt"].closed == 1


def test_a_batch_with_a_stop_request_starts_no_song(one_song: FakeWorld) -> None:
    stop = StopFlag()
    stop.request()
    results = run_batch(songs_of(one_song), Config(), one_song.engines, Options(), Hooks(stop=stop))
    assert results == []


def test_the_echo_follows_the_whole_log_file_with_the_name_of_the_song(one_song: FakeWorld) -> None:
    heard: list[str] = []
    song = one_song.song(MUSIC / "a.mp3")

    def worker(request: SeparationRequest) -> None:  # a GPU worker writes to the log itself
        one_song.store.open_log(request.log_path).write("separation worker: piece 1 of 2")

    one_song.separator.during = worker
    make_song(song, Config(), one_song.engines, Options(), Hooks(echo=heard.append))
    lines = one_song.store.log_lines(WORK / "log.txt")
    assert heard == [f"Artist - Title: {line}" for line in lines]  # all, in order, each once

    def at(end: str) -> int:
        return next(i for i, line in enumerate(lines) if line.endswith(end))

    assert at(" probe: running") == 0
    assert at(" separation: running") < at("piece 1 of 2") < at(" separation: done")
    assert not one_song.store.logs[WORK / "log.txt"].followers  # let go when the song ended


def test_a_log_that_cannot_be_written_does_not_fail_the_song(
    one_song: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: object, line: str = "") -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(MemoryLog, "write", broken)
    monkeypatch.setattr(MemoryLog, "close", broken)
    assert one_song.run(MUSIC / "a.mp3").state == "ok"


def test_a_status_that_cannot_be_written_after_the_last_stage_fails_that_stage_once(
    one_song: FakeWorld,
) -> None:
    one_song.renderer.during = lambda request: one_song.store.full.add(WORK / "status.json")
    status = run_all(one_song)[0]
    assert status.error is not None
    assert (status.state, status.error.stage, status.error.kind) == (
        "failed",
        "cdg",
        "disk-error",
    )
    assert [outcome.stage for outcome in status.stages].count("cdg") == 1
