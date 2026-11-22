"""Cleaning of the common junk in lyrics found online (ADR-0008).

Section headings (``[Chorus]``, ``Refrain:``), repeat markers (``(2x)``, ``x2``) and credit lines
(``Written by ...``) are not sung. They are removed for the alignment, each removal is reported
(and later turns into a review reason), and the original text stays in the stage file.
"""

import re
from collections.abc import Container, Sequence
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from vocatron.core.glyphs import strip_undrawable
from vocatron.core.lyrics.document import Line, Mark

Junk = Literal["section", "repeat", "credit", "glyph"]

SECTION_WORDS = (
    r"(?:verse|chorus|refrain|bridge|intro|outro|hook|pre-?chorus|interlude|instrumental|solo|"
    r"coda|break|music|applause|strophe|vers|zwischenspiel|einleitung|ref)"
)
SECTION = re.compile(
    rf"[\[({{<]\s*{SECTION_WORDS}\b.*[\])}}>]\s*:?|"  # [Chorus], (Verse 2: Anna), [Refrain x2]
    rf"{SECTION_WORDS}(?:\s*\d+)?(?:\s*(?:x\s*\d+|\d+\s*[x×]))?\s*:?",  # Refrain:, Strophe 2
    re.IGNORECASE,
)
CREDIT_ROLES = (
    r"(?:written|composed|produced|arranged|mixed|mastered|lyrics|words|music|text|musik|melodie|"
    r"songtext|liedtext|translated|übersetzt)"
)
CREDIT_LABELS = (
    r"(?:songwriters?|writers?|composers?|lyricists?|producers?|lyrics|text|musik|melodie|music|"
    r"words|komponist|textdichter|texter|autor|übersetzung|translation|source|quelle)"
)
CREDIT = re.compile(
    rf"{CREDIT_ROLES}(?:\s+(?:and|und|&)\s+{CREDIT_ROLES})?\s+(?:by|von)\b.*|"  # Written by X
    rf"{CREDIT_LABELS}(?:\s*(?:and|und|&|/|,)\s*{CREDIT_LABELS})*\s*:.*|"  # Text & Musik: X
    r"(?:©|\(c\)|copyright\b).*|"
    r"(?:lyrics|songtext|liedtext)\s+(?:provided|powered|courtesy|from|source)\b.*|"
    r"\d*\s*embed|you might also like",
    re.IGNORECASE,
)
_MARK = (
    r"(?:[(\[{][^()\[\]{}]*?\b(?:\d+\s*(?:x|×|mal)|x\s*\d+|repeat|wdh|bis|twice|zweimal)\b"
    r"[^()\[\]{}]*?[)\]}]|\bx\s*\d+\b|\b\d+\s*[x×](?!\w))"
)
REPEAT_END = re.compile(rf"\s*{_MARK}\s*[,.;:]?\s*$", re.IGNORECASE)
REPEAT_START = re.compile(rf"^\s*{_MARK}\s*", re.IGNORECASE)
WORD = re.compile(r"\w")  # a line without a letter or digit (``---``, ``***``, ``♪``) is empty


class Removal(BaseModel):
    """One piece of junk that was taken out.

    Attributes:
        line: The row (from 1) of the line in the text it was read from.
        kind: ``section`` (a heading), ``repeat`` (a repeat marker), ``credit`` or ``glyph`` (a
            symbol the bundled font cannot draw, ADR-0046).
        text: The original text of the line.
        character: For ``glyph``, the code point that was dropped; ``None`` otherwise.
    """

    model_config = ConfigDict(frozen=True)

    line: int
    kind: Junk
    text: str
    character: int | None = None


class Cleaned(BaseModel):
    """The result of cleaning.

    Attributes:
        lines: The lines that stay.
        removals: What was taken out, in line order.
    """

    model_config = ConfigDict(frozen=True)

    lines: tuple[Line, ...]
    removals: tuple[Removal, ...]


def classify(text: str) -> Junk | None:
    """Say whether a whole line is a section heading or a credit; ``None`` for a sung line."""
    stripped = text.strip()
    if SECTION.fullmatch(stripped):
        return "section"
    if CREDIT.fullmatch(stripped):
        return "credit"
    return None


class Stripped(NamedTuple):
    """A line without its repeat markers.

    Attributes:
        text: What is left.
        skipped: How many characters of the original came off its start.
    """

    text: str
    skipped: int


