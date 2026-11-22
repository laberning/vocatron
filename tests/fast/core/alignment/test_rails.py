"""Stage 1: checking the line times of an .lrc against the singing."""

from itertools import combinations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.alignment.rails import (
    MARGIN,
    REACH,
    SLOT_REACH,
    check_rails,
    crowded_lines,
    in_order,
    line_windows,
    order_notes,
    voice_windows,
)
from vocatron.core.lyrics.document import Voice

HINTS = [10.0, 14.0, 19.0, 25.0, 31.0, 36.0]


def test_hints_that_match_up_to_one_offset_are_shifted_by_it() -> None:
    check = check_rails([h + 1.2 for h in HINTS], HINTS)
    assert check.rails == "shifted"
    assert check.offset == pytest.approx(1.2)
    assert check.compared == 6
    assert check.spread == pytest.approx(0.0)
    assert check.near == 1.0


def test_a_few_outliers_do_not_spoil_a_consistent_offset() -> None:
    found = [h + 0.5 for h in HINTS]
    found[2] += 4.0
    check = check_rails(found, HINTS)
    assert (check.rails, round(check.offset, 2)) == ("shifted", 0.5)


def test_hints_that_disagree_with_the_singing_are_ignored() -> None:
    found = [h + d for h, d in zip(HINTS, [0.0, 3.0, -2.0, 6.0, 0.5, -4.0], strict=True)]
    assert check_rails(found, HINTS).rails == "ignored"


def test_too_few_near_lines_are_ignored_even_with_a_small_spread() -> None:
    hints = [*HINTS, 40.0]
    found = [h + d for h, d in zip(hints, [0.0, 0.0, 0.0, 0.0, 9.0, 9.0, 9.0], strict=True)]
    check = check_rails(found, hints)
    assert check.spread == 0.0  # the median line is on the offset ...
    assert check.near == pytest.approx(4 / 7)  # ... but fewer than 60 % of the lines are
    assert check.rails == "ignored"


def test_the_spread_limit_is_a_third_of_a_second() -> None:
    wobble = [0.0, 0.4, -0.4, 0.4, -0.4, 0.0]  # median deviation 0.4 s
    assert (
        check_rails([h + w for h, w in zip(HINTS, wobble, strict=True)], HINTS).rails == "ignored"
    )


def test_too_few_lines_with_times_say_nothing() -> None:
    check = check_rails([1.0, None, 3.0, None], [1.0, 2.0, None, None])
    assert (check.rails, check.compared) == ("none", 1)
    assert check_rails([], []).rails == "none"


def test_lines_without_a_hint_or_a_found_start_are_left_out_of_the_comparison() -> None:
    found: list[float | None] = [10.0, None, 19.0, 25.0, 31.0]
    hints: list[float | None] = [10.0, 14.0, 19.0, None, 31.0]
    check = check_rails(found, hints)
    assert (check.rails, check.compared) == ("shifted", 3)


def test_each_line_may_start_a_margin_before_its_corrected_time_and_end_after_the_next() -> None:
    windows = line_windows([10.0, 20.0, 30.0], 1.0, 100.0)
    assert windows == [(11 - MARGIN, 21 + MARGIN), (21 - MARGIN, 31 + MARGIN), (31 - MARGIN, 100.0)]


def test_a_line_without_a_hint_takes_the_window_between_its_neighbours() -> None:
    windows = line_windows([10.0, None, 30.0], 0.0, 100.0)
    assert windows[1] == (10.0 - MARGIN, 30.0 + MARGIN)
    assert line_windows([None, 10.0], 0.0, 50.0)[0] == (0.0, 10.0 + MARGIN)


@given(
    st.lists(st.one_of(st.none(), st.floats(0, 300)), min_size=1, max_size=12),
    st.floats(-5, 5),
    st.floats(0.1, 300),
)
def test_windows_stay_inside_the_audio_and_are_never_empty(
    hints: list[float | None], offset: float, duration: float
) -> None:
    for low, high in line_windows(hints, offset, duration):
        assert 0.0 <= low < high <= duration


def test_a_line_hinted_near_the_end_gets_a_window_ending_at_the_end() -> None:
    assert line_windows([297.0], 5.0, 300.0) == [(300.0 - MARGIN, 300.0)]
    assert line_windows([10.0, 299.0], 0.0, 300.0)[1] == (299.0 - MARGIN, 300.0)


def test_a_line_hinted_before_the_start_gets_a_window_starting_at_zero() -> None:
    assert line_windows([1.0, 10.0], -5.0, 50.0)[0] == (0.0, 10.0 - 5.0 + MARGIN)
    assert line_windows([1.0], -5.0, 50.0) == [(0.0, 50.0)]


