"""The lyrics file format of ADR-0008: parser and writer for ``.txt`` and ``.lrc``.

A document is a list of lines, each with its singer marks (ADR-0018), its voice (ADR-0052) and
(in LRC) an optional time, plus the singer names and colours of the header. A singer mark is
``{1}`` to ``{5}``, ``{all}`` or a group such as ``{1,3}``, at the start of a line or before a
word inside it. ``{&}`` at the start of a line puts it on the second voice. The writer produces
the canonical form: parsing a file in canonical form and writing it back gives the same text.
Files that differ only in spacing, in the spelling of time tags or in the order of header tags are
normalised by the first write; Vocatron never rewrites a user's file.
"""

import json
import math
import re
from collections.abc import Callable, Sequence
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ruamel.yaml import YAML, YAMLError

Kind = Literal["txt", "lrc"]

MAX_SINGERS = 5
ALL = "all"
HEADER_FENCE = "---"
COLOUR = re.compile(r"#[0-9a-fA-F]{6}")
MARK = re.compile(rf"\{{({ALL}|[1-5](?:,[1-5])*)\}}")
VOICE_MARK = "{&}"
"""The mark at the start of a line that puts it on the second voice (ADR-0052)."""
Voice = Literal[1, 2]
FIRST_VOICE: Voice = 1
SECOND_VOICE: Voice = 2
TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
LINE_TIMES = re.compile(r"(?P<tags>(?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\])+)\s*(?P<rest>.*)")
ID_TAG = re.compile(r"\[([A-Za-z#][\w#-]*)\s*:\s*(.*?)\s*\]")
SINGER_TAG = re.compile(r"singer([1-5])", re.IGNORECASE)
SINGER_VALUE = re.compile(rf"(?:(.*?)\s*,\s*)?({COLOUR.pattern})|(.*)")
WORD_TAG = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>\s*")
PLAIN_NAME = re.compile(r"[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ .'-]*")
YAML_WORDS = frozenset({"y", "n", "yes", "no", "true", "false", "on", "off", "null"})


class FormatError(ValueError):
    """A lyrics file does not follow the format; the message says where."""


class SingerInfo(BaseModel):
    """Name and colour of one singer; both are optional.

    Attributes:
        name: The singer's name.
        colour: The singer's colour as ``#rrggbb``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    colour: str | None = Field(default=None, pattern=COLOUR.pattern)


class Mark(BaseModel):
    """A singer mark: from this word on, these singers sing.

    Attributes:
        word: The index of the word the singers start at; the number of words of the line for a
            mark at its end, which holds from the next line.
        singers: ``1`` to ``5``, a group such as ``1,3`` (sorted), or ``all``.
    """

    model_config = ConfigDict(frozen=True)

    word: int = Field(ge=0)
    singers: str


class Line(BaseModel):
    """One sung phrase.

    Attributes:
        text: The words, without marks and time tag.
        marks: The singer marks of the line in the order of the file (words never decrease).
        voice: ``2`` for a line marked ``{&}``: it is sung by a second voice at the same time as
            the first (ADR-0052); ``1`` otherwise.
        time: The line time in seconds (``.lrc`` only).
        blank_before: A blank line separates this line from the one before.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    marks: tuple[Mark, ...] = ()
    voice: Voice = Field(default=FIRST_VOICE, exclude_if=lambda voice: voice == FIRST_VOICE)
    time: float | None = None
    blank_before: bool = False


class Resolved(NamedTuple):
    """Who sings a line.

    Attributes:
        singers: The singers of the first word.
        turns: Where the singers change inside the line (words after the first), each with the
            singers from there on.
    """

    singers: str
    turns: tuple[Mark, ...] = ()


class Document(BaseModel):
    """A parsed lyrics file.

    Attributes:
        kind: ``txt`` or ``lrc``.
        tags: The ID tags of an ``.lrc`` (``ti``, ``ar``, ``length``, ...) in file order.
        singers: Names and colours by singer number.
        lines: The lines in order.
        written_by: The ``written_by`` key of the header of a ``.txt`` (Vocatron's mark of a
            file it wrote, ``vocatron.core.lyrics.origin``); ``None`` without one.
    """

    model_config = ConfigDict(frozen=True)

    kind: Kind
    tags: tuple[tuple[str, str], ...] = ()
    singers: dict[int, SingerInfo] = Field(default_factory=dict)
    lines: tuple[Line, ...] = ()
    written_by: str | None = None


class Numbered(NamedTuple):
    """A parsed lyrics file with the row of every line.

    Attributes:
        document: The parsed lyrics.
        rows: For each line of the document, its row in the file (from 1).
    """

    document: Document
    rows: tuple[int, ...]


