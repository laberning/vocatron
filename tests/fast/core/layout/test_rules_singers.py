"""Stage 1: the rules of singers, transitions, restarts and blocks (rules 16, 17, 20, 22, 23)."""

from collections.abc import Sequence

import pytest

from fakes.measure import FixedMeasurer
from fakes.phrases import line as sung_line
from fakes.rule_breaks import (
    BIG,
    CP,
    FADE_PROFILE,
    FRAME,
    LONG_LINE,
    SMALL,
    P,
    edit,
    hits,
    messages,
    mutate,
    page_profile,
    page_scene,
    rule_20,
    without,
)
from fakes.scenes import (
    builtin_profile,
    duet_with,
    entchen_scene,
    entchen_with,
    profile,
)
from vocatron.core.layout import place
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.place import clearing
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.rules_base import TOLERANCE, RuleBroken
from vocatron.core.layout.rules_scroll import _rule_21_safe, _rule_21_together
from vocatron.core.layout.rules_singers import vertical_inside
from vocatron.core.layout.sample import DUET_TURNS
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    Colours,
    Keyframe,
    LineElement,
    LineTurn,
    Rect,
    Scene,
)


def test_rule_16_a_line_with_the_wrong_colours() -> None:
    base = entchen_with(CP)
    wrong = Colours(unsung="#123456", sung="#654321", edge="#111111")
    scene = edit(base, "line", 0, colours=wrong)
    assert hits(scene, CP) == {"16"}
    assert "line 0 has the wrong colours" in messages(scene, CP, 16)[0]
    line = base.lines()[0]
    only_edge = edit(base, "line", 0, colours=line.colours.model_copy(update={"edge": "#123456"}))
    assert "16" in hits(only_edge, CP)
    only_unsung = edit(
        base, "line", 0, colours=line.colours.model_copy(update={"unsung": "#123456"})
    )
    assert "16" in hits(only_unsung, CP)
    only_sung = edit(base, "line", 0, colours=line.colours.model_copy(update={"sung": "#123456"}))
    assert "16" not in hits(only_sung, CP)  # the sung colour is the singers' to choose


def test_rule_16_the_singers_of_a_line_choose_its_colours() -> None:
    base = duet_with(CP)
    for number, line in enumerate(base.lines()):
        assert "16" in hits(
            edit(base, "line", number, singers="5" if line.singers != "5" else "4"), CP
        )


def test_rule_16_singers_the_profile_has_no_colours_for_get_the_group_colours() -> None:
    base = duet_with(CP)
    group = CP.singer_colours("group")
    odd = next(x for x in base.lines() if x.singers == "all")
    assert (odd.colours.unsung, odd.colours.edge) == (group.unsung, group.edge)
    # "all" is no number: it is the group, not singer 1 to 5
    scene = edit(base, "line", base.lines().index(odd), singers="6")
    assert "16" not in hits(scene, CP)


def first_turn_line(scene: Scene) -> tuple[int, LineElement]:
    return next((i, x) for i, x in enumerate(scene.lines()) if x.turns)


def test_rule_16_a_turn_must_lie_inside_the_line() -> None:
    base = duet_with(CP, turns=DUET_TURNS)
    number, line = first_turn_line(base)
    turn = line.turns[0]
    for span in (0, len(line.spans), len(line.spans) + 3):
        scene = edit(base, "line", number, turns=[turn.model_copy(update={"span": span})])
        assert "turn of line" in " ".join(messages(scene, CP, 16)) and "misplaced" in " ".join(
            messages(scene, CP, 16)
        )
    last = edit(base, "line", number, turns=[turn.model_copy(update={"span": len(line.spans) - 1})])
    assert "misplaced" not in " ".join(messages(last, CP, 16))
    first = edit(base, "line", number, turns=[turn.model_copy(update={"span": 1})])
    assert "misplaced" not in " ".join(messages(first, CP, 16))


def test_rule_16_a_turn_rises_by_syllable() -> None:
    base = duet_with(CP, turns=DUET_TURNS)
    number, line = first_turn_line(base)
    turn = line.turns[0]
    other = "2" if turn.singers != "2" else "3"
    again = LineTurn(span=turn.span, singers=other, colours=P_colours(other))
    scene = edit(base, "line", number, turns=[turn, again])
    assert "misplaced" in " ".join(messages(scene, CP, 16))


def P_colours(singers: str) -> Colours:
    base = CP.singer_colours(singers if singers in {"1", "2", "3", "4", "5"} else "group")
    return Colours(unsung=base.unsung, sung=base.sung, edge=base.edge)


def test_rule_16_a_turn_changes_the_singers() -> None:
    base = duet_with(CP, turns=DUET_TURNS)
    number, line = first_turn_line(base)
    turn = line.turns[0]
    same = turn.model_copy(update={"singers": line.singers, "colours": line.colours})
    scene = edit(base, "line", number, turns=[same])
    assert "changes nothing" in " ".join(messages(scene, CP, 16))
    # a second turn is compared with the turn before it, not with the line
    back = LineTurn(span=turn.span + 1, singers=turn.singers, colours=turn.colours)
    scene = edit(base, "line", number, turns=[turn, back])
    assert "changes nothing" in " ".join(messages(scene, CP, 16))


