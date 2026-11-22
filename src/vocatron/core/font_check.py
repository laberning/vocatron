"""What libass says about the fonts it used, and the font's size convention (ADR-0002, ADR-0009).

libass replaces a font it cannot find without a word, so the renderer reads its log: every
``fontselect`` line names the face it chose, and all of them must be the bundled font. The size
convention follows the font's own tables: an ASS ``Fontsize`` is the height of the line cell, which
libass takes as the font's Windows ascent plus descent.
"""

import re
import struct
from collections.abc import Collection, Iterator

from vocatron.core.glyphs import describe

BUNDLED_FACE = "NotoSans-Bold"
"""The PostScript name of the bundled font (``vocatron.fonts``); libass must pick this face."""
_SELECTED = re.compile(r"fontselect: \(([^)]*)\) -> (.*)$", re.MULTILINE)
_TABLE_HEAD = 12
_TABLE_ROW = 16
CMAP_SEGMENTS = 4  # the ``cmap`` subtable formats that are read
CMAP_GROUPS = 12
PLATFORM_UNICODE = 0  # ``cmap`` platform ids; Windows encodings 1 and 10 are Unicode
PLATFORM_WINDOWS = 3
WINDOWS_UNICODE = frozenset({1, 10})


def fonts_used(log: str) -> list[str]:
    """Return the PostScript names of the faces libass chose, from its log, in order."""
    return [found.group(2).rsplit(",", 1)[-1].strip() for found in _SELECTED.finditer(log)]


def font_problems(
    log: str,
    *,
    text_drawn: bool = True,
    text: str = "",
    drawable: Collection[int] | None = None,
) -> list[str]:
    """Return a message for every face libass chose that is not the bundled font.

    Args:
        log: What ffmpeg and libass wrote to the error output.
        text_drawn: The subtitle file has text, so libass must have said which face it chose;
            a log that names none fails too, since then nothing proves the font.
        text: The text of the subtitle file, to name the characters the font lacks.
        drawable: The code points of the bundled font (``font_characters``); with it, a message
            about a wrong face names the characters of ``text`` that are not in it.
    """
    faces = dict.fromkeys(fonts_used(log))
    if text_drawn and not faces:
        return [f"libass did not say which font it drew with; expected {BUNDLED_FACE}"]
    problems = [
        f"libass drew with {face} instead of the bundled font {BUNDLED_FACE}"
        for face in faces
        if face != BUNDLED_FACE
    ]
    if problems and drawable is not None:
        missing = dict.fromkeys(char for char in text if ord(char) not in drawable and char != "\n")
        if missing:
            names = ", ".join(describe(ord(char)) for char in missing)
            problems = [f"{problem}; the font cannot draw {names}" for problem in problems]
    return problems


def _tables(font: bytes) -> dict[bytes, tuple[int, int]]:
    """Return the offset and length of every table of a TrueType font file."""
    count = struct.unpack(">H", font[4:6])[0]
    rows = (
        struct.unpack(
            ">4sIII", font[_TABLE_HEAD + _TABLE_ROW * i : _TABLE_HEAD + _TABLE_ROW * (i + 1)]
        )
        for i in range(count)
    )
    return {tag: (offset, length) for tag, _, offset, length in rows}


def _cell_metrics(font: bytes) -> tuple[int, int, int]:
    """Return the units per em and the Windows ascent and descent of a TrueType font file.

    Raises:
        ValueError: If the file has no ``head`` or ``OS/2`` table, or they are empty.
    """
    tables = _tables(font)
    if b"head" not in tables or b"OS/2" not in tables:
        raise ValueError("the font has no head or OS/2 table")
    units = struct.unpack(">H", font[tables[b"head"][0] + 18 : tables[b"head"][0] + 20])[0]
    offset = tables[b"OS/2"][0]
    ascent, descent = struct.unpack(">HH", font[offset + 74 : offset + 78])
    if not units or not ascent + descent:
        raise ValueError("the font's metrics are empty")
    return units, ascent, descent


