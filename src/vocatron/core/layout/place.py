"""Place: which slot a line goes to and when it appears and goes (rules 5, 6, 9, 10 and 11)."""

from collections.abc import Sequence
from dataclasses import dataclass

from vocatron.core.lyrics.document import FIRST_VOICE, SECOND_VOICE, Voice
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import Shortfall, rounded

TURNS = 2  # slots; up to this many the lines take turns, also the parts of a split line
PAIR_SLOTS = 2  # slots a pair of lines sung at once needs, side by side (ADR-0054)


@dataclass(frozen=True)
class Placement:
    """Where and when a line is on screen.

    Attributes:
        slot: The slot, counted from the top.
        show: When it appears.
        hide: When it goes.
        page: The page it belongs to in page mode, ``None`` in line mode.
    """

    slot: int
    show: float
    hide: float
    page: int | None = None


@dataclass(frozen=True)
class Times:
    """When a line is sung: its first syllable starts, its last one ends."""

    start: float
    end: float


@dataclass(frozen=True)
class Gap:
    """The silence before a line.

    Attributes:
        before: How long it is: from ``ended`` to the line's start (negative for an overlap),
            rounded to a thousandth like the scene, so a gap of exactly ``breaks.clear_after``
            is long whatever the rounding of the floats.
        ended: When the lines before it were last sung, ``0`` for the first line.
    """

    before: float
    ended: float


def gaps(times: Sequence[Times]) -> list[Gap]:
    """Return the silence before every line, counting from the start of the song for the first."""
    found: list[Gap] = []
    ended = 0.0
    for line in times:
        found.append(Gap(rounded(line.start - ended), ended))
        ended = max(ended, line.end)
    return found


type Run = tuple[int, ...]
"""Lines that take neighbouring slots, top to bottom (a pair, a split lyric line or one line)."""


def units(parts: Sequence[int], voices: Sequence[Voice] | None = None) -> list[Run]:
    """Return the lyric lines: the lines of one voice that a lyric line was split into, together.

    The lines of one voice never overlap, so the parts of a lyric line follow each other among the
    lines of their voice, with the other voice's lines in between when they are sung at once.

    Args:
        parts: For every line, which part of its lyric line it is (``Fitted.part``).
        voices: The voice of every line; ``None`` for lines of one voice.

    Returns:
        The indices of the lines of every lyric line, in sung order; lines that were not split are
        a unit of one.
    """
    found: list[list[int]] = []
    open_unit: dict[Voice, list[int]] = {}
    for index, part in enumerate(parts):
        voice = FIRST_VOICE if voices is None else voices[index]
        unit = open_unit.get(voice)
        if part and unit is not None and part == len(unit):
            unit.append(index)
        else:
            unit = [index]
            found.append(unit)
            open_unit[voice] = unit
    return [tuple(unit) for unit in found]


def pair_runs(
    times: Sequence[Times],
    voices: Sequence[Voice] | None,
    parts: Sequence[int],
    profile: Profile,
) -> list[Run]:
    """Return the lyric lines sung at once, each pair as its lines top to bottom (ADR-0054).

    Two lyric lines of different voices that follow each other in sung order and overlap in time
    form a pair, found from the start of the song on; a lyric line is in one pair at most. The
    first voice's lines stand above the second voice's, all rows of each in sung order, whichever
    voice starts first. A second-voice line that overlaps two first-voice lines is paired with the
    first of them, and the second one takes the next free slot. A pair is not formed when it needs
    more rows than the stack (or its blocks) has, or when a line of another lyric line is sung
    between its lines (a slot kept for a later row would starve it): its lines are shown as lines
    of their own.

    Args:
        times: When each line is sung, in sung order.
        voices: The voice of every line; ``None`` for lines of one voice.
        parts: For every line, which part of its lyric line it is (``Fitted.part``).
        profile: The profile; ``slots`` and ``block`` give the rows a pair can take.

    Returns:
        The pairs, each as the indices of its lines top to bottom.
    """
    if voices is None or profile.slots < PAIR_SLOTS:
        return []
    room = profile.slots // profile.block * profile.block
    lyric = units(parts, voices)
    ends = [max(times[i].end for i in unit) for unit in lyric]
    found: list[Run] = []
    paired = False  # the lyric line before is in a pair already
    for index in range(len(lyric) - 1):
        low, high = lyric[index], lyric[index + 1]
        different = {voices[low[0]], voices[high[0]]} == {FIRST_VOICE, SECOND_VOICE}
        overlap = times[low[0]].start < ends[index + 1] and times[high[0]].start < ends[index]
        rows = sorted((*low, *high))
        together = rows == list(range(rows[0], rows[-1] + 1))  # no line of another unit between
        if not paired and different and overlap and together and len(rows) <= room:
            first, second = (low, high) if voices[low[0]] == FIRST_VOICE else (high, low)
            found.append((*first, *second))
            paired = True
        else:
            paired = False
    return found


