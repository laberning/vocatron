"""Builders of CD+G packets: the inverse of ``packet.py`` (ADR-0023).

Every builder returns the 24 bytes of one packet: command 9, the instruction, the data and zero
parity bytes. ``CdgScreen`` decodes what they build, which is how the tests check them.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from vocatron.core.cdg import packet as codes
from vocatron.core.cdg.events import Colour4
from vocatron.core.cdg.packet import CDG_COMMAND, DATA_SIZE, PACKET_SIZE

PALETTE_HALF = 8
"""Entries in one colour table packet."""


def pack(instruction: int, data: Sequence[int] = ()) -> bytes:
    """Return one 24-byte drawing packet; ``data`` is padded with zeros to 16 bytes."""
    if len(data) > DATA_SIZE:
        raise ValueError(f"a packet holds {DATA_SIZE} data bytes, not {len(data)}")
    body = bytes(data).ljust(DATA_SIZE, b"\x00")
    return bytes([CDG_COMMAND, instruction, 0, 0]) + body + bytes(PACKET_SIZE - 4 - DATA_SIZE)


def filler() -> bytes:
    """Return the packet of a slot that draws nothing (command 0, which every player skips)."""
    return bytes(PACKET_SIZE)


def memory_preset(colour: int, repeat: int = 0) -> bytes:
    """Return a memory preset: the whole screen in ``colour``; ``repeat`` counts from 0."""
    return pack(codes.MEMORY_PRESET, [colour, repeat])


def border_preset(colour: int) -> bytes:
    """Return a border preset: the ring around the visible area in ``colour``."""
    return pack(codes.BORDER_PRESET, [colour])


def load_colours(entries: Sequence[Colour4], *, high: bool) -> bytes:
    """Return a colour table load for eight entries (indices 0 to 7, or 8 to 15 with ``high``).

    Raises:
        ValueError: If there are not exactly eight entries.
    """
    if len(entries) != PALETTE_HALF:
        raise ValueError("a colour table packet holds eight entries")
    data: list[int] = []
    for red, green, blue in entries:
        data += [(red << 2) | (green >> 2), ((green & 3) << 4) | blue]
    return pack(codes.LOAD_COLOURS_HIGH if high else codes.LOAD_COLOURS_LOW, data)


@dataclass(frozen=True, slots=True)
class TileOp:
    """What one tile block packet does to a tile.

    Attributes:
        colour0: The colour of the pixels with a 0 bit (or the XOR mask for them).
        colour1: The colour of the pixels with a 1 bit (or the XOR mask for them).
        pixels: The 12 pixel rows as 6-bit masks, the most significant bit at the left.
        xor: Combine the colours with the pixels already there by XOR instead of replacing them.
    """

    colour0: int
    colour1: int
    pixels: tuple[int, ...]
    xor: bool


def tile_block(row: int, column: int, op: TileOp) -> bytes:
    """Return the tile block packet of ``op`` for the tile at ``row`` and ``column``."""
    return pack(
        codes.TILE_BLOCK_XOR if op.xor else codes.TILE_BLOCK,
        [op.colour0, op.colour1, row, column, *op.pixels],
    )
