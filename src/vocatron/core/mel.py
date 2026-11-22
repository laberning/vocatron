"""The mel filter bank (Slaney scale and normalisation) in NumPy.

Both the Mel-Band Roformer network and the fullness and bleedless measures of the separation
evaluation need the triangular mel filters that the audio libraries call ``mel(sr, n_fft,
n_mels)`` with their defaults (0 Hz to the Nyquist frequency, Slaney mel scale, area-normalised
filters). Writing the few lines here keeps a whole audio library out of the dependencies.
"""

import numpy as np
from numpy.typing import NDArray

_F_SP = 200.0 / 3
"""Hz per mel in the linear part of the Slaney scale."""
_MIN_LOG_HZ = 1000.0
"""Above this frequency the Slaney scale is logarithmic."""
_MIN_LOG_MEL = _MIN_LOG_HZ / _F_SP
_LOG_STEP = float(np.log(6.4)) / 27.0


def hz_to_mel(hz: NDArray[np.float64]) -> NDArray[np.float64]:
    """Convert frequencies in Hz to the Slaney mel scale (linear below 1 kHz, then logarithmic)."""
    linear = hz / _F_SP
    safe = np.maximum(hz, _MIN_LOG_HZ)
    logarithmic = _MIN_LOG_MEL + np.log(safe / _MIN_LOG_HZ) / _LOG_STEP
    return np.where(hz >= _MIN_LOG_HZ, logarithmic, linear)


def mel_to_hz(mel: NDArray[np.float64]) -> NDArray[np.float64]:
    """Convert Slaney mel values back to Hz; the inverse of ``hz_to_mel``."""
    linear = _F_SP * mel
    logarithmic = _MIN_LOG_HZ * np.exp(_LOG_STEP * (mel - _MIN_LOG_MEL))
    return np.where(mel >= _MIN_LOG_MEL, logarithmic, linear)


def mel_filter_bank(sample_rate: int, n_fft: int, n_mels: int) -> NDArray[np.float32]:
    """Return the mel filter bank shaped (``n_mels``, ``n_fft // 2 + 1``).

    The ``n_mels`` triangular filters are spaced evenly on the Slaney mel scale between 0 Hz and
    the Nyquist frequency; each is scaled to constant area (``2 / bandwidth``). Row ``i`` weighs
    the frequency bins of an STFT with ``n_fft`` points.

    Raises:
        ValueError: If a size is not positive.
    """
    if sample_rate <= 0 or n_fft <= 0 or n_mels <= 0:
        raise ValueError(f"invalid mel filter bank: {sample_rate=}, {n_fft=}, {n_mels=}")
    bins = np.linspace(0.0, sample_rate / 2, 1 + n_fft // 2)
    low, high = hz_to_mel(np.array([0.0, sample_rate / 2]))
    edges = mel_to_hz(np.linspace(low, high, n_mels + 2))
    widths = np.diff(edges)
    ramps = np.subtract.outer(edges, bins)
    lower = -ramps[:-2] / widths[:-1, None]
    upper = ramps[2:] / widths[1:, None]
    weights = np.maximum(0.0, np.minimum(lower, upper))
    weights *= (2.0 / (edges[2 : n_mels + 2] - edges[:n_mels]))[:, None]
    return weights.astype(np.float32)
