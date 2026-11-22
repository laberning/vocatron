"""Stage 1: the scene rules of the scroll mode (rule 21) find a broken scene (ADR-0019)."""

import re
from typing import Any

import pytest

from fakes.measure import FixedMeasurer
from fakes.phrases import line as sung_line
from fakes.rule_breaks import (
    SMALL,
    P,
    edit,
    form_scene,
    hits,
    messages,
    moved_path,
    shifted,
    without,
)
from fakes.scenes import (
    builtin_profile,
    entchen_scene,
    entchen_with,
)
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.rules_base import EPS, RuleBroken
from vocatron.core.layout.rules_cards import _rest_start
from vocatron.core.layout.rules_scroll import _moments, _rule_21_parts, _rule_21_together
from vocatron.core.layout.rules_showing import _scrolls_out
from vocatron.core.layout.scroll import MIN_NOTICE, SETTLE
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    CardElement,
    CountdownElement,
    Keyframe,
    Scene,
    Shortfall,
)
from vocatron.core.tempo import MAX_COUNTDOWN

SCROLL_PROFILE = builtin_profile("lyric-scroll")


TWO_ROWS = builtin_profile("lyric-scroll", line_rows=2)


def scroll_scene(chosen: Profile = SCROLL_PROFILE) -> Scene:
    return entchen_with(chosen)


LONG_TEXT = "eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf"


def two_row_scene() -> Scene:
    """A song whose first line wraps onto two rows (the fixed measurer, 960 by 720)."""
    phrases = [sung_line(10.0, 14.0, LONG_TEXT), sung_line(16.0, 18.0), sung_line(19.0, 21.0)]
    return layout(phrases, SongText("T", "A", 60.0, {}), TWO_ROWS, (960, 720), FixedMeasurer())


def with_path(scene: Scene, index: int, path: list[Keyframe], **update: Any) -> Scene:
    return edit(scene, "line", index, path=path, **update)


def test_the_unbroken_scroll_scenes_are_clean() -> None:
    assert scene_findings(scroll_scene(), SCROLL_PROFILE) == []
    assert scene_findings(two_row_scene(), TWO_ROWS) == []


def test_rule_21_a_line_has_no_path_outside_scroll_mode() -> None:
    scene = entchen_scene()
    key = Keyframe(time=1.0, y=1.0)
    (found,) = messages(edit(scene, "line", 0, path=[key, key]), P, 21)
    assert "a path without scroll mode" in found
    scrolled = scroll_scene()
    assert "a path without scroll mode" in " ".join(messages(scrolled, P, 21))
    cut = scrolled.model_copy(update={"scroll": None})
    assert any("measures of its column" in m for m in messages(cut, SCROLL_PROFILE, 21))


def test_rule_21_a_column_that_moves_while_a_line_is_sung_is_refused() -> None:
    scene = scroll_scene()
    line = scene.lines()[1]
    middle = (line.sing_start + line.sing_end) / 2
    moving = [
        Keyframe(time=line.start, y=line.text_y),
        Keyframe(time=middle, y=line.text_y),
        Keyframe(time=middle + 0.2, y=line.text_y - 40),
        Keyframe(time=line.end, y=line.text_y - 40),
    ]
    (found,) = messages(with_path(scene, 1, moving), SCROLL_PROFILE, 21)
    assert "line 1 moves while it is sung" in found
    after = [*moving[:1], Keyframe(time=line.sing_end, y=line.text_y), *moving[2:]]
    after[2] = Keyframe(time=line.sing_end, y=line.text_y - 40)
    assert not any(
        "while it is sung" in m for m in messages(with_path(scene, 1, after), SCROLL_PROFILE, 21)
    )


def test_rule_21_a_wrapped_line_stands_still_until_the_last_minimum_glide_of_its_last_row() -> None:
    scene = two_row_scene()  # line 0 is sung 10-12 on its first row, 12-14 on its second

    def glide_out(start: float) -> Scene:
        moved = scene
        for index in (0, 1):  # the rows move together
            path = scene.lines()[index].path  # 7.0, 7.4 | 15.5, 15.9 | ...
            keys = [
                *path[:2],
                Keyframe(time=start, y=path[2].y),
                path[3].model_copy(update={"time": start + 0.3}),
                *path[4:],
            ]
            moved = with_path(moved, index, keys)
        return moved

    def sung(start: float) -> list[str]:
        return [m for m in messages(glide_out(start), TWO_ROWS, 21) if "while it is sung" in m]

    # the first row moves after its own words but before the last min_glide of the whole line
    assert sung(13.0) == ["rule 21: line 0 moves while it is sung"]
    assert sung(13.75) == []  # in the last min_glide of the whole line