def stacked(members: Sequence[int], pair_of: dict[int, Run]) -> list[int]:
    """Return ``members`` (lines of a group in sung order) top to bottom.

    A pair stands as a whole where its first line (in sung order) is: the first voice above the
    second whichever of them is sung first (ADR-0054); the other lines keep their order.
    """
    order: list[int] = []
    for index in members:
        run = pair_of.get(index)
        if run is None:
            order.append(index)
        elif run[0] not in order:
            order += run
    return order


def _free_at(
    times: Sequence[Times],
    previous: int | None,
    current: int,
    profile: Profile,
    due: float | None = None,
) -> float:
    """Return when the slot of line ``previous`` may be reused by line ``current``.

    The line has to be sung to its end, and the slot is refilled ``replace_after`` seconds after
    the next line, the other line, has started to be sung (with one slot there is no other line).
    Waiting for the other line gives way to the minimum lead-in (rule 5): the slot is free
    ``lead_in.min`` before ``current`` starts if its line has been sung by then. The slot is free
    at the latest when ``current`` starts, but never while its line is still sung: two lines of
    different voices may be sung at once (ADR-0054).

    ``due`` is the time ``current`` has to be on screen by when that is not its own start: the
    start of the earlier of two lines sung at once that appear together (``due_times``).
    """
    if previous is None:
        return 0.0
    start = times[current].start if due is None else due
    free = times[previous].end
    if previous + 1 < current:
        turn = times[previous + 1].start + profile.clear.replace_after
        free = max(free, min(turn, start - profile.lead_in.min))
    return max(times[previous].end, min(free, start))


def hold_end(last: float, profile: Profile) -> float:
    """Return when the lyrics go after the last line, which stopped being sung at ``last``.

    That is ``clear.hold`` later, but when the look shows an end screen the hold gives way: the
    lyrics go at the latest when it starts, ``ending.start_after`` after ``last`` (rule 15,
    ADR-0037).
    """
    hold = profile.clear.hold
    if profile.ending.end_screen:
        hold = min(hold, profile.ending.start_after)
    return last + hold


def last_hold(times: Sequence[Times], profile: Profile) -> float:
    """Return when the lyrics go after the last line (``hold_end`` of the last singing end)."""
    return hold_end(max((line.end for line in times), default=0.0), profile)


def _clears(times: Sequence[Times], profile: Profile) -> list[float]:
    """Return for every line when the screen clears after it unless its slot is needed sooner.

    That is the ``clearing`` of the first long gap (``breaks.clear_after``) after the line, or
    ``last_hold`` after the last line when no long gap follows (rules 12 and 15).
    """
    silences = gaps(times)
    cleared = last_hold(times, profile)
    found = [0.0] * len(times)
    for index in reversed(range(len(times))):
        found[index] = cleared
        if silences[index].before >= profile.breaks.clear_after:
            cleared = clearing(silences[index].ended, times[index].start, profile)
    return found


def clearing(ended: float, start: float, profile: Profile) -> float:
    """Return when the screen is cleared in a long gap from ``ended`` to a line sung at ``start``.

    That is ``hold`` after the singing stopped at ``ended``, but the hold gives way to
    ``lead_in.min``: the screen is cleared in time for the line to appear ``lead_in.min`` before it
    is sung, and never before the singing stopped (rules 5, 9 and 22, ADR-0034).
    """
    return max(ended, min(ended + profile.clear.hold, start - profile.lead_in.min))


