"""CD+G packets: the 24-byte units of the subcode stream, 300 per second.

A packet has a command byte, an instruction byte, two parity bytes, 16 data bytes and four more
parity bytes. Only packets whose command is 9 draw anything. The parity bytes are not checked: a
file that was ripped or produced without errors has none that matter, and the analysis is about
what a player would draw.
"""

from collections.abc import Iterator
from dataclasses import dataclass

PACKET_SIZE = 24
PACKETS_PER_SECOND = 300
CDG_COMMAND = 9
DATA_START = 4
DATA_SIZE = 16
MASK_6_BITS = 0x3F

MEMORY_PRESET = 1
BORDER_PRESET = 2
TILE_BLOCK = 6
SCROLL_PRESET = 20
SCROLL_COPY = 24
TRANSPARENT_COLOUR = 28
LOAD_COLOURS_LOW = 30
LOAD_COLOURS_HIGH = 31
TILE_BLOCK_XOR = 38


@dataclass(frozen=True, slots=True)
class CdgPacket:
    """One drawing packet.

    Attributes:
        index: The position in the stream counted in packets, so the time is ``index / 300``.
        instruction: The instruction code (the low six bits of the instruction byte).
        data: The 16 data bytes.
    """

    index: int
    instruction: int
    data: bytes


def packet_time(index: int) -> float:
    """Return the time in seconds at which the packet ``index`` is played."""
    return index / PACKETS_PER_SECOND


def parse_packets(stream: bytes) -> Iterator[CdgPacket]:
    """Yield the drawing packets of ``stream`` in order.

    Packets of other commands (and the filler between them) are skipped but still count for the
    index, so times stay right. A trailing partial packet is ignored.
    """
    for index in range(len(stream) // PACKET_SIZE):
        start = index * PACKET_SIZE
        if stream[start] & MASK_6_BITS != CDG_COMMAND:
            continue
        yield CdgPacket(
            index=index,
            instruction=stream[start + 1] & MASK_6_BITS,
            data=stream[start + DATA_START : start + DATA_START + DATA_SIZE],
        )
