"""A map of the screen at tile resolution: where text stands and in which colour, never what.

``tile_map(frame)`` reduces a decoded frame (palette indices, 216 by 300) to a grid of
``TILE_ROWS`` by ``TILE_COLUMNS`` cells, one character per 6 by 12 pixel tile. No pixel of a tile
survives: a cell says only whether the tile is background and which palette index dominates it,
so the map shows the layout (rows, extent, wipe progress, colours) but cannot be read as text.

Cell characters (the palette index 0 to 15 as the letter ``a`` to ``p``):

- ``.``: the tile is one flat colour and that colour is the screen's background (the most
  common colour of the frame).
- a lower case letter: the tile is one flat colour other than the background (a bar, a fill).
- an upper case letter: the tile mixes colours; the letter is its most common colour that is not
  the background (the colour of the ink). A tile of text sung or unsung is told apart by it.
"""

from collections import Counter
from collections.abc import Sequence

import numpy as np

from vocatron.core.cdg.screen import (
    TILE_COLUMNS,
    TILE_HEIGHT,
    TILE_ROWS,
    TILE_WIDTH,
    Frame,
)

LETTERS = "abcdefghijklmnop"
"""One letter per palette index (``PALETTE_SIZE`` of them)."""
BACKGROUND_CELL = "."


def tile_map(frame: Frame) -> list[str]:
    """Return one string of ``TILE_COLUMNS`` cells per tile row of ``frame``."""
    counts = np.bincount(frame.ravel())
    background = int(np.argmax(counts))
    rows: list[str] = []
    for row in range(TILE_ROWS):
        cells: list[str] = []
        for column in range(TILE_COLUMNS):
            tile = frame[
                row * TILE_HEIGHT : (row + 1) * TILE_HEIGHT,
                column * TILE_WIDTH : (column + 1) * TILE_WIDTH,
            ]
            used = Counter(int(v) for v in tile.ravel())
            if len(used) == 1:
                (colour,) = used
                cells.append(BACKGROUND_CELL if colour == background else LETTERS[colour])
            else:  # two colours or more: at least one of them is not the background
                ink = next(c for c, _ in used.most_common() if c != background)
                cells.append(LETTERS[ink].upper())
        rows.append("".join(cells))
    return rows


def render_maps(maps: Sequence[tuple[float, list[str]]], per_line: int = 3) -> str:
    """Lay out maps side by side (``per_line`` of them), each headed by its time."""
    width = TILE_COLUMNS
    blocks: list[str] = []
    for start in range(0, len(maps), per_line):
        group = maps[start : start + per_line]
        blocks.append("   ".join(f"t={time:7.2f} s".ljust(width) for time, _ in group))
        blocks.extend("   ".join(grid[row] for _, grid in group) for row in range(TILE_ROWS))
        blocks.append("")
    return "\n".join(blocks)
