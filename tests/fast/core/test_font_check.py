"""Stage 1: what libass says about its fonts, and the font's size convention."""

import struct
from pathlib import Path

import pytest

from vocatron.core.font_check import (
    BUNDLED_FACE,
    em_per_cell,
    font_characters,
    font_problems,
    fonts_used,
)

FONT = Path(__file__).resolve().parents[3] / "src" / "vocatron" / "fonts" / "NotoSans-Bold.ttf"
PREFIX = "[Parsed_subtitles_0 @ 0x1] fontselect: (Noto Sans, 700, 0) -> "
GOOD = PREFIX + "NotoSans-Bold, 0, NotoSans-Bold\n"
BAD = (
    "[Parsed_subtitles_0 @ 0x1] fontselect: (Noto Sans, 700, 0) -> "
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf, 0, DejaVuSans-Bold\n"
)


def test_the_face_libass_chose_is_read_from_its_log() -> None:
    assert fonts_used("noise\n" + GOOD + "more\n") == [BUNDLED_FACE]
    assert fonts_used(BAD) == ["DejaVuSans-Bold"]
    assert fonts_used("nothing here") == []


def test_only_the_bundled_font_is_accepted() -> None:
    assert font_problems(GOOD) == []
    assert font_problems("no font lines at all", text_drawn=False) == []
    (problem,) = font_problems(GOOD + BAD + BAD)
    assert "DejaVuSans-Bold" in problem
    assert BUNDLED_FACE in problem


def test_an_ass_font_size_is_the_line_cell_not_the_em() -> None:
    # Noto Sans: 1000 units per em, Windows ascent 1124 and descent 395
    assert em_per_cell(FONT.read_bytes()) == pytest.approx(1000 / 1519)


def test_a_file_that_is_not_a_font_is_refused() -> None:
    with pytest.raises(ValueError, match="no head or OS/2 table"):
        em_per_cell(b"\x00" * 64)


def test_a_log_that_names_no_font_is_no_proof_when_text_was_drawn() -> None:
    (problem,) = font_problems("no font lines at all")
    assert "did not say" in problem
    assert BUNDLED_FACE in problem


def font_with(tables: dict[bytes, bytes]) -> bytes:
    """A TrueType file of the given tables, laid out one after the other."""
    head = struct.pack(">IHHHH", 0x10000, len(tables), 0, 0, 0)
    offset = 12 + 16 * len(tables)
    rows, data = b"", b""
    for tag, body in tables.items():
        rows += struct.pack(">4sIII", tag, 0, offset + len(data), len(body))
        data += body
    return head + rows + data


def os2(ascent: int, descent: int) -> bytes:
    return b"\x00" * 74 + struct.pack(">HH", ascent, descent) + b"\x00" * 20


def head_table(units: int) -> bytes:
    return b"\x00" * 18 + struct.pack(">H", units) + b"\x00" * 34


def test_the_em_per_cell_is_read_from_the_head_and_os2_tables() -> None:
    assert em_per_cell(font_with({b"head": head_table(2048), b"OS/2": os2(1900, 500)})) == (
        pytest.approx(2048 / 2400)
    )


def test_a_font_without_one_of_the_tables_is_refused() -> None:
    with pytest.raises(ValueError, match="no head or OS/2 table"):
        em_per_cell(font_with({b"head": head_table(1000)}))
    with pytest.raises(ValueError, match="no head or OS/2 table"):
        em_per_cell(font_with({b"OS/2": os2(1100, 400)}))


def test_a_font_with_empty_metrics_is_refused() -> None:
    with pytest.raises(ValueError, match="metrics are empty"):
        em_per_cell(font_with({b"head": head_table(0), b"OS/2": os2(1100, 400)}))
    with pytest.raises(ValueError, match="metrics are empty"):
        em_per_cell(font_with({b"head": head_table(1000), b"OS/2": os2(0, 0)}))


def cmap_with(*subtables: tuple[int, int, bytes]) -> bytes:
    """A font with only a ``cmap`` of the given (platform, encoding, subtable) records."""
    head = struct.pack(">HH", 0, len(subtables))
    offset = len(head) + 8 * len(subtables)
    rows, data = b"", b""
    for platform, encoding, body in subtables:
        rows += struct.pack(">HHI", platform, encoding, offset + len(data))
        data += body
    return font_with({b"cmap": head + rows + data})


