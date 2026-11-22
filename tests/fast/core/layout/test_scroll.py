"""Stage 1: the scroll layout: stops, glides, wrapping, breaks and the way in (ADR-0033).

Invented timings on the fixed measurer (a character is half the font size wide).
"""

import math
from typing import Literal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import JsonValue

from conformance.scene_rules import check_scene
from fakes.measure import FixedMeasurer
from fakes.phrases import line
from fakes.scenes import builtin_profile, entchen_with
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.phrases import Phrase
from vocatron.core.layout.place import Times
from vocatron.core.layout.scroll import (
    LINE_GAP,
    MIN_NOTICE,
    SETTLE,
    Column,
    Part,
    Plan,
    Stop,
    View,
    path_of,
    plan_stops,
    visible_stops,
)
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    CardElement,
    CountdownElement,
    LineElement,
    ProgressElement,
    Scene,
    TimerElement,
)

FRAME = (960, 720)  # safe area 864 x 648
NO_INTRO: dict[str, JsonValue] = {"solo": 0.0, "group": 0.0}


def scrolling(**overrides: JsonValue) -> Profile:
    """The look lyric-scroll without an intro, with overrides (nested keys as in the YAML)."""
    return builtin_profile("lyric-scroll", intro=NO_INTRO, **overrides)


def scene_of(
    phrases: list[Phrase], chosen: Profile | None = None, bpm: float | None = None
) -> Scene:
    chosen = chosen or scrolling()
    built = layout(
        phrases, SongText("Titel", "Künstler", 90.0, {}, bpm=bpm), chosen, FRAME, FixedMeasurer()
    )
    check_scene(built, chosen)
    return built


def moves(row: LineElement) -> list[tuple[float, float]]:
    """The glides of a row: (start, end) of every stretch of its path that goes up."""
    return [(a.time, b.time) for a, b in zip(row.path, row.path[1:], strict=False) if a.y > b.y]


def rest_before_singing(row: LineElement) -> tuple[float, float]:
    """When the column came to rest for the row to be sung, and when it moves on."""
    sung = [(a.time, b.time) for a, b in zip(row.path, row.path[1:], strict=False)
            if a.y == b.y and a.time <= row.sing_start <= b.time]  # fmt: skip
    return sung[0]


# --------------------------------------------------------------------------- the stops


def times(*starts: float, length: float = 1.5) -> list[Times]:
    return [Times(start, start + length) for start in starts]


def plan_of(timings: list[Times], chosen: Profile | None = None) -> Plan:
    chosen = chosen or scrolling()
    return plan_stops(
        timings, chosen, None, first_show=timings[0].start - 3.0, title_end=timings[0].start - 3.0
    )


def test_the_column_comes_in_as_the_title_ends_and_glides_late_before_the_next_line() -> None:
    plan = plan_of(times(10.0, 14.0, 18.0))
    first, second, third = plan.stops
    assert (first.glide_start, first.glide_end) == (7.0, 7.4)
    # a gap of 2.5 s: the glide is as late as it can be, SETTLE before the line is sung
    assert (second.glide_start, second.glide_end) == (14.0 - SETTLE - 0.4, 14.0 - SETTLE)
    assert (third.glide_start, third.glide_end) == (18.0 - SETTLE - 0.4, 18.0 - SETTLE)
    assert plan.final == 18.0 + 1.5 + 2.0


def test_a_short_silence_starts_the_glide_during_the_end_of_the_line_before() -> None:
    plan = plan_of(times(10.0, 11.65, 13.5))  # silences of 0.15 s and 0.35 s
    second, third = plan.stops[1:]
    assert (second.glide_start, second.glide_end) == (11.25, 11.65 - SETTLE)
    assert (third.glide_start, third.glide_end) == (13.1, 13.5 - SETTLE)
    assert all(0.3 - 1e-9 <= stop.glide <= 0.4 + 1e-9 for stop in plan.stops)


def test_lines_back_to_back_glide_for_the_minimum_and_end_at_the_next_first_syllable() -> None:
    plan = plan_of(times(10.0, 11.5, 13.0))
    assert [(s.glide_start, s.glide_end) for s in plan.stops[1:]] == [(11.2, 11.5), (12.7, 13.0)]


def test_a_silence_with_room_for_the_full_glide_is_as_before() -> None:
    plan = plan_of(times(10.0, 12.5))  # 1 s of silence
    assert (plan.stops[1].glide_start, plan.stops[1].glide_end) == (12.5 - SETTLE - 0.4, 12.4)


