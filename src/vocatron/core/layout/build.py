"""Build the scene of a song from its phrases and a profile (ADR-0009)."""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from vocatron.core.layout.cards import (
    COUNTDOWN_GAP,
    COUNTDOWN_HEIGHT,
    ROW_GAP,
    TIMER_SCALE,
    Canvas,
    CardText,
    card,
    countdown_element,
    countdown_window,
    fits_safe_area,
    progress_element,
    row_rects,
    slot_rects,
    slot_rows,
    split_timer,
    timer_text,
    title_window,
)
from vocatron.core.layout.fit import Fitted, fit, popped_width
from vocatron.core.layout.intro import intro_lead
from vocatron.core.layout.mark import (
    PIXEL_ARTIST_PX,
    PIXEL_FLOOR_PX,
    PIXEL_NAME_PX,
    PIXEL_TITLE_PX,
    builds_up,
    symbol_space,
    with_symbol,
    wordmark_card,
    wordmark_end_card,
)
from vocatron.core.layout.pages import place_pages
from vocatron.core.layout.phrases import (
    Phrase,
    is_ensemble,
    marks_of,
    numbers_in,
    one_after_another,
    shifted,
)
from vocatron.core.layout.place import (
    PAIR_SLOTS,
    Placement,
    Times,
    clearing,
    gaps,
    lead_in_shortfalls,
    place,
)
from vocatron.core.layout.scroll import (
    FIT_SLACK,
    LINE_GAP,
    Column,
    Plan,
    View,
    path_of,
    plan_stops,
    visible_stops,
)
from vocatron.core.lyrics.document import ALL, SingerInfo
from vocatron.core.measure import TextMeasurer
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    BackgroundMotion,
    CardElement,
    CardLine,
    Colours,
    CountdownElement,
    Keyframe,
    LineElement,
    LineTurn,
    Look,
    PreviewElement,
    ProgressElement,
    Rect,
    Scene,
    SceneElement,
    ScrollView,
    Shortfall,
    Span,
    TimerElement,
    rounded,
    whole_seconds,
)
from vocatron.core.wordmark import AMBER, TEXT_COLOUR

PAIR = 2  # singers who are "both"; more are "all"
MAX_LISTED = 20  # line numbers the note of lines sung at once names
MIN_END_SCREEN = 0.5  # seconds an end screen must have to be worth showing
MIN_TRANSITION = 0.05  # seconds; a shorter fade or slide is not worth an event and is left out
SCROLL_BLOCK = "the line being sung and its countdown do not fit the safe area at scroll.current"
FONT_NAME = "Noto Sans"  # the family name of the bundled font (``vocatron.fonts``)
KIND_ORDER = {
    "title": 0, "break": 1, "progress": 2, "timer": 3, "countdown": 4, "line": 5, "preview": 6,
    "end": 7,
}  # fmt: skip


@dataclass(frozen=True)
class SongText:
    """What the layout needs to know about the song besides its lines.

    Attributes:
        title: The title.
        artist: The artist, or ``None``.
        duration: The length of the audio in seconds, or ``None`` when unknown.
        singers: Names and colours of the singers from the lyrics file.
        together_two: The language's word for lines sung together by two singers ("Both");
            empty for none.
        together_all: The word for three or more singers ("All"); empty for none.
        bpm: The tempo of the song in beats per minute, or ``None`` when it is unclear: the
            countdowns then run over ``countdown.duration`` seconds (ADR-0022).
    """

    title: str
    artist: str | None
    duration: float | None
    singers: dict[int, SingerInfo]
    together_two: str = ""
    together_all: str = ""
    bpm: float | None = None


def _name(song: SongText, number: str) -> str:
    """Return the name of singer ``number``, empty when the lyrics file gives none."""
    info = song.singers.get(int(number))
    return info.name or "" if info else ""


def together_labels(phrases: Sequence[Phrase], song: SongText) -> tuple[str, ...]:
    """Return the entries for lines sung together on the title screen, each group once.

    A group that names every singer, and ``all``, is the language's word (``together_two`` for
    two singers, ``together_all`` for more); any other group is its members' names joined by
    ``&``. A group is left out when one of its members has no name, and a group of everyone when
    the language has no word (ADR-0020).
    """
    marks = marks_of(phrases)
    everyone = numbers_in(marks) | {str(number) for number in song.singers}
    word = song.together_all if len(everyone) > PAIR else song.together_two
    labels: list[str] = []
    for mark in (m for m in marks if m == ALL or "," in m):
        members = everyone if mark == ALL else set(mark.split(","))
        names = [_name(song, number) for number in sorted(members)]
        if not names or not all(names):
            continue  # a group is listed only when all its members have names
        label = word if members >= everyone else " & ".join(names)
        if label and label not in labels:
            labels.append(label)
    return tuple(labels)


