"""Fail if a make target listed in ``CI_TARGETS`` has no job of the same name in the workflow."""

import re
import sys
from pathlib import Path

CI_TARGETS = re.compile(r"^CI_TARGETS\s*:?=\s*(?P<names>.*)$", re.MULTILINE)
JOB = re.compile(r"^  (?P<name>[\w-]+):\s*$", re.MULTILINE)


def ci_targets(makefile: str) -> list[str]:
    """Return the targets that the Makefile says CI must cover."""
    match = CI_TARGETS.search(makefile)
    return match.group("names").split() if match else []


def job_blocks(workflow: str) -> dict[str, str]:
    """Split a workflow file into its jobs: job name to the text of that job."""
    start = workflow.find("\njobs:")
    if start < 0:
        return {}
    body = workflow[start:]
    matches = list(JOB.finditer(body))
    return {
        m.group("name"): body[m.end() : matches[i + 1].start() if i + 1 < len(matches) else None]
        for i, m in enumerate(matches)
    }


def missing_targets(makefile: str, workflow: str) -> list[str]:
    """Return the CI targets that no job covers (job of that name running ``make <target>``)."""
    jobs = job_blocks(workflow)
    return [
        target
        for target in ci_targets(makefile)
        if target not in jobs or not re.search(rf"make\s+{re.escape(target)}\b", jobs[target])
    ]


def main(argv: list[str]) -> int:
    """Compare ``Makefile`` and the workflow file and print what is missing."""
    makefile = Path(argv[0] if argv else "Makefile").read_text(encoding="utf-8")
    workflow = Path(argv[1] if len(argv) > 1 else ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )
    if not ci_targets(makefile):
        print("Makefile: CI_TARGETS is missing or empty")
        return 1
    missing = missing_targets(makefile, workflow)
    for target in missing:
        print(f".github/workflows/ci.yml: no job runs 'make {target}'")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
