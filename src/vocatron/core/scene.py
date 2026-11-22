"""The scene model: what is on screen when, independent of any output format (ADR-0009).

The layout (``vocatron.core.layout``) builds a ``Scene``; the renderers only draw it. The tests
ask the model, never a frame: ``Scene.visible_at`` says what is visible at a time and
``LineElement.wipe_front`` where the colour sweep stands.

Times are seconds on the song timeline. Positions and sizes are pixels of the frame, from its top
left corner. Numbers are rounded to a thousandth so that stored scenes compare and snapshot well.
"""

import math
from typing import Annotated, Literal, override

from pydantic import BaseModel, ConfigDict, Field

from vocatron.core.lyrics.document import FIRST_VOICE, Voice

type Kind = Literal["line", "preview", "progress", "timer", "countdown", "title", "break", "end"]

MILLI = 1000
SECOND_SLACK = 1e-6  # seconds; a span of exactly n seconds counts n numbers whatever the floats


def rounded(value: float) -> float:
    """Round to a thousandth."""
    return round(value * MILLI) / MILLI


def whole_seconds(span: float) -> int:
    """Return how many whole seconds a span of ``span`` seconds counts, rounded up (at least 1)."""
    return max(1, math.ceil(span - SECOND_SLACK))


class Rect(BaseModel):
    """A rectangle: left, top, width, height."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        """The right edge."""
        return self.x + self.w

    @property
    def bottom(self) -> float:
        """The bottom edge."""
        return self.y + self.h

    def overlaps(self, other: Rect) -> bool:
        """Tell whether the two rectangles share area (touching edges do not count)."""
        return (
            self.x < other.right - 1e-6
            and other.x < self.right - 1e-6
            and self.y < other.bottom - 1e-6
            and other.y < self.bottom - 1e-6
        )

    def inside(self, outer: Rect) -> bool:
        """Tell whether this rectangle lies inside ``outer`` (with a thousandth of tolerance)."""
        tolerance = 1.5 / MILLI
        return (
            self.x >= outer.x - tolerance
            and self.y >= outer.y - tolerance
            and self.right <= outer.right + tolerance
            and self.bottom <= outer.bottom + tolerance
        )


class Look(BaseModel):
    """What every renderer needs besides the elements.

    Attributes:
        font: The font family name (the bundled font).
        wipe: ``smooth`` or ``syllable``.
        wipe_offset: Seconds the wipes are shifted.
        shadow_colour: Shadow colour as ``#rrggbb``.
        shadow_alpha: Shadow opacity.
        glow: Strength (0 to 1) of the glow of the sung text, 0 for none (ADR-0032).
        glow_colour: The colour of the glow, ``None`` for the sung colour of the line.
        pop_scale: How much larger the word being sung gets, 1 for no pop.
        pop_time: Seconds from the start of a word until it is back to its size.
        upcoming_dim: How much a line is dimmed before its first syllable, 0 for not at all.
        transition: ``none``, ``fade`` or ``slide``: how the lines come and go (``enter`` and
            ``exit`` of a line say how long).
        sung_dim: How much a line is dimmed once it has been sung, 0 for not at all; only in
            scroll mode, where sung lines stay in the column (ADR-0033).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    font: str
    wipe: Literal["smooth", "syllable"]
    wipe_offset: float
    shadow_colour: str
    shadow_alpha: float
    glow: float = 0.0
    glow_colour: str | None = None
    pop_scale: float = 1.0
    pop_time: float = 0.25
    upcoming_dim: float = 0.0
    transition: Literal["none", "fade", "slide"] = "none"
    sung_dim: float = 0.0


class BackgroundMotion(BaseModel):
    """A colour gradient that moves slowly, drawn instead of the plain background.

    Attributes:
        colours: Two to four colours as ``#rrggbb``.
        speed: How fast the gradient turns (ffmpeg's ``gradients`` speed).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    colours: list[str]
    speed: float


class Colours(BaseModel):
    """The three colours of a text: before the wipe, after it, and the outline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unsung: str
    sung: str
    edge: str


