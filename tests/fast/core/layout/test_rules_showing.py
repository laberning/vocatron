"""Stage 1: the rules of showing, holding and clearing lines (rules 5 to 12)."""

from collections.abc import Callable

import pytest

from fakes.measure import FixedMeasurer
from fakes.rule_breaks import (
    BIG,
    LINE_COUNT,
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
    with_span,
    without,
)
from fakes.scenes import (
    builtin_profile,
    duet_with,
    entchen_scene,
    entchen_with,
    profile,
)
from vocatron.core.layout import sample
from vocatron.core.layout.build import SongText
from vocatron.core.layout.pages import page_turn
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.rules_base import TOLERANCE, gaps
from vocatron.core.layout.rules_showing import _earliest_show
from vocatron.core.layout.sample import scene_of, timed_song
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    LineElement,
    PreviewElement,
    ProgressElement,
    Rect,
    Scene,
    Shortfall,
)


def test_rule_5_a_preview_that_ends_when_its_line_does_not_start() -> None:
    base = preview_scene()
    preview = next(e for e in base.elements if isinstance(e, PreviewElement))
    scene = edit(base, "preview", 0, end=preview.end + BIG)
    assert "5" in hits(scene, preview_profile())
    assert "preview" in messages(scene, preview_profile(), 5)[0]
    assert "5" not in hits(edit(base, "preview", 0, end=preview.end + SMALL), preview_profile())


def test_rule_5_a_line_shown_too_long_ahead() -> None:
    base = entchen_scene()
    line = base.lines()[3]
    assert line.sing_start - line.start == pytest.approx(
        P.lead_in.max
    )  # the sample sits on the limit
    sooner = edit(base, "line", 3, start=line.start - BIG)
    assert "5" in hits(sooner, P)
    assert "ahead" in messages(sooner, P, 5)[0]
    assert "5" not in hits(edit(base, "line", 3, start=line.start - SMALL), P)


def test_rule_5_a_line_shown_too_short_ahead() -> None:
    base = entchen_scene()
    first = base.lines()[0]
    later = edit(base, "line", 0, start=first.sing_start - P.lead_in.min + BIG)
    assert "5" in hits(later, P)
    assert "only" in messages(later, P, 5)[0]
    at_min = edit(base, "line", 0, start=first.sing_start - P.lead_in.min)
    assert "5" not in hits(at_min, P)
    nearly = edit(base, "line", 0, start=first.sing_start - P.lead_in.min + SMALL)
    assert "5" not in hits(nearly, P)


def test_rule_5_after_a_gap_the_line_is_shown_for_the_target_time() -> None:
    base = entchen_scene()
    line = base.lines()[5]  # after a very long gap, ahead of the countdown
    assert line.sing_start - line.start >= P.lead_in.target
    later = edit(base, "line", 5, start=line.sing_start - P.lead_in.target + BIG)
    assert "5" in hits(later, P)
    assert "after a gap" in messages(later, P, 5)[0]
    exactly = edit(base, "line", 5, start=line.sing_start - P.lead_in.target)
    assert "5" not in hits(exactly, P)
    nearly = edit(base, "line", 5, start=line.sing_start - P.lead_in.target + SMALL)
    assert "5" not in hits(nearly, P)


def test_rule_5_the_first_line_is_not_a_line_after_a_gap() -> None:
    base = entchen_scene()
    first = base.lines()[0]
    assert first.sing_start - first.start >= P.lead_in.min
    scene = edit(base, "line", 0, start=first.sing_start - P.lead_in.min)
    assert "5" not in hits(scene, P)


def test_rule_5_a_reported_line_is_not_shown_ahead_more_than_the_minimum() -> None:
    base = entchen_scene()
    reported = base.model_copy(
        update={"shortfalls": [Shortfall(kind="lead-in", line=0, message="x")]}
    )
    assert "5" in hits(reported, P)
    assert "reported but fine" in messages(reported, P, 5)[0]
    other = base.model_copy(update={"shortfalls": [Shortfall(kind="title", line=0, message="x")]})
    assert hits(other, P) == set()


def test_rule_5_a_reported_line_that_could_have_appeared_sooner() -> None:
    base = entchen_scene()
    first = base.lines()[0]
    late = edit(base, "line", 0, start=first.sing_start - P.lead_in.min + SMALL)
    reported = late.model_copy(
        update={"shortfalls": [Shortfall(kind="lead-in", line=0, message="x")]}
    )
    assert "could appear sooner" in messages(reported, P, 5)[0]
    # the first line may appear at 0: no title screen is in the way for the rule
    at_zero = edit(base, "line", 0, start=0.0)
    assert "5" in hits(at_zero, P)


