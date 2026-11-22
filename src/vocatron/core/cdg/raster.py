"""The target frames of a CD+G scene: what the screen should show at every tick (ADR-0023).

Each element of the scene becomes an *art*: pixels of palette indices that know their state at a
time (how far the wipe is, how many dots are left, which number the timer shows) and paint it
into a frame. Text is drawn once from the rasteriser's coverage, in three classes (ink, one
shade level for smooth edges, edge); the edge is the dilation of the letters and is drawn only
when its colour differs from the background. A wipe moves in steps of the look's
``wipe_columns`` pixels (3 unless the look says otherwise), so a tile changes at most every few
ticks.

The tick is a hundredth of a second, three packet slots. ``TargetFrames.frame(tick)`` is the frame
for the time ``tick / 100``; frames are shared while nothing changes.

The fixed simplification of the CD+G output (ADR-0023, ADR-0029): colours of 12 bits, one shade
level, no shadow, fades are cuts.

The start screen with the wordmark (ADR-0056) is drawn in a palette of its own, without shades:
the wordmark as pixel letters with a one-pixel edge, a rounded frame, a rule and the texts in ink
only. The song's frames use the song's palette; the stream swaps the two when the screen ends
(``TargetFrames.swap_tick``).
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from vocatron.core.cdg.canvas import SAFE
from vocatron.core.cdg.palette import Palette, colour4, is_pixel_title
from vocatron.core.cdg.screen import HEIGHT, TILE_COLUMNS, TILE_HEIGHT, TILE_ROWS, TILE_WIDTH, WIDTH
from vocatron.core.measure import TextRasteriser
from vocatron.core.scene import (
    CardElement,
    CardLine,
    Colours,
    CountdownElement,
    LineElement,
    Look,
    PreviewElement,
    ProgressElement,
    Scene,
    SceneElement,
    TimerElement,
    TitleMark,
)
from vocatron.core.wordmark import (
    BAND_COLOURS,
    EDGE_COLOUR,
    pixel_band,
    pixel_word_cells,
)

Frame = NDArray[np.uint8]
Indices = NDArray[np.int16]

TICKS_PER_SECOND = 100
STEP = 3
"""The pixels a wipe, a bar or a countdown moves at a time unless the look says otherwise (half a
tile)."""
SHOWN_SLACK = 1e-6
"""Rounding slack when the tick a line first appears is worked out from its start in seconds."""
INK_MIN = 128
"""Coverage from which a pixel is ink."""
SHADE_MIN = 48
"""Coverage from which a pixel below ``INK_MIN`` is shade."""
INK_ONLY_MIN = 96
"""Coverage from which a pixel is ink in text without shades (the start screen): lower than
``INK_MIN``, so that thin strokes of small letters do not break up."""
NONE, SHADE, INK, EDGE = 0, 1, 2, 3
"""The class of a text pixel."""
CLEAR = -1
"""A pixel of a sprite that is not drawn."""
DONE = 1 << 20
"""The state of a wipe that has reached the end of the line."""
BAR_END = 0.01
"""The share of its width a shrinking bar ends with (and a progress bar starts with)."""
PROGRESS_FRAME = 0.2
"""The frame of a progress bar, of its height."""


class Art(Protocol):
    """An element's pixels, which paint themselves at a state."""

    @property
    def box(self) -> tuple[int, int, int, int]:
        """The pixels it can touch: top, bottom, left and right (the end exclusive)."""
        ...

    def state(self, time: float) -> int:
        """Return a number that changes exactly when what is drawn changes."""
        ...

    def paint(self, frame: Frame, state: int) -> None:
        """Draw the element in the state ``state`` into ``frame``."""
        ...


SAFE_LEFT, SAFE_TOP = round(SAFE.x), round(SAFE.y)
SAFE_RIGHT, SAFE_BOTTOM = round(SAFE.right), round(SAFE.bottom)


