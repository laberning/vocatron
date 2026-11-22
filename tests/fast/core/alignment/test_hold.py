"""Stage 1: measured words end where the voice stops (ADR-0013)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.alignment.estimate import Timed
from vocatron.core.alignment.hold import MAX_HOLD_SECONDS, hold_ends
from vocatron.core.alignment.voice import VoiceActivity

SPF = 0.02


def measured(start: float, last_end: float, *, estimated: bool = False) -> Timed:
    """A word of three letters whose last letter ends at ``last_end`` (one frame long)."""
    if estimated:
        return Timed(start, last_end, 0.0, True)
    middle = (start + last_end - SPF) / 2
    letters = ((start, middle), (middle, last_end - SPF), (last_end - SPF, last_end))
    return Timed(start, last_end, 0.9, False, letters)


def voice(*spans: tuple[float, float]) -> VoiceActivity:
    return VoiceActivity(tuple(spans))


def test_an_end_moves_to_the_end_of_the_voiced_run_that_holds_the_last_letter() -> None:
    held = hold_ends([measured(1.0, 1.5)], voice((0.9, 2.5)), SPF)
    assert held.words[0].end == pytest.approx(2.5)
    assert (held.held, held.median_move) == (1, pytest.approx(1.0))
    assert held.words[0].start == 1.0
    assert held.words[0].letters == measured(1.0, 1.5).letters


def test_the_next_word_caps_the_end_also_when_it_is_estimated() -> None:
    for follower in (measured(2.0, 2.4), measured(2.0, 2.4, estimated=True)):
        held = hold_ends([measured(1.0, 1.5), follower], voice((0.9, 3.0)), SPF)
        assert held.words[0].end == pytest.approx(2.0)


def test_the_maximum_hold_caps_the_end() -> None:
    held = hold_ends([measured(1.0, 1.5)], voice((0.9, 20.0)), SPF)
    assert held.words[0].end == pytest.approx(1.5 + MAX_HOLD_SECONDS)


def test_a_last_letter_in_silence_keeps_the_end_even_if_a_voice_starts_just_after() -> None:
    word = measured(1.0, 1.5)
    held = hold_ends([word], voice((0.9, 1.4), (1.6, 2.5)), SPF)
    assert held.words == [word]
    assert (held.held, held.median_move) == (0, 0.0)


def test_an_estimated_word_keeps_its_end() -> None:
    word = measured(1.0, 1.5, estimated=True)
    assert hold_ends([word], voice((0.0, 5.0)), SPF).words == [word]


def test_a_run_that_ends_inside_the_last_frame_still_holds_the_letter() -> None:
    held = hold_ends([measured(1.0, 1.5)], voice((0.5, 1.5)), SPF)
    assert held.words[0].end == pytest.approx(1.5)
    assert held.held == 0


def test_the_middle_of_the_last_frame_decides_whether_the_last_letter_is_voiced() -> None:
    word = measured(1.0, 1.5)
    assert hold_ends([word], voice((1.5 - 0.4 * SPF, 3.0)), SPF).words == [word]
    held = hold_ends([word], voice((1.5 - 0.6 * SPF, 3.0)), SPF)
    assert held.words[0].end == pytest.approx(3.0)


def test_a_run_holds_its_start_but_not_its_end() -> None:
    middle = 1.5 - SPF / 2
    held = hold_ends([measured(1.0, 1.5)], voice((0.5, middle), (middle, 2.5)), SPF)
    assert held.words[0].end == pytest.approx(2.5)


def test_a_measured_word_without_letters_keeps_its_end() -> None:
    word = Timed(1.0, 1.5, 0.9, False)
    assert hold_ends([word], voice((0.0, 5.0)), SPF).words == [word]


def test_the_median_move_is_over_the_words_that_moved() -> None:
    words = [measured(1.0, 1.1), measured(1.5, 1.6), measured(3.0, 3.1), measured(5.0, 5.1)]
    held = hold_ends(words, voice((0.9, 1.3), (1.4, 1.9), (2.0, 2.2)), SPF)
    assert held.held == 2
    assert held.median_move == pytest.approx((0.2 + 0.3) / 2)


@st.composite
def songs(draw: st.DrawFn) -> tuple[list[Timed], VoiceActivity]:
    cursor = 0.0
    words: list[Timed] = []
    for _ in range(draw(st.integers(1, 8))):
        start = cursor + draw(st.floats(0.0, 1.0))
        end = start + draw(st.floats(0.04, 1.0))
        words.append(measured(start, end, estimated=draw(st.booleans())))
        cursor = end
    spans: list[tuple[float, float]] = []
    cursor = 0.0
    for _ in range(draw(st.integers(0, 6))):
        begin = cursor + draw(st.floats(0.0, 2.0))
        cursor = begin + draw(st.floats(0.1, 8.0))
        spans.append((begin, cursor))
    return words, VoiceActivity(tuple(spans))


@given(songs())
def test_starts_never_change_ends_only_move_later_and_words_never_overlap(
    song: tuple[list[Timed], VoiceActivity],
) -> None:
    words, activity = song
    held = hold_ends(words, activity, SPF).words
    assert len(held) == len(words)
    for before, after, follower in zip(words, held, [*held[1:], None], strict=True):
        assert after.start == before.start
        assert after.end >= before.end
        assert after.letters == before.letters
        assert after.estimated == before.estimated
        if before.estimated:
            assert after == before
        else:
            assert after.end <= before.letters[-1][1] + MAX_HOLD_SECONDS + 1e-9
        if follower is not None:
            assert after.end <= follower.start + 1e-9
