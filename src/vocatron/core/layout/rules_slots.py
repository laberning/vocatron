"""Rules 1 to 4: the safe area, the slots, the fit and the alignment of the lines.."""

from vocatron.core.layout.rules_base import (
    EPS,
    TOLERANCE,
    RuleBroken,
    boxes,
    is_later_row,
    need,
)
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    LineElement,
    PreviewElement,
    Scene,
)


def rule_1_safe_area(scene: Scene, profile: Profile) -> None:
    """Every text box lies inside the safe area."""
    del profile
    for label, box in boxes(scene):
        need(box.inside(scene.safe), f"rule 1: a {label} box {box} leaves the safe area")
    for slot in [*scene.slots, *([scene.preview_row] if scene.preview_row else [])]:
        need(slot.inside(scene.safe), "rule 1: a slot or the preview row leaves the safe area")


def rule_2_slots(scene: Scene, profile: Profile) -> None:
    """At most ``slots`` lines are visible at once (the rows of a line count as one).

    With ``page.slot_per_row`` every row takes a slot, so at most ``slots`` rows are visible. In
    scroll mode (ADR-0033) the lines around the one being sung are at most ``before + after + 1``
    when the column stands still (not at the first syllable of a line sung for ``min_glide`` or
    less that glides out as it begins, ADR-0036), one more while it glides.
    """
    lines = scene.lines()
    counted = [
        x for i, x in enumerate(lines) if profile.page.slot_per_row or not is_later_row(lines, i)
    ]
    most = profile.slots
    if scene.scroll is not None:  # the line being sung, those around it, and one gliding in or out
        most = scene.scroll.before + scene.scroll.after + 2
    for line in lines:
        for time in (line.start, line.sing_start, line.sing_end - TOLERANCE):
            shown = [x for x in counted if x.visible(time)]
            need(len(shown) <= most, f"rule 2: {len(shown)} lines visible at {time}")
        if scene.scroll is not None and not _glides_from_first_syllable(line):
            at_rest = [x for x in counted if x.visible(line.sing_start)]
            need(
                len(at_rest) <= scene.scroll.before + scene.scroll.after + 1,
                f"rule 2: {len(at_rest)} lines visible at rest at {line.sing_start}",
            )


def _glides_from_first_syllable(line: LineElement) -> bool:
    """Whether a glide of the line starts at its first syllable (a brief line, ADR-0036)."""
    return any(
        abs(before.y - after.y) > EPS
        and before.time <= line.sing_start + TOLERANCE
        and after.time > line.sing_start + EPS
        for before, after in zip(line.path, line.path[1:], strict=False)
    )


def rule_3_fit(scene: Scene, profile: Profile) -> None:
    """No line is wider than the safe area; a shrunk line is not below ``min_size``."""
    reported = {s.line for s in scene.shortfalls if s.kind == "too-wide"}
    smallest = profile.font.min_size * scene.safe.h
    for index, line in enumerate(scene.lines()):
        need(line.box.w <= scene.safe.w + TOLERANCE, f"rule 3: line {index} is too wide")
        need(line.size >= smallest - TOLERANCE or index in reported, f"rule 3: line {index}")
        need(
            line.size <= profile.font.size * scene.safe.h + TOLERANCE,
            f"rule 3: line {index} is larger than font.size",
        )


def rule_4_alignment(scene: Scene, profile: Profile) -> None:
    """Lines are aligned as the profile says and stay in their slot; previews in their row.

    In scroll mode there are no slots: a line stands at the current height (rule 21).
    """
    for preview in (e for e in scene.elements if isinstance(e, PreviewElement)):
        row = scene.preview_row
        if row is None:
            raise RuleBroken("rule 4: a preview without a preview row")
        need(preview.box.inside(row), f"rule 4: preview of {preview.of_line}")
        need(preview.box.y >= max(s.bottom for s in scene.slots) - TOLERANCE, "rule 4")
    lines = scene.lines()
    for index, line in enumerate(lines):
        if scene.scroll is None:
            need(line.box.inside(scene.slots[line.slot]), f"rule 4: line {index} leaves its slot")
        need(line.row < profile.line_rows, f"rule 4: line {index} is row {line.row + 1} of a line")
        if line.row:
            above = lines[index - 1]
            need(
                (above.row, above.start, above.end) == (line.row - 1, line.start, line.end),
                f"rule 4: row {index} does not belong to the row above",
            )
            if scene.scroll is None:
                below = above.slot + profile.page.slot_per_row
                need(line.slot == below, f"rule 4: row {index} is not in the slot it belongs in")
            need(line.box.y >= above.box.bottom - TOLERANCE, f"rule 4: row {index} is not below")
            need(line.sing_start >= above.sing_end - TOLERANCE, f"rule 4: row {index} sung early")
        if profile.align == "center":
            middle = line.box.x + line.box.w / 2
            need(abs(middle - (scene.safe.x + scene.safe.w / 2)) <= TOLERANCE, f"rule 4: {index}")
