"""Helpers of the end-to-end test on the demo song (stage 2) that need no GPU, tested in stage 1.

The references hold numbers only: the start of every word and the seconds of five frames; the
words themselves are never written down here (AGENTS.md).
"""

import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from vocatron.core.scene import Scene

MEDIAN_LIMIT = 0.1  # seconds: median error of the word starts
WORST_LIMIT = 1.0  # seconds: no word may be further off than this
TITLE_SECONDS = 1.0
INTO_LINE = 0.5  # seconds after a line starts to sing: the sweep is under way
FIRST_LINE = "first-line"
LINE_SHARES = (("quarter-line", 1, 4), ("middle-line", 1, 2), ("late-line", 3, 4))


class DemoNames(NamedTuple):
    """Where the end-to-end test of one language keeps its files.

    Attributes:
        references: The folder of the stored references, below ``tests/slow/golden/demo``.
        make: The folder ``make`` runs in, below ``.corpus/demo``.
        sheet: The contact sheet of the golden frames, in ``reports/``.
        log: The log file, in ``.cache/logs/``.
    """

    references: str
    make: str
    sheet: str
    log: str


def demo_names(language: str) -> DemoNames:
    """Return the names the demo test of ``language`` uses (no song's run touches another's)."""
    return DemoNames(
        references=language,
        make=f"make-{language}",
        sheet=f"contact-sheet-demo-{language}.png",
        log=f"stage2-demo-{language}.log",
    )


@dataclass(frozen=True)
class Reference:
    """The stored reference of the demo song.

    Attributes:
        starts: The start of every word in seconds, in song order.
        frames: The seconds of each of the five golden frames, by name.
    """

    starts: list[float]
    frames: dict[str, float]


@dataclass(frozen=True)
class Errors:
    """How far the found word starts are from the reference.

    Attributes:
        median: The median absolute error in seconds.
        worst: The largest absolute error in seconds.
        count: How many words were compared.
    """

    median: float
    worst: float
    count: int


def start_errors(found: list[float], reference: list[float]) -> Errors:
    """Compare word starts with the reference.

    Raises:
        ValueError: If the two lists differ in length (the lyrics changed).
    """
    if len(found) != len(reference):
        raise ValueError(f"{len(found)} words found, the reference has {len(reference)}")
    if not found:
        raise ValueError("no words to compare")
    errors = [abs(a - b) for a, b in zip(found, reference, strict=True)]
    return Errors(statistics.median(errors), max(errors), len(errors))


def verdict(errors: Errors) -> str | None:
    """Return why the errors are too large (numbers only), or ``None`` when they are fine."""
    if errors.median > MEDIAN_LIMIT:
        return f"median start error {errors.median * 1000:.0f} ms (limit {MEDIAN_LIMIT * 1000:.0f})"
    if errors.worst > WORST_LIMIT:
        return f"worst start error {errors.worst:.2f} s (limit {WORST_LIMIT:.1f})"
    return None


def frame_moments(scene: Scene) -> dict[str, float]:
    """Choose the five seconds of the golden frames: the title and four moments in lines."""
    lines = scene.lines()
    chosen = {"title": TITLE_SECONDS, FIRST_LINE: lines[0].sing_start + INTO_LINE}
    for name, numerator, denominator in LINE_SHARES:
        line = lines[len(lines) * numerator // denominator]
        chosen[name] = line.sing_start + INTO_LINE
    return chosen


def write_reference(path: Path, reference: Reference) -> None:
    """Write the reference as JSON (rounded to the millisecond)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "starts": [round(start, 3) for start in reference.starts],
        "frames": {name: round(seconds, 3) for name, seconds in reference.frames.items()},
    }
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def read_reference(path: Path) -> Reference:
    """Read a reference written by ``write_reference``."""
    data = json.loads(path.read_text("utf-8"))
    return Reference([float(x) for x in data["starts"]], dict(data["frames"]))
