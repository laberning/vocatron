"""Hearing the backing vocals where the lead is silent: which frames take its output (ADR-0014).

The separation sometimes puts a sung word into the backing vocals (a word shouted by several
voices). The model hears the lead and the backing in two passes; a frame takes the backing's row
only where the lead is silent and cannot have been heard, and the backing sounds. Everywhere
else the lead's row stays, so a song without such frames gives the lead's matrix unchanged.
Every row is a log-softmax over the same vocabulary, so the mixed matrix needs no
renormalisation. Pure NumPy, no randomness.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vocatron.core.alignment.chunks import Emissions
from vocatron.core.alignment.estimate import Timed
from vocatron.core.alignment.tokens import blank_id
from vocatron.core.alignment.voice import (
    CLOSE_HOLE_SECONDS,
    FLOOR_MARGIN_DB,
    FLOOR_PERCENTILE,
    MIN_VOICED_SECONDS,
    find_voice,
    smooth,
)

USED = "used"
SWITCHED_OFF = "switched off"
LEAD_NOT_PLAUSIBLE = "lead voice not plausible"
NO_FRAMES = "no backing frames"


@dataclass(frozen=True)
class BackingReport:
    """What became of the backing vocals in the model's ear.

    Attributes:
        reason: ``USED`` or the fixed phrase that says why not.
        frames: How many frames took the backing's output.
        words: How many measured words have most of their letters in those frames.
    """

    reason: str
    frames: int = 0
    words: int = 0


@dataclass(frozen=True)
class Mixed:
    """The emissions with the backing's rows where they were chosen.

    Attributes:
        log_probs: The lead's matrix with the swapped rows taken from the backing.
        swapped: Which frames took the backing's row.
        reason: ``USED``, or why no frame was swapped.
    """

    log_probs: NDArray[np.float32]
    swapped: NDArray[np.bool_]
    reason: str

    @property
    def frames(self) -> int:
        """The number of swapped frames."""
        return int(self.swapped.sum())


def span_mask(
    spans: Sequence[tuple[float, float]], seconds_per_frame: float, total: int
) -> NDArray[np.bool_]:
    """Return the frames covered by ``spans`` in seconds (each span rounded to whole frames)."""
    mask = np.zeros(total, dtype=np.bool_)
    for start, end in spans:
        mask[max(round(start / seconds_per_frame), 0) : max(round(end / seconds_per_frame), 0)] = (
            True
        )
    return mask


def mix_backing(emissions: Emissions, confident: Sequence[tuple[float, float]]) -> Mixed:
    """Choose the frames that take the backing's output.

    A frame is swapped when all of these hold: the lead is silent there (outside its own voice,
    found on the lead's loudness with the ``confident`` words of the lead pass); the lead's
    output is blank there; the frame lies in no confident word of the lead pass; the backing
    sounds (above the lead's threshold and ``FLOOR_MARGIN_DB`` above its own floor, smoothed
    like the voice); and the swapped run is at least ``MIN_VOICED_SECONDS`` long.

    Args:
        emissions: The lead's output, with ``backing`` set.
        confident: Start and end in seconds of the confidently measured words of the lead pass.

    Returns:
        The mixed matrix, the swapped frames and the reason; with no swapped frame the lead's
        matrix itself.

    Raises:
        ValueError: If ``emissions`` has no backing part or its parts differ in length.
    """
    part = emissions.backing
    if part is None:
        raise ValueError("the emissions carry no backing part")
    lead = emissions.log_probs
    total = len(lead)
    shapes = {total, len(part.log_probs), len(part.lead_loudness), len(part.backing_loudness)}
    if len(shapes) != 1 or part.log_probs.shape != lead.shape:
        raise ValueError("the backing part does not have the lead's length")
    spf = emissions.seconds_per_frame
    none = np.zeros(total, dtype=np.bool_)
    detection = find_voice(part.lead_loudness, spf, confident)
    if detection.activity is None:
        return Mixed(lead, none, LEAD_NOT_PLAUSIBLE)
    shortest = round(MIN_VOICED_SECONDS / spf)
    sounds = backing_sounds(part.backing_loudness, detection.threshold_db, spf)
    silent = ~span_mask(detection.activity.spans, spf, total)
    blank = np.argmax(lead, axis=1) == blank_id(emissions.vocabulary)
    free = ~span_mask(confident, spf, total)
    swapped = smooth(silent & blank & free & sounds, 0, shortest)
    if not swapped.any():
        return Mixed(lead, none, NO_FRAMES)
    return Mixed(np.where(swapped[:, None], part.log_probs, lead), swapped, USED)


def backing_sounds(
    loudness: NDArray[np.float32], lead_threshold_db: float, seconds_per_frame: float
) -> NDArray[np.bool_]:
    """Return the frames where the backing sounds: above the lead's threshold and above its floor.

    The threshold is the lead's, but at least ``FLOOR_MARGIN_DB`` above the backing's own floor;
    the frames are smoothed like the voice (``CLOSE_HOLE_SECONDS``, ``MIN_VOICED_SECONDS``).
    """
    floor = float(np.percentile(loudness, FLOOR_PERCENTILE, method="lower"))
    threshold = max(lead_threshold_db, floor + FLOOR_MARGIN_DB)
    return smooth(
        loudness > threshold,
        round(CLOSE_HOLE_SECONDS / seconds_per_frame),
        round(MIN_VOICED_SECONDS / seconds_per_frame),
    )


def second_voice_rows(
    emissions: Emissions,
    lead: NDArray[np.float32],
    confident: Sequence[tuple[float, float]],
    bounded: bool,
) -> NDArray[np.float32]:
    """Return the matrix a second voice is aligned on: the backing's rows where it sounds.

    Where the backing is silent, or when the lead's voice is not plausible and so no threshold is
    known, the row is that of ``lead`` (the matrix of the first voice). That is only safe when the
    search of the second voice is confined to windows: without them (``bounded`` false) the lead's
    rows would hold the letters of the other voice's lines for the whole song, so the backing's
    matrix is taken as it is.

    Args:
        emissions: The emissions with the backing part (``None`` gives ``lead``).
        lead: The matrix of the first voice, the lead's with the backing mixed in (``mix_backing``).
        confident: Start and end in seconds of the confidently measured words of the lead pass.
        bounded: Whether the search is confined to windows of line times.
    """
    part = emissions.backing
    if part is None:
        return lead
    if not bounded:
        return part.log_probs
    detection = find_voice(part.lead_loudness, emissions.seconds_per_frame, confident)
    if detection.activity is None:
        return lead
    sounds = backing_sounds(
        part.backing_loudness, detection.threshold_db, emissions.seconds_per_frame
    )
    return np.where(sounds[:, None], part.log_probs, lead)


def words_in(swapped: NDArray[np.bool_], words: Sequence[Timed], seconds_per_frame: float) -> int:
    """Count the measured words whose letters lie mostly in the swapped frames."""
    inside = np.concatenate(([0], np.cumsum(swapped)))
    count = 0
    for word in words:
        if word.estimated or not word.letters:
            continue
        spans = [
            (
                round(a / seconds_per_frame),
                max(round(b / seconds_per_frame), round(a / seconds_per_frame) + 1),
            )
            for a, b in word.letters
        ]
        covered = sum(
            int(inside[min(b, len(swapped))] - inside[min(a, len(swapped))]) for a, b in spans
        )
        if 2 * covered > sum(b - a for a, b in spans):
            count += 1
    return count
