"""The cheapest packets that turn one tile into another (ADR-0023).

A tile block packet draws a 12 by 6 tile in two colours, either replacing the pixels (normal) or
combining its colours with the pixels already there by XOR. A wipe step changes the pixels it
reaches by one XOR value, so it is one XOR packet; a text tile of three colours is a normal block
and a XOR block over it. ``plan_tile`` tries the XOR route, which keeps what is there, and the
normal-block route, which starts over, and returns the shorter list.

The plan depends only on the two tiles, and a stream asks for the same pairs again and again, so it
is worked out in plain Python on the tiles' bytes (small numpy calls cost more than the work) and
remembered by those bytes.
"""

from collections import Counter
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray

from vocatron.core.cdg.screen import TILE_HEIGHT, TILE_WIDTH
from vocatron.core.cdg.write import TileOp

type Tile = NDArray[np.uint8]

COLOUR_BITS = 4
"""A palette index has four bits, so a difference needs at most four bit planes."""
CANDIDATES = 3
"""A normal block is tried with each pair of the most frequent colours of the target."""
REDRAW_BLOCKS = 2
"""A redraw is at least a normal block and, unless the target has two colours, a XOR block."""
REDRAW_COLOURS = 2
"""A normal block draws two colours; a target of more needs a XOR block for the rest."""
CACHED_PLANS = 1 << 16
"""How many plans are remembered; a plan is a few hundred bytes."""


_IS_VALUE = tuple(bytes(int(i == value) for i in range(256)) for value in range(256))
"""For each value, the table that turns a tile's bytes into flags: 1 where the byte is the value."""
_BIT_OF = tuple(bytes((i >> bit) & 1 for i in range(256)) for bit in range(COLOUR_BITS))
"""For each bit, the table that turns a tile's bytes into flags: that bit of the byte."""


def _rows(flags: bytes) -> tuple[int, ...]:
    """Return the 12 rows of a tile mask (72 flags of 0 or 1, row by row) as 6-bit masks."""
    return tuple(
        (a << 5) | (b << 4) | (c << 3) | (d << 2) | (e << 1) | f
        for a, b, c, d, e, f in (
            flags[start : start + TILE_WIDTH]
            for start in range(0, TILE_HEIGHT * TILE_WIDTH, TILE_WIDTH)
        )
    )


def _xor(first: bytes, second: bytes) -> bytes:
    """Return the bytes of two equally long tiles XORed pixel by pixel."""
    size = len(first)
    return (int.from_bytes(first) ^ int.from_bytes(second)).to_bytes(size)


def _layers(diff: bytes) -> list[TileOp]:
    """Return the XOR blocks that apply ``diff`` (the value XORed into each pixel).

    One block does it when the difference has one value besides 0, or two values and no 0.
    Otherwise there is one block per value, or one per bit plane when that is fewer.
    """
    values = sorted(set(diff))
    changing = [v for v in values if v != 0]
    if not changing:
        return []
    if len(changing) == 1:
        return [TileOp(0, changing[0], _rows(diff.translate(_IS_VALUE[changing[0]])), xor=True)]
    if len(changing) == 2 and len(values) == 2:  # noqa: PLR2004  # no pixel is left unchanged
        low, high = changing
        return [TileOp(low, high, _rows(diff.translate(_IS_VALUE[high])), xor=True)]
    used = 0
    for v in changing:
        used |= v
    planes = [b for b in range(COLOUR_BITS) if (used >> b) & 1]
    if len(planes) < len(changing):
        return [TileOp(0, 1 << b, _rows(diff.translate(_BIT_OF[b])), xor=True) for b in planes]
    return [TileOp(0, v, _rows(diff.translate(_IS_VALUE[v])), xor=True) for v in changing]


def _two_colours(zero: int, one: int) -> bytes:
    """Return the table that keeps ``one`` and turns every other byte into ``zero``."""
    return bytes(one if i == one else zero for i in range(256))


_two_colours_of = lru_cache(maxsize=CACHED_PLANS)(_two_colours)
"""``_two_colours``, remembered (mutmut does not mutate a decorated function, so no decorator)."""


def _replace(target: bytes, zero: int, one: int) -> tuple[TileOp, bytes]:
    """Return the normal block with ``zero`` and ``one`` and the tile it leaves behind.

    Pixels of the target in neither colour are drawn in ``zero``; XOR blocks mend them.
    """
    ones = target.translate(_IS_VALUE[one])
    drawn = target.translate(_two_colours_of(zero, one))
    return TileOp(zero, one, _rows(ones), xor=False), drawn


def _plan(current: bytes, target: bytes) -> tuple[TileOp, ...]:
    """Return the plan for two tiles given as their 72 bytes (``plan_tile`` remembers it)."""
    if current == target:
        return ()
    best = _layers(_xor(current, target))
    if len(best) == 1:
        return tuple(best)
    counts = Counter(target)
    if len(counts) == 1:  # one colour all over: a block with no pixel of the other colour
        (colour,) = counts
        return (TileOp(colour, colour, (0,) * TILE_HEIGHT, xor=False),)
    if len(best) <= REDRAW_BLOCKS and len(counts) > REDRAW_COLOURS:
        return tuple(best)  # a block and a layer for the other colours would be no shorter
    common = [colour for colour, _ in counts.most_common(CANDIDATES)]
    for zero in common:
        for one in common:
            if zero == one:
                continue
            block, drawn = _replace(target, zero, one)
            plan = [block, *_layers(_xor(target, drawn))]
            if len(plan) < len(best):
                best = plan
    return tuple(best)


_plan_of = lru_cache(maxsize=CACHED_PLANS)(_plan)
"""``_plan``, remembered by the bytes of the two tiles."""


def plan_tile(current: Tile, target: Tile) -> list[TileOp]:
    """Return the fewest tile blocks (at most about five) that turn ``current`` into ``target``.

    Args:
        current: The 12 by 6 palette indices on the screen.
        target: The 12 by 6 palette indices wanted.

    Returns:
        The packets' contents in the order to send them; empty when the tiles are equal.
    """
    return list(_plan_of(current.tobytes(), target.tobytes()))
