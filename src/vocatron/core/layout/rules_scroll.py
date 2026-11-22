"""Rule 21, the scroll path, and the rule that no two elements overlap."""

from collections.abc import Sequence

from vocatron.core.layout.rules_base import (
    EPS,
    TOLERANCE,
    is_later_row,
    line_ends,
    need,
)
from vocatron.core.layout.rules_singers import block_of, vertical_inside
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    CardElement,
    LineElement,
    Moving,
    Rect,
    Scene,
    SceneElement,
    ScrollView,
)


def _rule_21_path(item: Moving, name: str, glide: float) -> None:
    """The path of a row runs from its start to its end, only up, in short moves.

    A move is at most ``glide`` seconds long. ``name`` says which row it is in the message.
    """
    path = item.path
    need(len(path) > 1, f"rule 21: {name} has no path")
    need(abs(path[0].time - item.start) <= TOLERANCE, f"rule 21: {name} starts off its path")
    need(abs(path[-1].time - item.end) <= TOLERANCE, f"rule 21: {name} ends off its path")
    for before, after in zip(path, path[1:], strict=False):
        need(after.time >= before.time, f"rule 21: the path of {name} goes back in time")
        need(after.y <= before.y + EPS, f"rule 21: {name} moves down")
        if before.y - after.y > EPS:
            need(
                after.time - before.time <= glide + TOLERANCE,
                f"rule 21: {name} glides for {after.time - before.time} s",
            )


def _rule_21_rows(lines: Sequence[LineElement], index: int) -> None:
    """The rows of one lyric line move together: the same times, the same offsets."""
    line, above = lines[index], lines[index - 1]
    follow = [(k.time, k.y - line.text_y) for k in line.path]
    leads = [(k.time, k.y - above.text_y) for k in above.path]
    need(
        len(follow) == len(leads)
        and all(
            abs(a[0] - b[0]) <= TOLERANCE and abs(a[1] - b[1]) <= TOLERANCE
            for a, b in zip(follow, leads, strict=True)
        ),
        f"rule 21: row {index} does not move with the row above",
    )


def _rule_21_still(lines: Sequence[LineElement], index: int, view: ScrollView, end: float) -> None:
    """The line being sung stands still at its place, with its block centred on ``current``.

    It may only glide out during its last ``min_glide`` seconds (ADR-0036), never in before. A
    line wrapped onto rows glides as one: each row counts by the singing of the whole line, from
    its first row's first syllable to ``end``, its last row's last syllable.
    """
    line = lines[index]
    first = lines[index - line.row].sing_start
    start = max(end - view.min_glide, first) - TOLERANCE
    for before, after in zip(line.path, line.path[1:], strict=False):
        if abs(before.y - after.y) > EPS:
            sung = after.time > first + EPS and before.time < end - EPS
            need(not sung or before.time >= start, f"rule 21: line {index} moves while it is sung")
    current = view.current
    need(abs(line.y_at(first) - line.text_y) <= TOLERANCE, f"rule 21: line {index}")
    if not is_later_row(lines, index):
        rows = block_of(lines, index)
        middle = (rows[0].box.y + rows[-1].box.bottom) / 2
        need(
            abs(middle - current) <= TOLERANCE,
            f"rule 21: line {index} is not at the current height",
        )


def _rule_21_calm(lines: Sequence[LineElement], min_glide: float) -> None:
    """A glide takes at least ``min_glide``, unless it starts as the column comes to rest.

    The first glide (into the first line), a glide that starts at the end of the glide before
    (the stop between them was too short) and a glide out of a line that is sung for less than
    ``min_glide``, which starts with its first syllable, may be shorter (ADR-0036). A line wrapped
    onto rows counts as a whole, from its first row's first syllable to its last row's last.
    """
    ends = line_ends(lines)
    brief = [
        x.sing_start
        for i, x in enumerate(lines)
        if not is_later_row(lines, i) and ends[i] - x.sing_start <= min_glide + TOLERANCE
    ]
    glides = sorted(
        {
            (before.time, after.time)
            for line in lines
            for before, after in zip(line.path, line.path[1:], strict=False)
            if before.y - after.y > EPS
        }
    )
    rested = [float("-inf")]
    for start, end in glides:
        if end - start < min_glide - TOLERANCE and len(rested) > 1:
            need(
                abs(start - rested[-1]) <= TOLERANCE
                or any(abs(start - first) <= TOLERANCE for first in brief),
                f"rule 21: the glide at {start} takes {end - start} s, shorter than {min_glide} s",
            )
        if end > rested[-1] + TOLERANCE:
            rested.append(end)


def _rule_21_safe(item: Moving, name: str, safe: Rect) -> None:
    """A row that stands still lies inside the safe area; one that glides may not."""
    for before, after in zip(item.path, item.path[1:], strict=False):
        if abs(before.y - after.y) <= EPS and after.time > before.time:
            need(
                vertical_inside(item.box_at(before.time), safe),
                f"rule 21: {name} leaves the safe area at {before.time}",
            )


def _moments(items: Sequence[Moving]) -> list[float]:
    """Return the times at which the paths turn, and the middle of every stretch between them."""
    times = sorted({k.time for item in items for k in item.path})
    return sorted({*times, *((a + b) / 2 for a, b in zip(times, times[1:], strict=False))})


