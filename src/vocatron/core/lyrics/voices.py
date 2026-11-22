"""Which lines are sung by the second voice, as far as the lyrics file tells (ADR-0052).

A second voice sings a different line while the first is still singing. The file tells it in two
ways: a line marked ``{&}`` (``Line.voice``), and two lines with the same ``.lrc`` time, of which
the later one is the second voice. The audio adds more (``vocatron.core.alignment.voices``).
"""

from collections.abc import Sequence
from typing import Literal

from vocatron.core.lyrics.document import FIRST_VOICE, SECOND_VOICE, Line, Voice

Source = Literal["mark", "time"]
"""Where a second-voice line of the file comes from: ``mark`` (``{&}``) or ``time`` (the same
``.lrc`` time as the line before)."""


def same_time(times: Sequence[float | None]) -> list[bool]:
    """Tell for every line whether it has the time of the line before (a line without one: no).

    Of three lines with one time only the second counts: a run of equal times is two voices at
    most, so the third line is not on a voice of its own.

    Args:
        times: The line times, ``None`` for a line without one.
    """
    found: list[bool] = []
    for index, time in enumerate(times):
        earlier = index > 0 and found[index - 1]
        found.append(time is not None and index > 0 and times[index - 1] == time and not earlier)
    return found


def voices_of(lines: Sequence[Line]) -> list[Voice]:
    """Return every line's voice: ``2`` if marked ``{&}`` or with the time of the line before."""
    shared = same_time([line.time for line in lines])
    return [
        SECOND_VOICE if line.voice == SECOND_VOICE or later else FIRST_VOICE
        for line, later in zip(lines, shared, strict=True)
    ]


def source_of(times: Sequence[float | None], voices: Sequence[int]) -> dict[int, Source]:
    """Say where each second-voice line comes from: the index of the line and ``mark`` or ``time``.

    A line with the time of the one before counts as ``time`` even if it is also marked.
    """
    shared = same_time(times)
    return {
        index: "time" if shared[index] else "mark"
        for index, voice in enumerate(voices)
        if voice == SECOND_VOICE
    }
