"""How a CD+G karaoke disc presents its lyrics, measured from the drawing events.

``analyse(events, duration)`` takes the timeline of ``vocatron.core.cdg.decode`` and returns
numbers only: the title screen, the lines on the screen and their tile rows, the horizontal
alignment, the lead-in of each line (drawn to first wipe), the speed and granularity of the
wipe, the hold and clearing, the gaps and breaks with their countdowns, the palette and the
colours per singer. Nothing reads the text of the lyrics: a tile is its position, its pixel
count and its two colours. How tiles become sessions and wipe samples is inferred in
``vocatron.lab.cdg.tracking``; on top of that this module uses these rules:

- A *line* is a session with wipe samples, joined with the session in the row below when both
  were on the screen together and their wipes overlap in time (a font taller than a tile row; a
  descender wiped in one sample during the line's wipe counts as overlapping, and so does one
  wiped in one step up to ``WIPE_JOIN_SLACK`` before or after it, at the spot the line's
  highlight was then, within ``WIPE_JOIN_PIXELS``). A row shared by
  two lines (the descenders of one and the ascenders of the next) is wiped twice; where its
  highlight jumps back by more than ``WIPE_RESTART_PIXELS`` a second *pass* begins, and each
  pass joins the line it was wiped with, as wide as the part its highlight crossed;
  two static sessions in adjacent rows join when they started within ``SAME_LINE_START``.
  A line stands in the rows of its wipe samples, so on a scrolling disc it is where it was sung.
- The *title* is the static text wider than a countdown that was drawn before the first line and
  gone by its first wipe, without the blocks of a countdown. The title phase runs from its first
  tile to the first wipe; ``lyrics_from`` is when the first line was drawn.
- A wipe *step* starts with a sample and takes every sample of the next ``STEP_GAP`` seconds; the
  wipe *speed* is the pixels gained from the first to the last sample over their time span
  (none for a line wiped in one step). On a smooth wipe the step is only the speed times
  ``STEP_GAP``; the *sample* advance (the pixels a single sample moves the highlight on) tells
  the granularity: 1 to a few pixels for a smooth wipe, a tile (6) for a wipe by tiles.
- A *gap* runs from the end of all wipes so far to the next first wipe (lines sung together
  overlap); from ``BREAK_SECONDS`` on it is a break.
- A *countdown* is at least ``COUNTDOWN_MIN_TICKS`` small changes (``COUNTDOWN_MAX_COLUMNS``
  columns at most, outside the lyric lines) in a gap, near each other on the screen and at
  regular spacing (within ``TICK_SPACING_TOLERANCE`` of the median, ``TICK_MIN_SPACING`` to
  ``TICK_MAX_SPACING`` seconds apart) and of equal width (within ``TICK_WIDTH_TOLERANCE`` columns
  of the median) and ends at most ``COUNTDOWN_MAX_BEFORE_WIPE`` seconds before the next wipe.
  A countdown may also be *recoloured*: blocks drawn together and highlighted one after the other.
  Such a "line" has wipe samples that form at least ``COUNTDOWN_MIN_TICKS`` separate bursts (no
  longer than ``COUNTDOWN_MAX_COLUMNS`` columns, the samples of the whole line, nothing between)
  that satisfy the same spacing and width rule, stand apart (at least one empty tile column
  between two bursts; a word-by-word wipe of adjoining chunks is a line), and a line follows within
  ``COUNTDOWN_MAX_BEFORE_WIPE``; it is taken out of the lyric lines and reported as the countdown
  of the gap it falls in.
- A wiped session is a *progress bar* (a bar that fills during a break) when its highlight
  moves at an even pace up to its furthest point: every step comes within
  ``BAR_PACE_TOLERANCE`` of the median spacing, for at least ``BAR_MIN_SECONDS``. Sung lines
  follow the syllables and are never that even for that long. Bars are no lyric lines; the gap
  they fall in reports how long its bar ran.
- A wiped line whose highlight gets no further than ``WIPE_MIN_COVER`` of its width, or moves
  slower than ``WIPE_MIN_SPEED``, is no sung line either: it is an animation or a picture drawn
  in XOR layers (a few pixels change colour in place). Nor is a line that changes colour in a
  single step (``STEP_GAP``): no one sings a line that fast, so it is a fade or a flash of
  the whole text, a mark that blinks in a notice or a bit of ink that did not join its line (a
  descender, a dot). Such a line is neither lyric nor title.
- The *alignment* is the edge (left, centre, right) whose position varies least over the lines;
  when all lines are equally wide, the place of their centre decides between centred and left.

Times are seconds, positions are pixels of the 300 by 216 screen (the visible area starts at 6
and ends at 294), rows are tile rows (12 pixels each, 0 to 17).
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from statistics import median, pstdev

from vocatron.core.cdg import (
    PACKETS_PER_SECOND,
    TILE_WIDTH,
    WIDTH,
    CdgEvent,
    Colour4,
)
from vocatron.lab.cdg.tracking import Change, Session, Tracking, Wipe, on_screen, track

BREAK_SECONDS = 8.0
"""A gap between wiped lines of at least this length counts as a break (an instrumental part)."""
STEP_GAP = 0.05
"""Wipe samples closer than this (seconds) belong to one step of the highlight."""
COUNTDOWN_MAX_COLUMNS = 8
"""A countdown tick touches at most this many tile columns."""
COUNTDOWN_MIN_TICKS = 3
"""A countdown has at least this many ticks."""
MIN_SPACINGS = 2
"""The spacing of a run of ticks is checked against its median once it has this many spacings."""
TICK_CLUSTER_GAP = 0.25
"""Changes closer than this (seconds) are one tick."""
TICK_MIN_SPACING = 0.3
"""Seconds between two ticks, at least."""
TICK_MAX_SPACING = 3.0
"""Seconds between two ticks, at most."""
TICK_SPACING_TOLERANCE = 0.4
"""How far (a share of the median) a tick's spacing may differ from the run's median."""
COUNTDOWN_MAX_BEFORE_WIPE = 3.0
"""A countdown's last tick comes at most this many seconds before the wipe it counts in."""
TICK_WIDTH_TOLERANCE = 1
"""How many tile columns a tick may be wider or narrower than the median tick of its run."""
BAR_MIN_SECONDS = 6.0
"""An even highlight that runs at least this long is a progress bar (on 25 discs: sung lines
5.0 s at most, bars 8.5 s and longer)."""
BAR_PACE_TOLERANCE = 0.1
"""How far (a share of the median) a step of a progress bar may be from the median spacing."""
WIPE_MIN_COVER = 0.75
"""A sung line's highlight crosses more than this share of its width (on 25 discs: sung lines
0.87 and up, animations 0.6 at most). A line wiped in a single step is no sung line either (the
shortest sung lines take 0.07 s in two steps)."""
WIPE_RESTART_PIXELS = 4 * TILE_WIDTH
"""A highlight that jumps back further than this (pixels) starts a new pass over its row."""
WIPE_MIN_SPEED = 3.0
"""Pixels per second a sung line's highlight moves at least (on 25 discs: sung lines 5 and up,
pictures in XOR layers 2 at most)."""
WIPE_JOIN_SLACK = 3.5 / PACKETS_PER_SECOND
"""A session wiped in one step joins the line in the next row if their wipes are at most this far
apart (seconds; three packets: the disc sends the tiles of one column row after row)."""
WIPE_JOIN_PIXELS = 2 * TILE_WIDTH
"""How far (pixels) such a session may be from where the line's highlight was at that time (the
same column is a few pixels off; a descender at the far end of the line above is 100 and more)."""
SCREEN_CENTRE = WIDTH // 2
"""The horizontal centre of the screen in pixels."""
MIN_LINES_FOR_ALIGNMENT = 3
"""Fewer wiped lines give the alignment ``unknown``."""
SAME_LINE_START = 1.0
"""Static sessions in adjacent rows that start this close (seconds) are one line."""
CENTRED_TOLERANCE = 2 * TILE_WIDTH
"""Equally wide lines whose centre is this close (pixels) to the screen centre are centred."""
SAME_POSITION_PIXELS = 3.0
"""Spreads of the edges that differ less than this (pixels) cannot tell the alignment."""