class Span(BaseModel):
    """One sung syllable on a line.

    Attributes:
        text: The syllable (with the space after a word, if it ends one).
        start: When it starts to be sung.
        end: When it ends.
        x0: Where its text starts, pixels from the left of the line's text.
        x1: Where its text ends.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    start: float
    end: float
    x0: float
    x1: float


class LineTurn(BaseModel):
    """A change of singers inside a line: from one syllable on, other colours.

    Attributes:
        span: The index of the first syllable (in ``LineElement.spans``) the new singers sing.
        singers: Who sings from there on: ``1``, ``1,3`` or ``all``.
        colours: Their colours (those of the lyrics file where it names one).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    span: int
    singers: str
    colours: Colours


class Element(BaseModel):
    """Something on screen for a while.

    Attributes:
        start: The first moment it is visible.
        end: The first moment it is gone.
        box: Everything it draws, with outline and shadow.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: float
    end: float
    box: Rect

    def visible(self, time: float) -> bool:
        """Tell whether the element is on screen at ``time``."""
        return self.start <= time < self.end


class Keyframe(BaseModel):
    """A point of the path of an element in scroll mode: at ``time`` it is at height ``y``.

    Between two keyframes the element moves in a straight line; two keyframes with the same ``y``
    are a stretch where it stands still, two with the same ``time`` a jump (ADR-0033).

    Attributes:
        time: Seconds on the song timeline.
        y: The anchor of the element (``Moving.anchor``) at that time, in pixels: the top of the
            line cell of a line and a timer, the top of the box of a break card and a bar.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    time: float
    y: float


class Moving(Element):
    """A lyric line that can glide with the column in scroll mode (ADR-0033).

    Attributes:
        path: In scroll mode where the element is over time: from ``start`` to ``end``, its
            anchor at each keyframe (``y_at``); empty in line and page mode, where it stays where
            it was built (ADR-0033).
    """

    path: list[Keyframe] = Field(default_factory=list)

    @property
    def anchor(self) -> float:
        """The height the keyframes of the path refer to: the top of the box, by default."""
        return self.box.y

    def y_at(self, time: float) -> float:
        """Return the anchor at ``time``: on its path in scroll mode, else where it was built.

        Before the first keyframe and after the last the element stands at that keyframe. At a jump
        (two keyframes at one time) it is the place after the jump.
        """
        if not self.path:
            return self.anchor
        if time < self.path[0].time:
            return self.path[0].y
        for before, after in zip(self.path, self.path[1:], strict=False):
            if time < after.time:
                share = (time - before.time) / (after.time - before.time)
                return before.y + (after.y - before.y) * share
        return self.path[-1].y

    def box_at(self, time: float) -> Rect:
        """Return the box at ``time``: ``box`` moved to where the path has it."""
        return self.box.model_copy(update={"y": self.box.y + self.offset_at(time)})

    def offset_at(self, time: float) -> float:
        """Return how far the path has moved the element from where it was built at ``time``."""
        return self.y_at(time) - self.anchor