def test_the_minimum_glide_is_the_key_of_the_profile() -> None:
    chosen = scrolling(scroll={"min_glide": 0.4})
    plan = plan_of(times(10.0, 11.5), chosen)
    assert abs(plan.stops[1].glide - 0.4) < 1e-9


def test_the_first_glide_ends_before_the_first_line_or_its_earlier_wipe_is_sung() -> None:
    for offset, end in ((0.3, 10.0), (0.0, 10.0), (-0.1, 9.9), (-0.3, 9.8)):
        chosen = scrolling(wipe={"offset": offset})
        plan = plan_stops([Times(10.0, 11.5)], chosen, None, first_show=9.8, title_end=9.8)
        first = plan.stops[0]
        assert (first.glide_start, first.glide_end) == (9.8, pytest.approx(end)), offset


def test_a_short_glide_without_min_glide_is_its_own_minimum_and_keeps_every_rule() -> None:
    chosen = scrolling(scroll={"glide": 0.2})  # below the default minimum of 0.3 s
    plan = plan_of(times(10.0, 11.5, 13.0), chosen)
    assert [(s.glide_start, s.glide_end) for s in plan.stops[1:]] == [(11.3, 11.5), (12.8, 13.0)]
    scene_of([line(10.0, 11.5), line(11.5, 13.0), line(13.0, 14.5)], chosen)  # checks the rules


def test_a_glide_never_starts_before_the_column_has_come_to_rest() -> None:
    # line 1 is sung for 0.1 s only: the glide into line 2 can start no earlier than the rest
    plan = plan_stops([Times(10.0, 11.5), Times(11.5, 11.6), Times(11.6, 13.0)], scrolling(), None,
                      7.0, 7.0)  # fmt: skip
    _, second, third = plan.stops
    assert third.glide_start >= second.glide_end - 1e-9
    assert third.glide < 0.3  # the one case where it stays shorter than the minimum
    assert third.glide_end == 11.6


def test_a_glide_before_a_shifted_wipe_still_ends_before_the_wipe() -> None:
    chosen = scrolling(wipe={"offset": -0.3})
    plan = plan_of(times(10.0, 12.0), chosen)  # the wipe starts at 11.7, 0.2 s after the line
    assert plan.stops[1].glide_end <= 12.0 - 0.3 + 1e-9
    assert plan.stops[1].glide >= 0.3 - 1e-9
    assert plan.stops[1].glide_start >= 11.5 - 0.3 - 1e-9


def test_a_glide_with_a_wipe_shifted_later_starts_at_most_the_minimum_before_the_wipe_ends() -> (
    None
):
    chosen = scrolling(wipe={"offset": 0.3})
    plan = plan_of(times(10.0, 12.0), chosen)
    stop = plan.stops[1]
    assert stop.glide_start >= 11.5 + 0.3 - 0.3 - 1e-9  # not before the last 0.3 s of the line


def test_a_wipe_shifted_later_keeps_the_glide_out_of_the_wipe() -> None:
    chosen = scrolling(wipe={"offset": 0.3})
    plan = plan_of(times(10.0, 14.0), chosen)
    assert plan.stops[1].glide_start >= 11.5 + 0.3 - 1e-9


def test_a_wipe_shifted_earlier_keeps_the_glide_out_of_the_wipe() -> None:
    chosen = scrolling(wipe={"offset": -0.3})
    plan = plan_of(times(10.0, 14.0), chosen)
    assert plan.stops[1].glide_end <= 14.0 - 0.3 + 1e-9


def test_a_long_gap_ends_a_part_after_the_hold_and_starts_the_next_like_the_song() -> None:
    plan = plan_of(times(10.0, 40.0))
    first, second = plan.parts
    assert (first.first, first.last, second.first, second.last) == (0, 0, 1, 1)
    assert first.leave == 11.5 + 2.0  # the lines go after the hold
    assert second.leave is None and first.leave is not None
    start = plan.stops[1]
    assert start.glide_start - first.leave >= MIN_NOTICE  # the break screen stands alone
    assert start.glide == pytest.approx(scrolling().scroll.glide)  # a whole glide in from below
    assert plan.countdowns[1].start == start.glide_end  # the countdown starts when it rests


def test_a_song_without_a_long_gap_is_one_part() -> None:
    plan = plan_of(times(10.0, 14.0, 18.0))
    assert plan.parts == [Part(0, 2, None)]
    assert plan.part_of(1) == plan.parts[0]