def lead_in_shortfalls(
    first_seen: Sequence[float], times: Sequence[Times], profile: Profile
) -> list[Shortfall]:
    """Report the lines that are first seen less than ``lead_in.min`` before they are sung.

    Both modes use this: a line is first seen when it appears, or earlier when a preview of it
    does, or when its page appears.

    Args:
        first_seen: For every line, when it is first on screen.
        times: When each line is sung.
        profile: The profile.
    """
    shortfalls: list[Shortfall] = []
    for index, (seen, line) in enumerate(zip(first_seen, times, strict=True)):
        if line.start - seen < profile.lead_in.min - 1e-9:
            message = (
                f"on screen {line.start - seen:.2f} s before it starts "
                f"(minimum {profile.lead_in.min} s)"
            )
            shortfalls.append(Shortfall(kind="lead-in", line=index, message=message))
    return shortfalls


def lyric_runs(parts: Sequence[int], voices: Sequence[Voice] | None, slots: int) -> dict[int, Run]:
    """Return for every part of a split lyric line the neighbouring slots it opens, top to bottom.

    A lyric line split into ``n`` lines takes ``n`` neighbouring slots when ``n`` fits the
    ``slots`` (``units``): its parts take them in order, each appearing when its own slot is
    free. A line split into more lines than there are slots takes a slot per part, as a line of
    its own does. With two slots or fewer the lines keep taking turns: two slots are always
    neighbours, and putting the first part on top would wait for the line sung just before it
    whenever that line is on top.

    Args:
        parts: For every line, which part of its lyric line it is (``Fitted.part``).
        voices: The voice of every line; ``None`` for lines of one voice.
        slots: How many slots there are.

    Returns:
        The run of every line that belongs to a split lyric line that has one.
    """
    if slots <= TURNS:
        return {}
    return {
        index: unit for unit in units(parts, voices) if 1 < len(unit) <= slots for index in unit
    }


def groups(
    times: Sequence[Times],
    parts: Sequence[int],
    profile: Profile,
    voices: Sequence[Voice] | None = None,
) -> list[int]:
    """Return for every line the group it belongs to, in the order the lines are sung (ADR-0038).

    A group holds up to ``profile.block`` lines and turns as a whole. The lines are counted in
    sung order: a group is full at ``block`` lines. A lyric line split into several lines
    (``parts``) is never put together with another lyric line: its parts form groups of their own
    (``block`` parts at most). Two lyric lines sung at once (``pair_runs``) are always in one
    group, whichever of their lines come first, and a pair of split lyric lines has the group to
    itself, which takes as many blocks as it has rows (ADR-0054). A pair of whole lines starts
    a new group when it does not fit the group before. After a gap where the screen is cleared
    (``breaks.clear_after``) the grouping starts again, so the last group before a gap may be
    short. The numbers grow with the first line of a group, so a line of a pair can have a lower
    number than the line before it.

    Args:
        times: When each line is sung.
        parts: For every line, which part of its lyric line it is (``Fitted.part``).
        profile: The profile; ``block`` is the size of a group.
        voices: The voice of every line; ``None`` for lines of one voice.

    Returns:
        The number of the group of every line, counted from 0 for the first.
    """
    silences = gaps(times)
    lyric = {index: unit for unit in units(parts, voices) for index in unit}
    pair_of = {index: run for run in pair_runs(times, voices, parts, profile) for index in run}
    joined: dict[Run, int] = {}  # the group of a pair that has started
    found: list[int] = []
    size = 0  # the lines in the current group, the last one started
    span = -1  # the lyric line the current group holds the parts of, -1 for a group of whole lines
    for index in range(len(times)):
        run = pair_of.get(index)
        if run is not None and run in joined:  # a later line of a pair: in the group of the first
            found.append(joined[run])
            continue
        split = len(lyric[index]) > 1
        wide = run is not None and len(run) > PAIR_SLOTS
        needs = 1 if run is None else len(run)  # the first of a pair brings the others
        mine = lyric[index][0] if split else -1
        belongs = size + needs <= profile.block and span == mine and not wide
        restart = index > 0 and silences[index].before >= profile.breaks.clear_after
        if index == 0 or restart or not belongs:
            found.append(max(found, default=-1) + 1)
            size = 0
        else:
            found.append(found[-1])
        size += needs
        span = -2 - index if wide else mine  # a wide pair keeps every other line out
        if run is not None:
            joined[run] = found[-1]
    return found


