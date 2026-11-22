"""The CD+G screen: 300 by 216 pixels of 16 palette colours, drawn by packets.

The screen is 50 by 18 tiles of 6 by 12 pixels. The visible area is the inner 288 by 192 pixels,
the outer ring is the border. Written from the published format description; the details that
players handle differently are chosen as follows and are part of the contract:

- A memory preset with a non-zero repeat count is a repetition of an earlier one and is ignored.
- A memory preset fills the whole screen including the border, a border preset only the ring.
  A border preset has no repeat count and is applied every time (a repetition changes nothing
  unless tiles were drawn into the border in between).
- A tile outside the 50 by 18 grid is ignored.
- A scroll shifts the whole 300 by 216 pixels; "copy" wraps what leaves on one side in on the
  other, "preset" fills the new area with the given colour. The fine scroll offset moves the
  displayed window into the content (content shifts left and up by the offset).
"""

import numpy as np
from numpy.typing import NDArray

from vocatron.core.cdg import packet as codes
from vocatron.core.cdg.events import CdgEvent, CdgOp, Colour4, scroll_step
from vocatron.core.cdg.packet import MASK_6_BITS, CdgPacket

WIDTH = 300
HEIGHT = 216
TILE_WIDTH = 6
TILE_HEIGHT = 12
TILE_COLUMNS = WIDTH // TILE_WIDTH
TILE_ROWS = HEIGHT // TILE_HEIGHT
BORDER_X = TILE_WIDTH
BORDER_Y = TILE_HEIGHT
PALETTE_SIZE = 16
MAX_H_OFFSET = 5
MAX_V_OFFSET = 11
MASK_4_BITS = 0x0F
MASK_5_BITS = 0x1F

Frame = NDArray[np.uint8]


_ROW_BITS = (
    (np.arange(1 << TILE_WIDTH)[:, None] >> np.arange(TILE_WIDTH - 1, -1, -1)[None, :]) & 1
).astype(np.bool_)
"""The six pixels (most significant bit left) of each of the 64 possible tile rows."""


def _bit_mask(rows: tuple[int, ...]) -> NDArray[np.bool_]:
    """Return the 12 by 6 boolean grid of a tile's pixel rows (most significant bit left)."""
    return _ROW_BITS[np.array(rows)]


def _colour(high: int, low: int) -> Colour4:
    """Decode one palette entry from its two bytes."""
    high &= MASK_6_BITS
    low &= MASK_6_BITS
    return ((high >> 2) & 15, ((high & 3) << 2) | (low >> 4), low & 15)


