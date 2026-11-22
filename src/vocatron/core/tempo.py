"""The tempo of a song and the length of a countdown in beats (ADR-0022).

``estimate_tempo`` finds one tempo for a whole song with NumPy alone: the onset strength curve
(the rise of a log-magnitude spectrum from frame to frame) is autocorrelated, and the strongest
repeat between 40 and 240 beats per minute, gently weighted towards common tempos, is the tempo.
Only the tempo is estimated, not where the beats fall. A song with no clear repeat (noise,
silence, a changing tempo) has no tempo, and its countdown runs in seconds.

``countdown_beat`` folds the beat by doubling or halving until a countdown of ``count`` beats is
neither too short nor too long. All of it is pure; decoding the audio is an engine's job.
"""

from dataclasses import dataclass
from typing import ClassVar, Literal

import numpy as np
from numpy.typing import NDArray

from vocatron.core.stage_file import StageFile

SAMPLE_RATE = 22050
"""The sample rate the tempo is estimated at (mono)."""
FRAME = 1024
"""Samples per analysis frame."""
HOP = 256
"""Samples between two frames: about 11.6 ms, fine enough to tell tempos 2 % apart."""
MIN_BPM = 40.0
MAX_BPM = 240.0
PRIOR_CENTRE = 120.0
"""The tempo the weighting favours, in beats per minute."""
PRIOR_WIDTH = 1.5
"""The width of the weighting in octaves (the standard deviation): gentle, not a rule."""
CHUNK = 2048
"""Frames whose spectrum is taken at once: about 24 s of the song, some 17 MB."""
LOG_GAIN = 100.0
"""Scales the magnitudes before the logarithm, so that quiet detail counts."""
SMOOTHING_SECONDS = 1.0
"""The window of the moving mean that is taken off the onset strength."""
MIN_SECONDS = 20.0
"""A song shorter than this has no tempo: there are too few beats to tell."""
MIN_CLARITY = 0.2
"""Below this clarity the tempo is unclear and ``Tempo.bpm`` is ``None``."""
MIN_COUNTDOWN = 1.5
"""A countdown of ``count`` beats lasts at least this many seconds."""
MAX_COUNTDOWN = 4.0
"""A countdown of ``count`` beats lasts at most this many seconds."""

type Samples = NDArray[np.float32]


@dataclass(frozen=True)
class Tempo:
    """The tempo of a song.

    Attributes:
        bpm: Beats per minute, or ``None`` when the tempo is unclear.
        clarity: How clearly the song repeats at that tempo: 0 (not at all) to about 1 (a click
            track). The tempo is clear from ``MIN_CLARITY`` on.
    """

    bpm: float | None
    clarity: float


UNCLEAR = Tempo(bpm=None, clarity=0.0)


class TempoFile(StageFile):
    """``tempo.json``: the tempo of the song.

    Attributes:
        bpm: Beats per minute, or ``None`` when the tempo is unclear (the countdowns then run in
            seconds).
        clarity: How clearly the song repeats at that tempo.
    """

    SCHEMA_NAME: ClassVar[str] = "tempo"
    schema_version: Literal[1] = 1
    bpm: float | None
    clarity: float


def onset_strength(samples: Samples) -> NDArray[np.float64]:
    """Return how strongly something starts in every frame of ``samples`` (mono).

    The rise of the log-magnitude spectrum from one frame to the next, summed over the
    frequencies, minus its moving mean over about a second, and never below zero: one value per
    frame after the first. Samples too short for two frames have none. The spectrum is taken
    ``CHUNK`` frames at a time, so a long song needs little memory.
    """
    if samples.shape[0] < FRAME + HOP:
        return np.zeros(0)
    count = 1 + (samples.shape[0] - FRAME) // HOP
    taper = np.hanning(FRAME)
    rises: list[NDArray[np.float64]] = []
    previous: NDArray[np.float64] | None = None
    for first in range(0, count, CHUNK):
        index = (
            np.arange(FRAME)[None, :] + HOP * np.arange(first, min(first + CHUNK, count))[:, None]
        )
        frames = samples[index].astype(np.float64) * taper
        spectrum = np.log1p(LOG_GAIN * np.abs(np.fft.rfft(frames, axis=1)))
        joined = spectrum if previous is None else np.concatenate([previous, spectrum])
        rises.append(np.maximum(np.diff(joined, axis=0), 0.0).sum(axis=1))
        previous = spectrum[-1:]
    rise = np.concatenate(rises)
    window = min(round(SMOOTHING_SECONDS * SAMPLE_RATE / HOP), rise.shape[0])  # a short curve
    mean = np.convolve(rise, np.ones(window) / window, mode="same")
    return np.maximum(rise - mean, 0.0)


