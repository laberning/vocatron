"""Cards, the countdown and the timer: title, break and end screens (rules 12 to 15)."""

from dataclasses import dataclass

from vocatron.core.layout.fit import SHRINK_MARGIN
from vocatron.core.measure import TextMeasurer
from vocatron.core.profiles.model import Countdown, Profile
from vocatron.core.scene import (
    CardElement,
    CardLine,
    CountdownElement,
    ProgressElement,
    Rect,
    Shortfall,
    TimerElement,
    rounded,
)
from vocatron.core.tempo import countdown_beat, countdown_end

LINE_PITCH = 1.25  # a card's lines are this many font sizes apart
COUNTDOWN_HEIGHT = 0.3  # of the font size
ROW_GAP = 0.1  # between slots, and between the rows of a slot, of the font size
COUNTDOWN_GAP = 0.1  # between the countdown band and the slots, of the font size
DOT_SPACING = 1.6  # of a dot's diameter
PROGRESS_WIDTH = 0.6  # of the safe width
PROGRESS_HEIGHT = 0.15  # of the font size
PROGRESS_GAP = 0.4  # between the text of a break screen and its progress bar, of the font size
TIMER_SCALE = 0.8  # of the size of the notice above the timer
BEAT_SLACK = 1e-6  # of a beat: a countdown that fits except for rounding still fits
ROW_PITCH = 1.1  # the rows of one wrapped text are this many font sizes apart
JOIN_GAP = 0.8  # the space between texts side by side, of the font size
SMALLEST_CARD_SIZE = 4.0  # pixels; a card line that is still wider is shrunk no further


@dataclass(frozen=True)
class CardText:
    """One piece of text on a card: what, how large (a share of the base size) and in what colour.

    ``wraps`` lets the start screen with the wordmark wrap the text onto two rows at a word
    before it shrinks (ADR-0056); ``card`` itself never wraps. ``join`` puts the text on the row
    of the one before it (the singers' names side by side, each in its colour), ``tight`` makes
    it a further row of the text before it: the rows of one text stand closer together than
    separate texts and share one size. ``flows`` lets the start screen put the texts that follow
    each other like this (the singers' names) side by side, as many to a row as fit.
    """

    text: str
    scale: float
    colour: str
    wraps: bool = False
    join: bool = False
    tight: bool = False
    flows: bool = False


@dataclass
class _Row:
    """The texts that stand on one row of a card, with their sizes and widths at that moment."""

    texts: list[CardText]
    tight: bool
    sizes: list[float]
    widths: list[float]

    @property
    def size(self) -> float:
        """The size the row's height is counted in: its largest text."""
        return max(self.sizes)

    @property
    def gap(self) -> float:
        """The space between two texts side by side."""
        return JOIN_GAP * self.size

    def total(self) -> float:
        """The width of all the texts and the spaces between them."""
        return sum(self.widths) + self.gap * (len(self.widths) - 1)


@dataclass(frozen=True)
class Canvas:
    """What a card is drawn on and with: the measurer, the profile, the safe area, the font size.

    A card is centred in the safe area.
    """

    measurer: TextMeasurer
    profile: Profile
    safe: Rect
    size: float


def title_window(first_start: float, profile: Profile) -> tuple[float, float, list[Shortfall]]:
    """Return when the title screen ends and the first line appears (rule 14).

    The first line appears ``lead_in.target`` before it is sung and the title ends then, if that
    leaves the title its minimum time. Otherwise the title is shortened, down to ``min_short``;
    the first line then appears later than the target but not later than ``lead_in.min`` before
    it is sung.

    Returns:
        The end of the title screen (0 for none), the time the first line appears, and what
        could not be done.
    """
    title, lead = profile.title, profile.lead_in
    shows = first_start - lead.target
    if not title.fields:
        return 0.0, max(shows, 0.0), []
    ends = shows
    if ends < title.min_short:
        ends = max(shows, min(title.min_short, first_start - lead.min))
    ends = max(ends, 0.0)
    if ends >= title.min_short:
        return ends, ends, []
    text = f"the title is on screen {ends:.2f} s (minimum {title.min_short} s)"
    return ends, ends, [Shortfall(kind="title", message=text)]