def test_rule_21_a_brief_second_row_does_not_allow_a_short_glide() -> None:
    scene = two_row_scene()
    second = scene.lines()[1]  # its words, 12-14, shortened to the last 0.1 s
    brief = second.spans[-1].model_copy(update={"start": 13.9, "end": 14.0})
    scene = edit(scene, "line", 1, spans=[brief])
    for index in (0, 1):  # the rows glide out at the brief row's first syllable, for 0.1 s
        path = scene.lines()[index].path  # 7.0, 7.4 | 15.5, 15.9 | ...
        keys = [
            *path[:2],
            Keyframe(time=13.9, y=path[2].y),
            path[3].model_copy(update={"time": 14.0}),
            *path[4:],
        ]
        scene = with_path(scene, index, keys)
    found = [m for m in messages(scene, TWO_ROWS, 21) if "shorter than" in m]
    assert len(found) == 1  # the whole line, 10-14, is not brief


def quick_scene() -> Scene:
    """Three lines that follow without a silence: the glides start during the end of the line."""
    phrases = [sung_line(10.0, 12.0), sung_line(12.1, 14.0), sung_line(14.0, 16.0)]
    return layout(
        phrases, SongText("T", "A", 60.0, {}), SCROLL_PROFILE, (960, 720), FixedMeasurer()
    )


def test_rule_21_a_line_glides_out_during_its_last_minimum_glide() -> None:
    scene = quick_scene()
    assert scene_findings(scene, SCROLL_PROFILE) == []
    view = scene.scroll
    assert view is not None
    line = scene.lines()[1]
    assert line.path[-3].time == pytest.approx(line.sing_end - view.min_glide, abs=0.01)


def test_rule_21_a_glide_out_that_starts_before_the_last_minimum_glide_is_refused() -> None:
    scene = quick_scene()
    view, line = scene.scroll, scene.lines()[1]
    assert view is not None
    top, bottom = line.path[-3], line.path[-2]

    def glide_from(start: float) -> list[Keyframe]:
        return [*line.path[:-3], Keyframe(time=start, y=top.y), bottom, line.path[-1]]

    late = glide_from(line.sing_end - view.min_glide + 0.05)
    assert not any(
        "while it is sung" in m for m in messages(with_path(scene, 1, late), SCROLL_PROFILE, 21)
    )
    early = glide_from(line.sing_end - view.min_glide - 0.1)
    assert any(
        "line 1 moves while it is sung" in m
        for m in messages(with_path(scene, 1, early), SCROLL_PROFILE, 21)
    )


def test_rule_21_a_line_that_glides_in_while_it_is_sung_is_refused() -> None:
    scene = quick_scene()
    line = scene.lines()[1]
    start = line.sing_start - 0.1  # the glide in reaches into the first syllable
    keys = [
        *line.path[:2],
        Keyframe(time=start, y=line.path[2].y),
        Keyframe(time=start + 0.3, y=line.path[3].y),
        *line.path[4:],
    ]
    assert any(
        "moves while it is sung" in m
        for m in messages(with_path(scene, 1, keys), SCROLL_PROFILE, 21)
    )


def test_rule_21_a_glide_between_two_lines_shorter_than_the_minimum_is_refused() -> None:
    scene = quick_scene()
    line = scene.lines()[1]
    top = line.path[-3]
    quick = [*line.path[:-3], Keyframe(time=line.sing_end - 0.1, y=top.y), *line.path[-2:]]
    found = messages(with_path(scene, 1, quick), SCROLL_PROFILE, 21)
    assert any("shorter than" in m for m in found)


def test_rule_21_a_short_glide_from_the_rest_of_the_stop_before_is_fine() -> None:
    phrases = [sung_line(10.0, 12.0), sung_line(12.0, 12.1), sung_line(12.1, 14.0)]
    scene = layout(
        phrases, SongText("T", "A", 60.0, {}), SCROLL_PROFILE, (960, 720), FixedMeasurer()
    )
    assert scene_findings(scene, SCROLL_PROFILE) == []
    view = scene.scroll
    assert view is not None
    glides = {
        (a.time, b.time)
        for x in scene.lines()
        for a, b in zip(x.path, x.path[1:], strict=False)
        if a.y > b.y
    }
    assert any(end - start < view.min_glide - 0.01 for start, end in glides)


def calm_findings(scene: Scene, index: int, path: list[Keyframe]) -> list[str]:
    return [
        m
        for m in messages(with_path(scene, index, path), SCROLL_PROFILE, 21)
        if "shorter than" in m
    ]