def test_rule_16_a_turn_has_the_colours_of_its_singers() -> None:
    base = duet_with(CP, turns=DUET_TURNS)
    number, line = first_turn_line(base)
    turn = line.turns[0]
    wrong = Colours(unsung="#123456", sung="#654321", edge="#111111")
    scene = edit(base, "line", number, turns=[turn.model_copy(update={"colours": wrong})])
    assert "turn of line" in " ".join(messages(scene, CP, 16))
    assert "wrong colours" in " ".join(messages(scene, CP, 16))
    edge = turn.colours.model_copy(update={"edge": "#123456"})
    scene = edit(base, "line", number, turns=[turn.model_copy(update={"colours": edge})])
    assert "wrong colours" in " ".join(messages(scene, CP, 16))
    unsung = turn.colours.model_copy(update={"unsung": "#123456"})
    scene = edit(base, "line", number, turns=[turn.model_copy(update={"colours": unsung})])
    assert "wrong colours" in " ".join(messages(scene, CP, 16))


def sung_with(scene: Scene, number: int, other: int, offset: float) -> Scene:
    """Return ``scene`` with line ``number`` sung ``offset`` s after line ``other`` starts."""
    lines = scene.lines()
    shift = lines[number].sing_start - (lines[other].sing_start + offset)
    return mutate(
        scene,
        "line",
        number,
        lambda x: x.model_copy(
            update={
                "spans": [
                    s.model_copy(update={"start": s.start - shift, "end": s.end - shift})
                    for s in x.spans
                ]
            }
        ),
    )


def test_rule_17_more_lines_sung_at_once_than_slots() -> None:
    base = without(entchen_scene(), "countdown")
    scene = sung_with(sung_with(base, 1, 0, 0.1), 2, 0, 0.2)
    assert "17" in hits(scene, P)
    assert "more lines sung than slots" in messages(scene, P, 17)[0]


def test_rule_17_as_many_lines_sung_at_once_as_slots_is_fine() -> None:
    base = without(entchen_scene(), "countdown")
    scene = sung_with(base, 1, 0, 0.1)
    assert "17" not in hits(scene, P)
    assert "17" in hits(sung_with(scene, 2, 0, 0.2), P)


def fade_scene() -> Scene:
    return entchen_with(FADE_PROFILE)


def test_rule_20_holds_for_the_unbroken_scenes_with_a_transition() -> None:
    assert scene_findings(fade_scene(), FADE_PROFILE) == []
    slide = profile(cdg=None, transition={"form": "slide", "time": 0.3})
    assert scene_findings(entchen_with(slide), slide) == []


def test_rule_20_a_transition_into_a_syllable_is_refused() -> None:
    line = fade_scene().lines()[0]
    late = edit(fade_scene(), "line", 0, start=line.sing_start - 0.1, enter=0.2)
    (found,) = rule_20(late)
    assert "comes in after its first syllable starts" in found
    ok = edit(fade_scene(), "line", 0, start=line.sing_start - 0.3, enter=0.2)
    assert rule_20(ok) == []


def test_rule_20_a_transition_out_of_a_syllable_is_refused() -> None:
    line = fade_scene().lines()[0]
    early = edit(fade_scene(), "line", 0, end=line.sing_end + 0.1, exit=0.2)
    (found,) = rule_20(early)
    assert "starts to go before its last syllable ends" in found
    ok = edit(fade_scene(), "line", 0, end=line.sing_end + 0.3, exit=0.2)
    assert rule_20(ok) == []


def test_rule_20_a_transition_longer_than_the_profile_says_is_refused() -> None:
    (found,) = rule_20(edit(fade_scene(), "line", 0, enter=0.31))
    assert "takes 0.31 s to enter" in found
    (found,) = rule_20(edit(fade_scene(), "line", 0, exit=0.31))
    assert "takes 0.31 s to exit" in found


def test_rule_20_a_negative_transition_is_refused() -> None:
    assert any("negative enter" in m for m in rule_20(edit(fade_scene(), "line", 0, enter=-0.1)))


def test_rule_20_a_scene_without_a_transition_has_none() -> None:
    scene = edit(entchen_scene(), "line", 0, enter=0.1)
    assert any("takes 0.1 s to enter" in m for m in rule_20(scene, P))


def test_rule_20_a_scene_that_says_another_form_is_refused() -> None:
    scene = fade_scene()
    other = scene.model_copy(update={"look": scene.look.model_copy(update={"transition": "slide"})})
    assert any("another form" in m for m in rule_20(other))


def test_rule_20_the_rows_of_a_line_come_and_go_together() -> None:
    chosen = profile(cdg=None, line_rows=2, transition={"form": "fade", "time": 0.3})
    scene = entchen_with(chosen)
    rows = [i for i, x in enumerate(scene.lines()) if x.row == 1]
    assert rows
    broken = edit(scene, "line", rows[0], enter=0.1)
    (found,) = rule_20(broken, chosen)
    assert "does not come and go with the row above" in found


