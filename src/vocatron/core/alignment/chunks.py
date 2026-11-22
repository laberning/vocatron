"""Pieces of 30 seconds for the acoustic model, and stitching their frames (ADR-0002).

A whole song in one pass needs too much memory on long songs, so the model sees overlapping
pieces. The frames of the pieces are put together by index: in the overlap, the first piece is
used up to the middle and the second from there on, so no frame is taken from the unreliable end
of a piece.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

SAMPLE_RATE = 16000
"""The sample rate wav2vec2 models expect."""
STRIDE = 320
"""Samples between two output frames of wav2vec2 (20 ms)."""
FIELD = 400
"""Samples one output frame looks at."""
SILENCE_DB = -100.0
"""The loudness reported for digital silence (and the lowest value ``frame_loudness`` gives)."""


@dataclass(frozen=True)
class BackingPart:
    """What the acoustic model made of the backing vocals (ADR-0014).

    Attributes:
        log_probs: The log-probabilities of the backing vocals, shaped like the lead's.
        lead_loudness: The loudness of the lead vocals alone per frame in dBFS.
        backing_loudness: The loudness of the backing vocals alone per frame in dBFS (the backing
            padded or trimmed to the lead's length first).
    """

    log_probs: NDArray[np.float32]
    lead_loudness: NDArray[np.float32]
    backing_loudness: NDArray[np.float32]


@dataclass(frozen=True)
class Emissions:
    """What the acoustic model made of a song.

    Attributes:
        log_probs: The log-probabilities shaped (frames, vocabulary).
        seconds_per_frame: How long a frame is.
        vocabulary: The model's tokens by id (the CTC blank is ``<pad>``).
        loudness: The loudness of the vocals per frame in dBFS (``frame_loudness``), shaped
            (frames,) like ``log_probs``; ``None`` when not known (no voice activity then). With
            ``alignment.voice_source: vocals`` it is the loudness of lead and backing added.
        backing: The model's output on the backing vocals with the loudness of each stem alone;
            ``None`` when the backing was not heard (``alignment.hear_backing`` off).
    """

    log_probs: NDArray[np.float32]
    seconds_per_frame: float
    vocabulary: tuple[str, ...]
    loudness: NDArray[np.float32] | None = None
    backing: BackingPart | None = None


@dataclass(frozen=True)
class Piece:
    """One piece of audio for the model.

    Attributes:
        start: Its first sample (a multiple of ``STRIDE``, so frames line up with the song's).
        stop: Its end (exclusive).
    """

    start: int
    stop: int

    @property
    def first_frame(self) -> int:
        """The index of the piece's first frame in the whole song."""
        return self.start // STRIDE


def frame_count(samples: int) -> int:
    """Return how many frames the model makes of ``samples`` samples (0 if too short)."""
    return 0 if samples < FIELD else (samples - FIELD) // STRIDE + 1


def fit_length(wave: NDArray[np.float32], samples: int) -> NDArray[np.float32]:
    """Return ``wave`` trimmed or padded with zeros at the end to exactly ``samples`` samples."""
    if len(wave) >= samples:
        return wave[:samples]
    return np.concatenate((wave, np.zeros(samples - len(wave), dtype=np.float32)))


def sum_waves(first: NDArray[np.float32], second: NDArray[np.float32]) -> NDArray[np.float32]:
    """Return the two waves added sample by sample; the shorter one is padded with zeros.

    This is how lead and backing vocals become the one signal whose loudness says where anybody
    sings (``alignment.voice_source: vocals``, ADR-0012).
    """
    length = max(len(first), len(second))
    total = np.zeros(length, dtype=np.float32)
    total[: len(first)] += first
    total[: len(second)] += second
    return total


def frame_loudness(wave: NDArray[np.float32]) -> NDArray[np.float32]:
    """Return the RMS loudness of every model frame of ``wave`` in dBFS (ADR-0012).

    Frame ``t`` covers the same samples as the model's frame ``t`` (``FIELD`` samples, every
    ``STRIDE``), so the result has ``frame_count`` entries. Digital silence gives ``SILENCE_DB``.

    Args:
        wave: The mono samples before any normalisation, so that levels mean something.

    Returns:
        One loudness per frame; empty if the wave is shorter than a frame.
    """
    count = frame_count(len(wave))
    if count == 0:
        return np.empty(0, dtype=np.float32)
    windows = np.lib.stride_tricks.sliding_window_view(wave, FIELD)[::STRIDE][:count]
    rms = np.sqrt(np.mean(np.square(windows, dtype=np.float32), axis=1, dtype=np.float32))
    floor = np.float32(10.0 ** (SILENCE_DB / 20.0))
    level = 20.0 * np.log10(np.maximum(rms, floor))
    # The floor itself is SILENCE_DB exactly: log10 in float32 rounds differently on other CPUs.
    return np.where(rms > floor, level, SILENCE_DB).astype(np.float32)


def plan_pieces(samples: int, piece_seconds: float, overlap_seconds: float) -> list[Piece]:
    """Plan overlapping pieces that cover ``samples`` samples.

    Args:
        samples: The length of the audio.
        piece_seconds: The length of a piece.
        overlap_seconds: How much consecutive pieces share.

    Returns:
        The pieces; the last may be shorter, but is at least as long as the overlap.

    Raises:
        ValueError: If the audio is too short for a frame, or the overlap is not shorter than
            the piece.
    """
    length = round(piece_seconds * SAMPLE_RATE) // STRIDE * STRIDE
    step = length - round(overlap_seconds * SAMPLE_RATE) // STRIDE * STRIDE
    if frame_count(samples) == 0:
        raise ValueError(f"{samples} samples are too short for the acoustic model")
    if length < FIELD or step <= 0:
        raise ValueError("the overlap must be shorter than a piece, and a piece not tiny")
    pieces: list[Piece] = []
    start = 0
    while True:
        stop = min(start + length, samples)
        pieces.append(Piece(start, stop))
        if stop == samples:
            return pieces
        start += step


def stitch(parts: Sequence[tuple[int, NDArray[np.float32]]], total: int) -> NDArray[np.float32]:
    """Put the frames of overlapping pieces together.

    Args:
        parts: For each piece in order its first frame and its frames shaped (frames, vocabulary).
        total: The number of frames of the whole song.

    Returns:
        The frames of the song, shaped (total, vocabulary).

    Raises:
        ValueError: If there are no pieces, or they leave a gap or do not end at ``total``.
    """
    if not parts:
        raise ValueError("no pieces to stitch")
    out = np.empty((total, parts[0][1].shape[1]), dtype=np.float32)
    cursor = 0
    for index, (first, frames) in enumerate(parts):
        end = first + len(frames)
        if index + 1 < len(parts):
            end = min(end, (parts[index + 1][0] + end) // 2)  # the middle of the overlap
        elif end != total:
            raise ValueError(f"the pieces end at frame {end}, not at {total}")
        if first > cursor:
            raise ValueError(f"the pieces leave a gap before frame {first}")
        out[cursor:end] = frames[cursor - first : end - first]
        cursor = end
    return out
