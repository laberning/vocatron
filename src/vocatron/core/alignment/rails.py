"""Line times of an ``.lrc`` as guide rails for the alignment (ADR-0008).

The times of a human-made ``.lrc`` are hints. They are first compared with where the lines start
when the alignment searches without them: if they differ by one steady offset, the hints are
shifted by it and narrow the search to a window around each line; if they disagree, they are
ignored. The alignment always has the last word.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from vocatron.core.lyrics.document import FIRST_VOICE, Voice, format_time
from vocatron.core.lyrics.voices import same_time

Rails = Literal["none", "shifted", "ignored"]
"""``none``: no usable times; ``shifted``: used after correcting an offset; ``ignored``: they do
not fit the singing."""

MAX_SPREAD = 0.3
"""The median absolute deviation from the offset may be at most this many seconds."""
NEAR = 0.5
"""A line is near the offset when it is within this many seconds of it."""
MIN_NEAR_SHARE = 0.6
"""At least this share of the lines must be near the offset."""
MARGIN = 1.5
"""How far a line may start before its corrected time, and a line end after the next one."""
MIN_LINES = 3
"""Fewer lines with a time say too little about the whole song."""
REACH = 3.0
"""How far a second-voice line may run past the time of the next line of any voice (ADR-0052)."""
SLOT_REACH = 0.2
"""How far lines that share one ``.lrc`` time may run past the time of the next line: the file
puts them in one slot, and the next time ends it (ADR-0052)."""


@dataclass(frozen=True)
class RailCheck:
    """What the comparison of hints and singing found.

    Attributes:
        rails: ``none``, ``shifted`` or ``ignored``.
        offset: Seconds the singing lies after the hints (median); 0 for ``none``.
        compared: How many lines had both a hint and a found start.
        spread: The median absolute deviation from the offset in seconds.
        near: The share of lines within ``NEAR`` of the offset.
        dropped: Indices of the lines whose hints broke the order of the lines and were left out
            (``in_order``); kept for every outcome.
    """

    rails: Rails
    offset: float = 0.0
    compared: int = 0
    spread: float = 0.0
    near: float = 0.0
    dropped: tuple[int, ...] = ()


@dataclass(frozen=True)
class Order:
    """The hints that stay after the order check.

    Attributes:
        kept: One entry per line: its hint, or ``None`` for a line without one or a dropped hint.
        dropped: Indices of the lines whose hints were dropped, ascending.
    """

    kept: list[float | None]
    dropped: tuple[int, ...]


def in_order(hints: Sequence[float | None], starts: Sequence[float | None] | None = None) -> Order:
    """Keep the largest set of hints that is in order and drop the others.

    The hinted lines must have non-decreasing times (equal times are in order). Of several sets of
    the same size, the one whose hints lie closest to ``starts`` (the line starts of the pass
    without hints, after the median offset of all pairs) stays, so of two hints that contradict
    each other the one further from the singing is dropped. Without ``starts``, or when still
    equal, the later line is dropped. Hints in order come back unchanged.

    Args:
        hints: The line times of the ``.lrc`` (``None`` for a line without one).
        starts: Where each line starts according to the alignment without hints.

    Returns:
        The kept hints (``None`` where dropped) and the indices of the dropped lines.
    """
    deviation = _deviations(hints, starts)
    indices = [i for i, h in enumerate(hints) if h is not None]
    # best[k]: (size, -deviation, -index sum) of the best chain ending at indices[k]
    best: list[tuple[int, int, int]] = []
    before: list[int | None] = []
    for k, i in enumerate(indices):
        step = (1, -deviation[i], -i)
        previous: int | None = None
        score = step
        for j in range(k):
            if (hints[indices[j]] or 0.0) <= (hints[i] or 0.0):
                candidate = (best[j][0] + 1, best[j][1] + step[1], best[j][2] + step[2])
                if candidate > score:
                    previous, score = j, candidate
        best.append(score)
        before.append(previous)
    kept: set[int] = set()
    cursor = max(range(len(indices)), key=best.__getitem__, default=None)
    while cursor is not None:
        kept.add(indices[cursor])
        cursor = before[cursor]
    dropped = tuple(i for i in indices if i not in kept)
    return Order([None if i in dropped else h for i, h in enumerate(hints)], dropped)


def skipped_note(line: int, time: str) -> str:
    """Say which hint was dropped for breaking the order (one place for the wording)."""
    return f"line {line}: time {time} is out of order, skipped"


def order_notes(times: Sequence[float | None]) -> list[str]:
    """Return one note per line time that breaks the order of the lines.

    This is the check of ``in_order`` without the singing to compare with.
    """
    return [
        skipped_note(index + 1, format_time(times[index] or 0.0))
        for index in in_order(times).dropped
    ]


def _deviations(hints: Sequence[float | None], starts: Sequence[float | None] | None) -> list[int]:
    """Return how far each hint lies from its line start after the median offset, in microseconds.

    A line without a hint or a start, and every line when ``starts`` is ``None``, gets 0.
    """
    result = [0] * len(hints)
    if starts is None:
        return result
    pairs = {
        i: s - h
        for i, (s, h) in enumerate(zip(starts, hints, strict=True))
        if s is not None and h is not None
    }
    if not pairs:
        return result
    offset = float(np.median(list(pairs.values())))
    for i, difference in pairs.items():
        result[i] = round(abs(difference - offset) * 1_000_000)
    return result


def check_rails(starts: Sequence[float | None], hints: Sequence[float | None]) -> RailCheck:
    """Compare the line starts found without hints with the hints.

    Args:
        starts: Where each line starts according to the unconstrained alignment.
        hints: The line times of the ``.lrc`` (``None`` for a line without one).

    Returns:
        ``none`` with fewer than ``MIN_LINES`` comparable lines; ``shifted`` when the differences
        are consistent (spread and near share within the limits); else ``ignored``.
    """
    pairs = [(s, h) for s, h in zip(starts, hints, strict=True) if s is not None and h is not None]
    if len(pairs) < MIN_LINES:
        return RailCheck("none", compared=len(pairs))
    differences = np.array([s - h for s, h in pairs])
    offset = float(np.median(differences))
    deviations = np.abs(differences - offset)
    spread = float(np.median(deviations))
    near = float(np.mean(deviations <= NEAR))
    fits = spread <= MAX_SPREAD and near >= MIN_NEAR_SHARE
    return RailCheck("shifted" if fits else "ignored", offset, len(pairs), spread, near)


def line_windows(
    hints: Sequence[float | None], offset: float, duration: float
) -> list[tuple[float, float]]:
    """Return the time window each line must lie in, in seconds.

    A line may start ``MARGIN`` before its corrected time and end ``MARGIN`` after the corrected
    time of the next line with a hint. A line without a hint takes the window between the lines
    with hints around it. Corrected times are clamped to ``[0, duration]`` first, so a line hinted
    at or after the end still gets a window of ``MARGIN`` seconds ending at the end of the audio.
    Hints out of order never give an empty window: it is at least ``MARGIN`` long.

    Args:
        hints: The line times of the ``.lrc``.
        offset: The offset to add to them.
        duration: The length of the audio.

    Returns:
        One ``(first, last)`` second per line.
    """
    corrected = [None if h is None else min(max(h + offset, 0.0), duration) for h in hints]
    windows: list[tuple[float, float]] = []
    for index in range(len(corrected)):
        before = [c for c in corrected[: index + 1] if c is not None]
        after = [c for c in corrected[index + 1 :] if c is not None]
        low = max(before[-1] - MARGIN, 0.0) if before else 0.0
        high = min(after[0] + MARGIN, duration) if after else duration
        windows.append((low, max(high, min(low + MARGIN, duration))))  # unsorted hints: not empty
    return windows


def voice_windows(
    hints: Sequence[float | None], voices: Sequence[Voice], offset: float, duration: float
) -> list[tuple[float, float]]:
    """Return the time window of every line when a second voice sings (ADR-0052).

    Each voice has its own windows: the lines of one voice are taken as ``line_windows`` takes all
    lines, so a line's window ends at the next line of its voice. A second-voice line also ends at
    most ``REACH`` after the time of the next line of any voice, so a lone second-voice line does
    not search the rest of the song. Lines that share one time sing together in one slot: they
    end at most ``SLOT_REACH`` after the time of the next line, in both voices. With one voice
    and no shared time the result is that of ``line_windows``.

    Args:
        hints: The line times of the ``.lrc`` (``None`` for a line without one).
        voices: The voice of every line, ``1`` or ``2``.
        offset: The offset to add to the hints.
        duration: The length of the audio.

    Returns:
        One ``(first, last)`` second per line.
    """
    windows: list[tuple[float, float]] = [(0.0, duration)] * len(hints)
    corrected = [None if h is None else min(max(h + offset, 0.0), duration) for h in hints]
    later_of_pair = same_time(hints)
    slot = [
        later or (index + 1 < len(hints) and later_of_pair[index + 1])
        for index, later in enumerate(later_of_pair)
    ]
    for voice in sorted(set(voices)):
        members = [i for i, v in enumerate(voices) if v == voice]
        own = line_windows([hints[i] for i in members], offset, duration)
        for index, (low, high) in zip(members, own, strict=True):
            windows[index] = (low, high)
            time = corrected[index]
            later: list[float] = (
                [] if time is None else [c for c in corrected if c is not None and c > time]
            )
            reach = SLOT_REACH if slot[index] else (REACH if voice > FIRST_VOICE else None)
            if later and reach is not None:
                windows[index] = (
                    low,
                    max(min(high, min(later) + reach), min(low + MARGIN, duration)),
                )
    return windows


def crowded_lines(
    windows: Sequence[tuple[float, float]], voices: Sequence[Voice]
) -> frozenset[int]:
    """Return the lines whose window overlaps the window of a line of the other voice.

    Only there can one voice's search take words the other voice sings (ADR-0052): the first
    voice's search takes the second voice's words, and a second-voice line that the backing does
    not carry takes the first voice's. A line far from every line of the other voice has no such
    risk, whatever it sounds like. Windows that only touch at an edge do not overlap.

    Args:
        windows: The window of every line in seconds (``voice_windows``).
        voices: The voice of every line, ``1`` or ``2``.

    Returns:
        The indices of the lines to judge; empty with one voice.

    Raises:
        ValueError: If ``windows`` and ``voices`` differ in length.
    """
    return frozenset(
        index
        for index, ((low, high), voice) in enumerate(zip(windows, voices, strict=True))
        if any(
            other != voice and low < end and start < high
            for (start, end), other in zip(windows, voices, strict=True)
        )
    )