def card(  # a card is a kind, a time span and its lines; grouping adds nothing
    kind: str,
    lines: list[CardText],
    canvas: Canvas,
    start: float,
    end: float,
    fade_out: float = 0.0,
) -> CardElement:
    """Build a card: centred lines in the safe area, each shrunk until it fits.

    A line too wide is shrunk on its own, the rows of one text (``tight``) and the texts of one row
    (``join``) together; rows too many for the height (a title naming many singers) are all shrunk
    by the same share.

    Args:
        kind: ``title``, ``break`` or ``end``.
        lines: The text lines from the top.
        canvas: Measurer, profile, safe area and base size.
        start: When the card appears.
        end: When it goes.
        fade_out: Seconds it fades out at its end.
    """
    measurer, profile, safe = canvas.measurer, canvas.profile, canvas.safe
    rows = _rows(lines, canvas)
    _shrink_to_width(rows, canvas)
    if (height := _stack_height(rows, profile)) > safe.h:  # too many rows: shrink them all alike
        for row in rows:
            _resize(row, safe.h / height * SHRINK_MARGIN, measurer)
    tops, total = _tops(rows)
    top = safe.y + (safe.h - total) / 2
    placed: list[CardLine] = []
    for row, row_top in zip(rows, tops, strict=True):
        pitch = row.size * LINE_PITCH
        left = safe.x + (safe.w - row.total()) / 2
        for line, size, width in zip(row.texts, row.sizes, row.widths, strict=True):
            pad = profile.padding(size)
            box = Rect(
                x=rounded(left - pad),
                y=rounded(top + row_top + (pitch - size) / 2 - pad),
                w=rounded(width + 2 * pad),
                h=rounded(size + 2 * pad),
            )
            left += width + row.gap
            placed.append(
                CardLine(
                    text=line.text,
                    size=rounded(size),
                    edge=rounded(profile.edge.width * size),
                    shadow=rounded(profile.shadow.offset * size),
                    colour=line.colour,
                    edge_colour=profile.colours.group.edge,
                    box=box,
                    text_x=rounded(box.x + pad),
                    text_y=rounded(box.y + pad),
                )
            )
    return CardElement.model_validate(
        {
            "kind": kind,
            "start": rounded(start),
            "end": rounded(end),
            "box": union([line.box for line in placed]),
            "lines": placed,
            "fade_out": fade_out,
        }
    )


def _rows(lines: list[CardText], canvas: Canvas) -> list[_Row]:
    """Group the texts into rows (``join``) and measure them at their wanted sizes."""
    rows: list[_Row] = []
    for line in lines:
        size = canvas.size * line.scale
        width = canvas.measurer.width(line.text, size)
        if line.join and rows:
            row = rows[-1]
            row.texts.append(line)
            row.sizes.append(size)
            row.widths.append(width)
        else:
            rows.append(_Row([line], line.tight, [size], [width]))
    return rows


def _shrink_to_width(rows: list[_Row], canvas: Canvas) -> None:
    """Shrink every text too wide for the safe area; the rows of one text shrink together."""
    blocks: list[list[_Row]] = []
    for row in rows:
        if row.tight and blocks:
            blocks[-1].append(row)
        else:
            blocks.append([row])
    for block in blocks:
        factor = min(_fit_factor(row, canvas.profile, canvas.safe.w) for row in block)
        if factor < 1:
            for row in block:
                _resize(row, factor, canvas.measurer)


def _fit_factor(row: _Row, profile: Profile, limit: float) -> float:
    """Return the share a row is to shrink by to fit in ``limit`` with its padding (1: it fits)."""
    pad = profile.padding(row.size)
    width = row.total()
    if width + 2 * pad <= limit:
        return 1.0
    return (limit - 2 * pad) / width * SHRINK_MARGIN


def _resize(row: _Row, factor: float, measurer: TextMeasurer) -> None:
    """Shrink every text of ``row`` by ``factor`` (not below ``SMALLEST_CARD_SIZE``)."""
    row.sizes = [max(size * factor, SMALLEST_CARD_SIZE) for size in row.sizes]
    row.widths = [
        measurer.width(text.text, size) for text, size in zip(row.texts, row.sizes, strict=True)
    ]


def _tops(rows: list[_Row]) -> tuple[list[float], float]:
    """Return the top of every row's cell from the first one's, and the height of them all.

    The cells are ``LINE_PITCH`` font sizes high and stand one under the other; a row that is
    ``tight`` stands ``ROW_PITCH`` font sizes under the row before it instead.
    """
    tops: list[float] = []
    for index, row in enumerate(rows):
        if index == 0:
            tops.append(0.0)
        elif row.tight:
            tops.append(tops[-1] + rows[index - 1].size * ROW_PITCH)
        else:
            tops.append(tops[-1] + rows[index - 1].size * LINE_PITCH)
    return tops, tops[-1] + rows[-1].size * LINE_PITCH


