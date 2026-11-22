"""Stage 1: the rules of the safe area, the slots and the fit (rules 1 to 4)."""

import pytest

from fakes.rule_breaks import (
    BIG,
    SMALL,
    P,
    edit,
    hits,
    messages,
    mutate,
    page_profile,
    page_scene,
    preview_profile,
    preview_scene,
    shifted,
)
from fakes.scenes import (
    entchen_scene,
    entchen_with,
    profile,
    turn_scene,
)
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.rules_base import Gap, boxes, gaps
from vocatron.core.scene import (
    CardElement,
    PreviewElement,
    Rect,
    Scene,
    Shortfall,
)


def test_the_unbroken_samples_are_clean() -> None:
    assert scene_findings(entchen_scene(), P) == []
    assert scene_findings(page_scene(), page_profile()) == []
    assert scene_findings(preview_scene(), preview_profile()) == []
    assert scene_findings(turn_scene(), P) == []


def test_gaps_count_from_the_start_and_from_the_longest_singing() -> None:
    lines = entchen_scene().lines()
    found = gaps(lines)
    assert found[0] == Gap(before=lines[0].sing_start, ended=0.0)
    assert found[1] == Gap(
        round((lines[1].sing_start - lines[0].sing_end) * 1000) / 1000, lines[0].sing_end
    )
    # a line that ends before an earlier one does: the next gap counts from the later end
    long_first = lines[0].model_copy(
        update={"spans": [lines[0].spans[0].model_copy(update={"end": 50.0})]}
    )
    assert gaps([long_first, lines[1], lines[2]])[2].ended == 50.0
    assert (
        gaps([long_first, lines[1]])[1].before == round((lines[1].sing_start - 50.0) * 1000) / 1000
    )
    assert gaps([]) == []


def test_boxes_name_every_card_line_and_every_other_element() -> None:
    scene = entchen_scene()
    found = boxes(scene)
    cards = [e for e in scene.elements if isinstance(e, CardElement)]
    card_lines = sum(len(c.lines) for c in cards)
    assert len(found) == len(scene.elements) - len(cards) + card_lines
    assert ("title line", cards[0].lines[0].box) in found
    assert ("line", scene.lines()[0].box) in found
    assert ("countdown", next(e for e in scene.elements if e.kind == "countdown").box) in found


def moved_title_line(scene: Scene) -> Scene:
    def change(card: CardElement) -> CardElement:
        first = card.lines[0].model_copy(update={"box": shifted(card.lines[0].box, dy=-400)})
        return card.model_copy(update={"lines": [first, *card.lines[1:]]})

    return mutate(scene, "title", 0, change)


def test_rule_1_a_card_line_outside_the_safe_area() -> None:
    scene = moved_title_line(entchen_scene())
    assert hits(scene, P) == {"1"}
    (message,) = messages(scene, P, 1)
    assert "title line" in message


def test_rule_1_a_countdown_outside_the_safe_area() -> None:
    scene = edit(entchen_scene(), "countdown", 0, box=Rect(x=130, y=5, w=140, h=23))
    assert hits(scene, P) == {"1", "13"}
    assert "countdown" in messages(scene, P, 1)[0]


def test_rule_1_a_slot_outside_the_safe_area() -> None:
    base = entchen_scene()
    first = base.slots[0]
    slots = [
        Rect(x=first.x, y=first.y, w=first.w, h=base.safe.bottom - first.y + 10),
        base.slots[1],
    ]
    scene = base.model_copy(update={"slots": slots})
    assert hits(scene, P) == {"1"}
    assert "slot" in messages(scene, P, 1)[0]


def test_rule_1_the_preview_row_outside_the_safe_area() -> None:
    base = preview_scene()
    assert base.preview_row is not None
    row = Rect(x=base.preview_row.x, y=base.preview_row.y, w=base.preview_row.w, h=300)
    scene = base.model_copy(update={"preview_row": row})
    assert hits(scene, preview_profile()) == {"1"}


def test_rule_1_a_box_just_inside_the_safe_area_is_fine() -> None:
    base = entchen_scene()
    wide = Rect(x=base.safe.x, y=base.slots[0].y, w=base.safe.w, h=base.slots[0].h)
    scene = edit(base, "line", 0, box=wide)
    assert scene_findings(scene, P) == []


def test_rule_1_a_line_outside_the_safe_area() -> None:
    scene = edit(entchen_scene(), "line", 0, box=shifted(entchen_scene().lines()[0].box, dx=-100))
    assert "1" in hits(scene, P)


def test_rule_2_more_lines_visible_than_slots() -> None:
    scene = edit(entchen_scene(), "line", 0, end=60.0)
    found = hits(scene, P)
    assert "2" in found
    assert "3 lines visible" in messages(scene, P, 2)[0]


def test_rule_2_checks_the_moment_the_singing_stops() -> None:
    scene = entchen_scene()
    lines = scene.lines()
    # a third line is on screen only just before the second ends being sung: not at any start
    third = lines[0].model_copy(
        update={"start": lines[1].sing_end - 0.2, "end": lines[1].sing_end, "slot": 0}
    )
    broken = scene.model_copy(update={"elements": [*scene.elements, third]})
    assert "2" in hits(broken, P)