def safe_area(profile: Profile, frame: tuple[int, int]) -> Rect:
    """Return the safe area of a frame: the profile's share of it, centred."""
    width, height = frame
    safe_w, safe_h = width * profile.safe_area, height * profile.safe_area
    return Rect(
        x=rounded((width - safe_w) / 2),
        y=rounded((height - safe_h) / 2),
        w=rounded(safe_w),
        h=rounded(safe_h),
    )


def background_motion(profile: Profile) -> BackgroundMotion | None:
    """Return the moving background of a profile, or ``None`` for the plain colour."""
    motion = profile.background_motion
    return BackgroundMotion(colours=motion.colours, speed=motion.speed) if motion.colours else None


def line_colours(singers: str, profile: Profile, infos: dict[int, SingerInfo]) -> Colours:
    """Return the colours of a line: its singer's, or the group's for several or ``all``.

    A colour from the lyrics file replaces the singer's sung colour (ADR-0008).
    """
    key = singers if singers in {"1", "2", "3", "4", "5"} else "group"
    base = profile.singer_colours(key)
    info = infos.get(int(key)) if key != "group" else None
    sung = info.colour if info is not None and info.colour else base.sung
    return Colours(unsung=base.unsung, sung=sung, edge=base.edge)


def _box_in(ctx: Context, width: float, size: float, region: Rect) -> tuple[Rect, float]:
    """Return the box of a text of ``width`` at ``size`` aligned in ``region``, and its padding."""
    profile, safe = ctx.profile, ctx.safe
    pad = profile.padding(size)
    box_w, box_h = width + 2 * pad, size + 2 * pad
    left = {
        "center": safe.x + (safe.w - box_w) / 2,
        "left": safe.x,
        "right": safe.right - box_w,
    }[profile.align]
    box = Rect(
        x=rounded(left),
        y=rounded(region.y + (region.h - box_h) / 2),
        w=rounded(box_w),
        h=rounded(box_h),
    )
    return box, pad


def transition_times(ctx: Context, item: Fitted, placement: Placement) -> tuple[float, float]:
    """Return how long a line takes to come in and to go (``LineElement.enter`` and ``exit``).

    The profile's ``transition.time``, but never into the singing: the line is in before its
    first syllable (a wipe shifted earlier counts) and starts to go after its last one (a wipe
    shifted later counts), and a transition shorter than ``MIN_TRANSITION`` is left out. All
    rows of a line get the same times, since they come and go together (ADR-0032).
    """
    profile = ctx.profile
    if profile.transition.form == "none":
        return 0.0, 0.0
    first = item.parts[0].start + min(profile.wipe.offset, 0.0)
    time = profile.transition.time
    enter = _move_time(time, rounded(first) - rounded(placement.show))
    return enter, _exit_time(ctx, item, placement.hide, time)


def _move_time(time: float, room: float) -> float:
    """Return ``time`` cut to ``room``; a move shorter than ``MIN_TRANSITION`` is left out."""
    seconds = rounded(max(min(time, room), 0.0))
    return seconds if seconds >= MIN_TRANSITION else 0.0


def _exit_time(ctx: Context, item: Fitted, hide: float, time: float) -> float:
    """Return how long a line takes to go before ``hide``: ``time``, but after its singing.

    The line is sung to its end (a wipe shifted later counts) before it starts to go.
    """
    last = item.parts[-1].end + max(ctx.profile.wipe.offset, 0.0)
    return _move_time(time, rounded(hide) - rounded(last))


