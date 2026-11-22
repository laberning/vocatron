"""Stage 1: the remembered tile plans of the CD+G encoder equal fresh ones and reach the target."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.cdg import encode
from vocatron.core.cdg.encode import _plan, plan_tile
from vocatron.core.cdg.screen import TILE_HEIGHT, TILE_WIDTH
from vocatron.core.cdg.write import TileOp

PIXELS = TILE_HEIGHT * TILE_WIDTH


def tiles(colours: int) -> st.SearchStrategy[bytes]:
    """Tiles of 72 palette indices below ``colours``; few colours make the cheap routes likely."""
    return st.binary(min_size=PIXELS, max_size=PIXELS).map(
        lambda raw: bytes(v % colours for v in raw)
    )


def as_tile(raw: bytes) -> np.ndarray:
    return np.frombuffer(raw, dtype=np.uint8).reshape(TILE_HEIGHT, TILE_WIDTH).copy()


def applied(current: np.ndarray, ops: list[TileOp]) -> np.ndarray:
    """Return the tile after the blocks, drawn the way a decoder does."""
    shifts = np.arange(TILE_WIDTH - 1, -1, -1)
    result = current.copy()
    for op in ops:
        bits = (np.array(op.pixels)[:, None] >> shifts[None, :]) & 1
        colours = np.where(bits == 1, op.colour1, op.colour0).astype(np.uint8)
        result = result ^ colours if op.xor else colours
    return result


@given(
    colours=st.sampled_from([2, 3, 4, 16]),
    data=st.data(),
)
def test_a_remembered_plan_equals_a_fresh_one_and_reaches_the_target(
    colours: int, data: st.DataObject
) -> None:
    current = data.draw(tiles(colours))
    target = data.draw(tiles(colours))
    first = plan_tile(as_tile(current), as_tile(target))
    again = plan_tile(as_tile(current), as_tile(target))  # from the memory
    fresh = list(_plan(current, target))
    assert first == again == fresh
    assert np.array_equal(applied(as_tile(current), first), as_tile(target))


@given(raw=tiles(16))
def test_equal_tiles_need_no_block(raw: bytes) -> None:
    assert plan_tile(as_tile(raw), as_tile(raw)) == []


def test_a_caller_cannot_change_the_remembered_plan() -> None:
    current = as_tile(bytes(range(PIXELS)))
    target = np.zeros((TILE_HEIGHT, TILE_WIDTH), dtype=np.uint8)
    plan_tile(current, target).clear()
    assert plan_tile(current, target) != []


def test_the_plan_of_a_non_contiguous_tile_is_that_of_its_copy() -> None:
    screen = np.arange(2 * TILE_HEIGHT * 2 * TILE_WIDTH, dtype=np.uint8).reshape(
        2 * TILE_HEIGHT, 2 * TILE_WIDTH
    )
    region = screen[TILE_HEIGHT:, TILE_WIDTH:]
    target = np.full((TILE_HEIGHT, TILE_WIDTH), 5, dtype=np.uint8)
    assert plan_tile(region, target) == plan_tile(region.copy(), target)


# --- exact plans, worked out by hand; the stream of every CD+G file depends on them -------------

NOISE = np.arange(PIXELS, dtype=np.uint8).reshape(TILE_HEIGHT, TILE_WIDTH) % 16
"""A tile of sixteen colours: no cheap way to change it into a tile of few colours."""


def across(*columns: int) -> np.ndarray:
    """Return a tile whose column ``c`` holds ``columns[c]`` in every row."""
    return np.tile(np.array(columns, dtype=np.uint8), (TILE_HEIGHT, 1))


def differing(tile_: np.ndarray, flips: np.ndarray) -> np.ndarray:
    """Return ``tile_`` with ``flips`` XORed into it."""
    return (tile_ ^ flips).astype(np.uint8)


def test_a_difference_of_two_values_without_zero_is_one_xor_block_with_the_higher_value_set() -> (
    None
):
    plan = plan_tile(NOISE, NOISE ^ across(4, 4, 4, 6, 6, 6))
    assert plan == [TileOp(4, 6, (0b000111,) * TILE_HEIGHT, xor=True)]


def test_a_difference_in_fewer_bit_planes_than_values_is_one_xor_block_per_plane() -> None:
    plan = plan_tile(NOISE, NOISE ^ across(0, 2, 4, 6, 0, 2))
    assert plan == [
        TileOp(0, 2, (0b010101,) * TILE_HEIGHT, xor=True),
        TileOp(0, 4, (0b001100,) * TILE_HEIGHT, xor=True),
    ]


def test_a_difference_in_as_many_bit_planes_as_values_is_one_xor_block_per_value() -> None:
    plan = plan_tile(NOISE, NOISE ^ across(0, 1, 3, 0, 1, 3))
    assert plan == [
        TileOp(0, 1, (0b010010,) * TILE_HEIGHT, xor=True),
        TileOp(0, 3, (0b001001,) * TILE_HEIGHT, xor=True),
    ]


def test_an_area_of_one_colour_is_one_normal_block_of_that_colour_twice() -> None:
    plan = plan_tile(NOISE, across(9, 9, 9, 9, 9, 9))
    assert plan == [TileOp(9, 9, (0,) * TILE_HEIGHT, xor=False)]


def test_three_colours_are_a_normal_block_of_the_two_commonest_and_a_xor_block_for_the_rest() -> (
    None
):
    plan = plan_tile(NOISE, across(0, 0, 7, 7, 7, 3))
    assert plan == [
        TileOp(7, 0, (0b110000,) * TILE_HEIGHT, xor=False),
        TileOp(0, 4, (0b000001,) * TILE_HEIGHT, xor=True),
    ]


def test_of_two_colours_the_first_one_met_among_equally_common_ones_is_the_zero_colour() -> None:
    plan = plan_tile(NOISE, across(1, 1, 1, 2, 2, 2))
    assert plan == [TileOp(1, 2, (0b000111,) * TILE_HEIGHT, xor=False)]


def test_a_normal_block_is_tried_with_the_three_commonest_colours_only() -> None:
    current = bytes(
        [6, 10, 2, 14, 4, 8, 7, 5, 4, 4, 7, 12, 5, 0, 9, 15, 10, 11, 0, 4, 1, 14, 7, 11]
        + [0, 9, 4, 12, 4, 15, 15, 0, 0, 11, 3, 14, 4, 4, 5, 15, 3, 6, 2, 12, 9, 3, 13, 14]
        + [7, 2, 1, 1, 7, 0, 2, 14, 7, 14, 9, 10, 15, 13, 14, 4, 4, 5, 6, 8, 7, 0, 10, 7]
    )
    target = bytes(
        [13, 13, 9, 12, 13, 13, 8, 13, 13, 8, 12, 8, 13, 1, 9, 13, 1, 9, 9, 13, 8, 12, 9, 13]
        + [9, 13, 9, 8, 13, 13, 13, 13, 1, 13, 1, 13, 13, 13, 12, 1, 13, 13, 13, 13, 13, 8, 12, 9]
        + [8, 8, 9, 13, 13, 13, 8, 12, 8, 9, 9, 12, 13, 9, 13, 8, 9, 13, 13, 9, 13, 13, 9, 8]
    )
    plan = plan_tile(as_tile(current), as_tile(target))
    assert len(plan) == 4  # a pair with a rarer colour would do it in three


def test_a_tile_of_two_colours_is_redrawn_in_one_block_when_the_difference_needs_two() -> None:
    target = across(1, 1, 1, 2, 2, 2)
    plan = plan_tile(
        differing(target, across(0, 1, 3, 0, 1, 3)), target
    )  # two XOR blocks would mend it
    assert plan == [TileOp(1, 2, (0b000111,) * TILE_HEIGHT, xor=False)]


def test_a_tile_of_three_colours_with_a_difference_of_two_blocks_is_mended_not_redrawn() -> None:
    target = across(1, 1, 2, 2, 3, 3)
    plan = plan_tile(differing(target, across(0, 1, 3, 0, 1, 3)), target)
    assert plan == [
        TileOp(0, 1, (0b010010,) * TILE_HEIGHT, xor=True),
        TileOp(0, 3, (0b001001,) * TILE_HEIGHT, xor=True),
    ]


def test_a_two_block_mend_of_a_tile_of_three_colours_tries_no_redraw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A redraw of more than two colours is a block and a layer at least, so it is not tried."""

    def no_redraw(*_: object) -> None:
        raise AssertionError("a redraw was tried")

    target = across(1, 1, 2, 2, 3, 3)
    current = differing(target, across(0, 1, 3, 0, 1, 3))
    monkeypatch.setattr(encode, "_replace", no_redraw)
    assert len(encode._plan(current.tobytes(), target.tobytes())) == 2