def test_the_limits_of_spread_and_near_share_are_inclusive() -> None:
    hints = [10.0, 20.0, 30.0, 40.0, 50.0]
    found = [10.0, 20.0, 30.0, 40.5, 52.0]  # deviations 0, 0, 0, 0.5, 2: three of five near
    check = check_rails(found, hints)
    assert (check.rails, check.near) == ("shifted", 0.8)
    found = [10.0, 20.0, 30.0, 41.0, 52.0]  # 0, 0, 0, 1, 2: exactly 60 % near
    assert check_rails(found, hints).near == 0.6
    assert check_rails(found, hints).rails == "shifted"
    hints = [0.0, 0.0, 0.0, 0.0, 0.0]
    found = [0.0, 0.0, 0.3, 0.6, 0.6]  # spread exactly at its limit
    check = check_rails(found, hints)
    assert (check.rails, check.spread) == ("shifted", 0.3)


def test_a_window_never_starts_before_the_audio() -> None:
    assert line_windows([0.5, 10.0], 0.0, 50.0)[0] == (0.0, 10.0 + MARGIN)


def test_a_song_shorter_than_the_margin_keeps_its_windows_inside_the_audio() -> None:
    assert line_windows([0.5], 0.0, 1.0) == [(0.0, 1.0)]
    assert line_windows([0.8, 0.2], 0.0, 1.0) == [(0.0, 1.0), (0.0, 1.0)]


def test_a_next_line_hinted_before_the_start_is_clamped_to_zero() -> None:
    assert line_windows([5.0, 0.5], -3.0, 50.0) == [(0.5, 2.0), (0.0, 50.0)]


def test_starts_and_hints_of_different_lengths_are_refused() -> None:
    with pytest.raises(ValueError, match="zip"):
        check_rails([h + 1.0 for h in HINTS], [*HINTS, 40.0])


def test_hints_in_order_come_back_unchanged() -> None:
    order = in_order([*HINTS, None], [h + 1 for h in HINTS] + [40.0])
    assert order.kept == [*HINTS, None]
    assert order.dropped == ()


def test_one_late_typo_is_dropped() -> None:
    hints: list[float | None] = [10.0, 14.0, 143.0, 25.0, 31.0]
    order = in_order(hints)
    assert order.kept == [10.0, 14.0, None, 25.0, 31.0]
    assert order.dropped == (2,)


def test_of_two_swapped_neighbours_the_one_further_from_its_start_is_dropped() -> None:
    hints: list[float | None] = [10.0, 20.0, 15.0, 30.0]
    near_second = [10.0, 15.0, 16.0, 30.0]  # the singing agrees with line 3 at 15
    assert in_order(hints, near_second).dropped == (1,)
    near_first = [10.0, 20.0, 21.0, 30.0]  # the singing agrees with line 2 at 20
    assert in_order(hints, near_first).dropped == (2,)


def test_equal_deviations_drop_the_later_line() -> None:
    hints: list[float | None] = [10.0, 20.0, 15.0, 30.0]
    assert in_order(hints).dropped == (2,)
    assert in_order(hints, [10.0, 17.5, 17.5, 30.0]).dropped == (2,)


def test_equal_times_are_in_order_and_lines_without_hints_are_ignored() -> None:
    order = in_order([5.0, None, 5.0, 5.0, None, 9.0])
    assert order.dropped == ()
    assert in_order([None, None]).kept == [None, None]


def test_the_note_names_the_line_and_its_time() -> None:
    assert order_notes([10.0, 143.0, 14.0, 20.0]) == [
        "line 2: time 02:23.00 is out of order, skipped"
    ]
    assert order_notes([1.0, 2.0]) == []


def _largest_in_order(hints: list[float | None]) -> int:
    indices = [i for i, h in enumerate(hints) if h is not None]
    for size in range(len(indices), 0, -1):
        for chosen in combinations(indices, size):
            times = [hints[i] or 0.0 for i in chosen]
            if all(a <= b for a, b in zip(times, times[1:], strict=False)):
                return size
    return 0


@given(
    st.lists(st.none() | st.integers(0, 6).map(float), max_size=10),
    st.booleans(),
)
def test_the_kept_hints_are_in_order_and_no_larger_set_exists(
    hints: list[float | None], with_starts: bool
) -> None:
    starts = [float(i) for i in range(len(hints))] if with_starts else None
    order = in_order(hints, starts)
    kept = [h for h in order.kept if h is not None]
    assert kept == sorted(kept)
    assert len(kept) == _largest_in_order(hints)
    assert all(order.kept[i] is None and hints[i] is not None for i in order.dropped)
    assert all(k in (None, h) for k, h in zip(order.kept, hints, strict=True))


def test_the_deviation_from_the_start_is_measured_after_the_median_offset() -> None:
    hints: list[float | None] = [10.0, 20.0, 15.0, 30.0]
    # sung 2 s after the hints; line 3 lies 1 s, line 2 lies 5 s from its start after the offset
    assert in_order(hints, [12.0, 17.0, 18.0, 32.0]).dropped == (1,)
    # line 2 lies 1 s, line 3 lies 5 s from its start after the offset
    assert in_order(hints, [12.0, 23.0, 12.0, 32.0]).dropped == (2,)