def _line_element(  # the row of a block, where and when it is, and how it moves
    item: Fitted, row: int, placement: Placement, ctx: Context, region: Rect,
    moves: tuple[float, float] = (0.0, 0.0),
) -> LineElement:  # fmt: skip
    """Draw row ``row`` of a line into its region: box, text position and every syllable's place.

    The placement's slot is the row's own slot; ``moves`` are the block's ``enter`` and ``exit``.
    """
    phrase, size = item.parts[row], item.size
    profile, measurer = ctx.profile, ctx.measurer
    edge, shadow = profile.edge.width * size, profile.shadow.offset * size
    box, pad = _box_in(ctx, popped_width(phrase, measurer, size, profile.pop), size, region)
    spans: list[Span] = []
    text, before = "", 0.0
    for piece in phrase.pieces:
        text += piece.text
        after = measurer.width(text, size)
        spans.append(Span(text=piece.text, start=rounded(piece.start), end=rounded(piece.end),
                          x0=rounded(before), x1=rounded(after)))  # fmt: skip
        before = after
    return LineElement(
        start=rounded(placement.show),
        end=rounded(placement.hide),
        box=box,
        text=phrase.text,
        singers=phrase.singers,
        voice=phrase.voice,
        slot=placement.slot,
        page=placement.page,
        row=row,
        part=item.part,
        enter=moves[0],
        exit=moves[1],
        size=rounded(size),
        edge=rounded(edge),
        shadow=rounded(shadow),
        colours=line_colours(phrase.shown_singers, profile, ctx.song.singers),
        turns=[
            LineTurn(
                span=turn.piece,
                singers=turn.singers,
                colours=line_colours(turn.singers, profile, ctx.song.singers),
            )
            for turn in phrase.turns
        ],
        text_x=rounded(box.x + pad),  # a popping word pushes the text after it to the right only
        text_y=rounded(box.y + pad),
        spans=spans,
    )


def _block_elements(
    item: Fitted, placement: Placement, ctx: Context, slots: list[Rect]
) -> list[LineElement]:
    """Draw a line into its slot: one element per row, which appear and go together.

    With ``page.slot_per_row`` row ``r`` has the slot ``placement.slot + r`` to itself; otherwise
    the rows share the slot.
    """
    count = len(item.parts)
    moves = transition_times(ctx, item, placement)
    if ctx.profile.page.slot_per_row:
        return [
            _line_element(item, row, replace(placement, slot=placement.slot + row), ctx,
                          slots[placement.slot + row], moves)
            for row in range(count)
        ]  # fmt: skip
    regions = row_rects(slots[placement.slot], count, ctx.size)
    return [
        _line_element(item, row, placement, ctx, region, moves)
        for row, region in enumerate(regions)
    ]


@dataclass(frozen=True)
class Context:
    """What building the scene shares: profile, measurer, song, safe area and the base size."""

    profile: Profile
    measurer: TextMeasurer
    song: SongText
    safe: Rect
    size: float
    together: tuple[str, ...] = ()
    wordmark: bool = False
    pixel: bool = False

    @property
    def canvas(self) -> Canvas:
        """The canvas the cards are drawn on."""
        return Canvas(self.measurer, self.profile, self.safe, self.size)

    @property
    def marked(self) -> bool:
        """Whether the end and break screens carry the mark: the video's wordmark form."""
        return self.wordmark and not self.pixel

    @property
    def rule_after(self) -> int | None:
        """The index of the line the start and end screens' rule stands under, ``None`` for none."""
        fields = self.profile.title.fields
        return 0 if "title" in fields and "artist" in fields and self.song.artist else None

    def names(self, wordmark: bool | None = None) -> list[CardText]:
        """Return the title and the artist as card lines (in capitals, with the wordmark).

        Args:
            wordmark: Whether the lines are those of the start screen with the wordmark; the
                default is the profile's form, but on the CD+G screen only that start screen
                has it, the end and break screens keep the look's colours (ADR-0056).
        """
        colour = self.profile.colours.group.unsung
        if self.marked if wordmark is None else wordmark:
            lines = [
                CardText(
                    self.song.title.upper(),
                    self._scale(1.0, PIXEL_TITLE_PX),
                    TEXT_COLOUR,
                    wraps=True,
                )
            ]
            if self.song.artist:
                artist = self.song.artist.upper()
                lines.append(CardText(artist, self._scale(0.7, PIXEL_ARTIST_PX), AMBER, wraps=True))
            return lines
        lines = [CardText(self.song.title, 1.0, colour)]
        if self.song.artist:
            lines.append(CardText(self.song.artist, 0.7, colour))
        return lines

    def _scale(self, share: float, pixels: float) -> float:
        """Return a start screen text's share of the base size: ``share``, or on CD+G ``pixels``.

        The texts of the CD+G start screen have sizes of their own in pixels, the same in every
        look (ADR-0056); in the video they are relative to the base size.
        """
        return pixels / self.size if self.pixel else share

    def title_card(self, end: float) -> CardElement:
        """Build the start screen from 0 to ``end``: with the wordmark, or the plain card.

        On the CD+G screen (``pixel``) the wordmark is made of pixel letters, and a screen that
        lasts less than ``BUILD_MIN`` seconds, or whose texts would be smaller than
        ``PIXEL_FLOOR_PX``, is the plain card (ADR-0056).
        """
        wordmark = self.wordmark and (not self.pixel or builds_up(end))
        lines = self.title_lines(wordmark)
        if wordmark:
            floor = PIXEL_FLOOR_PX if self.pixel else None
            marked = wordmark_card(lines, self.canvas, end, self.rule_after, self.pixel, floor)
            if marked is not None:
                return marked
            lines = self.title_lines(False)
        return card("title", lines, self.canvas, 0.0, end)

    def title_lines(self, wordmark: bool) -> list[CardText]:
        """Return the lines of the title screen as the profile's ``title.fields`` say."""
        names = self.names(wordmark)
        small = self._scale(0.6, PIXEL_NAME_PX) if wordmark else 0.6
        singers = [
            CardText(
                info.name,
                small,
                line_colours(str(number), self.profile, self.song.singers).sung,
                flows=wordmark,
            )
            for number, info in sorted(self.song.singers.items())
            if info.name
        ]
        group = self.profile.colours.group.sung
        groups = [CardText(label, small, group, flows=wordmark) for label in self.together]
        wanted = self.profile.title.fields
        return [
            *names[:1] * ("title" in wanted),
            *names[1:] * ("artist" in wanted),
            *singers * ("singers" in wanted),
            *groups * ("singers" in wanted),
        ]