def test_a_gap_too_short_for_a_break_screen_is_no_part_edge() -> None:
    chosen = scrolling(breaks={"notice_after": 2.0, "clear_after": 2.0})
    # 2 s of silence: the hold and the shortest break screen do not fit into it
    assert len(plan_of(times(10.0, 13.5), chosen).parts) == 1
    assert len(plan_of(times(10.0, 21.0), chosen).parts) == 2  # 9.5 s do


def test_a_break_screen_needs_its_time_alone_and_a_whole_glide_in_to_the_line() -> None:
    chosen = scrolling(breaks={"notice_after": 2.0, "clear_after": 2.0})
    # the lines go at 13.5, the screen stands until 14.5, then a glide of 0.4 s ends at SETTLE
    plan = plan_of([Times(10.0, 11.5), Times(14.9, 16.0)], chosen)  # 0.1 s short of it
    assert len(plan.parts) == 1
    plan = plan_of([Times(10.0, 11.5), Times(15.1, 16.0)], chosen)
    assert len(plan.parts) == 2
    exact = scrolling(breaks={"notice_after": 3.6, "clear_after": 2.0})
    assert len(plan_of([Times(10.0, 11.5), Times(15.1, 16.0)], exact).parts) == 2  # 3.6 s: enough
    assert len(plan_of([Times(10.0, 11.5), Times(15.0, 16.0)], exact).parts) == 1  # 3.5 s: not
    leave = plan.parts[0].leave
    assert leave is not None and plan.stops[1].glide_start - leave >= MIN_NOTICE - 1e-9
    assert plan.stops[1].glide == pytest.approx(0.4)


@settings(max_examples=60, deadline=None)
@given(
    gaps=st.lists(st.sampled_from([0.5, 3.0, 8.0, 16.0, 30.0]), min_size=1, max_size=7),
    bpm=st.sampled_from([None, 90.0, 140.0]),
)
def test_every_part_starts_with_a_whole_glide_in_after_a_still_break_screen(
    gaps: list[float], bpm: float | None
) -> None:
    chosen = scrolling()
    start = 10.0
    timings: list[Times] = []
    for gap in gaps:
        timings.append(Times(start, start + 1.5))
        start += 1.5 + gap
    timings.append(Times(start, start + 1.5))
    plan = plan_stops(timings, chosen, bpm, 7.0, 7.0)
    for before, after in zip(plan.parts, plan.parts[1:], strict=False):
        assert before.leave is not None
        assert after.first == before.last + 1
        stop = plan.stops[after.first]
        # the lines go after the hold, the screen stands alone, then a whole glide in
        assert before.leave >= timings[before.last].end + chosen.clear.hold - 1e-9
        assert stop.glide_start >= before.leave + MIN_NOTICE - 1e-9
        assert stop.glide == pytest.approx(chosen.scroll.glide)
        assert stop.glide_end <= timings[after.first].start + 1e-9
        window = plan.countdowns.get(after.first)
        assert window is None or window.start >= stop.glide_end - 1e-3  # rounded
        # a gap of break_after or more with room has a part edge: the gaps are 16 s and 30 s
        assert timings[after.first].start - timings[before.last].end >= chosen.breaks.notice_after
    long = [
        i for i in range(1, len(timings))
        if timings[i].start - timings[i - 1].end >= chosen.breaks.notice_after + 5.0
    ]  # fmt: skip
    assert {part.first for part in plan.parts[1:]} >= set(long)


def test_a_countdown_starts_after_the_glide_into_its_line() -> None:
    plan = plan_of(times(10.0, 20.0))
    window = plan.countdowns[1]
    assert window.start >= plan.stops[1].glide_end - 1e-9
    assert plan.stops[1].glide_end == window.start  # the glide ends where the countdown starts
    assert 0 in plan.countdowns  # the first line too


def test_a_countdown_in_a_short_gap_waits_for_a_whole_glide_after_the_line_before() -> None:
    chosen = scrolling(countdown={"min_gap": 0.5})
    plan = plan_of([Times(10.0, 11.5), Times(12.3, 13.8)], chosen)  # 0.8 s of silence
    assert plan.countdowns[1].start == 11.5 + 0.4  # cut at the end of a full glide, not before
    assert (plan.stops[1].glide_start, plan.stops[1].glide_end) == (11.5, 11.9)


def test_no_countdown_for_a_gap_below_min_gap() -> None:
    plan = plan_of(times(10.0, 14.0))
    assert 1 not in plan.countdowns


# --------------------------------------------------------------------------- the column


def column(heights: list[float], gaps: list[float] | None = None) -> Column:
    return Column(heights, gaps or [10.0] * len(heights))