def test_rule_20_a_wipe_shifted_later_moves_the_end_of_the_singing_the_exit_must_wait_for() -> None:
    shifted_profile = profile(
        cdg=None, transition={"form": "fade", "time": 0.3}, wipe={"offset": 0.5}
    )
    scene = entchen_with(shifted_profile)
    assert rule_20(scene, shifted_profile) == []
    line = scene.lines()[0]
    inside = {"end": line.sing_end + 0.6, "exit": 0.2}  # valid without the shift, not with it
    assert any(
        "starts to go before" in m
        for m in rule_20(edit(scene, "line", 0, **inside), shifted_profile)
    )
    assert (
        rule_20(
            edit(scene, "line", 0, **inside),
            FADE_PROFILE.model_copy(update={"wipe": FADE_PROFILE.wipe}),
        )
        == []
    )


def test_rule_9_a_line_that_outlasts_a_line_sung_after_it() -> None:
    chosen = builtin_profile("three-line")
    base = entchen_with(chosen)
    lines = base.lines()
    later = lines[1].end + 0.5  # line 1 stays on after line 2 has gone
    assert "9" in hits(edit(base, "line", 1, end=later), chosen)
    assert "9" not in hits(base, chosen)


def test_rule_9_a_line_does_not_go_before_its_own_singing_ends() -> None:
    base = entchen_scene()
    line = base.lines()[3]
    early = edit(base, "line", 3, end=line.sing_end - BIG)
    assert "9" in hits(early, P)


def test_rule_22_the_first_line_after_a_long_gap_takes_the_top_slot() -> None:
    chosen = builtin_profile("three-line")
    base = entchen_with(chosen)
    assert base.lines()[3].slot == 0
    assert "22" not in hits(base, chosen)
    moved = edit(base, "line", 3, slot=1)
    assert "22" in hits(moved, chosen)
    assert "line 3 leaves a slot empty" in messages(moved, chosen, 22)[0]


def test_rule_22_the_slots_fill_from_the_top_without_a_hole() -> None:
    chosen = builtin_profile("three-line")
    base = entchen_with(chosen)
    lines = base.lines()
    assert [x.slot for x in lines[3:5]] == [0, 1]
    holed = edit(edit(base, "line", 3, slot=0), "line", 4, slot=2)
    assert "22" in hits(holed, chosen)


def test_rule_22_no_line_appears_before_the_screen_is_cleared() -> None:
    base = entchen_scene()
    line = base.lines()[2]
    cleared = base.lines()[1].sing_end + P.clear.hold
    assert line.start >= cleared - TOLERANCE
    early = edit(base, "line", 2, start=cleared - BIG)
    assert "22" in hits(early, P)
    assert "before the screen is cleared" in messages(early, P, 22)[0]
    assert "22" not in hits(edit(base, "line", 2, start=cleared - SMALL), P)


def test_edge_rule_22_a_line_that_appears_exactly_the_slack_before_the_clearing_is_fine() -> None:
    base = entchen_scene()
    line = base.lines()[2]
    cleared = clearing(base.lines()[1].sing_end, line.sing_start, P)
    assert messages(edit(base, "line", 2, start=cleared - TOLERANCE), P, 22) == []


def test_rule_22_does_not_apply_to_pages_or_the_column() -> None:
    assert "22" not in hits(page_scene(), page_profile())


def test_rule_5_after_a_gap_barely_long_enough_the_line_comes_when_the_screen_is_cleared() -> None:
    chosen = builtin_profile("four-line-stack")  # lead target 5 s, hold 1 s, clear_after 5 s
    phrases = [sung_line(0.0, 0.05), sung_line(5.0496, 5.2996)]
    scene = layout(phrases, SongText("T", "A", 60.0, {}), chosen, (960, 720), FixedMeasurer())
    second = scene.lines()[1]
    assert second.sing_start - second.start < chosen.lead_in.target  # 4 s: the room there is
    assert "5" not in hits(scene, chosen)
    assert "22" not in hits(scene, chosen)


@pytest.mark.parametrize("name", ["two-line-turns", "three-line", "four-line-stack"])
@pytest.mark.parametrize("gap", [5.0, 5.5])
def test_the_rules_hold_when_the_hold_leaves_less_than_the_minimum_lead_in(
    name: str, gap: float
) -> None:
    chosen = builtin_profile(name, clear={"hold": 4.5}, ending={"start_after": 5.0})
    phrases = [sung_line(0.0, 1.0), sung_line(1.5, 2.5), sung_line(2.5 + gap, 3.5 + gap)]
    scene = layout(phrases, SongText("T", "A", 60.0, {}), chosen, (960, 720), FixedMeasurer())
    third = scene.lines()[2]
    assert third.sing_start - third.start == pytest.approx(chosen.lead_in.min)  # the hold gives way
    assert not scene.shortfalls
    assert scene_findings(scene, chosen) == []
    early = edit(scene, "line", 2, start=third.start - BIG)
    assert "22" in hits(early, chosen)