def autocorrelation(curve: NDArray[np.float64]) -> NDArray[np.float64]:
    """Return the autocorrelation of ``curve`` per lag, scaled to 1 at lag 0 and fair to long lags.

    Every lag is divided by the number of frames it can compare, so a long repeat is not
    punished for having fewer. A flat curve (all zero) gives all zeros.
    """
    n = curve.shape[0]
    size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(curve - curve.mean(), size)
    raw = np.fft.irfft(np.abs(spectrum) ** 2, size)[:n]
    fair = raw / (n - np.arange(n))
    return fair / fair[0] if fair[0] > 0 else np.zeros(n)


def tempo_weight(bpm: NDArray[np.float64]) -> NDArray[np.float64]:
    """Return the weight of each tempo: 1 at ``PRIOR_CENTRE``, falling gently with the octaves."""
    octaves = np.log2(bpm / PRIOR_CENTRE)
    return np.exp(-0.5 * (octaves / PRIOR_WIDTH) ** 2)


def refined_peak(values: NDArray[np.float64], best: int) -> float:
    """Return where the peak at ``best`` of ``values`` lies between the samples.

    A parabola is laid through the peak and its two neighbours; its top is the refined place. A
    peak at either end, or one that is not higher than its neighbours bend down to, stays at
    ``best``.
    """
    if not 0 < best < values.shape[0] - 1:
        return float(best)
    left, peak, right = values[best - 1], values[best], values[best + 1]
    curvature = left - 2 * peak + right
    if curvature >= 0:
        return float(best)
    return best + 0.5 * (left - right) / curvature


def estimate_tempo(samples: Samples, rate: int = SAMPLE_RATE) -> Tempo:
    """Estimate the one tempo of a song.

    Args:
        samples: The song as mono samples.
        rate: Their sample rate; it must be ``SAMPLE_RATE``, the rate the analysis is tuned for.

    Returns:
        The tempo and its clarity. ``bpm`` is ``None`` when the clarity is below ``MIN_CLARITY``
        or the song is shorter than ``MIN_SECONDS``.

    Raises:
        ValueError: If ``rate`` is not ``SAMPLE_RATE``.
    """
    if rate != SAMPLE_RATE:
        raise ValueError(f"the tempo is estimated at {SAMPLE_RATE} Hz, not {rate} Hz")
    if samples.shape[0] < MIN_SECONDS * rate:
        return UNCLEAR
    peak = float(np.max(np.abs(samples)))
    if peak == 0.0:
        return UNCLEAR
    curve = onset_strength(samples / np.float32(peak))  # the same tempo at any level
    frame_seconds = HOP / rate
    ac = autocorrelation(curve)
    first = int(np.ceil(60.0 / (MAX_BPM * frame_seconds)))
    last = int(np.floor(60.0 / (MIN_BPM * frame_seconds)))  # MIN_SECONDS leaves far more lags
    lags = np.arange(first, last + 1, dtype=np.float64)
    bpm = 60.0 / (lags * frame_seconds)
    window = ac[first : last + 1]
    best = int(np.argmax(window * tempo_weight(bpm)))
    lag = first + refined_peak(window, best)
    peak = window[best]
    clarity = float(max(peak - np.median(window), 0.0))
    if clarity < MIN_CLARITY:
        return Tempo(bpm=None, clarity=round(clarity, 4))
    return Tempo(bpm=round(float(60.0 / (lag * frame_seconds)), 2), clarity=round(clarity, 4))


def countdown_beat(bpm: float, count: int) -> float:
    """Return the length of one beat of a countdown of ``count`` beats, in seconds.

    The beat of the tempo is doubled while ``count`` beats would last less than
    ``MIN_COUNTDOWN``, and halved while they would last more than ``MAX_COUNTDOWN``. The window
    is wider than a factor of two, so a fitting length always exists.

    Args:
        bpm: The tempo in beats per minute (positive).
        count: The number of beats (positive).

    Raises:
        ValueError: If ``bpm`` or ``count`` is not positive.
    """
    if bpm <= 0 or count <= 0:
        raise ValueError("the tempo and the number of beats must be positive")
    beat = 60.0 / bpm
    while count * beat < MIN_COUNTDOWN:
        beat *= 2
    while count * beat > MAX_COUNTDOWN:
        beat /= 2
    return beat


def countdown_end(sing_start: float, beat: float | None) -> float:
    """Return when the countdown before a line ends.

    A countdown in beats ends one beat before the line, so the singing starts on the beat after
    the last step (ADR-0028); one in seconds (no tempo) ends at the line's start.

    Args:
        sing_start: When the line starts to be sung.
        beat: The countdown's beat (from ``countdown_beat``), or ``None`` without a tempo.
    """
    return sing_start if beat is None else sing_start - beat
