"""Pages: page mode cuts the lines into pages and times them (rules 5, 9, 10 and 11)."""

import math
from collections.abc import Sequence
from itertools import accumulate

from vocatron.core.layout.place import Placement, Times, gaps, in_order, last_hold
from vocatron.core.profiles.model import Profile

type Cost = tuple[int, int, float, tuple[int, ...]]
"""What a way of cutting a run costs, compared as a tuple: pages, pages with fewer lines than
``page.min_lines``, minus the shortest silence at a cut, and the cuts (an earlier cut wins)."""


def _fewest_pages(
    marks: Sequence[int], slots: int, low: int, rows: Sequence[int]
) -> tuple[int, int, tuple[int, ...]] | None:
    """Cut at some of ``marks`` (the run's first line, the allowed cuts, its end) into pages.

    A page holds at most ``slots`` rows: ``rows[i]`` is how many slots line ``i`` takes.

    Returns:
        The fewest pages, then the fewest pages with fewer than ``low`` lines, then the earliest
        cuts, as ``(pages, small pages, cuts)``; ``None`` if no cut makes pages of ``slots``.
    """
    first = marks[0]
    before = [0, *accumulate(rows)]  # the rows of the lines before line ``i``
    best: dict[int, tuple[int, int, tuple[int, ...]]] = {first: (0, 0, ())}
    for number, mark in enumerate(marks[1:], start=1):
        # the marks are distinct and rising and a line takes a row at least, so only the ``slots``
        # marks before can start a page
        window = marks[max(0, number - slots) : number]
        options = [
            (pages + 1, small + (mark - start < low), cuts if start == first else (*cuts, start))
            for start in window
            if start in best and before[mark] - before[start] <= slots
            for pages, small, cuts in [best[start]]
        ]
        if options:
            best[mark] = min(options)
    return best.get(marks[-1])


def _cut_run(
    first: int, end: int, before: Sequence[float], profile: Profile, rows: Sequence[int]
) -> list[tuple[int, int]]:
    """Cut the lines ``first`` to ``end`` (between two long gaps) into pages.

    The fewest pages come first, then as many pages of at least ``page.min_lines`` lines as the
    run allows, then the longest shortest silence at a cut, then the earlier cut. The shortest
    silence is a bottleneck, so each silence is tried as the floor of the cuts allowed, and the
    best of those cuttings wins.
    """
    allowed = [c for c in range(first + 1, end) if before[c] >= 0]
    found: list[Cost] = []
    for floor in [math.inf, *sorted({before[c] for c in allowed}, reverse=True)]:
        marks = [first, *(c for c in allowed if before[c] >= floor), end]
        result = _fewest_pages(marks, profile.slots, profile.page.min_lines, rows)
        if result is not None:
            pages, small, cuts = result
            worst = min((before[c] for c in cuts), default=math.inf)
            found.append((pages, small, -worst, cuts))
    if not found:
        unit = "rows" if profile.page.slot_per_row else "lines"
        raise ValueError(f"lines {first} to {end - 1} do not fit pages of {profile.slots} {unit}")
    bounds = [first, *min(found)[3], end]
    return list(zip(bounds, bounds[1:], strict=False))


def cut_pages(
    times: Sequence[Times], profile: Profile, rows: Sequence[int] | None = None
) -> list[tuple[int, int]]:
    """Cut the lines into pages: every long gap ends a page, long runs are cut at the pauses.

    A cut is only allowed where all lines before it have been sung. A run between long gaps
    gets the fewest pages, then as many pages of ``page.min_lines`` to ``slots`` lines as it
    allows, then the longest shortest silence at a cut, then the earlier cut.

    Args:
        times: When each line is sung, in order.
        profile: The profile (``slots``, ``page.min_lines``, ``breaks.clear_after``).
        rows: How many slots every line takes (two for a line wrapped onto two rows with
            ``page.slot_per_row``); ``None`` for one each. A page never holds more than ``slots``
            rows, and a line that would not fit in the rows left starts the next page.

    Returns:
        The pages as ranges ``(first, end)`` of line indexes.

    Raises:
        ValueError: If a stretch of overlapping lines is longer than ``slots``; the layout
            requires lines that do not overlap in time (ADR-0018).
    """
    rows = [1] * len(times) if rows is None else rows
    before = [silence.before for silence in gaps(times)]
    starts = [0, *(i for i in range(1, len(times)) if before[i] >= profile.breaks.clear_after)]
    ends = [*starts[1:], len(times)]
    pages: list[tuple[int, int]] = []
    for first, end in zip(starts, ends, strict=True):
        pages += _cut_run(first, end, before, profile, rows)
    return pages


def page_turn(sung: float, start: float, profile: Profile) -> float:
    """Return when the page with its first line at ``start`` appears, after a page sung to ``sung``.

    That is ``max(sung, min(sung + hold, start - lead_in.target))``, no sooner than
    ``lead_in.max`` before ``start`` and never after it: the hold gives way to the lead-in of the
    next page. The one rule of the whole-page turn, for the placement and for rule 9.
    """
    lead = profile.lead_in
    turn = max(sung, min(sung + profile.clear.hold, start - lead.target))
    return min(max(turn, start - lead.max), start)