def test_rule_21_a_short_glide_is_fine_only_where_the_column_has_just_come_to_rest() -> None:
    scene = quick_scene()
    path = scene.lines()[1].path  # glides 11.7-12.0 and 13.7-14.0, then a rest until 18.0
    assert path[5].time == 14.0
    low = path[5].y - 88.0
    at_rest = [
        *path[:6],
        Keyframe(time=14.1, y=low),
        Keyframe(time=18.0, y=low),
    ]  # 0.1 s from the rest at 14.0
    assert calm_findings(scene, 1, at_rest) == []
    off_rest = [
        *path[:6],
        Keyframe(time=15.0, y=path[5].y),
        Keyframe(time=15.1, y=low),
        Keyframe(time=18.0, y=low),
    ]
    assert len(calm_findings(scene, 1, off_rest)) == 1  # the same 0.1 s, but not from a rest


def test_rule_21_the_first_glide_may_be_short_but_a_later_one_may_not() -> None:
    scene = quick_scene()
    for index in range(3):
        path = scene.lines()[index].path
        scene = with_path(scene, index, [path[0], Keyframe(time=7.3, y=path[0].y), *path[1:]])
    assert [m for m in messages(scene, SCROLL_PROFILE, 21) if "shorter than" in m] == []
    path = scene.lines()[1].path  # 7.0, 7.3, 7.4 | 11.7, 12.0 | 13.7, 14.0, 18.0
    later = [*path[:5], Keyframe(time=13.9, y=path[5].y), path[6], path[7]]
    assert len(calm_findings(scene, 1, later)) == 1
    for index in range(3):  # the second glide of the column takes 0.1 s
        keys = scene.lines()[index].path
        scene = with_path(scene, index, [*keys[:3], Keyframe(time=11.9, y=keys[3].y), *keys[4:]])
    (found,) = [m for m in messages(scene, SCROLL_PROFILE, 21) if "shorter than" in m]
    assert re.search(r"the glide at 11\.9 takes 0\.(1|09)\d* s, shorter than 0\.3 s", found)


def test_rule_21_a_still_stretch_cut_into_short_parts_is_no_glide() -> None:
    scene = quick_scene()
    path = scene.lines()[1].path  # 7.0, 7.4 | 11.7, 12.0 | 13.7, 14.0, 18.0
    cut = [*path[:2], Keyframe(time=9.0, y=path[1].y), Keyframe(time=9.1, y=path[1].y), *path[2:]]
    assert calm_findings(scene, 1, cut) == []


def test_rule_21_a_glide_out_of_a_brief_line_may_be_short_from_its_first_syllable() -> None:
    sung = [sung_line(10.0 + 0.05 * k, 10.05 + 0.05 * k) for k in range(5)]
    scene = layout(sung, SongText("T", "A", 60.0, {}), SCROLL_PROFILE, (960, 720), FixedMeasurer())
    assert scene_findings(scene, SCROLL_PROFILE) == []
    first = scene.lines()[0]
    out = [(a.time, b.time) for a, b in zip(first.path, first.path[1:], strict=False) if a.y > b.y]
    assert any(a == pytest.approx(first.sing_start) and b - a < 0.1 for a, b in out)


def test_rule_2_counts_the_lines_at_rest_unless_a_brief_line_glides_from_its_first_syllable() -> (
    None
):
    scene = scroll_scene()
    rest = scene.scroll
    assert rest is not None
    fewer = scene.model_copy(update={"scroll": rest.model_copy(update={"after": 0})})
    assert messages(fewer, SCROLL_PROFILE, 2) == ["rule 2: 4 lines visible at rest at 9.0"]
    sung = [sung_line(10.0 + 0.05 * k, 10.05 + 0.05 * k) for k in range(8)]
    brief = layout(sung, SongText("T", "A", 60.0, {}), SCROLL_PROFILE, (960, 720), FixedMeasurer())
    assert messages(brief, SCROLL_PROFILE, 2) == []  # 7 lines at 10.1, while the column glides
    view = brief.scroll
    assert view is not None
    narrow = brief.model_copy(update={"scroll": view.model_copy(update={"after": 2})})
    assert "rule 2: 7 lines visible at 10.1" in messages(narrow, SCROLL_PROFILE, 2)  # one more only
    still = brief.lines()[2]
    keys = [Keyframe(time=still.start, y=still.text_y), Keyframe(time=still.end, y=still.text_y)]
    found = messages(with_path(brief, 2, keys), SCROLL_PROFILE, 2)
    assert "rule 2: 7 lines visible at rest at 10.1" in found  # it does not glide: at rest
    arriving = [
        Keyframe(time=still.start, y=still.text_y + 88.0),
        Keyframe(time=still.sing_start - 0.02, y=still.text_y + 88.0),
        Keyframe(time=still.sing_start, y=still.text_y),
        Keyframe(time=still.end, y=still.text_y),
    ]  # a glide in that ends at the first syllable is no glide out
    found = messages(with_path(brief, 2, arriving), SCROLL_PROFILE, 2)
    assert "rule 2: 7 lines visible at rest at 10.1" in found


