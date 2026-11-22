"""Stage 1: the tempo estimate and the length of a countdown in beats."""

import warnings

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fakes.clicks import clicks, drum_pattern, noise
from vocatron.core.tempo import (
    CHUNK,
    FRAME,
    HOP,
    LOG_GAIN,
    MAX_COUNTDOWN,
    MIN_COUNTDOWN,
    MIN_SECONDS,
    SAMPLE_RATE,
    SMOOTHING_SECONDS,
    UNCLEAR,
    autocorrelation,
    countdown_beat,
    estimate_tempo,
    onset_strength,
    refined_peak,
    tempo_weight,
)

TOLERANCE = 0.02


def near_octave(found: float, wanted: float, tolerance: float = TOLERANCE) -> bool:
    """Whether ``found`` is ``wanted`` within ``tolerance`` (2 %), or at double or half of it."""
    return any(abs(found / (wanted * factor) - 1) <= tolerance for factor in (0.5, 1, 2))


@settings(max_examples=25)
@given(
    bpm=st.floats(60, 180),
    swing=st.sampled_from([0.0, 0.1, 0.2]),
    jitter=st.floats(0, 0.005),
    seed=st.integers(0, 1000),
)
def test_a_drum_pattern_is_found_within_two_percent_or_at_double_or_half(
    bpm: float, swing: float, jitter: float, seed: int
) -> None:
    tempo = estimate_tempo(drum_pattern(bpm, swing=swing, jitter=jitter, seed=seed))
    assert tempo.bpm is not None
    assert near_octave(tempo.bpm, bpm)
    assert tempo.clarity > 0.5


@settings(max_examples=15)
@given(bpm=st.floats(60, 180))
def test_bare_clicks_are_found_too(bpm: float) -> None:
    tempo = estimate_tempo(clicks(bpm))
    assert tempo.bpm is not None
    assert near_octave(tempo.bpm, bpm)


def test_the_tempo_is_found_at_the_usual_pop_tempos_without_folding() -> None:
    for bpm in (80.0, 100.0, 120.0, 140.0):
        tempo = estimate_tempo(drum_pattern(bpm))
        assert tempo.bpm == pytest.approx(bpm, rel=TOLERANCE)


@pytest.mark.parametrize("seed", range(5))
def test_noise_has_no_tempo(seed: int) -> None:
    tempo = estimate_tempo(noise(seed=seed))
    assert tempo.bpm is None
    assert 0 <= tempo.clarity < 0.2


def test_silence_has_no_tempo() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no division by a peak of zero
        assert estimate_tempo(np.zeros(30 * SAMPLE_RATE, dtype=np.float32)) == UNCLEAR


def test_a_song_that_is_too_short_has_no_tempo() -> None:
    short = drum_pattern(100.0, seconds=MIN_SECONDS - 1)
    assert estimate_tempo(short) == UNCLEAR
    assert estimate_tempo(np.zeros(0, dtype=np.float32)) == UNCLEAR


@pytest.mark.parametrize("bpm", np.linspace(60, 180, 13).tolist())
def test_the_peak_is_refined_between_frames_to_half_a_percent(bpm: float) -> None:
    # a frame is 11.6 ms: without the refinement a fast tempo would be up to 1.7 % off
    tempo = estimate_tempo(clicks(bpm))
    assert tempo.bpm is not None
    assert near_octave(tempo.bpm, bpm, 0.005)


def test_the_tempo_and_the_clarity_are_rounded() -> None:
    clear, unclear = estimate_tempo(clicks(103.0)), estimate_tempo(noise())
    assert clear.bpm is not None
    assert clear.bpm == round(clear.bpm, 2) != round(clear.bpm, 1)
    assert clear.clarity == round(clear.clarity, 4) != round(clear.clarity, 3)
    assert unclear.clarity == round(unclear.clarity, 4) != round(unclear.clarity, 3)


