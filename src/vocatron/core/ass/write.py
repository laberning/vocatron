"""The writer: the scene as an ASS file (ADR-0002, ADR-0009, ADR-0032, ADR-0033, ADR-0040)."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from vocatron.core.ass.mark import (
    LAYER_TEXT,
    mark_events,
    mark_styles,
    symbol_events,
    text_clip,
    text_start,
)
from vocatron.core.ass.tags import (
    CIRCLE,
    PATH_EPS,
    dialogue,
    move,
    number,
    rectangle,
    solid,
    style_name,
)
from vocatron.core.ass.tags import fade as fade_tag
from vocatron.core.ass.timing import cs_of
from vocatron.core.colour import ass_alpha, ass_colour
from vocatron.core.scene import (
    CardElement,
    CardLine,
    Colours,
    CountdownElement,
    Keyframe,
    LineElement,
    Look,
    PreviewElement,
    ProgressElement,
    Scene,
    SceneElement,
    TimerElement,
    rounded,
)

BAR_SCALE_END = 1  # the bar shrinks to this percent of its width, and a progress bar starts there
PROGRESS_FRAME = 0.2  # the frame of a progress bar, of its height
POP_RISE = 0.4  # the share of ``pop.time`` a word takes to grow; it settles back in the rest
DIM_RAMP = 0.3  # seconds before its first syllable that a dimmed line is brought back to full
GLOW_BLUR = 0.3  # the blur of the copy of the text that is the glow at strength 1, of the font size
GLOW_MIN_OPACITY = 0.7  # the opacity of a glow of a strength near 0; it rises to 1 at strength 1
MIN_EVENT_CS = 1  # centiseconds; a stretch of a path that is shorter than this is no event
SLIDE_REACH = 0.4  # how far a line slides in or out, of the height of its slot
GLOW_LAYER = 0  # the glow is drawn under the line, which then is on the layer above


def _text(text: str) -> str:
    """Make text safe inside an event: no tags, no escapes, no line breaks."""
    return (
        text.replace("{", "(")
        .replace("}", ")")
        .replace("\\", "/")
        .replace("\n", " ")
        .replace("\r", "")
    )


def _style_line(scene: Scene, colours: Colours) -> str:
    """Write one ``Style:`` line; size, edge and shadow are set per event."""
    look = scene.look
    fields = [
        style_name(colours),
        look.font,
        "40",
        ass_colour(colours.sung),
        ass_colour(colours.unsung),
        ass_colour(colours.edge),
        ass_colour(look.shadow_colour, look.shadow_alpha),
        "-1", "0", "0", "0", "100", "100", "0", "0", "1", "0", "0", "7", "0", "0", "0", "1",
    ]  # fmt: skip
    return "Style: " + ",".join(fields)


HEADER = """[Script Info]
; Written by Vocatron
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: None

[V4+ Styles]
Format: {style_format}
"""
STYLE_FORMAT = (
    "Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
    "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
    "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
EVENTS = """
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _place(x: float, y: float, size: float, edge: float, shadow: float, motion: str = "") -> str:
    r"""Write the override block that places a text and sets its size, edge and shadow.

    ``motion`` replaces the ``\pos`` (a ``\move``, for a line that slides).
    """
    where = motion or f"\\pos({number(x)},{number(y)})"
    return f"\\an7{where}\\fs{number(size)}\\bord{number(edge)}\\shad{number(shadow)}"


def _recolour(colours: Colours) -> str:
    r"""Write the tags that switch to other colours: ``\1c`` sung, ``\2c`` unsung, ``\3c`` edge."""
    sung, unsung, edge = (ass_colour(c) for c in (colours.sung, colours.unsung, colours.edge))
    return f"\\1c{sung}\\2c{unsung}\\3c{edge}"


def _starts_word(line: LineElement, index: int) -> bool:
    """Tell whether syllable ``index`` is the first of a word (the one before ends in a space)."""
    return index == 0 or line.spans[index - 1].text.endswith(" ")


def _pop(scale: float, time: float, at: int) -> str:
    r"""Write the tags that grow the word starting ``at`` centiseconds into the event and settle it.

    The word is first set back to its size (the scale of the word before stays on the text after
    it), then grows to ``scale`` and is back to its size ``time`` seconds after it started.
    """
    grow = at * 10 + round(time * 1000 * POP_RISE)
    settle = at * 10 + round(time * 1000)
    big, normal = f"\\fscx{round(scale * 100)}\\fscy{round(scale * 100)}", "\\fscx100\\fscy100"
    return f"{normal}\\t({at * 10},{grow},{big})\\t({grow},{settle},{normal})"