def test_rule_5_a_reported_line_is_checked_against_the_line_before_it_in_its_slot() -> None:
    base = entchen_scene()
    lines = base.lines()
    # line 2 shares its slot with line 0; it could appear when line 0 has been sung to its end
    soonest = lines[0].sing_end
    short = edit(base, "line", 2, start=lines[2].sing_start - 0.5)
    report = [Shortfall(kind="lead-in", line=2, message="x")]
    reported = short.model_copy(update={"shortfalls": report})
    assert "could appear sooner" in " ".join(messages(reported, P, 5))
    assert soonest < lines[2].sing_start - 0.5
    ok = edit(base, "line", 2, start=soonest)  # as soon as it could, but shown for a long time
    reported_ok = ok.model_copy(update={"shortfalls": report})
    assert "could appear sooner" not in " ".join(messages(reported_ok, P, 5))


def on_page(scene: Scene, page: int, change: Callable[[LineElement], LineElement]) -> Scene:
    """Return ``scene`` with ``change`` applied to every line of ``page`` (a page moves as one)."""
    numbers = [i for i, x in enumerate(scene.lines()) if x.page == page]
    for number in numbers:
        scene = mutate(scene, "line", number, change)
    return scene


def test_rule_5_in_page_mode_a_page_is_shown_ahead() -> None:
    base = page_scene()
    chosen = page_profile()
    first = next(x for x in base.lines() if x.page == 1)
    shown = first.sing_start - first.start
    assert chosen.lead_in.min < shown <= chosen.lead_in.max
    late = on_page(
        base,
        1,
        lambda x: x.model_copy(update={"start": first.sing_start - chosen.lead_in.min + BIG}),
    )
    assert "only" in " ".join(messages(late, chosen, 5))
    early = on_page(
        base,
        1,
        lambda x: x.model_copy(update={"start": first.sing_start - chosen.lead_in.max - BIG}),
    )
    assert "ahead" in " ".join(messages(early, chosen, 5))
    exact = on_page(
        base, 1, lambda x: x.model_copy(update={"start": first.sing_start - chosen.lead_in.max})
    )
    assert "5" not in hits(exact, chosen)


def test_rule_5_in_page_mode_the_other_lines_of_a_page_are_not_checked_for_the_maximum() -> None:
    base = page_scene()
    lines = base.lines()
    last_in_page = next(i for i, x in enumerate(lines) if x.page == 0 and lines[i - 1].page == 0)
    scene = mutate(
        base, "line", last_in_page, lambda x: x.model_copy(update={"start": x.start - 4.0})
    )
    assert "5" not in hits(scene, page_profile())


TIGHT = "Ja\nNein\nDoch\nOh\nJa\nNein\n"  # short lines close together: the layout reports lead-ins


def tight_scene(name: str) -> tuple[Scene, Profile]:
    chosen = builtin_profile(name)
    song = timed_song(TIGHT, start=9.0, gaps={i: 0.2 for i in range(6)})
    scene = scene_of(
        song, SongText("Ein Titel", "Eine Künstlerin", 60.0, {}), chosen, "4x3-720", FixedMeasurer()
    )
    return scene, chosen


def delayed(scene: Scene, number: int, by: float) -> Scene:
    """Return ``scene`` with line ``number`` first seen ``by`` seconds later (its page with it)."""
    previews = [e for e in scene.elements if isinstance(e, PreviewElement)]
    for index, preview in enumerate(previews):
        if preview.of_line == number:
            return mutate(
                scene, "preview", index, lambda p: p.model_copy(update={"start": p.start + by})
            )
    page = scene.lines()[number].page
    if page is None:
        return edit(scene, "line", number, start=scene.lines()[number].start + by)
    return on_page(scene, page, lambda x: x.model_copy(update={"start": x.start + by}))


@pytest.mark.parametrize("name", ["two-line-turns", "blue-page", "one-line-preview", "full-page"])
def test_rule_5_a_reported_line_was_shown_as_soon_as_it_could_be(name: str) -> None:
    scene, chosen = tight_scene(name)
    reported = [s.line for s in scene.shortfalls if s.kind == "lead-in"]
    assert reported
    assert scene_findings(scene, chosen) == []
    for number in reported:
        assert number is not None
        later = delayed(scene, number, 0.05)
        assert "could appear sooner" in " ".join(messages(later, chosen, 5)), (name, number)
        sooner = delayed(scene, number, -0.05)
        assert "could appear sooner" not in " ".join(messages(sooner, chosen, 5)), (name, number)


def test_rule_6_a_line_that_appears_late() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    scene = edit(base, "line", 0, start=line.sing_start + BIG)
    assert "6" in hits(scene, P)
    assert "appears late" in messages(scene, P, 6)[0]
    assert "6" not in hits(edit(base, "line", 0, start=line.sing_start), P)


