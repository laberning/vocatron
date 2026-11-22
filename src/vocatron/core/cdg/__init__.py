"""CD+G: packets, the screen model and the decoder (pure; NumPy for the screen buffer).

``decode(stream)`` turns the bytes of a ``.cdg`` file into a timeline of drawing events and,
on request, frames. The analysis of classic discs and the tests of the CD+G output both use it.
"""

from vocatron.core.cdg.decode import CdgDecoding, decode
from vocatron.core.cdg.events import CdgEvent, CdgOp, Colour4
from vocatron.core.cdg.packet import PACKET_SIZE, PACKETS_PER_SECOND, CdgPacket, parse_packets
from vocatron.core.cdg.screen import (
    HEIGHT,
    PALETTE_SIZE,
    TILE_COLUMNS,
    TILE_HEIGHT,
    TILE_ROWS,
    TILE_WIDTH,
    WIDTH,
    CdgScreen,
)

__all__ = [
    "HEIGHT",
    "PACKETS_PER_SECOND",
    "PALETTE_SIZE",
    "PACKET_SIZE",
    "TILE_COLUMNS",
    "TILE_HEIGHT",
    "TILE_ROWS",
    "TILE_WIDTH",
    "WIDTH",
    "CdgDecoding",
    "CdgEvent",
    "CdgOp",
    "CdgPacket",
    "CdgScreen",
    "Colour4",
    "decode",
    "parse_packets",
]
