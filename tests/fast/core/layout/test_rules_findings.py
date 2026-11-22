"""Stage 1: the scene rules live in core and report findings instead of raising (ADR-0019)."""

import pytest

from fakes.scenes import builtin_profile, duet_scene, entchen_scene, entchen_with, profile
from vocatron.core.layout import rules
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.rules_base import RuleBroken, need
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import LineElement, ProgressElement, Rect, Scene


def narrowed(scene: Scene) -> Scene:
    """The same scene with a safe area so small that every text box leaves it."""
    return scene.model_copy(update={"safe": Rect(x=0, y=0, w=10, h=10)})


def test_a_clean_scene_has_no_findings() -> None:
    assert scene_findings(entchen_scene(), profile()) == []
    assert scene_findings(duet_scene(), profile()) == []


def test_a_box_outside_the_safe_area_is_a_rule_1_finding() -> None:
    found = scene_findings(narrowed(entchen_scene()), profile())
    assert any(message.startswith("rule 1:") for message in found)


def test_every_rule_reports_at_most_one_finding() -> None:
    found = scene_findings(narrowed(entchen_scene()), profile())
    assert len(found) == len(set(found))
    assert len([m for m in found if m.startswith("rule 1:")]) == 1


def test_need_raises_only_when_the_condition_fails() -> None:
    need(True, "never seen")
    with pytest.raises(RuleBroken, match="rule 99: broken"):
        need(False, "rule 99: broken")


def _edited(scene: Scene, kind: str, **update: object) -> Scene:
    """The scene with fields of the first element of ``kind`` changed."""
    elements = list(scene.elements)
    index = next(i for i, e in enumerate(elements) if e.kind == kind)
    elements[index] = elements[index].model_copy(update=update)
    return scene.model_copy(update={"elements": elements})


def test_a_countdown_before_no_line_cannot_be_checked_by_rule_11() -> None:
    # rule 11 looks for the line the countdown leads into and finds none (StopIteration)
    scene = _edited(entchen_scene(), "countdown", start=0.1, end=0.2)
    found = scene_findings(scene, profile())
    assert "rule 11 could not be checked: StopIteration" in found
    assert any(m.startswith("rule 13:") for m in found)  # the other rules still run


def test_a_progress_bar_beside_its_break_screen_cannot_be_checked_by_rule_12() -> None:
    # rule 12 looks for the one bar with the times of the break screen and finds none
    chosen = builtin_profile("blue-page")
    base = entchen_with(chosen)
    bar = next(e for e in base.elements if isinstance(e, ProgressElement))
    scene = _edited(base, "progress", start=bar.start + 1.0)
    assert scene_findings(base, chosen) == []
    assert scene_findings(scene, chosen) == ["rule 12 could not be checked: ValueError"]


def test_a_line_in_a_slot_that_does_not_exist_cannot_be_checked_by_rule_4() -> None:
    # rule 4 finds no such slot (IndexError); rule 10 sees the line leave the slots
    base = entchen_scene()
    elements = list(base.elements)
    index = [i for i, e in enumerate(elements) if isinstance(e, LineElement)][2]
    elements[index] = elements[index].model_copy(update={"slot": 2})
    found = scene_findings(base.model_copy(update={"elements": elements}), profile())
    assert "rule 4 could not be checked: IndexError" in found
    assert "rule 10: line 2 leaves the slots" in found


def test_a_check_without_a_rule_number_is_named_by_its_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_overlap(scene: Scene, chosen: Profile) -> None:
        del scene, chosen
        raise ZeroDivisionError

    monkeypatch.setattr(rules, "RULES", (no_overlap,))
    found = scene_findings(entchen_scene(), profile())
    assert found == ["no overlap could not be checked: ZeroDivisionError"]