def _stack_height(rows: list[_Row], profile: Profile) -> float:
    """Return the height the boxes of a card's rows take when they are centred.

    The rows are ``LINE_PITCH`` font sizes apart and centred as a block, so the boxes fit when
    the block plus what the first or the last box reaches beyond it (less, when it stays inside
    its pitch), on both sides, fits.
    """
    total = _tops(rows)[1]
    beyond = max(
        profile.padding(row.size) - (row.size * LINE_PITCH - row.size) / 2
        for row in (rows[0], rows[-1])
    )
    return total + 2 * beyond


def union(boxes: list[Rect]) -> Rect:
    """Return the smallest rectangle around ``boxes``."""
    left = min(box.x for box in boxes)
    top = min(box.y for box in boxes)
    return Rect(
        x=left,
        y=top,
        w=rounded(max(box.right for box in boxes) - left),
        h=rounded(max(box.bottom for box in boxes) - top),
    )


def progress_element(  # a box, a span and the font size place it
    profile: Profile, safe: Rect, text: Rect, size: float, start: float, end: float
) -> ProgressElement:
    """Build the progress bar of a break screen: centred under the text of the screen.

    Args:
        profile: The profile (the group's colours are the bar's).
        safe: The safe area, which the bar stays inside.
        text: The box around the text of the break screen.
        size: The base font size.
        start: When the break screen appears; the bar is empty.
        end: When it goes; the bar is full.
    """
    width = PROGRESS_WIDTH * safe.w
    box = Rect(
        x=rounded(safe.x + (safe.w - width) / 2),
        y=rounded(text.bottom + PROGRESS_GAP * size),
        w=rounded(width),
        h=rounded(PROGRESS_HEIGHT * size),
    )
    group = profile.colours.group
    return ProgressElement(
        start=rounded(start), end=rounded(end), box=box, fill=group.sung, frame=group.unsung
    )


@dataclass(frozen=True)
class CountdownWindow:
    """When a countdown runs and what it counts.

    Attributes:
        start: When it starts.
        end: When it ends (when the line starts to be sung).
        count: The number of dots or blocks (and, with a ``beat``, of beats).
        beat: The length of one beat in seconds, or ``None`` for a countdown in seconds.
    """

    start: float
    end: float
    count: int
    beat: float | None = None


def countdown_window(
    setting: Countdown, bpm: float | None, sing_start: float, floor: float
) -> CountdownWindow | None:
    """Return when the countdown before a line starts, or ``None`` when there is no room for one.

    With a tempo the countdown lasts ``setting.count`` beats and ends one beat before
    ``sing_start``, so the singing starts on the next beat (``countdown_end``). Where ``floor``
    (the end of the line before or of a title or break screen) leaves less room, it starts on the
    first whole beat after the floor and counts the beats that are left. Without a tempo it runs
    over ``setting.duration`` seconds up to ``sing_start``, cut at the floor (ADR-0022, ADR-0026,
    ADR-0028).

    Args:
        setting: The profile's countdown settings.
        bpm: The tempo of the song, or ``None`` when it is unclear.
        sing_start: When the line starts to be sung.
        floor: The earliest the countdown may start: the end of the line before, or of the title
            or break screen when that is later.
    """
    if bpm is None:
        start = max(sing_start - setting.duration, floor)
        return CountdownWindow(start, sing_start, setting.count) if start < sing_start else None
    beat = countdown_beat(bpm, setting.count)
    end = countdown_end(sing_start, beat)
    whole = int((end - floor) / beat + BEAT_SLACK)
    count = min(setting.count, whole)
    if count < 1:
        return None
    return CountdownWindow(end - count * beat, end, count, beat)


def countdown_element(
    profile: Profile, safe: Rect, band: Rect, text_x: float, window: CountdownWindow
) -> CountdownElement:
    """Build the countdown above the slots, its left edge over the first letter of the line.

    Args:
        profile: The profile (its countdown form and the colour of the group).
        safe: The safe area, which the countdown stays inside.
        band: The band above the slots that is kept free for it.
        text_x: Where the first letter of the line starts.
        window: When it runs and how many dots, blocks or beats it counts.
    """
    form = profile.countdown.form
    width = band.h * (window.count * DOT_SPACING if form != "shrinking-bar" else 6)
    left = min(max(text_x, safe.x), safe.right - width)
    return CountdownElement(
        start=rounded(window.start),
        end=rounded(window.end),
        box=Rect(x=rounded(left), y=band.y, w=rounded(width), h=band.h),
        form=form,
        count=window.count,
        colour=profile.colours.group.sung,
        beat=None if window.beat is None else rounded(window.beat),
    )