def canonical_singers(singers: str) -> str:
    """Return the singers of a mark in canonical form: ``1``, ``1,3`` (sorted) or ``all``.

    ``all`` is never part of a group (``MARK``), so it stays as it is.
    """
    return ",".join(sorted(set(singers.split(","))))


def is_single_singer(singers: str) -> bool:
    """Tell whether a mark names one singer (``2``), not a group (``1,3``) or ``all``."""
    return singers.isdecimal()


def resolve_singers(lines: tuple[Line, ...] | list[Line]) -> list[Resolved]:
    """Return who sings every line: the marks hold until the next one, also across lines.

    Words before the first mark are sung by singer 1. At one position the last mark counts, and a
    mark at the end of a line holds from the next line. A mark that names the singers already
    singing makes no turn.
    """
    result: list[Resolved] = []
    current = "1"
    for line in lines:
        count = len(line.text.split())
        last = {mark.word: mark.singers for mark in line.marks}  # at one position the last counts
        if count:
            current = last.get(0, current)
        start = current
        turns: list[Mark] = []
        for word, singers in sorted(last.items()):
            if word < count and singers != current:  # a mark at word 0 set ``current``
                turns.append(Mark(word=word, singers=singers))
                current = singers
        ends = [last[word] for word in sorted(last) if word >= count]
        current = ends[-1] if ends else current
        result.append(Resolved(start, tuple(turns)))
    return result


def has_singer_marks(lines: tuple[Line, ...] | list[Line]) -> bool:
    """Tell whether any line carries a singer mark."""
    return any(line.marks for line in lines)


def format_time(seconds: float) -> str:
    """Format a line time as ``mm:ss.xx`` (centiseconds)."""
    centis = round(seconds * 100)
    return f"{centis // 6000:02d}:{centis % 6000 // 100:02d}.{centis % 100:02d}"


def _seconds(minutes: str, secs: str, fraction: str | None) -> float:
    """Convert the parts of a time tag to seconds."""
    frac = int(fraction) / 10 ** len(fraction) if fraction else 0.0
    return int(minutes) * 60 + int(secs) + frac


def parse_length(value: str) -> float | None:
    """Read the value of an ``[length: m:ss]`` tag in seconds, or ``None`` if it is not one."""
    found = re.fullmatch(r"(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?", value.strip())
    return None if found is None else _seconds(*found.groups())


def offset_of(tags: Sequence[tuple[str, str]]) -> float:
    """Return the ``[offset:]`` of an ``.lrc`` in seconds (0 without a valid one).

    The tag is in milliseconds; a positive offset shows the lyrics earlier, so it is subtracted
    from every time tag. With several offset tags the last one counts.
    """
    offset = 0.0
    for key, value in tags:
        found = re.fullmatch(r"[+-]?\d+", value.strip())
        if key.lower() == "offset" and found is not None:
            offset = int(found.group()) / 1000
    return offset


def _split_marks(text: str) -> tuple[str, tuple[Mark, ...], Voice]:
    """Split the singer marks and the voice mark off a line of text.

    A mark stands at the start of a word (``{2}word`` counts, ``word{2}`` does not). The voice
    mark ``{&}`` counts only before the first word. A line with marks keeps its words one space
    apart; a line without keeps its text as it is.
    """
    words: list[str] = []
    marks: list[Mark] = []
    voice: Voice = FIRST_VOICE
    marked = False
    for token in text.split():
        rest = token
        while True:
            if not words and rest.startswith(VOICE_MARK):
                voice, marked, rest = SECOND_VOICE, True, rest[len(VOICE_MARK) :]
            elif (found := MARK.match(rest)) is not None:
                marks.append(Mark(word=len(words), singers=canonical_singers(found.group(1))))
                rest = rest[found.end() :]
            else:
                break
        if rest:
            words.append(rest)
    return (" ".join(words), tuple(marks), voice) if marks or marked else (text, (), FIRST_VOICE)


# ---------------------------------------------------------------- reading


class _Header(BaseModel):
    """The YAML block at the top of a ``.txt`` file."""

    model_config = ConfigDict(extra="forbid")

    written_by: str | None = None
    singers: dict[int, SingerInfo | str] = Field(default_factory=dict)


def _check_numbers(numbers: list[int]) -> None:
    """Require singer numbers 1 to 5.

    Raises:
        FormatError: If a number is outside that range.
    """
    for number in numbers:
        if not 1 <= number <= MAX_SINGERS:
            raise FormatError(f"singer {number}: singers are numbered 1 to {MAX_SINGERS}")