def _karaoke(  # the line, how it sweeps, where the event starts and what is recoloured
    line: LineElement,
    tag: str,
    offset: float,
    origin: float | None,
    recolour: Callable[[Colours], str],
    pop: tuple[float, float] | None,
) -> str:
    """Write the text of a lyric line with a karaoke tag per syllable (see ``karaoke_text``)."""
    base = cs_of(line.start if origin is None else origin)
    cursor = base
    turns = {turn.span: recolour(turn.colours) for turn in line.turns}
    text = ""
    for index, span in enumerate(line.spans):
        begin, end = cs_of(span.start + offset), cs_of(span.end + offset)
        begin = max(begin, cursor)
        if begin > cursor:
            text += f"{{\\k{begin - cursor}}}"
        popping = _pop(*pop, begin - base) if pop and _starts_word(line, index) else ""
        text += f"{{{turns.get(index, '')}{popping}\\{tag}{max(end - begin, 0)}}}{_text(span.text)}"
        cursor = max(end, begin)
    return text


def _sweep_tag(wipe: str) -> str:
    """Return the karaoke tag of a wipe: ``kf`` for a smooth one, ``k`` for a syllable wipe."""
    return "kf" if wipe == "smooth" else "k"


def karaoke_text(
    line: LineElement,
    wipe: str,
    offset: float,
    origin: float | None = None,
    pop: tuple[float, float] | None = None,
) -> str:
    r"""Write the text of a lyric line with its wipe: ``{\k..}`` gaps and ``{\kf..}text`` pieces.

    Every boundary is rounded from the seconds once, so the durations add up to the end of the
    last syllable. The tag is ``kf`` for a smooth wipe and ``k`` for a syllable that switches at
    its start. Where the singers change inside the line (a turn), the colours switch in the block
    of the first syllable they sing.

    Args:
        line: The line.
        wipe: ``smooth`` or ``syllable``.
        offset: Seconds the wipe is shifted.
        origin: When the event that holds the text starts; the line's start by default.
        pop: The scale and the time of the growing word being sung, ``None`` for no pop.
    """
    return _karaoke(line, _sweep_tag(wipe), offset, origin, _recolour, pop)


def _sung_text(line: LineElement, recolour: Callable[[Colours], str]) -> str:
    """Write the text of a line that has been sung to its end: plain, in the primary colours."""
    turns = {turn.span: recolour(turn.colours) for turn in line.turns}
    return "".join(
        (f"{{{turns[index]}}}" if index in turns else "") + _text(span.text)
        for index, span in enumerate(line.spans)
    )


def _glow_colour(look: Look, colours: Colours) -> str:
    """Return the colour of the glow of a text in ``colours``."""
    return look.glow_colour or colours.sung


def _glow_head(look: Look, line: LineElement, motion: str, y: float) -> str:
    r"""Write the tags of the glow of a line: a blurred copy of its text in the glow colour.

    There is no outline: the filled letters are blurred as wide as the strength says into a halo.
    The fill is transparent before the sweep (``\2a``) and the glow colour at the glow opacity
    after it, so the glow grows with the colour of the text when it sweeps with the same tag.
    """
    head = _place(line.text_x, y, line.size, 0, 0, motion)
    colour = ass_colour(_glow_colour(look, line.colours))
    return (
        f"{head}\\blur{number(GLOW_BLUR * look.glow * line.size)}\\1c{colour}\\2a&HFF&"
        f"{_glow_alpha(look, 1.0)}"
    )


def _glow_alpha(look: Look, opacity: float) -> str:
    r"""Write ``\1a`` for the glow of a text at ``opacity``: its own opacity times that one."""
    return f"\\1a{ass_alpha((GLOW_MIN_OPACITY + (1 - GLOW_MIN_OPACITY) * look.glow) * opacity)}"


def _glow_recolour(look: Look) -> Callable[[Colours], str]:
    r"""Return the tags that switch the glow to the colour of a turn: ``\1c``."""
    return lambda colours: f"\\1c{ass_colour(_glow_colour(look, colours))}"