@dataclass(frozen=True)
class Choice:
    """The neighbouring slots a line takes: the run it opens and where it starts.

    Attributes:
        run: The lines that take neighbouring slots top to bottom, the line asked about among them.
        top: The slot of the first line of the run.
        slack: How late the slots free for the run's lines (``slack``); above 0 only for a run of
            one line, which takes the slot whose line ended first.
    """

    run: Run
    top: int
    slack: float


class Stack:
    """The choice of the slot of every line in line mode: single, in a split run or in a pair.

    A pair (``pair_runs``, ADR-0054) takes neighbouring slots, the first voice's lines above the
    second's, and a split lyric line neighbouring slots top to bottom (``lyric_runs``). The lines
    are asked in sung order; the first of a run to be asked takes the slots of all of them, which
    stay theirs until their lines are asked. A run whose slots are not all free as its lines
    start (``slack`` above 0) breaks up: a pair into its lyric lines, a lyric line into lines
    that each take the slot whose line ended first. The placement and the scene rules both use
    this class, so they judge the same choices.

    Attributes:
        times: When each line is sung.
        due: When every line has to be on screen by: its start, but for the first lines of two
            lyric lines sung at once, which appear together as the earlier one starts; the
            lines of a pair that broke up are due when they start.
    """

    def __init__(
        self,
        times: Sequence[Times],
        voices: Sequence[Voice] | None,
        parts: Sequence[int],
        profile: Profile,
    ) -> None:
        """Find the pairs and runs of the lines.

        Args:
            times: When each line is sung, in sung order.
            voices: The voice of every line; ``None`` for lines of one voice.
            parts: For every line, which part of its lyric line it is (``Fitted.part``).
            profile: The profile; ``slots`` and ``block`` give the room.
        """
        self.times = times
        self.due = [line.start for line in times]
        self._pairs = {i: run for run in pair_runs(times, voices, parts, profile) for i in run}
        self._runs = lyric_runs(parts, voices, profile.slots)
        self._heads = {unit[0] for unit in units(parts, voices)}
        for run in set(self._pairs.values()):
            self._due_together(run)
        self._broken: set[Run] = set()
        self._slot: dict[int, int] = {}
        self._waiting: set[int] = set()  # lines with a slot that have not been asked yet

    def _due_together(self, run: Run) -> None:
        """Make the first lines of the lyric lines of a pair due when the earlier of them starts."""
        heads = [i for i in run if i in self._heads]
        earliest = min(self.times[i].start for i in heads)
        for index in heads:
            self.due[index] = earliest

    def _masked(self, ended: Sequence[float]) -> list[float]:
        """Return ``ended`` with the slots kept for lines not yet asked about as never freeing."""
        held = {self._slot[i] for i in self._waiting}
        return [float("inf") if slot in held else end for slot, end in enumerate(ended)]

    def levels(self, index: int) -> list[Run]:
        """Return the runs line ``index`` may open, the widest first, ending in the line alone."""
        wider = (self._pairs.get(index), self._runs.get(index))
        return [*(r for r in wider if r is not None and r not in self._broken), (index,)]

    def planned(self, index: int) -> int | None:
        """Return the slot line ``index`` was given when a line of its run was asked, if it was."""
        return self._slot.get(index)

    def choose(self, index: int, ended: Sequence[float], eps: float = 0.0) -> Choice:
        """Return the run line ``index`` opens and the slots it takes, breaking up what is not free.

        Args:
            index: The line; none of its run was asked before.
            ended: When the line in every slot ended, -1 for an empty slot (``_slot_ends``).
            eps: How much a slot may be sung after its line starts and still count as free.
        """
        masked = self._masked(ended)
        for run in self.levels(index)[:-1]:  # the wider runs
            starts = [self.times[i].start for i in run]
            top = first_of_run(masked, starts)
            late = slack(masked, top, starts)
            if late <= eps:
                return Choice(run, top, late)
            self._broken.add(run)
            for line in run:
                self.due[line] = self.times[line].start
        start = [self.times[index].start]
        top = first_of_run(masked, start)
        return Choice((index,), top, slack(masked, top, start))

    def fits(self, choice: Choice, top: int, ended: Sequence[float], eps: float) -> bool:
        """Tell whether the run of ``choice`` at ``top`` is as good as its best slots."""
        masked = self._masked(ended)
        starts = [self.times[i].start for i in choice.run]
        inside = 0 <= top <= len(ended) - len(choice.run)
        return inside and slack(masked, top, starts) <= choice.slack + eps

    def commit(self, choice: Choice, top: int) -> None:
        """Give the lines of a run their slots from ``top`` on (the lines are asked one by one)."""
        for row, index in enumerate(choice.run):
            self._slot[index] = top + row
            self._waiting.add(index)

    def slot_of(self, index: int, ended: Sequence[float]) -> int:
        """Return the slot of line ``index`` (asked in order), given when each slot's line ended."""
        if index not in self._slot:
            choice = self.choose(index, ended)
            self.commit(choice, choice.top)
        self._waiting.discard(index)
        return self._slot[index]

    def asked(self, index: int) -> None:
        """Note that line ``index`` has been asked about: its slot is no longer kept for it."""
        self._waiting.discard(index)

    def reserved(self, index: int) -> bool:
        """Tell whether line ``index`` got its slot when an earlier line of its run was asked."""
        return index in self._waiting


