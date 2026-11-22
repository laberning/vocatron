"""From a CD+G scene to the bytes of a ``.cdg`` file (ADR-0023).

The stream starts with the colour table, the memory preset and the border preset, each repeated
so that a player that starts late or loses a packet still gets them, and goes on with the packets
the scheduler writes for the target frames. When the scene has a start screen with the wordmark,
the colour table of that screen comes first; when the screen ends, one memory preset and the song's
colour table replace it (ADR-0056).
"""

import math
from dataclasses import dataclass

from vocatron.core.cdg.packet import PACKET_SIZE, PACKETS_PER_SECOND
from vocatron.core.cdg.palette import Palette, build_palette, build_title_palette
from vocatron.core.cdg.raster import STEP, TargetFrames
from vocatron.core.cdg.schedule import Scheduled, Swap, schedule
from vocatron.core.cdg.write import PALETTE_HALF, border_preset, load_colours, memory_preset
from vocatron.core.measure import TextRasteriser
from vocatron.core.scene import Scene

MEMORY_REPEATS = 8
"""Memory preset packets at the start (repeat counts 0 to 7); a player uses the first it sees."""
BORDER_REPEATS = 2
"""Border preset packets at the start."""


@dataclass(frozen=True)
class CdgStream:
    """A finished CD+G stream.

    Attributes:
        stream: The bytes of the ``.cdg`` file.
        palette: The 16 colours of the song.
        scheduled: What the scheduler measured (lags, drawing packets).
        targets: The frames the stream aims at.
    """

    stream: bytes
    palette: Palette
    scheduled: Scheduled
    targets: TargetFrames

    @property
    def packets(self) -> int:
        """The number of packets in the stream."""
        return len(self.stream) // PACKET_SIZE


def colour_table(palette: Palette) -> list[bytes]:
    """Return the two packets that load ``palette``: the low half, then the high half."""
    entries = palette.entries
    return [
        load_colours(entries[:PALETTE_HALF], high=False),
        load_colours(entries[PALETTE_HALF:], high=True),
    ]


def header_packets(palette: Palette) -> list[bytes]:
    """Return the packets that set up the screen: colour table, memory preset, border preset."""
    return [
        *colour_table(palette),
        *(memory_preset(palette.background, repeat) for repeat in range(MEMORY_REPEATS)),
        *(border_preset(palette.background) for _ in range(BORDER_REPEATS)),
    ]


def swap_packets(palette: Palette) -> list[bytes]:
    """Return the packets that clear the screen and load ``palette``: a memory preset, two loads."""
    return [memory_preset(palette.background), *colour_table(palette)]


def build_stream(
    scene: Scene, rasteriser: TextRasteriser, wipe_columns: int = STEP, clear_first: bool = False
) -> CdgStream:
    """Write the CD+G stream of a scene laid out for the CD+G screen.

    Args:
        scene: The scene (``cdg_scene``).
        rasteriser: Draws the letters.
        wipe_columns: The pixels a wipe, a bar or a countdown moves at a time (the look's
            ``cdg.wipe_columns``).
        clear_first: Clear tiles before new text is drawn in them; the page looks do (ADR-0041).

    Raises:
        StageError: ``cdg-palette`` if the scene (or its start screen) needs more than 16 colours.
    """
    palette = build_palette(scene)
    title = build_title_palette(scene)
    targets = TargetFrames(scene, palette, rasteriser, wipe_columns, title)
    slots = math.ceil(scene.duration * PACKETS_PER_SECOND)
    swap = None
    if targets.swap_tick is not None:
        swap = Swap(targets.swap_tick, swap_packets(palette))
    scheduled = schedule(
        targets, header_packets(title or palette), slots, palette.background, clear_first, swap
    )
    return CdgStream(scheduled.stream, palette, scheduled, targets)
