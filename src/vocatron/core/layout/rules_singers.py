"""Rules 16, 17, 20, 22 and 23: singers, slots, transitions, restarts after a break and blocks.."""

from collections.abc import Sequence

from vocatron.core.layout.phrases import SECOND_VOICE_COLOUR
from vocatron.core.layout.place import (
    clearing,
    first_of_run,
    group_slots,
    slack,
    stacked,
)
from vocatron.core.layout.rules_base import (
    EPS,
    ROUNDING,
    TOLERANCE,
    gaps,
    is_later_row,
    line_ends,
    lyric_lines,
    need,
    pairs,
    turns,
)
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    LineElement,
    Rect,
    Scene,
)


def _colours_of(singers: str, profile: Profile) -> tuple[str, str]:
    """Return the unsung colour and the edge colour a profile gives the singers."""
    base = profile.singer_colours(singers if singers in {"1", "2", "3", "4", "5"} else "group")
    return base.unsung, base.edge


def rule_16_singers(scene: Scene, profile: Profile) -> None:
    """A line, and each turn of a line, has the colours of its singers, or of the group.

    A second-voice line may also have the colours of singer 2 (ADR-0054).

    The turns of a line rise by syllable, lie inside the line and each names other singers than
    the syllable before it.
    """
    for index, line in enumerate(scene.lines()):
        own = _colours_of(line.singers, profile)
        second = _colours_of(
            SECOND_VOICE_COLOUR, profile
        )  # a second voice without a mark of its own
        need(
            (line.colours.unsung, line.colours.edge)
            in ([own, second] if line.voice > 1 else [own]),
            f"rule 16: line {index} has the wrong colours",
        )
        before, singing = 0, line.singers
        for turn in line.turns:
            need(before < turn.span < len(line.spans), f"rule 16: turn of line {index} misplaced")
            need(turn.singers != singing, f"rule 16: turn of line {index} changes nothing")
            need(
                (turn.colours.unsung, turn.colours.edge) == _colours_of(turn.singers, profile),
                f"rule 16: turn of line {index} has the wrong colours",
            )
            before, singing = turn.span, turn.singers


def rule_17_slots(scene: Scene, profile: Profile) -> None:
    """Never more lines sung at the same time than slots (lines are never merged).

    In scroll mode one line is sung at a time: the column has one current place.
    """
    lines = scene.lines()
    most = 1 if scene.scroll is not None else profile.slots  # the column has one current line
    for line in lines:
        singing = [x for x in lines if x.sing_start < line.sing_start + EPS < x.sing_end]
        need(len(singing) < most + 1, "rule 17: more lines sung than slots")


def rule_20_transitions(scene: Scene, profile: Profile) -> None:
    """Lines come in before their first syllable and go after their last (ADR-0032).

    ``enter`` and ``exit`` are 0 without a transition and never more than ``transition.time``; in
    scroll mode, which has no transition, a line has no ``enter`` and goes with an ``exit`` of at
    most ``ending.fade`` where the column ends before a long break (ADR-0040); a line is in before
    its first syllable (a wipe shifted earlier counts) and starts to go after its last (a wipe
    shifted later counts); the rows of a line come and go together.
    """
    lines = scene.lines()
    shift = profile.wipe.offset
    slack = 3 * ROUNDING
    need(scene.look.transition == profile.transition.form, "rule 20: the look has another form")
    for index, line in enumerate(lines):
        for name, seconds in (("enter", line.enter), ("exit", line.exit)):
            need(seconds >= 0, f"rule 20: line {index} has a negative {name}")
            limit = profile.transition.time if profile.transition.form != "none" else 0.0
            if scene.scroll is not None:
                limit = profile.ending.fade if name == "exit" else 0.0
            need(seconds <= limit + slack, f"rule 20: line {index} takes {seconds} s to {name}")
        if line.enter:
            need(
                line.start + line.enter <= line.sing_start + min(shift, 0.0) + slack,
                f"rule 20: line {index} comes in after its first syllable starts",
            )
        if line.exit:
            need(
                line.end - line.exit >= line.sing_end + max(shift, 0.0) - slack,
                f"rule 20: line {index} starts to go before its last syllable ends",
            )
        if is_later_row(lines, index):
            need(
                (lines[index - 1].enter, lines[index - 1].exit) == (line.enter, line.exit),
                f"rule 20: row {index} does not come and go with the row above",
            )


