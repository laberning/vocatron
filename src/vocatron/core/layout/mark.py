"""The start screen with the wordmark: wordmark, frame, texts and the build-up (ADR-0055).

The wordmark stands at the top, a rounded frame below it holds the song title, a short rule, the
artist and the singers' names. The lines are laid out by ``card`` inside the frame, so they
shrink to stay in it as they do on any card, but a title or artist too wide for the frame first
wraps onto two rows at a word (``fit.wrap_words``, the split of a sung line); the rows share one
size and stand closer together. The singers' names stand side by side, as many to a row as fit,
spread evenly over as few rows as give them the largest size once the card is laid out
(``_best``). The screen builds up in about two seconds when it lasts at least ``BUILD_MIN``
seconds; a shorter one is finished from its first frame.

On the CD+G screen the wordmark is made of pixel letters set in whole cells (``pixel``,
ADR-0056): the box is the word's cells times ``PIXEL_SCALE``, the frame is wider and taller, the
rule two pixels high, the texts have no outline, and there is no build-up (the screen is drawn as
fast as the format allows). The texts have sizes of their own in pixels (``PIXEL_TITLE_PX``,
``PIXEL_ARTIST_PX``, ``PIXEL_NAME_PX``); if one is still smaller than ``PIXEL_FLOOR_PX``, there is
no such screen: the plain card takes its place.

The end screen is the same screen without the build-up (``wordmark_end_card``, ADR-0057). The
break screen has the V symbol above its notice: ``symbol_space`` is the empty line that leaves
room for it in the card, ``with_symbol`` turns that line into the symbol's box.
"""

from dataclasses import dataclass, replace

from vocatron.core.layout.cards import LINE_PITCH, Canvas, CardText, card, union
from vocatron.core.layout.fit import wrap_words
from vocatron.core.scene import (
    BuildUp,
    CardElement,
    CardLine,
    MarkFill,
    Rect,
    TimeRange,
    TitleMark,
    rounded,
)
from vocatron.core.wordmark import (
    FIELD_COLOUR,
    LETTER_HEIGHT,
    PIXEL_ROWS,
    PIXEL_SCALE,
    SYLLABLES,
    pixel_word_columns,
    symbol,
    word_width,
)

BUILD_MIN = 4.0  # seconds a start screen lasts at least for the build-up to play
EDGE_IN = (0.0, 0.4)  # the edge of the letters fades in
FILL_STEPS = ((0.5, 0.8), (0.8, 1.1), (1.1, 1.5))  # the bands fill VO, then CA, then TRON
WIPE_IN = (1.5, 2.0)  # the frame and the texts wipe in from the left
MARK_WIDTH = 0.68  # of the safe width
MARK_MAX_HEIGHT = 0.2  # of the safe height
MARK_GAP = 0.06  # between wordmark and frame, of the safe height
FRAME_WIDTH = 0.82  # of the safe width
FRAME_HEIGHT = 0.5  # of the safe height
FRAME_INSET_X = 0.05  # between the frame and its texts, of the frame's width
FRAME_INSET_Y = 0.07  # of the frame's height
FRAME_RADIUS = 0.08  # of the frame's height
RULE_WIDTH = 0.085  # of the frame's width
RULE_HEIGHT = 0.011  # of the frame's height
RULE_SPACE = 0.5  # the height of the space the rule stands in, of the title's size
SCALE_DIGITS = 6  # the scale of the letters is a ratio: kept finer than a thousandth
TEXT_EDGE = "#000000"  # the outline of the texts on the dark frame
PIXEL_FRAME_WIDTH = 0.885  # on CD+G: of the safe width
PIXEL_FRAME_HEIGHT = 0.6  # of the safe height
PIXEL_RULE_HEIGHT = 2.0  # in pixels
PIXEL_TITLE_PX = 22.0  # the sizes of the CD+G start screen's texts, the same in every look
PIXEL_ARTIST_PX = 15.0
PIXEL_NAME_PX = 13.0
PIXEL_FLOOR_PX = 12.0  # no text of the CD+G start screen is smaller; the plain card takes over
SYMBOL_ROWS = 1.5  # the height of the break screen's V symbol, in rows of the notice
SYMBOL_GAP = 0.5  # the gap between the symbol and the notice, in rows of the notice
SIZE_SLACK = 1e-3  # a text rounded down by this much still counts as at the smallest size


