"""Stage 1: the estimate of the time left, the learnt speeds, and the formats of times."""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.ffmpeg_cmd import parse_progress as parse_ffmpeg_progress
from vocatron.core.ffmpeg_cmd import with_progress
from vocatron.core.progress import (
    DEFAULT_LENGTH,
    DEFAULT_SPEEDS,
    STALE_AFTER,
    WINDOW,
    ProgressFile,
    Timings,
    expected,
    format_duration,
    format_length,
    is_fresh,
    learn,
    percent,
    progress_text,
    song_left,
    speed_of,
)
from vocatron.core.worker import effective_limit, parse_progress, progress_line

STAGES = ("probe", "lyrics", "separation", "alignment", "syllables", "layout", "render")


@given(st.integers(min_value=0, max_value=10**6), st.integers(min_value=1, max_value=10**6))
def test_a_progress_line_is_read_back_as_the_fraction_it_says(done: int, total: int) -> None:
    fraction = parse_progress(progress_line(done, total))
    assert fraction == min(done / total, 1.0)


@pytest.mark.parametrize(
    "line",
    [
        "",
        "loading model",
        "progress",
        "progress 1",
        "progress 1 2 3",
        "progress a b",
        "progress 0 0",
    ],
)
def test_any_other_line_is_not_progress(line: str) -> None:
    assert parse_progress(line) is None


def test_ffmpeg_reports_the_written_time_and_n_a_before_the_first_frame() -> None:
    assert parse_ffmpeg_progress("out_time_us=30000000", 120.0) == 0.25
    assert parse_ffmpeg_progress("out_time_us=999000000", 120.0) == 1.0  # never above one
    for line in ("out_time_us=N/A", "frame=12", "progress=continue", ""):
        assert parse_ffmpeg_progress(line, 120.0) is None
    assert parse_ffmpeg_progress("out_time_us=1000", 0.0) is None  # no length to compare with


def test_ffmpeg_gets_the_progress_option_right_after_its_name() -> None:
    assert with_progress(("ffmpeg", "-y", "out.mp4")) == (
        "ffmpeg",
        "-progress",
        "pipe:1",
        "-nostats",
        "-y",
        "out.mp4",
    )


def test_the_song_limit_wins_only_when_it_is_shorter() -> None:
    assert effective_limit(100.0, None) == (100.0, False)
    assert effective_limit(100.0, 400.0) == (100.0, False)
    assert effective_limit(100.0, 40.0) == (40.0, True)
    assert effective_limit(100.0, -5.0) == (0.0, True)


def test_a_stage_without_a_learnt_speed_takes_its_default() -> None:
    timings = Timings()
    assert speed_of(timings, "separation") == DEFAULT_SPEEDS["separation"]
    assert speed_of(timings, "no-such-stage") == 0.0
    assert expected(STAGES, None, timings)["separation"] == pytest.approx(
        DEFAULT_SPEEDS["separation"] * DEFAULT_LENGTH
    )


def test_a_learnt_speed_is_per_device_and_the_last_device_is_assumed() -> None:
    timings = learn(Timings(), "separation", "cuda", seconds=90.0, length=100.0)
    assert speed_of(timings, "separation") == pytest.approx(0.9)
    timings = learn(timings, "separation", "cpu", seconds=2000.0, length=100.0)
    assert speed_of(timings, "separation", "cuda") == pytest.approx(0.9)
    assert speed_of(timings, "separation", "cpu") == pytest.approx(20.0)
    assert speed_of(timings, "separation") == pytest.approx(20.0)  # the last one ran on the CPU


def test_learning_is_a_running_average_of_the_latest_runs() -> None:
    timings = Timings()
    for seconds in (50.0, 100.0, 150.0):
        timings = learn(timings, "alignment", "cuda", seconds, length=100.0)
    assert speed_of(timings, "alignment") == pytest.approx(1.0)
    assert timings.speeds["alignment:cuda"].runs == 3


