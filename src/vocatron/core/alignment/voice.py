"""Where the singing voice sounds: voice activity from the loudness of the lead vocals (ADR-0012).

The loudness per frame comes from the acoustic worker. The threshold is taken from the song
itself: a low percentile of the loudness inside the confidently measured words, but never closer
to the noise floor than a margin. A song whose contrast between voice and floor is small, or
whose voiced share is odd, is not trusted (a lead stem full of backing vocals or bleed), and the
caller falls back to the earlier placement. Pure NumPy, no randomness.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

VOICE_PERCENTILE = 20.0
"""The percentile of the loudness inside confident words that the threshold starts from: low
enough to count consonants and soft word ends as voice, high enough to ignore a stray frame."""
VOICE_MARGIN_DB = 6.0
"""How far below that percentile the threshold lies (half the amplitude), so the quiet parts of a
sung word still count as voiced."""
FLOOR_PERCENTILE = 10.0
"""The percentile of all frames taken as the noise floor (a song has pauses; 10 % are quietest)."""
FLOOR_MARGIN_DB = 6.0
"""The threshold is at least this far above the noise floor, so noise never counts as voice."""
MIN_CONTRAST_DB = 15.0
"""Plausible only if the median loudness inside confident words is this far above the floor; a
clean lead stem has 30 dB or more, bleed and backing vocals shrink it."""
MIN_VOICED_SHARE = 0.10
"""Plausible only if at least this share of the frames is voiced (a song is not instrumental)."""
MAX_VOICED_SHARE = 0.95
"""Plausible only if at most this share of the frames is voiced (a song has pauses)."""
MIN_CONFIDENT_SECONDS = 1.0
"""Confident words must cover this many seconds, or the song's own levels are not known."""
CONFIDENT_WORD = 0.5
"""A measured word with at least this confidence tells the song's own levels and speed."""
CLOSE_HOLE_SECONDS = 0.15
"""An unvoiced hole shorter than this inside the voice (a consonant, a breath) is closed."""
MIN_VOICED_SECONDS = 0.1
"""A voiced island shorter than this (a click, a breath) is dropped."""

USED = "used"
SWITCHED_OFF = "switched off"
NO_LOUDNESS = "no loudness"
TOO_LITTLE_SINGING = "too little confident singing"
LOW_CONTRAST = "low contrast"
ODD_SHARE = "voiced share out of range"


@dataclass(frozen=True)
class VoiceActivity:
    """Where the voice sounds in a song.

    Attributes:
        spans: The voiced stretches in seconds, ordered and apart from each other.
    """

    spans: tuple[tuple[float, float], ...]

    def voiced_fraction(self, start: float, end: float) -> float:
        """Return the share of ``[start, end)`` that is voiced (0 for an empty interval)."""
        if end <= start:
            return 0.0
        covered = sum(max(min(b, end) - max(a, start), 0.0) for a, b in self.spans)
        return covered / (end - start)


@dataclass(frozen=True)
class Detection:
    """The outcome of the voice detection for one song.

    Attributes:
        activity: The voice, or ``None`` when it is not plausible or not known.
        reason: ``USED``, or the fixed phrase that says why not.
        threshold_db: The threshold found (0 if none).
        voiced_share: The share of voiced frames (0 if none).
    """

    activity: VoiceActivity | None
    reason: str
    threshold_db: float = 0.0
    voiced_share: float = 0.0


def voiced_runs(mask: NDArray[np.bool_]) -> list[tuple[int, int]]:
    """Return the ``(first, stop)`` frames of the runs of ``True`` in ``mask``."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2], strict=True)]


def smooth(mask: NDArray[np.bool_], close_frames: int, min_frames: int) -> NDArray[np.bool_]:
    """Close unvoiced holes shorter than ``close_frames``, then drop islands under ``min_frames``.

    Holes at the start or the end of the song are not closed.
    """
    runs = voiced_runs(mask)
    out = np.zeros_like(mask)
    merged: list[list[int]] = []
    for first, stop in runs:
        if merged and first - merged[-1][1] < close_frames:
            merged[-1][1] = stop
        else:
            merged.append([first, stop])
    for first, stop in merged:
        if stop - first >= min_frames:
            out[first:stop] = True
    return out


def _frames(start: float, end: float, seconds_per_frame: float, total: int) -> tuple[int, int]:
    """Return the frames ``[first, stop)`` of ``[start, end)``: at least one, inside the song."""
    first = min(max(int(start / seconds_per_frame), 0), total - 1)
    stop = min(max(int(np.ceil(end / seconds_per_frame)), first + 1), total)
    return first, stop


def find_voice(
    loudness: NDArray[np.float32],
    seconds_per_frame: float,
    confident: Sequence[tuple[float, float]],
) -> Detection:
    """Find where the voice sounds in a song, if its levels can be trusted.

    The check does not use the threshold's own frames: it compares the median loudness inside
    the confident words with the noise floor of the whole song, and looks at the voiced share.

    Args:
        loudness: The loudness per frame in dBFS.
        seconds_per_frame: The length of a frame.
        confident: Start and end in seconds of the confidently measured words.

    Returns:
        The detection; ``activity`` is ``None`` with the reason when the song is not plausible.
    """
    total = len(loudness)
    if total == 0:
        return Detection(None, NO_LOUDNESS)
    inside = [
        loudness[a:b] for a, b in (_frames(s, e, seconds_per_frame, total) for s, e in confident)
    ]
    sung = np.concatenate(inside) if inside else np.empty(0, dtype=np.float32)
    if len(sung) * seconds_per_frame < MIN_CONFIDENT_SECONDS:
        return Detection(None, TOO_LITTLE_SINGING)
    floor = float(np.percentile(loudness, FLOOR_PERCENTILE, method="lower"))
    contrast = float(np.percentile(sung, 50.0, method="lower")) - floor
    if contrast < MIN_CONTRAST_DB:
        return Detection(None, LOW_CONTRAST)
    voice = float(np.percentile(sung, VOICE_PERCENTILE, method="lower"))
    threshold = max(voice - VOICE_MARGIN_DB, floor + FLOOR_MARGIN_DB)
    mask = smooth(
        loudness > threshold,
        round(CLOSE_HOLE_SECONDS / seconds_per_frame),
        round(MIN_VOICED_SECONDS / seconds_per_frame),
    )
    share = float(mask.mean())
    if not MIN_VOICED_SHARE <= share <= MAX_VOICED_SHARE:
        return Detection(None, ODD_SHARE, threshold, share)
    spans = tuple((a * seconds_per_frame, b * seconds_per_frame) for a, b in voiced_runs(mask))
    return Detection(VoiceActivity(spans), USED, threshold, share)