def test_rule_21_a_jump_while_a_line_is_sung_is_refused_too() -> None:
    scene = scroll_scene()
    line = scene.lines()[1]
    at = line.sing_start + 0.2
    jump = [
        Keyframe(time=line.start, y=line.text_y),
        Keyframe(time=at, y=line.text_y),
        Keyframe(time=at, y=line.text_y - 40),
        Keyframe(time=line.end, y=line.text_y - 40),
    ]
    assert any(
        "moves while it is sung" in m
        for m in messages(with_path(scene, 1, jump), SCROLL_PROFILE, 21)
    )


def test_rule_21_a_line_that_is_not_where_it_is_sung_at_that_time_is_refused() -> None:
    scene = scroll_scene()
    line = scene.lines()[1]
    off = [Keyframe(time=k.time, y=k.y + 10) for k in line.path]
    (found,) = messages(with_path(scene, 1, off), SCROLL_PROFILE, 21)
    assert "line 1" in found


def test_rule_21_the_line_being_sung_stands_at_the_current_height() -> None:
    scene = scroll_scene()
    current = scene.scroll
    assert current is not None
    low = scene.model_copy(
        update={"scroll": current.model_copy(update={"current": current.current + 5})}
    )
    assert any("not at the current height" in m for m in messages(low, SCROLL_PROFILE, 21))
    near = scene.model_copy(
        update={"scroll": current.model_copy(update={"current": current.current + SMALL})}
    )
    assert messages(near, SCROLL_PROFILE, 21) == []


def test_rule_21_rows_that_overlap_in_the_column_are_refused() -> None:
    scene = scroll_scene()
    box = scene.lines()[2].box  # fatter than the room between two lines
    fat = box.model_copy(update={"y": box.y - 25, "h": box.h + 50})
    (found,) = messages(edit(scene, "line", 2, box=fat), SCROLL_PROFILE, 21)
    assert "overlap or change places" in found
    thin = box.model_copy(update={"y": box.y - 10, "h": box.h + 20})
    assert messages(edit(scene, "line", 2, box=thin), SCROLL_PROFILE, 21) == []


def test_rule_21_a_sung_row_outside_the_safe_area_is_refused() -> None:
    scene = scroll_scene()
    last = 2
    line = scene.lines()[last]
    # the row rests far below its place before it glides: outside the safe area
    low = [Keyframe(time=k.time, y=k.y + (400 if i < 3 else 0)) for i, k in enumerate(line.path)]
    (found,) = messages(with_path(scene, last, low), SCROLL_PROFILE, 21)
    assert f"line {last} leaves the safe area" in found


def test_rule_21_a_row_at_rest_outside_the_safe_area_is_judged_by_its_box() -> None:
    scene = scroll_scene()
    bigger = scene.safe.model_copy(update={"h": scene.safe.h / 2})
    assert any(
        "leaves the safe area" in m
        for m in messages(scene.model_copy(update={"safe": bigger}), SCROLL_PROFILE, 21)
    )


def test_rule_21_a_line_only_moves_up() -> None:
    scene = scroll_scene()
    line = scene.lines()[1]
    down = [*line.path[:2], Keyframe(time=line.path[2].time, y=line.path[1].y + 5), *line.path[3:]]
    assert any("moves down" in m for m in messages(with_path(scene, 1, down), SCROLL_PROFILE, 21))


def test_rule_21_a_glide_takes_at_most_the_glide_of_the_profile() -> None:
    scene = scroll_scene()
    line = scene.lines()[1]
    slow = [
        *line.path[:2],
        Keyframe(time=line.path[2].time, y=line.path[2].y),
        Keyframe(time=line.path[2].time + 0.5, y=line.path[3].y),
        *line.path[4:],
    ]
    found = messages(with_path(scene, 1, slow), SCROLL_PROFILE, 21)
    assert any("glides for" in m or "goes back in time" in m for m in found)


def test_rule_21_a_path_runs_from_the_start_to_the_end_of_its_line() -> None:
    scene = scroll_scene()
    line = scene.lines()[1]
    assert any(
        "starts off its path" in m
        for m in messages(edit(scene, "line", 1, start=line.start - 1), SCROLL_PROFILE, 21)
    )
    assert any(
        "ends off its path" in m
        for m in messages(edit(scene, "line", 1, end=line.end + 1), SCROLL_PROFILE, 21)
    )
    assert any(
        "line 1 has no path" in m
        for m in messages(edit(scene, "line", 1, path=[]), SCROLL_PROFILE, 21)
    )