def builds_up(seconds: float) -> bool:
    """Return whether a start screen of ``seconds`` builds up (at least ``BUILD_MIN``)."""
    return seconds >= BUILD_MIN


def build_up(end: float) -> BuildUp | None:
    """Return the build-up of a start screen lasting until ``end``, ``None`` when it is short."""
    if not builds_up(end):
        return None
    return BuildUp(
        edge=TimeRange(start=EDGE_IN[0], end=EDGE_IN[1]),
        fills=[
            MarkFill(first=first, last=last, when=TimeRange(start=start, end=stop))
            for (first, last), (start, stop) in zip(SYLLABLES, FILL_STEPS, strict=True)
        ],
        wipe=TimeRange(start=WIPE_IN[0], end=WIPE_IN[1]),
    )


def _frame(safe: Rect, mark_height: float, pixel: bool) -> Rect:
    """Return the frame: below the wordmark, ``FRAME_WIDTH`` wide and ``FRAME_HEIGHT`` high.

    The wordmark is at most ``MARK_MAX_HEIGHT`` high, so wordmark, gap and frame always fit.
    """
    gap = MARK_GAP * safe.h
    height = (PIXEL_FRAME_HEIGHT if pixel else FRAME_HEIGHT) * safe.h
    top = safe.y + (safe.h - (mark_height + gap + height)) / 2 + mark_height + gap
    width = (PIXEL_FRAME_WIDTH if pixel else FRAME_WIDTH) * safe.w
    return Rect(
        x=rounded(safe.x + (safe.w - width) / 2),
        y=rounded(top),
        w=rounded(width),
        h=rounded(height),
    )


def _word(safe: Rect, pixel: bool) -> tuple[float, float, float]:
    """Return the scale of the letters and the width and height of the wordmark.

    The scale is a ratio in grid units for the polygon letters and the pixels along a cell's side
    for the pixel letters.
    """
    if pixel:
        return (
            float(PIXEL_SCALE),
            float(PIXEL_SCALE * pixel_word_columns()),
            float(PIXEL_SCALE * PIXEL_ROWS),
        )
    scale = round(
        min(MARK_WIDTH * safe.w / word_width(), MARK_MAX_HEIGHT * safe.h / LETTER_HEIGHT),
        SCALE_DIGITS,
    )
    return scale, word_width() * scale, LETTER_HEIGHT * scale


def _wrapped(text: CardText, canvas: Canvas, room: float) -> list[CardText]:
    """Return a text that may wrap and is too wide for ``room`` as its two rows, else as it is."""
    size = canvas.size * text.scale
    wide = canvas.measurer.width(text.text, size) > room - 2 * canvas.profile.padding(size)
    halves = wrap_words(text.text, canvas.measurer, size) if text.wraps and wide else None
    if not halves:
        return [text]
    return [replace(text, text=halves[0]), replace(text, text=halves[1], tight=True)]


def _flowed(names: list[CardText], rows: int) -> list[CardText]:
    """Spread names evenly over ``rows`` rows, in order; the first rows take the extra ones.

    ``join`` makes a name stand beside the one before it, so five names on two rows stand three
    and two, four names two and two.
    """
    base, extra = divmod(len(names), rows)
    counts = [base + (row < extra) for row in range(rows)]
    starts = {sum(counts[:row]) for row in range(rows)}
    return [replace(name, join=index not in starts) for index, name in enumerate(names)]


def _arranged(lines: list[CardText], canvas: Canvas, rows: int) -> list[list[CardText]]:
    """Return every line as the texts it becomes: wrapped rows, or names flowed over ``rows``."""
    arranged: list[list[CardText]] = []
    index = 0
    while index < len(lines):
        if lines[index].flows:
            end = index
            while end < len(lines) and lines[end].flows:
                end += 1
            arranged += [[name] for name in _flowed(lines[index:end], rows)]
            index = end
        else:
            arranged.append(_wrapped(lines[index], canvas, canvas.safe.w))
            index += 1
    return arranged


