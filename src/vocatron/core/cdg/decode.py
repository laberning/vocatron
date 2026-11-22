"""Decoding a whole CD+G stream into a timeline and frame snapshots."""

from collections.abc import Sequence
from dataclasses import dataclass

from vocatron.core.cdg.events import CdgEvent, Colour4
from vocatron.core.cdg.packet import PACKET_SIZE, PACKETS_PER_SECOND, parse_packets
from vocatron.core.cdg.screen import CdgScreen, Frame

SNAPSHOT_EPSILON = 1e-9


@dataclass(frozen=True, slots=True)
class CdgDecoding:
    """The result of decoding a stream.

    Attributes:
        events: Every event that changed the screen, in packet order.
        packet_count: The number of packets in the stream (drawing or not).
        frames: The palette-index frames requested as snapshots, in the order requested.
        palettes: The palette in force at each snapshot (16 entries of 4-bit red, green and
            blue), in the order requested; a stream may replace its palette (ADR-0056).
    """

    events: tuple[CdgEvent, ...]
    packet_count: int
    frames: tuple[Frame, ...]
    palettes: tuple[tuple[Colour4, ...], ...] = ()

    @property
    def duration(self) -> float:
        """The length of the stream in seconds."""
        return self.packet_count / PACKETS_PER_SECOND


def decode(stream: bytes, snapshots: Sequence[float] = ()) -> CdgDecoding:
    """Decode ``stream`` and take a frame at each time in ``snapshots``.

    A snapshot at ``t`` shows the screen after every packet played up to and including time
    ``t``; a time after the end gives the final screen. Decoding is deterministic and has no
    side effects.
    """
    order = sorted(range(len(snapshots)), key=lambda i: snapshots[i])
    limits = [int(snapshots[i] * PACKETS_PER_SECOND + SNAPSHOT_EPSILON) for i in order]
    taken: dict[int, Frame] = {}
    palettes: dict[int, tuple[Colour4, ...]] = {}
    screen = CdgScreen()
    events: list[CdgEvent] = []
    next_snapshot = 0

    def take_until(index: int) -> None:
        nonlocal next_snapshot
        while next_snapshot < len(order) and limits[next_snapshot] < index:
            taken[order[next_snapshot]] = screen.frame()
            palettes[order[next_snapshot]] = tuple(screen.palette)
            next_snapshot += 1

    for packet in parse_packets(stream):
        take_until(packet.index)
        if (event := screen.apply(packet)) is not None:
            events.append(event)
    take_until(len(stream) // PACKET_SIZE + 1 + max(limits, default=0))  # also late snapshots
    return CdgDecoding(
        events=tuple(events),
        packet_count=len(stream) // PACKET_SIZE,
        frames=tuple(taken[i] for i in range(len(snapshots))),
        palettes=tuple(palettes[i] for i in range(len(snapshots))),
    )
