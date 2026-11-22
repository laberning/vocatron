r"""The screens with the wordmark as ASS events (ADR-0055, ADR-0057).

The wordmark is drawn from the polygons of ``vocatron.core.wordmark`` as vector drawings (``\p1``).
Libass draws the outline of a drawing outside it, so a letter is, from the bottom up: a blurred
cyan ring (the glow), a sharp cyan ring, the seven colour bands (the letters clipped to one band
each by ``\clip``), and a thin light ring on top. The build-up moves clip rectangles with ``\t``:
the bands sweep into the letters of VO, CA and TRON one after the other, and the frame, the rule
and the texts wipe in from the left; the edge fades in with ``\fad``. Without a build-up every
event stands from the start of the screen. The renderer cannot trace an outline stroke by stroke
or fade a shape along a gradient, so the edge only fades in and there is no reflection.

The end screen is the same without a build-up; its field, letters and frame fade out together
(``\fad``). The V symbol of a break screen is a finished letter of the same drawing (glow, edge,
bands, light edge), without a field and without a build-up (``symbol_events``).
"""

from collections.abc import Callable, Sequence

from vocatron.core.ass.tags import (
    CIRCLE,
    dialogue,
    number,
    rectangle,
    solid,
    style_name,
)
from vocatron.core.ass.tags import fade as fade_tag
from vocatron.core.colour import ass_colour
from vocatron.core.scene import CardElement, Colours, Rect, Scene, TimeRange, TitleMark
from vocatron.core.wordmark import (
    AMBER,
    BAND_COLOURS,
    EDGE_COLOUR,
    EDGE_LIGHT,
    EDGE_WIDTH,
    FRAME_FILL,
    LETTER_HEIGHT,
    LIGHT_WIDTH,
    Letter,
    bands,
    letters,
    symbol,
)

GLOW_BORDER = 0.75  # the width of the blurred ring, of the edge width of the letters
GLOW_BLUR = 0.5  # the blur of the glow, of the edge width
LIGHT_SHARE = 0.6  # the drawn light edge, of its width in the logo files
FRAME_LINE = 0.012  # the line of the frame, of its height
FRAME_GLOW_BORDER = 1.5  # the ring of the frame's glow, of the frame's line
FRAME_GLOW_BLUR = 2.0  # the blur of the frame's glow, of the frame's line
MIN_LINE = 1.0  # pixels; no line is drawn thinner
FRAME_REACH = 3.0  # the glow of the frame reaches this many line widths beyond it
LAYER_FIELD = 0
LAYER_GLOW = 1
LAYER_EDGE = 2
LAYER_BANDS = 3
LAYER_LIGHT = 4
LAYER_FRAME = 5
LAYER_TEXT = 6
"""The layers of the screen, from the field up; the texts are on the top one."""
ALPHA_CLEAR = "&HFF&"


def mark_styles(card: CardElement) -> list[Colours]:
    """Return the colour sets the events of a card with a mark or a symbol need a style for."""
    if card.symbol is not None:
        return [solid(colour) for colour in dict.fromkeys([EDGE_COLOUR, EDGE_LIGHT, *BAND_COLOURS])]
    mark = card.mark
    if mark is None:
        return []
    colours = [mark.field, EDGE_COLOUR, EDGE_LIGHT, FRAME_FILL, AMBER, *BAND_COLOURS]
    return [solid(colour) for colour in dict.fromkeys(colours)]


def _contours(shapes: Sequence[Letter], scale: float) -> tuple[str, float, float]:
    """Return the drawing of letters (moved to start at its own corner) and that corner in the word.

    The commands are in pixels from the top left of the letters' bounding box; the corner, in
    pixels from the top left of the word, is where the drawing has to be placed. The drawing then
    starts at (0, 0), however libass aligns it.
    """
    points = [point for letter in shapes for contour in letter.contours for point in contour]
    left, top = min(x for x, _ in points), min(y for _, y in points)
    parts = []
    for letter in shapes:
        for contour in letter.contours:
            moved = [
                f"{number((x - left) * scale)} {number((y - top) * scale)}" for x, y in contour
            ]
            parts.append(f"m {moved[0]} l {' '.join(moved[1:])}")
    return " ".join(parts), left * scale, top * scale