def format4() -> bytes:
    """Segments mapped by delta and through the glyph array, one of them above U+7FFF.

    A, B, C by delta; a (5 + 2), b (glyph 0, none) and c (0xFFFE + 2 wraps to 0, none) through
    the glyph array with a delta; U+F000 (0, none) and U+F001 (9) through the array at its end.
    """
    ends, starts = [0x43, 0x63, 0xF001, 0xFFFF], [0x41, 0x61, 0xF000, 0xFFFF]
    deltas = [(1 - 0x41) & 0xFFFF, 2, 0, 1]
    shifts = [0, 6, 10, 0]  # bytes from the segment's own entry to its first glyph in the array
    glyphs = [5, 0, 0xFFFE, 0, 9]
    words = [*ends, 0, *starts, *deltas, *shifts, *glyphs]
    body = b"".join(struct.pack(">H", v) for v in words)
    return struct.pack(">HHHHHHH", 4, 14 + len(body), 0, 8, 0, 0, 0) + body


def format12(groups: list[tuple[int, int, int]]) -> bytes:
    body = b"".join(struct.pack(">III", *group) for group in groups)
    return struct.pack(">HHIII", 12, 0, 16 + len(body), 0, len(groups)) + body


def test_format_4_maps_by_delta_and_through_the_glyph_array() -> None:
    found = font_characters(cmap_with((3, 1, format4())))
    assert found == {0x41, 0x42, 0x43, 0x61, 0xF001}  # the last segment maps to none


def test_format_12_maps_groups_and_skips_glyph_zero() -> None:
    found = font_characters(cmap_with((3, 10, format12([(0x1F600, 0x1F602, 7), (0x30, 0x31, 0)]))))
    assert found == {0x1F600, 0x1F601, 0x1F602, 0x31}  # '0' would be glyph 0


def test_subtables_of_both_kinds_are_joined_and_other_platforms_ignored() -> None:
    mac = (1, 1, format12([(0x7A, 0x7A, 3)]))  # encoding 1 of another platform is no Unicode
    symbol = (3, 0, format12([(0x79, 0x79, 3)]))  # Windows, but the symbol encoding
    unicode = (0, 4, format12([(0x20, 0x20, 2)]))
    found = font_characters(cmap_with((3, 1, format4()), unicode, mac, symbol))
    assert found == {0x41, 0x42, 0x43, 0x61, 0xF001, 0x20}


def test_a_font_without_a_readable_cmap_is_refused() -> None:
    with pytest.raises(ValueError, match="^the font has no cmap table$"):
        font_characters(font_with({b"head": head_table(1000)}))
    with pytest.raises(
        ValueError, match="^the font's cmap has no Unicode subtable of format 4 or 12$"
    ):
        font_characters(cmap_with((1, 0, format12([(0x20, 0x20, 2)]))))


def test_the_bundled_font_has_letters_and_not_a_square_root_sign() -> None:
    found = font_characters(FONT.read_bytes())
    assert {ord(c) for c in "aZäöüßÄ0 9"} <= found
    assert {0x221A, 0x266A, 0x2665} & found == set()  # square root, eighth note, heart
    assert 0x0416 in found  # Cyrillic capital zhe
    assert 0x6F22 not in found  # a Han character


def test_a_wrong_face_names_the_characters_the_font_lacks() -> None:
    (problem,) = font_problems(BAD, text="ab√√ c♪", drawable={ord(c) for c in "abc "})
    assert "U+221A SQUARE ROOT, U+266A EIGHTH NOTE" in problem
    (plain,) = font_problems(BAD, text="ab", drawable={ord("a"), ord("b")})
    assert "cannot draw" not in plain
    (lines,) = font_problems(BAD, text="a\nb", drawable={ord("a"), ord("b")})
    assert "cannot draw" not in lines  # line breaks are not drawn
    (untold,) = font_problems(BAD, drawable={ord("a")})
    assert "cannot draw" not in untold  # without the text there is nothing to name


def test_a_subtable_of_another_format_is_skipped() -> None:
    format6 = struct.pack(">HHHHH", 6, 12, 0, 0x41, 1) + struct.pack(">H", 9)
    found = font_characters(cmap_with((3, 1, format6), (3, 10, format12([(0x20, 0x20, 2)]))))
    assert found == {0x20}
    with pytest.raises(ValueError, match="no Unicode subtable"):
        font_characters(cmap_with((3, 1, format6)))
