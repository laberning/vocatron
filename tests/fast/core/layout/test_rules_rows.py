"""Stage 1: the scene rules on lines of two rows, rows over slots and the timer."""

from typing import Any

import pytest

from fakes.measure import FixedMeasurer
from fakes.phrases import line as sung_line
from fakes.rule_breaks import (
    BIG,
    FRAME,
    LONG_LINE,
    SMALL,
    P,
    edit,
    hits,
    messages,
    mutate,
    rule_20,
    shifted,
    with_span,
    without,
)
from fakes.scenes import (
    builtin_profile,
    entchen_scene,
    entchen_with,
    profile,
)
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.rules_base import TOLERANCE, Gap, gaps
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    Rect,
    Scene,
    TimerElement,
)

ROWS = (1, 2)  # the numbers of the two rows of the first long line in ``rows_scene().lines()``


def rows_profile() -> Profile:
    return builtin_profile("one-line-preview")


def rows_scene() -> Scene:
    """Short, long (two rows), short, long (two rows): the long lines keep their rows together."""
    phrases = [
        sung_line(10, 12, "la la"),
        sung_line(13, 25, LONG_LINE),
        sung_line(26, 28, "li li"),
        sung_line(29, 35, LONG_LINE),
    ]
    info = SongText("Titel", "Künstler", 60.0, {})
    return layout(phrases, info, rows_profile(), FRAME, FixedMeasurer())


def with_copy_of(scene: Scene, number: int, **update: Any) -> Scene:
    """Return ``scene`` with a changed copy of line ``number`` right after it."""
    lines = scene.lines()
    elements = list(scene.elements)
    elements.insert(elements.index(lines[number]) + 1, lines[number].model_copy(update=update))
    return scene.model_copy(update={"elements": elements})


def test_the_rows_sample_has_two_rows_and_is_clean() -> None:
    scene = rows_scene()
    assert [x.slot for x in scene.lines()] == [0] * 6
    first, second = (scene.lines()[n] for n in ROWS)
    assert (first.start, first.end) == (second.start, second.end)
    assert scene_findings(scene, rows_profile()) == []


def test_a_second_row_has_no_silence_before_it() -> None:
    lines = rows_scene().lines()
    found = gaps(lines)
    assert found[2] == Gap(before=0.0, ended=lines[1].sing_end)
    late = mutate(rows_scene(), "line", 2, lambda x: with_span(x, 0, start=x.sing_start + 1.0))
    assert gaps(late.lines())[2].before == 0.0  # even when the second row starts after a pause
    assert found[3].before == round((lines[3].sing_start - lines[2].sing_end) * 1000) / 1000
    assert found[3].before > 0


def test_rule_2_the_rows_of_a_line_count_as_one() -> None:
    scene = rows_scene()
    first, second = (scene.lines()[n] for n in ROWS)
    assert first.visible(first.start) and second.visible(first.start)
    assert messages(scene, rows_profile(), 2) == []
    early = mutate(scene, "line", 3, lambda x: x.model_copy(update={"start": first.start + 0.5}))
    assert "2" in hits(early, rows_profile())


def test_rule_4_a_line_with_more_rows_than_the_profile_allows() -> None:
    scene = rows_scene()
    broken = with_copy_of(scene, 2, row=2)
    assert "rule 4: line 3 is row 3 of a line" in messages(broken, rows_profile(), 4)
    one_row = rows_profile().model_copy(update={"line_rows": 1})
    assert "rule 4: line 2 is row 2 of a line" in messages(scene, one_row, 4)


def test_rule_4_a_second_row_that_is_not_below_the_first() -> None:
    scene = rows_scene()
    lines = scene.lines()
    above = edit(scene, "line", 2, box=lines[1].box)
    assert any("is not below" in m for m in messages(above, rows_profile(), 4))
    for slack in (SMALL, TOLERANCE):  # at the edge of the slack too
        just = lines[2].box.model_copy(update={"y": lines[1].box.bottom - slack})
        assert messages(edit(scene, "line", 2, box=just), rows_profile(), 4) == []


def test_rule_4_a_second_row_that_is_sung_before_the_first_is_done() -> None:
    scene = rows_scene()
    lines = scene.lines()
    early = mutate(scene, "line", 2, lambda x: with_span(x, 0, start=lines[1].sing_end - BIG))
    assert any("sung early" in m for m in messages(early, rows_profile(), 4))
    for slack in (SMALL, TOLERANCE):  # at the edge of the slack too
        ok = mutate(
            scene, "line", 2, lambda x, s=slack: with_span(x, 0, start=lines[1].sing_end - s)
        )
        assert messages(ok, rows_profile(), 4) == []


def test_rule_5_the_second_row_is_judged_with_its_first() -> None:
    scene = rows_scene()
    lines = scene.lines()
    assert lines[2].sing_start - lines[2].start > rows_profile().lead_in.max  # not checked itself
    assert messages(scene, rows_profile(), 5) == []