def test_rule_21_a_path_goes_forward_in_time() -> None:
    scene = scroll_scene()
    line = scene.lines()[1]
    back = [line.path[0], Keyframe(time=line.path[0].time - 1, y=line.path[0].y), *line.path[1:]]
    assert any("back in time" in m for m in messages(with_path(scene, 1, back), SCROLL_PROFILE, 21))


def test_rule_21_the_rows_of_a_line_move_together() -> None:
    scene = two_row_scene()
    rows = scene.lines()
    index = next(i for i, x in enumerate(rows) if x.row == 1)
    skewed = [
        Keyframe(time=k.time, y=k.y + (3 if n == 0 else 0)) for n, k in enumerate(rows[index].path)
    ]
    (found,) = messages(with_path(scene, index, skewed), TWO_ROWS, 21)
    assert "does not move with the row above" in found


def test_rule_2_in_scroll_mode_the_lines_around_the_current_one_are_few() -> None:
    chosen = builtin_profile("lyric-scroll", scroll={"before": 0, "after": 1})
    scene = entchen_with(chosen)
    end = scene.duration
    stay = scene
    for index in range(len(scene.lines())):
        stay = edit(stay, "line", index, end=end)
    assert any("lines visible at" in m for m in messages(stay, chosen, 2))
    assert messages(scene, chosen, 2) == []


def test_rule_4_in_scroll_mode_a_row_is_below_the_row_above_and_sung_after_it() -> None:
    scene = two_row_scene()
    rows = scene.lines()
    index = next(i for i, x in enumerate(rows) if x.row == 1)
    up = edit(scene, "line", index, box=shifted(rows[index].box, dy=-rows[index].box.h))
    assert any("is not below" in m for m in messages(up, TWO_ROWS, 4))
    lonely = edit(scene, "line", index, start=rows[index].start - 1)
    assert any("does not belong to the row above" in m for m in messages(lonely, TWO_ROWS, 4))


def test_rule_5_in_scroll_mode_a_line_is_shown_ahead_or_reported() -> None:
    scene = scroll_scene()
    line = scene.lines()[1]
    late = edit(scene, "line", 1, start=line.sing_start - 0.5)
    assert any("line 1 is shown" in m for m in messages(late, SCROLL_PROFILE, 5))
    reported = late.model_copy(
        update={"shortfalls": [Shortfall(kind="lead-in", line=1, message="short")]}
    )
    assert messages(reported, SCROLL_PROFILE, 5) == []
    fine = scene.model_copy(update={"shortfalls": [Shortfall(kind="lead-in", line=1, message="x")]})
    assert any("reported but fine" in m for m in messages(fine, SCROLL_PROFILE, 5))


def test_rule_5_in_scroll_mode_only_the_first_line_is_shown_at_most_the_maximum_ahead() -> None:
    scene = scroll_scene()
    first = scene.lines()[0]
    early = edit(scene, "line", 0, start=first.sing_start - SCROLL_PROFILE.lead_in.max - 1)
    assert any("line 0 is shown" in m for m in messages(early, SCROLL_PROFILE, 5))
    later = scene.lines()[3]  # a later line is shown far ahead: that is the column
    assert later.sing_start - later.start > SCROLL_PROFILE.lead_in.max


def test_rule_9_in_scroll_mode_a_line_ends_by_gliding_out_or_after_the_hold() -> None:
    scene = scroll_scene()
    last = len(scene.lines()) - 1
    line = scene.lines()[last]
    early = edit(scene, "line", last, end=line.end - 0.5)
    assert any(f"line {last} goes at" in m for m in messages(early, SCROLL_PROFILE, 9))
    out = scene.lines()[0]
    assert out.path[-1].y < out.path[-2].y  # it glides out: no complaint
    assert messages(scene, SCROLL_PROFILE, 9) == []


def test_rule_9_in_scroll_mode_a_line_before_a_break_goes_as_the_break_screen_starts() -> None:
    scene = scroll_scene()
    card = next(e for e in scene.elements if isinstance(e, CardElement) and e.kind == "break")
    before = next(
        i for i, x in enumerate(scene.lines()) if abs(x.end - card.start) < 1e-6
    )  # the lines that go with the screen
    late = edit(scene, "line", before, end=card.start + 0.5)
    assert any(f"line {before} goes at" in m for m in messages(late, SCROLL_PROFILE, 9))


def test_rule_10_in_scroll_mode_lines_leave_in_the_order_they_came() -> None:
    scene = scroll_scene()
    first = scene.lines()[0]
    stays = edit(scene, "line", 0, end=scene.lines()[1].end + 1)
    assert any("line 1 stays" in m for m in messages(stays, SCROLL_PROFILE, 10))
    assert first.end <= scene.lines()[1].end


def break_card(scene: Scene) -> CardElement:
    return next(e for e in scene.elements if isinstance(e, CardElement) and e.kind == "break")