def _previews(
    fitted: list[Fitted],
    blocks: list[list[LineElement]],
    heads: list[int],
    times: list[Times],
    ctx: Context,
    row: Rect,
) -> list[PreviewElement]:
    """Build the previews: line ``i`` is shown smaller below line ``i - 1`` until it moves up.

    The preview of a line of several rows is its first row. ``heads`` holds the index of the
    first row of every line in the scene's lines, which is ``of_line``.

    A preview appears at the later of the show of the line before and ``lead_in.max`` before its
    line is sung, so rule 5 holds on the moment a line is first seen. There is none across a long
    gap, and none for a line that appears the moment the line before it is sung.
    """
    profile, scale = ctx.profile, ctx.profile.preview.scale
    found: list[PreviewElement] = []
    first_rows = [block[0] for block in blocks]
    for index, silence in enumerate(gaps(times)):
        if index == 0 or silence.before >= profile.breaks.clear_after:
            continue
        line = first_rows[index]
        start = rounded(max(first_rows[index - 1].start, times[index].start - profile.lead_in.max))
        if start >= line.start:
            continue
        size = fitted[index].size * scale
        box, pad = _box_in(ctx, ctx.measurer.width(line.text, size), size, row)
        text = CardLine(
            text=line.text,
            size=rounded(size),
            edge=rounded(profile.edge.width * size),
            shadow=rounded(profile.shadow.offset * size),
            colour=line.colours.unsung,
            edge_colour=line.colours.edge,
            box=box,
            text_x=rounded(box.x + pad),
            text_y=rounded(box.y + pad),
        )
        found.append(
            PreviewElement(start=start, end=line.start, box=box, of_line=heads[index], line=text)
        )
    return found


def _cards_and_countdowns(
    lines: list[LineElement], times: list[Times], ctx: Context, band: Rect, title_end: float
) -> list[CardElement | ProgressElement | TimerElement | CountdownElement]:
    """Build the break screens and countdowns of the long gaps and the title screen.

    Args:
        lines: The first row of every line, in the order they are sung.
        times: When each of them is sung (all its rows).
        ctx: What building the scene shares.
        band: The band above the slots that is kept free for the countdown.
        title_end: When the title screen ends, 0 for none.
    """
    profile = ctx.profile
    found: list[CardElement | ProgressElement | TimerElement | CountdownElement] = [
        *_title_card(ctx, title_end)
    ]
    for index, (line, silence) in enumerate(zip(lines, gaps(times), strict=True)):
        gap = silence.before
        floor = max(silence.ended, title_end)  # the line before ends after the title (ADR-0026)
        if index and gap >= profile.breaks.notice_after:
            start = clearing(silence.ended, times[index].start, profile)
            if start < line.start:
                found += _break_screen(ctx, start, line.start)
                floor = line.start
        if gap >= profile.countdown.min_gap:
            window = countdown_window(profile.countdown, ctx.song.bpm, line.sing_start, floor)
            if window is not None:
                found.append(
                    countdown_element(profile, ctx.safe, band, line.text_x, window)  # fmt: skip
                )
    return found


def _title_card(ctx: Context, title_end: float) -> list[CardElement]:
    """Build the title screen up to ``title_end``, or nothing when there is none (0)."""
    return [ctx.title_card(title_end)] if title_end > 0 else []


