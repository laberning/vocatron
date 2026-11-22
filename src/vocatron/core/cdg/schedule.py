"""The scheduler: from target frames to a stream of packets, one per slot (ADR-0023).

The scheduler models the screen with ``CdgScreen``. Every tick (a hundredth of a second, three
packet slots) it compares the new target frame with the last one; each tile that changed joins a
queue with the tick it is due, unless it is queued already (it then keeps its place and is encoded
from the newest target when it is sent). Every slot sends the next packet of the tile at the head
of the queue and applies it to the model. Two queues keep the timing of the sweep: tiles of a wipe,
a bar or a countdown go before the tiles of lines that appear or go, which have the lead-in to be
drawn in. A page look (``clear_first``, ADR-0041) has a third queue between them: each tile of text
that appears or goes is first cleared (filled with the background, one packet, unless it shows the
background already) and then drawn, so old and new letters never share a tile and the new text
arrives from the top. Line looks redraw straight from the old text into the new one. All queues
are served oldest first, in row order within a tick.

``Scheduled.draw_lag`` and ``wipe_lag`` are the longest time between the tick a tile was due and the
slot that sent its last packet, for each queue (the tiles of a start screen before a swap do not
count). A target may name *deadlines*: pixels that must show
their target frame by a tick (a line must be fully drawn when its first syllable starts); the
scheduler looks at its model screen at that tick and reports the deadlines it missed. A line is
judged against the frame it is shown in, if that is later than the tick before it is sung.

A *swap* (ADR-0056) ends the start screen with the wordmark, which is drawn in a palette of its
own: at its tick the tiles still waiting are dropped, the packets of the swap (a memory preset and
the song's colour tables) are sent, the model screen is cleared and the target frames of the song
are queued from that tick on.
"""

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from vocatron.core.cdg.encode import plan_tile
from vocatron.core.cdg.packet import PACKETS_PER_SECOND, CdgPacket
from vocatron.core.cdg.raster import TICKS_PER_SECOND, Deadline, Frame
from vocatron.core.cdg.screen import (
    HEIGHT,
    TILE_COLUMNS,
    TILE_HEIGHT,
    TILE_ROWS,
    TILE_WIDTH,
    WIDTH,
    CdgScreen,
)
from vocatron.core.cdg.write import filler, tile_block

SLOTS_PER_TICK = PACKETS_PER_SECOND // TICKS_PER_SECOND
WIPE, CLEAR, DRAW = 0, 1, 2
"""The three queues: tiles of smooth changes; tiles of lines that appear or go, still to be cleared;
and those cleared, still to be drawn. ``Scheduled.draw_lag`` counts both of the last two."""
QUEUES = 3


class Targets(Protocol):
    """The frames the screen should show."""

    @property
    def deadlines(self) -> Sequence[Deadline]:
        """The pixels that must be drawn by a tick, for the report of the missed ones."""
        ...

    @property
    def ticks(self) -> int:
        """The number of ticks (hundredths of a second) with a frame."""
        ...

    def frame(self, tick: int) -> Frame:
        """Return the frame at ``tick``; the same array while nothing changes."""
        ...

    def redrawn(self, tick: int) -> NDArray[np.bool_]:
        """Return the tiles (18 by 50) of the elements that appear or go at ``tick``."""
        ...


@dataclass(frozen=True)
class Swap:
    """The end of the start screen: its palette is replaced by the song's.

    Attributes:
        tick: The first tick of the song's frames.
        packets: What is sent then: a memory preset in the background, the colour tables.
    """

    tick: int
    packets: Sequence[bytes]


@dataclass(frozen=True)
class Scheduled:
    """The stream and what the scheduler learnt writing it.

    Attributes:
        stream: The packets, 24 bytes each.
        draw_lag: The longest wait of a tile of a line that appears or goes, in seconds, from the
            moment it changed to its last packet (clearing included).
        wipe_lag: The longest wait of a tile of a wipe, a bar or a countdown, in seconds.
        drawing_packets: How many packets draw (the others are filler).
        missed: The numbers of the target's deadlines that were not met.
        settled: The ticks whose frame the screen showed in full before the next tick.
    """

    stream: bytes
    draw_lag: float
    wipe_lag: float
    drawing_packets: int
    missed: tuple[int, ...]
    settled: tuple[int, ...]


def as_packet(index: int, raw: bytes) -> CdgPacket:
    """Return the packet in the bytes ``raw`` as the decoder sees it at slot ``index``."""
    return CdgPacket(index=index, instruction=raw[1] & 0x3F, data=raw[4:20])


def _changed_tiles(frame: Frame, previous: Frame) -> NDArray[np.bool_]:
    """Return which tiles (18 by 50) differ between two frames."""
    differ = frame != previous
    # Two reductions over one axis each are several times faster than one over two axes.
    by_pixel_column = differ.reshape(TILE_ROWS, TILE_HEIGHT, WIDTH).any(axis=1)
    return by_pixel_column.reshape(TILE_ROWS, TILE_COLUMNS, TILE_WIDTH).any(axis=2)