@dataclass(frozen=True)
class _Phase:
    r"""A stretch of a line's life that is one event: its times, where it is and how it fades.

    Attributes:
        start: Where the event starts.
        end: Where it ends.
        motion: A ``\\move``, or empty for the line's ``\\pos``.
        fade: A ``\\fad``, or empty.
        sung: The line is sung to its end by then, so it is plain text in the sung colours.
        y: The top of the line cell where the event starts, ``None`` for the line's ``text_y``.
    """

    start: float
    end: float
    motion: str = ""
    fade: str = ""
    sung: bool = False
    y: float | None = None


def _phases(scene: Scene, line: LineElement) -> list[_Phase]:
    r"""Split the life of a line into the events that draw it.

    A line without a transition, or with a fade, is one event (a fade is ``\fad``). A line that
    slides is up to three: it comes in moving up from below, is sung where it stands, and goes
    out moving up again (each by ``SLIDE_REACH`` of its slot's height); the last is plain text,
    since a ``\move`` cannot be combined with the karaoke of the middle.
    """
    enter, leave = line.enter, line.exit
    if not (enter or leave):
        return [_Phase(line.start, line.end)]
    if scene.look.transition == "fade":
        fade = fade_tag(enter, leave)
        return [_Phase(line.start, line.end, fade=fade)]
    reach = SLIDE_REACH * scene.slots[line.slot].h
    x, y = line.text_x, line.text_y
    middle_start, middle_end = rounded(line.start + enter), rounded(line.end - leave)
    phases: list[_Phase] = []
    if enter:
        motion, fade = move(x, y + reach, y, enter), fade_tag(enter, 0.0)
        phases.append(_Phase(line.start, middle_start, motion, fade))
    phases.append(_Phase(middle_start, middle_end))
    if leave:
        motion, fade = move(x, y, y - reach, leave), fade_tag(0.0, leave)
        phases.append(_Phase(middle_end, line.end, motion, fade, sung=True))
    return phases


@dataclass(frozen=True)
class _Stretch:
    """A piece of a path in scroll mode that is one event: where it starts and ends, and the fade.

    Attributes:
        start: Where it starts, in seconds.
        end: Where it ends.
        y: The anchor of the element where the stretch starts.
        to: The anchor where it ends; the same as ``y`` for a still stretch.
        fading: ``in`` for the glide the element comes in with, ``out`` for the one it goes with.
    """

    start: float
    end: float
    y: float
    to: float
    fading: Literal["in", "out", ""] = ""

    @property
    def moving(self) -> bool:
        """Whether the element moves during the stretch."""
        return abs(self.y - self.to) > PATH_EPS

    @property
    def fade(self) -> str:
        r"""The ``\fad`` over the whole stretch, or empty."""
        millis = round((self.end - self.start) * 1000)
        return {"in": f"\\fad({millis},0)", "out": f"\\fad(0,{millis})", "": ""}[self.fading]


def _stretches(path: list[Keyframe]) -> list[_Stretch]:
    """Split a path into the stretches that are one event each.

    A jump, or a stretch too short to be seen, is left out. The element fades in during the first
    glide and out during the last.
    """
    found: list[_Stretch] = []
    for index, (before, after) in enumerate(zip(path, path[1:], strict=False)):
        if cs_of(after.time) - cs_of(before.time) < MIN_EVENT_CS:
            continue
        fading: Literal["in", "out", ""] = ""
        if abs(before.y - after.y) > PATH_EPS:
            fading = "in" if index == 0 else "out" if index == len(path) - 2 else ""
        found.append(_Stretch(before.time, after.time, before.y, after.y, fading))
    return found


def _scroll_phases(scene: Scene, line: LineElement) -> list[_Phase]:
    r"""Split the path of a line in scroll mode into the events that draw it.

    A still part is one event at its place, a glide is one event with a ``\move``. The line fades
    in during the glide it comes in with and out during the glide it goes with. A part after the
    last syllable (and its shifted wipe) is plain text in the sung colours; the rest, before and
    with the wipe, is karaoke text, also a glide that starts while the last syllables are sung.
    A line that goes where the column ends before a long break (``exit``, ADR-0040) fades out
    over its last ``exit`` seconds, a final plain part of its still stretch.
    """
    done = _done(scene.look, line)
    stretches = _stretches(line.path)
    cut = line.end - line.exit
    if line.exit and stretches and not stretches[-1].moving and stretches[-1].start < cut:
        *before, last = stretches
        stretches = [
            *before,
            _Stretch(last.start, cut, last.y, last.to),
            _Stretch(cut, last.end, last.y, last.to, "out"),
        ]
    return [
        _Phase(
            s.start,
            s.end,
            move(line.text_x, s.y, s.to, s.end - s.start) if s.moving else "",
            s.fade,
            s.start >= done - PATH_EPS,
            s.y,
        )
        for s in stretches
    ]