def _break_screen(
    ctx: Context, start: float, end: float
) -> list[CardElement | ProgressElement | TimerElement]:
    """Build the break screen from ``start`` to ``end`` with what the form of the profile adds.

    The ``notice`` form is the screen alone; ``progress`` adds the bar under its text, ``timer``
    the seconds timer, which is laid out with the text and then split off (``split_timer``). The
    text is centred in the safe area, in every mode (ADR-0040).
    """
    profile = ctx.profile
    form = profile.breaks.form
    text = [CardText(profile.breaks.notice, 0.9, profile.colours.group.unsung)]
    if ctx.marked:  # room for the V symbol above the notice (ADR-0057)
        text.insert(0, symbol_space(0.9))
    if profile.breaks.show_title:
        text += [CardText(c.text, c.scale * 0.5, c.colour) for c in ctx.names()]
    if form == "timer":
        text.append(_timer_text(ctx, rounded(end) - rounded(start)))
    screen = card("break", text, ctx.canvas, start, end)
    timer = None
    if form == "timer":
        screen, timer = split_timer(screen)
    if ctx.marked:
        screen = with_symbol(screen)
    if timer is not None:
        return [screen, timer]
    if form == "progress":
        return [screen, progress_element(profile, ctx.safe, screen.box, ctx.size, start, end)]
    return [screen]


def _timer_text(ctx: Context, seconds: float) -> CardText:
    """Return the last line of a break screen with a timer: the widest number it will show.

    The line is laid out with the screen, which centres the timer under the text; ``split_timer``
    then takes it out. It is in the group's sung colour.
    """
    scale = 0.9 * TIMER_SCALE  # of the notice, which is 0.9 of the base size
    text = timer_text(ctx.measurer, whole_seconds(seconds), ctx.size * scale)
    return CardText(text, scale, ctx.profile.colours.group.sung)


def _end_card(lines: list[LineElement], ctx: Context, duration: float) -> list[CardElement]:
    """Build the end screen, if the profile wants one and the song leaves room for it.

    With the wordmark form it is the start screen's wordmark screen without the build-up
    (ADR-0057); otherwise, and on CD+G, the plain card.
    """
    ending = ctx.profile.ending
    start = max(line.sing_end for line in lines) + ending.start_after
    if not ending.end_screen or duration - start < MIN_END_SCREEN:
        return []
    texts = ctx.title_lines(True) if ctx.marked else []
    if texts:  # the wordmark screen of the start without the build-up (ADR-0057)
        return [
            wordmark_end_card(texts, ctx.canvas, (start, duration), ending.fade, ctx.rule_after)
        ]
    return [card("end", ctx.names(), ctx.canvas, start, duration, ending.fade)]


@dataclass(frozen=True)
class Scrolled:
    """What the scroll layout makes: the lines and the elements around them.

    Attributes:
        blocks: The rows of every line, in the order the lines are sung.
        others: The break screens (with their bars or timers) and the countdowns.
        view: The measures of the column.
        short: What the column could not do as the profile asks.
    """

    blocks: list[list[LineElement]]
    others: list[CardElement | ProgressElement | TimerElement | CountdownElement]
    view: ScrollView
    short: list[Shortfall]


def scroll_view(ctx: Context) -> ScrollView:
    """Return the measures of the column of a profile in scroll mode."""
    cfg = ctx.profile.scroll
    return ScrollView(
        current=rounded(ctx.safe.y + cfg.current * ctx.safe.h),
        before=cfg.before,
        after=cfg.after,
        glide=cfg.glide,
        min_glide=cfg.shortest_glide,
    )


def _countdown_room(ctx: Context) -> float:
    """Return the room a countdown takes above its line: its band and the gap below it."""
    return (COUNTDOWN_HEIGHT + COUNTDOWN_GAP) * ctx.size


def _row_pitch(item: Fitted, ctx: Context) -> tuple[float, float]:
    """Return the height of a row of ``item`` and how far apart its rows are."""
    row_h = item.size + 2 * ctx.profile.padding(item.size)
    return row_h, row_h + ROW_GAP * ctx.size


def _column(plan: Plan, heights: list[float], ctx: Context) -> Column:
    """Return the entries of the column: the stops of the plan with their heights and gaps.

    A line with a countdown has the countdown's band above it; a line without one has none. The
    first line of every part starts the column again (``Column.starts``).
    """
    band = _countdown_room(ctx)
    return Column(
        [heights[stop.line] for stop in plan.stops],
        [LINE_GAP * ctx.size + band * (stop.line in plan.countdowns) for stop in plan.stops],
        frozenset(part.first for part in plan.parts),
    )