class _Writer:
    """The state of one run of the scheduler: the model screen, the queues and the stream."""

    def __init__(
        self,
        targets: Targets,
        header: Sequence[bytes],
        background: int,
        clear_first: bool,
        swap_tick: int,
    ) -> None:
        self.targets = targets
        self.swap_tick = swap_tick  # tiles due before it belong to the start screen: no lag
        self.redraw_queue = CLEAR if clear_first else DRAW  # where a tile of changing text joins
        self.screen = CdgScreen()
        self.stream = bytearray()
        self.pending: deque[tuple[bytes, tuple[int, int] | None]] = deque(
            (raw, None) for raw in header
        )
        self.queues: tuple[dict[tuple[int, int], int], ...] = tuple({} for _ in range(QUEUES))
        self.current: Frame = np.full((HEIGHT, WIDTH), background, dtype=np.uint8)
        self.blank = np.full((TILE_HEIGHT, TILE_WIDTH), background, dtype=np.uint8)
        self.lags = [0] * QUEUES
        self.drawing = 0
        self.missed: list[int] = []
        self.due: dict[int, list[int]] = {}
        for number, deadline in enumerate(targets.deadlines):
            self.due.setdefault(deadline.tick, []).append(number)

    def swap(self, swap: Swap) -> None:
        """Drop what waits of the start screen and send the packets that replace its palette."""
        self.pending.clear()
        for queue in self.queues:
            queue.clear()
        self.pending.extend((raw, None) for raw in swap.packets)
        self.current = np.full_like(self.current, self.blank[0, 0])  # the preset clears the screen

    def idle(self) -> bool:
        """Tell whether nothing is left to send."""
        return not self.pending and not any(self.queues)

    def judge(self, tick: int) -> None:
        """Note the deadlines of ``tick`` whose pixels do not show their target yet."""
        for number in self.due.get(tick, ()):
            deadline = self.targets.deadlines[number]
            rows = slice(deadline.top, deadline.bottom)
            columns = slice(deadline.left, deadline.right)
            wanted = self.targets.frame(max(tick - 1, deadline.shown))[rows, columns]
            if not np.array_equal(self.screen.pixels[rows, columns], wanted):
                self.missed.append(number)

    def tick(self, tick: int) -> None:
        """Queue the tiles that changed in the frame of ``tick``."""
        frame = self.targets.frame(tick)
        if frame is self.current:
            return
        redrawn = self.targets.redrawn(tick)
        for row, column in np.argwhere(_changed_tiles(frame, self.current)):
            place = (int(row), int(column))
            if redrawn[place] and self.redraw_queue == CLEAR and place in self.queues[WIPE]:
                # text appears or goes in a tile that waits to be wiped: clear it first
                self.queues[CLEAR][place] = self.queues[WIPE].pop(place)
            elif not any(place in queue for queue in self.queues):
                self.queues[self.redraw_queue if redrawn[place] else WIPE][place] = tick
        self.current = frame

    def refill(self) -> None:
        """Take the next tile from the queues and plan its packets."""
        while not self.pending and any(self.queues):
            kind = next(kind for kind, queue in enumerate(self.queues) if queue)
            place, due = next(iter(self.queues[kind].items()))
            del self.queues[kind][place]
            row, column = place
            top, left = row * TILE_HEIGHT, column * TILE_WIDTH
            region = (slice(top, top + TILE_HEIGHT), slice(left, left + TILE_WIDTH))
            target = self.current[region]
            if kind == CLEAR:  # cleared first (no packet if blank), then drawn unless it only goes
                ops = plan_tile(self.screen.pixels[region], self.blank)
                if not np.array_equal(target, self.blank):
                    self.queues[DRAW][place] = due  # the wait goes on until it is drawn
                kind = DRAW  # its wait counts as one of drawing, up to its last packet
            else:
                ops = plan_tile(self.screen.pixels[region], target)
            for number, op in enumerate(ops):
                last = (kind, due) if number == len(ops) - 1 else None
                self.pending.append((tile_block(row, column, op), last))

    def send(self, slot: int) -> None:
        """Send the next packet in ``slot``, or filler when there is none."""
        if not self.pending:
            self.stream += filler()
            return
        raw, last = self.pending.popleft()
        self.screen.apply(as_packet(slot, raw))
        self.stream += raw
        self.drawing += 1
        if last is not None:
            kind, due = last
            if due >= self.swap_tick:  # the start screen's wait is not the song's lag
                self.lags[kind] = max(self.lags[kind], slot - SLOTS_PER_TICK * due)


def schedule(
    targets: Targets,
    header: Sequence[bytes],
    slots: int,
    background: int,
    clear_first: bool,
    swap: Swap | None = None,
) -> Scheduled:
    """Write ``slots`` packets that draw the target frames, after the ``header`` packets.

    Args:
        targets: The frames wanted.
        header: The packets that set up the screen (palette, presets), sent first.
        slots: The number of packets in the stream.
        background: The palette index the header fills the screen with.
        clear_first: Clear a tile that shows other text before new text is drawn in it (page
            looks, ADR-0041); otherwise it is redrawn straight from the old text into the new.
        swap: The end of the start screen with its own palette; the frames before its tick are
            drawn in that palette, the later ones in the song's.
    """
    writer = _Writer(targets, header, background, clear_first, 0 if swap is None else swap.tick)
    settled: list[int] = []
    for slot in range(slots):
        tick, phase = divmod(slot, SLOTS_PER_TICK)
        if phase == 0:
            if swap is not None and tick == swap.tick:
                writer.swap(swap)
            writer.judge(tick)
            if tick < targets.ticks:
                writer.tick(tick)
        writer.refill()
        writer.send(slot)
        if phase == SLOTS_PER_TICK - 1 and writer.idle():
            settled.append(tick)
    return Scheduled(
        stream=bytes(writer.stream),
        draw_lag=writer.lags[DRAW] / PACKETS_PER_SECOND,
        wipe_lag=writer.lags[WIPE] / PACKETS_PER_SECOND,
        drawing_packets=writer.drawing,
        missed=tuple(writer.missed),
        settled=tuple(settled),
    )
