"""The Vocatron wordmark: the name in block letters made of straight edges (ADR-0055).

The eight capital letters and the letter V alone are polygons on a unit grid, built here from a
few numbers; no font and no artwork from elsewhere is used. A letter has one outer contour and,
where it has a hole (O, R), the contours of its counters, wound the other way round, so that
both the even-odd and the non-zero fill rule leave the counter open. The colours are fixed: seven
bands from yellow through red to violet, a cyan edge, the dark field and the amber of the rule.

The video draws these shapes (``vocatron.core.ass.mark``) and the logo files are written from
them (``vocatron.core.logo``), so the two never differ. Pure: no I/O.
"""

from dataclasses import dataclass
from functools import cache

type Point = tuple[float, float]
type Contour = tuple[Point, ...]
type Corner = tuple[float, float, float]  # x, y and how far the corner is cut off (0: sharp)

WORD = "VOCATRON"
SYLLABLES = ((0, 1), (2, 3), (4, 7))
"""The letters of VO, CA and TRON as ``(first, last)``: the steps the bands fill the word in."""

LETTER_HEIGHT = 180.0
"""The height of every letter, in grid units."""
LETTER_WIDTH = 176.0
STEM = 52.0
BAR = 40.0
CUT = 30.0
INNER_CUT = 12.0
TIP_CUT = 10.0
GAP = 24.0
"""The space between two letters, in grid units."""
PRECISION = 1000
"""Coordinates are rounded to a thousandth of a grid unit."""

BAND_COLOURS = ("#fff27a", "#ffc02e", "#ff8a1f", "#ff4b4b", "#f0288f", "#a22be2", "#4a25b8")
"""The seven bands of the letters, from the top."""
EDGE_COLOUR = "#5ff4ff"
"""The cyan of the glowing edge, and of the frame."""
EDGE_LIGHT = "#d9feff"
"""The thin light line on the edge."""
FIELD_COLOUR = "#0b0719"
"""The dark field of the start screen and of the logo files."""
FRAME_FILL = "#04020b"
"""The inside of the frame, a little darker than the field."""
AMBER = "#ffc02e"
"""The rule and the artist of the start screen."""
TEXT_COLOUR = "#ffffff"
"""The song title."""
EDGE_WIDTH = 12.0
"""The width of the glowing edge, in grid units."""
LIGHT_WIDTH = 3.5
"""The width of the thin light edge, in grid units."""


@dataclass(frozen=True)
class Letter:
    """One letter of the wordmark.

    Attributes:
        char: The capital letter.
        left: Where its box starts, in grid units from the left of the word.
        width: The width of its box.
        contours: The outer contour first, then the counters, each a closed polygon (the last
            point joins the first) with the outer one wound positively and the counters
            negatively (see ``signed_area``). Coordinates are grid units from the top left of
            the word.
    """

    char: str
    left: float
    width: float
    contours: tuple[Contour, ...]

    @property
    def right(self) -> float:
        """Where its box ends."""
        return self.left + self.width


def signed_area(contour: Contour) -> float:
    """Return the area of a polygon, positive when it is wound the way the outer contours are."""
    return (
        sum(
            x0 * y1 - x1 * y0
            for (x0, y0), (x1, y1) in zip(contour, contour[1:] + contour[:1], strict=True)
        )
        / 2
    )


def _round(value: float) -> float:
    return round(value * PRECISION) / PRECISION


def _cut(corners: list[Corner], left: float) -> Contour:
    """Cut the corners of a polygon off with straight lines and move it ``left`` to the right.

    A corner ``(x, y, cut)`` with a ``cut`` above 0 is replaced by two points on its edges, ``cut``
    away from it (at most half the edge), so the polygon keeps straight edges only.
    """
    points: list[Point] = []
    count = len(corners)
    for index, (x, y, cut) in enumerate(corners):
        if not cut:
            points.append((x, y))
            continue
        for ox, oy, _ in (corners[index - 1], corners[(index + 1) % count]):
            length = ((ox - x) ** 2 + (oy - y) ** 2) ** 0.5
            reach = min(cut, length / 2)
            points.append((x + (ox - x) * reach / length, y + (oy - y) * reach / length))
    return tuple((_round(x + left), _round(y)) for x, y in points)