def test_rule_5_a_short_line_after_a_long_gap_could_not_appear_before_the_clearing() -> None:
    # a long gap shorter than lead_in.min: the line appears when the singing stops, and is reported
    chosen = profile(breaks={"clear_after": 0.5}, clear={"hold": 2.0})
    phrases = [sung_line(0.0, 1.0), sung_line(1.5, 2.5), sung_line(3.1, 4.0)]
    scene = layout(phrases, SongText("T", "A", 60.0, {}), chosen, (960, 720), FixedMeasurer())
    assert {s.line for s in scene.shortfalls} == {1, 2}  # both gaps are long (0.5 s)
    assert messages(scene, chosen, 5) == []
    assert messages(scene, chosen, 22) == []


def test_rule_22_the_first_line_of_the_song_takes_the_top_slot() -> None:
    assert "22" in hits(edit(entchen_scene(), "line", 0, slot=1), P)


def test_rule_22_a_gap_of_exactly_clear_after_restarts_the_slots() -> None:
    phrases = [sung_line(0.0, 1.0), sung_line(1.5, 2.5), sung_line(7.5, 8.5), sung_line(9.0, 10.0)]
    scene = layout(phrases, SongText("T", "A", 60.0, {}), P, (960, 720), FixedMeasurer())
    assert [x.slot for x in scene.lines()] == [0, 1, 0, 1]  # 5.0 s after line 1
    assert "22" not in hits(scene, P)
    assert "22" in hits(edit(scene, "line", 2, slot=1), P)


def test_rule_5_a_page_after_a_long_gap_still_needs_the_target_lead_in() -> None:
    # pages may appear before the clearing: the room after it is no excuse in page mode
    chosen = builtin_profile("blue-page", clear={"hold": 3.0}, lead_in={"target": 2.5})
    phrases = [sung_line(0.0, 1.0), sung_line(1.5, 2.5), sung_line(7.5, 8.5), sung_line(9.0, 10.0)]
    scene = layout(phrases, SongText("T", "A", 60.0, {}), chosen, (960, 720), FixedMeasurer())
    page = scene.lines()[2]
    assert page.sing_start - page.start == pytest.approx(chosen.lead_in.target)
    assert messages(scene, chosen, 5) == []
    later = scene
    for index, line in enumerate(scene.lines()):
        if line.page == page.page:  # 2 s ahead: the room after the clearing, short of the target
            later = edit(later, "line", index, start=page.sing_start - 2.0)
    assert "rule 5: line 2 after a gap" in messages(later, chosen, 5)


def test_rule_12_a_line_stays_after_the_clearing_where_the_hold_gives_way() -> None:
    chosen = builtin_profile("two-line-turns", clear={"hold": 4.5}, ending={"start_after": 5.0})
    phrases = [sung_line(0.0, 1.0), sung_line(1.5, 2.5), sung_line(7.5, 8.5)]
    scene = layout(phrases, SongText("T", "A", 60.0, {}), chosen, (960, 720), FixedMeasurer())
    lines = scene.lines()
    cleared = clearing(lines[1].sing_end, lines[2].sing_start, chosen)
    assert cleared < lines[1].sing_end + chosen.clear.hold  # the hold gives way to lead_in.min
    assert messages(scene, chosen, 12) == []
    late = edit(edit(scene, "line", 2, start=cleared + 0.5), "line", 1, end=cleared + 0.3)
    assert "rule 12: a line stays after the long gap before line 2" in messages(late, chosen, 12)


def test_rule_15_a_look_with_a_long_hold_ends_its_lyrics_when_the_end_screen_starts() -> None:
    chosen = profile(clear={"hold": 4.0}, ending={"start_after": 1.0})
    base = entchen_with(chosen)
    assert scene_findings(base, chosen) == []
    last = max(x.sing_end for x in base.lines())
    line_index = len(base.lines()) - 1
    assert max(x.end for x in base.lines()) == pytest.approx(last + 1.0)
    late = edit(base, "line", line_index, end=last + 1.0 + BIG)
    assert "15" in hits(late, chosen)  # the full hold is no longer allowed
    assert "15" not in hits(edit(base, "line", line_index, end=last + 1.0 + SMALL), chosen)


def test_rule_15_a_notice_or_countdown_over_the_end_screen() -> None:
    base = entchen_scene()
    end = next(e for e in base.elements if e.kind == "end")
    over = edit(base, "countdown", 0, start=end.start - 1.0, end=end.start + BIG)
    assert "still on screen when the end screen starts" in " ".join(messages(over, P, 15))


def blocks_profile() -> Profile:
    return builtin_profile("four-line-stack", intro={"solo": 0.0, "group": 0.0})


def blocks_scene(spans: list[tuple[float, float]] | None = None) -> Scene:
    chosen = blocks_profile()
    spans = spans or [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0), (4.5, 5.5), (6.0, 7.0), (7.5, 8.5)]
    phrases = [sung_line(start, end) for start, end in spans]
    return layout(phrases, SongText("T", "A", 60.0, {}), chosen, (960, 720), FixedMeasurer())


def test_rule_23_pairs_share_a_block_appear_together_and_go_together() -> None:
    scene, chosen = blocks_scene(), blocks_profile()
    assert [x.slot for x in scene.lines()] == [0, 1, 2, 3, 0, 1]
    assert scene_findings(scene, chosen) == []
    first, second = scene.lines()[:2]
    assert (first.start, first.end) == (second.start, second.end)


