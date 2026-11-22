"""Stage 1: SDR, SI-SDR, fullness, bleedless, line-up and summary (properties and known values)."""

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from numpy.typing import NDArray

from vocatron.core.mel import mel_filter_bank
from vocatron.lab.separation import metrics
from vocatron.lab.separation.metrics import (
    bleedless_fullness,
    find_lag,
    score,
    sdr,
    si_sdr,
    summarise,
    trim_pair,
)

RATE = 44100


def noise(seed: int, samples: int = RATE, channels: int = 2) -> NDArray[np.float32]:
    return np.random.default_rng(seed).uniform(-0.5, 0.5, (channels, samples)).astype(np.float32)


def test_identical_signals_score_very_high_everywhere() -> None:
    ref = noise(1)
    scores = score(ref, ref)
    assert scores.sdr > 70
    assert scores.si_sdr > 70
    assert scores.fullness == 100.0
    assert scores.bleedless == 100.0


def test_sdr_of_a_known_error_is_ten_log_of_the_energy_ratio() -> None:
    ref = np.ones((2, 1000), dtype=np.float32)
    est = ref * 0.9  # error energy is 1 % of the reference energy
    assert sdr(ref, est) == pytest.approx(20.0, abs=1e-3)


def test_silence_does_not_divide_by_zero() -> None:
    zero = np.zeros((2, 100), dtype=np.float32)
    assert math.isfinite(sdr(zero, zero))
    assert math.isfinite(si_sdr(zero, zero))


@given(scale=st.floats(0.05, 4.0), seed=st.integers(0, 50))
@settings(max_examples=25, deadline=None)
def test_si_sdr_does_not_change_when_the_estimate_is_scaled(scale: float, seed: int) -> None:
    ref = noise(seed, 2000)
    est = ref + 0.1 * noise(seed + 100, 2000)
    assert si_sdr(ref, est * np.float32(scale)) == pytest.approx(si_sdr(ref, est), abs=1e-3)


@given(scale=st.floats(0.1, 0.9))
@settings(max_examples=20, deadline=None)
def test_a_scaled_copy_has_a_sdr_that_depends_on_the_scale_but_a_perfect_si_sdr(
    scale: float,
) -> None:
    ref = noise(3, 2000)
    est = ref * np.float32(scale)
    assert si_sdr(ref, est) > 60
    assert sdr(ref, est) == pytest.approx(-20 * math.log10(1 - scale), abs=0.05)


@given(level=st.floats(0.01, 0.3))
@settings(max_examples=20, deadline=None)
def test_more_added_noise_lowers_the_scores(level: float) -> None:
    ref = noise(4, 8000)
    small = ref + np.float32(level) * noise(5, 8000)
    large = ref + np.float32(2 * level) * noise(5, 8000)
    assert sdr(ref, large) < sdr(ref, small)
    assert si_sdr(ref, large) < si_sdr(ref, small)


def test_sdr_is_not_symmetric_but_the_error_energy_is() -> None:
    ref, est = noise(6, 4000), noise(7, 4000) * np.float32(0.3)
    assert sdr(ref, est) != pytest.approx(sdr(est, ref), abs=1e-3)
    assert float(np.sum((ref - est) ** 2)) == pytest.approx(float(np.sum((est - ref) ** 2)))


def test_channels_and_samples_count_alike() -> None:
    ref, est = noise(8, 3000), noise(9, 3000)
    assert sdr(ref, est) == pytest.approx(sdr(ref.reshape(1, -1), est.reshape(1, -1)), abs=1e-6)


def test_signals_of_different_shapes_are_refused() -> None:
    with pytest.raises(ValueError, match="different shapes"):
        sdr(noise(1, 100), noise(1, 101))
    with pytest.raises(ValueError, match="different shapes"):
        si_sdr(noise(1, 100), noise(1, 101))
    with pytest.raises(ValueError, match="different shapes"):
        bleedless_fullness(noise(1, 9000), noise(1, 9001))


def test_a_thin_estimate_lowers_fullness_and_added_noise_lowers_bleedless() -> None:
    ref = noise(10, RATE)
    bleedless, fullness = bleedless_fullness(ref, ref)
    thin_bleedless, thin_fullness = bleedless_fullness(ref, ref * np.float32(0.25))
    assert thin_fullness < fullness
    assert thin_bleedless == pytest.approx(bleedless)  # nothing was added
    loud_bleedless, loud_fullness = bleedless_fullness(ref, ref * np.float32(4.0))
    assert loud_bleedless < bleedless
    assert loud_fullness == pytest.approx(fullness)  # nothing is missing