@dataclass(frozen=True)
class _Laid:
    """The texts of the frame laid out with the names on a number of rows."""

    card: CardElement
    texts: list[CardText]  # what was laid out, the rule's spacer included
    rule_after: int | None  # the index of the laid line the rule stands under

    def smallest(self) -> tuple[float, float]:
        """Return the size of the smallest name and of the smallest text (spacer left out)."""
        sizes = [
            (line.size, text.flows)
            for line, text in zip(self.card.lines, self.texts, strict=True)
            if text.text
        ]
        names = [size for size, flows in sizes if flows]
        everything = min(size for size, _ in sizes)
        return min(names, default=everything), everything


def _lay(  # the texts, where they go, when, the rule and the names' rows
    lines: list[CardText],
    canvas: Canvas,
    end: float,
    rule_after: int | None,
    rule_edge: str,
    rows: int,
) -> _Laid:
    """Lay the texts out inside the frame (``canvas``) with the names on ``rows`` rows."""
    arranged = _arranged(lines, canvas, rows)
    texts = [text for group in arranged for text in group]
    if rule_after is not None:
        rule_index = sum(len(group) for group in arranged[: rule_after + 1])
        texts.insert(rule_index, CardText("", RULE_SPACE * lines[0].scale, rule_edge))
        rule_after = rule_index - 1
    return _Laid(card("title", texts, canvas, 0.0, end), texts, rule_after)


def _best(
    lines: list[CardText], canvas: Canvas, end: float, rule_after: int | None, rule_edge: str
) -> _Laid:
    """Lay the texts out with the names on the number of rows that leaves them largest.

    Every row count is tried, as the card lays them out (shrunk to the width and to the height);
    the largest names win, then the largest smallest text, then the fewest rows (so names that
    fit stand in one row, four long names two and two, and one name to a row only when that is
    larger).
    """
    names = sum(line.flows for line in lines)
    options = [
        _lay(lines, canvas, end, rule_after, rule_edge, rows)
        for rows in range(1, max(names, 1) + 1)
    ]
    best = max(range(len(options)), key=lambda index: (*options[index].smallest(), -index))
    return options[best]


def wordmark_card(
    lines: list[CardText],
    canvas: Canvas,
    end: float,
    rule_after: int | None,
    pixel: bool,
    min_px: float | None = None,
) -> CardElement | None:
    """Build the start screen with the wordmark, from time 0 to ``end``.

    Args:
        lines: The text lines from the top: title, artist, singers (the colours are the lines').
        canvas: Measurer, profile, safe area and base size.
        end: When the screen goes.
        rule_after: The index of the line the short rule stands under, ``None`` for no rule.
        pixel: Pixel letters for the CD+G screen, without a build-up (ADR-0056).
        min_px: On CD+G ``PIXEL_FLOOR_PX``: no text is to be smaller than this many pixels.

    Returns:
        The card, or ``None`` when a text would be smaller than ``min_px`` (the caller then
        builds the plain card).
    """
    marked, smallest = _marked(lines, canvas, end, rule_after, pixel)
    if min_px is not None and smallest < min_px - SIZE_SLACK:
        return None
    return marked


def wordmark_end_card(  # the texts, the canvas, the span, the fade and the rule
    lines: list[CardText],
    canvas: Canvas,
    span: tuple[float, float],
    fade_out: float,
    rule_after: int | None,
) -> CardElement:
    """Build the end screen with the wordmark: the start screen without the build-up (ADR-0057).

    Args:
        lines: The text lines from the top, as the start screen's.
        canvas: Measurer, profile, safe area and base size.
        span: When the screen starts and goes.
        fade_out: Seconds it fades out at its end, field, letters and frame with it.
        rule_after: The index of the line the short rule stands under, ``None`` for no rule.
    """
    start, end = span
    laid, _ = _marked(lines, canvas, end, rule_after, False)
    assert laid.mark is not None  # _marked always makes one
    mark = laid.mark.model_copy(update={"build": None})
    return laid.model_copy(
        update={
            "kind": "end",
            "start": rounded(start),
            "fade_out": fade_out,
            "mark": mark,
        }
    )