def place(
    times: Sequence[Times],
    first_show: float,
    profile: Profile,
    parts: Sequence[int] | None = None,
    voices: Sequence[Voice] | None = None,
) -> list[Placement]:
    """Give every line a slot, an appearance time and a time to go.

    A line takes the slot whose line ended first and appears as early as the lead-in maximum
    allows once the slot is free, never before the line before it. The lines a lyric line was
    split into take neighbouring slots, top to bottom, so it reads in order: the ``n`` slots in a
    row that give its parts the longest shortest lead-in (``first_of_run``); each part appears
    when its own slot is free (``Stack``). A sung line stays until its slot is
    needed, so a gap shorter than ``breaks.clear_after`` keeps the screen (rule 11, which wins over
    rule 9 in line mode). When a long gap comes first, the line goes when the screen is cleared
    in that gap (``clearing``), or when its slot is needed if that is sooner (rule 12). A line
    whose slot is not needed again goes when the screen is cleared in the next long gap, or
    ``hold`` after the last line (rule 15).

    With ``profile.block`` above 1 the lines turn in blocks instead (``groups``, ADR-0038): a
    group of lines takes the block whose lines ended first, its lines appear together once the
    block is free, and the lines in the block before go at that moment. A group with fewer lines
    than its block sits next to the middle of the stack (``group_slots``, ADR-0039).

    Two lyric lines of different voices that are sung at once (``pair_runs``, ADR-0054) take
    neighbouring slots with all their rows, the first voice above the second, and their first
    rows are due as the earlier of them starts (``Stack.due``); a slot is never given to a line
    while its line is being sung, so a second-voice line that overlaps two first-voice lines keeps
    its slot until it ends, and the next first-voice line takes the next free slot. With blocks a
    pair belongs to one group, which takes as many blocks as it has rows.

    After a long gap the screen is clear: the slots have no memory of the lines before it, so the
    lines fill them from the top as at the start of the song, and none appears before the
    screen is cleared (``clearing``: ``hold`` after the singing stopped, but in time for
    ``lead_in.min``; rule 22, ADR-0034). Lines go in the order they were sung: none stays on
    screen after a line sung later has gone, and none goes before its own singing ends (rule 9).

    Args:
        times: When each line is sung, in the order of the lines.
        first_show: When the first line appears (after the title).
        profile: The profile.
        parts: For every line, which part of its lyric line it is (``Fitted.part``); ``None``
            for lines that were not split.
        voices: The voice of every line; ``None`` for lines of one voice.

    Returns:
        The placement of every line.
    """
    parts = [0] * len(times) if parts is None else parts
    if profile.block > 1 and times:
        return _place_blocks(times, first_show, profile, parts, voices)
    stack = Stack(times, voices, parts, profile)
    last_in_slot: list[int | None] = [None] * profile.slots
    shows: list[float] = []
    slots: list[int] = []
    hides = _clears(times, profile)  # a line whose slot is needed goes sooner, below
    silences = gaps(times)
    cleared = 0.0  # when the screen is empty after the last long gap
    for index, line in enumerate(times):
        long_gap = silences[index].before >= profile.breaks.clear_after
        if index and long_gap and not stack.reserved(index):
            cleared = clearing(silences[index].ended, line.start, profile)
            last_in_slot = [None] * profile.slots
        slot = stack.slot_of(index, _slot_ends(times, last_in_slot))
        # a line sung before it that appears later keeps it from appearing earlier: the order of
        # the lines on screen is the order they are sung
        due = max(stack.due[index], shows[-1] if shows else 0.0)
        show = min(first_show, due)
        if index:
            free = _free_at(times, last_in_slot[slot], index, profile, due)
            show = _show(free, max(cleared, shows[-1]), due, profile)
        _hand_over(hides, last_in_slot, slot, index, show)
        shows.append(show)
        slots.append(slot)
    hides = in_order(hides, [line.end for line in times])
    return [Placement(s, a, h) for s, a, h in zip(slots, shows, hides, strict=True)]