@dataclass(frozen=True, slots=True)
class LineStats:
    """One line of text on the screen: one or more adjacent tile rows that belong together.

    Attributes:
        rows: The tile rows where it was wiped (where it was drawn, for static text).
        start: When its first tile was drawn.
        first_wipe: When the highlight reached it, or ``None`` for static text (title, notice).
        last_wipe: When the highlight left it.
        end: When its last tile went, or ``None`` if it stood to the end.
        end_kind: How it went: ``cleared``, ``replaced``, ``preset``, ``scrolled`` or ``open``.
        left: Its leftmost ink pixel.
        right: Its rightmost ink pixel (exclusive).
        wipe_method: ``xor`` or ``recolour``.
        wipe_steps: The number of separate steps of the highlight.
        wipe_step_px: The median advance of the highlight per step in pixels.
        wipe_sample_px: The median advance per wipe sample in pixels (the granularity).
        wipe_speed: The average speed of the highlight in pixels per second.
        unsung: Palette index of the text before the highlight.
        sung: Palette index of the text after the highlight.
    """

    rows: tuple[int, ...]
    start: float
    first_wipe: float | None
    last_wipe: float | None
    end: float | None
    end_kind: str
    left: int
    right: int
    wipe_method: str | None
    wipe_steps: int
    wipe_step_px: float | None
    wipe_sample_px: float | None
    wipe_speed: float | None
    unsung: int | None
    sung: int | None

    @property
    def lead_in(self) -> float | None:
        """Seconds from the line being drawn to the first wipe."""
        return None if self.first_wipe is None else self.first_wipe - self.start

    @property
    def hold(self) -> float | None:
        """Seconds the sung line stays after the last wipe, or ``None`` if it never goes."""
        if self.last_wipe is None or self.end is None:
            return None
        return self.end - self.last_wipe