def _parse_header(block: str) -> _Header:
    """Read the YAML block of a ``.txt`` file: the singers and the ``written_by`` key.

    Raises:
        FormatError: If the block is not valid YAML or does not follow the format.
    """
    try:
        data: object = YAML(typ="safe").load(block)
        header = _Header.model_validate({} if data is None else data)
    except (YAMLError, ValidationError) as error:
        raise FormatError(f"the singer header is invalid: {error}") from error
    _check_numbers(list(header.singers))
    return header


def _split_header(rows: list[str]) -> tuple[_Header, int]:
    """Read the optional ``---`` block at the top of a ``.txt`` file.

    Returns:
        The header, and the index of the first row after the block (0 without a block).

    Raises:
        FormatError: If the block is not closed.
    """
    if not rows or rows[0].strip() != HEADER_FENCE:
        return _Header(), 0
    for index in range(1, len(rows)):
        if rows[index].strip() == HEADER_FENCE:
            return _parse_header("\n".join(rows[1:index])), index + 1
    raise FormatError("the singer header is not closed by a second '---' line")


def _parse_txt(rows: list[str], header: bool) -> Numbered:
    """Parse the rows of a ``.txt`` file; ``header`` reads a ``---`` block at the top."""
    head, start = _split_header(rows) if header else (_Header(), 0)
    singers = {
        number: SingerInfo(name=info) if isinstance(info, str) else info
        for number, info in head.singers.items()
    }
    lines: list[Line] = []
    numbers: list[int] = []
    blank = False
    for number, row in enumerate(rows[start:], start=start + 1):
        text = row.strip()
        if not text:
            blank = bool(lines)
            continue
        words, marks, voice = _split_marks(text)
        lines.append(Line(text=words, marks=marks, voice=voice, blank_before=blank))
        numbers.append(number)
        blank = False
    document = Document(kind="txt", singers=singers, lines=tuple(lines), written_by=head.written_by)
    return Numbered(document, tuple(numbers))


def _singer_from_tag(value: str) -> SingerInfo:
    """Read ``Anna, #e0b000``, ``Anna`` or ``#e0b000``."""
    found = SINGER_VALUE.fullmatch(value)
    if found is None or found.group(3) is not None:
        return SingerInfo(name=value or None)
    return SingerInfo(name=found.group(1) or None, colour=found.group(2))


class _LrcReader:
    """Collects the rows of an ``.lrc`` file: ID tags, singer tags and lines."""

    def __init__(self) -> None:
        self.tags: list[tuple[str, str]] = []
        self.singers: dict[int, SingerInfo] = {}
        self.lines: list[tuple[Line, int]] = []  # each line with its row
        self.blank = False
        self.expanded = False  # a row had several time tags

    def add_lines(self, rest: str, times: Sequence[float | None], number: int) -> None:
        """Add one line per time tag of row ``number``."""
        text, marks, voice = _split_marks(WORD_TAG.sub("", rest).strip())
        self.lines += [
            (Line(text=text, marks=marks, voice=voice, time=t, blank_before=self.blank), number)
            for t in times
        ]
        self.blank = False

    def add_tag(self, key: str, value: str) -> None:
        """Add an ID tag, or the name and colour of a singer."""
        owner = SINGER_TAG.fullmatch(key)
        if owner is None:
            self.tags.append((key, value))
        else:
            self.singers[int(owner.group(1))] = _singer_from_tag(value)

    def read(self, row: str, number: int) -> None:
        """Read row ``number``."""
        text = row.strip()
        timed = LINE_TIMES.fullmatch(text)
        tag = ID_TAG.fullmatch(text)
        if not text:
            self.blank = bool(self.lines)
        elif timed is not None:
            times = [_seconds(*found) for found in TIME_TAG.findall(timed.group("tags"))]
            self.expanded |= len(times) > 1
            self.add_lines(timed.group("rest"), times, number)
        elif tag is not None and not self.lines:
            self.add_tag(tag.group(1), tag.group(2))
        else:
            self.add_lines(text, [None], number)

    def numbered(self) -> Numbered:
        """Return the document; lines with several time tags put all lines in time order.

        Untimed lines then come first. The ``[offset:]`` tag is applied to every line time.
        """
        offset = offset_of(self.tags)
        pairs = [
            (line if line.time is None else line.model_copy(update={"time": line.time - offset}), n)
            for line, n in self.lines
        ]
        if self.expanded:
            pairs = sorted(
                pairs, key=lambda pair: -math.inf if pair[0].time is None else pair[0].time
            )
        document = Document(
            kind="lrc",
            tags=tuple(self.tags),
            singers=self.singers,
            lines=tuple(line for line, _ in pairs),
        )
        return Numbered(document, tuple(number for _, number in pairs))