def test_fullness_of_a_known_gain_is_a_hundred_over_one_plus_the_decibels() -> None:
    ref = noise(11, RATE)
    gain = 0.5  # 6.02 dB less everywhere
    _, fullness = bleedless_fullness(ref, ref * np.float32(gain))
    assert fullness == pytest.approx(100 / (1 + 20 * math.log10(1 / gain)), rel=0.01)


def test_the_measures_have_a_fixed_order() -> None:
    assert metrics.MEASURES == ("sdr", "si_sdr", "fullness", "bleedless")
    assert set(metrics.MEASURES) == set(metrics.Scores.__dataclass_fields__)


@given(shift=st.integers(0, 400))
@settings(max_examples=20, deadline=None)
def test_find_lag_recovers_a_shift_and_trim_pair_lines_the_signals_up(shift: int) -> None:
    base = noise(12, 6000)
    late = np.concatenate([np.zeros((2, shift), np.float32), base], axis=1)
    lag = find_lag(base, late, 1000)
    assert lag == shift
    first, second = trim_pair(base, late, lag)
    assert first.shape == second.shape
    assert np.array_equal(first, second)


def test_find_lag_is_antisymmetric_and_bounded() -> None:
    base = noise(13, 5000)
    late = np.concatenate([np.zeros((2, 300), np.float32), base], axis=1)
    assert find_lag(base, late, 1000) == 300
    assert find_lag(late, base, 1000) == -300
    assert abs(find_lag(base, late, 100)) <= 100


def test_trim_pair_cuts_to_the_common_stretch() -> None:
    first, second = np.arange(10.0).reshape(1, 10), np.arange(8.0).reshape(1, 8)
    a, b = trim_pair(first, second, 0)
    assert a.shape == b.shape == (1, 8)
    a, b = trim_pair(first, second, 3)  # second[3:] against first[0:]
    assert a.shape == b.shape == (1, 5)
    assert b[0, 0] == 3.0
    a, b = trim_pair(first, second, -4)
    assert a[0, 0] == 4.0 and a.shape == b.shape == (1, 6)
    a, b = trim_pair(first, second, 50)
    assert a.shape == (1, 0)


def test_find_lag_refuses_empty_signals() -> None:
    with pytest.raises(ValueError, match="empty"):
        find_lag(np.zeros((2, 0)), noise(1, 10), 5)


def test_summarise_gives_mean_and_standard_error() -> None:
    result = summarise([1.0, 2.0, 3.0, 4.0])
    assert result.mean == 2.5
    assert result.error == pytest.approx(math.sqrt(5 / 3) / 2)
    assert result.count == 4
    assert math.isnan(summarise([1.0]).error)
    empty = summarise([])
    assert math.isnan(empty.mean)
    assert empty.count == 0


def msst_si_sdr(reference: NDArray[np.float64], estimate: NDArray[np.float64]) -> float:
    """MSST's SI-SDR written out as the oracle: EPS per sample in the scale, as upstream."""
    eps = 1e-8
    scale = np.sum(estimate * reference + eps) / np.sum(reference**2 + eps)
    scaled = reference * scale
    return float(10 * np.log10(np.sum(scaled**2) / (np.sum((scaled - estimate) ** 2) + eps) + eps))


def test_si_sdr_equals_msst_where_the_epsilon_per_sample_matters() -> None:
    # samples of 1e-4 have an energy of 1e-8 each, as large as the epsilon added per sample
    reference = np.full((2, 500), 1e-4)
    estimate = reference * 0.5 + np.random.default_rng(3).normal(0, 2e-5, (2, 500))
    assert si_sdr(reference, estimate) == pytest.approx(msst_si_sdr(reference, estimate), rel=1e-9)


def test_si_sdr_of_a_known_error_has_ten_decibels_per_decade() -> None:
    reference = noise(30, 4000).astype(np.float64)
    orthogonal = noise(31, 4000).astype(np.float64)
    orthogonal -= reference * np.sum(orthogonal * reference) / np.sum(reference**2)
    orthogonal *= np.sqrt(np.sum(reference**2) / np.sum(orthogonal**2)) / 10  # 1/100 the energy
    assert si_sdr(reference, reference + orthogonal) == pytest.approx(20.0, abs=1e-3)


def test_the_hann_window_is_the_periodic_one() -> None:
    assert np.allclose(metrics._hann(8), np.hanning(9)[:-1])
    assert metrics._hann(4).tolist() == pytest.approx([0.0, 0.5, 1.0, 0.5])