def _done(look: Look, line: LineElement) -> float:
    """Return when a line is sung to its end, with the shifted wipe: from then on it is dimmed."""
    return line.sing_end + max(look.wipe_offset, 0.0)


def _dim_sung(
    look: Look, done: float, span: tuple[float, float], alphas: Callable[[Look, float], str]
) -> str:
    r"""Write the tags that dim something once it has been sung (``\t``), in scroll mode.

    It is at full opacity until ``done`` (its last syllable and its shifted wipe) and then sinks
    to the dimmed opacity over ``DIM_RAMP`` seconds; an event ``span`` (start, end) that starts
    later starts at the opacity it has by then. ``alphas`` writes the opacity tags: ``_alphas``
    for the text, ``_glow_alpha`` for its glow, so the glow sinks with the text and the line keeps
    its look.
    """
    start, end = span
    if look.sung_dim <= 0 or end <= done:
        return ""
    dimmed = 1 - look.sung_dim
    share = max((start - done) / DIM_RAMP, 0.0)  # 1 or more: fully dimmed
    if share >= 1:
        return alphas(look, dimmed)
    base = alphas(look, 1 - look.sung_dim * share) if share > 0 else ""
    ramp = f"\\t({round((max(done, start) - start) * 1000)},"
    return f"{base}{ramp}{round((done + DIM_RAMP - start) * 1000)},{alphas(look, dimmed)})"


def _undimmed(look: Look, line: LineElement) -> float:
    """Return when a dimmed line is back to full: its first syllable, or its earlier wipe."""
    return line.sing_start + min(look.wipe_offset, 0.0)


def _opacity(look: Look, full: float, time: float) -> float:
    """Return how opaque something is at ``time`` before ``full``: dimmed, then rising."""
    dimmed = 1 - look.upcoming_dim
    ramp_start = full - DIM_RAMP
    share = min(max((time - ramp_start) / DIM_RAMP, 0.0), 1.0)
    return dimmed + (1 - dimmed) * share


def _alphas(look: Look, opacity: float) -> str:
    r"""Write ``\1a`` to ``\4a`` for text at ``opacity``; the shadow keeps its own opacity."""
    plain = ass_alpha(opacity)
    return f"\\1a{plain}\\2a{plain}\\3a{plain}\\4a{ass_alpha(look.shadow_alpha * opacity)}"


def _dim(look: Look, full: float, span: tuple[float, float]) -> str:
    r"""Write the tags that dim an event before ``full`` and bring it back (``\t``).

    The event ``span`` (start, end) starts at the opacity it has at its start, and rises to full
    over the ``DIM_RAMP`` seconds before ``full``: a line's first syllable (its wipe, if that is
    shifted earlier). An event from then on is not dimmed.
    """
    start, end = span
    if look.upcoming_dim <= 0 or start >= full:
        return ""
    tags = _alphas(look, _opacity(look, full, start))
    if end <= full - DIM_RAMP:
        return tags  # the whole event is before the ramp
    ramp_start = max(full - DIM_RAMP, start)
    return (
        f"{tags}\\t({round((ramp_start - start) * 1000)},"
        f"{round((full - start) * 1000)},{_alphas(look, 1.0)})"
    )