def _scroll_block(
    item: Fitted, path: list[Keyframe], top: float, ctx: Context, leaves: bool
) -> list[LineElement]:
    """Draw the rows of a line where it is sung, with the path of the glides.

    ``top`` is the top of its block at the stop it is sung at; every row gets the same path, the
    offsets added to its own place. ``leaves`` says the lines go where the part of the column
    ends before a long break: they then fade out over ``ending.fade`` seconds, but never into the
    singing (``exit``, ADR-0040).
    """
    row_h, pitch = _row_pitch(item, ctx)
    placement = Placement(0, path[0].time, path[-1].time)
    # the lines of a part go over the fade of the end of the song (ADR-0040)
    moves = (0.0, _exit_time(ctx, item, placement.hide, ctx.profile.ending.fade) if leaves else 0.0)
    rows: list[LineElement] = []
    for row in range(len(item.parts)):
        region = Rect(x=ctx.safe.x, y=rounded(top + row * pitch), w=ctx.safe.w, h=rounded(row_h))
        shown = _line_element(item, row, placement, ctx, region, moves)
        rows.append(shown.model_copy(update={"path": _on_path(shown.anchor, path)}))
    return rows


def _on_path(anchor: float, offsets: list[Keyframe]) -> list[Keyframe]:
    """Return the keyframes of an element built at ``anchor``: the offsets added to it."""
    return [Keyframe(time=k.time, y=rounded(anchor + k.y)) for k in offsets]


def scroll_lines(
    fitted: list[Fitted], times: list[Times], ctx: Context, first_show: float, title_end: float
) -> Scrolled:
    """Lay the lines out as a column that glides (ADR-0033).

    The plan (``plan_stops``) says when the column glides; every line is drawn where it is sung,
    with a path that follows the column while the line is in view. A long break ends a part of the
    column: its lines go, the break screen of the look stands alone and still as in the other
    modes, and the next part comes in from below like the song does (ADR-0040); a line after a
    gap that asks for it has a countdown above it, which stands still.

    Args:
        fitted: The lines in the order they are sung.
        times: When each of them is sung.
        ctx: What building the scene shares.
        first_show: When the column starts to come in: the title screen ends.
        title_end: When the title screen ends, 0 for none.
    """
    profile, size = ctx.profile, ctx.size
    view = scroll_view(ctx)
    plan = plan_stops(times, profile, ctx.song.bpm, first_show, title_end)
    heights = [len(item.parts) * _row_pitch(item, ctx)[1] - ROW_GAP * size for item in fitted]
    column = _column(plan, heights, ctx)
    centres, steps = column.centres(), column.steps()
    window = View(view.current, ctx.safe.y, ctx.safe.bottom, view.before, view.after)
    blocks: list[list[LineElement]] = []
    crowded = False
    for index, item in enumerate(fitted):
        part = plan.part_of(index)
        run = visible_stops(index, column, centres, window, part)
        path = path_of(index, run, plan, centres, steps)
        top = view.current - heights[index] / 2
        blocks.append(
            _scroll_block(item, path, top, ctx, run[1] == part.last and part.leave is not None)
        )
        room = _countdown_room(ctx) * (index in plan.countdowns)
        crowded = (
            crowded
            or top - room < ctx.safe.y - FIT_SLACK
            or top + heights[index] > ctx.safe.bottom + FIT_SLACK
        )
    others: list[CardElement | ProgressElement | TimerElement | CountdownElement] = []
    band_h = COUNTDOWN_HEIGHT * size
    for index, found in plan.countdowns.items():
        row = blocks[index][0]
        band = Rect(
            x=ctx.safe.x, y=rounded(row.box.y - COUNTDOWN_GAP * size - band_h), w=ctx.safe.w,
            h=rounded(band_h),
        )  # fmt: skip
        others.append(countdown_element(profile, ctx.safe, band, row.text_x, found))
    for part, following in zip(plan.parts, plan.parts[1:], strict=False):
        if part.leave is not None:  # the screen stands from the lines going to the glide in
            others += _break_screen(ctx, part.leave, plan.stops[following.first].glide_start)
    short = [Shortfall(kind="block", message=SCROLL_BLOCK)] if crowded else []
    return Scrolled(blocks, others, view, short)