def _rounded(width: float, height: float, radius: float) -> str:
    """Write a rectangle with rounded corners, from the origin, as drawing commands."""
    n, r = number, radius
    c = r * CIRCLE
    w, h = width, height
    return (
        f"m {n(r)} 0 l {n(w - r)} 0 b {n(w - r + c)} 0 {n(w)} {n(r - c)} {n(w)} {n(r)} "
        f"l {n(w)} {n(h - r)} b {n(w)} {n(h - r + c)} {n(w - r + c)} {n(h)} {n(w - r)} {n(h)} "
        f"l {n(r)} {n(h)} b {n(r - c)} {n(h)} 0 {n(h - r + c)} 0 {n(h - r)} "
        f"l 0 {n(r)} b 0 {n(r - c)} {n(r - c)} 0 {n(r)} 0"
    )


def _clip(box: Rect, reach: float, share: float = 1.0) -> str:
    r"""Write a ``\clip`` over ``box`` and ``reach`` around it, from its left to ``share`` of it."""
    left, top = box.x - reach, box.y - reach
    right = left + (box.w + 2 * reach) * share
    return f"\\clip({number(left)},{number(top)},{number(right)},{number(box.bottom + reach)})"


def _swept(box: Rect, reach: float, when: TimeRange) -> str:
    r"""Write the tags that open a clip over ``box`` from the left during ``when``.

    The event that holds them starts at ``when.start``, where the transform starts.
    """
    millis = round((when.end - when.start) * 1000)
    return f"{_clip(box, reach, 0.0)}\\t(0,{millis},{_clip(box, reach)})"


def _shape(  # the drawing, where it stands, what it is made of and for how long
    drawing: str,
    place: tuple[float, float],
    colour: str,
    tags: str,
    span: tuple[float, float],
    layer: int,
) -> str:
    r"""Write the event of a drawing at ``place`` in ``colour``; ``tags`` add to its tags."""
    where = f"\\pos({number(place[0])},{number(place[1])})"
    head = f"\\an7{where}\\shad0\\p1\\1c{ass_colour(colour)}{tags}"
    return dialogue(span[0], span[1], style_name(solid(colour)), f"{{{head}}}{drawing}", layer)


def _ring(width: float, colour: str, blur: float = 0.0) -> str:
    r"""Write the tags of a ring around a drawing: a clear fill and an outline of ``width``."""
    soft = f"\\blur{number(blur)}" if blur else ""
    return f"\\1a{ALPHA_CLEAR}\\bord{number(width)}\\3c{ass_colour(colour)}{soft}"


def _edge_events(  # the drawing, where, how thick, when and the extra tags
    drawing: str,
    place: tuple[float, float],
    scale: float,
    span: tuple[float, float],
    tags: str,
) -> list[str]:
    """Write the glow and the sharp cyan ring of letters, the bottom layers of the edge."""
    edge = EDGE_WIDTH * scale
    return [
        _shape(
            drawing, place, EDGE_COLOUR,
            _ring(edge * GLOW_BORDER, EDGE_COLOUR, edge * GLOW_BLUR) + tags, span, LAYER_GLOW,
        ),
        _shape(
            drawing, place, EDGE_COLOUR, _ring(edge / 2, EDGE_COLOUR) + tags, span,
            LAYER_EDGE,
        ),
    ]  # fmt: skip


def _light_event(
    drawing: str,
    place: tuple[float, float],
    scale: float,
    span: tuple[float, float],
    tags: str,
) -> str:
    """Write the thin light ring on top of letters."""
    light = max(LIGHT_WIDTH * scale * LIGHT_SHARE, MIN_LINE)
    return _shape(drawing, place, EDGE_LIGHT, _ring(light, EDGE_LIGHT) + tags, span, LAYER_LIGHT)


def _band_events(  # the letters, where, how big, when, the extra tags and how a band is clipped
    group: Sequence[Letter],
    origin: tuple[float, float],
    scale: float,
    span: tuple[float, float],
    tags: Callable[[Rect], str],
) -> list[str]:
    r"""Write the seven colour bands of ``group``: the letters, each clipped to one band.

    ``origin`` is where the word's top left stands; ``tags`` writes the tags of a band from its
    area (the ``\clip``: a sweep or a still box; a fade).
    """
    drawing, gx, gy = _contours(group, scale)
    place = (origin[0] + gx, origin[1] + gy)
    events = []
    for top, bottom, colour in bands():
        area = Rect(
            x=origin[0] + group[0].left * scale,
            y=origin[1] + top * scale,
            w=(group[-1].right - group[0].left) * scale,
            h=(bottom - top) * scale,
        )
        events.append(_shape(drawing, place, colour, "\\bord0" + tags(area), span, LAYER_BANDS))
    return events