def test_rule_6_a_line_that_goes_early() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    scene = edit(base, "line", 0, end=line.sing_end - BIG)
    assert "6" in hits(scene, P)
    assert "goes early" in messages(scene, P, 6)[0]
    assert "6" not in hits(edit(base, "line", 0, end=line.sing_end), P)


def test_rule_6_a_line_is_checked_by_its_own_syllables_not_the_whole_scene() -> None:
    base = entchen_scene()
    scene = edit(base, "line", 3, end=base.lines()[3].sing_end - BIG)
    assert "line 3 goes early" in messages(scene, P, 6)[0]


def test_rule_7_the_front_outside_the_syllable_that_is_sung() -> None:
    base = entchen_scene()
    first = base.lines()[0].spans[0]
    # the second syllable is sung inside the first: there the front is still in the first one
    inside = mutate(
        base,
        "line",
        0,
        lambda x: with_span(x, 1, start=first.start + 0.1, end=first.start + 0.2),
    )
    assert "7" in hits(inside, P)
    assert "rule 7: line 0" in messages(inside, P, 7)[0]


def test_rule_7_a_syllable_of_no_length_has_no_middle_to_check() -> None:
    base = entchen_scene()
    first = base.lines()[0].spans[0]
    # a syllable without time, sung inside the first one
    point = mutate(
        base,
        "line",
        0,
        lambda x: with_span(x, 1, start=first.start + 0.1, end=first.start + 0.1 + TOLERANCE / 2),
    )
    assert "middle" not in " ".join(messages(point, P, 7))
    assert "rule 7: line 0" not in " ".join(
        m for m in messages(point, P, 7) if "end of" not in m and "backwards" not in m
    )


def test_rule_7_the_front_has_to_reach_the_end_of_the_syllable_and_not_go_back() -> None:
    base = entchen_scene()
    first = base.lines()[0].spans[0]
    # the second syllable is drawn to the left of the first: the front goes backwards
    swapped = mutate(
        base, "line", 0, lambda x: with_span(x, 1, x0=first.x0 - 20.0, x1=first.x0 - 10.0)
    )
    assert "goes backwards" in " ".join(messages(swapped, P, 7))


def test_rule_7_a_wipe_that_starts_before_the_first_syllable() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    early = mutate(
        base,
        "line",
        0,
        lambda x: with_span(x, 0, start=line.spans[0].start, end=line.spans[0].start - 1),
    )
    assert "7" in hits(early, P)
    assert "wiped before" in " ".join(messages(early, P, 7)) or "7" in hits(early, P)


@pytest.mark.parametrize("offset", [-0.2, 0.2])
def test_rule_7_a_wipe_offset_in_the_look_is_taken_into_account(offset: float) -> None:
    chosen = profile(wipe={"granularity": "smooth", "offset": offset})
    scene = entchen_with(chosen)
    assert scene.look.wipe_offset == offset
    assert scene_findings(scene, chosen) == []


def test_rule_7_syllable_wipes_are_fine() -> None:
    chosen = profile(wipe={"granularity": "syllable", "offset": 0.1})
    assert scene_findings(entchen_with(chosen), chosen) == []


def test_rule_7_syllables_that_follow_each_other_closely_share_a_front() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    # the second syllable starts before the first ends: one front for both
    tight = mutate(
        base,
        "line",
        0,
        lambda x: with_span(x, 1, start=line.spans[0].end - 0.01),
    )
    assert "7" not in hits(tight, P)


def test_rule_8_a_wipe_that_sweeps_ahead_of_its_syllable() -> None:
    base = entchen_scene()
    scene = base.model_copy(update={"look": base.look.model_copy(update={"wipe": "syllable"})})
    assert hits(scene, P) == {"8"}
    assert "line 0 sweeps ahead" in messages(scene, P, 8)[0]


def test_rule_8_a_syllable_wipe_profile_is_not_held_to_it() -> None:
    chosen = profile(wipe={"granularity": "syllable"})
    scene = entchen_with(chosen)
    assert scene.look.wipe == "syllable"
    assert scene_findings(scene, chosen) == []
    # the same scene against a smooth profile does sweep ahead
    assert "8" in hits(scene, P)


def test_rule_8_short_and_narrow_syllables_are_left_alone() -> None:
    base = entchen_scene()
    scene = base.model_copy(update={"look": base.look.model_copy(update={"wipe": "syllable"})})
    only_narrow = scene
    for number in range(len(scene.lines())):
        only_narrow = mutate(
            only_narrow,
            "line",
            number,
            lambda x: x.model_copy(
                update={"spans": [s.model_copy(update={"x1": s.x0 + 0.5}) for s in x.spans]}
            ),
        )
    assert "8" not in hits(only_narrow, P)
    only_short = scene
    for number in range(len(scene.lines())):
        only_short = mutate(
            only_short,
            "line",
            number,
            lambda x: x.model_copy(
                update={"spans": [s.model_copy(update={"end": s.start + 0.03}) for s in x.spans]}
            ),
        )
    assert "8" not in hits(only_short, P)


