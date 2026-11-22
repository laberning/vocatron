"""Measured words end where the voice stops (ADR-0013).

The acoustic model hears the last letter of a word for about one frame, so a measured word ends
before the singer does. With the voice activity of ADR-0012, the end of a measured word moves to
the end of the voiced run that holds its last letter, but never past the next word's start and
never more than ``MAX_HOLD_SECONDS`` after the last letter. Starts and letters never change, an
end only moves later, and estimated words keep their times. Pure, no randomness.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from statistics import median

from vocatron.core.alignment.estimate import Timed
from vocatron.core.alignment.voice import VoiceActivity

MAX_HOLD_SECONDS = 4.0
"""The longest a word is held past its last letter: a guard against an outro or an ad-lib that
the voice runs into, not a tuned value."""


@dataclass(frozen=True)
class Held:
    """The words of a song after the ends were moved.

    Attributes:
        words: The words in order; only ends of measured words differ from the input.
        held: How many measured words ended later than before.
        median_move: The median move of those ends in seconds (0 without moves).
    """

    words: list[Timed]
    held: int = 0
    median_move: float = 0.0


def _run_end(voice: VoiceActivity, moment: float) -> float | None:
    """Return the end of the voiced run that contains ``moment``, or ``None`` in silence."""
    for begin, end in voice.spans:
        if begin <= moment < end:
            return end
        if begin > moment:
            break
    return None


def hold_ends(words: Sequence[Timed], voice: VoiceActivity, seconds_per_frame: float) -> Held:
    """Move the end of every measured word to where its voice stops.

    Args:
        words: The settled words, in order and without overlaps.
        voice: Where the voice sounds.
        seconds_per_frame: The length of a frame; the last letter counts as voiced at the
            middle of its last frame.

    Returns:
        The words with their new ends and how far the ends moved.
    """
    out: list[Timed] = []
    moves: list[float] = []
    for index, original in enumerate(words):
        word = original
        if word.estimated or not word.letters:
            out.append(word)
            continue
        last = word.letters[-1][1]
        run_end = _run_end(voice, last - seconds_per_frame / 2)
        if run_end is None:
            out.append(word)
            continue
        limit = words[index + 1].start if index + 1 < len(words) else run_end
        end = min(run_end, limit, last + MAX_HOLD_SECONDS)
        if end > word.end:
            moves.append(end - word.end)
            word = replace(word, end=end)
        out.append(word)
    return Held(out, len(moves), median(moves) if moves else 0.0)
