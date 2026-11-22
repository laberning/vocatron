"""Stage 1: pieces for the acoustic model and stitching their frames."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.alignment.chunks import (
    FIELD,
    SAMPLE_RATE,
    SILENCE_DB,
    STRIDE,
    fit_length,
    frame_count,
    frame_loudness,
    plan_pieces,
    stitch,
    sum_waves,
)


def test_frames_follow_the_stride_of_the_model() -> None:
    assert frame_count(FIELD - 1) == 0
    assert frame_count(FIELD) == 1
    assert frame_count(FIELD + STRIDE) == 2
    assert frame_count(SAMPLE_RATE) == 49  # one second gives 49 frames


def test_a_short_song_is_one_piece() -> None:
    (piece,) = plan_pieces(10 * SAMPLE_RATE, 30.0, 2.0)
    assert (piece.start, piece.stop) == (0, 10 * SAMPLE_RATE)


def test_pieces_are_30_seconds_with_2_seconds_overlap() -> None:
    pieces = plan_pieces(70 * SAMPLE_RATE, 30.0, 2.0)
    assert [(p.start / SAMPLE_RATE, p.stop / SAMPLE_RATE) for p in pieces] == [
        (0.0, 30.0),
        (28.0, 58.0),
        (56.0, 70.0),
    ]


@given(st.integers(FIELD, 400 * SAMPLE_RATE))
def test_pieces_cover_the_song_overlap_and_line_up_with_its_frames(samples: int) -> None:
    pieces = plan_pieces(samples, 30.0, 2.0)
    assert pieces[0].start == 0
    assert pieces[-1].stop == samples
    for before, after in zip(pieces, pieces[1:], strict=False):
        assert after.start % STRIDE == 0
        assert before.stop - after.start == 2 * SAMPLE_RATE  # the overlap
    assert all(frame_count(p.stop - p.start) > 0 for p in pieces)
    assert pieces[-1].first_frame + frame_count(pieces[-1].stop - pieces[-1].start) == frame_count(
        samples
    )


@pytest.mark.parametrize(
    ("samples", "piece", "overlap"),
    [(100, 30.0, 2.0), (SAMPLE_RATE, 2.0, 2.0), (SAMPLE_RATE, 0.0, 0.0)],
)
def test_plans_that_cannot_work_are_errors(samples: int, piece: float, overlap: float) -> None:
    with pytest.raises(ValueError, match="too short|overlap"):
        plan_pieces(samples, piece, overlap)


@given(st.integers(FIELD, 150 * SAMPLE_RATE), st.integers(1, 6))
def test_stitching_pieces_of_one_signal_gives_the_signal_back(samples: int, width: int) -> None:
    total = frame_count(samples)
    signal = np.random.default_rng(samples).normal(size=(total, width)).astype(np.float32)
    parts = []
    for piece in plan_pieces(samples, 30.0, 2.0):
        first = piece.first_frame
        parts.append((first, signal[first : first + frame_count(piece.stop - piece.start)]))
    assert np.array_equal(stitch(parts, total), signal)


def test_the_middle_of_the_overlap_is_where_the_second_piece_takes_over() -> None:
    first = (0, np.zeros((10, 1), dtype=np.float32))
    second = (6, np.ones((8, 1), dtype=np.float32))  # frames 6 to 13; overlap 6..9
    out = stitch([first, second], 14)
    assert out[:, 0].tolist() == [0.0] * 8 + [1.0] * 6


def test_pieces_that_do_not_fit_are_errors() -> None:
    piece = np.zeros((5, 2), dtype=np.float32)
    with pytest.raises(ValueError, match="no pieces"):
        stitch([], 5)
    with pytest.raises(ValueError, match="gap"):
        stitch([(0, piece), (7, piece)], 12)
    with pytest.raises(ValueError, match="end at frame"):
        stitch([(0, piece)], 9)


@given(st.integers(0, 6 * SAMPLE_RATE))
def test_the_loudness_has_one_value_per_model_frame(samples: int) -> None:
    loudness = frame_loudness(np.zeros(samples, dtype=np.float32))
    assert loudness.shape == (frame_count(samples),)
    assert loudness.dtype == np.float32
    assert np.all(loudness == SILENCE_DB)


@given(st.integers(FIELD, 3 * SAMPLE_RATE), st.data())
def test_a_burst_is_loud_exactly_in_the_frames_that_cover_it(
    samples: int, data: st.DataObject
) -> None:
    start = data.draw(st.integers(0, samples - 1))
    stop = data.draw(st.integers(start + 1, samples))
    wave = np.zeros(samples, dtype=np.float32)
    wave[start:stop] = 0.5
    loudness = frame_loudness(wave)
    for frame in (0, len(loudness) // 2, len(loudness) - 1):
        covers = frame * STRIDE < stop and frame * STRIDE + FIELD > start
        assert (loudness[frame] > SILENCE_DB) == covers


def test_a_full_scale_sine_is_minus_three_decibels() -> None:
    t = np.arange(SAMPLE_RATE) / SAMPLE_RATE
    wave = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    assert frame_loudness(wave) == pytest.approx(-3.01, abs=0.1)
    assert frame_loudness(wave * 0.1) == pytest.approx(-23.01, abs=0.1)


@given(st.floats(-7.0, 0.0))
def test_a_steady_level_is_its_decibels_down_to_the_floor(power: float) -> None:
    wave = np.full(FIELD, 10.0**power, dtype=np.float32)
    level = 20.0 * power
    assert frame_loudness(wave)[0] == pytest.approx(max(level, SILENCE_DB), abs=0.01)
    if level < SILENCE_DB - 0.01:  # below the floor it is exactly the floor, on every CPU
        assert frame_loudness(wave)[0] == SILENCE_DB


def test_a_wave_shorter_than_a_frame_has_no_loudness() -> None:
    assert frame_loudness(np.ones(FIELD - 1, dtype=np.float32)).shape == (0,)


def test_two_waves_are_added_sample_by_sample_and_the_shorter_is_padded_with_zeros() -> None:
    first = np.array([0.5, -0.25, 0.1], dtype=np.float32)
    second = np.array([0.25, 0.25, 0.0, 0.3, 0.4], dtype=np.float32)
    assert sum_waves(first, second).tolist() == pytest.approx([0.75, 0.0, 0.1, 0.3, 0.4])
    assert sum_waves(second, first).tolist() == sum_waves(first, second).tolist()
    assert sum_waves(first, np.empty(0, dtype=np.float32)).tolist() == first.tolist()


@given(st.integers(0, 2000), st.integers(0, 2000))
def test_the_sum_is_as_long_as_the_longer_wave(short: int, extra: int) -> None:
    a = np.ones(short, dtype=np.float32)
    b = np.ones(short + extra, dtype=np.float32)
    assert len(sum_waves(a, b)) == short + extra


def test_fit_length_trims_or_pads_with_silence_and_keeps_the_type() -> None:
    wave = np.array([0.5, -0.5, 0.25], dtype=np.float32)
    assert fit_length(wave, 2).tolist() == [0.5, -0.5]
    assert fit_length(wave, 3).tolist() == wave.tolist()
    padded = fit_length(wave, 5)
    assert padded.tolist() == [0.5, -0.5, 0.25, 0.0, 0.0]
    assert padded.dtype == np.float32