def test_a_song_of_exactly_the_shortest_length_has_a_tempo() -> None:
    tempo = estimate_tempo(
        drum_pattern(100.0, seconds=MIN_SECONDS)[: int(MIN_SECONDS * SAMPLE_RATE)]
    )
    assert tempo.bpm is not None


def test_a_tempo_below_the_slowest_is_not_found_as_itself() -> None:
    tempo = estimate_tempo(clicks(39.6, seconds=60))
    assert tempo.bpm is None or not near_octave(tempo.bpm, 39.6, 0.005)
    assert estimate_tempo(clicks(40.5, seconds=60)).bpm == pytest.approx(40.5, rel=0.005)


def test_the_weighting_favours_the_centre_and_falls_by_the_octave() -> None:
    weights = tempo_weight(np.array([120.0, 240.0, 60.0, 30.0]))
    assert weights == pytest.approx(np.exp(-0.5 * (np.array([0, 1, 1, 2]) / 1.5) ** 2))


def test_a_parabola_through_the_peak_finds_its_top_between_the_samples() -> None:
    values = -((np.arange(6.0) - 2.3) ** 2)
    assert refined_peak(values, 2) == pytest.approx(2.3)
    assert refined_peak(-((np.arange(6.0) - 2.8) ** 2), 3) == pytest.approx(2.8)


def test_a_peak_at_an_end_or_without_a_bend_stays_where_it_is() -> None:
    values = np.array([3.0, 2.0, 1.0, 0.5])
    assert refined_peak(values, 0) == 0.0
    assert refined_peak(values[::-1].copy(), 3) == 3.0
    assert refined_peak(np.array([1.0, 1.0, 1.0]), 1) == 1.0  # flat: no bend
    assert refined_peak(np.array([2.0, 1.0, 2.0]), 1) == 1.0  # a dip, not a peak


def test_a_peak_next_to_an_end_is_refined_too() -> None:
    values = np.array([0.0, 1.0, 0.5, 0.0])
    assert refined_peak(values, 1) == pytest.approx(1 + 0.5 * (0.0 - 0.5) / (0.0 - 2 + 0.5))
    assert refined_peak(values[::-1].copy(), 2) == pytest.approx(3 - refined_peak(values, 1))


def test_the_clarity_is_the_height_of_the_peak_above_the_median() -> None:
    # a click track: the peak is 0.89, the median of the other repeats a little below zero
    assert estimate_tempo(clicks(100.0)).clarity == pytest.approx(0.927, abs=0.01)


def test_another_sample_rate_is_a_mistake() -> None:
    with pytest.raises(ValueError, match="22050"):
        estimate_tempo(drum_pattern(100.0), rate=44100)


def test_a_tempo_that_changes_in_the_middle_is_not_clearer_than_a_steady_one() -> None:
    steady = estimate_tempo(drum_pattern(100.0, seconds=40))
    changing = estimate_tempo(
        np.concatenate([drum_pattern(80.0, seconds=20), drum_pattern(130.0, seconds=20)])
    )
    assert changing.clarity < steady.clarity


def test_the_estimate_does_not_depend_on_the_level() -> None:
    song = drum_pattern(110.0)
    assert estimate_tempo(song * 0.05) == estimate_tempo(song)


def test_the_onset_curve_has_one_value_per_frame_and_is_never_negative() -> None:
    curve = onset_strength(drum_pattern(100.0, seconds=10))
    assert curve.ndim == 1
    assert curve.shape[0] > 800
    assert (curve >= 0).all()
    assert onset_strength(np.zeros(100, dtype=np.float32)).shape == (0,)


