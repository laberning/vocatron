"""The parser: an ASS file read back for the tests and the renderer (ADR-0009)."""

import re
from dataclasses import dataclass, field, replace

from vocatron.core.ass.timing import parse_time

_BLOCK = re.compile(r"\{([^}]*)\}")
_KARAOKE = re.compile(r"\\(kf|k)(\d+)")
_POS = re.compile(r"\\pos\(([-\d.]+),([-\d.]+)\)")
_SIZE = re.compile(r"\\fs([\d.]+)")
_MOVE = re.compile(r"\\move\(([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+),(\d+),(\d+)\)")
_FADE = re.compile(r"\\fad\((\d+),(\d+)\)")
_RECOLOUR = re.compile(r"\\1c(&H[0-9A-F]+)\\2c(&H[0-9A-F]+)\\3c(&H[0-9A-F]+)")


@dataclass(frozen=True)
class Sweep:
    r"""One karaoke piece of an event.

    Attributes:
        tag: ``k`` or ``kf``.
        centis: The duration.
        text: The text.
        colours: The sung, unsung and edge colours (``&HAABBGGRR``) this piece switches to, or
            ``None`` when it keeps those before it (a turn of singers, ``\1c\2c\3c``).
    """

    tag: str
    centis: int
    text: str
    colours: tuple[str, str, str] | None = None


@dataclass(frozen=True)
class Event:
    r"""One ``Dialogue:`` line read back.

    Attributes:
        start: Start in centiseconds.
        end: End in centiseconds.
        style: The style name.
        position: The ``\\pos`` of the event, or ``None``.
        size: The ``\\fs`` of the event, or ``None``.
        move: The ``\\move`` of the event as ``(x1, y1, x2, y2, t1, t2)`` with the times in
            milliseconds, or ``None``.
        fade_in_ms: The fade-in of ``\fad``, or 0.
        fade_out_ms: The fade-out of ``\fad``, or 0.
        layer: The layer.
        tags: Every override block of the event, one after the other, without the braces.
        sweeps: The karaoke pieces in order (gaps have the empty text).
        text: The visible text without any tag; empty for a drawing.
        drawing: Whether the event is a vector drawing.
    """

    start: int
    end: int
    style: str
    position: tuple[float, float] | None
    size: float | None
    fade_out_ms: int
    sweeps: tuple[Sweep, ...]
    text: str
    drawing: bool
    fade_in_ms: int = 0
    layer: int = 0
    tags: str = ""
    move: tuple[float, float, float, float, int, int] | None = None

    @property
    def sweep_end(self) -> int:
        """Where the karaoke durations end, in centiseconds on the song's timeline."""
        return self.start + sum(sweep.centis for sweep in self.sweeps)


@dataclass(frozen=True)
class Script:
    """A parsed ASS file.

    Attributes:
        width: ``PlayResX``.
        height: ``PlayResY``.
        styles: The style names with their font name.
        events: The events in file order.
    """

    width: int
    height: int
    styles: dict[str, str] = field(default_factory=dict)
    events: tuple[Event, ...] = ()


def _event(row: str) -> Event:
    """Read one ``Dialogue:`` line (its text is the tenth field)."""
    fields = row.removeprefix("Dialogue:").strip().split(",", 9)
    text = fields[9]
    sweeps: list[Sweep] = []
    plain = ""
    drawing = False
    position = size = move = None
    fade = fade_in = 0
    blocks: list[str] = []
    cursor = 0
    pending: Sweep | None = None  # the last karaoke tag, waiting for its text
    for block in _BLOCK.finditer(text):
        piece = text[cursor : block.start()]
        if pending is not None:
            sweeps.append(replace(pending, text=piece))
        plain += piece
        tags = block.group(1)
        pending = None
        recolour = _RECOLOUR.search(tags)
        colours = None if recolour is None else (recolour[1], recolour[2], recolour[3])
        for found in _KARAOKE.finditer(tags):
            if pending is not None:
                sweeps.append(pending)
            pending = Sweep(found.group(1), int(found.group(2)), "", colours)
            colours = None  # only the first piece of a block switches the colours
        place, scale, fader = _POS.search(tags), _SIZE.search(tags), _FADE.search(tags)
        position = (float(place.group(1)), float(place.group(2))) if place else position
        moved = _MOVE.search(tags)
        if moved:
            x1, y1, x2, y2, t1, t2 = moved.groups()
            move = (float(x1), float(y1), float(x2), float(y2), int(t1), int(t2))
        size = float(scale.group(1)) if scale else size
        fade = int(fader.group(2)) if fader else fade
        fade_in = int(fader.group(1)) if fader else fade_in
        blocks.append(tags)
        drawing = drawing or "\\p1" in tags
        cursor = block.end()
    tail = text[cursor:]
    if pending is not None:
        sweeps.append(replace(pending, text=tail))
    plain += tail
    return Event(
        start=parse_time(fields[1]),
        end=parse_time(fields[2]),
        style=fields[3],
        position=position,
        size=size,
        fade_out_ms=fade,
        sweeps=tuple(sweeps),
        text="" if drawing else plain,
        drawing=drawing,
        fade_in_ms=fade_in,
        layer=int(fields[0]),
        tags="".join(blocks),
        move=move,
    )


def parse_ass(text: str) -> Script:
    """Read an ASS file written by :func:`write_ass`.

    Raises:
        ValueError: If the file has no ``PlayResX`` or ``PlayResY``.
    """
    rows = text.splitlines()
    res = {
        key: int(value)
        for row in rows
        if (found := re.fullmatch(r"(PlayRes[XY]): (\d+)", row))
        for key, value in [found.groups()]
    }
    if set(res) != {"PlayResX", "PlayResY"}:
        raise ValueError("the file has no PlayResX and PlayResY")
    styles = {
        row.removeprefix("Style:").split(",")[0].strip(): row.split(",")[1]
        for row in rows
        if row.startswith("Style:")
    }
    events = tuple(_event(row) for row in rows if row.startswith("Dialogue:"))
    return Script(res["PlayResX"], res["PlayResY"], styles, events)