def test_the_centres_of_the_entries_follow_their_heights_and_gaps() -> None:
    found = column([40.0, 60.0, 40.0], [10.0, 20.0, 30.0])
    assert found.centres() == [20.0, 90.0, 170.0]
    assert found.steps() == [50.0, 70.0, 80.0]


def test_the_first_step_is_a_row_and_a_gap() -> None:
    assert column([40.0, 60.0], [10.0, 20.0]).steps()[0] == 50.0


def whole(found: Column) -> Part:
    return Part(0, len(found.heights) - 1, None)


def view(before: int = 2, after: int = 3) -> View:
    return View(current=300.0, top=0.0, bottom=600.0, before=before, after=after)


def test_a_line_is_in_view_from_the_stop_that_has_it_among_the_next_lines_to_the_stop_after() -> (
    None
):
    found = column([40.0] * 8, [20.0] * 8)
    centres = found.centres()
    assert visible_stops(5, found, centres, view(before=2, after=3), whole(found)) == (2, 7)
    assert visible_stops(0, found, centres, view(before=2, after=3), whole(found)) == (0, 2)
    assert visible_stops(7, found, centres, view(before=0, after=1), whole(found)) == (6, 7)


def test_a_line_outside_the_safe_area_is_not_in_view() -> None:
    found = column([200.0] * 6, [20.0] * 6)  # 220 px apart: a line fits only at its own stop
    assert visible_stops(4, found, found.centres(), view(before=2, after=4), whole(found)) == (4, 4)


def path_for(entry: int, plan: Plan, found: Column, current: View) -> list[tuple[float, float]]:
    centres = found.centres()
    run = visible_stops(entry, found, centres, current, whole(found))
    return [(k.time, k.y) for k in path_of(entry, run, plan, centres, found.steps())]


def test_a_path_comes_in_rests_glides_and_goes_out() -> None:
    stops = [Stop(i, 10.0 * i, 10.0 * i + 1.0) for i in range(4)]
    plan = Plan(stops, [Part(0, 3, None)], {}, final=40.0)
    found = column([40.0] * 4, [20.0] * 4)
    frames = path_for(1, plan, found, view(before=1, after=1))
    # in view at the stops 0, 1, 2: it comes in during the glide into stop 0, then glides twice
    # by 60 px and leaves by one more step during the glide into stop 3
    assert frames == [
        (0.0, 60.0 + 60.0), (1.0, 60.0), (10.0, 60.0), (11.0, 0.0), (20.0, 0.0), (21.0, -60.0),
        (30.0, -60.0), (31.0, -120.0),
    ]  # fmt: skip


def test_the_last_stop_stays_until_the_end() -> None:
    stops = [Stop(i, 10.0 * i, 10.0 * i + 1.0) for i in range(2)]
    plan = Plan(stops, [Part(0, 1, None)], {}, final=25.0)
    found = column([40.0] * 2, [20.0] * 2)
    frames = path_for(1, plan, found, view(before=1, after=1))
    assert frames[-1] == (25.0, 0.0)


def test_glides_back_to_back_leave_no_doubled_keyframe() -> None:
    stops = [Stop(0, 0.0, 1.0), Stop(1, 1.0, 2.0), Stop(2, 2.0, 3.0)]
    plan = Plan(stops, [Part(0, 2, None)], {}, final=9.0)
    found = column([40.0] * 3, [20.0] * 3)
    frames = path_for(1, plan, found, view(before=1, after=1))
    assert frames == [(0.0, 120.0), (1.0, 60.0), (2.0, 0.0), (3.0, -60.0), (9.0, -60.0)]


def test_a_row_is_in_view_up_to_a_thousandth_of_a_pixel_outside_the_safe_area() -> None:
    found = column([40.0, 40.0], [20.0, 20.0])  # the second row at the first stop: 340 to 380
    for bottom, shown in ((380.0, True), (379.9995, True), (379.998, False)):
        window = View(current=300.0, top=0.0, bottom=bottom, before=1, after=1)
        assert (
            visible_stops(1, found, found.centres(), window, whole(found)) == (0, 1)
        ) is shown, bottom
    for top, shown in ((220.0, True), (220.0005, True), (220.002, False)):
        window = View(current=300.0, top=top, bottom=600.0, before=1, after=1)  # the first row
        assert (
            visible_stops(0, found, found.centres(), window, whole(found)) == (0, 1)
        ) is shown, top  # at 1: 220 to 260