def test_rule_12_in_scroll_mode_a_long_break_has_its_break_screen() -> None:
    scene = scroll_scene()
    card = break_card(scene)
    plain = without(scene, "break")
    assert any("no break screen" in m for m in messages(plain, SCROLL_PROFILE, 12))
    soon = edit(scene, "break", 0, start=card.start - 1.5)
    assert any("starts too early" in m for m in messages(soon, SCROLL_PROFILE, 12))
    late = edit(scene, "break", 0, end=card.end + 5)
    assert any("ends too late" in m for m in messages(late, SCROLL_PROFILE, 12))


def test_rule_12_in_scroll_mode_a_notice_needs_a_long_gap() -> None:
    scene = scroll_scene()
    chosen = builtin_profile("lyric-scroll", breaks={"notice_after": 60.0, "clear_after": 5.0})
    assert any("short gap" in m for m in messages(scene, chosen, 12))
    assert break_card(scene).start > 0


def test_rule_12_in_scroll_mode_a_break_screen_may_be_missing_only_where_the_gap_has_no_room() -> (
    None
):
    chosen = builtin_profile(
        "lyric-scroll",
        intro={"solo": 0.0, "group": 0.0},
        breaks={"notice_after": 3.0, "clear_after": 3.0},
        wipe={"offset": 0.2},
    )
    room = chosen.clear.hold + chosen.scroll.glide + MIN_NOTICE + SETTLE + MAX_COUNTDOWN
    room += 2 * 0.2  # the wipe shifted on both sides
    for gap, refused in ((room + 0.05, True), (room - 0.05, False)):
        phrases = [sung_line(10.0, 12.0), sung_line(12.0 + gap, 14.0 + gap)]
        built = layout(phrases, SongText("T", "A", 60.0, {}), chosen, (960, 720), FixedMeasurer())
        plain = without(built, "break")
        assert any("no break screen" in m for m in messages(plain, chosen, 12)) is refused, gap


def test_rule_12_in_scroll_mode_a_break_screen_stands_from_the_hold_to_before_the_line() -> None:
    scene = scroll_scene()
    card = break_card(scene)
    lines = scene.lines()
    after = next(x for x in lines if x.sing_start >= card.end)
    ended = max(x.sing_end for x in lines if x.sing_end <= card.start)
    earliest = ended + SCROLL_PROFILE.clear.hold
    latest = after.sing_start - SETTLE
    fits = edit(scene, "break", 0, start=earliest, end=latest)
    assert [m for m in messages(fits, SCROLL_PROFILE, 12) if "card" in m] == []  # the bounds
    soon = edit(scene, "break", 0, start=earliest - 0.05)
    assert any("starts too early" in m for m in messages(soon, SCROLL_PROFILE, 12))
    late = edit(scene, "break", 0, end=latest + 0.05)
    assert any("ends too late" in m for m in messages(late, SCROLL_PROFILE, 12))


def test_rule_13_in_scroll_mode_the_countdown_is_above_its_line() -> None:
    scene = scroll_scene()
    countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
    low = edit(scene, "countdown", 0, box=shifted(countdown.box, dy=200))
    assert any("not above" in m for m in messages(low, SCROLL_PROFILE, 13))


def test_rule_13_in_scroll_mode_the_countdown_waits_for_the_glide() -> None:
    scene = scroll_scene()
    countdown = [e for e in scene.elements if isinstance(e, CountdownElement)][1]
    lines = scene.lines()
    index = min(
        (i for i, x in enumerate(lines) if x.sing_start >= countdown.end),
        key=lambda i: lines[i].sing_start,
    )
    line = lines[index]
    path = list(line.path)
    last_glide = max(
        i + 1
        for i in range(len(path) - 1)
        if path[i].y > path[i + 1].y and path[i + 1].time <= line.sing_start
    )
    assert path[last_glide].time <= countdown.start + EPS  # the countdown waits for it
    path[last_glide] = Keyframe(time=countdown.start + 0.1, y=path[last_glide].y)
    found = messages(with_path(scene, index, path), SCROLL_PROFILE, 13)
    assert any("is early" in m for m in found), found


def test_rule_13_in_scroll_mode_a_line_may_have_no_countdown_when_there_is_no_room() -> None:
    scene = scroll_scene()
    assert messages(without(scene, "countdown"), SCROLL_PROFILE, 13) != []  # but not here
    tight = builtin_profile("lyric-scroll", countdown={"min_gap": 100.0})
    assert messages(without(entchen_with(tight), "countdown"), tight, 13) == []