def test_rule_23_the_lines_of_a_group_are_in_one_block_top_to_bottom() -> None:
    scene, chosen = blocks_scene(), blocks_profile()
    assert "23" in hits(edit(scene, "line", 1, slot=2), chosen)  # the other block
    assert "23" in hits(edit(scene, "line", 1, slot=0), chosen)  # on top of its neighbour
    assert "block's slots" in messages(edit(scene, "line", 1, slot=2), chosen, 23)[0]


def test_rule_23_a_lone_line_sits_next_to_the_other_block() -> None:
    spans = [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0), (4.5, 5.5), (6.0, 7.0)]
    scene, chosen = blocks_scene(spans), blocks_profile()
    lone = scene.lines()[4]
    assert lone.slot == 1  # the bottom slot of the upper block
    # the top slot, where an empty row stays under the line: only rule 23 sees it
    assert hits(edit(scene, "line", 4, slot=0, box=scene.slots[0]), chosen) == {"23"}
    assert "23" in hits(edit(scene, "line", 4, slot=2), chosen)  # the other block
    assert (
        "block's slots"
        in messages(edit(scene, "line", 4, slot=0, box=scene.slots[0]), chosen, 23)[0]
    )
    # in the lower block it keeps the top slot, not the bottom one
    below = blocks_scene([(0.0, 1.0), (1.5, 2.5), (3.0, 4.0)])
    assert [x.slot for x in below.lines()] == [0, 1, 2]
    assert hits(edit(below, "line", 2, slot=3, box=below.slots[3]), chosen) == {"23"}


def test_a_lone_line_before_a_split_line_sits_next_to_its_parts() -> None:
    # the case of ADR-0039 on the scene of four-line-stack: a line alone in the top block, as
    # the line after it is split in two and fills the lower block, takes the bottom slot
    long = " ".join(["lala"] * 7)  # split into two lines
    spans = [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0), (4.5, 5.5), (6.0, 7.0)]
    phrases = [*(sung_line(a, b) for a, b in spans), sung_line(7.5, 10.5, long)]
    phrases.append(sung_line(11.0, 12.0))
    chosen = blocks_profile()
    scene = layout(phrases, SongText("T", "A", 60.0, {}), chosen, FRAME, FixedMeasurer())
    lines = scene.lines()
    assert [(x.slot, x.part) for x in lines[4:]] == [(1, 0), (2, 0), (3, 1), (1, 0)]
    assert lines[4].end > lines[5].start  # on screen together, no empty row between them
    assert scene_findings(scene, chosen) == []


def test_rule_23_the_lines_of_a_group_appear_and_go_together() -> None:
    scene, chosen = blocks_scene(), blocks_profile()
    later = scene.lines()[1].start + 0.5
    assert "appear and go together" in messages(edit(scene, "line", 1, start=later), chosen, 23)[0]
    sooner = scene.lines()[1].end - 0.5
    assert "23" in hits(edit(scene, "line", 1, end=sooner), chosen)


def test_rule_23_the_block_before_goes_when_the_group_appears() -> None:
    scene, chosen = blocks_scene(), blocks_profile()
    new = scene.lines()[4].start
    stays = edit(edit(scene, "line", 0, end=new + 1.0), "line", 1, end=new + 1.0)  # still together
    assert "does not go when group 2 appears" in " ".join(messages(stays, chosen, 23))
    early = edit(edit(scene, "line", 0, end=new - 0.5), "line", 1, end=new - 0.5)
    assert "does not go when group 2 appears" in messages(early, chosen, 23)[0]


def test_rule_23_a_group_goes_into_the_block_whose_lines_ended_first() -> None:
    scene, chosen = blocks_scene(), blocks_profile()
    swapped = edit(edit(scene, "line", 4, slot=2), "line", 5, slot=3)
    assert "not in the block that ended first" in messages(swapped, chosen, 23)[0]


def test_rule_23_the_blocks_start_again_after_a_long_gap() -> None:
    spans = [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0), (10.0, 11.0), (11.5, 12.5)]
    scene, chosen = blocks_scene(spans), blocks_profile()
    assert [x.slot for x in scene.lines()] == [0, 1, 2, 0, 1]  # a lone line before the gap
    assert scene_findings(scene, chosen) == []


def test_rule_23_does_not_apply_without_blocks() -> None:
    assert messages(entchen_scene(), P, 23) == []
    assert messages(page_scene(), page_profile(), 23) == []
    assert (
        messages(entchen_with(builtin_profile("three-line")), builtin_profile("three-line"), 23)
        == []
    )


def test_rule_5_the_lead_in_maximum_counts_for_the_first_line_of_a_group_only() -> None:
    chosen = blocks_profile()  # lead_in.max 6 s
    scene = blocks_scene([(0.0, 6.4), (6.5, 7.5), (9.0, 10.0), (10.5, 11.5)])
    second = scene.lines()[1]
    assert second.sing_start - second.start > chosen.lead_in.max  # shown 6.5 s ahead: fine
    assert scene_findings(scene, chosen) == []
    third = scene.lines()[2]
    early = edit(
        edit(scene, "line", 2, start=third.start - 1.0), "line", 3, start=third.start - 1.0
    )
    assert "rule 5: line 2 is shown" in messages(early, chosen, 5)[0]