def test_a_jump_is_two_keyframes_at_one_time() -> None:
    stops = [Stop(0, 0.0, 1.0), Stop(1, 5.0, 5.0), Stop(2, 9.0, 9.4)]
    plan = Plan(stops, [Part(0, 2, None)], {}, final=12.0)
    found = column([40.0] * 3, [20.0] * 3)
    frames = path_for(1, plan, found, view(before=1, after=1))
    assert (5.0, 0.0 + 60.0) in frames and (5.0, 0.0) in frames


# --------------------------------------------------------------------------- the scene


def test_a_scene_has_the_measures_of_its_column_and_no_slots() -> None:
    scene = scene_of([line(10.0, 12.0), line(13.0, 15.0)])
    assert scene.scroll is not None
    assert scene.slots == [] and scene.preview_row is None
    assert scene.scroll.current == round(scene.safe.y + 0.42 * scene.safe.h, 3)
    assert (scene.scroll.before, scene.scroll.after, scene.scroll.glide) == (2, 3, 0.4)
    assert scene.look.sung_dim == 0.5


def test_a_scene_in_another_mode_has_no_column_and_no_path() -> None:
    scene = entchen_with(builtin_profile("two-line-turns"))
    assert scene.scroll is None and scene.look.sung_dim == 0.0
    assert all(x.path == [] for x in scene.lines())


def test_a_glide_ends_before_the_first_syllable_of_its_line() -> None:
    scene = scene_of([line(10.0, 12.0), line(14.0, 16.0), line(18.0, 20.0)])
    for row in scene.lines()[1:]:
        low, high = rest_before_singing(row)
        assert low <= row.sing_start - SETTLE + 1e-6
        assert high >= row.sing_end


def test_the_line_being_sung_stands_still_at_the_current_height() -> None:
    scene = scene_of([line(10.0, 12.0), line(13.0, 15.0), line(16.0, 18.0)])
    assert scene.scroll is not None
    for row in scene.lines():
        assert (
            row.box.y + row.box.h / 2 == scene.scroll.current
            or abs(row.box.y + row.box.h / 2 - scene.scroll.current) < 0.01
        )
        for time in (row.sing_start, (row.sing_start + row.sing_end) / 2, row.sing_end - 0.01):
            assert row.y_at(time) == row.text_y


def test_lines_before_and_after_are_where_the_column_puts_them() -> None:
    scene = scene_of([line(10.0 + 3.0 * i, 12.0 + 3.0 * i) for i in range(5)])
    rows = scene.lines()
    moment = rows[2].sing_start
    shown = [(i, x.box_at(moment)) for i, x in enumerate(rows) if x.visible(moment)]
    assert [i for i, _ in shown] == [0, 1, 2, 3, 4]
    tops = [box.y for _, box in shown]
    assert tops == sorted(tops)
    middle = rows[2].box_at(moment)
    assert [i for i, box in shown if box.y < middle.y] == [0, 1]
    assert [i for i, box in shown if box.y > middle.y] == [3, 4]


def test_only_the_lines_that_fit_the_window_are_in_view() -> None:
    chosen = scrolling(scroll={"before": 1, "after": 2})
    scene = scene_of([line(10.0 + 3.0 * i, 12.0 + 3.0 * i) for i in range(8)], chosen)
    rows = scene.lines()
    for index, row in enumerate(rows):
        shown = [i for i, x in enumerate(rows) if x.visible(row.sing_start)]
        assert shown == [i for i in range(index - 1, index + 3) if 0 <= i < len(rows)]


def test_a_long_line_wraps_onto_two_rows_that_move_together() -> None:
    long_text = "eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf"
    scene = scene_of([line(10.0, 14.0, long_text), line(16.0, 18.0), line(19.0, 21.0)])
    first, second = scene.lines()[:2]
    assert (first.row, second.row) == (0, 1)
    assert (first.start, first.end) == (second.start, second.end)
    gap = second.text_y - first.text_y
    assert gap > first.size
    for a, b in zip(first.path, second.path, strict=True):
        assert (a.time, round(b.y - a.y, 3)) == (b.time, round(gap, 3))
    assert scene.scroll is not None
    block = (first.box.y + second.box.bottom) / 2
    assert abs(block - scene.scroll.current) < 0.01  # the block is centred on the current height


def test_the_rows_of_a_line_never_overlap_in_motion() -> None:
    long_text = "eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf"
    phrases = [
        line(10.0 + 5.0 * i, 13.0 + 5.0 * i, long_text if i % 2 else "la la") for i in range(6)
    ]
    scene_of(phrases)  # check_scene runs rule 21 over every keyframe and middle of a glide


