"""The timeline of a CD+G stream: one event per instruction that changed the screen."""

from dataclasses import dataclass
from enum import StrEnum

from vocatron.core.cdg.packet import packet_time

Colour4 = tuple[int, int, int]
"""A palette entry: red, green and blue with 4 bits each (0 to 15)."""

SCROLL_STEPS = {1: 1, 2: -1}
"""Tiles a scroll command moves the content: 1 right or down, 2 left or up; 0 and 3 do not move."""


def scroll_step(command: int) -> int:
    """Return the tiles a scroll command moves the content (``+1``, ``-1`` or ``0``)."""
    return SCROLL_STEPS.get(command, 0)


class CdgOp(StrEnum):
    """What an event did to the screen."""

    MEMORY_PRESET = "memory_preset"
    BORDER_PRESET = "border_preset"
    TILE = "tile"
    TILE_XOR = "tile_xor"
    SCROLL_PRESET = "scroll_preset"
    SCROLL_COPY = "scroll_copy"
    TRANSPARENT = "transparent"
    PALETTE = "palette"


@dataclass(frozen=True, slots=True)
class CdgEvent:
    """One drawing event with the packet it came from.

    Which fields mean something depends on ``op``; the others keep their defaults.

    Attributes:
        packet: The index of the packet in the stream.
        op: The kind of event.
        colour0: A tile's colour for 0 bits; the colour of a preset, of the fill of a scroll
            preset, or of the transparent entry.
        colour1: A tile's colour for 1 bits.
        row: A tile's row (0 to 17).
        column: A tile's column (0 to 49).
        pixels: A tile's 12 pixel rows as 6-bit masks, the most significant bit at the left.
        h_command: Horizontal scroll: 0 none, 1 six pixels right, 2 six pixels left.
        v_command: Vertical scroll: 0 none, 1 twelve pixels down, 2 twelve pixels up.
        h_offset: The horizontal fine scroll offset after a scroll (0 to 5).
        v_offset: The vertical fine scroll offset after a scroll (0 to 11).
        first_colour: For a palette load, the index of the first entry (0 or 8).
        colours: For a palette load, the eight entries.
    """

    packet: int
    op: CdgOp
    colour0: int = 0
    colour1: int = 0
    row: int = 0
    column: int = 0
    pixels: tuple[int, ...] = ()
    h_command: int = 0
    v_command: int = 0
    h_offset: int = 0
    v_offset: int = 0
    first_colour: int = 0
    colours: tuple[Colour4, ...] = ()

    @property
    def columns_moved(self) -> int:
        """For a scroll, the tile columns the content moved (positive to the right)."""
        return scroll_step(self.h_command)

    @property
    def rows_moved(self) -> int:
        """For a scroll, the tile rows the content moved (positive down)."""
        return scroll_step(self.v_command)

    @property
    def time(self) -> float:
        """The time in seconds at which the event happens."""
        return packet_time(self.packet)
