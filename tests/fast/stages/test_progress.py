"""Stage 1: the plan of a batch, the tracker behind the live display, and ``progress.json``."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from fakes.lyrics import HAENSCHEN
from fakes.songs import FakeWorld
from vocatron.core.progress import DEFAULT_SPEEDS, ProgressFile, Timings
from vocatron.core.report import SummaryRow
from vocatron.core.song import Tags
from vocatron.core.status import StageOutcome
from vocatron.stages.batch import Hooks, Options, plan_song, run_batch
from vocatron.stages.config import Config
from vocatron.stages.progress import (
    PROGRESS_FILE,
    SongPlan,
    Tracker,
    View,
    load_timings,
)
from vocatron.stages.songs import discover
from vocatron.stages.stage import Song

MUSIC = Path("/music")
CLONE = Path("/clone")
TIMINGS = CLONE / ".cache" / "timings.json"
ALL = (
    "probe", "lyrics", "separation", "tempo", "alignment", "syllables", "layout", "render", "cdg",
)  # fmt: skip


class Recording:
    """A display that keeps what it was shown."""

    def __init__(self) -> None:
        self.views: list[View] = []
        self.rows: list[SummaryRow] = []
        self.stages: list[str] = []
        self.started: list[str] = []
        self.closed = 0

    def song_started(self, index: int, total: int, name: str) -> None:
        self.started.append(f"{index}/{total} {name}")

    def update(self, view: View) -> None:
        self.views.append(view)

    def stage_done(
        self, song: str, stage: str, outcome: StageOutcome, seconds: float, view: View
    ) -> None:
        self.stages.append(f"{song}: {stage} {outcome.action}")

    def song_done(self, row: SummaryRow, names: Sequence[str]) -> None:
        self.rows.append(row)

    def close(self) -> None:
        self.closed += 1


def songs(world: FakeWorld, *lengths: float) -> list[Song]:
    for number, length in enumerate(lengths):
        world.add_song(MUSIC / f"s{number}.mp3", tags=Tags("A", f"T{number}", length))
    return world_songs(world)


def world_songs(world: FakeWorld) -> list[Song]:
    return discover(MUSIC, Config(), world.engines)


def test_a_new_song_plans_every_stage_and_a_finished_one_none(world: FakeWorld) -> None:
    (song,) = songs(world, 100.0)
    config = Config()
    assert plan_song(song, config, world.engines, Options()).stages == ALL
    run_batch([song], config, world.engines, Options())
    assert plan_song(song, config, world.engines, Options()).stages == ()
    assert plan_song(song, config, world.engines, Options(force=True)).stages == ALL


def test_a_changed_lyrics_file_plans_only_the_stages_that_depend_on_it(world: FakeWorld) -> None:
    (song,) = songs(world, 100.0)
    run_batch([song], Config(), world.engines, Options())
    world.store.add(MUSIC / "s0.txt", HAENSCHEN.encode())
    planned = plan_song(song, Config(), world.engines, Options()).stages
    assert planned == ("lyrics", "alignment", "syllables", "layout", "render", "cdg")


def test_a_partial_run_plans_only_its_own_stages(world: FakeWorld) -> None:
    (song,) = songs(world, 100.0)
    assert plan_song(song, Config(), world.engines, Options(until="lyrics")).stages == (
        "probe",
        "lyrics",
    )
    only = Options(only=("probe", "layout"))
    assert plan_song(song, Config(), world.engines, only).stages == ("probe", "layout")


def test_files_that_cannot_be_read_plan_the_whole_song(
    world: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    (song,) = songs(world, 100.0)

    def unreadable(path: Path) -> str | None:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(world.store, "sha256", unreadable)
    assert plan_song(song, Config(), world.engines, Options()).stages == ALL


def test_the_length_of_the_song_is_part_of_the_plan(world: FakeWorld) -> None:
    (song,) = songs(world, 123.0)
    assert plan_song(song, Config(), world.engines, Options()).length == 123.0


def run(world: FakeWorld, tracker: Tracker, found: list[Song], *, force: bool = False) -> None:
    run_batch(found, Config(), world.engines, Options(force=force), Hooks(tracker))


def test_the_estimate_starts_from_the_defaults_and_ends_at_zero(world: FakeWorld) -> None:
    found = songs(world, 100.0, 200.0)
    display = Recording()
    tracker = Tracker(world.engines, display)
    run(world, tracker, found)
    first, last = display.views[0], display.views[-1]
    work = sum(DEFAULT_SPEEDS[stage] for stage in ALL)
    assert first.left == pytest.approx(work * 300.0)
    assert (first.total, first.percent) == (2, 0)
    assert (last.left, last.percent, last.finished) == (0.0, 100, 2)
    lefts = [view.left for view in display.views]
    assert lefts == sorted(lefts, reverse=True)  # it only goes down: nothing was slower than said
    assert display.started == ["1/2 A - T0", "2/2 A - T1"]
    assert display.closed == 0  # the command closes the display, not the batch


def test_the_progress_of_a_stage_shortens_the_time_left(world: FakeWorld) -> None:
    found = songs(world, 100.0)
    display = Recording()
    tracker = Tracker(world.engines, display)
    world.separator.during = lambda request: None
    run(world, tracker, found)
    in_separation = [view for view in display.views if view.stage == "separation"]
    halfway = next(view for view in in_separation if view.fraction == 0.5)
    start = next(view for view in in_separation if view.fraction == 0.0)
    assert start.song_left - halfway.song_left == pytest.approx(DEFAULT_SPEEDS["separation"] * 50.0)


def test_stages_that_are_skipped_count_zero(world: FakeWorld) -> None:
    found = songs(world, 100.0)
    run(world, Tracker(world.engines, Recording()), found)
    display = Recording()
    run(world, Tracker(world.engines, display), found)
    assert all(view.left == 0.0 for view in display.views)
    assert display.views[0].percent == 0  # nothing to do: by songs, none finished yet
    assert display.views[-1].percent == 100


def test_what_a_stage_took_is_learnt_and_used_for_the_next_estimate(world: FakeWorld) -> None:
    found = songs(world, 100.0)
    world.separator.during = lambda request: world.clock.wait(20.0)  # 0.2 per second of audio
    run(world, Tracker(world.engines, Recording(), TIMINGS), found, force=True)
    learnt = load_timings(world.store, TIMINGS)
    assert learnt.speeds["separation:cpu"].speed == pytest.approx(0.2)
    display = Recording()
    tracker = Tracker(world.engines, display, TIMINGS)
    tracker.batch_started([SongPlan(found[0], 100.0, ("separation",))])
    tracker.song_started(0, found[0])
    assert display.views[-1].left == pytest.approx(20.0)  # not the default 90


def test_a_skipped_stage_teaches_nothing(world: FakeWorld) -> None:
    found = songs(world, 100.0)
    run(world, Tracker(world.engines, Recording(), TIMINGS), found)
    before = world.store.read_text(TIMINGS)
    run(world, Tracker(world.engines, Recording(), TIMINGS), found)
    assert world.store.read_text(TIMINGS) == before


def test_an_unreadable_timings_file_means_the_defaults(world: FakeWorld) -> None:
    world.store.add(TIMINGS, b"{not json")
    assert load_timings(world.store, TIMINGS) == Timings()
    assert load_timings(world.store, CLONE / "nothing.json") == Timings()


def test_the_timings_that_cannot_be_written_are_a_missed_lesson_not_an_error(
    world: FakeWorld,
) -> None:
    found = songs(world, 100.0)
    world.store.full.add(CLONE)
    display = Recording()
    run(world, Tracker(world.engines, display, TIMINGS), found)
    assert display.rows[0].state == "ok"


def test_progress_json_is_written_at_most_every_two_seconds_and_removed_at_the_end(
    world: FakeWorld,
) -> None:
    (song,) = songs(world, 100.0)
    path = song.work_dir / PROGRESS_FILE
    seen: list[ProgressFile] = []

    def look(request: object) -> None:
        text = world.store.read_text(path)
        assert text is not None
        seen.append(ProgressFile.model_validate_json(text))

    world.separator.during = look
    run(world, Tracker(world.engines, Recording()), [song])
    assert seen[0].stage == "separation"
    assert seen[0].fraction == 0.0  # 0.5 came less than two seconds after the start: not written
    assert world.store.size(path) is None
    writes = [p for p in world.store.writes if p.name == PROGRESS_FILE]
    assert 1 <= len(writes) <= len(ALL)  # once per stage start, and no more


def test_a_progress_file_that_cannot_be_written_does_not_stop_the_song(world: FakeWorld) -> None:
    (song,) = songs(world, 100.0)
    world.store.full.add(song.work_dir / PROGRESS_FILE)
    display = Recording()
    run(world, Tracker(world.engines, display), [song])
    assert display.rows[0].state == "ok"


def test_the_stage_lines_and_rows_come_with_the_batch(world: FakeWorld) -> None:
    found = songs(world, 100.0)
    display = Recording()
    run(world, Tracker(world.engines, display), found)
    assert display.stages[0] == "A - T0: probe ran"
    assert display.stages[-1] == "A - T0: cdg ran"
    assert [row.name for row in display.rows] == ["A - T0"]


def test_a_stopped_song_has_a_row_from_its_status_and_no_progress_file(world: FakeWorld) -> None:
    found = songs(world, 100.0, 100.0)
    stop = Hooks()
    display = Recording()
    world.separator.during = lambda request: stop.stop.request()
    run_batch(
        found, Config(), world.engines, Options(), Hooks(Tracker(world.engines, display), stop.stop)
    )
    assert [row.state for row in display.rows] == ["interrupted"]
    assert world.store.size(found[0].work_dir / PROGRESS_FILE) is None