def _rule_21_column(lines: Sequence[LineElement]) -> None:
    """Rows never overlap, at any keyframe or in the middle of a glide, and stay in order."""
    for time in _moments(lines):
        shown = [(i, x.box_at(time)) for i, x in enumerate(lines) if x.start <= time < x.end]
        for (first, above), (second, below) in zip(shown, shown[1:], strict=False):
            need(
                not above.overlaps(below) and above.y <= below.y + TOLERANCE,
                f"rule 21: rows {first} and {second} overlap or change places at {time}",
            )


def _rule_21_together(moving: Sequence[Moving]) -> None:
    """In every glide everything on screen in the column moves by the same distance (ADR-0033).

    The paths are straight between the times any of them turns, so it is enough to compare the
    distance each element moves between two such times, for those that are on screen over both.
    """
    times = sorted({k.time for item in moving for k in item.path})
    moved: dict[int, float] = {}
    for item in moving:
        for number, (low, high) in enumerate(zip(times, times[1:], strict=False)):
            if item.start <= low + EPS and high <= item.end + EPS:
                distance = item.y_at(low) - item.y_at(high)
                same = moved.setdefault(number, distance)
                need(
                    abs(distance - same) <= TOLERANCE,
                    f"rule 21: the column does not glide together between {low} and {high}",
                )


def _rule_21_parts(lines: Sequence[LineElement], breaks: Sequence[CardElement]) -> None:
    """The column starts again after a break screen: its lines come in from below as it ends.

    No line is on screen from the start of a break screen to its end, and the first line after
    it (the line sung next) comes in by a glide that starts when the screen ends (ADR-0040).
    """
    for number, card in enumerate(breaks):
        for index, line in enumerate(lines):
            need(
                line.end <= card.start + TOLERANCE or line.start >= card.end - TOLERANCE,
                f"rule 21: line {index} is on screen in break screen {number}",
            )
        first = next((x for x in lines if x.sing_start >= card.end - TOLERANCE), None)
        need(
            first is not None
            and len(first.path) > 1
            and abs(first.path[0].time - card.end) <= TOLERANCE
            and first.path[0].y > first.path[1].y,
            f"rule 21: the column does not glide in from below after break screen {number}",
        )


def rule_21_scroll_path(scene: Scene, profile: Profile) -> None:
    """The column moves only in glides, and the line being sung stands still (ADR-0033).

    Outside scroll mode nothing has a path. In scroll mode the path of every row runs from its
    start to its end and only goes up, each move at most ``scroll.glide`` seconds long; the line
    being sung stands still from its first syllable to its last, except that it glides out in its
    last ``scroll.min_glide`` seconds (a line wrapped onto rows counts as a whole), with its block
    centred on the current height; a glide takes at least ``scroll.min_glide`` unless it starts as
    the column comes to rest; a row that stands still lies inside the safe area; rows never
    overlap at a keyframe or in the middle of a glide, and stay in the order they are sung; in
    every glide everything on screen moves by the same distance; no row is on screen during a
    break screen, and the column comes in from below when it ends (ADR-0040).
    """
    lines, view = scene.lines(), scene.scroll
    if profile.mode != "scroll":
        need(view is None and not any(x.path for x in lines), "rule 21: a path without scroll mode")
        return
    need(view is not None, "rule 21: a scroll look without the measures of its column")
    assert view is not None  # told above
    reported = any(s.kind == "block" for s in scene.shortfalls)
    ends = line_ends(lines)
    for index, line in enumerate(lines):
        _rule_21_path(line, f"line {index}", view.glide)
        if is_later_row(lines, index):
            _rule_21_rows(lines, index)
        if not reported:
            _rule_21_still(lines, index, view, ends[index])
            _rule_21_safe(line, f"line {index}", scene.safe)
    breaks = scene.cards("break")
    _rule_21_parts(lines, breaks)
    _rule_21_calm(lines, view.min_glide)
    _rule_21_column(lines)
    _rule_21_together(lines)


def _collide(first: SceneElement, second: SceneElement) -> bool:
    """Tell whether two elements that are on screen together touch at any moment of it.

    An element on a path is looked at where its path turns and in the middle of every stretch.
    """
    moving = [x for x in (first, second) if isinstance(x, Moving) and x.path]
    if not moving:
        return first.box.overlaps(second.box)
    low, high = max(first.start, second.start), min(first.end, second.end)
    times = [t for t in _moments(moving) if low <= t <= high]
    return any(_box(first, t).overlaps(_box(second, t)) for t in (low, high, *times))


def _box(element: SceneElement, time: float) -> Rect:
    """Return the box of ``element`` at ``time``; one on a path is where the path has it."""
    return element.box_at(time) if isinstance(element, Moving) else element.box


def no_overlap(scene: Scene, profile: Profile) -> None:
    """No two elements that are on screen at the same time overlap.

    Lines on their paths in scroll mode are checked against each other by rule 21, and against
    the notice of a break there too; everything else is checked here, on its path where it has one.
    """
    del profile
    elements: Sequence[SceneElement] = scene.elements
    for index, first in enumerate(elements):
        for second in elements[index + 1 :]:
            together = min(first.end, second.end) - max(first.start, second.start)
            if together <= TOLERANCE:
                continue
            if isinstance(first, LineElement) and isinstance(second, LineElement) and first.path:
                continue
            need(
                not _collide(first, second),
                f"two elements overlap: {first.kind} {first.start}-{first.end} and "
                f"{second.kind} {second.start}-{second.end}",
            )