@pytest.mark.parametrize("number", range(LINE_COUNT))
@pytest.mark.parametrize("delta", [-0.5, 0.5])
def test_rule_9_a_line_that_goes_at_the_wrong_time(number: int, delta: float) -> None:
    base = entchen_scene()
    scene = edit(base, "line", number, end=base.lines()[number].end + delta)
    assert "9" in hits(scene, P)
    assert f"line {number} goes at" in messages(scene, P, 9)[0]


@pytest.mark.parametrize("number", range(LINE_COUNT))
def test_rule_9_a_line_within_the_slack_is_fine(number: int) -> None:
    base = entchen_scene()
    end = base.lines()[number].end
    for delta in (-SMALL, SMALL):
        assert "9" not in hits(edit(base, "line", number, end=end + delta), P)
    for delta in (-BIG, BIG):
        assert "9" in hits(edit(base, "line", number, end=end + delta), P)


def test_rule_9_the_hold_after_the_last_line_is_the_profiles() -> None:
    chosen = profile(clear={"hold": 3.0}, ending={"start_after": 3.0})
    scene = entchen_with(chosen)
    assert scene_findings(scene, chosen) == []
    assert "9" in hits(scene, P)


def test_rule_9_a_line_waits_for_the_line_that_takes_over_its_slot() -> None:
    # no gap shorter than clear_after is followed by a clear: a line stays until its slot is needed
    chosen = profile(breaks={"clear_after": 30.0, "notice_after": 40.0})
    scene = entchen_with(chosen)
    assert scene_findings(scene, chosen) == []
    assert "9" in hits(scene, P)


def test_rule_9_in_page_mode_the_lines_of_a_page_go_together() -> None:
    base = page_scene()
    chosen = page_profile()
    lines = base.lines()
    for number, line in enumerate(lines):
        assert "9" in hits(edit(base, "line", number, end=line.end - 0.5), chosen)
        assert "9" in hits(edit(base, "line", number, end=line.end + 0.5), chosen)
    assert "9" not in hits(edit(base, "line", 0, end=lines[0].end + SMALL), chosen)


def test_rule_10_a_line_that_appears_before_the_line_before_it() -> None:
    base = entchen_scene()
    lines = base.lines()
    scene = edit(base, "line", 3, start=lines[2].start - 1e-4)
    assert "10" in hits(scene, P)
    assert "line 3 is early" in messages(scene, P, 10)[0]
    assert "10" not in hits(edit(base, "line", 3, start=lines[2].start - 1e-7), P)
    assert "10" not in hits(edit(base, "line", 3, start=lines[2].start), P)
    second = edit(base, "line", 1, start=lines[0].start - 1e-4)  # the first pair is checked too
    assert "line 1 is early" in " ".join(messages(second, P, 10))


def test_rule_10_the_next_line_takes_the_slot_that_was_freed_first() -> None:
    scene = edit(entchen_scene(), "line", 4, slot=1)
    assert "10" in hits(scene, P)
    assert "rule 10: line 4" in messages(scene, P, 10)[0]


def test_rule_10_the_parts_of_a_split_line_sit_in_neighbouring_slots_top_to_bottom() -> None:
    chosen = builtin_profile("three-line")
    base = entchen_with(chosen)
    lines = base.lines()
    assert [(x.slot, x.part) for x in lines[3:5]] == [(0, 0), (1, 1)]  # one line in two parts
    assert scene_findings(base, chosen) == []
    above = edit(base, "line", 4, slot=2)
    assert "line 4 is not in the slot under the part before" in messages(above, chosen, 10)[0]
    low = edit(edit(base, "line", 3, slot=2), "line", 4, slot=3)
    assert "line 3 leaves the slots" in messages(low, chosen, 10)[0]


def test_rule_10_a_split_line_takes_the_slots_that_free_soonest() -> None:
    chosen = builtin_profile("three-line")
    base = entchen_with(chosen)
    lines = base.lines()
    assert [(x.slot, x.part) for x in lines[5:7]] == [(0, 0), (1, 1)]
    # slots 1 and 2 still hold the lines sung just before: the parts would wait for them
    moved = edit(edit(base, "line", 5, slot=1), "line", 6, slot=2)
    assert messages(moved, chosen, 10) == ["rule 10: line 5"]


def test_rule_10_a_line_may_take_a_slot_that_frees_up_with_the_other() -> None:
    # equal end times in both slots: either one may be used next
    chosen = profile(slots=2)
    scene = entchen_with(chosen)
    lines = scene.lines()
    even = scene
    for number in range(2):
        even = edit(even, "line", number, **{})
    assert "10" not in hits(even, chosen)
    assert lines[0].slot != lines[1].slot


