"""Following the tiles of a CD+G timeline: who drew what, when it was wiped and when it went.

The decoder (``vocatron.core.cdg``) says what each packet drew. This module turns that into
*sessions*: the lifetime of the text that stands in one tile row, from its first drawn tile to the
moment its last tile is cleared, overwritten, scrolled away or wiped out by a memory preset.
Sessions carry the wipe samples (time and pixel position of the highlight) and the colours.

The tracker keeps the pixels of every tile it follows (palette indices), so it sees what an XOR
tile *did*, not only what it said. Most real discs draw, highlight and erase text with XOR tiles
alone: text is XOR-ed onto the background (the colour of the last memory preset), the highlight
XORs the colour difference onto the text, and the same XOR with the sung-to-background
difference erases it. The inference rules (the limits of the inference are the limits of the
analysis):

- A normal tile with ink (some pixels set, two different colours) draws text; a normal tile
  without ink clears it. A tile sent again with the same pixels is ignored.
- A normal tile that repeats the shape of a tile but with another colour is a *recolour wipe*;
  drawn again in its unsung colour, or over a tile that was wiped or composed, it is new text.
- An XOR tile is judged by its result on the tile's *ink* (the pixels that differ from the
  tile's background colour): it **erases** when no ink is left, it **draws** text on a tile that
  had none, it **composes** (outline fonts, two-step drawing) when the set of ink pixels changes,
  and it is a **wipe sample** when the ink pixels stay the same and only their colour changes.
  Timing plays no part, so a wipe may start right after the draw (``DRAW_GAP`` only decides
  when a draw in a row begins a new session).
- An XOR on the tile that the tile packet just before drew or composed, at most
  ``LAYER_PACKETS`` packets later, is one more *layer* of that drawing, never a wipe: smoothed
  text is drawn as a tile and then XOR-ed bit planes on the same tile in the next packets, and a
  plane that happens to leave the ink pixels unchanged only changes their shade.
- An XOR with the colour of the running wipe on a tile with no text, within ``DRAW_GAP`` after
  a sample of a wipe in that row, is a wipe sample too (the highlight runs on past the text).
- The pixel position of a sample is the right edge of the pixels it changes.
- A scroll command moves the tiles with the content; text that leaves the screen on a scroll
  preset is gone (``scrolled``). A session keeps the rows it was drawn in; where it was wiped
  is in its wipe samples. The fine scroll offsets move only the displayed window, not the tiles.

Known limits: an XOR that recolours part of the ink of a tile and leaves the rest is a wipe
sample, even when the disc meant it as a (weird) composition; a drawn tile whose text colour is
the background colour is invisible and not seen; a wipe whose XOR also touches background
pixels of the tile (a column mask with a palette in which the changed background looks the
same) changes the set of ink pixels and is taken for composing. None of these was seen on the
real discs so far.
"""

from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from vocatron.core.cdg import (
    PALETTE_SIZE,
    TILE_COLUMNS,
    TILE_HEIGHT,
    TILE_ROWS,
    TILE_WIDTH,
    WIDTH,
    CdgEvent,
    CdgOp,
    Colour4,
)

DRAW_GAP = 0.5
"""Seconds of silence in a row after which a new drawing is a new session, and the longest pause
between two samples of a wipe that still carries the highlight on over a tile with no text."""

LAYER_PACKETS = 2
"""The most packets between a drawn tile and an XOR on it that is one more layer of the drawing
(on the real discs nearly every layer comes in the very next packet)."""

Key = tuple[int, int]
"""A tile position: row, column."""

Pixels = NDArray[np.uint8]
"""The 12 by 6 palette indices of one tile."""


def on_screen(start: float, end: float | None, time: float) -> bool:
    """Tell whether something shown from ``start`` until ``end`` (``None``: never gone) is up."""
    return start <= time and (end is None or time < end)


@dataclass(frozen=True, slots=True)
class Wipe:
    """One step of a highlight: an XOR tile or a recolour that reached ``frontier`` pixels.

    ``value`` is the colour the XOR tile used (the colour of the recolour, for a recolour);
    ``pixels`` is the number of pixels the step recoloured (0 over a tile with no text).
    """

    time: float
    row: int
    frontier: int
    unsung: int | None
    sung: int | None
    method: str
    value: int = 0
    pixels: int = 0