def em_per_cell(font: bytes) -> float:
    """Return how many pixels of em one pixel of ASS ``Fontsize`` is worth in ``font``.

    libass sets the size so that the Windows ascent plus descent (``OS/2``) of the face is the
    ``Fontsize``; the em is then ``units per em / (ascent + descent)`` of that.

    Raises:
        ValueError: If the file has no ``head`` or ``OS/2`` table, or they are empty.
    """
    units, ascent, descent = _cell_metrics(font)
    return units / (ascent + descent)


def ascent_share(font: bytes) -> float:
    """Return the share of the line cell above the baseline (Windows ascent over the cell height).

    Raises:
        ValueError: If the file has no ``head`` or ``OS/2`` table, or they are empty.
    """
    _, ascent, descent = _cell_metrics(font)
    return ascent / (ascent + descent)


def _cmap_subtables(font: bytes, cmap: int) -> Iterator[int]:
    """Yield the offset of every Unicode subtable of a ``cmap`` table."""
    count = struct.unpack(">H", font[cmap + 2 : cmap + 4])[0]
    for i in range(count):
        platform, encoding, offset = struct.unpack(
            ">HHI", font[cmap + 4 + 8 * i : cmap + 12 + 8 * i]
        )
        if platform == PLATFORM_UNICODE or (
            platform == PLATFORM_WINDOWS and encoding in WINDOWS_UNICODE
        ):
            yield cmap + offset


def _format4(font: bytes, base: int) -> Iterator[int]:
    """Yield the code points with a glyph in a ``cmap`` subtable of format 4."""
    segments = struct.unpack(">H", font[base + 6 : base + 8])[0] // 2
    ends = base + 14
    starts = ends + 2 * segments + 2
    deltas = starts + 2 * segments
    ranges = deltas + 2 * segments
    for i in range(segments):
        (end,) = struct.unpack(">H", font[ends + 2 * i : ends + 2 * i + 2])
        (start,) = struct.unpack(">H", font[starts + 2 * i : starts + 2 * i + 2])
        (delta,) = struct.unpack(">H", font[deltas + 2 * i : deltas + 2 * i + 2])
        (shift,) = struct.unpack(">H", font[ranges + 2 * i : ranges + 2 * i + 2])
        for code in range(start, end + 1):
            if shift == 0:
                glyph = (code + delta) & 0xFFFF
            else:
                at = ranges + 2 * i + shift + 2 * (code - start)
                (glyph,) = struct.unpack(">H", font[at : at + 2])
                glyph = (glyph + delta) & 0xFFFF if glyph else 0
            if glyph:
                yield code


def _format12(font: bytes, base: int) -> Iterator[int]:
    """Yield the code points with a glyph in a ``cmap`` subtable of format 12."""
    groups = struct.unpack(">I", font[base + 12 : base + 16])[0]
    for i in range(groups):
        start, end, glyph = struct.unpack(">III", font[base + 16 + 12 * i : base + 28 + 12 * i])
        for code in range(start, end + 1):
            if glyph + code - start:
                yield code


def font_characters(font: bytes) -> frozenset[int]:
    """Return the code points a TrueType font file has a glyph for (its ``cmap``, ADR-0046).

    Reads the Unicode subtables of formats 4 and 12; other formats are skipped.

    Raises:
        ValueError: If the file has no ``cmap`` table or no readable Unicode subtable.
    """
    tables = _tables(font)
    if b"cmap" not in tables:
        raise ValueError("the font has no cmap table")
    found: set[int] = set()
    readable = False
    for base in _cmap_subtables(font, tables[b"cmap"][0]):
        (kind,) = struct.unpack(">H", font[base : base + 2])
        if kind == CMAP_SEGMENTS:
            found.update(_format4(font, base))
        elif kind == CMAP_GROUPS:
            found.update(_format12(font, base))
        else:
            continue
        readable = True
    if not readable:
        raise ValueError("the font's cmap has no Unicode subtable of format 4 or 12")
    return frozenset(found)