def test_rule_10_pages_are_numbered_from_zero_in_order() -> None:
    base = page_scene()
    chosen = page_profile()
    lines = base.lines()
    renumbered = base
    for number, line in enumerate(lines):
        renumbered = edit(renumbered, "line", number, page=(line.page or 0) + 1)
    assert "10" in hits(renumbered, chosen)
    assert "numbered in order" in messages(renumbered, chosen, 10)[0]
    in_line_mode = hits(entchen_scene(), P)
    assert "10" not in in_line_mode


def test_rule_10_the_lines_of_a_page_follow_each_other() -> None:
    base = page_scene()
    chosen = page_profile()
    lines = base.lines()
    second = next(i for i, x in enumerate(lines) if x.page == 1)
    swapped = edit(edit(base, "line", 0, page=1), "line", second, page=0)
    assert "10" in hits(swapped, chosen)


def test_rule_10_a_page_has_no_more_lines_than_slots() -> None:
    base = page_scene()
    chosen = profile(slots=1, mode="page")
    assert "too many lines" in " ".join(messages(base, chosen, 10))


def test_rule_10_a_page_sits_in_the_middle_of_the_block() -> None:
    base = page_scene()
    chosen = page_profile()
    scene = base
    for number, line in enumerate(base.lines()):
        scene = edit(scene, "line", number, slot=line.slot - 1)
    assert "10" in hits(scene, chosen)
    assert f"rule 10: {base.lines()[0].page}" in " ".join(messages(scene, chosen, 10))


def test_rule_10_a_page_is_not_torn() -> None:
    base = page_scene()
    chosen = page_profile()
    lines = base.lines()
    scene = edit(base, "line", 0, end=lines[0].end + 1.0)
    assert "torn" in " ".join(messages(scene, chosen, 10))
    scene = edit(base, "line", 0, start=lines[0].start + 0.5)
    assert "torn" in " ".join(messages(scene, chosen, 10))


def by_line_scene() -> tuple[Scene, Profile]:
    """Hänschen klein in a four-slot look that turns pages line by line: four lines, then two."""
    chosen = builtin_profile("blue-page", page={"turn": "line"})
    song = timed_song(sample.HAENSCHEN, start=9.0, gaps={3: 2.0})
    text = sample.song_text("Hänschen klein", "Volkslied", 60.0, {})
    return sample.scene_of(song, text, chosen, "4x3-720", FixedMeasurer()), chosen


def test_rule_10_a_page_turning_line_by_line_is_not_torn_but_each_line_comes_in_its_time() -> None:
    base, chosen = by_line_scene()
    lines = base.lines()
    assert [(x.page, x.slot) for x in lines] == [(0, 0), (0, 1), (0, 2), (0, 3), (1, 1), (1, 2)]
    assert messages(base, chosen, 10) == []
    assert len({x.end for x in lines[:4]}) > 1  # the old page goes line by line
    assert len({x.start for x in lines[:4]}) == 1 and lines[4].start < lines[5].start
    assert "torn" in " ".join(messages(base, page_profile(), 10))  # whole-page turns are not


def test_rule_10_a_line_of_a_new_page_may_not_appear_before_the_line_in_its_slot_is_sung() -> None:
    base, chosen = by_line_scene()
    lines = base.lines()
    early = edit(base, "line", 5, start=lines[2].sing_end - 0.5)  # slot 2 is sung to its end
    assert "line 5 appears before its slot is sung" in " ".join(messages(early, chosen, 10))
    exact = edit(base, "line", 5, start=lines[2].sing_end)
    assert "before its slot" not in " ".join(messages(exact, chosen, 10))


def test_rule_10_a_line_of_a_new_page_may_not_appear_after_its_first_syllable() -> None:
    base, chosen = by_line_scene()
    lines = base.lines()
    late = edit(base, "line", 5, start=lines[5].sing_start + 0.5)
    assert "line 5 appears late" in " ".join(messages(late, chosen, 10))
    on_time = edit(base, "line", 5, start=lines[5].sing_start)
    assert "appears late" not in " ".join(messages(on_time, chosen, 10))


