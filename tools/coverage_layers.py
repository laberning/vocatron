"""Check the branch coverage of each layer against its minimum (ADR-0004).

Reads ``reports/coverage.json`` (written by ``coverage json``). A layer without any code yet
is reported and passes.
"""

import json
import sys
from pathlib import Path
from typing import NamedTuple


class Summary(NamedTuple):
    """Statement and branch counts of one source file."""

    statements: int
    covered: int
    branches: int
    covered_branches: int


MINIMUM = {"core": 95.0, "lab": 95.0, "stages": 90.0, "cli": 80.0, "engines": 60.0}


def layer_of(path: str) -> str | None:
    """Return the layer a source file belongs to, or ``None`` for top-level modules."""
    parts = Path(path).parts
    if "vocatron" not in parts:
        return None
    rest = parts[parts.index("vocatron") + 1 :]
    return rest[0] if len(rest) > 1 and rest[0] in MINIMUM else None


def parse_report(raw: object) -> dict[str, Summary]:
    """Read the per-file summaries out of a coverage.py JSON report.

    Raises:
        ValueError: If the report does not have the expected shape.
    """
    files = raw.get("files") if isinstance(raw, dict) else None
    if not isinstance(files, dict):
        raise ValueError("not a coverage.py JSON report (no 'files')")
    result: dict[str, Summary] = {}
    for path, entry in files.items():
        summary = entry.get("summary") if isinstance(entry, dict) else None
        if not isinstance(summary, dict):
            raise ValueError(f"{path}: no summary")
        result[str(path)] = Summary(
            statements=int(summary["num_statements"]),
            covered=int(summary["covered_lines"]),
            branches=int(summary.get("num_branches", 0)),
            covered_branches=int(summary.get("covered_branches", 0)),
        )
    return result


def layer_percentages(files: dict[str, Summary]) -> dict[str, float | None]:
    """Compute branch coverage per layer.

    Returns:
        Percentage per layer; ``None`` when the layer has no statements yet.
    """
    covered = dict.fromkeys(MINIMUM, 0)
    total = dict.fromkeys(MINIMUM, 0)
    for path, summary in files.items():
        layer = layer_of(path)
        if layer is None:
            continue
        covered[layer] += summary.covered + summary.covered_branches
        total[layer] += summary.statements + summary.branches
    return {k: (100.0 * covered[k] / total[k] if total[k] else None) for k in MINIMUM}


def check(files: dict[str, Summary]) -> tuple[list[str], bool]:
    """Return report lines and whether every layer meets its minimum."""
    lines: list[str] = []
    ok = True
    for layer, percent in layer_percentages(files).items():
        need = MINIMUM[layer]
        if percent is None:
            lines.append(f"{layer}: no code yet (minimum {need:.0f} %)")
        elif percent < need:
            ok = False
            lines.append(f"{layer}: coverage {percent:.1f} % is below the minimum {need:.0f} %")
        else:
            lines.append(f"{layer}: coverage {percent:.1f} % (minimum {need:.0f} %)")
    return lines, ok


def main(argv: list[str]) -> int:
    """Read the coverage report named by ``argv[0]`` and print the verdict."""
    path = Path(argv[0]) if argv else Path("reports/coverage.json")
    if not path.exists():
        print(f"{path}: no coverage data; the tests did not run")
        return 1
    lines, ok = check(parse_report(json.loads(path.read_text(encoding="utf-8"))))
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
