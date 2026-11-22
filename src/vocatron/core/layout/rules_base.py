"""Shared pieces of the layout rules: tolerances, the broken-rule error and line helpers."""

from collections.abc import Sequence
from dataclasses import dataclass

from vocatron.core.layout.place import (
    Run,
    Times,
    block_ends,
    falls_back,
    groups,
    kept_lead_in,
    pair_runs,
    units,
)
from vocatron.core.lyrics.document import Voice
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    CardElement,
    LineElement,
    Rect,
    Scene,
)

EPS = 1e-6
TOLERANCE = 0.01  # seconds or pixels of slack for rounding to a thousandth
ROUNDING = 0.0005  # the most a value rounded to a thousandth is off


class RuleBroken(Exception):
    """A rule of the presentation does not hold; the message names the rule."""


def need(holds: bool, message: str) -> None:
    """Raise ``RuleBroken`` with ``message`` unless ``holds``."""
    if not holds:
        raise RuleBroken(message)


@dataclass(frozen=True)
class Gap:
    """The silence before a line: how long, and when the lines before it were last sung."""

    before: float
    ended: float


def is_later_row(lines: Sequence[LineElement], index: int) -> bool:
    """Tell whether line ``index`` is a second row of a line wrapped onto rows.

    The rows of one lyric line share appearance and going and are told apart by their ``row``;
    they sit in the same slot or, with ``page.slot_per_row``, in neighbouring slots.
    """
    return lines[index].row > 0


def gaps(lines: Sequence[LineElement]) -> list[Gap]:
    """Return the silence before every line, counting from the start of the song for the first.

    The later rows of a lyric line have no silence before them (0): they belong to the line.
    """
    found: list[Gap] = []
    ended = 0.0
    for index, line in enumerate(lines):
        silence = (
            0.0 if is_later_row(lines, index) else round((line.sing_start - ended) * 1000) / 1000
        )
        found.append(Gap(silence, ended))  # rounded as the scene
        ended = max(ended, line.sing_end)
    return found


def line_ends(lines: Sequence[LineElement]) -> list[float]:
    """Return for every line when it is sung to its end: a wrapped line until its last row is.

    The rows of a line wrapped onto rows share their going, so every row counts by the end of
    the whole line (as the placement sees it), not by the end of its own words.
    """
    ends = [line.sing_end for line in lines]
    for index, line in enumerate(lines):
        head = index - line.row
        ends[head] = max(ends[head], line.sing_end)
    return [ends[index - line.row] for index, line in enumerate(lines)]


def lyric_rows(lines: Sequence[LineElement], index: int) -> range:
    """Return the indices of the rows of the lyric line that line ``index`` belongs to."""
    head = index - lines[index].row
    end = head + 1
    while end < len(lines) and is_later_row(lines, end):
        end += 1
    return range(head, end)


def _first_of_page(lines: Sequence[LineElement], page: int | None) -> int | None:
    """Return the index of the first line of ``page`` (``None`` if it has none)."""
    return next((i for i, x in enumerate(lines) if x.page == page), None)


def turns_by_line(lines: Sequence[LineElement], profile: Profile, page: int | None) -> bool:
    """Tell whether the page ``page`` takes over from the page before it line by line (ADR-0041).

    That is so with ``page.turn: line`` for a page inside a run of lines: not the first page and
    not a page after a long gap, which turns as a whole.
    """
    if profile.page.turn != "line" or not page:
        return False
    first = _first_of_page(lines, page)
    return first is not None and gaps(lines)[first].before < profile.breaks.clear_after - EPS


def line_groups(lines: Sequence[LineElement], profile: Profile) -> list[int]:
    """Return the group of every line: those that turn together (``block`` above 1, ADR-0038).

    The later rows of a lyric line belong to the group of their first row. Without blocks every
    line is a group of its own.
    """
    firsts = [i for i in range(len(lines)) if not is_later_row(lines, i)]
    if profile.block == 1:
        found = {index: number for number, index in enumerate(firsts)}
    else:
        ends = line_ends(lines)  # a line is sung until its last row is
        times = [Times(lines[i].sing_start, ends[i]) for i in firsts]
        numbers = groups(
            times, [lines[i].part for i in firsts], profile, [lines[i].voice for i in firsts]
        )
        found = dict(zip(firsts, numbers, strict=True))
    return [found[i - lines[i].row] for i in range(len(lines))]


@dataclass(frozen=True)
class Turn:
    """A group of lines that turns in a block (ADR-0038), as the scene shows it.

    Attributes:
        number: The group's number (``line_groups``).
        lines: The indices of its lines, every row.
        fallback: Whether no block was free as it started, so its lines turned one by one.
        ended: For every block, when the lines in it were sung as the group started (-1: empty).
        old: The indices of the lines in the block it took (every row), or, when it falls back,
            in the slots its lines took one by one.
        alone: When it falls back, for every first row of its lines, the line and when the line
            in every slot ended as it came (-1: empty); empty otherwise.
        span: How many blocks its lines take: more than one for a pair of lyric lines with more
            rows than a block has (ADR-0054).
    """

    number: int
    lines: list[int]
    fallback: bool
    ended: list[float]
    old: list[int]
    alone: list[tuple[int, list[float]]]
    span: int = 1