class LineElement(Moving):
    """A lyric line in a slot.

    Attributes:
        text: The line as drawn.
        singers: Who sings its first syllable: ``1``, ``1,3`` or ``all``.
        voice: ``2`` for a line sung by the second voice at the same time as the first (ADR-0052),
            ``1`` otherwise. Two lines of different voices may be on screen and sung at once. A
            second-voice line without a singer mark of its own is drawn in the colours of singer
            2, whoever ``singers`` names (ADR-0054).
        slot: The slot it is in, counted from the top; 0 in scroll mode, which has no slots.
        page: The index of the page it belongs to in page mode, ``None`` in line mode.
        row: Which row of its lyric line this is: 0 for the first (or only) row, 1 for the
            second row of a line wrapped onto two rows. The rows share their times and either
            one slot or, with ``page.slot_per_row``, neighbouring slots.
        part: Which of the lines a lyric line too wide for its rows was split into this is: 0
            for the first (or a line that was not split), 1 for the next, and so on. In line mode
            the parts of a line take neighbouring slots, top to bottom, where the slots allow.
        enter: Seconds from ``start`` that the line takes to come in (``Look.transition``); it
            ends before the first syllable. 0 for none. The rows of one line share it.
        exit: Seconds before ``end`` that the line starts to go; it starts after the last
            syllable. 0 for none.
        size: Font size (ASS ``Fontsize``).
        edge: Outline width in pixels.
        shadow: Shadow offset in pixels.
        colours: Its colours (those of the singers of its first syllable, or of singer 2 for a
            second-voice line without a singer mark of its own).
        turns: Where the singers change inside the line, by rising ``span``; empty for a line
            sung by one voice or group.
        text_x: Where the text starts (the left of the first letter).
        text_y: The top of the line cell. In scroll mode it is where the line stands while it is
            sung, and ``box`` is the box there.
        spans: The syllables in the order they are sung.
    """

    kind: Literal["line"] = "line"
    text: str
    singers: str
    voice: Voice = FIRST_VOICE
    slot: int
    page: int | None = None
    row: int = 0
    part: int = 0
    enter: float = 0.0
    exit: float = 0.0
    size: float
    edge: float
    shadow: float
    colours: Colours
    turns: list[LineTurn] = Field(default_factory=list)
    text_x: float
    text_y: float
    spans: list[Span]

    @property
    @override
    def anchor(self) -> float:
        """The top of the line cell, which the keyframes of its path give."""
        return self.text_y

    @property
    def sing_start(self) -> float:
        """When the first syllable starts."""
        return self.spans[0].start

    @property
    def sing_end(self) -> float:
        """When the last syllable ends."""
        return self.spans[-1].end

    def wipe_front(self, time: float, look: Look) -> float:
        """Return where the colour sweep stands at ``time``, in pixels from the line's text.

        Before the first syllable it is 0, after the last one the width of the line. Within a
        syllable it is linear for ``smooth`` and jumps at the start for ``syllable``.
        """
        front = 0.0
        shift = look.wipe_offset
        for span in self.spans:
            start, end = span.start + shift, span.end + shift
            if time >= end:
                front = span.x1
            elif time >= start:
                if look.wipe == "syllable":
                    return span.x1
                share = (time - start) / (end - start) if end > start else 1.0
                return span.x0 + (span.x1 - span.x0) * share
            else:
                break
        return front


class CountdownElement(Element):
    """The countdown before a line, ending at ``tempo.countdown_end``.

    A countdown in beats ends one beat before the line starts, one in seconds when it starts
    (ADR-0028).

    Attributes:
        form: ``shrinking-bar``, ``dots`` or ``blocks``.
        count: The number of dots or blocks. In a countdown in beats it is the number of beats it
            lasts.
        colour: Its colour.
        beat: The length of one beat in seconds when the countdown counts beats of the song's
            tempo (it then lasts ``count`` beats); ``None`` when it runs over a fixed number of
            seconds (ADR-0022).
    """

    kind: Literal["countdown"] = "countdown"
    form: Literal["shrinking-bar", "dots", "blocks"]
    count: int
    colour: str
    beat: float | None = None


class CardLine(BaseModel):
    """One line of text on a card.

    Attributes:
        text: The text.
        size: Font size.
        edge: Outline width in pixels.
        shadow: Shadow offset in pixels.
        colour: Text colour.
        edge_colour: Outline colour.
        box: Where it is drawn.
        text_x: Where the text starts.
        text_y: The top of the line cell.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    size: float
    edge: float
    shadow: float
    colour: str
    edge_colour: str
    box: Rect
    text_x: float
    text_y: float


class TimeRange(BaseModel):
    """A stretch of time: from ``start`` to ``end``, seconds on the song timeline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: float
    end: float