def rule_22_restart_after_break(scene: Scene, profile: Profile) -> None:
    """After a long gap the lines fill the slots from the top, none before the screen is cleared.

    From the first line of the song, and from every line after a gap of ``breaks.clear_after`` or
    more, the lines take the slots without leaving one empty above (the first takes the top slot;
    with blocks, the top block, ADR-0038),
    and no line of the new phrase appears before the screen is cleared (``clearing``: ``hold``
    after the singing stopped, but in time for ``lead_in.min``; ADR-0034). Only line mode has
    slots that start again; in page mode every page starts at the top by rule 10, and a column
    has none.
    """
    if profile.mode != "line" or scene.scroll is not None:
        return
    lines = scene.lines()
    silences = gaps(lines)
    mates = pairs(lines, profile)
    lyric = lyric_lines(lines)
    filled = 0  # the slots (or blocks) from the top that the lines of this phrase have used
    cleared = 0.0
    for index, line in enumerate(lines):
        if index and silences[index].before >= profile.breaks.clear_after - EPS:
            filled = 0
            cleared = clearing(silences[index].ended, line.sing_start, profile)
        need(
            line.start >= min(cleared, line.sing_start) - TOLERANCE,
            f"rule 22: line {index} appears before the screen is cleared",
        )
        if not is_later_row(lines, index):
            unit = line.slot // profile.block  # a block of slots counts as one
            # a pair counts from the slot of its first voice, which may be sung after the second
            top = min(lines[i].slot // profile.block for i in mates.get(index, (index,)))
            need(min(unit, top) <= filled, f"rule 22: line {index} leaves a slot empty above it")
            filled = max(filled, unit + 1)
            # a pair or a split line that sits in neighbouring slots keeps them all for its lines,
            # which come one by one: lines sung between them go below
            run = mates.get(index) or lyric.get(index) or (index,)
            held = {lines[i].slot // profile.block for i in run}
            if held == set(range(min(held), max(held) + 1)):
                filled = max(filled, max(held) + 1)


def rule_23_blocks(scene: Scene, profile: Profile) -> None:
    """Lines turn in blocks: a group shares a block, appears and goes together (ADR-0038).

    Only line mode with ``block`` above 1 has groups (``groups``: the lines counted in sung order,
    a split lyric line on its own, starting again after a long gap). The lines of a group sit in
    one block, top to bottom in sung order, and appear and go together. A group with fewer lines
    than the block sits in the slots ``group_slots`` gives (next to the middle of the
    stack). The group goes into the block whose lines ended first (the top one on a tie), and the
    lines in that block go at the moment it appears: none of the block before stays, none has
    gone sooner. A group that found
    no block free, as a line in every block was still being sung, turns line by line instead
    (``falls_back``): each of its lines takes the slot whose line ended first (as rule 10 asks
    with ``block: 1``), rules 9 and 17 check when they come and go, and a line whose slot one of
    them took goes then, not with its group. As lines go in the order they are sung and none
    before its own singing ends (rule 9), a line may also go with a line sung after it, sooner
    than its group, or stay until it is sung, longer; rule 9 checks those moments.
    """
    if profile.mode != "line" or profile.block == 1 or scene.scroll is not None:
        return
    lines = scene.lines()
    found = turns(lines, profile)
    mates = pairs(lines, profile)
    ends = line_ends(lines)
    alone = {i for turn in found if turn.fallback for i in turn.old}  # went one by one
    for turn in found:
        for index, ended in turn.alone:  # no block was free: its lines turn one by one
            best = first_of_run(ended, [lines[index].sing_start])
            need(
                ended[lines[index].slot] <= ended[best] + EPS,
                f"rule 23: line {index} turns alone but not in the slot whose line ended first",
            )
        if turn.fallback:  # rules 9 and 17 check when its lines come and go
            continue
        number, group = turn.number, [lines[i] for i in turn.lines]
        # a line taken over alone, or moved by the order of rule 9, is not bound to the moment
        # its group goes
        going = [
            lines[i] for i in turn.lines if i not in alone and not _order_moves(lines, i, ends)
        ]
        block = min(x.slot for x in group) // profile.block
        # the later rows of a line share its slot; a pair stands first voice above the second
        firsts = [i for i in turn.lines if not lines[i].row]
        rows = [lines[i] for i in stacked(firsts, mates)]
        span = -(-len(rows) // profile.block)  # a pair of many rows takes several blocks
        need(
            [x.slot for x in rows] == group_slots(block, len(rows), profile),
            f"rule 23: the lines of group {number} are not in their block's slots",
        )
        need(
            all(abs(x.start - group[0].start) <= TOLERANCE for x in group)
            and all(abs(x.end - going[0].end) <= TOLERANCE for x in going),
            f"rule 23: the lines of group {number} do not appear and go together",
        )
        starts = [group[0].sing_start] * span
        best = first_of_run(turn.ended, starts)
        need(
            slack(turn.ended, block, starts) <= slack(turn.ended, best, starts) + EPS,
            f"rule 23: group {number} is not in the block that ended first",
        )
        for old in turn.old:
            need(
                abs(lines[old].end - group[0].start) <= TOLERANCE
                or (lines[old].end < group[0].start and _order_moves(lines, old, ends)),
                f"rule 23: a line of the block before does not go when group {number} appears",
            )


def _order_moves(lines: Sequence[LineElement], index: int, ends: Sequence[float]) -> bool:
    """Tell whether the order of rule 9 may have moved line ``index`` from its group's moment.

    Lines go in the order they are sung, none before its own singing ends (``in_order``): a line
    may go sooner, with a line sung after it, or stay until it is sung, longer than its group
    (``ends``: when every line is sung to its end, ``line_ends``). Rule 9 checks the exact moment.
    """
    line = lines[index]
    head = index - line.row
    return abs(line.end - ends[index]) <= TOLERANCE or any(
        abs(lines[j].end - line.end) <= TOLERANCE and j - lines[j].row != head
        for j in range(index + 1, len(lines))
    )


def vertical_inside(box: Rect, safe: Rect) -> bool:
    """Tell whether ``box`` lies between the top and the bottom of the safe area."""
    return box.y >= safe.y - TOLERANCE and box.bottom <= safe.bottom + TOLERANCE


def block_of(lines: Sequence[LineElement], index: int) -> list[LineElement]:
    """Return the rows of the lyric line whose first row is ``index``."""
    rows = [lines[index]]
    while index + len(rows) < len(lines) and is_later_row(lines, index + len(rows)):
        rows.append(lines[index + len(rows)])
    return rows