def _parse_lrc(rows: list[str], header: bool) -> Numbered:
    """Parse the rows of an ``.lrc`` file; word time tags are ignored (``header`` has no use)."""
    del header
    reader = _LrcReader()
    for number, row in enumerate(rows, start=1):
        reader.read(row, number)
    return reader.numbered()


PARSERS: dict[Kind, Callable[[list[str], bool], Numbered]] = {"txt": _parse_txt, "lrc": _parse_lrc}


def parse_numbered(text: str, kind: Kind, *, header: bool = True) -> Numbered:
    """Parse the text of a lyrics file and tell the row of every line.

    Args:
        text: The file content (a leading byte order mark is ignored).
        kind: ``txt`` or ``lrc``.
        header: Read the singer block at the top of a ``.txt``. Lyrics found online are no file
            of this format, so for them a ``---`` row is a line of text.

    Returns:
        The document and the rows of its lines.

    Raises:
        FormatError: If the singer header is invalid.
    """
    return PARSERS[kind](text.removeprefix("\ufeff").splitlines(), header)


def parse(text: str, kind: Kind, *, header: bool = True) -> Document:
    """Parse the text of a lyrics file (the arguments as for ``parse_numbered``).

    Raises:
        FormatError: If the singer header is invalid.
    """
    return parse_numbered(text, kind, header=header).document


# ---------------------------------------------------------------- writing


def _name_text(name: str) -> str:
    """Write a name as a YAML scalar: plain when that is safe, else as a double-quoted string."""
    safe = PLAIN_NAME.fullmatch(name) and name == name.strip() and name.lower() not in YAML_WORDS
    return name if safe else json.dumps(name, ensure_ascii=False)


def _txt_header(singers: dict[int, SingerInfo], written_by: str | None) -> list[str]:
    """Write the YAML block of a ``.txt`` file (nothing without singers and ``written_by``)."""
    rows = [HEADER_FENCE]
    if written_by is not None:
        rows.append(f"written_by: {_name_text(written_by)}")
    if not singers:
        return [*rows, HEADER_FENCE] if written_by is not None else []
    rows.append("singers:")
    for number in sorted(singers):
        info = singers[number]
        if info.name is not None and info.colour is None:
            rows.append(f"  {number}: {_name_text(info.name)}")
            continue
        parts = []
        if info.name is not None:
            parts.append(f"name: {_name_text(info.name)}")
        if info.colour is not None:
            parts.append(f'colour: "{info.colour}"')
        rows.append(f"  {number}: {{{', '.join(parts)}}}")
    return [*rows, HEADER_FENCE]


def _singer_tag(number: int, info: SingerInfo) -> str:
    """Write ``[singerN: Name, #rrggbb]``."""
    value = ", ".join(part for part in (info.name, info.colour) if part is not None)
    return f"[singer{number}: {value}]" if value else f"[singer{number}:]"


def _with_marks(line: Line) -> str:
    """Write the text of a line with each mark in front of its word (one space between words).

    The voice mark comes first.
    """
    if not line.marks and line.voice == FIRST_VOICE:
        return line.text
    words = line.text.split()
    parts: list[str] = [VOICE_MARK] if line.voice == SECOND_VOICE else []
    for index in range(len(words) + 1):
        parts += [f"{{{mark.singers}}}" for mark in line.marks if mark.word == index]
        parts += words[index : index + 1]
    return " ".join(parts)


def _body(line: Line, offset: float) -> str:
    """Write one line: ``[time] {2} text``; the time tag carries the file's ``offset`` again."""
    words = _with_marks(line)
    if line.time is None:
        return words
    return f"[{format_time(line.time + offset)}] {words}".rstrip()


def write(document: Document) -> str:
    """Write a document in canonical form.

    ``parse(write(d), d.kind) == d`` for every document whose texts are free of line breaks and
    do not hold a singer mark, a time tag or a header; a line with marks has its words one
    space apart. An ``[offset:]`` tag stays, and the time
    tags are written as the file had them (line time plus offset).
    """
    offset = offset_of(document.tags)
    if document.kind == "txt":
        rows = _txt_header(document.singers, document.written_by)
    else:
        rows = [f"[{key}: {value}]" if value else f"[{key}:]" for key, value in document.tags]
        rows += [_singer_tag(n, document.singers[n]) for n in sorted(document.singers)]
    for line in document.lines:
        if line.blank_before:
            rows.append("")
        rows.append(_body(line, offset))
    return "\n".join(rows) + "\n" if rows else ""