def _wound(contour: Contour, positive: bool) -> Contour:
    """Return the contour wound positively or negatively, as asked."""
    return contour if (signed_area(contour) > 0) == positive else contour[::-1]


def _box(x: float, y: float, width: float, height: float, cut: float) -> list[Corner]:
    """Return the corners of a rectangle with its corners cut."""
    return [(x, y, cut), (x + width, y, cut), (x + width, y + height, cut), (x, y + height, cut)]


def _letter(char: str, left: float) -> Letter:
    """Build the letter ``char`` with its box starting at ``left``."""
    height, stem, bar = LETTER_HEIGHT, STEM, BAR
    width = LETTER_WIDTH
    outer: list[Corner]
    counters: list[list[Corner]] = []
    if char in "VA":
        width *= 1.08
        arm = 1.12 * stem
        half = arm / 2
        notch = (width / 2 - arm) * height / (width / 2 - half)
        v = [
            (0, 0, 0), (arm, 0, 0), (width / 2, notch, 0), (width - arm, 0, 0), (width, 0, 0),
            (width / 2 + half, height, TIP_CUT), (width / 2 - half, height, TIP_CUT),
        ]  # fmt: skip
        outer = v if char == "V" else [(x, height - y, cut) for x, y, cut in v]
    elif char == "O":
        outer = _box(0, 0, width, height, CUT)
        counters = [_box(stem, bar, width - 2 * stem, height - 2 * bar, INNER_CUT)]
    elif char == "C":
        width *= 0.95
        y1, y2 = 0.36 * height, 0.64 * height
        outer = [
            (width, y1, 0), (width, 0, CUT), (0, 0, CUT), (0, height, CUT), (width, height, CUT),
            (width, y2, 0), (width - stem, y2, 0), (width - stem, height - bar, INNER_CUT),
            (stem, height - bar, INNER_CUT), (stem, bar, INNER_CUT), (width - stem, bar, INNER_CUT),
            (width - stem, y1, 0),
        ]  # fmt: skip
    elif char == "T":
        width *= 0.95
        top = bar * 1.15
        outer = [
            (0, 0, 0), (width, 0, 0), (width, top, 0), (width / 2 + stem / 2, top, 0),
            (width / 2 + stem / 2, height, 0), (width / 2 - stem / 2, height, 0),
            (width / 2 - stem / 2, top, 0), (0, top, 0),
        ]  # fmt: skip
    elif char == "R":
        belly = 0.6 * height
        leg = stem + (width - 2 * stem) * 0.18
        arm = 1.12 * stem
        outer = [
            (0, 0, 0), (width, 0, CUT), (width, belly, CUT), (leg + arm, belly, 0),
            (width, height, 0), (width - arm, height, 0), (leg, belly, 0), (stem, belly, 0),
            (stem, height, 0), (0, height, 0),
        ]  # fmt: skip
        counters = [_box(stem, bar, width - 2 * stem, belly - 2 * bar, INNER_CUT)]
    elif char == "N":
        arm = 1.12 * stem
        low, high = stem * height / (width - arm), (width - stem - arm) * height / (width - arm)
        outer = [
            (0, 0, 0), (arm, 0, 0), (width - stem, high, 0), (width - stem, 0, 0), (width, 0, 0),
            (width, height, 0), (width - arm, height, 0), (stem, low, 0), (stem, height, 0),
            (0, height, 0),
        ]  # fmt: skip
    else:
        raise ValueError(f"the wordmark has no letter {char!r}")
    contours = (
        _wound(_cut(outer, left), True),
        *(_wound(_cut(hole, left), False) for hole in counters),
    )
    return Letter(char, _round(left), _round(width), contours)


@cache
def letters() -> tuple[Letter, ...]:
    """Return the eight letters of ``WORD`` side by side, ``GAP`` apart, from the origin."""
    found: list[Letter] = []
    left = 0.0
    for char in WORD:
        letter = _letter(char, left)
        found.append(letter)
        left = letter.right + GAP
    return tuple(found)


def word_width() -> float:
    """Return the width of the whole word in grid units."""
    return letters()[-1].right


@cache
def symbol() -> Letter:
    """Return the letter V alone, its box starting at the origin: the symbol."""
    return _letter("V", 0.0)