def _place_blocks(
    times: Sequence[Times],
    first_show: float,
    profile: Profile,
    parts: Sequence[int],
    voices: Sequence[Voice] | None = None,
) -> list[Placement]:
    """Place the lines of a look that turns in blocks (``block`` above 1, ADR-0038).

    The lines are grouped (``groups``); a group goes into the block whose lines ended first, its
    lines take the block's slots in sung order (``group_slots``: a short group sits next to the
    middle of the stack) and appear together, once the block is free
    (``_free_at`` after the last line in the block, and after all its lines are sung). The
    lines in the block go at that moment. ``lead_in.max`` counts before the first line of the
    group. After a long gap the blocks start again (rule 22). When every block still holds a line
    that is being sung as the group starts, the group falls back to turning line by line: each of
    its lines takes the slot whose line ended first, as with ``block: 1``; the blocks go on
    afterwards (``falls_back``). A group also falls back when its best block frees less than
    ``lead_in.min`` before it starts while a line of the other voice is still sung then
    (``kept_lead_in``, ADR-0054). The rows of a group of several blocks count as ended block by
    block then (``_slot_ends`` with ``block``), so a line may take a sung row of such a group
    while the group's row in the other block is still sung.
    """
    numbers = groups(times, parts, profile, voices)
    pair_of = {i: run for run in pair_runs(times, voices, parts, profile) for i in run}
    members: list[list[int]] = [[] for _ in range(numbers[-1] + 1)]
    for index, number in enumerate(numbers):
        members[number].append(index)
    block = profile.block
    last_in_slot: list[int | None] = [None] * profile.slots  # the line in each slot
    shows = [0.0] * len(times)
    slots = [0] * len(times)
    hides = _clears(times, profile)  # a line whose slot is needed goes sooner, below
    silences = gaps(times)
    ends = [line.end for line in times]
    cleared = 0.0  # when the screen is empty after the last long gap
    latest = 0.0  # when the line before appeared
    wide: dict[int, list[int]] = {}  # the lines of a group that takes several blocks, by line
    for group in members:
        first = group[0]
        if first and silences[first].before >= profile.breaks.clear_after:
            cleared = clearing(silences[first].ended, times[first].start, profile)
            last_in_slot = [None] * profile.slots
        ended = _slot_ends(times, last_in_slot, wide)
        span = -(-len(group) // block)  # the blocks a pair of many rows takes
        start = times[first].start
        waits = kept_lead_in(ends, voices, first, start, profile.lead_in.min)
        if falls_back(ended, block, start, span, waits):
            for index in group:
                ended = _slot_ends(times, last_in_slot, wide, block)
                slot = first_of_run(ended, [times[index].start])
                floor = max(cleared, latest)
                latest = _line_show(times, index, last_in_slot[slot], floor, profile)
                _hand_over(hides, last_in_slot, slot, index, latest)
                shows[index], slots[index] = latest, slot
            continue
        top = first_of_run(block_ends(ended, block), [times[first].start] * span)
        before = [i for i in last_in_slot[block * top : block * (top + span)] if i is not None]
        before = list(dict.fromkeys([*before, *(m for i in before for m in wide.get(i, ()))]))
        # (a group of several blocks goes as a whole)
        last_in_slot = [None if i in before else i for i in last_in_slot]
        free = 0.0
        if before:  # the block's lines are sung, and its last line's slot is free
            free = max(
                _free_at(times, max(before), first, profile), *(times[i].end for i in before)
            )
        show = (
            min(first_show, start)
            if first == 0
            else _show(free, max(cleared, latest), start, profile)
        )
        for index in before:
            hides[index] = min(hides[index], show)
        where = group_slots(top, len(group), profile)
        rows = stacked(group, pair_of)
        for row, index in enumerate(rows):
            shows[index], slots[index] = show, where[row]
            last_in_slot[where[row]] = index
        if span > 1:
            wide.update({index: group for index in group})
        latest = show
    hides = in_order(hides, [line.end for line in times])
    return [Placement(s, a, h) for s, a, h in zip(slots, shows, hides, strict=True)]


def group_slots(block: int, size: int, profile: Profile) -> list[int]:
    """Return the slots a group of ``size`` rows takes from block number ``block`` (ADR-0039).

    The rows go top to bottom in sung order. A full group fills the block. A shorter group sits
    next to the middle of the stack: a block that lies wholly in the upper half of the slots
    fills from its bottom slot up, every other block from its top slot down, so no empty row
    stays between the group and the lines of the other block.

    Args:
        block: The block number, counted from the top, 0 for the first.
        size: How many rows the group has: at most ``profile.block``, or more for a pair of lyric
            lines that takes several blocks (ADR-0054), which then counts as one larger block.
        profile: The profile; ``block`` and ``slots`` give the layout.
    """
    span = -(-size // profile.block)  # the blocks the group takes
    top = block * profile.block
    upper = 2 * (block + span) * profile.block <= profile.slots
    offset = span * profile.block - size if upper else 0
    return [top + offset + row for row in range(size)]


def _slot_ends(
    times: Sequence[Times],
    last_in_slot: Sequence[int | None],
    wide: dict[int, list[int]] | None = None,
    block: int = 0,
) -> list[float]:
    """Return when the line in every slot ends, -1 for an empty slot (``first_of_run``).

    A line of a group that takes several blocks (``wide``: its lines by line) counts as ended when
    the whole group is sung, as the group goes as a whole (ADR-0054). With ``block`` above 0 (a
    group that turns line by line, ``falls_back``) it counts as ended when the group's lines in
    its own block are sung instead, so a block of it whose rows are sung frees for the lines that
    come while its other block is still sung, top slot first; a line still goes into such a slot
    only after the line in it is sung (``_free_at``).
    """
    group = wide or {}
    found: list[float] = []
    for slot, line in enumerate(last_in_slot):
        if line is None:
            found.append(-1.0)
            continue
        mates = group.get(line, [line])
        if block:
            top = slot // block * block
            mates = [m for m in last_in_slot[top : top + block] if m in mates]
        found.append(max(times[m].end for m in mates))
    return found


def block_ends(ended: Sequence[float], block: int) -> list[float]:
    """Return for every block when its lines are sung, from ``ended`` by slot (-1 when empty)."""
    return [max(ended[top : top + block]) for top in range(0, len(ended), block)]


def kept_lead_in(
    ends: Sequence[float],
    voices: Sequence[Voice] | None,
    first: int,
    start: float,
    minimum: float,
) -> float:
    """Return the lead-in the block of a group may not cut (``falls_back``, ADR-0054).

    That is ``minimum`` when a line sung before the group, in the other voice than the group's
    first line ``first``, is still sung ``minimum`` before ``start``, and 0 otherwise: in a song
    of one voice (``voices`` None or no line of another voice) a group always waits for its
    block (ADR-0038).

    Args:
        ends: When every line (every row) is sung to its end, in sung order.
        voices: The voice of every line, or ``None`` for a song of one voice.
        first: The index of the group's first line.
        start: When the group starts.
        minimum: The minimum lead-in (``lead_in.min``).
    """
    if voices is None:
        return 0.0
    since = start - minimum
    sung = any(voices[i] != voices[first] and ends[i] > since for i in range(first))
    return minimum if sung else 0.0


def falls_back(
    ended: Sequence[float], block: int, start: float, span: int = 1, lead_in: float = 0.0
) -> bool:
    """Tell whether a group sung from ``start`` turns line by line (ADR-0038, ADR-0054).

    ``ended`` holds when the line in every slot ends (-1 for an empty slot). A block is free once
    all its lines are sung. The group falls back when every ``span`` neighbouring blocks (the
    blocks a group of many rows takes) still hold a line sung at ``start``: its lines take the
    slots whose lines ended first, one by one, as with ``block: 1``. It also falls back when the
    best blocks free less than ``lead_in`` before ``start`` and another block is left to turn
    in: callers pass the minimum lead-in while a line of the other voice is still sung then
    (``kept_lead_in``), and 0 otherwise, so only the first reason counts in a song of one voice.
    """
    free = block_ends(ended, block)
    tops = range(len(free) - span + 1)
    late = {top: slack(free, top, [start] * span) for top in tops}
    best = min(tops, key=lambda top: (late[top], top))
    if late[best] > 0:
        return True
    own = free[best : best + span]
    return lead_in > 0 and max(own) > start - lead_in and span < len(free)


def _line_show(
    times: Sequence[Times], index: int, previous: int | None, floor: float, profile: Profile
) -> float:
    """Return when line ``index`` appears in the slot of line ``previous`` (``_free_at``)."""
    return _show(_free_at(times, previous, index, profile), floor, times[index].start, profile)


def _hand_over(
    hides: list[float], last_in_slot: list[int | None], slot: int, index: int, show: float
) -> None:
    """Put line ``index`` into ``slot`` at ``show``: the line in it before goes at that moment."""
    previous = last_in_slot[slot]
    if previous is not None:
        hides[previous] = min(hides[previous], show)
    last_in_slot[slot] = index


def _show(free: float, floor: float, start: float, profile: Profile) -> float:
    """Return when a line (or group) sung from ``start`` appears (rule 5).

    Once its slot is ``free``, not before ``floor`` (the screen cleared, the line before shown)
    and not more than ``lead_in.max`` ahead, but at the latest when it starts, and never before
    its slot is free: a slot whose line is still sung is not given away (ADR-0054).
    """
    return max(free, min(max(floor, start - profile.lead_in.max), start))


def in_order(hides: Sequence[float], ends: Sequence[float]) -> list[float]:
    """Let the lines go in the order they were sung, none before its own singing ends.

    A line goes when it would, but never after a line sung later has gone, and never before its
    own end (rule 9, ADR-0034).

    Args:
        hides: When every line would go.
        ends: When every line is sung to its end.
    """
    found = list(hides)
    latest = float("inf")  # the earliest time a later line goes
    for index in reversed(range(len(found))):
        found[index] = max(ends[index], min(found[index], latest))
        latest = min(latest, found[index])
    return found


def first_of_run(ended: Sequence[float], starts: Sequence[float]) -> int:
    """Return the top slot of the neighbouring slots that give the parts of a line the most time.

    ``ended`` holds when the last line of every slot ended, ``starts`` when each part of the line
    starts; part ``k`` goes into slot ``top + k``. A run counts by the part whose slot frees
    latest before it starts (``ended - start`` largest), so the run with the longest shortest
    lead-in wins, the first from the top on a tie. For one part that is the slot whose line ended
    first.
    """
    count = len(starts)
    return min(range(len(ended) - count + 1), key=lambda top: (slack(ended, top, starts), top))


def slack(ended: Sequence[float], top: int, starts: Sequence[float]) -> float:
    """Return how late the slots from ``top`` down free for parts starting at ``starts``.

    That is the largest ``end - start`` of the last line of slot ``top + k`` and part ``k``;
    above 0, a slot still holds a line that is sung as its part starts.
    """
    free = ended[top : top + len(starts)]
    return max(end - start for end, start in zip(free, starts, strict=True))