def _line_events(scene: Scene, line: LineElement) -> list[str]:
    """Write the events of a lyric line: its phases, each with its glow under it if it has one."""
    look = scene.look
    pop = (look.pop_scale, look.pop_time) if look.pop_scale > 1 else None
    layer = GLOW_LAYER + 1 if look.glow > 0 else GLOW_LAYER
    events: list[str] = []
    for phase in _scroll_phases(scene, line) if line.path else _phases(scene, line):
        style = style_name(line.colours)
        top = line.text_y if phase.y is None else phase.y
        if phase.sung:
            text, glow = _sung_text(line, _recolour), _sung_text(line, _glow_recolour(look))
        else:
            text = karaoke_text(line, look.wipe, look.wipe_offset, phase.start, pop)
            glow = _karaoke(
                line,
                _sweep_tag(look.wipe),
                look.wipe_offset,
                phase.start,
                _glow_recolour(look),
                pop,
            )
        head = _place(line.text_x, top, line.size, line.edge, line.shadow, phase.motion)
        span = (phase.start, phase.end)
        dim = _dim(look, _undimmed(look, line), span)  # nothing once it is sung
        done = _done(look, line)
        tags = head + phase.fade + dim + _dim_sung(look, done, span, _alphas)
        if look.glow > 0:
            glow_tags = (
                _glow_head(look, line, phase.motion, top)
                + phase.fade
                + _dim_sung(look, done, span, _glow_alpha)
            )
            events.append(
                dialogue(phase.start, phase.end, style, f"{{{glow_tags}}}{glow}", GLOW_LAYER)
            )
        events.append(dialogue(phase.start, phase.end, style, f"{{{tags}}}{text}", layer))
    return events


def _plain_colours(colour: str, edge: str) -> Colours:
    """Return the colours of a plain text: one colour, before and after."""
    return Colours(unsung=colour, sung=colour, edge=edge)


def _plain(line: CardLine) -> Colours:
    """Return the colours of a card line or preview."""
    return _plain_colours(line.colour, line.edge_colour)


def _plain_event(
    line: CardLine, start: float, end: float, fade_out: float = 0.0, wipe: str = "", layer: int = 0
) -> str:
    r"""Write the event of a plain text line (a card line or a preview), fading out at its end.

    ``wipe`` is added to the tags (the ``\clip`` that wipes the texts of a start screen in) and
    ``layer`` is the layer the event is drawn on.
    """
    fade = fade_tag(0.0, fade_out)
    head = _place(line.text_x, line.text_y, line.size, line.edge, line.shadow) + fade + wipe
    return dialogue(start, end, style_name(_plain(line)), f"{{{head}}}{_text(line.text)}", layer)


def _card_events(scene: Scene, card: CardElement) -> list[str]:
    r"""Write the events of a card: one per line, the last seconds fading out.

    A break screen with the wordmark also has the V symbol above its notice (ADR-0057). Every card
    stands still, in a scroll look too (ADR-0040).
    """
    if card.mark is not None:  # the start screen with the wordmark (ADR-0055)
        start, wipe = text_start(card), text_clip(card)
        texts = [
            _plain_event(line, start, card.end, card.fade_out, wipe, LAYER_TEXT)
            for line in card.lines
        ]
        return [*mark_events(scene, card), *texts]
    texts = [_plain_event(line, card.start, card.end, card.fade_out) for line in card.lines]
    out = fade_tag(0.0, card.fade_out)
    return [*symbol_events(card, (card.start, card.end), out, out), *texts]


def _drawing(box_w: float, box_h: float, round_: bool) -> str:
    """Write a rectangle, or an ellipse, of the given size as ASS drawing commands."""
    if not round_:
        return rectangle(box_w, box_h)
    rx, ry = box_w / 2, box_h / 2
    kx, ky = rx * CIRCLE, ry * CIRCLE
    n = number
    points = [
        f"m 0 {n(ry)}",
        f"b 0 {n(ry - ky)} {n(rx - kx)} 0 {n(rx)} 0",
        f"{n(rx + kx)} 0 {n(box_w)} {n(ry - ky)} {n(box_w)} {n(ry)}",
        f"{n(box_w)} {n(ry + ky)} {n(rx + kx)} {n(box_h)} {n(rx)} {n(box_h)}",
        f"{n(rx - kx)} {n(box_h)} 0 {n(ry + ky)} 0 {n(ry)}",
    ]
    return " ".join(points)


def _progress_events(progress: ProgressElement) -> list[str]:
    r"""Write the progress bar: a fill that grows from the left to the right, inside a frame.

    The frame is the outline of a transparent rectangle, drawn inside the box so that the
    outline (which libass puts around the path) ends at the box. The fill is the same rectangle
    scaled from ``\fscx1`` to ``\fscx100`` over the life of the bar. It stands still.
    """
    box = progress.box
    edge = box.h * PROGRESS_FRAME
    shape = _drawing(box.w - 2 * edge, box.h - 2 * edge, False)
    inner = f"\\an7\\pos({number(box.x + edge)},{number(box.y + edge)})\\p1"
    millis = round((progress.end - progress.start) * 1000)
    fill = (
        f"{inner}\\bord0\\shad0\\1c{ass_colour(progress.fill)}"
        f"\\fscx{BAR_SCALE_END}\\t(0,{millis},\\fscx100)"
    )
    frame = f"{inner}\\1a&HFF&\\bord{number(edge)}\\shad0\\3c{ass_colour(progress.frame)}"
    return [
        dialogue(progress.start, progress.end, style_name(solid(colour)), f"{{{tags}}}{shape}")
        for colour, tags in ((progress.fill, fill), (progress.frame, frame))
    ]