def strip_repeat(text: str) -> Stripped:
    """Remove repeat markers from the start and the end of a line, until none is left."""
    offset = 0
    while True:
        trimmed = REPEAT_END.sub("", text)
        found = REPEAT_START.match(trimmed)
        rest = trimmed[found.end() :] if found else trimmed
        stripped = rest.strip()
        if len(stripped) == len(text):
            return Stripped(text, offset)
        offset += len(trimmed) - len(rest.lstrip())
        text = stripped


def _shift_marks(marks: tuple[Mark, ...], skipped: int, kept: int) -> tuple[Mark, ...]:
    """Move marks along with the words of a line that lost words at its start and its end.

    A mark on a removed word moves to the next word that stays, or to the end of the line.
    """
    return tuple(
        Mark(word=min(max(mark.word - skipped, 0), kept), singers=mark.singers) for mark in marks
    )


def _clean_line(line: Line, number: int) -> tuple[Line | None, Removal | None]:
    """Clean one line; return what stays (if anything) and what was removed (if anything)."""
    kind = classify(line.text)
    if kind is not None:
        return None, Removal(line=number, kind=kind, text=line.text)
    text, offset = strip_repeat(line.text)
    if text == line.text:
        return line, None
    kind = classify(text) or "repeat"  # "Refrain (2x)" is a heading once the marker is gone
    removal = Removal(line=number, kind=kind, text=line.text)
    if kind != "repeat" or not text:
        return None, removal
    skipped = sum(1 for word in re.finditer(r"\S+", line.text) if word.end() <= offset)
    marks = _shift_marks(line.marks, skipped, len(text.split()))
    return line.model_copy(update={"text": text, "marks": marks}), removal


def _drop_glyphs(
    line: Line, number: int, drawable: Container[int]
) -> tuple[Line | None, list[Removal]]:
    """Drop the symbols of a line that the font cannot draw; ``None`` if nothing is left.

    Raises:
        UndrawableLetter: If a letter, mark or digit of the line is not in the font.
    """
    stripped = strip_undrawable(line.text, drawable, f"line {number}")
    if stripped.text == line.text:
        return line, []
    removals = [
        Removal(line=number, kind="glyph", text=line.text, character=code)
        for code in stripped.dropped
    ]
    if not WORD.search(stripped.text):
        return None, removals
    marks = tuple(
        Mark(word=stripped.kept[min(mark.word, len(stripped.kept) - 1)], singers=mark.singers)
        for mark in line.marks
    )
    return line.model_copy(update={"text": stripped.text, "marks": marks}), removals


def clean(
    lines: Sequence[Line],
    rows: Sequence[int] | None = None,
    drawable: Container[int] | None = None,
) -> Cleaned:
    """Remove section headings, repeat markers, credits and empty lines.

    With ``drawable`` (the code points of the bundled font), a symbol the font cannot draw is
    dropped from its line and reported as ``glyph`` (ADR-0046); the words that remain keep their
    singer marks.

    A line without a letter or digit (a separator such as ``---`` or a note sign) is dropped
    without a report, like an empty one. A block break in front of a removed line moves to the
    next line that stays, and so do the singer marks of a removed line (ADR-0018); marks shift
    with the words a line loses at its start. Cleaning cleaned lines changes nothing.

    Args:
        lines: The lines of a lyrics document.
        rows: The row of each line in its file (``parse_numbered``), for the removals; by
            default the position of the line (from 1).
        drawable: The code points the font can draw; by default every character counts as drawn.

    Returns:
        The remaining lines and the removals.

    Raises:
        UndrawableLetter: If a letter, mark or digit of a line that stays is not in ``drawable``.
    """
    kept: list[Line] = []
    removals: list[Removal] = []
    pending_break = False
    pending = list[Mark]()  # marks of removed lines, for the next line that stays
    for index, line in enumerate(lines):
        number = index + 1 if rows is None else rows[index]
        result, removal = _clean_line(line, number) if WORD.search(line.text) else (None, None)
        pending_break |= line.blank_before and bool(kept)  # no break before the first line
        if removal is not None:
            removals.append(removal)
        if result is not None and drawable is not None:
            result, dropped = _drop_glyphs(result, number, drawable)
            removals += dropped
        if result is None:
            pending += [Mark(word=0, singers=mark.singers) for mark in line.marks]
            continue
        marks = (*pending, *result.marks)
        kept.append(result.model_copy(update={"blank_before": pending_break, "marks": marks}))
        pending = list[Mark]()
        pending_break = False
    return Cleaned(lines=tuple(kept), removals=tuple(removals))