@dataclass(frozen=True, slots=True)
class Change:
    """A tile that appeared (``ink``) or disappeared, with the session it belonged to."""

    time: float
    row: int
    column: int
    ink: bool
    session: int


@dataclass(slots=True)
class Session:
    """The text in one tile row from its first tile to its end.

    ``rows`` are the tile rows it was drawn in (a scroll moves its tiles, not these); ``left``
    and ``right`` are its ink extent in pixels when drawn; the counters count its tiles by colour.
    """

    id: int
    start: float
    last_draw: float
    rows: set[int] = field(default_factory=set)
    tiles: int = 0
    end: float | None = None
    end_kind: str = "open"
    left: int = WIDTH
    right: int = 0
    wipes: list[Wipe] = field(default_factory=list)
    backgrounds: Counter[int] = field(default_factory=Counter)
    unsungs: Counter[int] = field(default_factory=Counter)
    edges: Counter[int] = field(default_factory=Counter)

    def alive_at(self, time: float) -> bool:
        """Tell whether the text is on the screen at ``time``."""
        return on_screen(self.start, self.end, time)


@dataclass(slots=True)
class _Tile:
    colours: Pixels
    base: int
    owner: int
    unsung: int
    edge: int | None = None
    composed: bool = False
    wiped: bool = False

    @property
    def ink(self) -> NDArray[np.bool_]:
        return self.colours != self.base


@dataclass(frozen=True, slots=True)
class Tracking:
    """What the pass over the timeline found.

    Attributes:
        sessions: All sessions in order of their start.
        changes: Every tile drawn or cleared by a tile packet (not wipes, presets or scrolls),
            in time order.
        palettes: The palette after each load, with its time (the first entry is the start).
        presets: The times of memory presets.
        scrolls: The times of scrolls that moved the content.
    """

    sessions: tuple[Session, ...]
    changes: tuple[Change, ...]
    palettes: tuple[tuple[float, tuple[Colour4, ...]], ...]
    presets: tuple[float, ...]
    scrolls: tuple[float, ...]


def _bits(pixels: tuple[int, ...]) -> NDArray[np.bool_]:
    """Return the 12 by 6 bits of a tile's pixel rows (the most significant bit at the left)."""
    rows = np.array(pixels, dtype=np.uint8)[:, None]
    return np.unpackbits(rows, axis=1)[:, 2:].astype(bool)


def _tile_colours(event: CdgEvent) -> Pixels:
    """Return the colours a tile packet puts (or XORs) onto its 12 by 6 pixels."""
    return np.where(_bits(event.pixels), event.colour1, event.colour0).astype(np.uint8)


def _extent(column: int, mask: NDArray[np.bool_]) -> tuple[int, int]:
    """Return the leftmost and the right edge (exclusive) pixel of the set pixels of a tile."""
    used = np.flatnonzero(mask.any(axis=0))
    return column * TILE_WIDTH + int(used[0]), column * TILE_WIDTH + int(used[-1]) + 1


def _roles(colours: Pixels, base: int) -> tuple[int, int | None]:
    """Return the text colour (most pixels) and the edge colour (the next one) of a tile's ink."""
    counts = Counter(int(c) for c in colours.ravel() if c != base)
    ranked = sorted(counts, key=lambda colour: (-counts[colour], colour))
    return ranked[0], (ranked[1] if len(ranked) > 1 else None)


