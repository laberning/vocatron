"""Objective measures of a separated stem against the true stem (ADR-0002, ADR-0004).

SDR, SI-SDR, fullness and bleedless follow the definitions of Music-Source-Separation-Training,
file ``utils/metrics.py`` at commit ``6fdad13686bb7e84d029ec66f9dbe76e65c93ebf`` (MIT), which is
also what the MVSep leaderboard uses: the same formulas, constants and edge cases, written in
NumPy. Only the definitions are taken, not the code. Audio is a float array shaped (channels,
samples). Songs from different sources are lined up first (``find_lag``, ``trim_pair``).

Fullness and bleedless compare the mel spectrograms (4096-point STFT, 512 mel bands) in dB: fullness
penalises energy the estimate lacks (holes, a thin sound), bleedless penalises energy it adds
(bleed, noise). Higher is better for all four; the community's guide calls fullness and bleedless
"not very reliable", and no validation against listening is known.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean, stdev

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray

from vocatron.core.mel import mel_filter_bank

Signal = NDArray[np.floating]
"""Audio shaped (channels, samples)."""

EPS = 1e-8
"""Added to the energies so that silence does not divide by zero (as upstream)."""
N_FFT = 4096
HOP = 1024
N_MELS = 512
TOP_DB = 80.0
"""The dB values are floored this far below the loudest one (as upstream)."""
AMIN = 1e-10
"""The smallest magnitude before the dB conversion."""
BLOCK_FRAMES = 256
"""STFT frames processed at once, to bound memory."""
SAMPLE_RATE = 44100


def sdr(reference: Signal, estimate: Signal) -> float:
    """Return the signal-to-distortion ratio in dB (reference energy over error energy).

    Both energies are summed over all channels and samples and get ``EPS`` added.

    Raises:
        ValueError: If the shapes differ.
    """
    _same_shape(reference, estimate)
    ref, est = reference.astype(np.float64), estimate.astype(np.float64)
    num = float(np.sum(ref**2)) + EPS
    den = float(np.sum((ref - est) ** 2)) + EPS
    return 10.0 * math.log10(num / den)


def si_sdr(reference: Signal, estimate: Signal) -> float:
    """Return the scale-invariant SDR in dB.

    As upstream, the *reference* is scaled by the factor that fits it best to the estimate (the
    scale is computed over all channels and samples, with ``EPS`` added per sample), then the SDR
    of the scaled reference against the estimate is taken.

    Raises:
        ValueError: If the shapes differ.
    """
    _same_shape(reference, estimate)
    ref, est = reference.astype(np.float64), estimate.astype(np.float64)
    scale = float(np.sum(est * ref + EPS)) / float(np.sum(ref**2 + EPS))
    scaled = ref * scale
    num = float(np.sum(scaled**2))
    den = float(np.sum((scaled - est) ** 2)) + EPS
    return 10.0 * math.log10(num / den + EPS)


def _same_shape(first: Signal, second: Signal) -> None:
    """Require two signals of one shape.

    Raises:
        ValueError: If the shapes differ.
    """
    if first.shape != second.shape:
        raise ValueError(f"the signals have different shapes: {first.shape} and {second.shape}")


def _hann(size: int) -> NDArray[np.float64]:
    """Return the periodic Hann window (the one ``torch.hann_window`` gives)."""
    return 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(size) / size)


def _mel_db(signal: Signal, bank: NDArray[np.float32]) -> NDArray[np.float32]:
    """Return the mel spectrogram in dB shaped (channels, mels, frames), floored at -80 dB."""
    window = _hann(N_FFT)
    padded = np.pad(signal.astype(np.float64), ((0, 0), (N_FFT // 2, N_FFT // 2)))
    frames = 1 + (padded.shape[1] - N_FFT) // HOP
    out = np.empty((signal.shape[0], bank.shape[0], frames), dtype=np.float32)
    windows = sliding_window_view(padded, N_FFT, axis=1)[:, ::HOP]
    for first in range(0, frames, BLOCK_FRAMES):
        block = windows[:, first : first + BLOCK_FRAMES] * window
        magnitude = np.abs(np.fft.rfft(block, axis=-1)).astype(np.float32)
        out[:, :, first : first + magnitude.shape[1]] = np.einsum("mf,cbf->cmb", bank, magnitude)
    decibels = 20.0 * np.log10(np.maximum(out, np.float32(AMIN)))
    return np.maximum(decibels, decibels.max() - TOP_DB).astype(np.float32)


def bleedless_fullness(reference: Signal, estimate: Signal) -> tuple[float, float]:
    """Return ``(bleedless, fullness)``, each between 0 and 100 (higher is better).

    The mel spectrograms in dB of the estimate and the reference are subtracted. Bleedless is
    ``100 / (1 + mean of the positive differences)``: the estimate has more energy than it should.
    Fullness is ``100 / (1 + mean of the absolute negative differences)``: it has less.

    Raises:
        ValueError: If the shapes differ.
    """
    _same_shape(reference, estimate)
    bank = mel_filter_bank(SAMPLE_RATE, N_FFT, N_MELS)
    diff = _mel_db(estimate, bank) - _mel_db(reference, bank)
    positive, negative = diff[diff > 0], diff[diff < 0]
    average_positive = float(positive.mean()) if positive.size else 0.0
    average_negative = float(negative.mean()) if negative.size else 0.0
    return 100.0 / (average_positive + 1.0), 100.0 / (-average_negative + 1.0)


@dataclass(frozen=True)
class Scores:
    """The four measures of one stem.

    Attributes:
        sdr: Signal-to-distortion ratio in dB.
        si_sdr: Scale-invariant SDR in dB.
        fullness: 0 to 100; low when the estimate lacks energy.
        bleedless: 0 to 100; low when the estimate has added energy.
    """

    sdr: float
    si_sdr: float
    fullness: float
    bleedless: float


MEASURES: tuple[str, ...] = ("sdr", "si_sdr", "fullness", "bleedless")
"""The names of the measures, in the order they are reported."""


def score(reference: Signal, estimate: Signal) -> Scores:
    """Return all four measures of ``estimate`` against ``reference`` (equal shapes)."""
    bleedless, fullness = bleedless_fullness(reference, estimate)
    return Scores(
        sdr=sdr(reference, estimate),
        si_sdr=si_sdr(reference, estimate),
        fullness=fullness,
        bleedless=bleedless,
    )


def find_lag(reference: Signal, other: Signal, max_lag: int) -> int:
    """Return by how many samples ``other`` lags behind ``reference``.

    The channels are summed to mono and cross-correlated; the lag with the highest correlation
    within ``+-max_lag`` samples wins (the earliest on ties). A positive lag means that
    ``other[n + lag]`` matches ``reference[n]``: ``other`` starts earlier in the music.

    Raises:
        ValueError: If a signal is empty or ``max_lag`` is negative.
    """
    if reference.shape[-1] == 0 or other.shape[-1] == 0 or max_lag < 0:
        raise ValueError("cannot line up empty signals or search a negative range")
    first = reference.astype(np.float64).sum(axis=0)
    second = other.astype(np.float64).sum(axis=0)
    size = 1 << (len(first) + len(second) - 1).bit_length()
    spectrum = np.fft.rfft(second, size) * np.conj(np.fft.rfft(first, size))
    correlation = np.fft.irfft(spectrum, size)
    lags = np.arange(-min(max_lag, len(first) - 1), min(max_lag, len(second) - 1) + 1)
    return int(lags[int(np.argmax(correlation[lags % size]))])


def trim_pair(first: Signal, second: Signal, lag: int = 0) -> tuple[Signal, Signal]:
    """Cut two signals to their common stretch after ``second`` lags ``first`` by ``lag`` samples.

    The returned signals have equal length: ``first[n]`` and ``second[n + lag]`` start together.
    """
    skip_first, skip_second = max(-lag, 0), max(lag, 0)
    length = min(first.shape[-1] - skip_first, second.shape[-1] - skip_second)
    length = max(length, 0)
    return (
        first[..., skip_first : skip_first + length],
        second[..., skip_second : skip_second + length],
    )


@dataclass(frozen=True)
class Summary:
    """Mean and standard error of a list of numbers.

    Attributes:
        mean: The mean (``nan`` for no numbers).
        error: The standard error of the mean (``nan`` for fewer than two numbers).
        count: How many numbers.
    """

    mean: float
    error: float
    count: int


def summarise(values: Sequence[float]) -> Summary:
    """Return the mean and the standard error (sample deviation over the root of the count)."""
    if not values:
        return Summary(math.nan, math.nan, 0)
    error = stdev(values) / math.sqrt(len(values)) if len(values) > 1 else math.nan
    return Summary(mean(values), error, len(values))