@dataclass(frozen=True, slots=True)
class Title:
    """The title phase: text shown before the first line of the song.

    Attributes:
        shown_from: When the first title tile was drawn.
        cleared_at: When the last one went, or ``None``.
        first_wipe: When the first line of the song was wiped.
        duration: Seconds from ``shown_from`` to ``first_wipe``.
        rows: The tile rows used.
        lines: The number of separate lines of text.
        lyrics_from: When the first line of the song was drawn.
    """

    shown_from: float
    cleared_at: float | None
    first_wipe: float
    duration: float
    rows: tuple[int, ...]
    lines: int
    lyrics_from: float


@dataclass(frozen=True, slots=True)
class Countdown:
    """Small regular draws before a line: the dots or numbers of a countdown.

    Attributes:
        ticks: The number of regular changes.
        interval: The median seconds between them.
        first_tick: When the first one happened.
        length: Seconds from the first tick to the next first wipe.
        before_wipe: Seconds from the last tick to the next first wipe.
        left_column: The leftmost tile column they touched.
        rows: The tile rows they touched.
        draws: Tiles drawn by the ticks.
        erases: Tiles erased by the ticks.
        recoloured: Wipe samples of the ticks (blocks that are highlighted one after the other).
        sessions: The ids of the tracked sessions that made the ticks.
    """

    ticks: int
    interval: float
    first_tick: float
    length: float
    before_wipe: float
    left_column: int
    rows: tuple[int, ...]
    draws: int
    erases: int
    recoloured: int = 0
    sessions: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class Gap:
    """The time without a wipe between two wiped lines (or before the first, after the last).

    Attributes:
        kind: ``intro``, ``between`` or ``outro``.
        start: When the previous wipe ended (0 for the intro).
        end: When the next wipe began (the end of the stream for the outro).
        length: ``end - start``.
        is_break: Whether the gap is at least ``BREAK_SECONDS`` long.
        sung_rows_at_middle: Tile rows holding sung or unsung lyrics at the middle of the gap.
        other_rows_at_middle: Tile rows holding other text (notice, title, countdown) there.
        other_changes: Tiles drawn or erased in the gap that do not belong to a lyric line.
        countdown: The countdown found in the gap, if any.
        bar: How long the progress bar that started in the gap ran (seconds), if there was one.
    """

    kind: str
    start: float
    end: float
    length: float
    is_break: bool
    sung_rows_at_middle: tuple[int, ...]
    other_rows_at_middle: tuple[int, ...]
    other_changes: int
    countdown: Countdown | None
    bar: float | None


@dataclass(frozen=True, slots=True)
class ColourUse:
    """A palette index with its colour and how often it was used."""

    index: int
    rgb: Colour4
    count: int


@dataclass(frozen=True, slots=True)
class Palette:
    """The colours of the lyrics, read when the first line was wiped.

    ``edge`` is only present on discs that compose text with XOR tiles over an outline colour.
    """

    background: ColourUse | None
    unsung: ColourUse | None
    sung: ColourUse | None
    edge: ColourUse | None


@dataclass(frozen=True, slots=True)
class Singer:
    """A pair of colours (before and after the highlight) and how many lines used it."""

    unsung: ColourUse
    sung: ColourUse
    lines: int


@dataclass(frozen=True, slots=True)
class Alignment:
    """Where the lyric lines stand horizontally.

    Attributes:
        kind: ``left``, ``centred``, ``right`` or ``unknown`` (fewer than three lines).
        left_stdev: Spread of the left edges in pixels.
        centre_stdev: Spread of the centres.
        right_stdev: Spread of the right edges.
        centre_offset: Median distance of the line centres from the screen centre.
        left_median: Median left edge.
    """

    kind: str
    left_stdev: float
    centre_stdev: float
    right_stdev: float
    centre_offset: float
    left_median: float


@dataclass(frozen=True, slots=True)
class Analysis:
    """Everything measured from one stream (numbers only).

    Attributes:
        duration: The length used for the ending (the audio length when given, else the stream).
        title: The title phase, or ``None`` if the first line came without one.
        lines: The lines that were wiped, in order.
        lines_per_screen: The median number of lyric lines visible when a line started its wipe.
        lines_per_screen_max: The most.
        row_positions: Tile row groups of the lines with how often each was used, most first.
        alignment: The horizontal alignment.
        lead_in: The median lead-in in seconds.
        wipe_speed: The median wipe speed in pixels per second.
        wipe_step_px: The median advance per step in pixels.
        wipe_sample_px: The median advance per wipe sample in pixels.
        wipe_methods: How many lines were highlighted by each method.
        hold: The median hold after the last wipe in seconds.
        end_kinds: How many lyric lines ended in each way.
        redraw_delay: The median seconds from the previous line in the same rows finishing its
            wipe to the next line being drawn there.
        gaps: All gaps in time order.
        palette: The colours.
        singers: The colour pairs of the lines, most used first.
        presets: How many memory presets (screen clears) there were.
        scrolls: How many scrolls that moved the content.
        ending: Seconds from the last wipe to the end.
        rows_at_end: Tile rows still holding text at the end.
    """

    duration: float
    title: Title | None
    lines: tuple[LineStats, ...]
    lines_per_screen: float | None
    lines_per_screen_max: int
    row_positions: tuple[tuple[tuple[int, ...], int], ...]
    alignment: Alignment
    lead_in: float | None
    wipe_speed: float | None
    wipe_step_px: float | None
    wipe_sample_px: float | None
    wipe_methods: tuple[tuple[str, int], ...]
    hold: float | None
    end_kinds: tuple[tuple[str, int], ...]
    redraw_delay: float | None
    gaps: tuple[Gap, ...]
    palette: Palette
    singers: tuple[Singer, ...]
    presets: int
    scrolls: int
    ending: float | None
    rows_at_end: tuple[int, ...]