@pytest.mark.parametrize("long", [0, 1])
def test_rule_5_a_short_line_waits_for_every_line_of_the_group_before_in_its_block(
    long: int,
) -> None:
    # one line of the first pair is sung long: the third pair can take that block only once both
    # are sung, so its first line is short, and that is not a fault (whichever line is the long one)
    pair = [(0.0, 5.9), (0.5, 1.0)] if long == 0 else [(0.0, 0.5), (0.6, 5.9)]
    spans = [*pair, (1.5, 7.0), (2.0, 2.5), (6.0, 6.5), (6.7, 7.2)]
    scene, chosen = blocks_scene(spans), blocks_profile()
    assert [x.slot for x in scene.lines()] == [0, 1, 2, 3, 0, 1]
    assert 4 in [s.line for s in scene.shortfalls if s.kind == "lead-in"]
    assert scene.lines()[4].start == pytest.approx(5.9)  # when the first pair is sung
    assert scene_findings(scene, chosen) == []


def test_rule_23_a_lone_line_takes_a_block_and_the_pair_in_it_goes() -> None:
    spans = [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0), (4.5, 5.5), (6.0, 7.0)]
    scene, chosen = blocks_scene(spans), blocks_profile()
    assert [x.slot for x in scene.lines()] == [0, 1, 2, 3, 1]  # the lone line next to the pair
    assert scene_findings(scene, chosen) == []
    later = scene.lines()[4].start + 1.0
    stays = edit(edit(scene, "line", 0, end=later), "line", 1, end=later)  # still together
    assert "does not go when group 2 appears" in messages(stays, chosen, 23)[0]


def test_rule_23_lines_sung_in_the_first_second_take_the_empty_block() -> None:
    scene = blocks_scene([(0.0, 0.3), (0.35, 0.6), (0.7, 0.9), (1.0, 1.2)])
    assert [x.slot for x in scene.lines()] == [0, 1, 2, 3]
    assert messages(scene, blocks_profile(), 23) == []


def test_rule_23_the_tolerance_counts_for_together() -> None:
    # exactly the tolerance apart (times near 0, where 0.01 is exact) is still together
    scene, chosen = blocks_scene(), blocks_profile()
    edits = [("line", 0, {"end": 0.0}), ("line", 1, {"end": 0.01})]
    edits += [("line", 4, {"start": 0.01}), ("line", 5, {"start": 0.02})]
    for kind, nth, update in edits:
        scene = edit(scene, kind, nth, **update)
    assert messages(scene, chosen, 23) == []


@pytest.mark.parametrize(("start", "slots"), [(15.0, [0, 0, 1, 2]), (17.5, [1, 1, 0, 1])])
def test_rule_23_a_line_wrapped_in_its_slot_is_sung_until_its_last_row(
    start: float, slots: list[int]
) -> None:
    # the gap before the next line counts from the end of the second row: 3 s is no break (from
    # the first row it would be), 5.5 s is one, and the lines start again in the top block
    chosen = builtin_profile("four-line-stack", intro={"solo": 0.0, "group": 0.0}, line_rows=2)
    phrases = [sung_line(0.0, 12.0, LONG_LINE), sung_line(start, start + 1.0)]
    phrases.append(sung_line(start + 1.5, start + 2.5))
    scene = layout(phrases, SongText("T", "A", 60.0, {}), chosen, FRAME, FixedMeasurer())
    lines = scene.lines()
    assert [x.slot for x in lines] == slots
    assert [x.row for x in lines] == [0, 1, 0, 0]
    assert messages(scene, chosen, 23) == []
    assert messages(scene, chosen, 5) == []


HELD_SPANS = [(0.0, 20.0), (1.0, 2.0), (3.0, 20.0), (4.0, 5.0), (6.0, 7.0), (8.0, 9.0)]


def test_rule_23_a_group_without_a_free_block_turns_line_by_line() -> None:
    scene, chosen = blocks_scene(HELD_SPANS), blocks_profile()
    lines = scene.lines()
    assert [x.slot for x in lines] == [0, 1, 2, 3, 1, 3]  # the slots whose lines ended first
    assert lines[4].start != lines[5].start
    assert scene_findings(scene, chosen) == []  # rules 2, 9, 23 and the overlap check hold
    on_top = edit(scene, "line", 4, slot=0)  # over the held line, still being sung
    assert "9" in hits(on_top, chosen)  # the held line would have to go
    stays = edit(scene, "line", 1, end=lines[5].start)  # with its pair, not when its slot is taken
    assert "9" in hits(stays, chosen)


def test_rule_23_a_group_with_a_free_block_does_not_turn_line_by_line() -> None:
    spans = [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0), (4.5, 5.5), (6.0, 7.0), (7.5, 8.5)]
    scene, chosen = blocks_scene(spans), blocks_profile()
    later = scene.lines()[5].start + 0.5
    apart = edit(edit(scene, "line", 5, start=later), "line", 1, end=later)
    assert "appear and go together" in " ".join(messages(apart, chosen, 23))


