"""Scroll mode: the column of lyrics stands still while a line is sung and glides in between.

The column holds one entry per line. At a stop its entry is centred at the height
``scroll.current``; the stop before it and the next one are above and below. Between two stops
the whole column glides up by the distance of their centres, over ``scroll.glide`` seconds, in the
silence between the two lines (ADR-0033). Where the silence leaves less than ``scroll.min_glide``
the glide starts earlier, during the end of the line that is finishing, but never before the
column has come to rest at the stop before (ADR-0036); a line that is about to be sung never
moves.

A long break is the end of a part: the song is a row of parts, cut at every gap of
``breaks.notice_after`` seconds or more that leaves room for the break screen. The lines of a part
are gone when the other modes clear the screen (``clearing``: ``clear.hold`` after the singing
stops, or sooner for the next line's lead-in), the break screen stands alone, and the next part
starts as the song does, gliding in from below (ADR-0040). This module decides when the glides
happen and where every entry is at every stop; ``build`` draws the lines, the break screens and
the countdowns at those places.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from vocatron.core.layout.cards import BEAT_SLACK, CountdownWindow, countdown_window
from vocatron.core.layout.place import Gap, Times, clearing, gaps, last_hold
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import Keyframe, rounded

SETTLE = 0.1  # seconds the column is at rest before the line is sung, where the gap is long
MIN_NOTICE = 1.0  # seconds the break screen stands alone at least, or there is none
LINE_GAP = 0.3  # between two entries of the column, of the font size
FIT_SLACK = 1e-3  # pixels of tolerance when a row is said to lie inside the safe area


@dataclass(frozen=True)
class Stop:
    """A place the column stands still at: the glide into it, then the rest until the next glide.

    Attributes:
        line: The index of the line (in the order they are sung) it is; the stops are the lines.
        glide_start: When the column starts to glide into this stop.
        glide_end: When it stands still there.
    """

    line: int
    glide_start: float
    glide_end: float

    @property
    def glide(self) -> float:
        """How long the glide into the stop takes."""
        return self.glide_end - self.glide_start


@dataclass(frozen=True)
class Part:
    """The stops between two long breaks; the column starts again at its first stop.

    Attributes:
        first: The first stop (line) of the part.
        last: The last stop of the part.
        leave: When its lines are gone and the break screen starts: when the screen is cleared
            (``clearing``). ``None`` for the last part, which stays until ``Plan.final``.
    """

    first: int
    last: int
    leave: float | None


@dataclass(frozen=True)
class Plan:
    """When the column glides, and the countdowns that fit.

    Attributes:
        stops: Every stop in order, one per line.
        parts: The parts of the song, in order.
        countdowns: The countdown before a line, by the index of the line.
        final: When the last stop ends and everything goes.
    """

    stops: list[Stop]
    parts: list[Part]
    countdowns: dict[int, CountdownWindow]
    final: float

    def part_of(self, stop: int) -> Part:
        """Return the part that stop ``stop`` belongs to."""
        return next(p for p in self.parts if p.first <= stop <= p.last)


def _countdown_window(
    index: int, floor: float, ctx: tuple[Profile, float | None, Sequence[Times], Sequence[Gap]]
) -> CountdownWindow | None:
    """Return the countdown before line ``index`` if its gap asks for one and there is room."""
    profile, bpm, times, silences = ctx
    if silences[index].before < profile.countdown.min_gap:
        return None
    return countdown_window(profile.countdown, bpm, times[index].start, floor)


def _arrive(
    index: int,
    earliest: float,
    latest: float,
    title_end: float,
    rest: float,
    ctx: tuple[Profile, float | None, Sequence[Times], Sequence[Gap]],
) -> tuple[float, float, CountdownWindow | None]:
    """Return when the column glides into line ``index`` and its countdown.

    The glide ends where the countdown starts, or ``SETTLE`` before the line is sung. It is
    ``scroll.glide`` long where the silence from ``earliest`` allows it, else as long as the
    silence but at least ``scroll.min_glide``: it then starts before ``earliest``, during the end
    of the line before, though never before ``rest`` (when the column came to rest at the stop
    before, or the line before is first sung), where it may stay shorter (ADR-0036). A countdown
    that would start after ``latest`` (when the wipe starts) is left out.

    Returns:
        When the glide starts, when it ends, and the countdown or ``None``.
    """
    profile = ctx[0]
    glide = profile.scroll.glide
    window = _countdown_window(index, max(title_end, earliest + glide), ctx)
    if window is not None and window.start <= latest + BEAT_SLACK:
        return window.start - glide, window.start, window
    end = max(latest - SETTLE, earliest)
    length = max(
        min(glide, end - earliest), min(profile.scroll.shortest_glide, max(end - rest, 0.0))
    )
    return end - length, end, None


def _room(prev_end: float, start: float, shift: float) -> tuple[float, float]:
    """Return when the column may glide between two lines: from, until.

    That is after the wipe of the line before ends and before the wipe of the next starts; without
    room for the shifted wipes, between the two lines themselves (a wipe is then cut by the glide).
    """
    after, before = prev_end + max(shift, 0.0), start + min(shift, 0.0)
    if before < after:
        after, before = prev_end, start
    return after, max(before, after)


def plan_stops(
    times: Sequence[Times],
    profile: Profile,
    bpm: float | None,
    first_show: float,
    title_end: float,
) -> Plan:
    """Decide the parts of the column, the stops, the glides between them and the countdowns.

    The column glides in from below at ``first_show`` (the end of the title screen). A line then
    gets its glide as late as the countdown allows, and at least ``scroll.min_glide`` long
    (``_arrive``). Before a gap of ``breaks.notice_after`` seconds a part ends: its lines go
    ``clear.hold`` after the singing stops (``clearing``), and the next part starts like the song
    does, with its first line gliding in from below and its countdown when the column rests, if
    the break screen can stand alone for ``MIN_NOTICE`` seconds before that glide (ADR-0040).

    Args:
        times: When each line is sung, in order.
        profile: The profile (``scroll``, ``breaks``, ``countdown``, ``clear``, ``wipe``).
        bpm: The tempo the countdowns count, or ``None``.
        first_show: When the first glide starts: the title screen ends.
        title_end: When the title screen ends, 0 for none.
    """
    shift, glide = profile.wipe.offset, profile.scroll.glide
    silences = gaps(times)
    ctx = (profile, bpm, times, silences)
    stops: list[Stop] = []
    parts: list[Part] = []
    countdowns: dict[int, CountdownWindow] = {}
    first = 0
    for index, line in enumerate(times):
        if index == 0:
            latest = max(line.start + min(shift, 0.0), first_show)
            end = first_show + min(glide, latest - first_show)
            window = _countdown_window(0, max(title_end, end), ctx)  # starts when the column rests
            stops.append(Stop(0, first_show, end))
        else:
            earliest, latest = _room(silences[index].ended, line.start, shift)
            rest = max(stops[-1].glide_end, times[index - 1].start)  # and the line before is sung
            arrival = _arrive(index, earliest, latest, title_end, rest, ctx)
            if silences[index].before >= profile.breaks.notice_after:
                on = max(clearing(silences[index].ended, line.start, profile), earliest)
                sooner = on + MIN_NOTICE
                later = _arrive(index, sooner, latest, title_end, sooner, ctx)
                # _arrive never starts the glide before ``sooner`` nor ends it after ``latest``;
                # without room it shortens the glide, and a part needs a whole glide in
                if later[1] - later[0] >= glide - BEAT_SLACK:
                    parts.append(Part(first, index - 1, rounded(on)))
                    first = index
                    arrival = later
            stops.append(Stop(index, rounded(arrival[0]), rounded(arrival[1])))
            window = arrival[2]
        if window is not None:
            countdowns[index] = window
    parts.append(Part(first, len(times) - 1, None))
    return Plan(stops, parts, countdowns, last_hold(times, profile))


@dataclass(frozen=True)
class Column:
    """The entries of the column, one per stop, with their sizes.

    Attributes:
        heights: The height of every entry (a line with all its rows).
        gaps: The room between an entry and the one before it; an entry with a countdown above
            it has the room of the countdown too. The first of a part has the room the column
            comes in over, from below.
        starts: The stops that start a part (the first stop is one).
    """

    heights: list[float]
    gaps: list[float]
    starts: frozenset[int] = frozenset({0})

    def centres(self) -> list[float]:
        """Return the height of the middle of every entry in a column that starts at 0."""
        found: list[float] = []
        top = 0.0
        for index, (height, gap) in enumerate(zip(self.heights, self.gaps, strict=True)):
            top += gap if index else 0.0
            found.append(top + height / 2)
            top += height
        return found

    def steps(self) -> list[float]:
        """Return how far the column glides into every stop: the distance of the middles.

        The first stop of a part is glided into from below by its own height and the room around
        it, like the first stop of the song.
        """
        centres = self.centres()
        return [
            self.heights[i] + self.gaps[i] if i in self.starts else centres[i] - centres[i - 1]
            for i in range(len(centres))
        ]


@dataclass(frozen=True)
class View:
    """What the viewer sees: where the current entry stands and how far the window reaches.

    Attributes:
        current: The height of the middle of the current entry, pixels from the top of the frame.
        top: The top of the safe area.
        bottom: The bottom of the safe area.
        before: The sung lines kept above at most.
        after: The upcoming lines below at most.
    """

    current: float
    top: float
    bottom: float
    before: int
    after: int


def _shown(entry: int, stop: int, column: Column, centres: list[float], view: View) -> bool:
    """Tell whether entry ``entry`` (a line) is on screen at the stop ``stop``.

    It must be among the ``before`` entries above and the ``after`` entries below the stop, and
    lie inside the safe area there.
    """
    height = column.heights[entry]
    top = view.current + centres[entry] - centres[stop] - height / 2
    return (
        stop - view.before <= entry <= stop + view.after
        and top >= view.top - FIT_SLACK
        and top + height <= view.bottom + FIT_SLACK
    )


def visible_stops(
    entry: int, column: Column, centres: list[float], view: View, part: Part
) -> tuple[int, int]:
    """Return the first and the last stop at which entry ``entry`` is on screen.

    The stops are consecutive and include the entry's own, where it is sung, and stay within its
    part ``part``: the column of the part before a long break is gone when the next one starts.
    """
    low = high = entry
    while low > part.first and _shown(entry, low - 1, column, centres, view):
        low -= 1
    while high < part.last and _shown(entry, high + 1, column, centres, view):
        high += 1
    return low, high


def path_of(  # the entry, where it is shown, when the column glides and where it rests
    entry: int, run: tuple[int, int], plan: Plan, centres: list[float], steps: list[float]
) -> list[Keyframe]:
    """Return the path of entry ``entry`` (a line), which is on screen at ``run``.

    The keyframes give the offset from where the entry stands at its own stop, in pixels (to be
    added to the anchor of what is drawn: the ``text_y`` of a row). It comes in during the glide
    into the first stop of the run, moving up from one step below, rests, glides up with the
    column and leaves during the glide out of the last stop of the run, moving up one step
    further. At the last stop of a part it stays until the part's ``leave`` (the lines fade out
    before the break screen, ADR-0040), at the last stop of the song until ``Plan.final``.
    """
    low, high = run
    stops = plan.stops

    def at(stop: int) -> float:
        return centres[entry] - centres[stop]

    def key(time: float, offset: float) -> Keyframe:
        return Keyframe(time=rounded(time), y=rounded(offset))

    frames = [key(stops[low].glide_start, at(low) + steps[low]), key(stops[low].glide_end, at(low))]
    for stop in range(low, high):
        following = stops[stop + 1]
        frames += [key(following.glide_start, at(stop)), key(following.glide_end, at(stop + 1))]
    part = plan.part_of(high)
    if high < part.last:
        leaving = stops[high + 1]
        frames += [
            key(leaving.glide_start, at(high)),
            key(leaving.glide_end, at(high) - steps[high + 1]),
        ]
    else:
        frames.append(key(plan.final if part.leave is None else part.leave, at(high)))
    return [f for i, f in enumerate(frames) if not (i and f == frames[i - 1])]