def _timer_events(timer: TimerElement) -> list[str]:
    r"""Write the timer: one plain text event for every whole second, centred in its box.

    The number is anchored at its top centre (``\an8``), so a one-digit number and a two-digit
    one share the middle of the box.
    """
    style = style_name(_plain_colours(timer.colour, timer.edge_colour))
    centre = timer.box.x + timer.box.w / 2
    times = sorted({timer.start, timer.end, *timer.changes()})
    head = (
        f"\\an8\\pos({number(centre)},{number(timer.text_y)})\\fs{number(timer.size)}"
        f"\\bord{number(timer.edge)}\\shad{number(timer.shadow)}"
    )
    return [
        dialogue(start, end, style, f"{{{head}}}{timer.seconds_left(start)}")
        for start, end in zip(times, times[1:], strict=False)
        if cs_of(end) - cs_of(start) >= MIN_EVENT_CS
    ]


def _countdown_events(countdown: CountdownElement) -> list[str]:
    """Write the countdown: a bar shrinking to the left, or dots or blocks going out one by one."""
    box = countdown.box
    style = style_name(solid(countdown.colour))
    base = f"\\an7\\bord0\\shad0\\p1\\1c{ass_colour(countdown.colour)}"
    if countdown.form == "shrinking-bar":
        millis = round((countdown.end - countdown.start) * 1000)
        head = f"{base}\\pos({number(box.x)},{number(box.y)})\\t(0,{millis},\\fscx{BAR_SCALE_END})"
        return [
            dialogue(
                countdown.start, countdown.end, style, f"{{{head}}}{_drawing(box.w, box.h, False)}"
            )
        ]
    pitch = box.w / countdown.count
    span = countdown.end - countdown.start
    return [
        dialogue(
            countdown.start,
            countdown.start + span * (countdown.count - index) / countdown.count,
            style,
            f"{{{base}\\pos({number(box.x + index * pitch)},{number(box.y)})}}"
            f"{_drawing(box.h, box.h, countdown.form == 'dots')}",
        )
        for index in range(countdown.count)
    ]


def _styles(element: SceneElement) -> list[Colours]:
    """Return the colour sets an element needs a style for."""
    if isinstance(element, LineElement):
        return [element.colours]
    if isinstance(element, CardElement):
        return [*(_plain(line) for line in element.lines), *mark_styles(element)]
    if isinstance(element, PreviewElement):
        return [_plain(element.line)]
    if isinstance(element, ProgressElement):
        return [solid(element.fill), solid(element.frame)]
    if isinstance(element, TimerElement):
        return [_plain_colours(element.colour, element.edge_colour)]
    return [solid(element.colour)]


def _events(scene: Scene, element: SceneElement) -> list[str]:
    """Write the events of an element."""
    if isinstance(element, LineElement):
        return _line_events(scene, element)
    if isinstance(element, CardElement):
        return _card_events(scene, element)
    if isinstance(element, PreviewElement):
        return [_plain_event(element.line, element.start, element.end)]
    if isinstance(element, ProgressElement):
        return _progress_events(element)
    if isinstance(element, TimerElement):
        return _timer_events(element)
    return _countdown_events(element)


def write_ass(scene: Scene) -> str:
    """Write the ASS file of a scene (lines, previews, cards, progress bars and countdowns)."""
    colours: dict[str, Colours] = {}
    for element in scene.elements:
        for found in _styles(element):
            colours.setdefault(style_name(found), found)
    events = [event for element in scene.elements for event in _events(scene, element)]
    styles = "\n".join(_style_line(scene, c) for c in colours.values())
    head = HEADER.format(width=scene.width, height=scene.height, style_format=STYLE_FORMAT)
    return head + styles + "\n" + EVENTS + "\n".join(events) + "\n"


# ---------------------------------------------------------------- reading it back