class MarkFill(BaseModel):
    """One step of the build-up of the wordmark: letters that fill with their colour bands.

    Attributes:
        first: The index of the first letter of the step in the word.
        last: The index of the last letter of the step.
        when: When the bands sweep into those letters, from left to right.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    first: int
    last: int
    when: TimeRange


class BuildUp(BaseModel):
    """How the start screen with the wordmark builds up (ADR-0055).

    Attributes:
        edge: When the glowing edge of the letters fades in.
        fills: The steps in which the bands fill the letters, in order.
        wipe: When the frame and the texts wipe in from the left.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    edge: TimeRange
    fills: list[MarkFill]
    wipe: TimeRange


class TitleMark(BaseModel):
    """The wordmark, the frame and the field of a start screen (ADR-0055).

    Attributes:
        field: The colour of the field that covers the whole picture while the screen stands.
        word: The box of the wordmark.
        scale: Pixels per unit of the letter shapes (``vocatron.core.wordmark``).
        frame: The box of the rounded frame around the texts.
        radius: The radius of its corners in pixels.
        rule: The short rule between title and artist, ``None`` when there is none.
        build: The build-up, ``None`` for a screen that is finished from its first frame.
        pixel: The wordmark is made of pixel letters for the CD+G screen (ADR-0056): ``scale`` is
            then the pixels along a cell's side, and there is no build-up.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    word: Rect
    scale: float
    frame: Rect
    radius: float
    rule: Rect | None = None
    build: BuildUp | None = None
    pixel: bool = False


class CardElement(Element):
    """A screen of centred text: the title, a break screen or the end screen.

    All of them stand still; the break screen of a scroll look too (ADR-0040).

    Attributes:
        kind: ``title``, ``break`` or ``end``.
        lines: The lines, from the top.
        fade_out: Seconds the card fades out at its end.
        mark: The wordmark, frame and field of a start or end screen with the wordmark; ``None``
            for a plain card (ADR-0055, ADR-0057). Then ``box`` also holds the wordmark and the
            frame.
        symbol: The box of the V symbol above the notice of a break screen with
            the wordmark (ADR-0057); ``None`` for none. ``box`` holds it too.
    """

    kind: Literal["title", "break", "end"]
    lines: list[CardLine]
    fade_out: float = 0.0
    mark: TitleMark | None = None
    symbol: Rect | None = None


class PreviewElement(Element):
    """The next line, smaller and in its unsung colour, below the line being sung.

    It is on screen from the moment it is first shown until the line takes the main place.

    Attributes:
        of_line: The index in ``Scene.lines()`` of the line it previews.
        line: What it draws.
    """

    kind: Literal["preview"] = "preview"
    of_line: int
    line: CardLine


class ProgressElement(Element):
    """The progress bar of a break screen: it fills from the start to the end of the screen.

    Attributes:
        fill: The colour of the growing fill.
        frame: The colour of the frame around it.
    """

    kind: Literal["progress"] = "progress"
    fill: str
    frame: str


class TimerElement(Element):
    """The timer of a break screen: the whole seconds until the next lines appear.

    It is on screen as long as the break screen and shows ``ceil(end - t)`` at the time ``t``,
    centred in ``box``, which is as wide as the widest number it shows.

    Attributes:
        colour: The text colour.
        edge_colour: The outline colour.
        size: Font size.
        edge: Outline width in pixels.
        shadow: Shadow offset in pixels.
        text_y: The top of the line cell.
    """

    kind: Literal["timer"] = "timer"
    colour: str
    edge_colour: str
    size: float
    edge: float
    shadow: float
    text_y: float

    @property
    def total(self) -> int:
        """The number it shows when it appears: the whole seconds of its life, rounded up."""
        return whole_seconds(self.end - self.start)

    def seconds_left(self, time: float) -> int:
        """Return the number shown at ``time``: the seconds until it goes, rounded up."""
        return min(max(1, math.ceil(self.end - time - SECOND_SLACK)), self.total)

    def changes(self) -> list[float]:
        """Return the moments the number changes after the start, in order (one a second)."""
        return [rounded(self.end - left) for left in range(self.total - 1, 0, -1)]


type SceneElement = Annotated[
    LineElement | PreviewElement | ProgressElement | TimerElement | CountdownElement | CardElement,
    Field(discriminator="kind"),
]


class Shortfall(BaseModel):
    """Something the layout could not do as the profile asks.

    Attributes:
        kind: ``lead-in`` (a line is on screen for less than the minimum lead-in), ``title`` (the
            title screen is shorter than asked), ``too-wide`` (text wider than the safe area
            even at the smallest size), ``block`` (the slots, or in scroll mode the line being
            sung with its countdown, do not fit the safe area) or ``overlap`` (lines sung at once
            by two voices are shown one after the other in this look, ADR-0054).
        line: The index of the line in ``Scene.lines()``, or ``None``.
        message: A readable description.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["lead-in", "title", "too-wide", "block", "overlap"]
    line: int | None = None
    message: str