def symbol_space(scale: float) -> CardText:
    """Return the empty first line of a break screen that leaves room for the V symbol.

    Args:
        scale: The notice's share of the base size; the line is as high as the symbol and the gap
            under it, in rows of the notice.
    """
    return CardText("", (SYMBOL_ROWS + SYMBOL_GAP) * scale, FIELD_COLOUR)


def with_symbol(screen: CardElement) -> CardElement:
    """Turn the empty first line of a break screen into the box of the V symbol.

    The symbol is ``SYMBOL_ROWS`` rows high, stands at the top of that line, centred, and the
    gap of ``SYMBOL_GAP`` rows below it is left free; the card's box grows to hold it.

    Args:
        screen: A break screen whose first line is ``symbol_space``.
    """
    space, *text = screen.lines
    cell = space.size * LINE_PITCH
    height = cell * SYMBOL_ROWS / (SYMBOL_ROWS + SYMBOL_GAP)
    width = symbol().width * height / LETTER_HEIGHT
    box = Rect(
        x=rounded(space.box.x + space.box.w / 2 - width / 2),
        y=rounded(space.box.y + space.box.h / 2 - cell / 2),
        w=rounded(width),
        h=rounded(height),
    )
    return screen.model_copy(
        update={"lines": text, "symbol": box, "box": union([*(x.box for x in text), box])}
    )


def _marked(
    lines: list[CardText], canvas: Canvas, end: float, rule_after: int | None, pixel: bool
) -> tuple[CardElement, float]:
    """Build a screen with the wordmark and return it with the size of its smallest text."""
    safe = canvas.safe
    scale, mark_w, mark_h = _word(safe, pixel)
    frame = _frame(safe, mark_h, pixel)
    word = Rect(
        x=rounded(safe.x + (safe.w - mark_w) / 2),
        y=rounded(frame.y - MARK_GAP * safe.h - mark_h),
        w=rounded(mark_w),
        h=rounded(mark_h),
    )
    text_edge = FIELD_COLOUR if pixel else TEXT_EDGE
    inset_x, inset_y = FRAME_INSET_X * frame.w, FRAME_INSET_Y * frame.h
    inner = Rect(
        x=rounded(frame.x + inset_x),
        y=rounded(frame.y + inset_y),
        w=rounded(frame.w - 2 * inset_x),
        h=rounded(frame.h - 2 * inset_y),
    )
    inner_canvas = Canvas(canvas.measurer, canvas.profile, inner, canvas.size)
    best = _best(lines, inner_canvas, end, rule_after, text_edge)
    laid, rule_after = best.card, best.rule_after
    shown: list[CardLine] = []
    rule: Rect | None = None
    for index, line in enumerate(laid.lines):
        if rule_after is not None and index == rule_after + 1:  # the space the rule stands in
            width = RULE_WIDTH * frame.w
            height = PIXEL_RULE_HEIGHT if pixel else max(RULE_HEIGHT * frame.h, 1.0)
            middle = line.box.y + line.box.h / 2
            rule = Rect(
                x=rounded(frame.x + (frame.w - width) / 2),
                y=rounded(middle - height / 2),
                w=rounded(width),
                h=rounded(height),
            )
            continue
        shown.append(line.model_copy(update={"edge_colour": text_edge}))
    mark = TitleMark(
        field=FIELD_COLOUR,
        word=word,
        scale=scale,
        frame=frame,
        radius=rounded(FRAME_RADIUS * frame.h),
        rule=rule,
        build=None if pixel else build_up(end),
        pixel=pixel,
    )
    marked = laid.model_copy(update={"lines": shown, "box": union([word, frame]), "mark": mark})
    return marked, best.smallest()[1]