def slot_rows(profile: Profile) -> int:
    """Return how many rows a slot holds: ``line_rows``, or one with ``page.slot_per_row``."""
    return 1 if profile.page.slot_per_row else profile.line_rows


def timer_text(measurer: TextMeasurer, seconds: int, size: float) -> str:
    """Return the widest number a timer counting down from ``seconds`` shows, at ``size``.

    The timer's box is as wide as this number, so the box never changes while it counts.
    """
    return max(
        (str(number) for number in range(1, seconds + 1)), key=lambda n: measurer.width(n, size)
    )


def split_timer(screen: CardElement) -> tuple[CardElement, TimerElement]:
    """Take the last line of a break screen out as its timer.

    The timer is laid out with the lines of the card, so the block of text and timer is centred,
    the timer is centred under the text and everything stays inside the safe area; the card keeps
    the lines above it.

    Args:
        screen: A break screen whose last line is the widest number of the timer.

    Returns:
        The screen without that line, and the timer with the same span.
    """
    *text, last = screen.lines
    timer = TimerElement(
        start=screen.start,
        end=screen.end,
        box=last.box,
        colour=last.colour,
        edge_colour=last.edge_colour,
        size=last.size,
        edge=last.edge,
        shadow=last.shadow,
        text_y=last.text_y,
    )
    return screen.model_copy(update={"lines": text, "box": union([x.box for x in text])}), timer


def slot_rects(
    profile: Profile, safe: Rect, size: float, pad: float
) -> tuple[list[Rect], Rect, Rect | None]:
    """Return the slot rectangles from the top, the band above them for the countdown, and the row.

    The block of slots sits where ``profile.position`` says, moved so that the countdown band
    above it and the block both lie inside the safe area. With a preview the block is one slot, a
    gap and the preview row below it, which is returned too (``None`` without a preview). A slot
    is as high as ``slot_rows`` rows of text and the gaps between them.
    """
    gap = ROW_GAP * size
    rows = slot_rows(profile)
    height = rows * (size + 2 * pad) + (rows - 1) * gap
    count = profile.slots
    block = count * height + (count - 1) * gap
    row_h = 0.0
    if profile.preview.show:
        small = profile.preview.scale * size
        row_h = small + 2 * profile.padding(small)
        block += gap + row_h
    band_h = COUNTDOWN_HEIGHT * size
    band_room = band_h + COUNTDOWN_GAP * size
    centre = {"top": 0.22, "middle": 0.5, "lower-third": 0.75, "bottom": 0.88}[profile.position]
    top = safe.y + centre * safe.h - block / 2
    top = max(min(top, safe.bottom - block), safe.y + band_room)
    slots = [
        Rect(x=safe.x, y=rounded(top + index * (height + gap)), w=safe.w, h=rounded(height))
        for index in range(count)
    ]
    band = Rect(x=safe.x, y=rounded(top - band_room), w=safe.w, h=rounded(band_h))
    row = None
    if profile.preview.show:
        below = top + count * height + (count - 1) * gap + gap
        row = Rect(x=safe.x, y=rounded(below), w=safe.w, h=rounded(row_h))
    return slots, band, row


def row_rects(slot: Rect, count: int, size: float) -> list[Rect]:
    """Return the rows of a slot that holds a line wrapped onto ``count`` rows, from the top.

    A line of one row sits in the middle of the slot, so ``slot`` itself is its region.

    Args:
        slot: The slot, as high as the most rows a line may have.
        count: How many rows the line has.
        size: The base font size, which the gap between the rows is a share of.
    """
    if count == 1:
        return [slot]
    gap = ROW_GAP * size
    height = (slot.h - (count - 1) * gap) / count
    return [
        Rect(x=slot.x, y=rounded(slot.y + index * (height + gap)), w=slot.w, h=rounded(height))
        for index in range(count)
    ]


def fits_safe_area(rects: list[Rect], band: Rect, scene_safe: Rect) -> bool:
    """Tell whether the band and every slot (and the preview row) lie inside the safe area."""
    return all(rect.inside(scene_safe) for rect in (band, *rects))
