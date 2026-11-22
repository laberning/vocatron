"""The timed lyrics as enhanced LRC: a time tag per line and one per word (ADR-0008, ADR-0009).

The file is the ADR-0008 ``.lrc`` format written by ``vocatron.core.lyrics.document``; the word
tags ``<mm:ss.xx>`` stand in the text of each line, and one more ends the line. Singer marks
(ADR-0018) stand where the singers change, also inside a line; ``{&}`` stands before a line the
second voice sings (ADR-0052). The lines are in time order, so two voices that overlap come out
as the file is read: the line that starts first first. Readers of the format that do not know
word tags ignore them.
"""

from collections.abc import Sequence
from itertools import groupby
from typing import NamedTuple

from vocatron.core.lyrics.document import (
    FIRST_VOICE,
    Document,
    Line,
    Mark,
    SingerInfo,
    Voice,
    format_time,
    write,
)
from vocatron.core.lyrics.file import LyricLine
from vocatron.core.syllables import SyllableWord

SECONDS_PER_MINUTE = 60


def _tag(seconds: float) -> str:
    """Write a word time tag."""
    return f"<{format_time(seconds)}>"


class Heading(NamedTuple):
    """What the header tags of the file say.

    Attributes:
        title: The title for the ``ti`` tag.
        artist: The artist for the ``ar`` tag, if known.
        duration: The length of the song in seconds for the ``length`` tag, if known.
    """

    title: str
    artist: str | None = None
    duration: float | None = None


def _voice_of(lines: Sequence[LyricLine], index: int) -> Voice:
    """Return the voice of lyrics line ``index`` (the first voice for a line that is not there)."""
    return lines[index].voice if index < len(lines) else FIRST_VOICE


def enhanced_lrc(
    words: Sequence[SyllableWord],
    lines: Sequence[LyricLine],
    heading: Heading,
    singers: dict[int, SingerInfo],
    offset: float = 0.0,
    voices: Sequence[Voice] = (),
) -> str:
    """Write the enhanced LRC of a song.

    Args:
        words: Every word with its times (``syllables.json``).
        lines: The cleaned lyrics lines, which a word's ``line`` indexes into.
        heading: Title, artist and length for the header tags.
        singers: Names and colours of the singers.
        offset: Seconds added to every time tag and to the length: the silent intro
            before the song (ADR-0020), so the file fits the video.
        voices: The voice of every line (``syllables.json``), also those the audio found; without
            one a line has the voice ``lines`` give it. A second-voice line is written with
            ``{&}``.
    """
    tags = [("ti", heading.title)]
    if heading.artist:
        tags.append(("ar", heading.artist))
    if heading.duration is not None:
        whole = round(heading.duration + offset)
        tags.append(("length", f"{whole // SECONDS_PER_MINUTE}:{whole % SECONDS_PER_MINUTE:02d}"))
    written: list[Line] = []
    singing = "1"
    groups = [list(group) for _, group in groupby(words, key=lambda word: word.line)]
    for members in sorted(groups, key=lambda members: members[0].start):  # time order, stable
        index = members[0].line
        who = lines[index].singers if index < len(lines) else singing
        text = " ".join(f"{_tag(word.start + offset)}{word.text}" for word in members)
        text += f" {_tag(members[-1].end + offset)}"
        turns = [
            turn
            for turn in (lines[index].turns if index < len(lines) else [])
            if turn.word < len(members)
        ]
        marks = [Mark(word=0, singers=who)] if who != singing else []
        marks += [Mark(word=turn.word, singers=turn.singers) for turn in turns]
        voice = voices[index] if index < len(voices) else _voice_of(lines, index)
        written.append(
            Line(text=text, marks=tuple(marks), voice=voice, time=members[0].start + offset)
        )
        singing = turns[-1].singers if turns else who
    document = Document(kind="lrc", tags=tuple(tags), singers=singers, lines=tuple(written))
    return write(document)