def bands() -> tuple[tuple[float, float, str], ...]:
    """Return the seven bands as ``(top, bottom, colour)``, from the top, sharing the letter height.

    The edges are taken from the same division, so one band ends exactly where the next starts.
    """
    edges = [
        _round(LETTER_HEIGHT * index / len(BAND_COLOURS)) for index in range(len(BAND_COLOURS))
    ]
    edges.append(LETTER_HEIGHT)
    return tuple(
        (edges[index], edges[index + 1], colour) for index, colour in enumerate(BAND_COLOURS)
    )


PIXEL_COLUMNS = 9
"""The width of a pixel letter, in cells."""
PIXEL_ROWS = 11
"""The height of a pixel letter, in cells."""
PIXEL_GAP = 1
"""The space between two pixel letters, in cells."""
PIXEL_SCALE = 3
"""The pixels of the CD+G screen along a cell's side (ADR-0056)."""
PIXEL_LETTERS = {
    "V": (
        "XXX...XXX", "XXX...XXX", "XXX...XXX", ".XXX.XXX.", ".XXX.XXX.", ".XXX.XXX.",
        "..XXXXX..", "..XXXXX..", "..XXXXX..", "...XXX...", "...XXX...",
    ),
    "O": (
        ".XXXXXXX.", "XXXXXXXXX", "XXX...XXX", "XXX...XXX", "XXX...XXX", "XXX...XXX",
        "XXX...XXX", "XXX...XXX", "XXX...XXX", "XXXXXXXXX", ".XXXXXXX.",
    ),
    "C": (
        ".XXXXXXX.", "XXXXXXXXX", "XXX...XXX", "XXX......", "XXX......", "XXX......",
        "XXX......", "XXX......", "XXX...XXX", "XXXXXXXXX", ".XXXXXXX.",
    ),
    "A": (
        "...XXX...", "...XXX...", "..XXXXX..", "..XXXXX..", ".XXX.XXX.", ".XXX.XXX.",
        ".XXX.XXX.", "XXX...XXX", "XXX...XXX", "XXX...XXX", "XXX...XXX",
    ),
    "T": (
        "XXXXXXXXX", "XXXXXXXXX", "...XXX...", "...XXX...", "...XXX...", "...XXX...",
        "...XXX...", "...XXX...", "...XXX...", "...XXX...", "...XXX...",
    ),
    "R": (
        "XXXXXXXX.", "XXXXXXXXX", "XXX...XXX", "XXX...XXX", "XXX...XXX", "XXXXXXXXX",
        "XXXXXXXX.", "XXX.XXX..", "XXX..XXX.", "XXX...XXX", "XXX...XXX",
    ),
    "N": (
        "XXX...XXX", "XXXX..XXX", "XXXX..XXX", "XXXXX.XXX", "XXXXXXXXX", "XXX.XXXXX",
        "XXX.XXXXX", "XXX..XXXX", "XXX..XXXX", "XXX...XXX", "XXX...XXX",
    ),
}  # fmt: skip
"""The letters of the word as pixel art for the CD+G screen: nine cells wide, eleven high, ``X``
where a cell is set. Drawn by hand so that the letters read at 27 by 33 pixels (ADR-0056)."""


def pixel_cells(char: str) -> tuple[tuple[bool, ...], ...]:
    """Return the cells of the pixel letter ``char`` as rows of set (true) and empty cells."""
    return tuple(tuple(cell == "X" for cell in row) for row in PIXEL_LETTERS[char])


def pixel_word_cells() -> tuple[tuple[bool, ...], ...]:
    """Return the cells of the whole word, its letters ``PIXEL_GAP`` cells apart, row by row."""
    gap = (False,) * PIXEL_GAP
    rows: list[tuple[bool, ...]] = []
    for row in range(PIXEL_ROWS):
        cells: tuple[bool, ...] = ()
        for number, char in enumerate(WORD):
            cells += (gap if number else ()) + pixel_cells(char)[row]
        rows.append(cells)
    return tuple(rows)


def pixel_word_columns() -> int:
    """Return the width of the word in cells."""
    return len(WORD) * PIXEL_COLUMNS + (len(WORD) - 1) * PIXEL_GAP


def pixel_band(row: int, rows: int) -> int:
    """Return the number of the band (0 at the top) that the pixel row ``row`` of ``rows`` is in.

    The word's height is divided into the seven bands as ``bands`` divides the polygon letters.
    """
    return row * len(BAND_COLOURS) // rows