def test_rule_2_as_many_lines_as_slots_is_fine() -> None:
    assert "2" not in hits(entchen_scene(), P)
    base = entchen_scene()
    lines = base.lines()
    assert len([x for x in lines if x.visible(lines[2].start - 0.001)]) == P.slots


def test_rule_3_a_line_below_the_smallest_size() -> None:
    scene = edit(entchen_scene(), "line", 0, size=P.font.min_size * entchen_scene().safe.h - BIG)
    assert hits(scene, P) == {"3"}


def test_rule_3_a_line_at_the_smallest_size_is_fine() -> None:
    scene = edit(entchen_scene(), "line", 0, size=P.font.min_size * entchen_scene().safe.h)
    assert scene_findings(scene, P) == []
    scene = edit(entchen_scene(), "line", 0, size=P.font.min_size * entchen_scene().safe.h - SMALL)
    assert scene_findings(scene, P) == []


def test_rule_3_a_small_line_that_is_reported_is_fine() -> None:
    base = edit(entchen_scene(), "line", 2, size=P.font.min_size * entchen_scene().safe.h - BIG)
    reported = base.model_copy(
        update={"shortfalls": [Shortfall(kind="too-wide", line=2, message="x")]}
    )
    assert scene_findings(reported, P) == []
    elsewhere = base.model_copy(
        update={"shortfalls": [Shortfall(kind="too-wide", line=1, message="x")]}
    )
    assert hits(elsewhere, P) == {"3"}
    other_kind = base.model_copy(
        update={"shortfalls": [Shortfall(kind="block", line=2, message="x")]}
    )
    assert hits(other_kind, P) == {"3"}
    assert "line 2" in messages(elsewhere, P, 3)[0]


def test_rule_3_a_line_above_the_font_size() -> None:
    base = entchen_scene()
    biggest = P.font.size * base.safe.h
    assert hits(edit(base, "line", 0, size=biggest + BIG), P) == {"3"}
    assert scene_findings(edit(base, "line", 0, size=biggest + SMALL), P) == []
    assert "larger" in messages(edit(base, "line", 0, size=biggest + BIG), P, 3)[0]


def test_rule_3_a_line_wider_than_the_safe_area() -> None:
    base = entchen_scene()
    wide = Rect(x=base.safe.x - 1, y=base.slots[0].y, w=base.safe.w + 2, h=base.slots[0].h)
    scene = edit(base, "line", 0, box=wide)
    assert "3" in hits(scene, P)
    assert "too wide" in messages(scene, P, 3)[0]
    full = Rect(x=base.safe.x, y=base.slots[0].y, w=base.safe.w, h=base.slots[0].h)
    assert scene_findings(edit(base, "line", 0, box=full), P) == []


def test_rule_4_a_preview_without_a_preview_row() -> None:
    scene = preview_scene().model_copy(update={"preview_row": None})
    assert "4" in hits(scene, preview_profile())
    assert "without a preview row" in messages(scene, preview_profile(), 4)[0]


def test_rule_4_a_preview_outside_its_row() -> None:
    base = preview_scene()
    preview = next(e for e in base.elements if isinstance(e, PreviewElement))
    scene = edit(base, "preview", 0, box=shifted(preview.box, dy=-150))
    assert "4" in hits(scene, preview_profile())
    assert f"preview of {preview.of_line}" in messages(scene, preview_profile(), 4)[0]


def test_rule_4_a_preview_not_below_the_slots() -> None:
    base = preview_scene()
    slot = base.slots[0]
    taller = Rect(x=slot.x, y=slot.y, w=slot.w, h=slot.h + 90)
    scene = base.model_copy(update={"slots": [taller]})
    assert hits(scene, preview_profile()) == {"4"}
    just = Rect(x=slot.x, y=slot.y, w=slot.w, h=slot.h + SMALL)
    assert scene_findings(base.model_copy(update={"slots": [just]}), preview_profile()) == []


def test_rule_4_a_line_leaving_its_slot() -> None:
    base = entchen_scene()
    scene = edit(base, "line", 0, box=shifted(base.lines()[0].box, dy=60))
    assert hits(scene, P) == {"4", "overlap"}  # it also lies on the line below
    assert "line 0 leaves its slot" in messages(scene, P, 4)[0]


def test_rule_4_a_line_in_the_wrong_slot() -> None:
    scene = edit(entchen_scene(), "line", 0, slot=1)
    assert "4" in hits(scene, P)


def test_rule_4_a_centred_line_off_centre() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    assert hits(edit(base, "line", 0, box=shifted(line.box, dx=BIG)), P) == {"4"}
    assert scene_findings(edit(base, "line", 0, box=shifted(line.box, dx=SMALL)), P) == []
    assert scene_findings(edit(base, "line", 0, box=shifted(line.box, dx=-SMALL)), P) == []
    assert "4" in hits(edit(base, "line", 0, box=shifted(line.box, dx=-BIG)), P)


@pytest.mark.parametrize("align", ["left", "right"])
def test_rule_4_lines_that_are_not_centred_are_fine_when_the_profile_says_so(align: str) -> None:
    chosen = profile(align=align)
    scene = entchen_with(chosen)
    assert scene_findings(scene, chosen) == []
    assert any(
        abs(x.box.x + x.box.w / 2 - (scene.safe.x + scene.safe.w / 2)) > 1 for x in scene.lines()
    )
    assert "4" in hits(scene, P)