def fill_rect(frame: Frame, top: int, bottom: int, left: int, right: int, value: int) -> None:
    """Fill the pixels of a rectangle that lie in the visible area with ``value``."""
    top, bottom = max(top, SAFE_TOP), min(bottom, SAFE_BOTTOM)
    left, right = max(left, SAFE_LEFT), min(right, SAFE_RIGHT)
    if top < bottom and left < right:
        frame[top:bottom, left:right] = value


def stamp(frame: Frame, top: int, left: int, mask: NDArray[np.bool_], value: int) -> None:
    """Set the pixels of ``mask`` placed at ``top`` and ``left`` that lie in the visible area."""
    row0, col0 = max(SAFE_TOP - top, 0), max(SAFE_LEFT - left, 0)
    row1, col1 = min(SAFE_BOTTOM - top, mask.shape[0]), min(SAFE_RIGHT - left, mask.shape[1])
    if row0 < row1 and col0 < col1:
        region = frame[top + row0 : top + row1, left + col0 : left + col1]
        region[mask[row0:row1, col0:col1]] = value


def classify(coverage: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Return the class of each pixel of a coverage map: none, shade or ink."""
    classes = np.zeros(coverage.shape, dtype=np.uint8)
    classes[coverage >= SHADE_MIN] = SHADE
    classes[coverage >= INK_MIN] = INK
    return classes


def ink_only(coverage: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Return the class of each pixel of a coverage map for text without shades: ink or none."""
    return np.where(coverage >= INK_ONLY_MIN, INK, NONE).astype(np.uint8)


def with_edge(classes: NDArray[np.uint8], radius: int) -> NDArray[np.uint8]:
    """Return ``classes`` padded by ``radius`` pixels, with the edge around the letters.

    The edge is every pixel within ``radius`` pixels (a square) of ink or shade that is neither.
    """
    height, width = classes.shape
    padded = np.zeros((height + 2 * radius, width + 2 * radius), dtype=np.uint8)
    padded[radius : radius + height, radius : radius + width] = classes
    solid = padded > NONE
    grown = solid.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            grown |= np.roll(solid, (dy, dx), axis=(0, 1))
    padded[grown & ~solid] = EDGE
    return padded


def colours_per_span(line: LineElement) -> list[Colours]:
    """Return the colours of each syllable of a line: its own, or those of the turn it is in."""
    found: list[Colours] = []
    for index in range(len(line.spans)):
        colours = line.colours
        for turn in line.turns:
            if turn.span <= index:
                colours = turn.colours
        found.append(colours)
    return found


@dataclass(frozen=True)
class Sprite:
    """Palette indices at a place on the screen, cropped to the visible area.

    Attributes:
        top: The row of the first pixel.
        left: The column of the first pixel.
        unsung: The pixels before the wipe reaches them (``CLEAR`` where nothing is drawn).
        sung: The pixels after the wipe.
    """

    top: int
    left: int
    unsung: Indices
    sung: Indices

    @property
    def box(self) -> tuple[int, int, int, int]:
        """Top, bottom, left and right of the sprite."""
        height, width = self.unsung.shape
        return self.top, self.top + height, self.left, self.left + width


def _crop(top: int, left: int, unsung: Indices, sung: Indices) -> Sprite:
    """Cut the arrays down to the part that lies in the visible area."""
    height, width = unsung.shape
    row0, col0 = max(SAFE_TOP - top, 0), max(SAFE_LEFT - left, 0)
    row1, col1 = min(SAFE_BOTTOM - top, height), min(SAFE_RIGHT - left, width)
    if row0 >= row1 or col0 >= col1:
        return Sprite(top, left, unsung[:0, :0], sung[:0, :0])
    return Sprite(top + row0, left + col0, unsung[row0:row1, col0:col1], sung[row0:row1, col0:col1])


@dataclass(frozen=True)
class TextSpec:
    """A text to draw.

    Attributes:
        text: The text.
        size: The font size (the height of the line cell).
        edge: The width of the outline in pixels; it is drawn in whole pixels, at least one.
        x: Where the text starts (``text_x`` of the element).
        y: The top of the line cell (``text_y`` of the element).
    """

    text: str
    size: float
    edge: float
    x: float
    y: float


def text_sprite(
    rasteriser: TextRasteriser,
    palette: Palette,
    spec: TextSpec,
    bounds: Sequence[float],
    colours: Sequence[Colours],
) -> Sprite:
    """Draw text into a sprite with an unsung and a sung picture.

    Args:
        rasteriser: Draws the letters.
        palette: Maps colours to entries.
        spec: The text, its size, edge and place.
        bounds: The right ends of all but the last syllable, in pixels from the start of the text.
        colours: The colours of each syllable (one more than ``bounds``).
    """
    radius = max(1, round(spec.edge))
    coverage = rasteriser.coverage(spec.text, spec.size)
    classes = classify(coverage) if palette.shaded else ink_only(coverage)
    classes = with_edge(classes, radius)
    centres = np.arange(classes.shape[1]) - radius + 0.5
    which = np.searchsorted(np.asarray(bounds, dtype=float), centres, side="right")
    background = palette.entries[palette.background]
    tables: dict[str, NDArray[np.int16]] = {
        field: np.empty(len(colours), dtype=np.int16)
        for field in ("unsung_ink", "unsung_shade", "sung_ink", "sung_shade", "edge")
    }
    for number, each in enumerate(colours):
        tables["unsung_ink"][number], tables["unsung_shade"][number] = palette.ink(each.unsung)
        tables["sung_ink"][number], tables["sung_shade"][number] = palette.ink(each.sung)
        tables["edge"][number] = (
            CLEAR if colour4(each.edge) == background else palette.flat(each.edge)
        )
    columns = {field: table[which][None, :] for field, table in tables.items()}
    pictures: list[Indices] = []
    for state in ("unsung", "sung"):
        picture = np.full(classes.shape, CLEAR, dtype=np.int16)
        picture = np.where(classes == EDGE, columns["edge"], picture)
        picture = np.where(classes == SHADE, columns[f"{state}_shade"], picture)
        picture = np.where(classes == INK, columns[f"{state}_ink"], picture)
        pictures.append(picture.astype(np.int16))
    top, left = round(spec.y) - radius, round(spec.x) - radius
    return _crop(top, left, pictures[0], pictures[1])


class TextArt:
    """Text with an optional wipe: the pixels left of the front are sung."""

    def __init__(
        self, sprite: Sprite, wipe: tuple[LineElement, Look] | None = None, step: int = STEP
    ) -> None:
        """Create the art.

        Args:
            sprite: The unsung and sung pictures.
            wipe: The line whose wipe it follows and the look (offset and granularity of the
                wipe); ``None`` for text without a wipe.
            step: The pixels the wipe moves at a time.
        """
        self._sprite = sprite
        self._wipe = wipe
        self._step = step
        height, width = sprite.unsung.shape
        self._columns = np.arange(sprite.left, sprite.left + width)[None, :]
        self._rows = height
        self._origin = 0 if wipe is None else round(wipe[0].text_x)
        self._total = 0.0 if wipe is None else wipe[0].spans[-1].x1

    @property
    def box(self) -> tuple[int, int, int, int]:
        """The pixels the text can touch."""
        return self._sprite.box

    def state(self, time: float) -> int:
        """Return the front of the wipe in pixels, a multiple of the step; ``DONE`` at the end."""
        if self._wipe is None:
            return 0
        line, look = self._wipe
        front = line.wipe_front(time, look)
        if front >= self._total:
            return DONE
        return int(front // self._step) * self._step

    def paint(self, frame: Frame, state: int) -> None:
        """Draw the text with everything left of the front in its sung colours."""
        sprite = self._sprite
        if not self._rows:
            return
        picture = (
            np.where(self._columns < self._origin + state, sprite.sung, sprite.unsung)
            if state
            else sprite.unsung
        )
        top, bottom, left, right = sprite.box
        region = frame[top:bottom, left:right]
        drawn = picture != CLEAR
        region[drawn] = picture[drawn]


class Bar:
    """A rectangle that changes over the life of its element: the place and the progress."""

    def __init__(self, element: CountdownElement | ProgressElement) -> None:
        """Take the place and the times of ``element``."""
        box = element.box
        self._start, self._end = element.start, element.end
        self._top, self._left = round(box.y), round(box.x)
        self._height, self._width = max(1, round(box.h)), max(1, round(box.w))

    @property
    def box(self) -> tuple[int, int, int, int]:
        """The pixels the bar can touch."""
        return self._top, self._top + self._height, self._left, self._left + self._width

    def share(self, time: float) -> float:
        """Return how much of its life the element has lived at ``time`` (0 to 1)."""
        span = self._end - self._start
        return min(max((time - self._start) / span, 0.0), 1.0) if span > 0 else 1.0


def stepped(width: float, most: int, step: int = STEP) -> int:
    """Return ``width`` rounded up to a multiple of ``step``, at least 1 and at most ``most``."""
    return max(1, min(most, math.ceil(width / step) * step))


class ShrinkingBar(Bar):
    """A bar that shrinks to the left over the life of its element."""

    def __init__(self, element: CountdownElement, index: int, step: int = STEP) -> None:
        """Create the bar of ``element`` in the palette entry ``index``, moving ``step`` pixels."""
        super().__init__(element)
        self._index = index
        self._step = step

    def state(self, time: float) -> int:
        """Return the width of the bar, a multiple of the step (the full width at most)."""
        width = self._width * (1 - (1 - BAR_END) * self.share(time))
        return stepped(width, self._width, self._step)

    def paint(self, frame: Frame, state: int) -> None:
        """Draw the bar."""
        top, left = self._top, self._left
        fill_rect(frame, top, top + self._height, left, left + state, self._index)


class Dots:
    """Dots or blocks that go out one by one, the last one first."""

    def __init__(self, element: CountdownElement, index: int) -> None:
        """Create the dots of ``element`` in the palette entry ``index``."""
        box = element.box
        self._start, self._end, self._count = element.start, element.end, element.count
        self._top, self._left = round(box.y), round(box.x)
        self._size = max(2, round(box.h))
        self._pitch = box.w / element.count
        self._round = element.form == "dots"
        self._index = index
        grid = np.indices((self._size, self._size)) + 0.5 - self._size / 2
        self._disc = (grid[0] ** 2 + grid[1] ** 2) <= (self._size / 2) ** 2

    @property
    def box(self) -> tuple[int, int, int, int]:
        """The pixels the dots can touch."""
        right = self._left + round(self._pitch * (self._count - 1)) + self._size
        return self._top, self._top + self._size, self._left, right

    def state(self, time: float) -> int:
        """Return how many dots are still lit."""
        span = self._end - self._start
        if span <= 0:
            return 0
        left = self._count * (self._end - time) / span
        return min(max(math.ceil(left - 1e-9), 0), self._count)

    def paint(self, frame: Frame, state: int) -> None:
        """Draw the dots that are lit."""
        for number in range(state):
            left = self._left + round(self._pitch * number)
            if self._round:
                stamp(frame, self._top, left, self._disc, self._index)
            else:
                size = self._size
                fill_rect(frame, self._top, self._top + size, left, left + size, self._index)


class ProgressBar(Bar):
    """A frame with a fill that grows from the left over the life of its element."""

    def __init__(
        self, element: ProgressElement, colours: tuple[int, int, int], step: int = STEP
    ) -> None:
        """Create the bar of ``element``; ``colours`` are the entries of fill, frame, background.

        The fill grows ``step`` pixels at a time.
        """
        super().__init__(element)
        self._step = step
        self._edge = max(1, round(element.box.h * PROGRESS_FRAME))
        self._fill, self._frame, self._background = colours

    def state(self, time: float) -> int:
        """Return the width of the fill, a multiple of the step."""
        inner = max(self._width - 2 * self._edge, 1)
        return stepped(inner * (BAR_END + (1 - BAR_END) * self.share(time)), inner, self._step)

    def paint(self, frame: Frame, state: int) -> None:
        """Draw the frame and the fill inside it."""
        top, left, edge = self._top, self._left, self._edge
        bottom, right = top + self._height, left + self._width
        fill_rect(frame, top, bottom, left, right, self._frame)
        fill_rect(frame, top + edge, bottom - edge, left + edge, right - edge, self._background)
        fill_rect(frame, top + edge, bottom - edge, left + edge, left + edge + state, self._fill)


class TimerArt:
    """The timer of a break screen: the number of seconds left, each number drawn once.

    The state is the number shown, so a frame is drawn again exactly when the number changes.
    """

    def __init__(self, element: TimerElement, numbers: dict[int, TextArt]) -> None:
        """Create the art from ``element`` and the art of every number it shows."""
        self._element = element
        self._numbers = numbers
        boxes = [art.box for art in numbers.values()]
        self._box = (
            min(b[0] for b in boxes),
            max(b[1] for b in boxes),
            min(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )

    @property
    def box(self) -> tuple[int, int, int, int]:
        """The pixels any of the numbers can touch."""
        return self._box

    def state(self, time: float) -> int:
        """Return the number of seconds left."""
        return self._element.seconds_left(time)

    def paint(self, frame: Frame, state: int) -> None:
        """Draw the number ``state``."""
        self._numbers[state].paint(frame, 0)


def _timer_art(rasteriser: TextRasteriser, palette: Palette, timer: TimerElement) -> TimerArt:
    """Return the art of a timer: every number from 1 to its total, centred in the timer's box."""
    colours = Colours(unsung=timer.colour, sung=timer.colour, edge=timer.edge_colour)
    middle = timer.box.x + timer.box.w / 2
    numbers: dict[int, TextArt] = {}
    for number in range(1, timer.total + 1):
        text = str(number)
        width = rasteriser.coverage(text, timer.size).shape[1]
        spec = TextSpec(text, timer.size, timer.edge, middle - width / 2, timer.text_y)
        numbers[number] = TextArt(text_sprite(rasteriser, palette, spec, [], [colours]))
    return TimerArt(timer, numbers)


def _plain_art(rasteriser: TextRasteriser, palette: Palette, line: CardLine) -> TextArt:
    """Return the art of a line of text without a wipe (a card line or a preview)."""
    colours = Colours(unsung=line.colour, sung=line.colour, edge=line.edge_colour)
    spec = TextSpec(line.text, line.size, line.edge, line.text_x, line.text_y)
    return TextArt(text_sprite(rasteriser, palette, spec, [], [colours]))


def arts_of(
    element: SceneElement,
    scene: Scene,
    palette: Palette,
    rasteriser: TextRasteriser,
    step: int = STEP,
    title: Palette | None = None,
) -> list[Art]:
    """Return the arts that draw ``element`` (a card is one art per line of text).

    ``step`` is the pixels a wipe, a bar or a countdown moves at a time; ``title`` is the palette
    of the start screen with pixel letters, which that card is drawn in.

    Raises:
        ValueError: If the element is the start screen with pixel letters and there is no
            ``title`` palette.
    """
    if isinstance(element, CardElement) and element.mark is not None and is_pixel_title(element):
        if title is None:
            raise ValueError("the start screen with pixel letters needs its palette")
        return _title_arts(element, element.mark, title, rasteriser)
    if isinstance(element, LineElement):
        bounds = [span.x1 for span in element.spans[:-1]]
        spec = TextSpec(element.text, element.size, element.edge, element.text_x, element.text_y)
        sprite = text_sprite(rasteriser, palette, spec, bounds, colours_per_span(element))
        return [TextArt(sprite, (element, scene.look), step)]
    if isinstance(element, ProgressElement | CountdownElement):
        return [_bar_art(element, palette, step)]
    return _text_arts(element, palette, rasteriser)


def _filled(top: int, left: int, picture: Indices) -> Art:
    """Return the art of a picture that stands still, placed at ``top`` and ``left``."""
    return TextArt(_crop(top, left, picture, picture))


def outline(height: int, width: int, radius: int) -> NDArray[np.bool_]:
    """Return a one-pixel outline of a rounded rectangle, ``height`` by ``width`` pixels."""

    def inside(rows: int, columns: int, corner: int) -> NDArray[np.bool_]:
        y, x = np.mgrid[0:rows, 0:columns] + 0.5
        dy, dx = y - np.clip(y, corner, rows - corner), x - np.clip(x, corner, columns - corner)
        return dy**2 + dx**2 <= corner**2

    inner = np.zeros((height, width), dtype=np.bool_)
    inner[1:-1, 1:-1] = inside(height - 2, width - 2, max(radius - 1, 0))
    return inside(height, width, radius) & ~inner


def _title_arts(
    card: CardElement, mark: TitleMark, palette: Palette, rasteriser: TextRasteriser
) -> list[Art]:
    """Return the arts of the start screen with pixel letters: wordmark, frame, rule, texts.

    The pixel letters are the cells of the word scaled by the mark's scale, banded by rows and
    edged by one pixel; the frame is a one-pixel rounded outline.
    """
    scale = round(mark.scale)
    word = with_edge(
        np.kron(np.array(pixel_word_cells(), dtype=np.uint8) * INK, np.ones((scale, scale))).astype(
            np.uint8
        ),
        1,
    )
    letters = np.full(word.shape, CLEAR, dtype=np.int16)
    letters[word == EDGE] = palette.flat(EDGE_COLOUR)
    rows = word.shape[0] - 2
    for row in range(rows):
        letters[row + 1][word[row + 1] == INK] = palette.flat(BAND_COLOURS[pixel_band(row, rows)])
    arts = [_filled(round(mark.word.y) - 1, round(mark.word.x) - 1, letters)]
    frame = np.full((round(mark.frame.h), round(mark.frame.w)), CLEAR, dtype=np.int16)
    ring = outline(frame.shape[0], frame.shape[1], round(mark.radius))
    frame[ring] = palette.flat(EDGE_COLOUR)
    arts.append(_filled(round(mark.frame.y), round(mark.frame.x), frame))
    if mark.rule is not None:
        rule = np.full((round(mark.rule.h), round(mark.rule.w)), palette.flat(BAND_COLOURS[1]))
        arts.append(_filled(round(mark.rule.y), round(mark.rule.x), rule.astype(np.int16)))
    return [*arts, *(_plain_art(rasteriser, palette, line) for line in card.lines)]


def _bar_art(element: ProgressElement | CountdownElement, palette: Palette, step: int) -> Art:
    """Return the art of a progress bar or a countdown."""
    if isinstance(element, ProgressElement):
        colours = (palette.flat(element.fill), palette.flat(element.frame), palette.background)
        return ProgressBar(element, colours, step)
    index = palette.flat(element.colour)
    return (
        ShrinkingBar(element, index, step)
        if element.form == "shrinking-bar"
        else Dots(element, index)
    )


def _text_arts(
    element: PreviewElement | CardElement | TimerElement,
    palette: Palette,
    rasteriser: TextRasteriser,
) -> list[Art]:
    """Return the arts of text without a wipe: a preview, a card (one per line) or a timer."""
    if isinstance(element, PreviewElement):
        return [_plain_art(rasteriser, palette, element.line)]
    if isinstance(element, CardElement):
        return [_plain_art(rasteriser, palette, line) for line in element.lines]
    return [_timer_art(rasteriser, palette, element)]


@dataclass(frozen=True)
class Deadline:
    """Pixels that must show the target frame of the tick before ``tick`` when ``tick`` begins.

    A line that appears only at ``tick`` has no frame before it, so its pixels are judged against
    the frame in which it is first shown: ``frame(max(tick - 1, shown))``.

    Attributes:
        tick: The tick (hundredth of a second) by which the pixels must be drawn.
        top: The first pixel row.
        bottom: One past the last pixel row.
        left: The first pixel column.
        right: One past the last pixel column.
        shown: The tick the line first appears (0: long before).
    """

    tick: int
    top: int
    bottom: int
    left: int
    right: int
    shown: int = 0


def first_tick_from(seconds: float) -> int:
    """Return the first tick whose time ``tick / 100`` is not before ``seconds``."""
    tick = max(math.ceil(seconds * TICKS_PER_SECOND) - 1, 0)  # one early: the product may round up
    while tick / TICKS_PER_SECOND < seconds:
        tick += 1
    return tick


class TargetFrames:
    """The frames the CD+G screen should show, tick by tick.

    Attributes:
        arts: Each element of the scene with the arts that draw it, in drawing order.
        ticks: The number of ticks (hundredths of a second) the scene lasts.
        deadlines: The pixels of every lyric line, which must be drawn when its first syllable
            starts.
        swap_tick: The first tick after the start screen with pixel letters, where the stream
            replaces its palette with the song's; ``None`` for a scene without one.
    """

    deadlines: list[Deadline]

    def __init__(
        self,
        scene: Scene,
        palette: Palette,
        rasteriser: TextRasteriser,
        step: int = STEP,
        title: Palette | None = None,
    ) -> None:
        """Draw every element of ``scene`` once; frames are put together on request.

        ``step`` is the pixels a wipe, a bar or a countdown moves at a time (``wipe_columns``);
        ``title`` is the palette of the start screen with pixel letters, if the scene has one.
        """
        self._palette = palette
        self.arts: list[tuple[SceneElement, Art]] = [
            (element, art)
            for element in scene.elements
            for art in arts_of(element, scene, palette, rasteriser, step, title)
        ]
        self.swap_tick: int | None = next(
            (first_tick_from(element.end) for element in scene.elements if is_pixel_title(element)),
            None,
        )
        self._starts = np.array([element.start for element, _ in self.arts])
        self._ends = np.array([element.end for element, _ in self.arts])
        self.ticks = math.ceil(scene.duration * TICKS_PER_SECOND) + 1
        self.deadlines = [
            Deadline(
                int(element.sing_start * TICKS_PER_SECOND),
                top,
                bottom,
                left,
                right,
                math.ceil(element.start * TICKS_PER_SECOND - SHOWN_SLACK),
            )  # fmt: skip
            for element, art in self.arts
            if isinstance(element, LineElement)
            for top, bottom, left, right in [art.box]
        ]
        self._key: tuple[tuple[int, int], ...] | None = None
        self._frame: Frame = self.blank()

    def blank(self) -> Frame:
        """Return a frame in the background colour."""
        return np.full((HEIGHT, WIDTH), self._palette.background, dtype=np.uint8)

    def _active(self, tick: int) -> list[int]:
        """Return the arts on screen at ``tick``, in drawing order."""
        time = tick / TICKS_PER_SECOND
        return [int(i) for i in np.nonzero((self._starts <= time) & (time < self._ends))[0]]

    def frame(self, tick: int) -> Frame:
        """Return the frame for the time ``tick / 100``; the same array while nothing changes.

        The array must not be changed by the caller.
        """
        time = tick / TICKS_PER_SECOND
        key = tuple((i, self.arts[i][1].state(time)) for i in self._active(tick))
        if key != self._key:
            frame = self.blank()
            for index, state in key:
                self.arts[index][1].paint(frame, state)
            self._key, self._frame = key, frame
        return self._frame

    def redrawn(self, tick: int) -> NDArray[np.bool_]:
        """Return the tiles (18 by 50) of the elements that appear or go at ``tick``."""
        before = set(self._active(tick - 1)) if tick > 0 else set()
        tiles = np.zeros((TILE_ROWS, TILE_COLUMNS), dtype=np.bool_)
        for index in before ^ set(self._active(tick)):
            top, bottom, left, right = self.arts[index][1].box
            if top < bottom and left < right:
                tiles[
                    top // TILE_HEIGHT : (bottom - 1) // TILE_HEIGHT + 1,
                    left // TILE_WIDTH : (right - 1) // TILE_WIDTH + 1,
                ] = True
        return tiles