def test_the_mel_spectrogram_has_one_frame_per_hop_and_is_float32() -> None:
    bank = mel_filter_bank(RATE, metrics.N_FFT, metrics.N_MELS)
    spectrogram = metrics._mel_db(noise(32, 10 * metrics.HOP), bank)
    assert spectrogram.shape == (2, metrics.N_MELS, 11)  # centred frames: 1 + samples // hop
    assert spectrogram.dtype == np.float32


def test_the_mel_spectrogram_is_floored_eighty_decibels_below_its_peak() -> None:
    signal = noise(33, 8 * metrics.HOP)
    signal[:, 4 * metrics.HOP :] *= np.float32(1e-6)  # 120 dB quieter in the second half
    bank = mel_filter_bank(RATE, metrics.N_FFT, metrics.N_MELS)
    spectrogram = metrics._mel_db(signal, bank)
    assert float(spectrogram.min()) == pytest.approx(float(spectrogram.max()) - metrics.TOP_DB)


def test_the_mel_spectrogram_of_more_frames_than_a_block_matches_one_block_at_a_time() -> None:
    frames = metrics.BLOCK_FRAMES + 20
    signal = noise(34, (frames - 1) * metrics.HOP, channels=1)
    bank = mel_filter_bank(RATE, metrics.N_FFT, metrics.N_MELS)
    whole = metrics._mel_db(signal, bank)
    assert whole.shape == (1, metrics.N_MELS, frames)
    # the last frames, computed directly from the padded signal
    padded = np.pad(signal[0].astype(np.float64), metrics.N_FFT // 2)
    last = padded[-metrics.N_FFT :] * metrics._hann(metrics.N_FFT)
    power = bank @ np.abs(np.fft.rfft(last)).astype(np.float32)
    expected = np.maximum(20 * np.log10(np.maximum(power, 1e-10)), whole.max() - metrics.TOP_DB)
    assert np.allclose(whole[0, :, -1], expected, atol=1e-3)


def test_only_strictly_louder_or_quieter_mel_bins_count_for_bleedless_and_fullness() -> None:
    reference = noise(35, RATE)
    louder = reference.copy()
    louder[1] *= np.float32(1.05)  # +0.42 dB in one channel, the other unchanged
    bleedless, fullness = bleedless_fullness(reference, louder)
    assert bleedless == pytest.approx(100 / (1 + 20 * math.log10(1.05)), rel=1e-3)
    assert fullness == 100.0
    quieter = reference.copy()
    quieter[1] *= np.float32(0.95)  # -0.45 dB
    bleedless, fullness = bleedless_fullness(reference, quieter)
    assert bleedless == 100.0
    assert fullness == pytest.approx(100 / (1 + 20 * math.log10(1 / 0.95)), rel=1e-3)


def test_find_lag_reaches_the_ends_of_the_overlap_and_no_further() -> None:
    impulse_last, impulse_first = np.array([[0.0, 0.0, 1.0]]), np.array([[1.0, 0.0, 0.0]])
    assert find_lag(impulse_last, impulse_first, 10) == -2  # other starts two samples later
    assert find_lag(impulse_first, impulse_last, 10) == 2
    # a single sample of opposite sign: only lag 0 overlaps, however wide the search
    assert find_lag(np.array([[1.0]]), np.array([[-1.0]]), 5) == 0


def test_find_lag_takes_a_zero_range_and_a_one_sample_signal() -> None:
    base = noise(36, 50)
    assert find_lag(base, base, 0) == 0
    assert find_lag(base, base[:, :1], 3) in range(-3, 1)


@pytest.mark.parametrize(
    ("reference", "other", "max_lag"),
    [
        (np.ones((2, 5)), np.zeros((2, 0)), 3),
        (np.zeros((2, 0)), np.ones((2, 5)), 3),
        (np.ones((2, 5)), np.ones((2, 5)), -1),
    ],
    ids=["other-empty", "reference-empty", "negative-range"],
)
def test_find_lag_refuses_nothing_to_line_up(
    reference: NDArray[np.float64], other: NDArray[np.float64], max_lag: int
) -> None:
    with pytest.raises(
        ValueError, match=r"^cannot line up empty signals or search a negative range$"
    ):
        find_lag(reference, other, max_lag)


def test_trim_pair_without_a_lag_starts_both_at_the_beginning_and_takes_mono() -> None:
    first, second = np.arange(6.0), np.arange(4.0)
    a, b = trim_pair(first, second)
    assert a.tolist() == b.tolist() == [0.0, 1.0, 2.0, 3.0]


def test_summarise_of_nothing_has_no_error_either() -> None:
    assert math.isnan(summarise([]).error)
