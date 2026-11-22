"""Stage 1: lines the model did not hear are placed at their line time (ADR-0027)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.alignment.estimate import LETTER_SECONDS, Timed
from vocatron.core.alignment.unheard import (
    AFTER_PREVIOUS_SECONDS,
    LATE_SECONDS,
    SNAP_SECONDS,
    UnheardLine,
    forget_late,
    place_unheard,
)
from vocatron.core.alignment.voice import VoiceActivity


def measured(start: float, end: float) -> Timed:
    return Timed(start, end, 0.9, False, ((start, end),))


def guessed(start: float, end: float) -> Timed:
    return Timed(start, end, 0.0, True)


def voiced(*spans: tuple[float, float]) -> VoiceActivity:
    return VoiceActivity(spans)


def test_an_unheard_line_starts_at_its_hint_plus_the_offset_not_the_models_place() -> None:
    words = [measured(1.0, 1.5), guessed(8.0, 8.5), guessed(8.5, 9.0), measured(20.0, 20.5)]
    placed = place_unheard(words, [0, 1, 1, 2], [3, 4, 4], [1.0, 10.0, 20.0], 0.5, None)
    assert placed.words[1].start == pytest.approx(10.5)
    assert placed.words[2].start == pytest.approx(placed.words[1].end)
    assert placed.lines == (UnheardLine(1, 10.5, min(20.5, 10.5 + 8 * LETTER_SECONDS)),)


def test_the_letters_are_shared_over_the_letters_times_the_letter_length_without_voice() -> None:
    words = [guessed(5.0, 5.1), guessed(5.1, 5.2)]
    placed = place_unheard(words, [0, 0], [1, 3], [10.0], 0.0, None)
    edges = [10.0, 10.0 + LETTER_SECONDS, 10.0 + 4 * LETTER_SECONDS]
    assert [w.start for w in placed.words] == pytest.approx(edges[:2])
    assert [w.end for w in placed.words] == pytest.approx(edges[1:])


def test_the_words_follow_the_voice_up_to_the_next_line() -> None:
    def five(start: float) -> Timed:  # 5 letters in 0.5 s: 0.1 s per letter
        letters = tuple((start + i * 0.1, start + i * 0.1 + 0.1) for i in range(5))
        return Timed(start, start + 0.5, 0.9, False, letters)

    words = [five(0.0), guessed(7.0, 7.1), five(20.0)]
    voice = voiced((10.2, 12.0))
    placed = place_unheard(words, [0, 1, 2], [5, 2, 3], [0.0, 10.0, 20.0], 0.0, voice)
    assert placed.words[1].start == pytest.approx(10.2)
    assert placed.words[1].end == pytest.approx(10.4)


def test_a_voice_that_starts_far_after_the_rail_is_not_followed() -> None:
    words = [guessed(7.0, 7.1), measured(20.0, 20.5)]
    voice = voiced((10.0 + SNAP_SECONDS + 1.0, 15.0))
    placed = place_unheard(words, [0, 1], [2, 3], [10.0, 20.0], 0.0, voice)
    assert placed.words[0].start == pytest.approx(10.0)


def test_a_measured_word_directly_before_pushes_the_start_and_is_cut() -> None:
    words = [measured(9.0, 11.0), guessed(30.0, 30.1), measured(40.0, 40.5)]
    placed = place_unheard(words, [0, 1, 2], [3, 3, 3], [8.0, 9.0, 40.0], 0.0, None)
    assert placed.words[1].start == pytest.approx(9.0 + AFTER_PREVIOUS_SECONDS)
    assert placed.words[0].end <= placed.words[1].start


def test_the_letters_of_a_cut_measured_word_end_with_it() -> None:
    letters = ((9.0, 9.2), (9.2, 9.6), (9.6, 10.0))
    words = [Timed(9.0, 10.0, 0.9, False, letters), guessed(30.0, 30.1)]
    placed = place_unheard(words, [0, 1], [3, 3], [None, 9.4], 0.0, None)
    assert placed.words[0].end == pytest.approx(9.4)
    assert placed.words[0].letters == ((9.0, 9.2), (9.2, 9.4), (9.4, 9.4))


def test_an_estimated_word_directly_before_does_not_push_the_start() -> None:
    words = [guessed(1.0, 9.5), guessed(30.0, 30.1)]
    placed = place_unheard(words, [0, 1], [3, 3], [None, 5.0], 0.0, None)
    assert placed.words[1].start == pytest.approx(5.0)
    assert placed.words[0].end == pytest.approx(5.0)  # cut: it overlapped the placed line


def test_lines_without_a_hint_and_lines_with_a_heard_word_are_unchanged() -> None:
    words = [guessed(1.0, 2.0), guessed(3.0, 3.5), measured(4.0, 4.5), measured(6.0, 7.0)]
    placed = place_unheard(words, [0, 1, 1, 2], [2, 2, 2, 2], [None, 50.0, 60.0], 0.0, None)
    assert placed.words == words
    assert placed.lines == ()


def test_the_last_line_is_placed_too() -> None:
    words = [measured(0.0, 1.0), guessed(2.0, 2.5)]
    placed = place_unheard(words, [0, 1], [3, 2], [0.0, 30.0], 0.0, None)
    assert placed.words[1].start == pytest.approx(30.0)
    assert placed.lines[0].stop == pytest.approx(30.0 + 2 * LETTER_SECONDS)


@given(
    st.lists(
        st.tuples(
            st.lists(st.booleans(), min_size=1, max_size=4),
            st.integers(1, 6),
            st.one_of(st.none(), st.floats(-3.0, 3.0)),
        ),
        min_size=1,
        max_size=8,
    ),
    st.floats(-1.0, 1.0),
    st.lists(st.tuples(st.floats(0.0, 12.0), st.floats(0.05, 3.0)), max_size=4),
)
def test_placement_keeps_heard_words_and_the_order_of_the_words(
    plan: list[tuple[list[bool], int, float | None]],
    offset: float,
    spans: list[tuple[float, float]],
) -> None:
    """Measured words never change but for a cut end; words stay in order and never overlap."""
    words: list[Timed] = []
    lines: list[int] = []
    weights: list[int] = []
    hints: list[float | None] = []
    cursor = 0.0
    for line, (heard, letters, early) in enumerate(plan):
        # in order, as the order check leaves them, but maybe far before or after the line
        earlier = [h for h in hints if h is not None]
        hints.append(None if early is None else max([cursor + early, *earlier]))
        for measure in heard:  # the model's words are in order and do not overlap
            words.append(
                measured(cursor, cursor + 0.4) if measure else guessed(cursor, cursor + 0.4)
            )
            lines.append(line)
            weights.append(letters)
            cursor += 0.5
        cursor += 0.5
    activity = voiced(*((a, a + b) for a, b in spans)) if spans else None
    placed = place_unheard(words, lines, weights, hints, offset, activity)
    for old, new in zip(words, placed.words, strict=True):
        if old.estimated:
            assert new.estimated
        else:
            assert (new.start, new.confidence) == (old.start, old.confidence)
            assert new.end <= old.end
            cut = tuple((min(a, new.end), min(b, new.end)) for a, b in old.letters)
            assert new.letters == cut  # no letter outlasts its word
    for before, after in zip(placed.words, placed.words[1:], strict=False):
        assert before.start <= after.start + 1e-9
        assert before.end <= after.start + 1e-9
    unheard = {
        line for line, (heard, _, hint) in enumerate(plan) if hint is not None and not any(heard)
    }
    assert {found.line for found in placed.lines} == unheard
    for found in placed.lines:
        first = lines.index(found.line)
        start = placed.words[first].start
        sure = [w.start for w in words[:first] if not w.estimated]
        floor = max([found.rail, *(s + AFTER_PREVIOUS_SECONDS for s in sure[-1:])])
        following = [w.start for w, n in zip(placed.words, lines, strict=True) if n > found.line]
        target = min([floor, *following[:1]])
        if activity is None:
            assert start == pytest.approx(target)
        else:  # a voice start up to SNAP_SECONDS later is followed, never past the next line
            onsets = [a for a, _ in activity.spans if target < a <= target + SNAP_SECONDS + 1e-9]
            assert start == pytest.approx(target) or start in onsets
            assert all(start <= f + 1e-9 for f in following[:1])
        assert found.stop >= found.rail
    for old, new, line in zip(words, placed.words, lines, strict=True):
        if line not in unheard and old.estimated:
            assert new.start <= old.start and new.end <= old.end


def test_the_window_of_a_line_ends_at_the_next_rail_that_exists() -> None:
    words = [guessed(1.0, 1.1), guessed(2.0, 2.1), guessed(3.0, 3.1)]
    placed = place_unheard(words, [0, 1, 2], [200, 1, 1], [10.0, None, 12.0], 0.5, None)
    assert placed.lines[0] == UnheardLine(0, 10.5, 12.5)


def test_a_voice_start_only_just_inside_the_snap_distance_is_followed() -> None:
    words = [guessed(1.0, 1.1), measured(20.0, 20.5)]
    voice = voiced((10.0 + SNAP_SECONDS - 0.01, 15.0))
    placed = place_unheard(words, [0, 1], [2, 3], [10.0, 20.0], 0.0, voice)
    assert placed.words[0].start == pytest.approx(10.0 + SNAP_SECONDS - 0.01)


def test_an_estimated_word_between_does_not_lower_the_floor_of_a_measured_word() -> None:
    words = [measured(9.0, 9.5), guessed(9.5, 9.6), guessed(30.0, 30.1)]
    placed = place_unheard(words, [0, 0, 1], [3, 3, 3], [None, 5.0], 0.0, None)
    assert placed.words[2].start == pytest.approx(9.0 + AFTER_PREVIOUS_SECONDS)
    assert placed.words[0].start == 9.0
    assert placed.words[0].letters == ((9.0, 9.0 + AFTER_PREVIOUS_SECONDS),)
    assert placed.words[1].end <= placed.words[2].start


def test_the_last_line_has_room_beyond_its_start_for_a_long_voice() -> None:
    words = [measured(0.0, 1.0), guessed(2.0, 2.5)]
    voice = voiced((30.0, 60.0))
    placed = place_unheard(words, [0, 1], [3, 200], [0.0, 30.0], 0.0, voice)
    assert placed.words[1].end > 30.0 + 0.5


def test_the_seconds_per_letter_come_from_the_letters_not_the_held_end() -> None:
    letters = tuple((i * 0.1, i * 0.1 + 0.1) for i in range(5))
    held = Timed(0.0, 9.0, 0.9, False, letters)  # held to 9 s, the letters take 0.5 s
    words = [held, guessed(1.0, 1.1)]
    placed = place_unheard(words, [0, 1], [5, 3], [0.0, 20.0], 0.0, voiced((20.0, 30.0)))
    assert placed.words[1].end == pytest.approx(20.0 + 3 * 0.1)


def test_the_window_stops_at_the_next_rail_not_the_one_after() -> None:
    words = [guessed(1.0, 1.1), guessed(2.0, 2.1), guessed(3.0, 3.1)]
    placed = place_unheard(words, [0, 1, 2], [200, 1, 1], [10.0, 11.0, 12.0], 0.0, None)
    assert placed.lines[0].stop == pytest.approx(11.0)


def test_a_rail_after_the_next_lines_start_does_not_reorder_the_words() -> None:
    words = [guessed(1.0, 1.1), measured(10.0, 10.5)]
    placed = place_unheard(words, [0, 1], [2, 3], [10.8, 11.0], 0.0, None)
    assert placed.words[0].start == pytest.approx(10.0)
    assert placed.words[0].end <= placed.words[1].start
    assert placed.words[1] == words[1]


def test_estimated_words_after_the_new_start_are_moved_to_it() -> None:
    words = [measured(1.0, 1.5), guessed(6.0, 7.0), guessed(30.0, 30.1)]
    placed = place_unheard(words, [0, 0, 1], [3, 3, 3], [None, 5.0], 0.0, None)
    assert placed.words[0] == words[0]
    assert (placed.words[1].start, placed.words[1].end) == (5.0, 5.0)
    assert placed.words[2].start == pytest.approx(5.0)  # the rail lies after the floor


def test_the_first_voice_start_after_the_rail_is_taken_not_the_last() -> None:
    words = [guessed(7.0, 7.1), measured(20.0, 20.5)]
    voice = voiced((10.2, 11.0), (12.0, 15.0))
    placed = place_unheard(words, [0, 1], [2, 3], [10.0, 20.0], 0.0, voice)
    assert placed.words[0].start == pytest.approx(10.2)


def test_a_voice_start_exactly_at_the_snap_distance_is_followed() -> None:
    words = [guessed(7.0, 7.1), measured(20.0, 20.5)]
    voice = voiced((10.0 + SNAP_SECONDS, 15.0))
    placed = place_unheard(words, [0, 1], [2, 3], [10.0, 20.0], 0.0, voice)
    assert placed.words[0].start == pytest.approx(10.0 + SNAP_SECONDS)


def test_a_line_that_starts_long_after_its_rail_becomes_unheard() -> None:
    words = [measured(1.0, 2.0), measured(13.0, 13.5), measured(13.5, 14.0), measured(20.0, 21.0)]
    lines = [0, 1, 1, 2]
    out = forget_late(
        words, lines, [1.0, 10.0, 20.0], 0.5, {0, 1, 2}
    )  # line 1: 13.0 is 2.5 s after 10.5
    assert [w.estimated for w in out] == [False, True, True, False]
    assert [w.letters for w in out[1:3]] == [(), ()]
    assert [(w.start, w.end) for w in out] == [
        (w.start, w.end) for w in words
    ]  # place_unheard moves


def test_a_late_line_after_a_line_of_two_words_is_found_too() -> None:
    words = [measured(1.0, 1.5), measured(1.5, 2.0), measured(13.0, 13.5)]
    out = forget_late(words, [0, 0, 1], [1.0, 10.0], 0.0, {0, 1})
    assert [w.estimated for w in out] == [False, False, True]


def test_a_line_that_starts_exactly_at_the_limit_or_has_no_hint_is_kept() -> None:
    words = [measured(10.0 + LATE_SECONDS, 12.0), measured(20.0, 21.0), guessed(30.0, 31.0)]
    assert forget_late(words, [0, 1, 2], [9.0, None, 5.0], 1.0, {0, 1, 2}) == words
    # line 0 starts exactly LATE_SECONDS after its rail; line 1 has no hint; line 2 is guessed
    assert forget_late(words[:1], [0], [9.0], 1.0, {0}) == words[:1]
    assert forget_late(words[:1], [0], [8.99], 1.0, {0})[0].estimated


def test_every_line_is_looked_at_once_by_its_first_word() -> None:
    words = [measured(10.0, 10.5), measured(30.0, 30.5)]  # the second word is late, the line is not
    assert forget_late(words, [0, 0], [10.0], 0.0, {0}) == words


def test_only_the_judged_lines_are_made_unheard() -> None:
    words = [measured(13.0, 13.5), measured(33.0, 33.5)]  # both start 3 s after their rail
    out = forget_late(words, [0, 1], [10.0, 30.0], 0.0, {1})
    assert [w.estimated for w in out] == [False, True]
    assert forget_late(words, [0, 1], [10.0, 30.0], 0.0, set()) == words