def test_the_column_glides_in_from_below_when_the_title_ends() -> None:
    scene = scene_of([line(10.0, 12.0), line(13.0, 15.0)])
    titles = [e for e in scene.elements if isinstance(e, CardElement) and e.kind == "title"]
    (title,) = titles
    first = scene.lines()[0]
    assert first.start == title.end == 7.0
    below, rest = first.path[0], first.path[1]
    assert below.y > rest.y and rest.time == below.time + 0.4
    assert first.y_at(first.start) > first.text_y  # it starts below its place


def test_the_whole_column_comes_in_together() -> None:
    scene = scene_of([line(10.0 + 3.0 * i, 12.0 + 3.0 * i) for i in range(6)])
    starts = {x.start for x in scene.lines()[:4]}  # the current line and the three below
    assert starts == {7.0}


BREAK_LINES = [
    line(10.0, 12.0),
    line(13.0, 15.0),
    line(45.0, 47.0),
    line(48.0, 50.0),
    line(51.0, 53.0),
]
FORMS: list[Literal["notice", "progress", "timer"]] = ["notice", "progress", "timer"]


def break_times() -> list[Times]:
    return [Times(10, 12), Times(13, 15), Times(45, 47), Times(48, 50), Times(51, 53)]


def notice_of(scene: Scene) -> CardElement:
    (notice,) = [e for e in scene.elements if isinstance(e, CardElement) and e.kind == "break"]
    return notice


def lines_in(scene: Scene, first: int, last: int) -> list[LineElement]:
    return scene.lines()[first : last + 1]


def test_the_break_screen_stands_alone_still_and_centred() -> None:
    scene, plan = scene_of(BREAK_LINES), plan_of(break_times())
    notice = notice_of(scene)
    leave, restart = plan.parts[0].leave, plan.stops[2].glide_start
    assert (notice.start, notice.end) == (leave, restart)
    middle = notice.box.y + notice.box.h / 2
    assert abs(middle - (scene.safe.y + scene.safe.h / 2)) < 1.0
    for row in scene.lines():  # nothing of the column is on screen during the screen
        assert row.end <= notice.start + 1e-6 or row.start >= notice.end - 1e-6


def test_the_lines_before_a_break_go_after_the_hold_and_stay_until_then() -> None:
    scene, plan = scene_of(BREAK_LINES), plan_of(break_times())
    assert plan.parts[0].leave == 15.0 + scrolling().clear.hold
    first = lines_in(scene, 0, 1)
    assert {x.end for x in first} == {15.0 + scrolling().clear.hold}
    for row in first:  # at rest from the last glide to the end: no glide out into the break
        assert row.path[-1].y == row.path[-2].y and row.path[-1].time == row.end
    assert plan.parts[0].leave == first[1].end


def test_the_lines_fade_out_over_the_fade_of_the_end_of_the_song() -> None:
    faded = scene_of(BREAK_LINES, scrolling(ending={"fade": 0.5}))
    assert [x.exit for x in lines_in(faded, 0, 1)] == [0.5, 0.5]
    assert [x.exit for x in lines_in(faded, 2, 4)] == [0.0, 0.0, 0.0]  # the song goes at its end
    assert [x.exit for x in scene_of(BREAK_LINES, scrolling(ending={"fade": 0.0})).lines()] == [
        0.0
    ] * 5


def test_the_fade_never_reaches_into_the_singing() -> None:
    short = scrolling(clear={"hold": 0.2}, ending={"fade": 0.5, "start_after": 0.2})
    scene = scene_of(BREAK_LINES, short)
    last = lines_in(scene, 0, 1)[1]
    assert 0 < last.exit <= last.end - last.sing_end + 1e-6


def test_the_column_starts_again_after_the_break_screen_as_after_the_title() -> None:
    scene, plan = scene_of(BREAK_LINES), plan_of(break_times())
    notice = notice_of(scene)
    for row in lines_in(scene, 2, 4):
        assert row.start >= notice.end - 1e-6  # nothing before the screen ends
    first = scene.lines()[2]
    below, rest = first.path[0], first.path[1]
    assert below.time == notice.end == first.start
    assert below.y > rest.y and rest.time == pytest.approx(below.time + 0.4)  # glides in from below
    assert first.y_at(first.sing_start) == first.text_y
    assert plan.stops[2].glide_start == pytest.approx(notice.end, abs=0.5)


