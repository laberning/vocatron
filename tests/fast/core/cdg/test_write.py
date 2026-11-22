"""Stage 1: the CD+G packet builders and the tile encoder, checked by decoding what they write."""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fakes import cdg as hand
from vocatron.core.cdg import PACKET_SIZE, CdgOp, CdgScreen, decode, parse_packets
from vocatron.core.cdg.encode import plan_tile
from vocatron.core.cdg.schedule import as_packet
from vocatron.core.cdg.screen import TILE_HEIGHT, TILE_WIDTH
from vocatron.core.cdg.write import (
    TileOp,
    border_preset,
    filler,
    load_colours,
    memory_preset,
    pack,
    tile_block,
)

ROWS = (0b101010, 0b010101) * 6


def test_every_packet_is_24_bytes_with_command_9_and_zero_parity() -> None:
    for raw in (
        memory_preset(3),
        border_preset(4),
        load_colours([(1, 2, 3)] * 8, high=False),
        tile_block(2, 3, TileOp(1, 2, ROWS, xor=False)),
    ):
        assert len(raw) == PACKET_SIZE
        assert raw[0] == 9
        assert raw[2:4] == b"\0\0"
        assert raw[20:] == b"\0\0\0\0"


def test_a_filler_packet_draws_nothing() -> None:
    assert len(filler()) == PACKET_SIZE
    assert list(parse_packets(filler() * 3)) == []


def test_too_much_data_for_a_packet_is_an_error() -> None:
    with pytest.raises(ValueError, match="16 data bytes"):
        pack(1, [0] * 17)


def test_the_builders_agree_with_the_hand_built_packets_of_the_decoder_tests() -> None:
    assert memory_preset(5, 2) == hand.memory_preset(5, 2)
    assert border_preset(7) == hand.border_preset(7)
    colours = [
        (0, 0, 0),
        (3, 3, 3),
        (15, 15, 15),
        (15, 0, 0),
        (0, 0, 15),
        (0, 15, 15),
        (1, 2, 3),
        (4, 5, 6),
    ]
    assert load_colours(colours, high=False) == hand.palette(colours)
    assert load_colours(colours, high=True) == hand.palette(colours, high=True)
    assert tile_block(4, 9, TileOp(2, 5, ROWS, xor=True)) == hand.tile(4, 9, ROWS, 2, 5, xor=True)
    assert tile_block(4, 9, TileOp(2, 5, ROWS, xor=False)) == hand.tile(4, 9, ROWS, 2, 5)


def test_a_colour_table_load_needs_eight_entries() -> None:
    with pytest.raises(ValueError, match="eight"):
        load_colours([(0, 0, 0)] * 7, high=False)


def test_a_written_colour_table_and_presets_decode_to_what_was_written() -> None:
    colours = [(i, 15 - i, (3 * i) % 16) for i in range(16)]
    stream = (
        load_colours(colours[:8], high=False)
        + load_colours(colours[8:], high=True)
        + memory_preset(5)
        + border_preset(6)
    )
    screen = CdgScreen()
    events = [screen.apply(p) for p in parse_packets(stream)]
    assert [e.op for e in events if e] == [
        CdgOp.PALETTE, CdgOp.PALETTE, CdgOp.MEMORY_PRESET, CdgOp.BORDER_PRESET,
    ]  # fmt: skip
    assert screen.palette == colours
    assert screen.border == 6
    frame = screen.frame()
    assert frame[0, 0] == 6 and frame[100, 100] == 5


def tile_of(values: list[list[int]]) -> np.ndarray:
    return np.array(values, dtype=np.uint8)


def reach(current: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, int]:
    """Send the planned packets through the decoder's screen and return the tile and the count."""
    screen = CdgScreen()
    screen.pixels[:TILE_HEIGHT, :TILE_WIDTH] = current
    ops = plan_tile(current, target)
    for number, op in enumerate(ops):
        screen.apply(as_packet(number, tile_block(0, 0, op)))
    return screen.pixels[:TILE_HEIGHT, :TILE_WIDTH].copy(), len(ops)


@st.composite
def tiles(draw: st.DrawFn, colours: int = 16) -> np.ndarray:
    values = draw(
        st.lists(
            st.integers(0, colours - 1),
            min_size=TILE_HEIGHT * TILE_WIDTH,
            max_size=TILE_HEIGHT * TILE_WIDTH,
        )
    )
    return np.array(values, dtype=np.uint8).reshape(TILE_HEIGHT, TILE_WIDTH)


@settings(max_examples=300, deadline=None)
@given(current=tiles(), target=tiles())
def test_random_tiles_decode_back_exactly(current: np.ndarray, target: np.ndarray) -> None:
    result, count = reach(current, target)
    assert np.array_equal(result, target)
    assert count <= 6  # four bit planes at the most, after a normal block


@settings(max_examples=200, deadline=None)
@given(current=tiles(4), target=tiles(4))
def test_tiles_of_few_colours_need_few_packets(current: np.ndarray, target: np.ndarray) -> None:
    result, count = reach(current, target)
    assert np.array_equal(result, target)
    assert count <= 3


def test_equal_tiles_need_no_packet() -> None:
    tile = np.full((TILE_HEIGHT, TILE_WIDTH), 4, dtype=np.uint8)
    assert plan_tile(tile, tile) == []


def test_a_wipe_step_is_one_xor_packet_with_the_mask() -> None:
    current = np.full((TILE_HEIGHT, TILE_WIDTH), 2, dtype=np.uint8)
    current[:, 3:] = 0  # the letters' colour on the left half, background on the right
    target = current.copy()
    target[:, :2][target[:, :2] == 2] = 2 ^ 6  # the wipe reaches two more columns
    (op,) = plan_tile(current, target)
    assert op.xor and op.colour1 == 6 and op.colour0 == 0


def test_an_erase_is_one_normal_packet() -> None:
    current = tile_of([[1, 2, 3, 1, 2, 3]] * TILE_HEIGHT)
    target = np.zeros((TILE_HEIGHT, TILE_WIDTH), dtype=np.uint8)
    (op,) = plan_tile(current, target)
    assert not op.xor and op.pixels == (0,) * TILE_HEIGHT and (op.colour0, op.colour1) == (0, 0)


def test_a_tile_of_three_colours_is_a_normal_block_and_one_xor_block() -> None:
    current = np.zeros((TILE_HEIGHT, TILE_WIDTH), dtype=np.uint8)
    target = current.copy()
    target[:, :2], target[:, 2:4] = 5, 7  # background, shade and ink
    ops = plan_tile(current, target)
    assert len(ops) == 2


def test_the_decoder_sees_the_stream_of_a_whole_frame_as_written() -> None:
    stream = memory_preset(0) + tile_block(5, 7, TileOp(0, 9, ROWS, xor=False))
    events = decode(stream).events
    assert (events[1].op, events[1].row, events[1].column, events[1].pixels) == (
        CdgOp.TILE, 5, 7, ROWS,
    )  # fmt: skip