class _Tracker:
    def __init__(self) -> None:
        self.tiles: dict[Key, _Tile] = {}
        self.bases: dict[Key, int] = {}
        self.fill = 0
        self.current: dict[int, Session] = {}
        self.sessions: list[Session] = []
        self.changes: list[Change] = []
        self.palette: list[Colour4] = [(0, 0, 0)] * PALETTE_SIZE
        self.palettes: list[tuple[float, tuple[Colour4, ...]]] = [(0.0, tuple(self.palette))]
        self.presets: list[float] = []
        self.scrolls: list[float] = []
        self.layering: tuple[Key, int] | None = None
        """The tile the last tile packet drew or composed, and its packet (else ``None``)."""
        self.previous: tuple[Key, int] | None = None
        self.packet = 0

    def handle(self, event: CdgEvent) -> None:
        self.packet = event.packet
        if event.op in (CdgOp.TILE, CdgOp.TILE_XOR):
            self.previous, self.layering = self.layering, None
        match event.op:
            case CdgOp.TILE:
                self._normal(event)
            case CdgOp.TILE_XOR:
                self._xor(event)
            case CdgOp.MEMORY_PRESET:
                self._clear_all(event.time)
                self.fill = event.colour0
                self.presets.append(event.time)
            case CdgOp.SCROLL_PRESET | CdgOp.SCROLL_COPY:
                self._scroll(event)
            case CdgOp.PALETTE:
                self.palette[event.first_colour : event.first_colour + len(event.colours)] = (
                    event.colours
                )
                self.palettes.append((event.time, tuple(self.palette)))
            case _:
                pass

    def result(self) -> Tracking:
        return Tracking(
            tuple(self.sessions),
            tuple(self.changes),
            tuple(self.palettes),
            tuple(self.presets),
            tuple(self.scrolls),
        )

    # ------------------------------------------------------------------ sessions

    def _session_for(self, time: float, row: int) -> Session:
        current = self.current.get(row)
        if (
            current is not None
            and current.end is None
            and not current.wipes
            and time - current.last_draw <= DRAW_GAP
        ):
            return current
        session = Session(len(self.sessions), start=time, last_draw=time)
        self.sessions.append(session)
        return session

    def _release(self, tile: _Tile, time: float, kind: str) -> None:
        session = self.sessions[tile.owner]
        session.tiles -= 1
        if session.tiles == 0 and session.end is None:
            session.end = time
            session.end_kind = kind

    def _count(self, session: Session, tile: _Tile, sign: int) -> None:
        """Add (``sign`` 1) or take away (-1) the colours of a tile from the session counters."""
        for counter, colour in ((session.unsungs, tile.unsung), (session.edges, tile.edge)):
            if colour is None:
                continue
            counter[colour] += sign
            if counter[colour] <= 0:
                del counter[colour]

    def _draw(self, time: float, key: Key, colours: Pixels, base: int) -> None:
        """Put a new tile with ink (replacing any old one) into the right session."""
        row, column = key
        session = self._session_for(time, row)
        text, edge = _roles(colours, base)
        tile = _Tile(colours, base, session.id, text, edge)
        old = self.tiles.get(key)
        self.tiles[key] = tile
        self.bases[key] = base
        session.tiles += 1
        session.rows.add(row)
        session.last_draw = time
        self._reach(session, column, tile)
        session.backgrounds[base] += 1
        self._count(session, tile, 1)
        self.current[row] = session
        self.changes.append(Change(time, row, column, True, session.id))
        self.layering = (key, self.packet)
        if old is not None:
            self._release(old, time, "replaced")

    @staticmethod
    def _reach(session: Session, column: int, tile: _Tile) -> None:
        left, right = _extent(column, tile.ink)
        session.left = min(session.left, left)
        session.right = max(session.right, right)

    def _remove(self, key: Key, time: float, kind: str) -> None:
        tile = self.tiles.pop(key)
        self.changes.append(Change(time, key[0], key[1], False, tile.owner))
        self._release(tile, time, kind)

    def _clear_all(self, time: float) -> None:
        for tile in self.tiles.values():
            self._release(tile, time, "preset")
        self.tiles.clear()
        self.bases.clear()
        self.current.clear()

    # ------------------------------------------------------------------ tiles

    def _normal(self, event: CdgEvent) -> None:
        key = (event.row, event.column)
        old = self.tiles.get(key)
        ink = any(event.pixels) and event.colour0 != event.colour1
        self.bases[key] = event.colour0
        if not ink:
            if old is not None:
                self._remove(key, event.time, "cleared")
            return
        colours = _tile_colours(event)
        if old is not None and not old.composed and not old.wiped and old.base == event.colour0:
            if np.array_equal(old.colours, colours):
                return  # a repeated packet: the tile shows exactly this already
            if np.array_equal(old.ink, colours != event.colour0) and event.colour1 != old.unsung:
                self._recolour(event, old, colours)
                return
        self._draw(event.time, key, colours, event.colour0)

    def _recolour(self, event: CdgEvent, old: _Tile, colours: Pixels) -> None:
        session = self.sessions[old.owner]
        _, right = _extent(event.column, old.ink)
        pixels = int(old.ink.sum())
        wipe = Wipe(
            event.time, event.row, right, old.unsung, event.colour1, "recolour",
            event.colour1, pixels,
        )  # fmt: skip
        session.wipes.append(wipe)
        old.colours = colours  # the tile shows its pattern in the sung colour now

    def _xor(self, event: CdgEvent) -> None:
        key = (event.row, event.column)
        old = self.tiles.get(key)
        base = old.base if old is not None else self.bases.get(key, self.fill)
        before = old.colours if old is not None else np.full((TILE_HEIGHT, TILE_WIDTH), base)
        after = before ^ _tile_colours(event)
        if np.array_equal(before, after):
            return
        if not (after != base).any():  # nothing is left: the text is erased
            if old is not None:
                self._remove(key, event.time, "cleared")
            return
        if old is None:
            if not self._carries_on(event):
                self._draw(event.time, key, after, base)
            return
        if np.array_equal(after != base, old.ink) and not self._layer(event):
            self._xor_wipe(event, old, after)
        else:
            self._compose(event, old, after)

    def _layer(self, event: CdgEvent) -> bool:
        """Tell whether an XOR is one more layer of the drawing of its tile (module docstring)."""
        if self.previous is None:
            return False
        key, packet = self.previous
        return key == (event.row, event.column) and event.packet - packet <= LAYER_PACKETS

    def _carries_on(self, event: CdgEvent) -> bool:
        """Tell whether an XOR over a tile with no text is the highlight running on past the text.

        If so, record the sample. It is when the row's running wipe stepped less than
        ``DRAW_GAP`` ago with the same XOR colour.
        """
        session = self.current.get(event.row)
        if session is None or session.end is not None or not session.wipes:
            return False
        last = session.wipes[-1]
        if last.value != event.colour1 or event.time - last.time > DRAW_GAP:
            return False
        _, right = _extent(event.column, _bits(event.pixels))
        session.wipes.append(
            Wipe(event.time, event.row, right, None, None, "xor", event.colour1, 0)
        )
        return True

    def _xor_wipe(self, event: CdgEvent, old: _Tile, after: Pixels) -> None:
        session = self.sessions[old.owner]
        changed = old.colours != after
        _, right = _extent(event.column, changed)
        pairs = Counter(zip(old.colours[changed].tolist(), after[changed].tolist(), strict=True))
        (unsung, sung), _ = max(pairs.items(), key=lambda item: (item[1], -item[0][0]))
        session.wipes.append(
            Wipe(
                event.time,
                event.row,
                right,
                unsung,
                sung,
                "xor",
                event.colour1,
                int(changed.sum()),
            )  # fmt: skip
        )
        old.colours = after
        old.wiped = True

    def _compose(self, event: CdgEvent, old: _Tile, after: Pixels) -> None:
        session = self.sessions[old.owner]
        session.last_draw = event.time
        self._count(session, old, -1)
        old.colours = after
        old.composed = True
        old.unsung, old.edge = _roles(after, old.base)
        self._count(session, old, 1)
        self._reach(session, event.column, old)
        self.layering = ((event.row, event.column), event.packet)

    # ------------------------------------------------------------------ scrolls

    def _scroll(self, event: CdgEvent) -> None:
        d_col = event.columns_moved
        d_row = event.rows_moved
        if d_col == 0 and d_row == 0:
            return
        self.scrolls.append(event.time)
        wrap = event.op is CdgOp.SCROLL_COPY

        def target(key: Key) -> Key | None:
            new_row, new_column = key[0] + d_row, key[1] + d_col
            if wrap:
                new_row, new_column = new_row % TILE_ROWS, new_column % TILE_COLUMNS
            if 0 <= new_row < TILE_ROWS and 0 <= new_column < TILE_COLUMNS:
                return new_row, new_column
            return None

        moved: dict[Key, _Tile] = {}
        for key, tile in self.tiles.items():
            if (new_key := target(key)) is not None:
                moved[new_key] = tile
            else:
                self._release(tile, event.time, "scrolled")
        self.tiles = moved
        shifted = ((target(key), base) for key, base in self.bases.items())
        self.bases = {key: base for key, base in shifted if key is not None}
        self.current = {}
        for (row, _), tile in moved.items():
            self.current[row] = self.sessions[tile.owner]


def track(events: tuple[CdgEvent, ...] | list[CdgEvent]) -> Tracking:
    """Follow ``events`` (as ``decode`` returns them) and return the sessions found."""
    tracker = _Tracker()
    for event in events:
        tracker.handle(event)
    return tracker.result()