def test_the_next_part_glides_in_by_its_own_height_whatever_stood_before_the_break() -> None:
    wrapped = [*BREAK_LINES]
    wrapped[1] = line(13.0, 15.0, " ".join(["la"] * 40))  # rows of it before the break
    scene, plan = scene_of(wrapped), plan_of(break_times())
    first = scene.lines()[0]
    assert len(scene.lines()) > len(wrapped)  # the line before the break has several rows
    assert {0, 2} <= set(plan.countdowns)  # both start a part with a countdown above them
    (restart,) = [x for x in scene.lines() if x.sing_start == 45.0]  # the line after the break
    assert restart.path[0].y - restart.path[1].y == pytest.approx(
        first.path[0].y - first.path[1].y
    )  # like the first line of the song, not by the distance from the wrapped line


def test_the_whole_next_part_comes_in_together() -> None:
    scene = scene_of(BREAK_LINES)
    notice = notice_of(scene)
    assert {x.start for x in lines_in(scene, 2, 4)} == {notice.end}


def test_the_stops_inside_a_part_are_as_without_a_break() -> None:
    plan = plan_of(break_times())
    assert [s.line for s in plan.stops] == [0, 1, 2, 3, 4]
    assert [(s.glide_start, s.glide_end) for s in plan.stops[3:]] == [(47.5, 47.9), (50.5, 50.9)]


def test_a_gap_between_clear_after_and_notice_after_glides_on() -> None:
    scene = scene_of([line(10.0, 12.0), line(20.0, 22.0), line(23.0, 25.0)])  # 8 s of silence
    assert not [e for e in scene.elements if isinstance(e, CardElement) and e.kind == "break"]
    assert len(plan_of(times(10.0, 20.0)).parts) == 1
    first, second = scene.lines()[:2]
    assert first.end > second.start  # the first line is still on screen when the next is sung


def test_the_countdown_stands_still_in_the_next_part_after_the_break_screen() -> None:
    scene = scene_of(BREAK_LINES, bpm=100.0)
    notice, after = notice_of(scene), scene.lines()[2]
    (countdown,) = [e for e in scene.elements if isinstance(e, CountdownElement) and e.end > 44.0]
    assert countdown.start >= notice.end + 0.4 - 1e-6  # when the column rests
    for moment in (countdown.start, (countdown.start + countdown.end) / 2, countdown.end - 0.01):
        assert countdown.box.bottom <= after.box_at(moment).y
        assert after.y_at(moment) == after.text_y


@pytest.mark.parametrize("form", FORMS)
def test_the_bar_and_the_timer_stand_still_with_the_screen(
    form: Literal["notice", "progress", "timer"],
) -> None:
    chosen = scrolling(breaks={"form": form})
    scene = scene_of(BREAK_LINES, chosen)
    notice = notice_of(scene)
    parts = [e for e in scene.elements if isinstance(e, ProgressElement | TimerElement)]
    assert len(parts) == (form != "notice")
    for part in parts:
        assert (part.start, part.end) == (notice.start, notice.end)
        assert part.box.inside(scene.safe) and part.box.y >= notice.box.bottom - 1e-6
        if isinstance(part, TimerElement):
            assert part.total == math.ceil(part.end - part.start - 1e-6)  # counts to the glide in
            assert part.seconds_left(part.end - 0.01) == 1


@pytest.mark.parametrize("form", FORMS)
@pytest.mark.parametrize("before", [0, 1, 2])
@pytest.mark.parametrize("after", [1, 2, 3])
def test_the_break_screen_follows_the_rules_for_every_form_and_window(
    form: Literal["notice", "progress", "timer"], before: int, after: int
) -> None:
    chosen = scrolling(breaks={"form": form}, scroll={"before": before, "after": after})
    scene = scene_of(BREAK_LINES, chosen, bpm=100.0)  # check_scene runs every rule
    assert notice_of(scene).start < notice_of(scene).end


def test_the_break_screen_with_the_wordmark_stands_still_too() -> None:
    chosen = scrolling(title={"form": "wordmark"})
    notice = notice_of(scene_of(BREAK_LINES, chosen))
    assert notice.symbol is not None


def test_a_song_without_a_break_has_no_break_screen_and_its_lines_glide_as_before() -> None:
    scene = scene_of([line(10.0, 12.0), line(14.0, 16.0), line(18.0, 20.0)])
    assert not [e for e in scene.elements if isinstance(e, CardElement) and e.kind == "break"]
    first = scene.lines()[0]
    assert [(k.time, k.y) for k in first.path][:3] == [
        (7.0, first.path[0].y), (7.4, first.text_y), (13.5, first.text_y),
    ]  # fmt: skip


