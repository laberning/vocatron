"""Syllable times: the time of a word split across its syllables (ADR-0005).

A syllable starts where its first letter was found and lasts until the next syllable begins; the
last one ends with the word, so it also gets the time the word is held after its last letter
(ADR-0013). Where the letters of the syllables do not add up to the letters the model heard (a
number sung as a word), the heard part of the word is shared in proportion to the length of the
syllables and the last syllable is extended to the word's end; an estimated word shares its whole
time.
"""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from vocatron.core.alignment.file import AlignedWord
from vocatron.core.languages.base import LanguageModule
from vocatron.core.lyrics.document import Voice
from vocatron.core.stage_file import StageFile


class Syllable(BaseModel):
    """One sung syllable.

    Attributes:
        text: The syllable as written (the parts of a word join to the word).
        start: Seconds from the start of the song.
        end: Seconds from the start of the song.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    start: float
    end: float


class SyllableWord(BaseModel):
    """A word with its syllables.

    Attributes:
        line: The index of its line in ``lyrics.json``.
        text: The word as written.
        start: Seconds from the start of the song.
        end: Seconds from the start of the song.
        estimated: The word's time is interpolated, so the syllables are shared proportionally.
        syllables: Its syllables in order.
    """

    model_config = ConfigDict(extra="forbid")

    line: int
    text: str
    start: float
    end: float
    estimated: bool
    syllables: list[Syllable]


class SyllablesFile(StageFile):
    """``syllables.json``: when every syllable is sung.

    Attributes:
        language: The language module that split the words.
        words: Every word with its syllables, in order.
        voices: The voice of every line of ``lyrics.json`` (``alignment.json``): ``2`` for a line
            the second voice sings, from the file or found in the audio (ADR-0052), ``1`` for
            the others. Empty when the alignment has no line of that index.
    """

    SCHEMA_NAME: ClassVar[str] = "syllables"
    schema_version: Literal[1, 2] = 2  # a v1 file reads as v2: v2 only adds the voices
    language: str
    words: list[SyllableWord]
    voices: list[Voice] = Field(default_factory=list)


def _proportional(parts: list[str], start: float, end: float) -> list[tuple[float, float]]:
    """Share ``start`` to ``end`` among ``parts`` in proportion to their length."""
    total = sum(max(len(part), 1) for part in parts)
    edges = [start]
    for part in parts:
        edges.append(edges[-1] + (end - start) * max(len(part), 1) / total)
    edges[-1] = end
    return list(zip(edges, edges[1:], strict=False))


def _from_letters(
    word: AlignedWord, parts: list[str], module: LanguageModule
) -> list[tuple[float, float]] | None:
    """Return the span of each syllable from the letters found, or ``None`` if they do not fit."""
    counts = [len(module.normalise(part)) for part in parts]
    if word.estimated or 0 in counts or sum(counts) != len(word.letters):
        return None
    firsts = [sum(counts[:i]) for i in range(len(counts))]
    starts = [word.letters[first][0] for first in firsts]
    ends = [*starts[1:], word.end]  # a syllable lasts until the next one begins
    return list(zip(starts, ends, strict=True))


def _fallback(word: AlignedWord, parts: list[str]) -> list[tuple[float, float]]:
    """Share the heard part of the word among ``parts``; the last one also gets the held part."""
    spans = _proportional(parts, word.start, word.heard_end)
    first, _ = spans[-1]
    return [*spans[:-1], (first, word.end)]


def split_word(word: AlignedWord, module: LanguageModule) -> SyllableWord:
    """Split a word into its syllables and give each a time."""
    parts = module.syllables(word.text)
    spans = _from_letters(word, parts, module) or _fallback(word, parts)
    return SyllableWord(
        line=word.line,
        text=word.text,
        start=word.start,
        end=word.end,
        estimated=word.estimated,
        syllables=[
            Syllable(text=p, start=a, end=b) for p, (a, b) in zip(parts, spans, strict=True)
        ],
    )