def layout(  # noqa: PLR0913  # the CD+G screen sets its safe area and its pixel mark, by keyword
    phrases: Sequence[Phrase],
    song: SongText,
    profile: Profile,
    frame: tuple[int, int],
    measurer: TextMeasurer,
    *,
    safe: Rect | None = None,
    pixel_mark: bool = False,
) -> Scene:
    """Turn the sung lines of a song into a scene.

    Args:
        phrases: The lines with their syllable times, ordered by start. Lines of one voice must not
            overlap in time (the alignment finds one path through the words); lines of the two
            voices may: line mode and the blocks show them side by side, first voice above
            (ADR-0054), the other looks one after the other (``one_after_another``) and note
            it in the shortfalls. Lines are never merged. The
            scene shifts them later by ``Scene.lead`` seconds where the profile's ``intro``
            asks (ADR-0020), so every time in the scene includes the silent intro.
        song: Title, artist, length and the singers' names and colours.
        profile: The style profile.
        frame: Width and height of the frame in pixels.
        measurer: Measures text in the bundled font.
        safe: The safe area in pixels; ``None`` takes the profile's share of the frame (the CD+G
            screen sets its visible area, ADR-0023).
        pixel_mark: The start screen with the wordmark has pixel letters and no build-up, and only
            when it lasts at least four seconds (the CD+G screen, ADR-0056).

    Returns:
        The scene: every element with its place and time, and what could not be done as the
        profile asks.
    """
    stacks = profile.mode == "line" and profile.slots >= PAIR_SLOTS
    note: list[Shortfall] = [] if stacks else _once_at_a_time(phrases)
    if note:  # the looks without a place for two lines at a time show the lines one by one
        phrases = one_after_another(phrases)
    lead = intro_lead(
        min((p.start for p in phrases), default=0.0), is_ensemble(marks_of(phrases)), profile
    )
    together = together_labels(phrases, song)
    phrases = shifted(phrases, lead)
    safe = safe_area(profile, frame) if safe is None else safe
    size = profile.font.size * safe.h
    pad = profile.padding(size)
    ctx = Context(
        profile, measurer, song, safe, size, together, profile.title.form == "wordmark", pixel_mark
    )
    look = Look(
        font=FONT_NAME,
        wipe=profile.wipe.granularity,
        wipe_offset=profile.wipe.offset,
        shadow_colour=profile.shadow.colour,
        shadow_alpha=profile.shadow.alpha,
        glow=profile.glow.sung,
        glow_colour=profile.glow.colour,
        pop_scale=profile.pop.scale,
        pop_time=profile.pop.time,
        upcoming_dim=profile.upcoming.dim,
        transition=profile.transition.form,
        sung_dim=profile.dim_sung if profile.mode == "scroll" else 0.0,
    )
    scrolling = profile.mode == "scroll"
    slots: list[Rect] = []
    band, row = Rect(x=0, y=0, w=0, h=0), None  # a column has no slots, band or preview row
    if not scrolling:
        slots, band, row = slot_rects(profile, safe, size, pad)
    rects = [*slots, *([row] if row else [])]
    shortfalls = (
        [] if scrolling or fits_safe_area(rects, band, safe) else [_block_shortfall(profile)]
    ) + note
    fitted = _fit_all(phrases, ctx)
    if not fitted:
        return _empty(ctx, frame, look, slots, shortfalls)
    # the scene's times, so the gaps decided on are the ones ``layout.json`` shows
    times = [Times(rounded(item.phrase.start), rounded(item.phrase.end)) for item in fitted]
    title_end, first_show, title_short = title_window(times[0].start, profile)
    scrolled: Scrolled | None = None
    if scrolling:
        scrolled = scroll_lines(fitted, times, ctx, first_show, title_end)
        blocks = scrolled.blocks
        shortfalls += scrolled.short
    else:
        if profile.mode == "page":
            rows = [len(item.parts) if profile.page.slot_per_row else 1 for item in fitted]
            placements = place_pages(times, first_show, profile, rows)
        else:
            placements = place(
                times,
                first_show,
                profile,
                [item.part for item in fitted],
                [item.phrase.voice for item in fitted],
            )
        blocks = [
            _block_elements(item, placement, ctx, slots)
            for item, placement in zip(fitted, placements, strict=True)
        ]
    lines = [line for block in blocks for line in block]
    first_rows = [block[0] for block in blocks]
    heads = [sum(len(block) for block in blocks[:i]) for i in range(len(blocks))]
    previews = _previews(fitted, blocks, heads, times, ctx, row) if row else []
    seen = [line.start for line in first_rows]
    for preview in previews:
        seen[heads.index(preview.of_line)] = preview.start
    short = [
        short.model_copy(update={"line": heads[short.line or 0]})  # the index of its first row
        for short in lead_in_shortfalls(seen, times, profile)
    ]
    shortfalls += [*title_short, *short, *_too_wide(fitted, heads)]
    # the song ends where its audio ends; the intro makes the video longer by the lead
    duration = (
        song.duration + lead if song.duration is not None else max(line.end for line in lines)
    )
    around = (
        scrolled.others
        if scrolled
        else _cards_and_countdowns(first_rows, times, ctx, band, title_end)
    )
    elements: list[SceneElement] = [
        *lines,
        *previews,
        *around,
        *_end_card(lines, ctx, duration),
    ]
    if scrolling:
        elements += _title_card(ctx, title_end)
    elements.sort(key=lambda e: (e.start, KIND_ORDER[e.kind]))
    return Scene(
        width=frame[0],
        height=frame[1],
        safe=safe,
        background=profile.background,
        background_motion=background_motion(profile),
        duration=rounded(duration),
        lead=lead,
        bpm=song.bpm,
        slots=slots,
        scroll=scrolled.view if scrolled else None,
        preview_row=row,
        look=look,
        elements=elements,
        shortfalls=shortfalls,
    )