# ---------------------------------------------------------------------- lines


def _overlap(a: Session, b: Session) -> bool:
    """Tell whether two sessions were on the screen at the same time."""
    a_end = float("inf") if a.end is None else a.end
    b_end = float("inf") if b.end is None else b.end
    return a.start < b_end and b.start < a_end


def _same_line(a: Session, b: Session) -> bool:
    """Tell whether two sessions in adjacent rows are the two rows of one line of text."""
    if not _overlap(a, b):
        return False
    if a.wipes and b.wipes:
        return _wiped_together(a, b)
    if a.wipes or b.wipes:
        return False
    return abs(a.start - b.start) <= SAME_LINE_START


def _wiped_together(a: Session, b: Session) -> bool:
    """Tell whether the wipes of two wiped sessions in adjacent rows are one highlight.

    They are when their wipes overlap in time, or when one of them is wiped in one step at most
    ``WIPE_JOIN_SLACK`` from the other's wipe and within ``WIPE_JOIN_PIXELS`` of where the
    other's highlight was at that time.
    """
    gap = max(a.wipes[0].time, b.wipes[0].time) - min(a.wipes[-1].time, b.wipes[-1].time)
    if gap <= 0:
        return True
    one, other = sorted((a, b), key=lambda s: len(_steps(s.wipes)))
    if gap > WIPE_JOIN_SLACK or len(_steps(one.wipes)) > 1:
        return False
    there = min(other.wipes, key=lambda w: abs(w.time - one.wipes[0].time)).frontier
    return abs(max(w.frontier for w in one.wipes) - there) <= WIPE_JOIN_PIXELS


def passes(session: Session) -> list[Session]:
    """Split a session at each point where its highlight jumps back (see the module docstring).

    Every pass is a copy of the session with the wipe samples of that pass, standing only where
    they went (from a tile before the first frontier to the furthest, within the row's ink): the
    row's ink belongs to two lines, and each line is only as wide as its own part. A session
    wiped once (or never) is returned as it is.
    """
    parts: list[list[Wipe]] = []
    furthest = 0
    for wipe in session.wipes:
        if not parts or wipe.frontier < furthest - WIPE_RESTART_PIXELS:
            parts.append([])
            furthest = 0
        parts[-1].append(wipe)
        furthest = max(furthest, wipe.frontier)
    if len(parts) <= 1:
        return [session]
    return [
        replace(
            session,
            wipes=part,
            left=max(session.left, min(w.frontier for w in part) - TILE_WIDTH),
            right=min(session.right, max(w.frontier for w in part)),
        )
        for part in parts
    ]