def held_scene() -> Scene:
    """``HELD_SPANS`` and a pair after the held lines: the blocks go on after falling back."""
    return blocks_scene([*HELD_SPANS, (21.0, 22.0), (22.5, 23.0)])


def test_rule_23_the_blocks_go_on_after_a_group_turned_line_by_line() -> None:
    scene, chosen = held_scene(), blocks_profile()
    lines = scene.lines()
    assert [x.slot for x in lines] == [0, 1, 2, 3, 1, 3, 0, 1]
    assert scene_findings(scene, chosen) == []
    stays = edit(scene, "line", 0, end=lines[6].start + 1.0)  # the held line, past the new pair
    assert "does not go when group 3 appears" in " ".join(messages(stays, chosen, 23))
    apart = edit(scene, "line", 7, start=lines[7].start + 0.5)
    assert "group 3 do not appear and go together" in " ".join(messages(apart, chosen, 23))


def test_rule_23_the_last_pair_goes_together() -> None:
    scene, chosen = blocks_scene(), blocks_profile()
    later = edit(scene, "line", 5, end=scene.lines()[5].end + 1.0)
    assert "group 2 do not appear and go together" in " ".join(messages(later, chosen, 23))


def test_rule_23_every_row_of_a_wrapped_line_goes_when_its_block_is_taken() -> None:
    chosen = builtin_profile("four-line-stack", intro={"solo": 0.0, "group": 0.0}, line_rows=2)
    spans = [(15.0, 16.0), (16.5, 17.5), (18.0, 19.0), (19.5, 20.5)]
    phrases = [sung_line(0.0, 12.0, LONG_LINE), *(sung_line(a, b) for a, b in spans)]
    scene = layout(phrases, SongText("T", "A", 60.0, {}), chosen, FRAME, FixedMeasurer())
    lines = scene.lines()
    assert [(x.slot, x.row) for x in lines] == [(0, 0), (0, 1), (1, 0), (2, 0), (3, 0), (1, 0)]
    assert messages(scene, chosen, 23) == []
    assert lines[0].end == lines[1].end == lines[5].start  # both rows go as the block is taken
    # the first row stays, with a line of the other block (so not apart from its group by order)
    stays = edit(scene, "line", 0, end=lines[3].end)
    assert lines[3].end > lines[5].start
    assert "does not go when group 2 appears" in " ".join(messages(stays, chosen, 23))


def test_rule_5_a_short_line_waits_for_the_last_row_of_the_line_before_in_its_slot() -> None:
    chosen = builtin_profile("two-line-turns", intro={"solo": 0.0, "group": 0.0}, line_rows=2)
    phrases = [sung_line(0.0, 12.0, LONG_LINE), sung_line(12.2, 13.0), sung_line(12.5, 14.0)]
    scene = layout(phrases, SongText("T", "A", 60.0, {}), chosen, FRAME, FixedMeasurer())
    lines = scene.lines()
    assert [(x.slot, x.row) for x in lines] == [(0, 0), (0, 1), (1, 0), (0, 0)]
    assert 3 in [s.line for s in scene.shortfalls if s.kind == "lead-in"]
    assert lines[3].start == pytest.approx(lines[1].sing_end)  # when the second row is sung
    assert messages(scene, chosen, 5) == []


def test_rule_23_a_line_of_a_group_may_go_early_with_the_lines_sung_after_it() -> None:
    # the held first line keeps its slot; its pair goes with the split line sung after it, as
    # lines go in the order they are sung (rule 9), not when the held line's block is taken
    long = " ".join(["lala"] * 14)  # split into four lines: two groups of two
    phrases = [sung_line(0.0, 20.0), sung_line(1.0, 2.0), sung_line(3.0, 20.0, long)]
    phrases += [sung_line(21.0, 22.0), sung_line(23.0, 24.0)]
    chosen = blocks_profile()
    scene = layout(phrases, SongText("T", "A", 60.0, {}), chosen, FRAME, FixedMeasurer())
    lines = scene.lines()
    assert [(x.slot, x.part) for x in lines][:6] == [(0, 0), (1, 0), (2, 0), (3, 1), (2, 2), (3, 3)]
    assert lines[1].end == lines[3].end < lines[0].end  # the pair does not go together
    assert scene_findings(scene, chosen) == []


def test_rule_23_a_line_turning_alone_may_take_an_empty_slot() -> None:
    # a line split into three leaves its last part alone in the second block; with the held
    # lines no block is free, so the next line takes the empty slot under that part
    long = " ".join(["lala"] * 11)
    phrases = [sung_line(0.0, 30.0), sung_line(1.0, 2.0), sung_line(3.0, 30.0, long)]
    phrases += [sung_line(26.0, 27.0), sung_line(27.5, 28.0)]
    chosen = blocks_profile()
    scene = layout(phrases, SongText("T", "A", 60.0, {}), chosen, FRAME, FixedMeasurer())
    lines = scene.lines()
    assert [x.slot for x in lines] == [0, 1, 2, 3, 2, 3, 1]
    assert scene_findings(scene, chosen) == []