def _once_at_a_time(phrases: Sequence[Phrase]) -> list[Shortfall]:
    """Note the lines of the two voices sung at once that a look shows one after the other.

    Args:
        phrases: The lines ordered by their start.

    Returns:
        One shortfall naming the lines (counted from 1 in sung order), none when no lines overlap.
    """
    numbers = sorted(
        {
            number
            for later, phrase in enumerate(phrases)
            for earlier in range(later)
            if phrase.start < phrases[earlier].end
            for number in (earlier + 1, later + 1)
        }
    )
    if not numbers:
        return []
    shown = ", ".join(str(number) for number in numbers[:MAX_LISTED])
    more = f" and {len(numbers) - MAX_LISTED} more" if len(numbers) > MAX_LISTED else ""
    message = f"lines {shown}{more} sung at once are shown one after the other in this look"
    return [Shortfall(kind="overlap", message=message)]


def _fit_all(phrases: Sequence[Phrase], ctx: Context) -> list[Fitted]:
    """Fit the phrases and put the lines in the order they are sung.

    Returns:
        The lines in the order they are sung (the halves of a split line sing in turn), each
        with its ``part``.
    """
    profile, measurer, safe = ctx.profile, ctx.measurer, ctx.safe
    limit = safe.w - 2 * profile.padding(ctx.size)
    min_size = profile.font.min_size * safe.h
    fitted = [
        replace(item, part=part)
        for phrase in phrases
        for part, item in enumerate(
            fit(phrase, measurer, ctx.size, min_size, limit, profile.line_rows, pop=profile.pop)
        )
    ]
    return sorted(fitted, key=lambda item: item.phrase.start)


def _block_shortfall(profile: Profile) -> Shortfall:
    """Describe slots that do not fit the safe area, naming their rows when a slot has several."""
    rows = f" of {slot_rows(profile)} rows" if slot_rows(profile) > 1 else ""
    message = f"the slots{rows} and the countdown do not fit the safe area"
    return Shortfall(kind="block", message=message)


def _too_wide(fitted: list[Fitted], heads: list[int]) -> list[Shortfall]:
    """Describe the lines that are wider than the safe area even at the smallest size.

    ``heads`` holds the index of the first row of every line in the scene's lines.
    """
    return [
        Shortfall(
            kind="too-wide",
            line=heads[index],
            message="wider than the safe area at the smallest size",
        )
        for index, item in enumerate(fitted)
        if item.too_wide
    ]


def _empty(
    ctx: Context, frame: tuple[int, int], look: Look, slots: list[Rect], shortfalls: list[Shortfall]
) -> Scene:
    """Return the scene of a song without sung lines: the title screen for the whole song."""
    duration = ctx.song.duration or ctx.profile.title.min
    elements: list[SceneElement] = []
    if ctx.profile.title.fields:
        elements.append(ctx.title_card(duration))
    return Scene(
        width=frame[0],
        height=frame[1],
        safe=ctx.safe,
        background=ctx.profile.background,
        background_motion=background_motion(ctx.profile),
        duration=rounded(duration),
        bpm=ctx.song.bpm,
        slots=slots,
        scroll=scroll_view(ctx) if ctx.profile.mode == "scroll" else None,
        look=look,
        elements=elements,
        shortfalls=shortfalls,
    )