def test_rule_17_in_scroll_mode_one_line_is_sung_at_a_time() -> None:
    scene = scroll_scene()
    first, second = scene.lines()[:2]
    both = edit(
        scene,
        "line",
        1,
        spans=[
            s.model_copy(update={"start": first.sing_start, "end": first.sing_end})
            for s in second.spans
        ],
    )
    assert any("more lines sung" in m for m in messages(both, SCROLL_PROFILE, 17))


def test_the_overlap_check_looks_at_a_line_against_the_break_screen() -> None:
    scene = scroll_scene()
    card = break_card(scene)
    index = next(i for i, x in enumerate(scene.lines()) if abs(x.end - card.start) < 1e-6)
    stays = scene.lines()[index]
    by = card.box.y - stays.box.y  # the line stands where the break screen is, until it ends
    path = [
        *moved_path(stays.path[:-1], by),
        Keyframe(time=card.start + 1.0, y=stays.path[-1].y + by),
    ]
    broken = edit(
        scene, "line", index, end=card.start + 1.0, path=path, box=shifted(stays.box, dy=by),
        text_y=stays.text_y + by,
    )  # fmt: skip
    assert "overlap" in hits(broken, SCROLL_PROFILE)
    assert "overlap" not in hits(scene, SCROLL_PROFILE)


def test_rule_21_a_reported_block_shortfall_excuses_a_row_outside_the_safe_area() -> None:
    scene = scroll_scene()
    small = scene.safe.model_copy(update={"h": scene.safe.h / 2})
    broken = scene.model_copy(update={"safe": small})
    found = [m for m in messages(broken, SCROLL_PROFILE, 21) if m.startswith("rule 21: line")]
    assert any("leaves the safe area" in m for m in found)
    excused = broken.model_copy(update={"shortfalls": [Shortfall(kind="block", message="x")]})
    assert [m for m in messages(excused, SCROLL_PROFILE, 21) if "line" in m] == []


def test_the_unbroken_scrolling_break_screens_of_every_form_are_clean() -> None:
    for form in ("notice", "progress", "timer"):
        scene, chosen = form_scene(form)
        assert scene_findings(scene, chosen) == [], form


def test_rule_21_a_line_on_screen_during_a_break_screen_is_refused() -> None:
    scene = scroll_scene()
    card = break_card(scene)
    before = next(i for i, x in enumerate(scene.lines()) if abs(x.end - card.start) < 1e-6)
    stays = scene.lines()[before]
    longer = [*stays.path[:-1], Keyframe(time=card.start + 1.0, y=stays.path[-1].y)]
    found = messages(with_path(scene, before, longer, end=card.start + 1.0), SCROLL_PROFILE, 21)
    assert f"rule 21: line {before} is on screen in break screen 0" in found
    after = next(i for i, x in enumerate(scene.lines()) if x.start >= card.end - 1e-6)
    first = scene.lines()[after]
    sooner = [Keyframe(time=card.end - 1.0, y=first.path[0].y), *first.path]
    early = with_path(scene, after, sooner, start=card.end - 1.0)  # the next part comes too soon
    found = messages(early, SCROLL_PROFILE, 21)
    assert f"rule 21: line {after} is on screen in break screen 0" in found
    assert messages(early, SCROLL_PROFILE, 12) == []  # rule 21 alone says so


def test_rule_21_the_column_has_to_glide_in_from_below_after_a_break_screen() -> None:
    scene = scroll_scene()
    card = break_card(scene)
    index = next(i for i, x in enumerate(scene.lines()) if x.start >= card.end - 1e-6)
    first = scene.lines()[index]
    assert not [m for m in messages(scene, SCROLL_PROFILE, 21) if "glide in" in m]
    # it stands there from the end of the break screen: no glide in
    still = [Keyframe(time=k.time, y=first.text_y) for k in first.path[:2]] + first.path[2:]
    found = messages(with_path(scene, index, still), SCROLL_PROFILE, 21)
    assert "rule 21: the column does not glide in from below after break screen 0" in found
    # it comes in, but later than the screen ends
    late = [Keyframe(time=k.time + 0.2, y=k.y) for k in first.path[:2]] + first.path[2:]
    found = messages(with_path(scene, index, late, start=first.start + 0.2), SCROLL_PROFILE, 21)
    assert "rule 21: the column does not glide in from below after break screen 0" in found


def test_rule_21_reports_a_break_screen_without_a_glide_in_after_it_instead_of_failing() -> None:
    scene = scroll_scene()
    card = break_card(scene)
    lines = scene.lines()
    before = [x for x in lines if x.end <= card.start + 1e-6]
    message = "the column does not glide in from below after break screen 0"
    with pytest.raises(RuleBroken, match=message):  # no line after the screen
        _rule_21_parts(before, [card])
    index = next(i for i, x in enumerate(lines) if x.start >= card.end - 1e-6)
    first = lines[index]
    still = first.model_copy(update={"path": first.path[:1]})  # a path of one keyframe
    with pytest.raises(RuleBroken, match=message):
        _rule_21_parts([*before, still, *lines[index + 1 :]], [card])
    _rule_21_parts(lines, [card])