def _word_events(card: CardElement, mark: TitleMark) -> list[str]:
    """Write the events of the wordmark: glow, edge, the bands in their steps, light edge.

    Without a build-up the edge fades out with the card (the end screen); the bands fade out with
    it too.
    """
    scale, end = mark.scale, card.end
    build = mark.build
    drawing, dx, dy = _contours(letters(), scale)
    origin = (mark.word.x, mark.word.y)
    place = (origin[0] + dx, origin[1] + dy)
    start = build.edge.start if build else card.start
    fade_in = build.edge.end - build.edge.start if build else 0.0
    out = fade_tag(0.0, card.fade_out)
    both = fade_tag(fade_in, card.fade_out)
    span = (start, end)
    events = _edge_events(drawing, place, scale, span, both)
    steps = (
        [(fill.first, fill.last, fill.when) for fill in build.fills]
        if build
        else [(0, len(letters()) - 1, None)]
    )
    for first, last, when in steps:
        begin = when.start if when else card.start

        def clip(area: Rect, when: TimeRange | None = when) -> str:
            return (_swept(area, 0.0, when) if when else _clip(area, 0.0)) + out

        events += _band_events(letters()[first : last + 1], origin, scale, (begin, end), clip)
    events.append(_light_event(drawing, place, scale, span, both))
    return events


def symbol_events(  # the card, when it stands and the extra tags of the rings and of the bands
    card: CardElement, span: tuple[float, float], rings: str, bands_tags: str
) -> list[str]:
    r"""Write the events of the V symbol of a break screen: a finished letter, glow to light edge.

    The V is drawn from the same polygon as in the wordmark, complete from the start, without a
    field, and it stands still (ADR-0040). ``rings`` (a fade of the outlines) go to the glow, the
    edge and the light edge; ``bands_tags`` (a fade of the fill) to the bands.
    """
    box = card.symbol
    if box is None:
        return []
    scale = box.h / LETTER_HEIGHT
    letter = symbol()
    drawing, dx, dy = _contours([letter], scale)
    place = (box.x + dx, box.y + dy)
    return [
        *_edge_events(drawing, place, scale, span, rings),
        *_band_events(
            [letter], (box.x, box.y), scale, span, lambda area: _clip(area, 0.0) + bands_tags
        ),
        _light_event(drawing, place, scale, span, rings),
    ]


def _frame_events(card: CardElement, mark: TitleMark) -> list[str]:
    """Write the events of the frame and the rule: glow, the framed dark inside, the amber rule."""
    frame, build = mark.frame, mark.build
    line = max(FRAME_LINE * frame.h, MIN_LINE)
    inside = _rounded(frame.w - 2 * line, frame.h - 2 * line, max(mark.radius - line, 0.0))
    place = (frame.x + line, frame.y + line)
    start = build.wipe.start if build else card.start
    sweep = _swept(frame, line * FRAME_REACH, build.wipe) if build else ""
    sweep += fade_tag(0.0, card.fade_out)
    span = (start, card.end)
    events = [
        _shape(
            inside, place, EDGE_COLOUR,
            _ring(line * FRAME_GLOW_BORDER, EDGE_COLOUR, line * FRAME_GLOW_BLUR) + sweep,
            span, LAYER_GLOW,
        ),
        _shape(
            inside, place, FRAME_FILL, f"\\bord{number(line)}\\3c{ass_colour(EDGE_COLOUR)}{sweep}",
            span, LAYER_FRAME,
        ),
    ]  # fmt: skip
    if mark.rule is not None:
        rule = mark.rule
        events.append(
            _shape(
                rectangle(rule.w, rule.h),
                (rule.x, rule.y),
                AMBER,
                "\\bord0" + sweep,
                span,
                LAYER_FRAME,
            )
        )
    return events


def mark_events(scene: Scene, card: CardElement) -> list[str]:
    """Write the events of a start screen with the wordmark, except its texts.

    That is the field over the whole picture, the wordmark with its glow, edge, bands and light
    edge, the frame with its glow and the rule. The texts are plain card lines
    (``text_start`` and ``text_clip`` say when they start and how they wipe in).
    """
    mark = card.mark
    if mark is None:
        return []
    field = _shape(
        rectangle(scene.width, scene.height), (0, 0), mark.field,
        "\\bord0" + fade_tag(0.0, card.fade_out),
        (card.start, card.end), LAYER_FIELD,
    )  # fmt: skip
    return [field, *_word_events(card, mark), *_frame_events(card, mark)]


def text_start(card: CardElement) -> float:
    """Return when the texts of a card appear: the start of the wipe, or of the card."""
    mark = card.mark
    return mark.build.wipe.start if mark and mark.build else card.start


def text_clip(card: CardElement) -> str:
    r"""Return the tags that wipe the texts of a card in from the left, empty for none."""
    mark = card.mark
    if mark is None or mark.build is None:
        return ""
    return _swept(mark.frame, 0.0, mark.build.wipe)