def test_rule_9_an_old_line_goes_when_its_slot_is_taken_or_at_the_page_turn() -> None:
    base, chosen = by_line_scene()
    lines = base.lines()
    assert messages(base, chosen, 9) == []
    assert lines[1].end == pytest.approx(lines[4].start)  # slot 1 is taken by line 4
    assert lines[2].end == pytest.approx(lines[5].start)
    for taken in (1, 2):  # a line that stays or goes at another moment than the line after it
        for change in (-0.5, 0.5):
            moved = edit(base, "line", taken, end=lines[taken].end + change)
            assert messages(moved, chosen, 9) != []
    turn = page_turn(max(x.sing_end for x in lines[:4]), lines[4].sing_start, chosen)
    assert lines[3].end == pytest.approx(max(turn, lines[4].start))  # slot 3 is not used again
    assert messages(edit(base, "line", 3, end=lines[3].end + 0.5), chosen, 9) != []
    assert messages(edit(base, "line", 0, end=lines[0].end - 0.5), chosen, 9) != []


def test_rule_9_an_unused_slot_goes_at_the_turn_set_by_the_first_line_of_the_next_page() -> None:
    chosen = builtin_profile("blue-page", page={"turn": "line"})
    song = timed_song(sample.HAENSCHEN, start=9.0, gaps={3: 4.0})  # room for a lead-in
    text = sample.song_text("Hänschen klein", "Volkslied", 60.0, {})
    base = sample.scene_of(song, text, chosen, "4x3-720", FixedMeasurer())
    lines = base.lines()
    assert [(x.page, x.slot) for x in lines] == [(0, 0), (0, 1), (0, 2), (0, 3), (1, 1), (1, 2)]
    sung = max(x.sing_end for x in lines[:4])
    turn = page_turn(sung, lines[4].sing_start, chosen)
    assert turn > sung + 0.5  # the hold gives way to the lead-in of line 4, not of line 5
    assert page_turn(sung, lines[5].sing_start, chosen) > turn + 0.1
    assert lines[3].end == pytest.approx(turn)
    assert messages(base, chosen, 9) == []


def wrapped_by_line_scene() -> tuple[Scene, Profile]:
    """The folk-song-like sample in a six-row page look: pages of rows, lines of two rows."""
    chosen = builtin_profile("tall-page", page={"turn": "line"})
    song = timed_song(sample.SAMPLE, start=9.0, gaps={1: 0.4, 2: 0.4, 3: 0.4, 4: 0.4})
    text = sample.song_text("Titel", "Volkslied", 90.0, {})
    return sample.scene_of(song, text, chosen, "4x3-720", FixedMeasurer()), chosen


def test_rule_10_a_wrapped_line_waits_for_every_slot_its_rows_take() -> None:
    base, chosen = wrapped_by_line_scene()
    lines = base.lines()
    assert (lines[6].slot, lines[7].slot, lines[7].row) == (2, 3, 1)  # one line of two rows
    assert messages(base, chosen, 10) == []
    # slot 3 is sung to the end of line 2 only; the rows must not appear before that
    early = lines[2].sing_end - 1.0
    only_second = edit(base, "line", 7, start=early)
    assert "line 7 appears before its slot is sung" in " ".join(messages(only_second, chosen, 10))
    only_first = edit(base, "line", 6, start=early)
    assert "line 6 appears before its slot is sung" in " ".join(messages(only_first, chosen, 10))
    different_end = edit(base, "line", 7, end=lines[7].end - 1.0)
    assert "line 7 is torn" in " ".join(messages(different_end, chosen, 10))


def test_rule_10_a_new_page_line_in_a_slot_the_old_page_did_not_use_waits_for_its_first_line() -> (
    None
):
    chosen = builtin_profile("blue-page", page={"turn": "line"})
    base = duet_with(chosen)
    lines = base.lines()
    assert [(x.page, x.slot) for x in lines[:3]] == [(0, 1), (0, 2), (1, 0)]  # slot 0 was empty
    early = edit(base, "line", 2, start=lines[0].sing_end - 0.5)
    assert "line 2 appears before its slot is sung" in " ".join(messages(early, chosen, 10))
    exact = edit(base, "line", 2, start=lines[0].sing_end)
    assert "before its slot" not in " ".join(messages(exact, chosen, 10))


def test_edge_rule_10_a_line_of_a_new_page_may_be_the_slack_late_and_the_slack_early() -> None:
    base, chosen = by_line_scene()
    lines = base.lines()
    late = edit(base, "line", 5, start=lines[5].sing_start + TOLERANCE)
    assert "appears late" not in " ".join(messages(late, chosen, 10))
    gate = lines[2].sing_end
    early = edit(base, "line", 5, start=gate - TOLERANCE)
    assert "before its slot" not in " ".join(messages(early, chosen, 10))


def test_rule_10_a_page_after_a_gap_of_exactly_clear_after_is_turned_whole() -> None:
    chosen = builtin_profile("blue-page", page={"turn": "line"})
    song = timed_song(sample.HAENSCHEN, start=9.0, gaps={3: 5.0 - sample.WORD_GAP})
    text = sample.song_text("Hänschen klein", "Volkslied", 60.0, {})
    base = sample.scene_of(song, text, chosen, "4x3-720", FixedMeasurer())
    lines = base.lines()
    assert gaps(lines)[4].before == pytest.approx(5.0)  # a long gap: the page is whole
    assert messages(base, chosen, 10) == []
    torn = edit(base, "line", 5, start=lines[5].start + 0.1)
    assert "torn" in " ".join(messages(torn, chosen, 10))