def test_rule_9_the_rows_of_a_line_go_when_the_next_line_takes_the_slot() -> None:
    scene = rows_scene()
    lines = scene.lines()
    assert lines[1].end == lines[2].end == pytest.approx(lines[3].start)
    late = edit(scene, "line", 1, end=lines[1].end + BIG)
    assert "9" in hits(late, rows_profile())


def test_rule_10_the_rows_of_a_line_do_not_count_as_lines_of_a_page() -> None:
    chosen = builtin_profile(
        "blue-page", slots=2, line_rows=2, font={"size": 0.1, "min_size": 0.07}
    )
    phrases = [
        sung_line(10, 12, "la la"),
        sung_line(12.5, 17, LONG_LINE),
        sung_line(18, 20, "li li"),
    ]
    info = SongText("Titel", "Künstler", 60.0, {})
    scene = layout(phrases, info, chosen, FRAME, FixedMeasurer())
    assert len(scene.lines()) == 4  # one line has two rows
    assert scene_findings(scene, chosen) == []
    assert {x.page for x in scene.lines()} == {0, 1}


def test_rule_5_a_line_after_a_line_of_two_rows_is_still_judged() -> None:
    bare = rows_profile().model_copy(
        update={"preview": rows_profile().preview.model_copy(update={"show": False})}
    )
    phrases = [sung_line(10, 25, LONG_LINE), sung_line(26, 28, "li li")]
    scene = layout(phrases, SongText("Titel", "Künstler", 60.0, {}), bare, FRAME, FixedMeasurer())
    lines = scene.lines()
    assert len(lines) == 3 and scene_findings(scene, bare) == []
    late = edit(scene, "line", 2, start=lines[2].sing_start - bare.lead_in.max - BIG)
    assert any(m.startswith("rule 5: line 2 is shown") for m in messages(late, bare, 5))


def over_slots() -> Profile:
    return builtin_profile(
        "tall-page", slots=4, cdg={"slots": 4}, font={"size": 0.1, "min_size": 0.07}
    )


def over_slots_scene() -> Scene:
    """Short, long (two rows), short on one page of four rows, then a long line on the next."""
    phrases = [
        sung_line(10, 12, "la la"),
        sung_line(12.5, 17, LONG_LINE),
        sung_line(18, 20, "li li"),
        sung_line(40, 46, LONG_LINE),
    ]
    info = SongText("Titel", "Künstler", 80.0, {})
    return layout(phrases, info, over_slots(), FRAME, FixedMeasurer())


def test_the_rows_over_slots_sample_has_a_row_in_every_slot_and_is_clean() -> None:
    scene = over_slots_scene()
    assert [(x.page, x.slot, x.row) for x in scene.lines()] == [
        (0, 0, 0), (0, 1, 0), (0, 2, 1), (0, 3, 0), (1, 1, 0), (1, 2, 1),
    ]  # fmt: skip
    assert scene_findings(scene, over_slots()) == []


def test_rule_2_with_rows_over_slots_every_row_counts() -> None:
    scene = over_slots_scene()
    fewer = over_slots().model_copy(update={"slots": 3})
    assert "rule 2: 4 lines visible" in " ".join(messages(scene, fewer, 2))
    by_line = fewer.model_copy(
        update={"page": fewer.page.model_copy(update={"slot_per_row": False})}
    )
    assert messages(scene, by_line, 2) == []  # rows sharing a slot count as one line


def test_rule_4_the_second_row_is_in_the_slot_below_the_first() -> None:
    scene = over_slots_scene()
    lines = scene.lines()
    same = edit(
        scene,
        "line",
        2,
        slot=lines[1].slot,
        box=shifted(lines[2].box, dy=lines[1].box.y - lines[2].box.y),
    )
    assert "rule 4: row 2 is not in the slot it belongs in" in messages(same, over_slots(), 4)
    far = edit(scene, "line", 2, slot=3, box=scene.slots[3])
    assert "rule 4: row 2 is not in the slot it belongs in" in messages(far, over_slots(), 4)
    shared = over_slots().model_copy(
        update={"page": over_slots().page.model_copy(update={"slot_per_row": False})}
    )
    assert "rule 4: row 2 is not in the slot it belongs in" in messages(scene, shared, 4)


def test_rule_4_a_row_belongs_to_the_row_above_it() -> None:
    scene = over_slots_scene()
    other = edit(scene, "line", 2, row=1, start=scene.lines()[2].start + BIG)
    assert any("does not belong to the row above" in m for m in messages(other, over_slots(), 4))
    skipped = edit(scene, "line", 2, row=2)
    assert any("is row 3 of a line" in m for m in messages(skipped, over_slots(), 4))