def _slot_ranges(first: int, end: int, profile: Profile, rows: Sequence[int]) -> list[range]:
    """Return the slots every line of the page ``first`` to ``end`` takes (the page is centred)."""
    top = (profile.slots - sum(rows[first:end])) // 2
    return [
        range(top + sum(rows[first:i]), top + sum(rows[first : i + 1])) for i in range(first, end)
    ]


def _overlap(one: range, other: range) -> bool:
    """Tell whether two ranges of slots share a slot."""
    return one.start < other.stop and other.start < one.stop


def _turn_by_line(
    times: Sequence[Times],
    pages: Sequence[tuple[int, int]],
    profile: Profile,
    rows: Sequence[int],
    whole: tuple[list[float], list[float]],
) -> tuple[list[float], list[float]]:
    """Return the shows and hides of every line when pages turn line by line (``page.turn: line``).

    ``whole`` holds the shows and hides of every line as the whole-page turn has them. Inside a
    run (no long gap before the page) the line of the new page for a slot appears once the old
    page's lines in that slot have been sung and ``clear.replace_after`` has passed, giving way to
    ``lead_in.min`` as a slot in line mode does, never after its own first syllable and not before
    the line above it appeared. The first line appears no more than ``lead_in.max`` ahead. A slot
    the old page did not use is freed when the old page's first line has been sung. An old line goes
    when the first new line that takes a slot of it appears, or, if no line does, at the whole-page
    turn but not before the first line of the new page appears (the screen is never empty); lines
    go in the order they were sung.
    """
    lead, ra = profile.lead_in, profile.clear.replace_after
    shows, hides = list(whole[0]), list(whole[1])
    before = [silence.before for silence in gaps(times)]
    ranges = {
        i: slots
        for (first, end) in pages
        for i, slots in zip(range(first, end), _slot_ranges(first, end, profile, rows), strict=True)
    }
    for (old_first, old_end), (first, end) in zip(pages, pages[1:], strict=False):
        if before[first] >= profile.breaks.clear_after:
            continue  # after a long gap the whole page turns
        old = range(old_first, old_end)
        for i in range(first, end):
            start = times[i].start
            sung = [times[j].end for j in old if _overlap(ranges[i], ranges[j])]
            gate = max(sung, default=times[old_first].end)
            free = min(max(gate, min(gate + ra, start - lead.min)), start)
            if i == first:
                free = min(max(free, start - lead.max), start)
            shows[i] = max(free, shows[i - 1])  # a page is never the first, so ``i`` is at least 1
        for j in old:
            replaced = [shows[i] for i in range(first, end) if _overlap(ranges[i], ranges[j])]
            hides[j] = min(replaced, default=max(hides[j], shows[first]))
    return shows, in_order(hides, [t.end for t in times])


def place_pages(
    times: Sequence[Times],
    first_show: float,
    profile: Profile,
    rows: Sequence[int] | None = None,
) -> list[Placement]:
    """Give every line a slot, an appearance time and a time to go, a page at a time.

    A page of ``k`` rows fills the slots ``o`` to ``o + k - 1`` with ``o = (slots - k) // 2``, so
    a short page sits as near the middle of the block as whole slots allow; a line of two rows
    (``rows``) takes two neighbouring slots and is placed at the first. The first page appears
    at ``first_show``. The page after a page sung to ``e``, whose first line starts at ``s``,
    appears at ``page_turn(e, s)`` (``max(e, min(e + hold, s - lead_in.target))``, never after
    ``s``: the hold gives way to the lead-in of the next page). The page before it goes then, so
    the screen is never empty in a gap shorter than ``breaks.clear_after``; before a long gap it
    goes when the hold is over if that is sooner. The last page goes ``last_hold`` after the last
    line (the hold gives way to the end screen).
    Every line of a page appears and goes with its page, unless the profile turns line by line
    (``page.turn: line``, ADR-0041): inside a run of lines the next page then builds from the top
    while the old one is still sung (``_turn_by_line``); after a long gap the whole page turns.

    Args:
        times: When each line is sung, in order.
        first_show: When the first page appears (after the title).
        profile: The profile.
        rows: How many slots every line takes, as for ``cut_pages``; ``None`` for one each.

    Returns:
        The placement of every line (its first slot).
    """
    if not times:
        return []
    rows = [1] * len(times) if rows is None else rows
    pages = cut_pages(times, profile, rows)
    before = [silence.before for silence in gaps(times)]
    sung = [max(line.end for line in times[first:end]) for first, end in pages]
    shows = [first_show]
    hides: list[float] = []
    for number, (first, _) in enumerate(pages[1:], start=1):
        turn = page_turn(sung[number - 1], times[first].start, profile)
        long = before[first] >= profile.breaks.clear_after
        hides.append(min(sung[number - 1] + profile.clear.hold, turn) if long else turn)
        shows.append(turn)
    hides.append(last_hold(times, profile))
    number_of = [number for number, (first, end) in enumerate(pages) for _ in range(first, end)]
    line_shows = [shows[number] for number in number_of]
    line_hides = [hides[number] for number in number_of]
    if profile.page.turn == "line":
        line_shows, line_hides = _turn_by_line(
            times, pages, profile, rows, (line_shows, line_hides)
        )
    placements: list[Placement] = []
    for number, (first, end) in enumerate(pages):
        top = (profile.slots - sum(rows[first:end])) // 2
        placements += [
            Placement(top + sum(rows[first:index]), line_shows[index], line_hides[index], number)
            for index in range(first, end)
        ]
    return placements
