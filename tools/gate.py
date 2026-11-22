"""Run one quality gate and record its result in ``reports/``.

Usage: ``python tools/gate.py <name> [--reports DIR] -- <command...>``

The command's combined output goes to the console and to ``reports/<name>.txt``; its exit code
goes to ``reports/<name>.status``. ``tools/summary.py`` reads both.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def run_gate(name: str, command: list[str], reports: Path) -> int:
    """Run ``command`` as the gate ``name`` and write its report and status files.

    Args:
        name: Gate name, used as the report file stem.
        command: The command line to run.
        reports: Folder for the report files; created if missing.

    Returns:
        The exit code of the command (127 when it cannot be started).
    """
    reports.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "NO_COLOR": "1"},  # plain text in the reports
        )
        output = ANSI.sub("", result.stdout + result.stderr)  # some tools ignore NO_COLOR
        code = result.returncode
    except OSError as error:
        output = f"cannot run {command[0]}: {error}\n"
        code = 127
    (reports / f"{name}.txt").write_text(output, encoding="utf-8")
    (reports / f"{name}.status").write_text(f"{code}\n", encoding="utf-8")
    sys.stdout.write(output)
    print(f"[gate {name}] {'ok' if code == 0 else f'FAILED (exit {code})'}")
    return code


def main(argv: list[str]) -> int:
    """Parse the command line (options, ``--``, command) and run the gate."""
    head, separator, command = _split(argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--reports", type=Path, default=Path("reports"))
    args = parser.parse_args(head)
    if not separator or not command:
        parser.error("missing command after '--'")
    return run_gate(args.name, command, args.reports)


def _split(argv: list[str]) -> tuple[list[str], bool, list[str]]:
    """Split ``argv`` at the first ``--``."""
    if "--" not in argv:
        return argv, False, []
    index = argv.index("--")
    return argv[:index], True, argv[index + 1 :]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