def test_rule_21_everything_in_the_column_glides_by_the_same_distance() -> None:
    scene = scroll_scene()
    first, second = scene.lines()[:2]
    assert not [m for m in messages(scene, SCROLL_PROFILE, 21) if "together" in m]
    _rule_21_together([first, second])
    start = second.path[0]
    far = second.model_copy(
        update={"path": [start.model_copy(update={"y": start.y + 5}), *second.path[1:]]}
    )  # it comes in over a longer way than the row above
    with pytest.raises(RuleBroken, match="does not glide together"):
        _rule_21_together([first, far])
    one_alone = far.model_copy(update={"start": first.end + 1, "end": first.end + 9})
    _rule_21_together([first, one_alone])  # not on screen over the same stretch: nothing to compare


def test_rules_11_12_and_13_judge_the_break_screen_by_its_whole_life() -> None:
    scene = scroll_scene()
    card = break_card(scene)
    assert messages(scene, SCROLL_PROFILE, 11) == []
    assert messages(scene, SCROLL_PROFILE, 12) == []
    assert messages(scene, SCROLL_PROFILE, 13) == []
    assert card.start < card.end


def test_rule_12_a_bar_or_timer_belongs_to_the_break_screen_that_lives_as_long() -> None:
    for form in ("progress", "timer"):
        scene, chosen = form_scene(form)
        found = messages(edit(scene, form, 0, start=break_card(scene).start + 1.0), chosen, 12)
        assert found, form


def test_rule_5_in_scroll_mode_every_line_is_judged_not_only_the_ones_before_a_second_row() -> None:
    scene = two_row_scene()
    lines = scene.lines()
    last = len(lines) - 1
    late = edit(scene, "line", last, start=lines[last].sing_start - 0.5)
    assert any(f"line {last} is shown" in m for m in messages(late, TWO_ROWS, 5))


def test_the_helpers_of_rule_21_and_13_read_a_path() -> None:
    scene = scroll_scene()
    line = scene.lines()[1]
    rest = _rest_start(line)
    glides = [b.time for a, b in zip(line.path, line.path[1:], strict=False) if a.y > b.y]
    assert rest == max(t for t in glides if t <= line.sing_start)
    still = line.model_copy(update={"path": [Keyframe(time=3.0, y=1.0), Keyframe(time=9.0, y=1.0)]})
    assert _rest_start(still) == 3.0  # it never moved before: it was at rest from the start
    assert _scrolls_out(scene.lines()[0]) is True and _scrolls_out(scene.lines()[-1]) is False
    out = line.model_copy(update={"path": [Keyframe(time=0, y=5), Keyframe(time=1, y=5)]})
    assert _scrolls_out(out) is False  # a stretch that stands still is not a glide out
    one = line.model_copy(update={"path": [Keyframe(time=0, y=5)]})
    assert _scrolls_out(one) is False
    sung = line.sing_start
    after_rest = line.model_copy(
        update={
            "path": [
                Keyframe(time=sung - 3.0, y=10.0),
                Keyframe(time=sung - 2.0, y=5.0),
                Keyframe(time=sung - 1.0, y=5.0),
                Keyframe(time=sung + 1.0, y=5.0),
            ]
        }
    )
    assert (
        _rest_start(after_rest) == sung - 2.0
    )  # the end of the move, not of a still stretch after it
    a = line.model_copy(update={"path": [Keyframe(time=0.0, y=1.0), Keyframe(time=2.0, y=0.0)]})
    b = line.model_copy(update={"path": [Keyframe(time=1.0, y=1.0), Keyframe(time=5.0, y=0.0)]})
    assert _moments([a, b]) == [0.0, 0.5, 1.0, 1.5, 2.0, 3.5, 5.0]


def test_rule_20_in_scroll_mode_a_line_has_no_enter_and_an_exit_of_at_most_the_end_fade() -> None:
    chosen = builtin_profile("lyric-scroll", ending={"fade": 0.5})
    scene = entchen_with(chosen)
    card = break_card(scene)
    before = next(i for i, x in enumerate(scene.lines()) if abs(x.end - card.start) < 1e-6)
    assert messages(scene, chosen, 20) == []
    assert scene.lines()[before].exit == 0.5
    long = edit(scene, "line", before, exit=0.9)
    assert any("takes 0.9 s to exit" in m for m in messages(long, chosen, 20))
    coming = edit(scene, "line", before, enter=0.2)
    assert any("takes 0.2 s to enter" in m for m in messages(coming, chosen, 20))
