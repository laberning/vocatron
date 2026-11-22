"""Stage 1: the mel filter bank."""

import numpy as np
import pytest

from vocatron.core.mel import hz_to_mel, mel_filter_bank, mel_to_hz


def test_hz_and_mel_are_inverse_and_linear_below_one_kilohertz() -> None:
    hz = np.array([0.0, 100.0, 999.0, 1000.0, 1500.0, 8000.0, 22050.0])
    assert np.allclose(mel_to_hz(hz_to_mel(hz)), hz)
    assert hz_to_mel(np.array([1000.0]))[0] == pytest.approx(15.0)
    assert hz_to_mel(np.array([300.0]))[0] == pytest.approx(4.5)


def test_the_bank_has_one_row_per_band_and_one_column_per_bin() -> None:
    bank = mel_filter_bank(44100, 2048, 60)
    assert bank.shape == (60, 1025)
    assert bank.dtype == np.float32
    assert (bank >= 0).all()
    assert (bank.max(axis=1) > 0).all()


def test_each_filter_has_the_area_the_slaney_scaling_gives() -> None:
    bank = mel_filter_bank(44100, 4096, 512).astype(np.float64)
    spacing = 44100 / 4096
    # a triangle of the bandwidth w, scaled by 2 / w, has the area 1 (where the bins resolve it)
    areas = bank.sum(axis=1) * spacing
    assert np.allclose(areas[300:500], 1.0, atol=0.03)  # bins sample the triangles coarsely


def test_golden_values_of_a_small_bank() -> None:
    bank = mel_filter_bank(8000, 16, 4)
    expected = [
        [0, 1.99e-3, 0, 0, 0, 0, 0, 0, 0],
        [0, 1.30e-4, 1.70e-3, 7.0e-5, 0, 0, 0, 0, 0],
        [0, 0, 1.4e-4, 1.26e-3, 6.5e-4, 0, 0, 0, 0],
        [0, 0, 0, 0, 4.1e-4, 7.9e-4, 5.3e-4, 2.6e-4, 0],
    ]
    assert np.allclose(bank, expected, atol=1e-5)


@pytest.mark.parametrize("args", [(0, 64, 4), (8000, 0, 4), (8000, 64, 0)])
def test_a_size_that_is_not_positive_is_refused(args: tuple[int, int, int]) -> None:
    with pytest.raises(ValueError, match="invalid mel filter bank"):
        mel_filter_bank(*args)


def test_a_small_bank_equals_the_slaney_filters_to_float32_precision() -> None:
    # computed by torchaudio's melscale_fbanks(norm="slaney", mel_scale="slaney") and checked
    # against this implementation in stage 2 for the sizes the models use
    expected = np.zeros((4, 9))
    expected[0, 1] = 1.9911719e-03
    expected[1, 1:4] = [1.2631025e-04, 1.6980426e-03, 6.7957510e-05]
    expected[2, 2:5] = [1.3976658e-04, 1.2614938e-03, 6.4534059e-04]
    expected[3, 4:8] = [4.0878251e-04, 7.8907772e-04, 5.2605185e-04, 2.6302593e-04]
    assert np.allclose(mel_filter_bank(8000, 16, 4), expected, rtol=1e-5, atol=1e-9)


def test_the_first_filter_starts_at_zero_hertz() -> None:
    assert mel_filter_bank(44100, 2048, 60)[0, 0] == 0.0  # the bin of 0 Hz lies on its edge


@pytest.mark.parametrize("args", [(1, 64, 4), (8000, 1, 1), (8000, 64, 1)])
def test_the_smallest_sizes_are_valid(args: tuple[int, int, int]) -> None:
    rate, n_fft, n_mels = args
    assert mel_filter_bank(rate, n_fft, n_mels).shape == (n_mels, n_fft // 2 + 1)
