"""Hand-built CD+G packets and streams for the tests of the decoder and the analysis.

Everything here is invented: no real disc, song or lyrics. ``CdgBuilder`` places packets at times
(300 per second) and fills the gaps with packets of another command, the way a disc has them.
"""

from vocatron.core.cdg import PACKET_SIZE, PACKETS_PER_SECOND, decode
from vocatron.lab.cdg.analysis import Analysis, analyse

FULL = 0b111111
BLANK = (0,) * 12
SOLID = (FULL,) * 12


def packet(instruction: int, data: bytes | list[int] = b"") -> bytes:
    """Return a 24-byte drawing packet with ``data`` padded to 16 bytes (parity left zero)."""
    body = bytes(data)[:16].ljust(16, b"\x00")
    return bytes([9, instruction, 0, 0]) + body + bytes(4)


def filler() -> bytes:
    """Return a packet of another command, which a decoder must skip."""
    return bytes(PACKET_SIZE)


def memory_preset(colour: int, repeat: int = 0) -> bytes:
    """Return a memory preset packet."""
    return packet(1, [colour, repeat])


def border_preset(colour: int) -> bytes:
    """Return a border preset packet."""
    return packet(2, [colour])


def tile(
    row: int,
    column: int,
    pixels: tuple[int, ...] = SOLID,
    colour0: int = 0,
    colour1: int = 1,
    *,
    xor: bool = False,
) -> bytes:
    """Return a tile block packet (normal, or XOR with ``xor=True``)."""
    return packet(38 if xor else 6, [colour0, colour1, row, column, *pixels])


def scroll(
    h_command: int = 0,
    v_command: int = 0,
    colour: int = 0,
    h_offset: int = 0,
    v_offset: int = 0,
    *,
    copy: bool = False,
) -> bytes:
    """Return a scroll packet (preset, or copy with ``copy=True``)."""
    return packet(
        24 if copy else 20, [colour, (h_command << 4) | h_offset, (v_command << 4) | v_offset]
    )


def transparent(colour: int) -> bytes:
    """Return a define-transparent-colour packet."""
    return packet(28, [colour])


def palette(entries: list[tuple[int, int, int]], *, high: bool = False) -> bytes:
    """Return a colour table load for eight 4-bit RGB entries (indices 0 to 7, or 8 to 15)."""
    data: list[int] = []
    for red, green, blue in entries:
        data += [(red << 2) | (green >> 2), ((green & 3) << 4) | blue]
    return packet(31 if high else 30, data)


class CdgBuilder:
    """Collects packets at packet indices and renders the stream."""

    def __init__(self) -> None:
        """Start an empty stream."""
        self.packets: list[bytes] = []

    def at(self, seconds: float) -> CdgBuilder:
        """Pad with filler packets until the next packet plays at ``seconds`` (never backwards)."""
        target = round(seconds * PACKETS_PER_SECOND)
        self.packets.extend(filler() for _ in range(target - len(self.packets)))
        return self

    def add(self, *packets: bytes) -> CdgBuilder:
        """Append packets directly after the current position."""
        self.packets.extend(packets)
        return self

    def end(self, seconds: float) -> bytes:
        """Pad to ``seconds`` and return the stream."""
        self.at(seconds)
        return b"".join(self.packets)


# ---------------------------------------------------------------- a synthetic classic disc

WIPE_STEP = 0.1  # seconds per tile of the highlight in the synthetic song


def draw_line(row: int, first: int, last: int, colour1: int = 2, colour0: int = 0) -> list[bytes]:
    """Return normal tiles that draw text across the columns ``first`` to ``last`` of a row."""
    return [tile(row, column, SOLID, colour0, colour1) for column in range(first, last + 1)]


def erase_line(row: int, first: int, last: int) -> list[bytes]:
    """Return normal tiles without ink across the columns, which clear the row there."""
    return [tile(row, column, BLANK, 0, 0) for column in range(first, last + 1)]


def wipe_line(  # noqa: PLR0913 - a row, its columns, the XOR colour and mask are all needed
    builder: CdgBuilder,
    start: float,
    row: int,
    first: int,
    last: int,
    flip: int = 1,
    *,
    pixels: tuple[int, ...] = SOLID,
) -> None:
    """Add a highlight that crosses the columns, one tile per ``WIPE_STEP`` seconds."""
    for step, column in enumerate(range(first, last + 1)):
        builder.at(start + step * WIPE_STEP).add(tile(row, column, pixels, 0, flip, xor=True))


OUTLINE = (0b111111,) + (0b100001,) * 10 + (0b111111,)
"""The ring of pixels around FILL in a tile: 32 pixels."""
FILL = (0,) + (0b011110,) * 10 + (0,)
"""The inside of OUTLINE: 40 pixels, so the fill colour is the one with most pixels."""


def draw_outline_line(
    row: int, first: int, last: int, outline: int = 1, fill: int = 3
) -> list[bytes]:
    """Return packets that draw outline text the way real discs do: a ring, then the fill by XOR.

    The ring is a normal tile in ``outline``; the XOR tile over it adds ``FILL`` in ``fill`` (the
    set of ink pixels grows), so the tile is composed, not wiped.
    """
    packets = [tile(row, c, OUTLINE, 0, outline) for c in range(first, last + 1)]
    packets += [tile(row, c, FILL, 0, fill, xor=True) for c in range(first, last + 1)]
    return packets


def classic_song() -> tuple[bytes, float]:
    """Build a 50-second disc with a title, two lines, a break with a countdown and a duet line.

    Palette: 0 black, 1 grey, 2 white (unsung) and 3 red (sung, 2 xor 1), 4 blue (unsung of the
    second singer) and 5 cyan (sung, 4 xor 1). Returns the stream and its length in seconds.
    """
    low = [
        (0, 0, 0),
        (3, 3, 3),
        (15, 15, 15),
        (15, 0, 0),
        (0, 0, 15),
        (0, 15, 15),
        (0, 0, 0),
        (0, 0, 0),
    ]
    builder = CdgBuilder().at(0.0).add(palette(low), memory_preset(0))
    builder.at(0.5).add(*draw_line(4, 10, 39), *draw_line(6, 12, 37))  # the title, two lines
    builder.at(6.0).add(memory_preset(0))  # the title goes, the screen is cleared
    builder.at(7.0).add(*draw_line(5, 8, 41))  # line 1, centred
    builder.at(7.2).add(*draw_line(8, 14, 35))  # line 2, centred
    wipe_line(builder, 9.0, 5, 8, 41)
    wipe_line(builder, 13.0, 8, 14, 35)
    builder.at(17.0).add(*erase_line(5, 8, 41))
    builder.at(17.2).add(*erase_line(8, 14, 35))
    for tick, column in enumerate(range(1, 4)):  # the countdown: four dots, one per second
        builder.at(36.0 + tick).add(tile(3, column, SOLID, 0, 2))
    builder.at(38.4).add(*draw_line(5, 11, 38, colour1=4))  # line 3, the second singer
    builder.at(39.0).add(tile(3, 4, SOLID, 0, 2))
    wipe_line(builder, 40.0, 5, 11, 38)
    return builder.end(50.0), 50.0


def measure(stream: bytes, duration: float) -> Analysis:
    """Decode ``stream`` and analyse it as a disc of ``duration`` seconds."""
    return analyse(decode(stream).events, duration)