def reported_by_line_scene() -> tuple[Scene, Profile]:
    """Pages back to back that turn line by line, with a lead-in no line can have: all reported."""
    chosen = builtin_profile(
        "blue-page", page={"turn": "line"}, lead_in={"min": 8.0, "target": 9.0, "max": 10.0}
    )
    song, text = sample.back_to_back_piece()
    return sample.scene_of(song, text, chosen, "4x3-720", FixedMeasurer()), chosen


def test_rule_5_a_reported_line_of_a_new_page_appears_when_the_line_in_its_slot_is_sung() -> None:
    base, chosen = reported_by_line_scene()
    lines = base.lines()
    assert messages(base, chosen, 5) == []
    assert lines[4].start == pytest.approx(lines[0].sing_end)  # as soon as slot 0 was sung
    late = edit(base, "line", 4, start=lines[4].start + 0.2)
    assert "line 4 could appear sooner" in " ".join(messages(late, chosen, 5))
    held = edit(base, "line", 5, start=lines[5].start + 0.2)
    assert "line 5 could appear sooner" in " ".join(messages(held, chosen, 5))


def test_rule_5_a_reported_line_of_a_new_page_may_wait_for_the_line_above_it() -> None:
    base, chosen = reported_by_line_scene()
    lines = base.lines()
    later = lines[1].sing_end + 0.3  # line 4 appears after the slot of line 5 was sung
    waiting = edit(base, "line", 4, start=later)
    # the first failure stops rule 5 at line 4, so line 5 is asked directly
    assert _earliest_show(waiting, chosen, 5) == pytest.approx(later)
    assert _earliest_show(base, chosen, 5) == pytest.approx(lines[1].sing_end)


def test_rule_10_a_page_is_not_cut_between_lines_sung_at_the_same_time() -> None:
    base = page_scene()
    chosen = page_profile()
    lines = base.lines()
    second = next(i for i, x in enumerate(lines) if x.page == 1)
    first_page_last = max(i for i, x in enumerate(lines) if x.page == 0)
    long_sung = mutate(
        base,
        "line",
        first_page_last,
        lambda x: with_span(x, len(x.spans) - 1, end=lines[second].sing_start + 1.0),
    )
    assert "cut between" in " ".join(messages(long_sung, chosen, 10))
    touching = mutate(
        base,
        "line",
        first_page_last,
        lambda x: with_span(x, len(x.spans) - 1, end=lines[second].sing_start + SMALL),
    )
    assert "cut between" not in " ".join(messages(touching, chosen, 10))


def test_rule_11_a_countdown_in_a_short_gap() -> None:
    base = entchen_scene()
    lines = base.lines()
    end = lines[1].sing_start - 0.6  # a beat before the line, as a countdown in beats ends
    scene = edit(base, "countdown", 0, end=end, start=end - 2.0)
    assert "11" in hits(scene, P)
    assert "a countdown in a short gap" in messages(scene, P, 11)[0]


def test_rule_11_a_countdown_in_a_gap_of_the_minimum_length_is_fine() -> None:
    chosen = profile(countdown={"min_gap": 6.08})
    assert pytest.approx(gaps(entchen_scene().lines())[2].before) == 6.08
    scene = entchen_with(chosen)
    assert "11" not in hits(scene, chosen)


def test_rule_11_a_break_screen_in_a_short_gap() -> None:
    base = entchen_scene()
    lines = base.lines()
    scene = edit(base, "break", 0, end=lines[4].start, start=lines[4].start - 3.0)
    assert "11" in hits(scene, P)
    assert "a break screen in a short gap" in messages(scene, P, 11)[0]


def test_rule_11_a_break_screen_in_a_gap_of_the_minimum_length_is_fine() -> None:
    chosen = profile(breaks={"notice_after": 22.08})
    assert gaps(entchen_scene().lines())[5].before == pytest.approx(22.08)
    assert "11" not in hits(entchen_with(chosen), chosen)


def test_rule_11_an_empty_screen_in_a_short_gap() -> None:
    base = preview_scene()
    lines = base.lines()
    gone = edit(base, "line", 0, end=lines[0].sing_end)
    late = edit(gone, "line", 1, start=lines[1].sing_start - 0.1)
    assert "11" in hits(late, preview_profile())
    assert "the screen is empty" in messages(late, preview_profile(), 11)[0]
    assert "gap before line 1" in messages(late, preview_profile(), 11)[0]