def test_the_onset_curve_taken_in_chunks_is_the_curve_taken_at_once() -> None:
    samples = drum_pattern(100.0, seconds=CHUNK * 2.5 * HOP / SAMPLE_RATE)
    count = 1 + (samples.shape[0] - FRAME) // HOP
    index = np.arange(FRAME)[None, :] + HOP * np.arange(count)[:, None]
    spectrum = np.log1p(LOG_GAIN * np.abs(np.fft.rfft(samples[index] * np.hanning(FRAME), axis=1)))
    rise = np.maximum(np.diff(spectrum, axis=0), 0.0).sum(axis=1)
    window = round(SMOOTHING_SECONDS * SAMPLE_RATE / HOP)
    once = np.maximum(rise - np.convolve(rise, np.ones(window) / window, mode="same"), 0.0)
    assert onset_strength(samples) == pytest.approx(once)
    assert onset_strength(samples[: FRAME + HOP]).shape == (1,)
    assert onset_strength(samples[: FRAME + HOP - 1]).shape == (0,)


def test_the_autocorrelation_is_one_at_lag_zero_and_zero_for_a_flat_curve() -> None:
    curve = np.abs(np.sin(np.arange(500) / 5.0))
    ac = autocorrelation(curve)
    assert ac[0] == pytest.approx(1.0)
    assert np.argmax(ac[10:25]) + 10 == pytest.approx(round(5 * np.pi), abs=1)
    assert not autocorrelation(np.zeros(100)).any()


def test_the_autocorrelation_is_the_direct_sum_over_the_overlap() -> None:
    curve = np.random.default_rng(3).random(37)
    centred = curve - curve.mean()
    direct = np.array([centred[: 37 - k] @ centred[k:] / (37 - k) for k in range(37)])
    assert autocorrelation(curve) == pytest.approx(direct / direct[0])


def test_the_autocorrelation_of_an_alternating_curve_goes_negative_at_lag_one() -> None:
    ac = autocorrelation(np.tile([1.0, 0.0], 20))
    assert ac[0] == pytest.approx(1.0)
    assert ac[1] < 0 < ac[2]


@settings(max_examples=200)
@given(bpm=st.floats(1, 1000), count=st.integers(1, 8))
def test_count_beats_always_last_between_the_limits(bpm: float, count: int) -> None:
    beat = countdown_beat(bpm, count)
    assert MIN_COUNTDOWN <= count * beat <= MAX_COUNTDOWN


@settings(max_examples=200)
@given(bpm=st.floats(1, 1000), count=st.integers(1, 8))
def test_the_beat_is_the_tempo_doubled_or_halved(bpm: float, count: int) -> None:
    ratio = countdown_beat(bpm, count) * bpm / 60.0
    octaves = np.log2(ratio)
    assert octaves == pytest.approx(round(octaves))


@settings(max_examples=100)
@given(bpm=st.floats(1, 1000), count=st.integers(1, 8))
def test_folding_twice_changes_nothing(bpm: float, count: int) -> None:
    beat = countdown_beat(bpm, count)
    assert countdown_beat(60.0 / beat, count) == pytest.approx(beat)


def test_a_tempo_that_fits_is_left_alone() -> None:
    assert countdown_beat(100.0, 4) == pytest.approx(0.6)  # 2.4 s
    assert countdown_beat(60.0, 4) == pytest.approx(1.0)  # 4 s exactly is not too long
    assert countdown_beat(160.0, 4) == pytest.approx(0.375)  # 1.5 s exactly is not too short


def test_a_slow_tempo_is_halved_and_a_fast_one_doubled() -> None:
    assert countdown_beat(50.0, 4) == pytest.approx(0.6)  # 4.8 s -> 2.4 s
    assert countdown_beat(200.0, 4) == pytest.approx(0.6)  # 1.2 s -> 2.4 s
    assert countdown_beat(100.0, 8) == pytest.approx(0.3)  # 4.8 s -> 2.4 s
    assert countdown_beat(100.0, 1) == pytest.approx(2.4)  # 0.6 s -> 1.2 s -> 2.4 s


@pytest.mark.parametrize(("bpm", "count"), [(0.0, 4), (-5.0, 4), (100.0, 0)])
def test_a_tempo_or_count_that_is_not_positive_is_refused(bpm: float, count: int) -> None:
    with pytest.raises(ValueError, match="^the tempo and the number of beats must be positive$"):
        countdown_beat(bpm, count)
