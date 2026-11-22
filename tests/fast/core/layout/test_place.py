"""Stage 1: which slot a line takes and when it appears and goes (rules 5, 6, 9, 10, 11)."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import JsonValue

from fakes.resources import FakeResources
from vocatron.core.layout.place import (
    Placement,
    Times,
    clearing,
    falls_back,
    first_of_run,
    group_slots,
    groups,
    hold_end,
    in_order,
    last_hold,
    lead_in_shortfalls,
    place,
)
from vocatron.core.profiles.model import BUILTIN_PROFILES, Profile, parse_profile
from vocatron.core.scene import Shortfall

TEXT = FakeResources().builtin_profile("two-line-turns") or ""
# The rules are tested with fixed numbers, not with whatever the shipped profile is tuned to.
RULE_TIMING: dict[str, JsonValue] = {
    "lead_in": {"min": 1.0, "target": 2.5, "max": 3.0},
    "clear": {"hold": 1.5, "replace_after": 0.33},
}
BASE = parse_profile("two-line-turns", TEXT, RULE_TIMING)


def lines(*spans: tuple[float, float]) -> list[Times]:
    return [Times(start, end) for start, end in spans]


def shortfalls_of(
    times: list[Times], placed: list[Placement], profile: Profile = BASE
) -> list[Shortfall]:
    return lead_in_shortfalls([p.show for p in placed], times, profile)


def test_two_slots_take_turns() -> None:
    placed = place(lines((10, 12), (12.5, 15), (15.5, 18), (18.5, 20)), 7.5, BASE)
    assert [p.slot for p in placed] == [0, 1, 0, 1]


def test_a_line_appears_as_early_as_the_lead_in_maximum_allows() -> None:
    placed = place(lines((10, 12), (14, 16)), 7.5, BASE)
    assert placed[0].show == 7.5  # the first line appears when the title leaves
    assert placed[1].show == pytest.approx(11.0)  # 3 s before it is sung


def test_the_slot_of_a_line_is_refilled_after_the_other_line_has_started() -> None:
    placed = place(lines((10, 12), (12.5, 15), (16, 18)), 7.5, BASE)
    assert placed[2].show == pytest.approx(13.0)  # 3 s ahead, and after 12.5 + 0.33


def test_a_sung_line_stays_until_its_slot_is_needed() -> None:
    placed = place(lines((10, 12), (12.5, 15), (19.0, 20.0)), 7.5, BASE)
    assert placed[2].show == pytest.approx(16.0)
    assert placed[0].hide == placed[2].show  # not 12 + 1.5: a 4 s gap keeps the screen (rule 11)
    placed = place(lines((10, 12), (12.2, 15), (12.4, 18)), 7.5, BASE)
    assert placed[0].hide == placed[2].show  # the slot was needed before the hold ran out


def test_before_a_long_gap_the_lines_go_hold_after_the_singing_stops() -> None:
    placed = place(lines((10, 12), (12.5, 15), (20.0, 21.0)), 7.5, BASE)
    assert placed[0].hide == pytest.approx(16.5)  # 15 + 1.5: the page clears as a whole
    assert placed[1].hide == pytest.approx(16.5)  # line 1 is not replaced, the gap follows it


def test_a_long_gap_later_does_not_cut_a_short_gap_short() -> None:
    placed = place(lines((0, 0.05), (4.85, 5.15), (11.15, 11.2)), 0.0, BASE)
    assert placed[1].show == pytest.approx(1.85)
    assert placed[0].hide == pytest.approx(6.65)  # not 1.55: the 4.8 s gap keeps line 0
    assert placed[1].hide == pytest.approx(6.65)  # both go hold after 5.15, before the 6 s gap


def test_a_line_whose_slot_is_not_needed_again_stays_until_the_screen_clears() -> None:
    profile: Profile = BASE.model_copy(update={"slots": 3})
    placed = place(lines((10, 12), (12.5, 15), (13.0, 14.0)), 7.5, profile)
    assert [p.hide for p in placed] == pytest.approx([16.5, 16.5, 16.5])  # 15 + 1.5 for all
    placed = place(lines((0, 0.05), (4.85, 4.9)), 0.0, BASE)
    assert placed[0].hide == pytest.approx(6.4)  # the first line stays through the 4.8 s gap


def test_a_slot_that_is_free_late_gives_a_short_lead_in_that_is_reported() -> None:
    times = lines((10, 12.5), (12.5, 13), (13.2, 14))
    placed = place(times, 7.5, BASE)
    shortfalls = shortfalls_of(times, placed)
    assert placed[2].show == pytest.approx(12.5)  # the moment the line before in its slot ends
    assert [(s.kind, s.line) for s in shortfalls] == [("lead-in", 2)]


def test_waiting_for_the_other_line_gives_way_to_the_minimum_lead_in() -> None:
    times = lines((10, 12), (12.0, 13), (13.2, 14))
    placed = place(times, 7.5, BASE)
    shortfalls = shortfalls_of(times, placed)
    assert placed[2].show == pytest.approx(12.2)  # not 12.33: 1 s ahead, the slot is free
    assert not shortfalls


def test_with_one_slot_the_line_appears_when_the_one_before_has_ended() -> None:
    profile: Profile = BASE.model_copy(update={"slots": 1})
    times = lines((10, 12), (14, 16))
    placed = place(times, 7.5, profile)
    shortfalls = shortfalls_of(times, placed, profile)
    assert placed[1].show == pytest.approx(12.0)
    assert not shortfalls


def test_lines_appear_in_order() -> None:
    placed = place(lines((10, 30), (10.5, 11), (11.5, 12), (12.5, 13)), 7.5, BASE)
    shows = [p.show for p in placed]
    assert shows == sorted(shows)


def test_a_song_without_lines_places_nothing() -> None:
    assert place([], 0.0, BASE) == []


def test_a_gap_of_exactly_clear_after_is_long_whatever_the_float_rounding() -> None:
    assert 8.2 - 3.2 < 5.0  # 4.999999999999999
    placed = place(lines((1, 3.2), (8.2, 9)), 0.0, BASE)
    assert placed[0].hide == pytest.approx(4.7)  # 3.2 + 1.5: the screen clears for the gap


def test_of_two_slots_finishing_together_the_upper_one_is_refilled_and_the_other_stays() -> None:
    placed = place(lines((10, 12), (10.5, 12), (13, 14)), 7.5, BASE)
    assert [p.slot for p in placed] == [0, 1, 0]
    assert placed[0].hide == placed[2].show  # refilled
    assert placed[1].hide == pytest.approx(15.5)  # stays through the short gap, hold after 14


THREE = BASE.model_copy(update={"slots": 3})


def test_the_parts_of_a_split_line_take_neighbouring_slots_top_to_bottom() -> None:
    times = lines((10, 11), (11.5, 12.5), (13, 14), (14.5, 15.5), (16, 17), (17.5, 18), (18.2, 19))
    assert [p.slot for p in place(times, 7.5, THREE)][5:] == [2, 0]  # taking turns wraps round
    placed = place(times, 7.5, THREE, [0, 0, 0, 0, 0, 0, 1])
    assert [p.slot for p in placed] == [0, 1, 2, 0, 1, 0, 1]  # in order, on top of each other
    assert [p.show for p in placed] == sorted(p.show for p in placed)


def test_a_split_line_takes_the_slots_that_free_soonest_before_its_parts() -> None:
    # slot 0 holds the line sung just before: the parts go into slots 1 and 2
    times = lines((10, 11), (11.5, 12.5), (13, 14), (14.5, 15.5), (16, 17), (17.5, 18))
    assert [p.slot for p in place(times, 7.5, THREE, [0, 0, 0, 0, 0, 1])] == [0, 1, 2, 0, 1, 2]
    assert [p.slot for p in place(times[:5], 7.5, THREE, [0, 0, 0, 0, 1])] == [0, 1, 2, 0, 1]


def test_with_two_slots_the_parts_of_a_split_line_take_turns() -> None:
    times = lines((10, 11), (11.5, 12.5), (13, 14), (14.5, 15.5))
    assert [p.slot for p in place(times, 7.5, BASE, [0, 0, 0, 1])] == [0, 1, 0, 1]
    assert [p.slot for p in place(times[1:], 7.5, BASE, [0, 0, 1])] == [0, 1, 0]


def test_the_run_with_the_longest_shortest_lead_in_wins_the_first_from_the_top_on_a_tie() -> None:
    assert first_of_run([3.0, 1.0, 2.0], [5.0]) == 1  # one part: the slot that ended first
    assert first_of_run([1.0, 1.0, 1.0], [5.0]) == 0
    assert first_of_run([4.0, 1.0, 2.0], [5.0, 6.0]) == 1
    assert first_of_run([1.0, 4.5, 2.0], [5.0, 6.0]) == 0  # 4.5 frees 1.5 s before part two
    assert first_of_run([4.9, 1.0, 4.0], [5.0, 6.0]) == 1  # 4.9 frees 0.1 s before part one
    assert first_of_run([2.0, 2.0, 2.0, 2.0], [5.0, 6.0, 7.0]) == 0


# --------------------------------------------------------------- after a break (ADR-0034)

LONG_LEAD = BASE.model_copy(
    update={"lead_in": BASE.lead_in.model_copy(update={"min": 1.0, "target": 2.5, "max": 5.0})}
)


@pytest.mark.parametrize("slots", [2, 3, 4])
@pytest.mark.parametrize("before", [1, 3, 5])
def test_after_a_long_gap_the_lines_fill_the_slots_from_the_top(slots: int, before: int) -> None:
    profile = BASE.model_copy(update={"slots": slots})
    first = [(10 + 2 * n, 11.5 + 2 * n) for n in range(before)]
    resume = first[-1][1] + 6.0
    after = [(resume + 2 * n, resume + 1.5 + 2 * n) for n in range(slots)]
    placed = place(lines(*first, *after), 7.5, profile)
    assert [p.slot for p in placed[before:]] == list(range(slots))


def test_after_a_long_gap_nothing_appears_before_the_screen_is_cleared() -> None:
    times = lines((10, 12), (12.5, 15), (15.5, 18), (24.0, 26.0), (26.5, 28.0))
    placed = place(times, 7.5, LONG_LEAD)
    cleared = 18 + 1.5
    assert placed[3].slot == 0  # not the bottom slot the turn-taking would give
    assert placed[3].show == pytest.approx(cleared)  # 4.5 s ahead: not 19, the lead-in maximum
    assert placed[4].show >= cleared
    assert placed[2].hide == pytest.approx(cleared)
    assert all(p.hide <= cleared + 1e-9 for p in placed[:3])  # all gone before the new phrase
    assert not shortfalls_of(times, placed, LONG_LEAD)  # the normal lead-in


def test_the_hold_gives_way_to_the_minimum_lead_in_after_a_long_gap() -> None:
    # a look of its own: a hold of 4.5 s leaves only 0.5 s of a 5 s gap after the clearing
    long_hold = LONG_LEAD.model_copy(update={"clear": BASE.clear.model_copy(update={"hold": 4.5})})
    times = lines((10, 12), (12.5, 15), (15.5, 18), (23.0, 25.0), (25.5, 27.0))
    placed = place(times, 7.5, long_hold)
    assert placed[3].slot == 0
    assert placed[3].show == pytest.approx(23.0 - 1.0)  # lead_in.min, not 0.5 s ahead
    assert all(p.hide <= 22.0 + 1e-9 for p in placed[:3])  # the screen is cleared by then
    assert not shortfalls_of(times, placed, long_hold)


def test_the_screen_is_cleared_after_the_hold_but_in_time_for_the_minimum_lead_in() -> None:
    assert clearing(10.0, 20.0, BASE) == pytest.approx(10.0 + BASE.clear.hold)
    held = BASE.model_copy(update={"clear": BASE.clear.model_copy(update={"hold": 4.5})})
    assert clearing(10.0, 15.0, held) == pytest.approx(15.0 - BASE.lead_in.min)
    assert clearing(10.0, 10.4, held) == pytest.approx(10.0)  # never before the singing stopped


def test_a_gap_shorter_than_clear_after_keeps_the_flow() -> None:
    placed = place(lines((10, 12), (12.5, 15), (15.5, 18), (22.0, 24.0)), 7.5, BASE)
    assert [p.slot for p in placed] == [0, 1, 0, 1]  # 4 s: the screen is not cleared


def test_a_phrase_after_a_long_gap_goes_on_taking_turns_from_the_top() -> None:
    times = lines((10, 12), (12.5, 15), (15.5, 18), (24, 26), (26.5, 28), (29, 30))
    assert [p.slot for p in place(times, 7.5, BASE)] == [0, 1, 0, 0, 1, 0]


def test_a_split_line_after_a_long_gap_starts_in_the_top_slot() -> None:
    times = lines((10, 11), (11.5, 12.5), (13, 14), (20, 21), (21.5, 22.5))
    placed = place(times, 7.5, THREE, [0, 0, 0, 0, 1])
    assert [p.slot for p in placed[3:]] == [0, 1]


def test_lines_leave_in_the_order_they_were_sung() -> None:
    # three slots, pairs and a single: the single takes the third slot, which nothing needs again
    times = lines((10, 11), (11.5, 12.5), (13, 14), (14.5, 15.5), (16, 17), (17.5, 18))
    placed = place(times, 7.5, THREE, [0, 1, 0, 0, 1, 0])
    hides = [p.hide for p in placed]
    assert hides == sorted(hides)
    assert all(h >= t.end for h, t in zip(hides, times, strict=True))


def test_a_line_that_would_stay_goes_with_the_one_sung_after_it() -> None:
    assert in_order([20.0, 30.0, 12.0], [5.0, 6.0, 7.0]) == [12.0, 12.0, 12.0]
    assert in_order([20.0, 30.0, 12.0], [5.0, 14.0, 7.0]) == [
        12.0,
        14.0,
        12.0,
    ]  # not before its end
    assert in_order([], []) == []
    assert in_order([8.0], [9.0]) == [9.0]


def test_early_lines_are_not_held_back_by_a_clearing_that_never_happened() -> None:
    placed = place(lines((0.0, 0.2), (0.3, 0.5)), 0.0, BASE)
    assert [p.show for p in placed] == [0.0, 0.0]  # no long gap: nothing waits for a clearing


GAP = st.sampled_from([0.0, 0.3, 1.0, 3.0, 4.9, 5.0, 6.0, 12.0, 20.0])
LENGTH = st.sampled_from([0.4, 1.0, 2.5])


@st.composite
def sung(draw: st.DrawFn) -> list[Times]:
    clock = draw(st.sampled_from([5.0, 9.0]))
    found: list[Times] = []
    for _ in range(draw(st.integers(1, 12))):
        start = clock + draw(GAP)
        clock = start + draw(LENGTH)
        found.append(Times(start, clock))
    return found


def with_hold(profile: Profile, hold: float | None) -> Profile:
    """Return ``profile`` with its ``clear.hold`` replaced, unless ``hold`` is ``None``."""
    if hold is None:
        return profile
    return profile.model_copy(update={"clear": profile.clear.model_copy(update={"hold": hold})})


def drawn_parts(times: list[Times], data: st.DataObject) -> list[int]:
    """Draw the part of every line (0 to 2); the first line is always a whole line."""
    parts = [data.draw(st.integers(0, 2)) for _ in times]
    parts[0] = 0
    return parts


@settings(max_examples=200, deadline=None)
@given(
    times=sung(),
    name=st.sampled_from(BUILTIN_PROFILES),
    hold=st.sampled_from([None, 0.0, 3.5, 4.5, 6.0]),
    data=st.data(),
)
def test_every_profile_restarts_at_the_top_and_lets_the_lines_leave_in_order(
    times: list[Times], name: str, hold: float | None, data: st.DataObject
) -> None:
    profile = parse_profile(name, FakeResources().builtin_profile(name) or "")
    if profile.mode != "line":
        return  # pages and the scroll column place their lines in other ways
    profile = with_hold(profile, hold)  # also a look of one's own whose hold takes most of a gap
    parts = drawn_parts(times, data)
    placed = place(times, 1.0, profile, parts)
    hides = [p.hide for p in placed]
    assert hides == sorted(hides)
    for line, here in zip(times, placed, strict=True):
        assert here.show <= line.start + 1e-9
        assert here.hide >= line.end - 1e-9
    ended = 0.0
    for index, (line, here) in enumerate(zip(times, placed, strict=True)):
        if index and round(line.start - ended, 3) >= profile.breaks.clear_after:
            assert here.show >= clearing(ended, line.start, profile) - 1e-9
            assert line.start - here.show >= profile.lead_in.min - 1e-9  # the hold gives way
            assert all(p.hide <= here.show + 1e-9 for p in placed[:index])  # the screen is clear
            if parts[index] == 0:
                assert here.slot // profile.block == 0  # the top block (ADR-0034)
        ended = max(ended, line.end)


def ending(chosen: Profile, hold: float, start_after: float, end_screen: bool = True) -> Profile:
    return chosen.model_copy(
        update={
            "clear": chosen.clear.model_copy(update={"hold": hold}),
            "ending": chosen.ending.model_copy(
                update={"start_after": start_after, "end_screen": end_screen}
            ),
        }
    )


def test_the_last_hold_gives_way_to_the_end_screen() -> None:
    times = lines((10, 12), (12.5, 15))
    assert last_hold(times, ending(BASE, 4.0, 1.0)) == pytest.approx(16.0)
    assert last_hold(times, ending(BASE, 0.5, 1.0)) == pytest.approx(15.5)  # a short hold stays
    assert last_hold(times, ending(BASE, 4.0, 0.0)) == pytest.approx(15.0)  # never before the end
    assert hold_end(15.0, ending(BASE, 4.0, 1.0)) == pytest.approx(16.0)


def test_without_an_end_screen_the_last_hold_stays_in_full() -> None:
    assert last_hold(lines((10, 12), (12.5, 15)), ending(BASE, 4.0, 1.0, False)) == pytest.approx(
        19.0
    )
    assert last_hold(lines(), ending(BASE, 4.0, 1.0)) == pytest.approx(1.0)


def test_the_last_lines_go_when_the_end_screen_starts() -> None:
    times = lines((10, 12), (12.5, 15))
    placed = place(times, 7.5, ending(BASE, 4.0, 1.0))
    assert [p.hide for p in placed] == [pytest.approx(16.0)] * 2
    full = place(times, 7.5, ending(BASE, 4.0, 1.0, False))
    assert [p.hide for p in full] == [pytest.approx(19.0)] * 2


# ------------------------------------------------------------------ blocks (ADR-0038)

BLOCKS = BASE.model_copy(update={"slots": 4, "block": 2})
STEADY = lines((10, 11.5), (12, 13.5), (14, 15.5), (16, 17.5), (18, 19.5), (20, 21.5))


def test_the_lines_are_grouped_in_pairs_in_sung_order() -> None:
    assert groups(STEADY, [0] * 6, BLOCKS) == [0, 0, 1, 1, 2, 2]
    assert groups(STEADY[:5], [0] * 5, BLOCKS) == [0, 0, 1, 1, 2]  # the last group is short
    triples = BLOCKS.model_copy(update={"slots": 6, "block": 3})
    assert groups(STEADY, [0] * 6, triples) == [0, 0, 0, 1, 1, 1]
    assert groups([], [], BLOCKS) == []


def test_a_split_line_fills_a_block_on_its_own() -> None:
    parts = [0, 0, 1, 0, 0]
    assert groups(STEADY[:5], parts, BLOCKS) == [0, 1, 1, 2, 2]  # not [0, 0, 1, ...]
    placed = place(STEADY[:5], 7.5, BLOCKS, parts)
    assert [p.slot for p in placed] == [1, 2, 3, 0, 1]  # the lone line next to the lower block
    assert placed[1].show == placed[2].show  # the two parts appear together


@pytest.mark.parametrize(
    ("slots", "block", "number", "size", "expected"),
    [
        (4, 2, 0, 2, [0, 1]),  # a full group fills its block
        (4, 2, 1, 2, [2, 3]),
        (4, 2, 0, 1, [1]),  # upper block: from the bottom
        (4, 2, 1, 1, [2]),  # lower block: from the top
        (6, 3, 0, 1, [2]),
        (6, 3, 0, 2, [1, 2]),
        (6, 3, 1, 1, [3]),
        (6, 3, 1, 2, [3, 4]),
        (6, 2, 0, 1, [1]),  # three blocks: the middle one keeps its top
        (6, 2, 1, 1, [2]),
        (6, 2, 2, 1, [4]),
        (8, 2, 1, 1, [3]),  # four blocks: the two upper ones fill from the bottom
        (8, 2, 2, 1, [4]),
        (8, 4, 0, 3, [1, 2, 3]),
    ],
)
def test_a_short_group_sits_next_to_the_middle(
    slots: int, block: int, number: int, size: int, expected: list[int]
) -> None:
    profile = BASE.model_copy(update={"slots": slots, "block": block})
    assert group_slots(number, size, profile) == expected


def test_a_lone_line_before_a_break_and_at_the_end_sits_next_to_the_other_block() -> None:
    # the lone line of the song's last group is in the top block: slot 1, under no empty row
    ending = place(STEADY[:5], 7.5, BLOCKS)
    assert [p.slot for p in ending] == [0, 1, 2, 3, 1]
    # a lone line in the lower block before a break keeps the top of its block (slot 2); after the
    # break the first group goes into the top block, its lone last line next to the lower block
    times = lines((10, 11), (11.5, 12.5), (13, 14), (20, 21), (21.5, 22.5), (23, 24))
    assert [p.slot for p in place(times, 7.5, BLOCKS)] == [0, 1, 2, 0, 1, 2]
    # a lone line in the top block right before a break
    top = lines((10, 11), (11.5, 12.5), (13, 14), (14.5, 15), (16, 17), (30, 31), (31.5, 32))
    assert [p.slot for p in place(top, 7.5, BLOCKS)] == [0, 1, 2, 3, 1, 0, 1]
    # after a break a lone first group goes into the top block (slot 1, rule 22 counts the block)
    lone = lines((10, 11), (11.5, 12.5), (20, 21))
    assert [p.slot for p in place(lone, 7.5, BLOCKS)] == [0, 1, 1]


def test_more_parts_than_a_block_holds_fill_blocks_of_their_own() -> None:
    triples = BLOCKS.model_copy(update={"slots": 6, "block": 3})
    assert groups(STEADY, [0, 0, 1, 2, 0, 0], triples) == [0, 1, 1, 1, 2, 2]
    assert groups(STEADY[:5], [0, 1, 2, 0, 0], BLOCKS) == [0, 0, 1, 2, 2]  # 3 parts, blocks of 2


def test_a_group_is_split_by_a_restart_after_a_long_gap() -> None:
    times = lines((10, 11), (11.5, 12.5), (13, 14), (20, 21), (21.5, 22.5))
    assert groups(times, [0] * 5, BLOCKS) == [0, 0, 1, 2, 2]  # an odd line before the gap


def test_both_lines_of_a_pair_appear_together_and_go_together() -> None:
    placed = place(STEADY, 7.5, BLOCKS)
    assert [p.slot for p in placed] == [0, 1, 2, 3, 0, 1]
    assert [p.show for p in placed[:2]] == [7.5, 7.5]
    assert placed[2].show == placed[3].show == pytest.approx(11.0)  # 3 s before it is sung
    # the first block is free once the next group has started plus replace_after: 14.33, but the
    # lead-in maximum keeps the group back until 18 - 3
    assert placed[4].show == placed[5].show == pytest.approx(15.0)
    assert placed[0].hide == placed[1].hide == placed[4].show
    assert placed[2].hide == placed[3].hide  # the last pair goes together after the song


def test_a_group_goes_into_the_block_whose_lines_ended_first() -> None:
    # the second pair is sung long, so the third group takes the first block again
    times = lines((10, 11), (11.5, 12.5), (13, 20), (20.5, 22), (23, 24), (24.5, 25))
    placed = place(times, 7.5, BLOCKS)
    assert [p.slot for p in placed] == [0, 1, 2, 3, 0, 1]
    # with the first pair sung long instead, the second block is the one that ended first
    other = lines((10, 11), (11.5, 24), (12, 13), (13.5, 14), (24.5, 25.5), (26, 27))
    assert [p.slot for p in place(other, 7.5, BLOCKS)] == [0, 1, 2, 3, 2, 3]


def test_the_block_is_replaced_when_the_next_group_has_started() -> None:
    placed = place(STEADY, 7.5, BLOCKS)
    start_of_next = STEADY[2].start + BLOCKS.clear.replace_after
    assert placed[4].show >= start_of_next - 1e-9
    assert placed[4].show >= STEADY[1].end  # and the pair is sung to its end


def test_after_a_long_gap_the_grouping_starts_again_in_the_top_block() -> None:
    times = lines((10, 11), (11.5, 12.5), (13, 14), (20, 21), (21.5, 22.5))
    placed = place(times, 7.5, BLOCKS)
    assert [p.slot for p in placed] == [0, 1, 2, 0, 1]
    cleared = clearing(14, 20, BLOCKS)
    assert placed[3].show == placed[4].show >= cleared - 1e-9
    assert all(p.hide <= cleared + 1e-9 for p in placed[:3])  # the lone line goes with the rest


def test_the_lead_in_maximum_counts_for_the_first_line_of_a_group_only() -> None:
    # the second line of the first pair is sung 5 s after the first appears: more than lead_in.max
    times = lines((10, 14), (14.5, 15), (17, 18), (18.5, 19))
    placed = place(times, 7.5, BLOCKS)
    assert times[1].start - placed[1].show > BLOCKS.lead_in.max
    assert placed[0].show == placed[1].show


def test_with_one_line_per_block_the_placement_is_the_one_of_today() -> None:
    explicit = BASE.model_copy(update={"slots": 4, "block": 1})
    plain = BASE.model_copy(update={"slots": 4})
    assert place(STEADY, 7.5, explicit) == place(STEADY, 7.5, plain)
    placed = place(STEADY, 7.5, plain)
    assert [p.slot for p in placed] == [0, 1, 2, 3, 0, 1]
    assert placed[0].hide != placed[1].hide  # one by one: each goes when its own slot is refilled


@settings(max_examples=150, deadline=None)
@given(
    times=sung(),
    shape=st.sampled_from([(4, 2), (6, 2), (6, 3)]),
    hold=st.sampled_from([None, 0.0, 4.5]),
    data=st.data(),
)
def test_blocks_turn_together_and_restart_at_the_top(
    times: list[Times], shape: tuple[int, int], hold: float | None, data: st.DataObject
) -> None:
    slots, block = shape
    profile = BASE.model_copy(update={"slots": slots, "block": block})
    profile = with_hold(profile, hold)
    parts = drawn_parts(times, data)
    placed = place(times, 1.0, profile, parts)
    numbers = groups(times, parts, profile)
    for number in set(numbers):
        group = [p for p, n in zip(placed, numbers, strict=True) if n == number]
        assert len({p.show for p in group}) == 1  # they appear together
        assert len({p.hide for p in group}) == 1  # and go together
        assert [p.slot for p in group] == list(range(group[0].slot, group[0].slot + len(group)))
        assert len(group) <= block
        assert [p.slot for p in group] == group_slots(group[0].slot // block, len(group), profile)
    hides = [p.hide for p in placed]
    assert hides == sorted(hides)
    ended = 0.0
    for index, (line, here) in enumerate(zip(times, placed, strict=True)):
        assert here.show <= line.start + 1e-9 and here.hide >= line.end - 1e-9
        if index and round(line.start - ended, 3) >= profile.breaks.clear_after:
            assert here.show >= clearing(ended, line.start, profile) - 1e-9
            assert here.slot // block == 0 or numbers[index] == numbers[index - 1]
            assert all(p.hide <= here.show + 1e-9 for p in placed[:index])
        ended = max(ended, line.end)


def test_an_empty_block_comes_before_one_whose_lines_were_sung() -> None:
    # lines sung under a second into the song: the empty block still wins over the sung one
    times = lines((0.1, 0.3), (0.4, 0.6), (0.7, 0.9), (1.0, 1.2))
    assert [p.slot for p in place(times, 0.0, BLOCKS)] == [0, 1, 2, 3]


def test_the_block_waits_for_the_next_group_to_start_plus_replace_after() -> None:
    # close pairs: neither lead_in.max nor the singing holds the third pair back, the turn does
    times = lines((10, 10.5), (10.6, 11), (11.1, 11.5), (11.6, 12), (14.1, 14.5), (14.6, 15))
    placed = place(times, 7.5, BLOCKS)
    turn = times[2].start + BLOCKS.clear.replace_after
    assert placed[4].show == placed[5].show == pytest.approx(turn)


def test_a_group_never_appears_before_the_group_before_it() -> None:
    # the second pair could appear lead_in.max before it is sung, 7.4, but the first pair only
    # appears at 7.5, after the title
    times = lines((10, 10.2), (10.25, 10.35), (10.4, 11), (11.1, 12))
    placed = place(times, 7.5, BLOCKS)
    assert [p.show for p in placed] == [7.5] * 4


# two lines held long fill both blocks: the third pair turns line by line (ADR-0038)
HELD = lines((10, 30), (11, 12), (13, 30), (14, 15), (16, 17), (18, 19), (31, 32), (32.5, 33))


def test_a_group_turns_line_by_line_when_no_block_is_free() -> None:
    placed = place(HELD, 7.5, BLOCKS)
    assert [p.slot for p in placed[:6]] == [0, 1, 2, 3, 1, 3]  # the slots that ended first
    assert placed[4].show != placed[5].show  # one by one, each when its slot is free
    assert placed[1].hide == placed[4].show and placed[3].hide == placed[5].show
    assert placed[0].hide >= HELD[0].end and placed[2].hide >= HELD[2].end  # sung to the end
    # afterwards the blocks go on: the next pair takes the block that ended first, all of it
    assert [p.slot for p in placed[6:]] == [0, 1]
    assert placed[6].show == placed[7].show
    assert placed[0].hide == placed[4].hide == placed[6].show


def test_falling_back_needs_a_line_sung_in_every_block() -> None:
    assert falls_back([30, 12, 30, 15], 2, 16)  # a held line in both blocks
    assert not falls_back([30, 12, 14, 15], 2, 16)  # the second block is sung
    assert not falls_back([30, 12, 16, 15], 2, 16)  # free the moment the group starts
    assert not falls_back([-1.0, -1.0, 30, 15], 2, 16)  # an empty block


@st.composite
def held(draw: st.DrawFn) -> list[Times]:
    """Lines that may be held long, over the lines after them (three or more sung at once)."""
    clock = 5.0
    found: list[Times] = []
    for _ in range(draw(st.integers(1, 12))):
        clock += draw(st.sampled_from([0.5, 1.0, 2.0, 6.0]))
        found.append(Times(clock, clock + draw(st.sampled_from([0.4, 1.0, 3.0, 12.0]))))
    return found


@settings(max_examples=150, deadline=None)
@given(times=held(), shape=st.sampled_from([(4, 2), (6, 2), (6, 3)]))
def test_a_group_splits_only_when_no_block_is_free(
    times: list[Times], shape: tuple[int, int]
) -> None:
    slots, block = shape
    profile = BASE.model_copy(update={"slots": slots, "block": block})
    placed = place(times, 1.0, profile)
    numbers = groups(times, [0] * len(times), profile)

    def sung_on_screen(at: float, before: int) -> set[int]:  # the blocks with a line sung at ``at``
        return {
            placed[j].slot // block
            for j in range(before)
            if times[j].end > at and placed[j].hide > at
        }

    for number in set(numbers):
        members = [i for i, n in enumerate(numbers) if n == number]
        group = [placed[i] for i in members]
        together = len({p.show for p in group}) == 1 and [p.slot for p in group] == list(
            range(group[0].slot, group[0].slot + len(group))
        )
        start = times[members[0]].start
        assert together or len(sung_on_screen(start, members[0])) == slots // block
    for k, here in enumerate(placed):  # a line takes a slot only when the line in it has gone
        earlier = [j for j in range(k) if placed[j].slot == here.slot]
        if earlier and placed[earlier[-1]].hide > here.show + 1e-9:
            busy = {placed[j].slot for j in range(k) if times[j].end > here.show}
            assert len(busy) == slots  # unless every slot holds a line still being sung


def test_a_group_turning_line_by_line_may_find_an_empty_slot() -> None:
    # a lyric line split into three: its last part is alone in the second block, so as the held
    # lines leave no block free, the next line takes the empty slot under it
    times = lines((10, 30), (11, 12), (13, 14), (14.5, 15), (15.5, 30), (17, 18), (19, 20))
    placed = place(times, 7.5, BLOCKS, [0, 0, 0, 1, 2, 0, 0])
    assert [p.slot for p in placed] == [0, 1, 2, 3, 2, 3, 1]
