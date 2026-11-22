"""Stage 1: where the voice sounds, found from the loudness of the lead vocals (ADR-0012)."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from numpy.typing import NDArray

from vocatron.core.alignment.voice import (
    LOW_CONTRAST,
    NO_LOUDNESS,
    ODD_SHARE,
    TOO_LITTLE_SINGING,
    USED,
    find_voice,
    smooth,
    voiced_runs,
)

SPF = 0.02
FLOOR = -80.0


def song(*parts: tuple[float, float]) -> NDArray[np.float32]:
    """Build a loudness curve from ``(seconds, dB)`` parts."""
    return np.concatenate([np.full(round(s / SPF), db, dtype=np.float32) for s, db in parts])


def flat(spans: tuple[tuple[float, float], ...]) -> list[float]:
    return [t for span in spans for t in span]


def mask(text: str) -> NDArray[np.bool_]:
    return np.array([c == "#" for c in text])


def test_a_clean_song_gets_a_threshold_between_its_floor_and_its_voice() -> None:
    loud = song((2, FLOOR), (3, -20), (2, FLOOR), (3, -20), (2, FLOOR))
    found = find_voice(loud, SPF, [(2.0, 5.0), (7.0, 10.0)])
    assert found.reason == USED
    assert found.activity is not None
    assert FLOOR + 6 <= found.threshold_db <= -20 - 6
    assert flat(found.activity.spans) == pytest.approx(flat(((2.0, 5.0), (7.0, 10.0))))
    assert found.voiced_share == pytest.approx(6 / 12)
    assert found.activity.voiced_fraction(1.0, 3.0) == pytest.approx(0.5)
    assert found.activity.voiced_fraction(5.0, 7.0) == 0.0
    assert found.activity.voiced_fraction(3.0, 3.0) == 0.0


def test_a_flat_lead_stem_full_of_bleed_has_too_little_contrast() -> None:
    loud = song((5, -40), (5, -38), (5, -40))
    found = find_voice(loud, SPF, [(0.0, 15.0)])
    assert (found.activity, found.reason) == (None, LOW_CONTRAST)


def test_near_silence_everywhere_has_too_little_contrast() -> None:
    found = find_voice(song((10, -100)), SPF, [(1.0, 5.0)])
    assert (found.activity, found.reason) == (None, LOW_CONTRAST)


def test_a_very_loud_song_works_like_any_other() -> None:
    loud = song((2, FLOOR), (4, -1), (2, FLOOR), (4, -3))
    found = find_voice(loud, SPF, [(2.0, 6.0), (8.0, 12.0)])
    assert found.reason == USED
    assert found.activity is not None
    assert flat(found.activity.spans) == pytest.approx(flat(((2.0, 6.0), (8.0, 12.0))))


def test_a_quiet_verse_and_a_loud_chorus_are_both_voiced() -> None:
    loud = song((2, FLOOR), (4, -45), (2, FLOOR), (4, -10), (2, FLOOR))
    found = find_voice(loud, SPF, [(2.0, 6.0), (8.0, 12.0)])
    assert found.activity is not None
    assert flat(found.activity.spans) == pytest.approx(flat(((2.0, 6.0), (8.0, 12.0))))


def test_without_enough_confident_singing_the_levels_are_not_known() -> None:
    loud = song((5, FLOOR), (0.6, -20), (5, FLOOR))
    assert find_voice(loud, SPF, [(5.0, 5.6)]).reason == TOO_LITTLE_SINGING
    assert find_voice(loud, SPF, []).reason == TOO_LITTLE_SINGING


def test_a_song_that_is_almost_never_voiced_is_not_plausible() -> None:
    loud = song((50, FLOOR), (1.5, -20), (50, FLOOR))
    found = find_voice(loud, SPF, [(50.0, 51.5)])
    assert (found.activity, found.reason) == (None, ODD_SHARE)
    assert 0.0 < found.voiced_share < 0.1


def test_without_loudness_there_is_no_voice() -> None:
    found = find_voice(np.empty(0, dtype=np.float32), SPF, [(0.0, 1.0)])
    assert (found.activity, found.reason) == (None, NO_LOUDNESS)


def test_confident_words_past_the_end_of_the_song_are_clipped_to_it() -> None:
    loud = song((2, FLOOR), (3, -20))
    found = find_voice(loud, SPF, [(2.0, 9.0), (50.0, 51.0)])
    assert found.reason == USED


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("..####..####..", "..##########.."),  # a hole shorter than 3 frames is closed
        ("..####...####..", "..####...####.."),  # a longer one stays
        ("..#...####..", "......####.."),  # an island shorter than 3 frames is dropped
        ("###...", "###..."),  # holes at the ends are not closed
        ("...###", "...###"),
    ],
)
def test_smoothing_closes_short_holes_and_drops_short_islands(before: str, after: str) -> None:
    result = smooth(mask(before), close_frames=3, min_frames=3)
    assert "".join("#" if v else "." for v in result) == after


def test_runs_are_the_voiced_stretches_in_order() -> None:
    assert voiced_runs(mask("..##.#")) == [(2, 4), (5, 6)]
    assert voiced_runs(mask("....")) == []
    assert voiced_runs(mask("###")) == [(0, 3)]


LEVELS = st.sampled_from([-80.0, -60.0, -30.0, -20.0, -10.0])


@given(
    st.lists(st.tuples(st.integers(1, 80), LEVELS), min_size=1, max_size=25), st.integers(-30, 30)
)
def test_voiced_spans_are_ordered_long_enough_and_independent_of_the_gain(
    parts: list[tuple[int, float]], gain: int
) -> None:
    loud = np.concatenate([np.full(n, db, dtype=np.float32) for n, db in parts])
    everything = [(0.0, len(loud) * SPF)]
    found = find_voice(loud, SPF, everything)
    shifted = find_voice(loud + np.float32(gain), SPF, everything)
    assert shifted.reason == found.reason
    assert (shifted.activity is None) == (found.activity is None)
    if found.activity is None or shifted.activity is None:
        return
    assert shifted.activity.spans == found.activity.spans
    assert shifted.threshold_db == pytest.approx(found.threshold_db + gain)
    spans = found.activity.spans
    assert all(0.0 <= a < b <= len(loud) * SPF + 1e-9 for a, b in spans)
    assert all(a2 > b1 for (_, b1), (a2, _) in zip(spans, spans[1:], strict=False))
    assert all(b - a >= 0.1 - 1e-9 for a, b in spans)


def test_noise_just_above_the_floor_never_counts_as_voice() -> None:
    # confident words: 30 % soft at -70 dB, the rest at -20; the floor is -80 with noise at -75
    word_part = ((0.9, -70), (2.1, -20))
    loud = song((2, FLOOR), *word_part, (2, -75), *word_part, (2, FLOOR))
    found = find_voice(loud, SPF, [(2.0, 5.0), (7.0, 10.0)])
    assert found.activity is not None
    assert found.threshold_db == pytest.approx(FLOOR + 6)  # not the -76 the words alone give
    assert found.activity.voiced_fraction(5.0, 7.0) == 0.0


def test_the_detection_closes_short_holes_and_drops_short_islands() -> None:
    loud = song((2, FLOOR), (1, -20), (0.1, FLOOR), (1, -20), (1, FLOOR), (0.06, -20), (2, FLOOR))
    found = find_voice(loud, SPF, [(2.0, 4.1)])
    assert found.activity is not None
    assert flat(found.activity.spans) == pytest.approx([2.0, 4.1])


def test_a_confident_word_at_the_very_start_counts_its_first_frame() -> None:
    loud = song((0.26, -45), (1.0, -20), (5, FLOOR))  # 13 soft frames: the 20th percentile
    found = find_voice(loud, SPF, [(0.0, 1.26)])
    assert found.reason == USED
    assert found.threshold_db == pytest.approx(-45.0 - 6)


def test_an_odd_share_still_reports_the_threshold() -> None:
    loud = song((50, FLOOR), (1.5, -20), (50, FLOOR))
    found = find_voice(loud, SPF, [(50.0, 51.5)])
    assert found.threshold_db == pytest.approx(-26.0)
