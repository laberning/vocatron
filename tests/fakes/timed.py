"""Timed lyrics for the layout tests: syllables with times, made from text or generated.

The generator lives in ``vocatron.core.layout.sample`` (the profile check uses it too).
``timed_from_line_times`` times real ``.lrc`` lines for the duet corpus test; a line without a
time (a corrected file may leave the times it does not know out) follows the line before.
"""

from collections.abc import Sequence

from vocatron.core.layout.sample import (
    LINE_GAP,
    WORD_GAP,
    WORD_LETTER_SECONDS,
    WORD_SECONDS,
    TimedSong,
    timed_song,
)
from vocatron.core.lyrics.file import LyricLine
from vocatron.core.syllables import Syllable, SyllableWord

__all__ = [
    "LINE_GAP",
    "WORD_GAP",
    "WORD_LETTER_SECONDS",
    "WORD_SECONDS",
    "TimedSong",
    "timed_from_line_times",
    "timed_song",
]

LAST_LINE_SECONDS = 4.0  # the length of the last line when timed from line times
LONGEST_LINE_SECONDS = 6.0  # no line timed from line times is longer
SHORTEST_LINE_SECONDS = 0.05  # nor shorter
LINE_TIME_GAP = 0.02  # seconds between the end of a line and the start of the next one


def timed_from_line_times(lines: Sequence[LyricLine]) -> list[SyllableWord]:
    """Time the words of each line evenly from its line time to just before the next line time.

    Like the alignment (one path through the words in order), a line never starts before the line
    before it has ended: two lines with one time tag are sung one after the other. A line without
    a time starts where the line before ended (the first line at 0 s), and a line followed by one
    without a time lasts at most ``LAST_LINE_SECONDS``. Each word is one syllable.

    Args:
        lines: The lyrics lines; ``time`` may be ``None``.
    """
    words: list[SyllableWord] = []
    free = 0.0  # when the line before has ended
    for index, line in enumerate(lines):
        start = free if line.time is None else max(line.time, free)
        following = lines[index + 1].time if index + 1 < len(lines) else None
        later = next((other.time for other in lines[index + 1 :] if other.time is not None), None)
        room = LAST_LINE_SECONDS if following is None else following - start - LINE_TIME_GAP
        if later is not None:
            room = min(room, later - start - LINE_TIME_GAP)
        length = max(min(room, LONGEST_LINE_SECONDS), SHORTEST_LINE_SECONDS)
        pieces = line.text.split()
        step = length / len(pieces)
        for number, piece in enumerate(pieces):
            begin, end = start + number * step, start + (number + 1) * step
            words.append(
                SyllableWord(
                    line=index,
                    text=piece,
                    start=begin,
                    end=end,
                    estimated=True,
                    syllables=[Syllable(text=piece, start=begin, end=end)],
                )
            )
        free = start + length + LINE_TIME_GAP
    return words