def turns(lines: Sequence[LineElement], profile: Profile) -> list[Turn]:
    """Return the groups of a look that turns in blocks in sung order, with the blocks they found.

    The slots are followed as the placement fills them: a group takes its block and empties it,
    a group that falls back (``falls_back``) puts each line into its own slot, and the slots are
    empty again after a long gap.
    """
    numbers = line_groups(lines, profile)
    silences = gaps(lines)
    voices = [line.voice for line in lines]
    ends = [line.sing_end for line in lines]
    held: dict[int, list[int]] = {}  # the rows of the line in each slot
    wide: dict[int, list[int]] = {}  # the lines of a group that takes several blocks, by line
    found: list[Turn] = []
    for number in dict.fromkeys(numbers):
        members = [i for i, n in enumerate(numbers) if n == number]
        first = members[0]
        if first and silences[first].before >= profile.breaks.clear_after - EPS:
            held.clear()  # the screen was cleared: the blocks start again (rule 22)
        by_slot = _slot_ends(lines, held, profile.slots, wide)
        span = -(-sum(1 for i in members if not lines[i].row) // profile.block)  # blocks it takes
        start = lines[first].sing_start
        waits = kept_lead_in(ends, voices, first, start, profile.lead_in.min)
        fallback = falls_back(by_slot, profile.block, start + EPS, span, waits)
        top = min(lines[i].slot for i in members) // profile.block * profile.block
        taken = range(top, top + span * profile.block)
        old: list[int] = [] if fallback else [i for slot in taken for i in held.pop(slot, [])]
        mates = _mates(old, wide)
        for slot in [slot for slot, rows in held.items() if mates.intersection(rows)]:
            old += held.pop(slot)  # a group of several blocks goes as a whole
        alone: list[tuple[int, list[float]]] = []
        for index in members:
            line = lines[index]
            if fallback and not line.row:
                old += held.get(line.slot, [])
                alone.append((index, _slot_ends(lines, held, profile.slots, wide, profile.block)))
            held[line.slot] = [*held.get(line.slot, []), index] if line.row else [index]
        if span > 1 and not fallback:
            wide.update({i: members for i in members})
        ended = block_ends(by_slot, profile.block)
        found.append(Turn(number, members, fallback, ended, old, alone, span))
    return found


def _mates(old: Sequence[int], wide: dict[int, list[int]]) -> set[int]:
    """Return the lines of the groups of several blocks that the lines in ``old`` belong to."""
    return {m for i in old for m in wide.get(i, ())}


def _slot_ends(
    lines: Sequence[LineElement],
    held: dict[int, list[int]],
    slots: int,
    wide: dict[int, list[int]],
    block: int = 0,
) -> list[float]:
    """Return when the line held in every slot (every row of it) is sung, -1 for an empty slot.

    A line of a group that takes several blocks counts as sung when the whole group is (``wide``:
    the lines of such a group by line), as the group goes as a whole (ADR-0054). With ``block``
    above 0 (a line that turns alone) it counts as sung when the group's lines in its own block
    are, as the placement sees it (``place._slot_ends``).
    """
    ends = []
    for slot in range(slots):
        rows = held.get(slot, [])
        group = {m for i in rows for m in wide.get(i, [i])}
        if block:
            top = slot // block * block
            near = {i for s in range(top, top + block) for i in held.get(s, [])}
            group &= near
        ends.append(max((lines[i].sing_end for i in group), default=-1.0))
    return ends


def boxes(scene: Scene) -> list[tuple[str, Rect]]:
    """Return every drawn box of the scene with a label (cards by line)."""
    found: list[tuple[str, Rect]] = []
    for element in scene.elements:
        if isinstance(element, CardElement):
            found += [(f"{element.kind} line", line.box) for line in element.lines]
            if element.mark is not None:
                found += [
                    (f"{element.kind} wordmark", element.mark.word),
                    (f"{element.kind} frame", element.mark.frame),
                ]
            if element.symbol is not None:
                found.append((f"{element.kind} symbol", element.symbol))
        else:
            found.append((element.kind, element.box))
    return found


def _first_rows(
    lines: Sequence[LineElement],
) -> tuple[list[int], list[Times], list[Voice], list[int]]:
    """Return the first rows of the lines, in sung order, with what the placement sees of them.

    That is their indices, when each whole line is sung (until its last row is), their voices and
    which part of its lyric line each is (``Fitted.part``).
    """
    firsts = [i for i in range(len(lines)) if not is_later_row(lines, i)]
    ends = line_ends(lines)
    times = [Times(lines[i].sing_start, ends[i]) for i in firsts]
    return firsts, times, [lines[i].voice for i in firsts], [lines[i].part for i in firsts]


def pairs(lines: Sequence[LineElement], profile: Profile) -> dict[int, Run]:
    """Return for every line (its first row) in a pair the lines of the pair, top to bottom.

    The pairs are those the placement found (``pair_runs``, ADR-0054), from the scene's lines:
    the first rows, in sung order, with the end of the whole line. A pair that could not take
    neighbouring slots and broke up is still in the result. Lines without a mate are not in it.
    """
    firsts, times, voices, parts = _first_rows(lines)
    found = pair_runs(times, voices, parts, profile)
    return {firsts[k]: tuple(firsts[j] for j in run) for run in found for k in run}


def lyric_lines(lines: Sequence[LineElement]) -> dict[int, Run]:
    """Return for every line (its first row) the lines its lyric line was split into, in order."""
    firsts, _, voices, parts = _first_rows(lines)
    return {
        firsts[k]: tuple(firsts[j] for j in unit) for unit in units(parts, voices) for k in unit
    }