def test_a_line_without_a_found_start_counts_as_no_deviation() -> None:
    hints: list[float | None] = [10.0, 20.0, 15.0, 30.0]
    assert in_order(hints, [10.0, None, 15.0, 30.0]).dropped == (2,)  # a tie: the later line
    assert in_order(hints, [10.0, None, 17.0, 30.0]).dropped == (2,)


def test_starts_of_another_length_than_the_hints_are_refused() -> None:
    with pytest.raises(ValueError, match="zip"):
        in_order([10.0, 20.0, 15.0], [10.0, 20.0])


# ---------------------------------------------------------------- two voices (ADR-0052)


@given(
    st.lists(st.one_of(st.none(), st.floats(0, 200)), min_size=1, max_size=12),
    st.floats(-2, 3),
)
def test_with_one_voice_and_no_shared_time_the_windows_are_those_of_before(
    hints: list[float | None], offset: float
) -> None:
    unique = [None if h is None else h + 0.001 * i for i, h in enumerate(hints)]
    assert voice_windows(unique, [1] * len(unique), offset, 240.0) == line_windows(
        unique, offset, 240.0
    )


def test_each_voice_has_windows_of_its_own_lines() -> None:
    hints = [10.0, 12.0, 20.0, 22.0]
    windows = voice_windows(hints, [1, 2, 1, 2], 0.0, 100.0)
    assert windows[0] == (10.0 - MARGIN, 20.0 + MARGIN)  # the first voice ends at its next line
    assert windows[1] == (12.0 - MARGIN, 20.0 + REACH)  # the second may run past the next time


def test_a_lone_second_voice_line_does_not_search_the_rest_of_the_song() -> None:
    windows = voice_windows([10.0, 12.0, 50.0], [1, 2, 1], 0.0, 100.0)
    assert windows[1] == (12.0 - MARGIN, 50.0 + REACH)  # not 100: its next later line limits it
    assert windows[1][1] < 100.0


def test_lines_with_one_time_end_shortly_after_the_next_time() -> None:
    hints = [10.0, 10.0, 17.0, 25.0]
    windows = voice_windows(hints, [1, 2, 1, 1], 0.5, 100.0)
    assert windows[0][1] == pytest.approx(17.5 + SLOT_REACH)
    assert windows[1][1] == pytest.approx(17.5 + SLOT_REACH)
    assert windows[2] == (17.5 - MARGIN, 25.5 + MARGIN)  # a line of its own: as before


def test_a_second_voice_window_is_never_empty() -> None:
    low, high = voice_windows([10.0, 10.5], [1, 2], 0.0, 100.0)[1]
    assert high - low >= MARGIN


def test_a_second_voice_line_at_the_very_start_reaches_past_the_next_time() -> None:
    windows = voice_windows([0.0, 0.5, 20.0], [2, 1, 1], 0.0, 100.0)
    assert windows[0] == (0.0, 0.5 + REACH)  # the next time is the first voice's at 0.5


def test_crowded_lines_are_the_lines_that_overlap_a_window_of_the_other_voice() -> None:
    windows = [(0.0, 10.0), (8.0, 20.0), (9.0, 15.0), (30.0, 40.0), (14.0, 25.0)]
    voices: list[Voice] = [1, 1, 2, 1, 1]
    assert crowded_lines(windows, voices) == {0, 1, 2, 4}  # line 3 is far from the pair


def test_a_second_voice_line_over_a_first_voice_line_is_crowded() -> None:
    assert crowded_lines([(0.0, 5.0), (3.0, 9.0), (20.0, 30.0)], [1, 2, 2]) == {0, 1}


def test_windows_that_only_touch_do_not_overlap_and_one_voice_has_none_crowded() -> None:
    assert crowded_lines([(0.0, 5.0), (5.0, 9.0)], [1, 2]) == frozenset()
    assert crowded_lines([(0.0, 5.0), (1.0, 9.0)], [1, 1]) == frozenset()
    assert crowded_lines([(0.0, 5.0), (1.0, 9.0)], [2, 2]) == frozenset()


@given(
    st.lists(st.tuples(st.floats(0, 100), st.floats(0, 50), st.sampled_from([1, 2])), max_size=8)
)
def test_a_crowded_line_overlaps_some_line_of_the_other_voice(
    rows: list[tuple[float, float, Voice]],
) -> None:
    windows = [(low, low + length) for low, length, _ in rows]
    voices = [v for *_, v in rows]
    for index in crowded_lines(windows, voices):
        assert any(
            voices[j] != voices[index]
            and windows[j][0] < windows[index][1]
            and windows[index][0] < windows[j][1]
            for j in range(len(rows))
        )


def test_windows_and_voices_of_different_length_are_refused() -> None:
    with pytest.raises(ValueError, match="argument"):
        crowded_lines([(0.0, 1.0), (0.5, 2.0)], [1])
    with pytest.raises(ValueError, match="argument"):
        crowded_lines([(0.0, 1.0)], [1, 2])
