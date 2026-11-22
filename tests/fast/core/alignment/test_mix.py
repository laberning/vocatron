"""Stage 1: which frames take the backing vocals' output, on synthetic emissions (ADR-0014)."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from numpy.typing import NDArray

from fakes.acoustic import BLANK, SECONDS_PER_FRAME, VOCABULARY, spike_matrix
from vocatron.core.alignment.chunks import BackingPart, Emissions
from vocatron.core.alignment.estimate import Timed
from vocatron.core.alignment.mix import (
    LEAD_NOT_PLAUSIBLE,
    NO_FRAMES,
    USED,
    mix_backing,
    span_mask,
    words_in,
)

SPF = SECONDS_PER_FRAME
FRAMES = 500
LOUD = -20.0
QUIET = -70.0
LETTER = VOCABULARY.index("a")
OTHER = VOCABULARY.index("b")
LEAD_WORD = (100, 200)  # the lead sings here, confidently
CONFIDENT = [(LEAD_WORD[0] * SPF, LEAD_WORD[1] * SPF)]


def curve(*runs: tuple[int, int]) -> NDArray[np.float32]:
    out = np.full(FRAMES, QUIET, dtype=np.float32)
    for first, stop in runs:
        out[first:stop] = LOUD
    return out


def emissions(
    backing_runs: tuple[tuple[int, int], ...],
    lead_runs: tuple[tuple[int, int], ...] = (LEAD_WORD,),
    lead_letters: tuple[int, ...] = (),
) -> Emissions:
    """Lead blank except at ``lead_letters``; backing spikes ``LETTER`` over ``backing_runs``."""
    lead = spike_matrix(FRAMES, {frame: OTHER for frame in lead_letters})
    heard = spike_matrix(
        FRAMES, {f: LETTER for first, stop in backing_runs for f in range(first, stop)}
    )
    return Emissions(
        lead,
        SPF,
        VOCABULARY,
        curve(*lead_runs),
        BackingPart(heard, curve(*lead_runs), curve(*backing_runs)),
    )


def test_a_backing_word_in_a_silent_lead_takes_the_backings_rows() -> None:
    made = emissions(((300, 360),))
    assert made.backing is not None
    mixed = mix_backing(made, CONFIDENT)
    assert (mixed.reason, mixed.frames) == (USED, 60)
    assert mixed.swapped[300:360].all()
    assert np.array_equal(mixed.log_probs[300:360], made.backing.log_probs[300:360])
    assert np.array_equal(mixed.log_probs[:300], made.log_probs[:300])
    assert np.array_equal(mixed.log_probs[360:], made.log_probs[360:])


def test_the_backing_under_a_confident_lead_word_is_not_taken() -> None:
    mixed = mix_backing(emissions(((120, 180), (300, 360))), CONFIDENT)
    assert mixed.swapped[100:200].sum() == 0
    assert mixed.swapped[300:360].all()


def test_a_letter_the_lead_model_heard_keeps_its_frame() -> None:
    made = emissions(((300, 360),), lead_letters=(330,))
    mixed = mix_backing(made, CONFIDENT)
    assert not mixed.swapped[330]
    assert mixed.frames == 59
    assert np.array_equal(mixed.log_probs[330], made.log_probs[330])


def test_without_a_frame_to_swap_the_lead_matrix_itself_is_returned() -> None:
    made = emissions(())
    mixed = mix_backing(made, CONFIDENT)
    assert (mixed.reason, mixed.frames) == (NO_FRAMES, 0)
    assert mixed.log_probs is made.log_probs


def with_backing_loudness(made: Emissions, loudness: NDArray[np.float32]) -> Emissions:
    assert made.backing is not None
    part = BackingPart(made.backing.log_probs, made.backing.lead_loudness, loudness)
    return Emissions(made.log_probs, SPF, VOCABULARY, made.loudness, part)


def test_a_backing_that_does_not_sound_above_its_own_floor_is_not_taken() -> None:
    made = emissions(((300, 360),))
    quiet = with_backing_loudness(made, np.full(FRAMES, QUIET, np.float32))
    assert mix_backing(quiet, CONFIDENT).reason == NO_FRAMES
    # loud enough for the lead's threshold (-26 dB) but no louder than the backing's own floor
    steady = np.full(FRAMES, -24.0, np.float32)
    steady[300:360] = -20.0
    assert mix_backing(with_backing_loudness(made, steady), CONFIDENT).reason == NO_FRAMES


def test_the_backings_floor_is_its_lower_tenth_percentile() -> None:
    # 50 of 500 frames at -70 dB: the lower 10th percentile is -70, so -24 dB sounds; an
    # interpolated floor (-28.6) would put the threshold above -24
    made = emissions(((0, FRAMES),))
    level = np.full(FRAMES, -24.0, np.float32)
    level[:50] = QUIET
    mixed = mix_backing(with_backing_loudness(made, level), CONFIDENT)
    assert mixed.frames == FRAMES - 50 - (LEAD_WORD[1] - LEAD_WORD[0])


def test_a_backing_exactly_at_the_threshold_does_not_sound() -> None:
    made = emissions(((300, 360),))
    level = np.full(FRAMES, QUIET, np.float32)
    level[300:360] = -26.0  # the lead's threshold: 20th percentile of -20 dB minus 6 dB
    assert mix_backing(with_backing_loudness(made, level), CONFIDENT).reason == NO_FRAMES
    level[300:360] = -25.9
    assert mix_backing(with_backing_loudness(made, level), CONFIDENT).frames == 60


def test_emissions_without_a_fitting_backing_part_are_refused() -> None:
    made = emissions(((300, 360),))
    assert made.backing is not None
    with pytest.raises(ValueError, match="^the emissions carry no backing part$"):
        mix_backing(Emissions(made.log_probs, SPF, VOCABULARY, made.loudness), CONFIDENT)
    short = BackingPart(
        made.backing.log_probs, made.backing.lead_loudness[:-1], made.backing.backing_loudness
    )
    with pytest.raises(ValueError, match="^the backing part does not have the lead's length$"):
        mix_backing(Emissions(made.log_probs, SPF, VOCABULARY, made.loudness, short), CONFIDENT)


def test_span_mask_rounds_to_frames_and_clamps_at_the_song_start() -> None:
    mask = span_mask([(0.0, 2 * SPF), (5 * SPF, 6 * SPF)], SPF, 8)
    assert mask.tolist() == [True, True, False, False, False, True, False, False]
    assert not span_mask([(-3 * SPF, -SPF)], SPF, 8).any()


def test_a_lead_whose_voice_is_not_plausible_is_left_alone() -> None:
    made = emissions(((300, 360),), lead_runs=((100, 120),))  # 0.4 s of confident singing
    mixed = mix_backing(made, [(2.0, 2.4)])
    assert (mixed.reason, mixed.frames) == (LEAD_NOT_PLAUSIBLE, 0)
    assert mixed.log_probs is made.log_probs


def test_a_run_shorter_than_the_least_voiced_time_is_dropped() -> None:
    assert mix_backing(emissions(((300, 304),)), CONFIDENT).reason == NO_FRAMES
    assert mix_backing(emissions(((300, 306),)), CONFIDENT).frames == 6


def test_a_hole_in_the_backing_is_closed_but_not_in_the_guards() -> None:
    mixed = mix_backing(emissions(((300, 330), (334, 360))), CONFIDENT)
    assert mixed.swapped[300:360].all()  # the 4-frame hole is closed like in the voice


@given(
    runs=st.lists(st.tuples(st.integers(0, 480), st.integers(1, 40)), max_size=5),
    letters=st.lists(st.integers(0, FRAMES - 1), max_size=30),
)
def test_a_mixed_row_is_a_row_of_the_lead_or_the_backing_and_the_guards_hold(
    runs: list[tuple[int, int]], letters: list[int]
) -> None:
    spans = tuple((first, min(first + length, FRAMES)) for first, length in runs)
    made = emissions(spans, lead_letters=tuple(letters))
    assert made.backing is not None
    mixed = mix_backing(made, CONFIDENT)
    own = np.all(mixed.log_probs == made.log_probs, axis=1)
    theirs = np.all(mixed.log_probs == made.backing.log_probs, axis=1)
    assert (own | theirs).all()
    assert not mixed.swapped[list(letters)].any()  # the lead's letters stay
    assert not mixed.swapped[LEAD_WORD[0] : LEAD_WORD[1]].any()  # and so do its confident words
    assert (np.argmax(made.log_probs[mixed.swapped], axis=1) == BLANK).all()
    if mixed.frames == 0:
        assert mixed.log_probs is made.log_probs


def timed(letters: list[tuple[int, int]], estimated: bool = False) -> Timed:
    spans = tuple((a * SPF, b * SPF) for a, b in letters)
    return Timed(spans[0][0], spans[-1][1], 0.9, estimated, () if estimated else spans)


def test_a_word_counts_when_most_of_its_letters_lie_in_swapped_frames() -> None:
    swapped = np.zeros(FRAMES, dtype=np.bool_)
    swapped[300:360] = True
    inside = timed([(300, 310), (310, 320)])
    mostly = timed([(290, 300), (300, 310), (310, 320)])
    half = timed([(290, 300), (300, 310)])
    outside = timed([(100, 110)])
    assert words_in(swapped, [inside, mostly, half, outside], SPF) == 2
    assert words_in(swapped, [timed([(300, 310)], estimated=True)], SPF) == 0


def test_counting_skips_estimated_words_and_counts_letters_of_no_length_as_one_frame() -> None:
    swapped = np.zeros(FRAMES, dtype=np.bool_)
    swapped[300] = True
    point = timed([(300, 300)])  # a letter heard in a single frame
    assert words_in(swapped, [point], SPF) == 1
    swapped[0:3] = True
    swapped[300:310] = True
    early = timed([(0, 3), (10, 12)])  # 3 of 5 letter frames swapped
    spread = timed([(250, 290), (300, 302), (305, 307)])  # 4 of 44
    sung = Timed(300 * SPF, 310 * SPF, 0.9, True, ((300 * SPF, 310 * SPF),))
    assert [words_in(swapped, [word], SPF) for word in (sung, early, spread)] == [0, 1, 0]
    assert words_in(swapped, [sung, early], SPF) == 1  # counting goes on after a skipped word