def group_lines(sessions: Sequence[Session]) -> list[list[Session]]:
    """Group sessions of adjacent tile rows that form one line (a font taller than a tile row)."""
    parent = list(range(len(sessions)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_top: dict[int, list[int]] = {}
    for i, session in enumerate(sessions):
        by_top.setdefault(min(session.rows), []).append(i)
    for i, session in enumerate(sessions):
        for j in by_top.get(max(session.rows) + 1, []):
            if _same_line(session, sessions[j]):
                parent[find(j)] = find(i)
    groups: dict[int, list[Session]] = {}
    for i, session in enumerate(sessions):
        groups.setdefault(find(i), []).append(session)
    return sorted(groups.values(), key=lambda group: min(s.start for s in group))


def _steps(wipes: Sequence[Wipe]) -> list[tuple[float, int]]:
    """Group wipe samples (in time order) into steps of ``STEP_GAP`` seconds: start, furthest pixel.

    A step starts with a sample and takes the samples up to ``STEP_GAP`` after it, so a smooth
    wipe of one pixel column every few packets still has many steps.
    """
    steps: list[tuple[float, int]] = []
    for wipe in wipes:
        if steps and wipe.time - steps[-1][0] <= STEP_GAP:
            steps[-1] = (steps[-1][0], max(steps[-1][1], wipe.frontier))
        else:
            steps.append((wipe.time, wipe.frontier))
    return steps


def _advances(frontiers: Sequence[int]) -> float | None:
    """Return the median of the pixels by which the frontier moved on, or ``None``."""
    jumps = [b - a for a, b in zip(frontiers, frontiers[1:], strict=False) if b > a]
    return median(jumps) if jumps else None


def _wipe_numbers(
    wipes: Sequence[Wipe],
) -> tuple[int, float | None, float | None, float | None]:
    """Return the number of steps, the median step and sample advance and the average speed.

    ``wipes`` are in time order. The speed is the pixels gained from the first to the last sample
    over their time span.
    """
    if not wipes:
        return 0, None, None, None
    steps = _steps(wipes)
    first, last = wipes[0], wipes[-1]
    gained = max(w.frontier for w in wipes) - first.frontier
    speed = gained / (last.time - first.time) if len(steps) > 1 and gained > 0 else None
    step_px = _advances([frontier for _, frontier in steps])
    return len(steps), step_px, _advances([w.frontier for w in wipes]), speed


def _common(counter: Counter[int]) -> int | None:
    return counter.most_common(1)[0][0] if counter else None


def progress_bar(wipes: Sequence[Wipe]) -> float | None:
    """Return how long the highlight ran if ``wipes`` (in time order) fill a progress bar.

    It is one when the steps up to the furthest frontier come at an even pace (see the module
    docstring) for at least ``BAR_MIN_SECONDS``; else ``None``.
    """
    steps = _steps(wipes)
    if not steps:
        return None
    furthest = max(frontier for _, frontier in steps)
    lead = steps[: next(i for i, (_, f) in enumerate(steps) if f == furthest) + 1]
    span = lead[-1][0] - lead[0][0]
    if span < BAR_MIN_SECONDS:
        return None
    spacings = [b[0] - a[0] for a, b in zip(lead, lead[1:], strict=False)]
    typical = median(spacings)
    even = all(abs(gap - typical) <= BAR_PACE_TOLERANCE * typical for gap in spacings)
    return span if even else None


def crossed(line: LineStats, wipes: Sequence[Wipe]) -> bool:
    """Tell whether the highlight of ``line`` crossed it like singing (see the module docstring)."""
    furthest = max(w.frontier for w in wipes)
    if line.wipe_speed is not None and line.wipe_speed < WIPE_MIN_SPEED:
        return False
    if line.wipe_steps <= 1:
        return False
    return furthest - line.left > WIPE_MIN_COVER * (line.right - line.left)


def line_stats(group: Sequence[Session]) -> LineStats:
    """Measure one line from its sessions."""
    wipes = sorted((w for s in group for w in s.wipes), key=lambda w: w.time)
    ends = [s.end for s in group]
    end = None if None in ends else max(e for e in ends if e is not None)
    last = max(group, key=lambda s: -1.0 if s.end is None else s.end)
    steps, step_px, sample_px, speed = _wipe_numbers(wipes)
    pairs = Counter((w.unsung, w.sung) for w in wipes if w.unsung is not None)
    unsung, sung = pairs.most_common(1)[0][0] if pairs else (None, None)
    if unsung is None:
        unsung = _common(sum((s.unsungs for s in group), Counter[int]()))
    methods = Counter(w.method for w in wipes)
    rows = {w.row for w in wipes} or {row for s in group for row in s.rows}
    return LineStats(
        rows=tuple(sorted(rows)),
        start=min(s.start for s in group),
        first_wipe=wipes[0].time if wipes else None,
        last_wipe=wipes[-1].time if wipes else None,
        end=end,
        end_kind="open" if end is None else last.end_kind,
        left=min(s.left for s in group),
        right=max(s.right for s in group),
        wipe_method=methods.most_common(1)[0][0] if methods else None,
        wipe_steps=steps,
        wipe_step_px=step_px,
        wipe_sample_px=sample_px,
        wipe_speed=speed,
        unsung=unsung,
        sung=sung,
    )


# ---------------------------------------------------------------------- the song


def _alignment(lyrics: Sequence[LineStats]) -> Alignment:
    if len(lyrics) < MIN_LINES_FOR_ALIGNMENT:
        return Alignment("unknown", 0.0, 0.0, 0.0, 0.0, 0.0)
    lefts = [float(line.left) for line in lyrics]
    rights = [float(line.right) for line in lyrics]
    centres = [(a + b) / 2 for a, b in zip(lefts, rights, strict=True)]
    spreads = {"left": pstdev(lefts), "centred": pstdev(centres), "right": pstdev(rights)}
    if max(spreads.values()) - min(spreads.values()) < SAME_POSITION_PIXELS:
        # All lines are equally wide: only the place on the screen tells.
        offset = abs(median(centres) - SCREEN_CENTRE)
        kind = "centred" if offset < CENTRED_TOLERANCE else "left"
    else:
        kind = min(spreads, key=lambda name: spreads[name])
    return Alignment(
        kind,
        spreads["left"],
        spreads["centred"],
        spreads["right"],
        median(centres) - SCREEN_CENTRE,
        median(lefts),
    )


def _lines_visible(lyrics: Sequence[LineStats]) -> list[int]:
    return [
        sum(on_screen(other.start, other.end, line.first_wipe) for other in lyrics)
        for line in lyrics
        if line.first_wipe is not None
    ]


def _title(static: Sequence[LineStats], first_start: float, first_wipe: float) -> Title | None:
    wide = [
        line
        for line in static
        if line.start < first_start
        and line.end is not None
        and line.end <= first_wipe
        and line.right - line.left > COUNTDOWN_MAX_COLUMNS * TILE_WIDTH
    ]
    if not wide:
        return None
    ends = [line.end for line in wide]
    return Title(
        shown_from=min(line.start for line in wide),
        cleared_at=None if None in ends else max(e for e in ends if e is not None),
        first_wipe=first_wipe,
        duration=first_wipe - min(line.start for line in wide),
        rows=tuple(sorted({row for line in wide for row in line.rows})),
        lines=len(wide),
        lyrics_from=first_start,
    )


def _rgb(tracking: Tracking, time: float, index: int) -> Colour4:
    palette = tracking.palettes[0][1]
    for when, entries in tracking.palettes:
        if when > time:
            break
        palette = entries
    return palette[index]


def _use(tracking: Tracking, time: float, counter: Counter[int]) -> ColourUse | None:
    if not counter:
        return None
    index, count = counter.most_common(1)[0]
    return ColourUse(index, _rgb(tracking, time, index), count)


def _palette(tracking: Tracking, lyric_sessions: Sequence[Session], time: float) -> Palette:
    return Palette(
        background=_use(tracking, time, sum((s.backgrounds for s in lyric_sessions), Counter())),
        unsung=_use(tracking, time, sum((s.unsungs for s in lyric_sessions), Counter())),
        sung=_use(
            tracking,
            time,
            Counter(w.sung for s in lyric_sessions for w in s.wipes if w.sung is not None),
        ),
        edge=_use(tracking, time, sum((s.edges for s in lyric_sessions), Counter())),
    )


def _singers(tracking: Tracking, lyrics: Sequence[LineStats]) -> tuple[Singer, ...]:
    pairs: Counter[tuple[int, int, Colour4, Colour4]] = Counter(
        (
            line.unsung,
            line.sung,
            _rgb(tracking, line.first_wipe, line.unsung),
            _rgb(tracking, line.first_wipe, line.sung),
        )
        for line in lyrics
        if line.first_wipe is not None and line.unsung is not None and line.sung is not None
    )
    return tuple(
        Singer(ColourUse(u, urgb, n), ColourUse(s, srgb, n), n)
        for (u, s, urgb, srgb), n in pairs.most_common()
    )


def _redraw_delays(lyrics: Sequence[LineStats]) -> list[float]:
    delays: list[float] = []
    latest: dict[tuple[int, ...], LineStats] = {}
    for line in sorted(lyrics, key=lambda item: item.start):
        previous = latest.get(line.rows)
        if previous is not None and previous.last_wipe is not None:
            delays.append(line.start - previous.last_wipe)
        latest[line.rows] = line
    return delays


# ---------------------------------------------------------------------- gaps, countdowns


@dataclass(frozen=True, slots=True)
class _Tick:
    time: float
    first_column: int
    last_column: int
    rows: frozenset[int]
    draws: int
    erases: int
    recoloured: int = 0
    sessions: frozenset[int] = frozenset()

    @property
    def width(self) -> int:
        return self.last_column - self.first_column + 1


def _ticks(changes: Sequence[Change]) -> list[_Tick | None]:
    """Cluster changes in time; clusters wider than a countdown tick are ``None``."""
    clusters: list[list[Change]] = []
    for change in changes:
        if clusters and change.time - clusters[-1][-1].time <= TICK_CLUSTER_GAP:
            clusters[-1].append(change)
        else:
            clusters.append([change])
    ticks: list[_Tick | None] = []
    for cluster in clusters:
        columns = [c.column for c in cluster]
        if max(columns) - min(columns) + 1 > COUNTDOWN_MAX_COLUMNS:
            ticks.append(None)
            continue
        ticks.append(
            _Tick(
                cluster[0].time,
                min(columns),
                max(columns),
                frozenset(c.row for c in cluster),
                sum(c.ink for c in cluster),
                sum(not c.ink for c in cluster),
                0,
                frozenset(c.session for c in cluster),
            )
        )
    return ticks


def _extends(run: list[_Tick], tick: _Tick) -> bool:
    spacing = tick.time - run[-1].time
    if not TICK_MIN_SPACING <= spacing <= TICK_MAX_SPACING:
        return False
    near = (
        tick.first_column <= max(t.last_column for t in run) + COUNTDOWN_MAX_COLUMNS
        and tick.last_column >= min(t.first_column for t in run) - COUNTDOWN_MAX_COLUMNS
    )
    if len(run) < MIN_SPACINGS + 1:
        return near
    typical = median(b.time - a.time for a, b in zip(run, run[1:], strict=False))
    wide = median(t.width for t in run)
    return (
        near
        and abs(spacing - typical) <= TICK_SPACING_TOLERANCE * typical
        and abs(tick.width - wide) <= TICK_WIDTH_TOLERANCE
    )


def _best_run(ticks: Sequence[_Tick | None]) -> list[_Tick]:
    best: list[_Tick] = []
    run: list[_Tick] = []
    for tick in ticks:
        if tick is None:
            run = []
        elif run and _extends(run, tick):
            run.append(tick)
        else:
            run = [tick]
        if len(run) > len(best):
            best = list(run)
    return best if len(best) >= COUNTDOWN_MIN_TICKS else []


def _countdown(run: Sequence[_Tick], end: float) -> Countdown:
    return Countdown(
        ticks=len(run),
        interval=median(b.time - a.time for a, b in zip(run, run[1:], strict=False)),
        first_tick=run[0].time,
        length=end - run[0].time,
        before_wipe=end - run[-1].time,
        left_column=min(t.first_column for t in run),
        rows=tuple(sorted({row for t in run for row in t.rows})),
        draws=sum(t.draws for t in run),
        erases=sum(t.erases for t in run),
        recoloured=sum(t.recoloured for t in run),
        sessions=frozenset().union(*(t.sessions for t in run)),
    )


def find_countdown(changes: Sequence[Change], end: float) -> Countdown | None:
    """Find a series of small regular draws or erasures in ``changes`` that leads to ``end``."""
    run = _best_run(_ticks(changes))
    return _countdown(run, end) if run and end - run[-1].time <= COUNTDOWN_MAX_BEFORE_WIPE else None


def _pulses(wipes: Sequence[Wipe]) -> list[_Tick | None]:
    """Cluster wipe samples in time into ticks (``None`` for clusters wider than a tick)."""
    clusters: list[list[Wipe]] = []
    for wipe in wipes:
        if clusters and wipe.time - clusters[-1][-1].time <= TICK_CLUSTER_GAP:
            clusters[-1].append(wipe)
        else:
            clusters.append([wipe])
    ticks: list[_Tick | None] = []
    for cluster in clusters:
        columns = [(w.frontier - 1) // TILE_WIDTH for w in cluster]
        if max(columns) - min(columns) + 1 > COUNTDOWN_MAX_COLUMNS:
            ticks.append(None)
            continue
        ticks.append(
            _Tick(
                cluster[0].time,
                min(columns),
                max(columns),
                frozenset(w.row for w in cluster),
                0,
                0,
                len(cluster),
            )
        )
    return ticks


def wiped_countdown(wipes: Sequence[Wipe]) -> list[_Tick]:
    """Return the ticks if the wipe samples of a "line" are the blocks of a countdown, else [].

    They are when every sample belongs to one run of ticks (see the module docstring).
    """
    ticks = _pulses(wipes)
    run = _best_run(ticks)
    if not run or len(run) != len(ticks):
        return []
    apart = all(
        a.last_column + 1 < b.first_column or b.last_column + 1 < a.first_column
        for a, b in zip(run, run[1:], strict=False)
    )
    return run if apart else []


@dataclass(frozen=True, slots=True)
class _Fillers:
    """What fills the gaps besides drawn text: wiped countdown blocks and progress bars."""

    countdowns: Sequence[Sequence[_Tick]] = ()
    bars: Sequence[tuple[float, float]] = ()
    """The start and the running time of each progress bar."""


def _gap(
    span: tuple[str, float, float],
    tracking: Tracking,
    lyric_ids: set[int],
    break_seconds: float,
    fillers: _Fillers,
) -> Gap:
    kind, start, end = span
    middle = (start + end) / 2
    alive = [s for s in tracking.sessions if s.alive_at(middle)]
    sung = sorted({r for s in alive if s.id in lyric_ids for r in s.rows})
    other = sorted({r for s in alive if s.id not in lyric_ids for r in s.rows})
    changes = [c for c in tracking.changes if start < c.time < end and c.session not in lyric_ids]
    own = [
        run
        for run in fillers.countdowns
        if start <= run[0].time < end and end - run[-1].time <= COUNTDOWN_MAX_BEFORE_WIPE
    ]
    found = None if kind == "outro" else find_countdown(changes, end)
    if own:  # blocks highlighted one after the other: the earliest run of the gap
        found = _countdown(min(own, key=lambda run: run[0].time), end)
    return Gap(
        kind=kind,
        start=start,
        end=end,
        length=end - start,
        is_break=end - start >= break_seconds,
        sung_rows_at_middle=tuple(sung),
        other_rows_at_middle=tuple(other),
        other_changes=len(changes),
        countdown=found,
        bar=max((span for time, span in fillers.bars if start <= time < end), default=None),
    )


def _gaps(
    tracking: Tracking,
    lyrics: Sequence[LineStats],
    lyric_ids: set[int],
    duration: float,
    break_seconds: float,
    fillers: _Fillers,
) -> tuple[Gap, ...]:
    """Return the gaps between the wipes of ``lyrics`` (wiped lines in order of their first wipe).

    A gap starts when every wipe so far has ended, so a short line sung together with a longer
    one does not open a gap while the longer one is still being wiped.
    """
    if not lyrics:
        return ()
    spans: list[tuple[str, float, float]] = [("intro", 0.0, lyrics[0].first_wipe or 0.0)]
    wiped_until = lyrics[0].last_wipe or 0.0
    for line in lyrics[1:]:
        spans.append(("between", wiped_until, line.first_wipe or 0.0))
        wiped_until = max(wiped_until, line.last_wipe or 0.0)
    spans.append(("outro", wiped_until, duration))
    return tuple(
        _gap(span, tracking, lyric_ids, break_seconds, fillers)
        for span in spans
        if span[2] > span[1]
    )


def median_or_none(values: Iterable[float | None]) -> float | None:
    """Return the median of the values that are present, or ``None`` if there are none."""
    present = [value for value in values if value is not None]
    return median(present) if present else None


_Entry = tuple[LineStats, Sequence[Session]]


def _sung(entries: Sequence[_Entry]) -> tuple[list[_Entry], list[list[_Tick]]]:
    """Split the wiped lines into sung lines (in order of their first wipe) and countdown blocks.

    Lines whose highlight does not cross them (``crossed``) are neither.
    """
    candidates: list[tuple[list[_Tick], _Entry]] = []
    sung: list[_Entry] = []
    for line, group in entries:
        if line.first_wipe is None:
            continue
        samples = sorted((w for s in group for w in s.wipes), key=lambda w: w.time)
        if run := wiped_countdown(samples):
            candidates.append((run, (line, group)))
        elif crossed(line, samples):
            sung.append((line, group))
    firsts = [line.first_wipe or 0.0 for line, _ in sung]
    countdowns: list[list[_Tick]] = []
    for run, entry in candidates:  # blocks only count when a line follows soon after them
        after = [f - run[-1].time for f in firsts if f > run[-1].time]
        if after and min(after) <= COUNTDOWN_MAX_BEFORE_WIPE:
            countdowns.append(run)
        else:
            sung.append(entry)
    sung.sort(key=lambda entry: entry[0].first_wipe or 0.0)
    return sung, countdowns


def analyse(
    events: Sequence[CdgEvent], duration: float, break_seconds: float = BREAK_SECONDS
) -> Analysis:
    """Measure the presentation of one stream.

    Args:
        events: The events of ``vocatron.core.cdg.decode``.
        duration: The length of the song in seconds (the audio length; the stream length is
            used for the ending if it is longer).
        break_seconds: The gap length from which a gap counts as a break.

    Returns:
        The numbers; with no wiped line at all most of them are ``None`` or empty.
    """
    tracking = track(list(events))
    bars = {
        s.id: (s.wipes[0].time, span) for s in tracking.sessions if (span := progress_bar(s.wipes))
    }
    groups = group_lines([p for s in tracking.sessions if s.id not in bars for p in passes(s)])
    entries = [(line_stats(group), group) for group in groups]
    wiped_entries, countdowns = _sung(entries)
    lyrics = [line for line, _ in wiped_entries]
    lyric_ids = {s.id for _, group in wiped_entries for s in group if s.wipes}
    lyric_sessions = [s for s in tracking.sessions if s.id in lyric_ids]
    total = max([duration, *(e.time for e in events)])
    first_time = (lyrics[0].first_wipe or 0.0) if lyrics else 0.0
    visible = _lines_visible(lyrics)
    positions = Counter(line.rows for line in lyrics)
    fillers = _Fillers(countdowns, sorted(bars.values()))
    gaps = _gaps(tracking, lyrics, lyric_ids, total, break_seconds, fillers)
    counted = frozenset().union(*(g.countdown.sessions for g in gaps if g.countdown))
    static = [
        line
        for line, group in entries
        if line.first_wipe is None and not counted.intersection(s.id for s in group)
    ]
    methods = Counter(line.wipe_method for line in lyrics if line.wipe_method)
    kinds = Counter(line.end_kind for line in lyrics)
    return Analysis(
        duration=total,
        title=_title(static, min(line.start for line in lyrics), first_time) if lyrics else None,
        lines=tuple(lyrics),
        lines_per_screen=median_or_none([float(n) for n in visible]),
        lines_per_screen_max=max(visible, default=0),
        row_positions=tuple(positions.most_common()),
        alignment=_alignment(lyrics),
        lead_in=median_or_none(line.lead_in for line in lyrics),
        wipe_speed=median_or_none(line.wipe_speed for line in lyrics),
        wipe_step_px=median_or_none(line.wipe_step_px for line in lyrics),
        wipe_sample_px=median_or_none(line.wipe_sample_px for line in lyrics),
        wipe_methods=tuple(methods.most_common()),
        hold=median_or_none(line.hold for line in lyrics),
        end_kinds=tuple(kinds.most_common()),
        redraw_delay=median_or_none(_redraw_delays(lyrics)),
        gaps=gaps,
        palette=_palette(tracking, lyric_sessions, first_time),
        singers=_singers(tracking, lyrics),
        presets=len(tracking.presets),
        scrolls=len(tracking.scrolls),
        ending=(total - max(line.last_wipe or 0.0 for line in lyrics)) if lyrics else None,
        rows_at_end=tuple(sorted({r for s in tracking.sessions if s.end is None for r in s.rows})),
    )