class CdgScreen:
    """The state of the screen, changed packet by packet with ``apply``.

    Attributes:
        pixels: The 216 by 300 palette indices of the content (before the fine scroll offset).
        palette: The 16 entries as 4-bit red, green and blue.
        border: The colour of the last border preset.
        transparent: The index set as transparent, or ``None``.
        h_offset: The horizontal fine scroll offset.
        v_offset: The vertical fine scroll offset.
    """

    def __init__(self) -> None:
        """Create a black screen with a black palette."""
        self.pixels: Frame = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
        self.palette: list[Colour4] = [(0, 0, 0)] * PALETTE_SIZE
        self.border = 0
        self.transparent: int | None = None
        self.h_offset = 0
        self.v_offset = 0

    def frame(self) -> Frame:
        """Return the displayed palette indices (a copy, with the fine scroll offset applied)."""
        return np.roll(self.pixels, (-self.v_offset, -self.h_offset), axis=(0, 1))

    def rgb_frame(self) -> NDArray[np.uint8]:
        """Return the displayed picture as 216 by 300 by 3 bytes (4-bit values scaled to 8)."""
        table = np.array(self.palette, dtype=np.uint8) * 17
        return table[self.frame()]

    def apply(self, packet: CdgPacket) -> CdgEvent | None:
        """Apply one packet; return its event, or ``None`` if it changed nothing or is unknown."""
        event: CdgEvent | None = None
        match packet.instruction:
            case codes.MEMORY_PRESET:
                event = self._memory_preset(packet)
            case codes.BORDER_PRESET:
                event = self._border_preset(packet)
            case codes.TILE_BLOCK:
                event = self._tile(packet, xor=False)
            case codes.TILE_BLOCK_XOR:
                event = self._tile(packet, xor=True)
            case codes.SCROLL_PRESET:
                event = self._scroll(packet, copy=False)
            case codes.SCROLL_COPY:
                event = self._scroll(packet, copy=True)
            case codes.TRANSPARENT_COLOUR:
                self.transparent = packet.data[0] & MASK_4_BITS
                event = CdgEvent(packet.index, CdgOp.TRANSPARENT, colour0=self.transparent)
            case codes.LOAD_COLOURS_LOW | codes.LOAD_COLOURS_HIGH:
                event = self._palette(packet)
        return event

    def _memory_preset(self, packet: CdgPacket) -> CdgEvent | None:
        if packet.data[1] & MASK_4_BITS:
            return None  # a repetition of the same preset
        colour = packet.data[0] & MASK_4_BITS
        self.pixels[:, :] = colour
        return CdgEvent(packet.index, CdgOp.MEMORY_PRESET, colour0=colour)

    def _border_preset(self, packet: CdgPacket) -> CdgEvent:
        colour = packet.data[0] & MASK_4_BITS
        self.border = colour
        inner = self.pixels[BORDER_Y : HEIGHT - BORDER_Y, BORDER_X : WIDTH - BORDER_X].copy()
        self.pixels[:, :] = colour
        self.pixels[BORDER_Y : HEIGHT - BORDER_Y, BORDER_X : WIDTH - BORDER_X] = inner
        return CdgEvent(packet.index, CdgOp.BORDER_PRESET, colour0=colour)

    def _tile(self, packet: CdgPacket, *, xor: bool) -> CdgEvent | None:
        data = packet.data
        colour0 = data[0] & MASK_4_BITS
        colour1 = data[1] & MASK_4_BITS
        row = data[2] & MASK_5_BITS
        column = data[3] & MASK_6_BITS
        if row >= TILE_ROWS or column >= TILE_COLUMNS:
            return None
        rows = tuple(byte & MASK_6_BITS for byte in data[4 : 4 + TILE_HEIGHT])
        colours = np.where(_bit_mask(rows), np.uint8(colour1), np.uint8(colour0))
        region = self.pixels[
            row * TILE_HEIGHT : (row + 1) * TILE_HEIGHT,
            column * TILE_WIDTH : (column + 1) * TILE_WIDTH,
        ]
        region[:, :] = region ^ colours if xor else colours
        return CdgEvent(
            packet.index,
            CdgOp.TILE_XOR if xor else CdgOp.TILE,
            colour0=colour0,
            colour1=colour1,
            row=row,
            column=column,
            pixels=rows,
        )

    def _scroll(self, packet: CdgPacket, *, copy: bool) -> CdgEvent:
        data = packet.data
        colour = data[0] & MASK_4_BITS
        h_command = (data[1] >> 4) & 3
        v_command = (data[2] >> 4) & 3
        self.h_offset = min(data[1] & 7, MAX_H_OFFSET)
        self.v_offset = min(data[2] & MASK_4_BITS, MAX_V_OFFSET)
        dx = scroll_step(h_command) * TILE_WIDTH
        dy = scroll_step(v_command) * TILE_HEIGHT
        self.pixels = np.roll(self.pixels, (dy, dx), axis=(0, 1))
        if not copy:
            if dy > 0:
                self.pixels[:dy, :] = colour
            elif dy < 0:
                self.pixels[dy:, :] = colour
            if dx > 0:
                self.pixels[:, :dx] = colour
            elif dx < 0:
                self.pixels[:, dx:] = colour
        return CdgEvent(
            packet.index,
            CdgOp.SCROLL_COPY if copy else CdgOp.SCROLL_PRESET,
            colour0=colour,
            h_command=h_command,
            v_command=v_command,
            h_offset=self.h_offset,
            v_offset=self.v_offset,
        )

    def _palette(self, packet: CdgPacket) -> CdgEvent:
        first = 8 if packet.instruction == codes.LOAD_COLOURS_HIGH else 0
        entries = tuple(
            _colour(packet.data[2 * i], packet.data[2 * i + 1]) for i in range(PALETTE_SIZE // 2)
        )
        self.palette[first : first + len(entries)] = entries
        return CdgEvent(packet.index, CdgOp.PALETTE, first_colour=first, colours=entries)
