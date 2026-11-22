"""Print only the failures of the last run, read from ``reports/``.

For every gate whose status file is non-zero, print ``file:line: message`` lines where the
tool's output has them (and JUnit XML for the tests), otherwise the last lines of the output.
"""

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

LOCATION = re.compile(
    r"^(?:(?:ERROR|WARN)\s+)?(?P<file>[\w./\\-]+\.\w+)(?::(?P<line>\d+))?(?::\d+(?:-\d+)?)?:\s+"
    r"(?P<msg>\S.*)$"
)
IMPORT = re.compile(r"^-\s+(?P<module>[\w.]+) -> (?P<target>[\w.]+) \(l\.(?P<line>\d+)\)\s*$")
TRACE_LOCATION = re.compile(r"(?P<file>[\w./\\-]+\.py):(?P<line>\d+)")
CLONE = re.compile(r"^ - (?P<file>\S+) \[(?P<line>\d+):\d+ - \d+:\d+\] \((?P<size>\d+) lines")
CLONE_COPY = re.compile(r"^ {3}(?P<file>\S+) \[(?P<line>\d+):\d+ - \d+:\d+\]\s*$")
SOURCE_ROOTS = ("", "src", "tools", "tests")
TAIL_LINES = 10


def module_path(module: str) -> str:
    """Map a dotted module name of the ``src`` layout to its file path (best effort)."""
    base = Path("src", *module.split("."))
    package = base / "__init__.py"
    return str(package if package.exists() else base.with_suffix(".py"))


def resolve_path(path: str) -> str:
    """Find the repository path of a file that a tool printed relative to a source root."""
    for root in SOURCE_ROOTS:
        candidate = Path(root, path)
        if candidate.exists():
            return str(candidate)
    return path


def parse_text(text: str) -> list[str]:
    """Extract ``file:line: message`` entries from a tool's text output.

    Understands ``file[:line[:col]]: message`` (Ruff, Pyrefly, vulture, deptry, ...) and
    import-linter's ``module -> module (l.N)`` lines. Falls back to the last lines.
    """
    found: list[str] = []
    clone: re.Match[str] | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if clone is not None and (copy := CLONE_COPY.match(line)):
            first = f"{resolve_path(clone['file'])}:{clone['line']}"
            other = f"{resolve_path(copy['file'])}:{copy['line']}"
            found.append(f"{first}: {clone['size']} duplicated lines, same as {other}")
            clone = None
            continue
        clone = CLONE.match(line)
        imported = IMPORT.match(line.strip())
        location = LOCATION.match(line)
        if imported:
            where = f"{module_path(imported['module'])}:{imported['line']}"
            found.append(f"{where}: imports {imported['target']} (forbidden by a layer contract)")
        elif location:
            where = location["file"] + (f":{location['line']}" if location["line"] else "")
            found.append(f"{where}: {location['msg']}")
    if found:
        return list(dict.fromkeys(found))  # contracts may report the same line twice
    return [line for line in text.splitlines()[-TAIL_LINES:] if line.strip()]


def parse_junit(path: Path) -> list[str]:
    """Return one ``file:line: test - message`` entry per failed or errored test."""
    found: list[str] = []
    for case in ET.parse(path).getroot().iter("testcase"):
        for problem in [*case.findall("failure"), *case.findall("error")]:
            body = problem.text or ""
            places = TRACE_LOCATION.findall(body)
            own = [p for p in places if not p[0].startswith((".venv", ".cache"))] or places
            place = f"{own[-1][0]}:{own[-1][1]}" if own else case.get("classname", "?")
            message = (problem.get("message") or "").splitlines()
            first = message[0] if message else "failed"
            found.append(f"{place}: {case.get('name')} - {first}")
    return found


def summarize(reports: Path) -> list[str]:
    """Build the summary lines for every failed gate found in ``reports``."""
    lines: list[str] = []
    for status in sorted(reports.glob("*.status")):
        if status.read_text(encoding="utf-8").strip() == "0":
            continue
        name = status.stem
        report = reports / f"{name}.txt"
        text = report.read_text(encoding="utf-8") if report.exists() else ""
        entries: list[str] = []
        junit = reports / f"{name}.xml"
        if junit.exists():
            entries = parse_junit(junit)
        if not entries:
            entries = parse_text(text)
        lines.append(f"{name}: FAILED")
        lines.extend(f"  {entry}" for entry in entries)
    return lines


def main(argv: list[str]) -> int:
    """Print the summary; exit 1 when anything failed or no reports exist."""
    reports = Path(argv[0]) if argv else Path("reports")
    if not any(reports.glob("*.status")):
        print("No reports found; run 'make check' first.")
        return 1
    lines = summarize(reports)
    print("\n".join(lines) if lines else "Nothing failed.")
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
