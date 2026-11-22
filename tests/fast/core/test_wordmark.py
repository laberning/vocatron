"""Stage 1: the shapes of the wordmark are well formed polygons (ADR-0055)."""

import pytest

from vocatron.core.wordmark import (
    BAND_COLOURS,
    GAP,
    LETTER_HEIGHT,
    PIXEL_COLUMNS,
    PIXEL_LETTERS,
    PIXEL_ROWS,
    PIXEL_SCALE,
    SYLLABLES,
    WORD,
    Contour,
    Letter,
    bands,
    letters,
    pixel_band,
    pixel_cells,
    pixel_word_cells,
    pixel_word_columns,
    signed_area,
    symbol,
    word_width,
)

EPS = 1e-6


def inside(point: tuple[float, float], contour: Contour) -> bool:
    """Even-odd test: is the point inside the polygon."""
    x, y = point
    found = False
    for (x0, y0), (x1, y1) in zip(contour, contour[1:] + contour[:1], strict=True):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            found = not found
    return found


def test_the_word_has_one_letter_for_each_character_in_order() -> None:
    assert "".join(letter.char for letter in letters()) == WORD
    assert len(letters()) == 8


def test_the_letters_stand_side_by_side_a_gap_apart() -> None:
    found = letters()
    for before, after in zip(found, found[1:], strict=False):
        assert after.left == pytest.approx(before.right + GAP, abs=2e-3)
    assert word_width() == pytest.approx(found[-1].right)


@pytest.mark.parametrize("letter", letters(), ids=lambda x: f"{x.char}-{x.left:.0f}")
def test_every_polygon_is_closed_inside_its_letter_box_and_has_no_zero_edge(
    letter: Letter,
) -> None:
    for contour in letter.contours:
        assert len(contour) >= 3
        for (x0, y0), (x1, y1) in zip(contour, contour[1:] + contour[:1], strict=True):
            assert (x0, y0) != (x1, y1)  # the last point joins the first: no repeated end point
        for x, y in contour:
            assert letter.left - EPS <= x <= letter.right + EPS
            assert -EPS <= y <= LETTER_HEIGHT + EPS


@pytest.mark.parametrize("letter", letters(), ids=lambda x: f"{x.char}-{x.left:.0f}")
def test_the_outer_contour_is_wound_one_way_and_the_counters_the_other(letter: Letter) -> None:
    outer, *counters = letter.contours
    assert signed_area(outer) > 0
    for counter in counters:
        assert signed_area(counter) < 0


@pytest.mark.parametrize("letter", letters(), ids=lambda x: f"{x.char}-{x.left:.0f}")
def test_a_counter_lies_inside_its_letter_and_the_letter_keeps_ink_around_it(
    letter: Letter,
) -> None:
    outer, *counters = letter.contours
    assert len(counters) == (1 if letter.char in "OR" else 0)
    for counter in counters:
        assert all(inside(point, outer) for point in counter)
        assert abs(signed_area(counter)) < abs(signed_area(outer))


def test_the_letters_have_the_edges_straight_cut_corners_not_curves() -> None:
    """Every edge of every polygon is a straight segment between two points of the list."""
    for letter in letters():
        for contour in letter.contours:
            assert all(len(point) == 2 for point in contour)


def test_the_symbol_is_the_first_letter_alone() -> None:
    assert symbol().char == "V"
    assert symbol().left == 0
    assert symbol().contours == letters()[0].contours


def test_the_bands_cover_the_letter_height_without_a_gap_in_the_colours_in_order() -> None:
    found = bands()
    assert [colour for _, _, colour in found] == list(BAND_COLOURS)
    assert found[0][0] == 0
    assert found[-1][1] == LETTER_HEIGHT
    for (_, bottom, _), (top, _, _) in zip(found, found[1:], strict=False):
        assert bottom == top
    heights = [bottom - top for top, bottom, _ in found]
    assert max(heights) - min(heights) < 2e-3


def test_the_syllables_split_the_word_into_vo_ca_and_tron() -> None:
    spoken = ["".join(letters()[i].char for i in range(a, b + 1)) for a, b in SYLLABLES]
    assert spoken == ["VO", "CA", "TRON"]


def test_the_signed_area_is_the_area_of_the_polygon_with_its_sign_for_the_winding() -> None:
    square = ((0.0, 0.0), (2.0, 0.0), (2.0, 3.0), (0.0, 3.0))
    assert signed_area(square) == 6.0
    assert signed_area(square[::-1]) == -6.0


# ------------------------------------------------------------------ the pixel letters (ADR-0056)

AGREEMENT = 0.85
"""The share of the 99 cells of a pixel letter that must agree with its polygon letter."""


def polygon_cells(letter: Letter) -> list[list[bool]]:
    """Rasterise a polygon letter onto the grid of the pixel letters: the cell centres decide."""
    outer, *counters = letter.contours

    def set_at(row: int, column: int) -> bool:
        point = (
            letter.left + (column + 0.5) / PIXEL_COLUMNS * letter.width,
            (row + 0.5) / PIXEL_ROWS * LETTER_HEIGHT,
        )
        return inside(point, outer) and not any(inside(point, hole) for hole in counters)

    return [[set_at(row, column) for column in range(PIXEL_COLUMNS)] for row in range(PIXEL_ROWS)]


def test_every_letter_of_the_word_has_a_pixel_letter_of_nine_by_eleven_cells() -> None:
    assert set(PIXEL_LETTERS) == set(WORD)
    for char in set(WORD):
        rows = PIXEL_LETTERS[char]
        assert len(rows) == PIXEL_ROWS
        assert all(len(row) == PIXEL_COLUMNS and set(row) <= {".", "X"} for row in rows), char
        assert pixel_cells(char) == tuple(tuple(c == "X" for c in row) for row in rows)


@pytest.mark.parametrize("letter", letters(), ids=lambda x: f"{x.char}-{x.left:.0f}")
def test_each_pixel_letter_covers_the_shape_of_its_polygon_letter(letter: Letter) -> None:
    cells = pixel_cells(letter.char)
    drawn = polygon_cells(letter)
    agreeing = sum(
        cells[row][column] == drawn[row][column]
        for row in range(PIXEL_ROWS)
        for column in range(PIXEL_COLUMNS)
    )
    assert agreeing / (PIXEL_ROWS * PIXEL_COLUMNS) >= AGREEMENT


def test_the_pixel_word_sets_its_letters_one_cell_apart() -> None:
    rows = pixel_word_cells()
    assert len(rows) == PIXEL_ROWS
    assert {len(row) for row in rows} == {pixel_word_columns()} == {8 * PIXEL_COLUMNS + 7}
    for number in range(len(WORD) - 1):
        gap = (number + 1) * PIXEL_COLUMNS + number
        assert not any(row[gap] for row in rows)  # the cell between two letters is empty
    first = [row[:PIXEL_COLUMNS] for row in rows]
    assert tuple(tuple(row) for row in first) == pixel_cells("V")


def test_the_word_is_240_pixels_or_less_wide_and_33_high_at_the_pixel_scale() -> None:
    assert (pixel_word_columns() * PIXEL_SCALE, PIXEL_ROWS * PIXEL_SCALE) == (237, 33)


def test_the_pixel_rows_are_banded_from_top_to_bottom_in_seven_equal_steps() -> None:
    rows = PIXEL_ROWS * PIXEL_SCALE
    found = [pixel_band(row, rows) for row in range(rows)]
    assert found == sorted(found)
    assert (found[0], found[-1]) == (0, len(BAND_COLOURS) - 1)
    assert all(4 <= found.count(band) <= 5 for band in range(len(BAND_COLOURS)))