def test_rule_10_with_rows_over_slots_a_page_holds_at_most_slots_rows_in_consecutive_slots() -> (
    None
):
    scene = over_slots_scene()
    fewer = over_slots().model_copy(update={"slots": 3})
    assert "rule 10: page 0 has too many lines" in messages(scene, fewer, 10)
    lines = scene.lines()
    gap = edit(scene, "line", 3, slot=3, box=scene.slots[3])
    gap = edit(gap, "line", 2, slot=1, box=scene.slots[1])
    assert "10" in hits(gap, over_slots())
    low = edit(scene, "line", 4, slot=0, box=scene.slots[0])
    assert "10" in hits(low, over_slots())  # a short page of two rows sits at slots 1 and 2
    assert lines[4].slot == 1


def timer_profile() -> Profile:
    return builtin_profile("three-line")


def timer_scene() -> Scene:
    return entchen_with(timer_profile())


def test_the_timer_sample_has_a_timer_and_is_clean() -> None:
    scene = timer_scene()
    assert any(isinstance(e, TimerElement) for e in scene.elements)
    assert scene_findings(scene, timer_profile()) == []


def test_rule_12_a_timer_for_every_break_screen_if_the_form_asks_for_it() -> None:
    base, chosen = timer_scene(), timer_profile()
    assert "timers" in " ".join(messages(without(base, "timer"), chosen, 12))
    plain = entchen_scene()
    extra = TimerElement(
        start=0.0, end=1.0, box=Rect(x=0, y=0, w=1, h=1), colour="#fff", edge_colour="#000",
        size=1.0, edge=0.0, shadow=0.0, text_y=0.0,
    )  # fmt: skip
    assert "timers" in " ".join(
        messages(plain.model_copy(update={"elements": [*plain.elements, extra]}), P, 12)
    )


def test_rule_12_the_timer_is_under_the_text_in_the_middle_and_inside_the_safe_area() -> None:
    base, chosen = timer_scene(), timer_profile()
    card = next(e for e in base.elements if e.kind == "break")
    timer = next(e for e in base.elements if isinstance(e, TimerElement))
    above = edit(base, "timer", 0, box=shifted(timer.box, dy=card.box.y - timer.box.y - 20))
    assert "under the text" in " ".join(messages(above, chosen, 12))
    just = edit(base, "timer", 0, box=shifted(timer.box, dy=card.box.bottom - timer.box.y - SMALL))
    assert "under the text" not in " ".join(messages(just, chosen, 12))
    edge = edit(
        base, "timer", 0, box=shifted(timer.box, dy=card.box.bottom - TOLERANCE - timer.box.y)
    )
    assert "under the text" not in " ".join(messages(edge, chosen, 12))  # the tolerance holds
    aside = edit(base, "timer", 0, box=shifted(timer.box, dx=BIG))
    assert "rule 12: the timer" in messages(aside, chosen, 12)
    out = edit(base, "timer", 0, box=shifted(timer.box, dy=base.safe.bottom))
    assert "rule 12: the timer leaves the safe area" in messages(out, chosen, 12)


def test_rule_12_a_timer_goes_with_its_break_screen() -> None:
    base, chosen = timer_scene(), timer_profile()
    timer = next(e for e in base.elements if isinstance(e, TimerElement))
    early = edit(base, "timer", 0, start=timer.start - 1.0)
    assert "rule 12: a timer does not go with its break screen" in messages(early, chosen, 12)
    late = edit(base, "timer", 0, end=timer.end + 1.0)
    assert "rule 12: a timer does not go with its break screen" in messages(late, chosen, 12)


@pytest.mark.parametrize("offset", [-0.5, 0.5])
def test_rule_20_only_a_wipe_shifted_earlier_moves_the_start_the_entrance_must_end_by(
    offset: float,
) -> None:
    shifted_profile = profile(
        cdg=None, transition={"form": "fade", "time": 0.3}, wipe={"offset": offset}
    )
    scene = entchen_with(shifted_profile)
    line = scene.lines()[0]
    early = min(offset, 0.0)
    ok = edit(scene, "line", 0, start=line.sing_start + early - 0.25, enter=0.2)
    assert rule_20(ok, shifted_profile) == []
    late = edit(scene, "line", 0, start=line.sing_start + early - 0.15, enter=0.2)
    assert any("comes in after" in m for m in rule_20(late, shifted_profile))


def test_rule_20_compares_a_row_only_with_the_row_above() -> None:
    chosen = profile(cdg=None, line_rows=2, transition={"form": "fade", "time": 0.3})
    scene = entchen_with(chosen)
    lines = scene.lines()
    index = next(i for i, x in enumerate(lines) if x.row == 1 and i >= 2)
    before = lines[index - 2]
    block = [i for i, x in enumerate(lines) if x.start == before.start and x.end == before.end]
    assert index - 1 not in block  # the line two above belongs to another block
    changed = scene
    for i in block:
        changed = edit(changed, "line", i, enter=before.enter / 2, exit=before.exit / 2)
    assert rule_20(changed, chosen) == []
