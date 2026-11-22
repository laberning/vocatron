"""Gate: the lines a change touches must be covered (ADR-0004, diff-cover).

Compares ``reports/coverage.xml`` with the base branch and fails below ``--fail-under`` percent.
Committed, staged, unstaged and untracked (not ignored) changes all count.
Before the first push there is no ``origin/main``; then the gate passes and says it was skipped.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

FAIL_UNDER = 90


def ref_exists(ref: str) -> bool:
    """Tell whether ``ref`` names a commit in this repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def main(argv: list[str]) -> int:
    """Run diff-cover against the base branch, or skip when it does not exist yet."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="branch to compare with")
    parser.add_argument("--coverage", type=Path, default=Path("reports/coverage.xml"))
    parser.add_argument("--fail-under", type=int, default=FAIL_UNDER)
    args = parser.parse_args(argv)
    if not ref_exists(args.base):
        print(f"diff-cover skipped: no {args.base} yet")
        return 0
    if not args.coverage.exists():
        print(f"{args.coverage}: no coverage data; the fast tests did not run")
        return 1
    command = [
        sys.executable,
        "-m",
        "diff_cover.diff_cover_tool",
        str(args.coverage),
        f"--compare-branch={args.base}",
        f"--fail-under={args.fail_under}",
        "--include-untracked",  # new modules of uncommitted work are untracked until committed
    ]
    return subprocess.run(command, check=False, env=git_env(os.environ)).returncode


def git_env(base: dict[str, str] | os._Environ[str]) -> dict[str, str]:
    r"""Return ``base`` plus ``core.quotepath=false`` for the git calls of diff-cover only.

    Git escapes non-ASCII bytes in the paths it prints by default (``Verd\303\244chtig.txt``),
    and diff-cover then cannot open the file. The setting is passed through the environment, so
    no git configuration changes.
    """
    env = dict(base)
    count = int(env.get("GIT_CONFIG_COUNT", "0"))
    env[f"GIT_CONFIG_KEY_{count}"] = "core.quotepath"
    env[f"GIT_CONFIG_VALUE_{count}"] = "false"
    env["GIT_CONFIG_COUNT"] = str(count + 1)
    return env


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