def test_rule_23_a_line_turning_alone_takes_the_slot_whose_line_ended_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # held lines in both blocks: the third pair turns line by line, into slots 1 and 3
    spans = [(0.0, 20.0), (1.0, 2.0), (3.0, 20.0), (4.0, 5.0), (15.0, 16.0), (16.5, 17.0)]
    scene, chosen = blocks_scene(spans), blocks_profile()
    assert [x.slot for x in scene.lines()] == [0, 1, 2, 3, 1, 3]
    assert messages(scene, chosen, 23) == []
    choose = place.first_of_run

    def latest_sung(ended: Sequence[float], starts: Sequence[float]) -> int:
        if len(ended) < chosen.slots:  # the choice of a block stays as it is
            return choose(ended, starts)
        return max((s for s in range(len(ended)) if ended[s] <= starts[0]), key=ended.__getitem__)

    monkeypatch.setattr(place, "first_of_run", latest_sung)
    wrong = blocks_scene(spans)  # a placement that picks the slot sung last: both in slot 3
    assert [x.slot for x in wrong.lines()] == [0, 1, 2, 3, 3, 3]
    assert "rule 23: line 4 turns alone but not in the slot" in messages(wrong, chosen, 23)[0]
    assert hits(wrong, chosen) == {"23"}  # no other rule sees it


def test_rule_23_a_pair_held_over_the_next_pairs_goes_line_by_line_as_it_is_sung() -> None:
    # the first pair is sung over the two pairs after it: the third pair takes the second block,
    # and as lines go in sung order the held pair goes when each of its lines is sung (rule 9)
    spans = [(0.0, 5.0), (1.0, 6.0), (1.5, 2.0), (2.5, 3.0), (3.5, 4.0), (4.5, 4.8)]
    scene, chosen = blocks_scene(spans), blocks_profile()
    lines = scene.lines()
    assert [x.slot for x in lines] == [0, 1, 2, 3, 2, 3]
    assert [lines[0].end, lines[1].end] == [lines[0].sing_end, lines[1].sing_end]
    assert lines[0].end != lines[1].end
    assert scene_findings(scene, chosen) == []
    apart = edit(scene, "line", 0, end=lines[0].end + 0.5)  # neither with its pair nor when sung
    assert "9" in hits(apart, chosen)


def synthetic(path: list[tuple[float, float]]) -> LineElement:
    """A row built at y 200 that stands at the keyframes with that y."""
    keys = [Keyframe(time=t, y=y) for t, y in path]
    box = Rect(x=100.0, y=200.0, w=100.0, h=40.0)
    return entchen_scene().lines()[0].model_copy(
        update={"start": keys[0].time, "end": keys[-1].time, "box": box, "text_y": 200.0,
                "path": keys}
    )  # fmt: skip


def test_rule_21_what_glides_at_other_times_by_the_same_total_does_not_glide_together() -> None:
    one = synthetic([(0.0, 300.0), (1.0, 250.0), (2.0, 250.0), (3.0, 200.0)])
    two = synthetic([(0.0, 300.0), (1.0, 300.0), (2.0, 250.0), (3.0, 250.0)])
    _rule_21_together([one, one])
    with pytest.raises(RuleBroken, match="does not glide together"):
        _rule_21_together([one, two])


def test_rule_21_the_glide_out_at_the_end_of_a_path_is_compared_too() -> None:
    one = synthetic([(0.0, 300.0), (1.0, 250.0), (2.0, 200.0)])
    two = synthetic([(0.0, 300.0), (1.0, 250.0), (2.0, 180.0)])  # leaves over a longer way
    with pytest.raises(RuleBroken, match="does not glide together between 1.0 and 2.0"):
        _rule_21_together([one, two])


def test_rule_21_a_stretch_of_no_length_is_not_judged_by_the_safe_area() -> None:
    card = synthetic([(0.0, 900.0), (1.0, 900.0), (1.0, 900.0), (2.0, 200.0)])
    _rule_21_safe(card, "line 0", Rect(x=0, y=0, w=800, h=1000))
    with pytest.raises(RuleBroken, match="line 0 leaves"):
        _rule_21_safe(card, "line 0", Rect(x=0, y=0, w=800, h=500))
    zero = synthetic([(0.0, 300.0), (1.0, 100.0), (1.0, 100.0), (2.0, 0.0)])
    _rule_21_safe(zero, "line 0", Rect(x=0, y=150, w=800, h=500))  # the instant at 100 is outside


def test_a_box_lies_inside_the_safe_area_up_to_the_tolerance_at_top_and_bottom() -> None:
    safe = Rect(x=0, y=TOLERANCE, w=1, h=1)
    assert vertical_inside(Rect(x=0, y=0, w=1, h=1), safe)  # up to the tolerance above the top
    assert not vertical_inside(Rect(x=0, y=-TOLERANCE, w=1, h=1), safe)
    low = Rect(x=0, y=0, w=1, h=1)
    assert vertical_inside(Rect(x=0, y=TOLERANCE, w=1, h=1), low)  # the tolerance below the bottom
    assert not vertical_inside(Rect(x=0, y=TOLERANCE, w=1, h=1 + TOLERANCE), low)