def test_the_countdown_stands_just_above_the_line_and_after_the_glide() -> None:
    scene = scene_of([line(10.0, 12.0), line(30.0, 32.0)], bpm=100.0)
    second = scene.lines()[1]
    countdowns = [e for e in scene.elements if isinstance(e, CountdownElement)]
    last = max(countdowns, key=lambda c: c.start)
    assert last.box.bottom <= second.box.y
    assert second.box.y - last.box.bottom < second.size
    low, _ = rest_before_singing(second)
    assert last.start >= low - 1e-9


def test_a_line_without_a_countdown_has_no_room_for_one_above_it() -> None:
    # the gap asks for a countdown (min_gap 0.5 s), but a beat does not fit after the glide
    chosen = scrolling(countdown={"min_gap": 0.5})
    scene = scene_of([line(10.0, 12.0), line(12.6, 14.6)], chosen, bpm=60.0)
    first, second = scene.lines()
    countdowns = [e for e in scene.elements if isinstance(e, CountdownElement)]
    assert [c.end <= first.sing_start for c in countdowns] == [True]  # only the first counts in
    above = first.text_y - first.y_at(second.sing_start)  # how far the column moved for it
    assert abs(above - (first.box.h + LINE_GAP * first.size)) <= 0.01


def test_a_line_that_does_not_fit_the_safe_area_at_the_current_height_is_reported() -> None:
    chosen = scrolling(scroll={"current": 0.2}, font={"size": 0.4, "min_size": 0.2})
    built = layout(
        [line(10.0, 12.0)], SongText("T", None, 30.0, {}), chosen, FRAME, FixedMeasurer()
    )
    assert [s.kind for s in built.shortfalls if s.kind == "block"] == ["block"]


def test_a_song_without_lines_still_has_its_column_measures() -> None:
    chosen = scrolling()
    built = layout([], SongText("T", None, 30.0, {}), chosen, FRAME, FixedMeasurer())
    assert built.scroll is not None and built.slots == []


def test_the_sample_song_is_clean_in_every_form_of_break() -> None:
    for form in ("notice", "progress", "timer"):
        chosen = scrolling(breaks={"form": form})
        check_scene(entchen_with(chosen), chosen)


def test_a_wipe_shifted_either_way_keeps_every_rule() -> None:
    for offset in (-0.4, 0.4):
        chosen = scrolling(wipe={"offset": offset})
        check_scene(entchen_with(chosen), chosen)


@settings(max_examples=80, deadline=None)
@given(
    gaps=st.lists(st.sampled_from([0.0, 0.1, 0.5, 1.0, 3.0, 6.0, 20.0]), min_size=1, max_size=8),
    glide=st.sampled_from([0.2, 0.4, 1.0]),
    minimum=st.sampled_from([0.1, 0.3, 1.0]),
    lengths=st.sampled_from([0.05, 0.2, 1.0]),
)
def test_every_glide_is_long_enough_and_only_the_end_of_a_line_moves(
    gaps: list[float], glide: float, minimum: float, lengths: float
) -> None:
    minimum = min(minimum, glide)
    chosen = scrolling(scroll={"glide": glide, "min_glide": minimum})
    start = 10.0
    timings: list[Times] = []
    for gap in gaps:
        timings.append(Times(start, start + lengths))
        start += lengths + gap
    plan = plan_stops(timings, chosen, None, 7.0, 7.0)
    previous_end = 0.0
    for stop in plan.stops:
        assert stop.glide_start >= previous_end - 1e-9
        assert 0 <= stop.glide <= glide + 1e-9
        if stop.line:
            # as long as the minimum, or as long as the column rested and the line before was sung
            floor = max(previous_end, timings[stop.line - 1].start)
            assert stop.glide >= min(minimum, stop.glide_end - floor) - 1e-9
            # a line moves only during its last min_glide seconds
            assert stop.glide_start >= timings[stop.line - 1].end - minimum - 1e-9
            assert stop.glide_end <= timings[stop.line].start + 1e-9
        previous_end = stop.glide_end
    assert plan.final >= timings[-1].end


def test_the_gap_between_entries_is_a_share_of_the_font_size() -> None:
    assert 0 < LINE_GAP < 1


def test_the_column_goes_when_the_end_screen_starts() -> None:
    times = [Times(10.0, 12.0), Times(13.0, 15.0)]
    for end_screen, expected in ((True, 16.0), (False, 19.0)):
        chosen = scrolling(
            clear={"hold": 4.0}, ending={"start_after": 1.0, "end_screen": end_screen}
        )
        assert plan_stops(times, chosen, None, 7.5, 7.5).final == pytest.approx(expected)