def test_rule_11_an_empty_screen_after_a_line_goes_in_a_short_gap() -> None:
    base = entchen_scene()
    lines = base.lines()
    # line 3 and line 4 are sung close together; line 3 goes while line 4 is not yet on screen
    scene = edit(base, "line", 3, end=lines[3].start + 0.1)
    scene = edit(scene, "line", 2, end=lines[2].start + 0.1)
    assert "11" in hits(scene, P)


def test_rule_11_a_gap_of_nothing_needs_no_line_on_screen() -> None:
    assert "11" not in hits(entchen_scene(), P)


def test_rule_12_a_line_stays_after_a_long_gap() -> None:
    base = entchen_scene()
    lines = base.lines()
    scene = edit(base, "line", 4, end=lines[4].end + 5.0)
    assert "12" in hits(scene, P)
    assert "a line stays after the long gap before line 5" in messages(scene, P, 12)[0]


def test_rule_12_a_line_that_is_gone_when_the_hold_is_over_is_fine() -> None:
    base = entchen_scene()
    lines = base.lines()
    cleared = lines[4].sing_end + P.clear.hold
    scene = edit(base, "line", 4, end=cleared + SMALL)
    assert "12" not in hits(scene, P)


def test_rule_12_a_very_long_gap_needs_a_break_screen() -> None:
    scene = without(entchen_scene(), "break")
    assert "12" in hits(scene, P)
    assert "no break screen before line 5" in messages(scene, P, 12)[0]


def test_rule_12_a_gap_that_is_long_but_not_very_long_needs_none() -> None:
    chosen = profile(breaks={"notice_after": 30.0})
    scene = entchen_with(chosen)
    assert not [e for e in scene.elements if e.kind == "break"]
    assert scene_findings(scene, chosen) == []
    assert "12" in hits(scene, P)


def test_rule_12_a_break_screen_that_starts_before_the_screen_is_cleared() -> None:
    base = entchen_scene()
    lines = base.lines()
    cleared = lines[4].sing_end + P.clear.hold
    early = edit(base, "break", 0, start=cleared - BIG)
    assert "12" in hits(early, P)
    assert "too early" in " ".join(messages(early, P, 12))
    assert "too early" not in " ".join(
        messages(edit(base, "break", 0, start=cleared - SMALL), P, 12)
    )


def test_rule_12_a_break_screen_that_ends_elsewhere() -> None:
    base = entchen_scene()
    lines = base.lines()
    brk = next(e for e in base.elements if e.kind == "break")
    scene = edit(base, "break", 0, end=brk.end - BIG)
    assert "12" in hits(scene, P)
    assert "no break screen before line 5" in messages(scene, P, 12)[0]
    assert lines[5].start == pytest.approx(brk.end)
    near = edit(base, "break", 0, end=brk.end - SMALL)
    assert "no break screen" not in " ".join(messages(near, P, 12))


def test_rule_12_a_break_screen_that_would_not_have_the_time_is_not_needed() -> None:
    # the long gap, but the hold covers it: the next line shows before the screen is cleared
    chosen = profile(clear={"hold": 20.0}, breaks={"notice_after": 15.0})
    scene = entchen_with(chosen)
    assert "12" not in hits(scene, chosen)


def test_rule_12_a_progress_bar_for_every_break_screen_if_the_form_asks_for_it() -> None:
    base = page_scene()
    chosen = page_profile()
    assert any(isinstance(e, ProgressElement) for e in base.elements)
    assert "progress bars" in " ".join(messages(without(base, "progress"), chosen, 12))
    plain = entchen_scene()
    extra = ProgressElement(
        start=0.0, end=1.0, box=Rect(x=0, y=0, w=1, h=1), fill="#fff", frame="#000"
    )
    assert "progress bars" in " ".join(
        messages(plain.model_copy(update={"elements": [*plain.elements, extra]}), P, 12)
    )


def test_rule_12_the_progress_bar_is_under_the_text() -> None:
    base = page_scene()
    chosen = page_profile()
    card = next(e for e in base.elements if e.kind == "break")
    bar = next(e for e in base.elements if e.kind == "progress")
    above = edit(
        base, "progress", 0, box=Rect(x=bar.box.x, y=card.box.y - 20, w=bar.box.w, h=bar.box.h)
    )
    assert "under the text" in " ".join(messages(above, chosen, 12))
    just = edit(base, "progress", 0, box=shifted(bar.box, dy=card.box.bottom - bar.box.y - SMALL))
    assert "under the text" not in " ".join(messages(just, chosen, 12))
    low = edit(base, "progress", 0, box=shifted(bar.box, dy=card.box.bottom - bar.box.y - BIG))
    assert "under the text" in " ".join(messages(low, chosen, 12))
