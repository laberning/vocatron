"""Rules 5 to 12: when lines show, are held, are cleared and replaced, and the gaps."""

from collections.abc import Sequence

from vocatron.core.layout.pages import page_turn
from vocatron.core.layout.place import (
    Stack,
    Times,
    clearing,
    hold_end,
    in_order,
)
from vocatron.core.layout.rules_base import (
    EPS,
    TOLERANCE,
    Gap,
    gaps,
    is_later_row,
    line_ends,
    line_groups,
    lyric_rows,
    need,
    pairs,
    turns,
    turns_by_line,
)
from vocatron.core.layout.rules_cards import counts_in, scene_beat
from vocatron.core.layout.scroll import MIN_NOTICE, SETTLE
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    CardElement,
    CountdownElement,
    LineElement,
    PreviewElement,
    ProgressElement,
    Scene,
    TimerElement,
)
from vocatron.core.tempo import MAX_COUNTDOWN


def _first_seen(scene: Scene, index: int) -> float:
    """Return when line ``index`` is first on screen: its preview appears, or the line itself."""
    line = scene.lines()[index]
    previews = [e for e in scene.elements if isinstance(e, PreviewElement) and e.of_line == index]
    return previews[0].start if previews else line.start


def _earliest_show(scene: Scene, profile: Profile, index: int) -> float:
    """Return the earliest a short line could have been first seen.

    The first line (or page) can appear at 0. In page mode a page appears when the pages before
    it have been sung. In line mode a line appears not before the line before it, and not before
    the line before it in its slot has been sung to its end (with blocks, every line in the block
    its group takes, ADR-0038); a preview of it appears with the line before it.
    After a long gap the slots start again, and no line appears before the screen is cleared
    (rule 22).
    """
    lines = scene.lines()
    line = lines[index]
    if index == 0:
        return 0.0
    if profile.mode == "page":
        if turns_by_line(lines, profile, line.page):
            return max(_slots_sung(lines, index), lines[index - 1].start)
        return max((x.sing_end for x in lines if (x.page or 0) < (line.page or 0)), default=0.0)
    if any(isinstance(e, PreviewElement) and e.of_line == index for e in scene.elements):
        return lines[index - 1].start
    silences = gaps(lines)
    long = profile.breaks.clear_after - EPS
    since = max(i for i in range(index + 1) if i == 0 or silences[i].before >= long)
    cleared = clearing(silences[since].ended, lines[since].sing_start, profile) if since else 0.0
    blocks = turns(lines, profile) if profile.block > 1 else []
    turn = next((t for t in blocks if index in t.lines), None)
    if turn and not turn.fallback:  # the lines in the block its group takes are sung
        taken = {lines[i].slot // profile.block for i in turn.lines}  # several for a wide pair
        sung_free = max(turn.ended[block] for block in taken)
    else:  # the line before it in its slot is sung, every row of it
        prior = [i for i in range(since, index) if lines[i].slot == line.slot]
        head = prior[-1] - lines[prior[-1]].row if prior else -1
        sung_free = max((lines[i].sing_end for i in prior if i - lines[i].row == head), default=0.0)
    return max(sung_free, lines[index - 1].start, cleared)


def _slots_sung(lines: Sequence[LineElement], index: int) -> float:
    """Return when the page before the page of line ``index`` has been sung in its slots.

    That is the end of the lines of that page in the slots the lyric line of ``index`` takes, or
    of the first line of that page where it takes slots the page did not use (ADR-0041).
    """
    ends = line_ends(lines)
    page = lines[index].page
    old = [i for i, x in enumerate(lines) if x.page == (page or 0) - 1]
    slots = {lines[k].slot for k in lyric_rows(lines, index)}
    found = [ends[i] for i in old if lines[i].slot in slots]
    return max(found, default=ends[old[0]])


def _starts_a_page(lines: Sequence[LineElement], index: int) -> bool:
    """Tell whether line ``index`` is the first line of its page (every line, in line mode).

    The later rows of a lyric line appear with its first row and do not start a page.
    """
    return not is_later_row(lines, index) and (
        index == 0 or lines[index].page is None or lines[index].page != lines[index - 1].page
    )


def _rule_5_scroll(scene: Scene, profile: Profile) -> None:
    """In scroll mode a line is on screen ``lead_in.min`` before it is sung, or reported.

    A line is shown as soon as the column has room for it, long before it is sung; only the first
    line, which comes in as the title ends, is shown no more than ``lead_in.max`` ahead.
    """
    short = {s.line for s in scene.shortfalls if s.kind == "lead-in"}
    lines = scene.lines()
    for index, line in enumerate(lines):
        shown = line.sing_start - line.start
        if is_later_row(lines, index):
            continue
        if index == 0:
            need(
                shown <= profile.lead_in.max + TOLERANCE, f"rule 5: line 0 is shown {shown} s ahead"
            )
        if index in short:
            need(
                shown < profile.lead_in.min + TOLERANCE,
                f"rule 5: line {index} is reported but fine",
            )
        else:
            need(shown >= profile.lead_in.min - TOLERANCE, f"rule 5: line {index} is shown {shown}")


def rule_5_lead_in(scene: Scene, profile: Profile) -> None:
    """A line is on screen ``lead_in.min`` to ``lead_in.max`` before it is sung, or reported.

    A line counts from the moment it is first seen: its own appearance, its preview, or its
    page. In page mode ``lead_in.max`` is checked on the first line of a page only (the other
    lines appear with it). A reported line was first seen as soon as it could be: the moment the
    line before it in its slot had been sung (or with the line before it), or the pages before
    its page had been sung, so a shortfall is never one the layout could have avoided. After a
    long gap a line is shown ``lead_in.target`` ahead, or from the moment the screen is cleared
    (``clearing``: ``clear.hold`` after the singing stopped, but never less than ``lead_in.min``
    ahead) when the gap leaves less room. In a look that turns in blocks (ADR-0038) the lines of
    a group appear together and only its first line counts for ``lead_in.max`` and the lead-in
    after a gap. In page mode with ``page.turn: line`` (ADR-0041) a line could have appeared at the
    earliest when the lines of the page before it in its slots had been sung and the line above it
    had appeared. Of two lines sung at once (ADR-0054) both are due as the earlier one starts, and
    only the earlier counts for ``lead_in.max`` and the lead-in after a gap.
    """
    if scene.scroll is not None:
        _rule_5_scroll(scene, profile)
        return
    short = {s.line for s in scene.shortfalls if s.kind == "lead-in"}
    lead = profile.lead_in
    lines = scene.lines()
    silences = gaps(lines)
    after_gap = {i for i, gap in enumerate(silences) if gap.before >= profile.breaks.clear_after}
    numbers = line_groups(lines, profile)
    mates = pairs(lines, profile)
    heads: dict[int, int] = {}  # the first line of every group
    for index, number in enumerate(numbers):
        heads.setdefault(number, index)
    fallen = fallen_lines(lines, profile)  # each of their lines appears on its own
    for preview in (e for e in scene.elements if isinstance(e, PreviewElement)):
        need(abs(preview.end - lines[preview.of_line].start) <= TOLERANCE, "rule 5: preview")
    for index, line in enumerate(lines):
        seen = _first_seen(scene, index)
        shown = line.sing_start - seen
        if is_later_row(lines, index):  # it appears with its first row, which is judged
            continue
        opens = _starts_a_page(lines, index) and (heads[numbers[index]] == index or index in fallen)
        # the first line of a lyric line that starts later than the one it is sung with appears
        # with that one
        later_of_pair = line.part == 0 and any(
            lines[j].voice != line.voice
            and lines[j].part == 0
            and lines[j].sing_start < line.sing_start
            for j in mates.get(index, ())
        )
        opens = opens and not later_of_pair
        if opens:
            need(shown <= lead.max + TOLERANCE, f"rule 5: line {index} is shown {shown} s ahead")
        if index in short:
            need(shown < lead.min + TOLERANCE, f"rule 5: line {index} is reported but fine")
            earliest = _earliest_show(scene, profile, index)
            need(seen <= earliest + TOLERANCE, f"rule 5: line {index} could appear sooner")
            continue
        need(shown >= lead.min - TOLERANCE, f"rule 5: line {index} is shown only {shown} s ahead")
        if index in after_gap and index > 0 and opens:
            room = _room_after_gap(lines, silences, index, profile)
            need(shown >= min(lead.target, room) - TOLERANCE, f"rule 5: line {index} after a gap")


def _room_after_gap(
    lines: Sequence[LineElement], silences: Sequence[Gap], index: int, profile: Profile
) -> float:
    """Return how long line ``index`` can be shown ahead after a long gap at most.

    In line mode no line appears before the screen is cleared (rule 22), so a gap barely long
    enough allows less than ``lead_in.target``; a page may appear before the clearing, but not
    before the pages before it have been sung.
    """
    sung, ended = lines[index].sing_start, silences[index].ended
    return sung - (clearing(ended, sung, profile) if profile.mode == "line" else ended)


def rule_6_visible_while_sung(scene: Scene, profile: Profile) -> None:
    """A line is visible during every one of its syllables."""
    del profile
    for index, line in enumerate(scene.lines()):
        need(line.start <= line.sing_start + EPS, f"rule 6: line {index} appears late")
        need(line.end >= line.sing_end - EPS, f"rule 6: line {index} goes early")
        for span in line.spans:
            middle = (span.start + span.end) / 2
            need(line.visible(middle) or span.end - span.start < EPS, f"rule 6: line {index}")


def rule_7_wipe_in_time(scene: Scene, profile: Profile) -> None:
    """The wipe front lies in the syllable that is sung and reaches its end when it ends."""
    del profile
    look = scene.look
    for index, line in enumerate(scene.lines()):
        before = -1.0
        for number, span in enumerate(line.spans):
            start, end = span.start + look.wipe_offset, span.end + look.wipe_offset
            if end - start > TOLERANCE:
                middle = line.wipe_front((start + end) / 2, look)
                need(span.x0 - EPS <= middle <= span.x1 + EPS, f"rule 7: line {index}")
            later = line.spans[number + 1 :]
            if not later or later[0].start + look.wipe_offset > end + TOLERANCE:
                after = line.wipe_front(end + EPS, look)
                need(abs(after - span.x1) <= TOLERANCE, f"rule 7: line {index}, end of a syllable")
                need(after >= before - EPS, f"rule 7: line {index} goes backwards")
                before = after
        before_start = line.wipe_front(line.spans[0].start + look.wipe_offset - TOLERANCE, look)
        need(before_start == 0.0, f"rule 7: line {index} is wiped before it is sung")


def rule_8_held_notes(scene: Scene, profile: Profile) -> None:
    """The wipe of a syllable lasts to its end: just before it, the front is not at the edge."""
    if profile.wipe.granularity != "smooth":
        return
    look = scene.look
    for index, line in enumerate(scene.lines()):
        for span in line.spans:
            if span.end - span.start > 4 * TOLERANCE and span.x1 - span.x0 > 1.0:
                front = line.wipe_front(span.end + look.wipe_offset - 2 * TOLERANCE, look)
                need(front < span.x1 - EPS, f"rule 8: line {index} sweeps ahead of its syllable")


def _clearing_after(scene: Scene, profile: Profile, line: int, until: int) -> float | None:
    """Return when the screen is cleared in the first long gap between ``line`` and ``until``."""
    lines = scene.lines()
    silences = gaps(lines)
    long = profile.breaks.clear_after - EPS
    after = (i for i in range(line + 1, until) if silences[i].before >= long)
    first = next(after, None)
    return (
        None if first is None else clearing(silences[first].ended, lines[first].sing_start, profile)
    )


def _refills(
    lines: Sequence[LineElement],
    index: int,
    profile: Profile,
    fallen: set[int],
    wide: dict[int, set[int]],
) -> list[int]:
    """Return the line that takes over from line ``index``: the next page or its slot's next.

    With blocks (ADR-0038) a group takes over the whole block, but a line of a group that fell
    back to turning line by line (``fallen``) only its own slot. A page that turns line by line
    (ADR-0041) is taken over by the first line of the next page in a slot of the line, if any.
    A group that takes several blocks (``wide``: their numbers by line, ADR-0054) goes when a line
    takes any of them.
    """
    line = lines[index]
    if profile.mode == "page":
        later = [i for i in range(index + 1, len(lines)) if lines[i].page != line.page]
        if later and turns_by_line(lines, profile, lines[later[0]].page):
            slots = {lines[k].slot for k in lyric_rows(lines, index)}
            return [
                i for i in later if lines[i].page == lines[later[0]].page and lines[i].slot in slots
            ][:1]
        return later[:1]
    # the slot, or the block of slots that turns together
    units = wide.get(index, {line.slot // profile.block})
    return [
        i
        for i in range(index + 1, len(lines))
        if lines[i].start > line.start
        and (
            lines[i].slot == line.slot
            or (lines[i].slot // profile.block in units and i not in fallen)
        )
    ][:1]


def fallen_lines(lines: Sequence[LineElement], profile: Profile) -> set[int]:
    """Return the lines of the groups that turned line by line, as no block was free (ADR-0038)."""
    if profile.mode != "line" or profile.block == 1:
        return set()
    return {i for turn in turns(lines, profile) if turn.fallback for i in turn.lines}


def wide_blocks(lines: Sequence[LineElement], profile: Profile) -> dict[int, set[int]]:
    """Return for every line of a group that takes several blocks the numbers of those blocks."""
    if profile.mode != "line" or profile.block == 1:
        return {}
    found: dict[int, set[int]] = {}
    for turn in turns(lines, profile):
        if turn.span > 1 and not turn.fallback:
            blocks = {lines[i].slot // profile.block for i in turn.lines}
            found.update(dict.fromkeys(turn.lines, blocks))
    return found


def _scrolls_out(line: LineElement) -> bool:
    """Tell whether a line ends by gliding up and out of the column (scroll mode)."""
    return len(line.path) > 1 and line.path[-1].y < line.path[-2].y - EPS


def rule_9_hold_and_clear(scene: Scene, profile: Profile) -> None:
    """A sung line stays until its slot is needed, or ``hold`` after the singing before a long gap.

    Rule 11 wins over rule 9 in line mode: without a long gap before the line that refills its
    slot, a sung line stays until that line appears. When a long gap comes first, it goes when
    the screen is cleared in that gap (``clearing``: ``hold`` after the singing stops, but in time
    for ``lead_in.min``), or earlier when its slot is needed. A line whose slot is not needed again
    goes when the screen is cleared in the next long gap, or ``hold`` after the last line (at the
    latest when the end screen starts, ADR-0037). Lines
    go in the order they were sung: none stays on screen after a line sung later has gone, and
    none goes before its own singing ends (ADR-0034; a wrapped line's rows by the end of its last
    row, ``line_ends``). In page mode the lines of a page go
    together, as the page that follows takes over (the first line of the next page refills); with
    ``page.turn: line`` (ADR-0041) a line goes when the line of the next page in its slot
    appears, and one whose slot the next page does not use at the page turn, but not before the
    next page's first line appears. In scroll mode a line stays until the column has glided it out
    of the window, until the break screen of a long break starts (``clearing``), or ``hold`` after
    the last line (at the latest when the end screen starts).
    """
    lines = scene.lines()
    last = max((x.sing_end for x in lines), default=0.0)
    if scene.scroll is not None:
        breaks = scene.cards("break")
        for index, line in enumerate(lines):
            at_end = abs(line.end - hold_end(last, profile)) <= TOLERANCE
            before_break = any(abs(card.start - line.end) <= TOLERANCE for card in breaks)
            need(
                at_end or before_break or _scrolls_out(line),
                f"rule 9: line {index} goes at {line.end}",
            )
        return
    expected = _expected_hides(scene, profile, last)
    expected = in_order(expected, line_ends(lines))
    for index, line in enumerate(lines):
        need(
            abs(line.end - expected[index]) <= TOLERANCE, f"rule 9: line {index} goes at {line.end}"
        )


def _unreplaced_hide(lines: Sequence[LineElement], index: int, profile: Profile) -> float | None:
    """Return when a line of a page goes if no line of the next page takes its slot (ADR-0041).

    That is the whole-page turn of the next page, ``page_turn``, but not before the next page's
    first line appears. ``None`` if there is no next page.
    """
    page = lines[index].page
    later = [i for i in range(index + 1, len(lines)) if lines[i].page != page]
    if not later or profile.mode != "page":
        return None
    sung = max(x.sing_end for x in lines if x.page == page)
    return max(page_turn(sung, lines[later[0]].sing_start, profile), lines[later[0]].start)


def _expected_hides(scene: Scene, profile: Profile, last: float) -> list[float]:
    """Return when every line goes before the order is applied: its slot is needed, or it clears.

    ``last`` is when the last line is sung to its end.
    """
    lines = scene.lines()
    fallen = fallen_lines(lines, profile)
    wide = wide_blocks(lines, profile)
    found: list[float] = []
    for index in range(len(lines)):
        refills = _refills(lines, index, profile, fallen, wide)
        turn = None if refills else _unreplaced_hide(lines, index, profile)
        if turn is not None:
            found.append(turn)
        elif not refills:
            cleared = _clearing_after(scene, profile, index, len(lines))
            found.append(hold_end(last, profile) if cleared is None else cleared)
        else:
            refill = lines[refills[0]].start
            cleared = _clearing_after(scene, profile, index, refills[0] + 1)
            found.append(refill if cleared is None else min(cleared, refill))
    return found


def _rule_10_page_by_line(lines: Sequence[LineElement], positions: Sequence[int]) -> None:
    """A page that takes over line by line (ADR-0041) has every line appear in time.

    A line appears no later than its first syllable and no sooner than the lines of the page
    before in its slots have been sung (``_slots_sung``); the rows of a lyric line appear and go
    together.
    """
    for index in positions:
        line = lines[index]
        need(line.start <= line.sing_start + TOLERANCE, f"rule 10: line {index} appears late")
        need(
            line.start >= _slots_sung(lines, index) - TOLERANCE,
            f"rule 10: line {index} appears before its slot is sung",
        )
        head = lines[lyric_rows(lines, index)[0]]
        need((line.start, line.end) == (head.start, head.end), f"rule 10: line {index} is torn")


def _rule_10_pages(scene: Scene, profile: Profile) -> None:
    """Pages come in order, in consecutive slots from the same row, never cut mid-song.

    A page holds at most ``slots`` lines (the rows of a line count as one; with
    ``page.slot_per_row`` at most ``slots`` rows) and is not cut between lines that are sung at
    the same time. A page appears as a whole, or, with ``page.turn: line`` inside a run of lines,
    line by line (``_rule_10_page_by_line``).
    """
    lines = scene.lines()
    pages = sorted({line.page for line in lines}, key=lambda page: -1 if page is None else page)
    need(pages == list(range(len(pages))), "rule 10: the pages are not numbered in order")
    sung_before = 0.0
    for page in pages:
        members = [x for x in lines if x.page == page]
        positions = [i for i, x in enumerate(lines) if x.page == page]
        need(positions == list(range(positions[0], positions[0] + len(members))), "rule 10")
        slots = [
            x.slot
            for i, x in enumerate(lines)
            if x.page == page and (profile.page.slot_per_row or not is_later_row(lines, i))
        ]
        need(len(slots) <= profile.slots, f"rule 10: page {page} has too many lines")
        top = (profile.slots - len(slots)) // 2
        need(slots == list(range(top, top + len(slots))), f"rule 10: {page}")
        arrives_by_line = turns_by_line(lines, profile, page)
        if arrives_by_line:
            _rule_10_page_by_line(lines, positions)
        leaves_by_line = turns_by_line(lines, profile, (page or 0) + 1)
        torn = {
            (None if arrives_by_line else x.start, None if leaves_by_line else x.end)
            for x in members
        }
        need(len(torn) == 1, f"rule 10: page {page} is torn")
        need(
            min(x.sing_start for x in members) >= sung_before - TOLERANCE,
            f"rule 10: page {page} is cut between lines sung at the same time",
        )
        sung_before = max(sung_before, *(x.sing_end for x in members))


def rule_10_replacement_order(scene: Scene, profile: Profile) -> None:
    """The next line takes the slot of the line that finished first; lines stay in order.

    In line mode the parts of a lyric line split into lines take neighbouring slots, top to
    bottom. In page mode: pages follow each other, fill consecutive slots as near the middle of
    the block as whole slots allow, and are not cut between lines that are sung at the same time.
    In scroll mode the lines come into the column and leave it in the order they are sung. In
    line mode with blocks the choice of the block is part of rule 23.
    """
    lines = scene.lines()
    if profile.mode == "page":
        _rule_10_pages(scene, profile)
    for index in range(1, len(lines)):
        need(lines[index].start >= lines[index - 1].start - EPS, f"rule 10: line {index} is early")
        if scene.scroll is not None:  # the lines go in the order they came
            need(lines[index].end >= lines[index - 1].end - EPS, f"rule 10: line {index} stays")
    if profile.mode == "line" and profile.block == 1:
        _rule_10_lines(lines, profile)


def _rule_10_lines(lines: Sequence[LineElement], profile: Profile) -> None:
    """In line mode a line takes the slot whose line finished first (``Stack``).

    The parts of a lyric line split into lines take neighbouring slots, top to bottom, when ``n``
    parts fit the ``slots``: of all runs of ``n`` slots, one whose slots free soonest before their
    parts start (the largest ``end - start`` of a slot's last line and its part is smallest). For
    one slot that is the slot whose line finished first. Two lyric lines sung at once
    (``pairs``, ADR-0054) take neighbouring slots the same way with all their rows, the first
    voice's above the second's. Where no such slots were free as the lines start (a slot still
    holds a line that is sung), the pair breaks up into its lyric lines, and a lyric line into
    lines that take a slot each. After a long gap the slots have no last line: they start again
    (rule 22).
    """
    firsts = [i for i in range(len(lines)) if not is_later_row(lines, i)]
    ends = line_ends(lines)
    stack = Stack(
        [Times(lines[i].sing_start, ends[i]) for i in firsts],
        [lines[i].voice for i in firsts],
        [lines[i].part for i in firsts],
        profile,
    )
    where = {line: number for number, line in enumerate(firsts)}
    mates = pairs(lines, profile)
    last: dict[int, LineElement] = {}
    silences = gaps(lines)
    for index, line in enumerate(lines):
        number = where.get(index)
        if number is not None:
            cleared = index and silences[index].before >= profile.breaks.clear_after - EPS
            if cleared and not stack.reserved(number):
                last.clear()  # the screen was cleared: the slots start again (rule 22)
            ended = [
                -1.0 if (x := last.get(s)) is None else x.sing_end for s in range(profile.slots)
            ]
            planned = stack.planned(number)
            if planned is None:
                choice = stack.choose(number, ended, EPS)
                top = line.slot - choice.run.index(number)
                need(
                    top >= 0 and top + len(choice.run) <= profile.slots,
                    f"rule 10: line {index} leaves the slots",
                )
                need(stack.fits(choice, top, ended, EPS), f"rule 10: line {index}")
                stack.commit(choice, top)
            else:
                need(
                    line.slot == planned,
                    f"rule 10: line {index} is not in the slot under the part before"
                    if index not in mates
                    else f"rule 10: line {index} is not next to the line it is sung with",
                )
            stack.asked(number)
        last[line.slot] = line


def rule_11_short_gaps(scene: Scene, profile: Profile) -> None:
    """A short gap brings no countdown and no break screen, and never an empty screen.

    During a gap shorter than ``breaks.clear_after`` a line is on screen at every moment: when
    the singing stops and whenever a line goes before the next line is sung.
    """
    shorter = profile.breaks.notice_after
    lines = scene.lines()
    found = gaps(lines)
    beat = scene_beat(scene, profile)
    for countdown in (e for e in scene.elements if isinstance(e, CountdownElement)):
        line = next(x for x in lines if counts_in(countdown, x, beat))
        need(
            found[lines.index(line)].before >= profile.countdown.min_gap - EPS,
            "rule 11: a countdown in a short gap",
        )
    for card in scene.cards("break"):
        following = [x for x in lines if x.sing_start >= card.end - TOLERANCE]
        gap = found[lines.index(following[0])].before
        need(gap >= shorter - EPS, "rule 11: a break screen in a short gap")
    for index, gap in enumerate(found):
        if index == 0 or gap.before <= 0 or gap.before >= profile.breaks.clear_after - EPS:
            continue
        resumes = lines[index].sing_start
        moments = [gap.ended] + [x.end for x in lines if gap.ended <= x.end < resumes - TOLERANCE]
        for moment in moments:
            shown = [x for x in lines if x.visible(moment + TOLERANCE / 2)]
            need(
                bool(shown),
                f"rule 11: the screen is empty at {moment} in the gap before line {index}",
            )


def rule_12_long_gaps(scene: Scene, profile: Profile) -> None:
    """After a long gap the screen is cleared (``clearing``); a very long one has a break screen.

    The screen is cleared ``hold`` after the singing stops, or sooner when the line after the gap
    would otherwise get less than ``lead_in.min`` (ADR-0034).
    """
    lines = scene.lines()
    breaks = scene.cards("break")
    if scene.scroll is not None:
        _rule_12_scroll(scene, profile, breaks)
    for index, gap in enumerate(gaps(lines)):
        if index == 0 or scene.scroll is not None:
            continue
        shows = lines[index].start
        cleared = clearing(gap.ended, lines[index].sing_start, profile)
        if gap.before >= profile.breaks.clear_after and cleared + TOLERANCE < shows:
            inside = [x for x in lines if x.start < shows - EPS and x.end > cleared + TOLERANCE]
            need(not inside, f"rule 12: a line stays after the long gap before line {index}")
        if gap.before >= profile.breaks.notice_after and cleared + TOLERANCE < shows:
            match = [b for b in breaks if abs(b.end - shows) <= TOLERANCE]
            need(bool(match), f"rule 12: no break screen before line {index}")
            need(match[0].start >= cleared - TOLERANCE, f"rule 12: break screen {index} too early")
    bars = [e for e in scene.elements if isinstance(e, ProgressElement)]
    need(len(bars) == len(breaks) * (profile.breaks.form == "progress"), "rule 12: progress bars")
    for card in breaks if bars else []:
        (bar,) = [b for b in bars if belongs_to(b, card)]
        need(bar.box.y >= card.box.bottom - TOLERANCE, "rule 12: the bar is not under the text")
    _rule_12_timers(scene, profile, breaks)
    _rule_12_symbols(profile, breaks)


def _rule_12_symbols(profile: Profile, breaks: list[CardElement]) -> None:
    """The V symbol of a break screen is the wordmark form's: above the text, inside the card.

    It stands only with ``title.form: wordmark`` (on CD+G the break screen is plain), is part of
    the card's box, and ends above every line of the notice (ADR-0057).
    """
    for card in (b for b in breaks if b.symbol is not None):
        symbol = card.symbol
        assert symbol is not None  # the filter above
        need(profile.title.form == "wordmark", "rule 12: a symbol on a plain break screen")
        need(symbol.inside(card.box), "rule 12: the symbol leaves the card")
        need(
            all(symbol.bottom <= line.box.y + TOLERANCE for line in card.lines),
            "rule 12: the symbol is not above the text",
        )


def belongs_to(part: ProgressElement | TimerElement, card: CardElement) -> bool:
    """Tell whether a bar or timer belongs to a break card: it is on screen as long as the card."""
    return abs(part.start - card.start) <= TOLERANCE and abs(part.end - card.end) <= TOLERANCE


def _rule_12_scroll(scene: Scene, profile: Profile, breaks: list[CardElement]) -> None:
    """In scroll mode a long gap has no clearing, and a very long one has a break screen alone.

    The lines of the column go ``clearing`` after the singing stops and the break screen stands
    until the column glides in again (ADR-0040; rule 21 checks that no line is on screen while it
    stands). A gap
    is long enough for the screen when the hold, the shortest time it stands, the glide in, the
    time before the line and a countdown fit into it.
    """
    lines = scene.lines()
    view = scene.scroll
    assert view is not None  # the caller checked
    margin = profile.clear.hold + view.glide + MIN_NOTICE + SETTLE + MAX_COUNTDOWN
    margin += 2 * abs(profile.wipe.offset)
    for index, gap in enumerate(gaps(lines)):
        if index == 0:
            continue
        sung = lines[index].sing_start
        noticed = [b for b in breaks if gap.ended - TOLERANCE <= b.start < sung]
        if gap.before >= profile.breaks.notice_after:
            need(bool(noticed) or gap.before < margin, f"rule 12: no break screen before {index}")
        for card in noticed:
            cleared = clearing(gap.ended, sung, profile)
            need(card.start >= cleared - TOLERANCE, f"rule 12: card {index} starts too early")
            need(card.end <= sung - SETTLE + TOLERANCE, f"rule 12: card {index} ends too late")
            need(gap.before >= profile.breaks.notice_after, "rule 12: a break in a short gap")


def _rule_12_timers(scene: Scene, profile: Profile, breaks: list[CardElement]) -> None:
    """A break screen has one timer in the ``timer`` form, under its text, inside the safe area."""
    timers = [e for e in scene.elements if isinstance(e, TimerElement)]
    need(len(timers) == len(breaks) * (profile.breaks.form == "timer"), "rule 12: timers")
    for card in breaks if timers else []:
        matching = [t for t in timers if belongs_to(t, card)]
        need(len(matching) == 1, "rule 12: a timer does not go with its break screen")
        (timer,) = matching
        need(timer.box.inside(scene.safe), "rule 12: the timer leaves the safe area")
        need(timer.box.y >= card.box.bottom - TOLERANCE, "rule 12: the timer is not under the text")
        middle = timer.box.x + timer.box.w / 2
        need(abs(middle - (scene.safe.x + scene.safe.w / 2)) <= TOLERANCE, "rule 12: the timer")
