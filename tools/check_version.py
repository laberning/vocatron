"""Fail if a release tag does not match the version in ``pyproject.toml`` and the changelog.

``make tag-check TAG=v0.1.0`` runs this; CI runs it on every pushed tag that starts with ``v``.
The tag ``vX.Y.Z`` must equal ``version = "X.Y.Z"`` of the project, and ``CHANGELOG.md`` must
have a section ``## [X.Y.Z]``.
"""

import re
import sys
import tomllib
from pathlib import Path

CLONE = Path(__file__).resolve().parents[1]
TAG = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$")


def problems(tag: str, pyproject: str, changelog: str) -> list[str]:
    """Return what is wrong with ``tag`` given the two files' texts (empty when it matches)."""
    match = TAG.match(tag)
    if not match:
        return [f"tag '{tag}' is not of the form vMAJOR.MINOR.PATCH"]
    wanted = match.group("version")
    version = str(tomllib.loads(pyproject).get("project", {}).get("version", ""))
    found = []
    if version != wanted:
        found.append(f"tag '{tag}' says {wanted} but pyproject.toml has version {version or '?'}")
    if not re.search(rf"^## \[{re.escape(wanted)}\]", changelog, re.MULTILINE):
        found.append(f"CHANGELOG.md has no section '## [{wanted}]'")
    return found


def main(argv: list[str]) -> int:
    """Check the tag given as the only argument against the files of the clone."""
    if len(argv) != 1:
        print("usage: check_version.py vMAJOR.MINOR.PATCH")
        return 2
    found = problems(
        argv[0],
        (CLONE / "pyproject.toml").read_text(encoding="utf-8"),
        (CLONE / "CHANGELOG.md").read_text(encoding="utf-8"),
    )
    print("\n".join(found) if found else f"tag {argv[0]} matches the version and the changelog")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