@given(st.lists(st.floats(min_value=0.01, max_value=100.0), min_size=1, max_size=40))
def test_a_learnt_speed_stays_between_the_extremes_and_remembers_a_window(
    observed: list[float],
) -> None:
    timings = Timings()
    for speed in observed:
        timings = learn(timings, "render", "cpu", speed * 100.0, length=100.0)
    learnt = timings.speeds["render:cpu"]
    assert min(observed) - 1e-6 <= learnt.speed <= max(observed) + 1e-6
    assert learnt.runs == min(len(observed), WINDOW)


def test_a_run_with_no_length_or_no_time_teaches_nothing() -> None:
    assert learn(Timings(), "render", "cpu", 10.0, 0.0) == Timings()
    assert learn(Timings(), "render", "cpu", 0.0, 100.0) == Timings()


def test_the_time_left_of_a_song_counts_the_rest_of_the_current_stage_by_its_progress() -> None:
    plan = {"separation": 100.0, "alignment": 20.0, "render": 40.0}
    assert song_left(plan, [], None, 0.0) == 160.0
    assert song_left(plan, ["separation"], "alignment", 0.5) == 10.0 + 40.0
    assert song_left(plan, ["separation", "alignment"], "render", 1.0) == 0.0
    assert song_left(plan, ["separation"], "render", 7.0) == 20.0  # a fraction is clamped
    assert song_left({}, [], None, 0.0) == 0.0


def test_a_stage_that_will_be_skipped_is_not_in_the_plan_and_counts_zero() -> None:
    timings = Timings()
    only_render = expected(("render",), 100.0, timings)
    assert sum(only_render.values()) == pytest.approx(DEFAULT_SPEEDS["render"] * 100.0)


def test_the_percentage_goes_by_time_and_by_songs_when_nothing_is_planned() -> None:
    assert percent(left=75.0, total=100.0, finished=0, songs=4) == 25
    assert percent(left=0.0, total=100.0, finished=3, songs=4) == 100
    assert percent(left=150.0, total=100.0, finished=0, songs=4) == 0  # an estimate that was low
    assert percent(left=0.0, total=0.0, finished=1, songs=4) == 25  # everything skipped
    assert percent(left=0.0, total=0.0, finished=0, songs=0) == 100


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (None, "?"),
        (0.4, "0s"),
        (45, "45s"),
        (125, "2m 05s"),
        (3599, "59m 59s"),
        (3720, "1h 02m"),
        (-3, "0s"),
    ],
)
def test_durations_are_short_for_people(seconds: float | None, text: str) -> None:
    assert format_duration(seconds) == text


def test_lengths_are_minutes_and_seconds() -> None:
    assert [format_length(s) for s in (None, 0, 59.6, 185)] == ["-", "0:00", "1:00", "3:05"]


def test_the_progress_text_names_stage_percentage_and_time_left() -> None:
    assert progress_text("separation", 0.414, 200.0) == "separation 41%, about 3m 20s left"
    assert progress_text("render", 0.0, None) == "render 0%, about ? left"


def test_a_progress_file_is_fresh_for_two_minutes() -> None:
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    def at(delta: float) -> ProgressFile:
        written = (now - timedelta(seconds=delta)).isoformat()
        return ProgressFile(stage="render", fraction=0.5, left=1.0, updated=written)

    assert is_fresh(at(1), now)
    assert not is_fresh(at(STALE_AFTER + 1), now)
    assert not is_fresh(at(STALE_AFTER), now)
    assert not is_fresh(ProgressFile(stage="x", fraction=0, updated="yesterday"), now)


def test_short_songs_and_short_totals_still_count() -> None:
    taught = learn(Timings(), "render", "cpu", 0.25, 0.5)
    assert speed_of(taught, "render", "cpu") == 0.5
    assert percent(0.25, 0.5, 0, 1) == 50
    assert percent(-1.0, 10.0, 0, 1) == 100  # an estimate that ran over is done, not more
    assert parse_ffmpeg_progress("out_time_us=250000", 0.5) == 0.5


def test_a_song_limit_as_long_as_the_own_limit_leaves_the_own_one() -> None:
    assert effective_limit(10.0, 10.0) == (10.0, False)