class ScrollView(BaseModel):
    """What the column of lyrics in scroll mode is measured from (ADR-0033).

    Attributes:
        current: The height of the middle of the line being sung, pixels from the top of the
            frame. A line wrapped onto two rows is centred on it.
        before: How many sung lines are kept above it at most.
        after: How many upcoming lines are shown below it at most.
        glide: The longest the column takes to move up to the next line, in seconds.
        min_glide: The shortest a glide between two lines takes, unless the column only came to
            rest shortly before (ADR-0036).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    current: float
    before: int
    after: int
    glide: float
    min_glide: float


class Scene(BaseModel):
    """Everything on screen for a song.

    Attributes:
        width: Frame width in pixels.
        height: Frame height in pixels.
        safe: The safe area: all text lies inside.
        background: The plain background colour.
        background_motion: A moving gradient drawn instead of it, ``None`` for the plain colour
            (ADR-0032).
        duration: The length of the video in seconds: the song and the silent intro.
        lead: The silence added before the song in seconds (0 for none, ADR-0020). Every time
            in the scene already includes it; the renderers shift the audio by it.
        bpm: The tempo whose beats the countdowns count (ADR-0022), ``None`` when the tempo is
            unclear and they run over a number of seconds.
        slots: The slot rectangles, from the top; none in scroll mode.
        scroll: The measures of the column in scroll mode, ``None`` in line and page mode.
        preview_row: The fixed row of the preview below the slots, ``None`` without a preview.
        look: Wipe, shadow and font.
        elements: Every element, ordered by start.
        shortfalls: What the layout could not do as the profile asks.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    width: int
    height: int
    safe: Rect
    background: str
    background_motion: BackgroundMotion | None = None
    duration: float
    lead: float = 0.0
    bpm: float | None = None
    slots: list[Rect]
    scroll: ScrollView | None = None
    preview_row: Rect | None = None
    look: Look
    elements: list[SceneElement]
    shortfalls: list[Shortfall] = Field(default_factory=list)

    def visible_at(self, time: float) -> list[SceneElement]:
        """Return the elements on screen at ``time``."""
        return [element for element in self.elements if element.visible(time)]

    def lines(self) -> list[LineElement]:
        """Return the lyric lines, in the order they are sung."""
        return [e for e in self.elements if isinstance(e, LineElement)]

    def cards(self, kind: Literal["title", "break", "end"]) -> list[CardElement]:
        """Return the screens of one kind (the title, the break screens or the end), in order."""
        return [e for e in self.elements if isinstance(e, CardElement) and e.kind == kind]
