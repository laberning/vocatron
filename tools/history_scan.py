"""Scan every commit of the git history for things that must not be in a public repository.

``make history-scan`` runs this. It reads the whole history (every branch and tag, every commit
message, every added line and every path that was ever added, even when it was deleted later) and
looks for: names of other projects, planning-vault content and local paths of this machine,
audio, model and stem files, real lyrics files outside ``tests/data/demo/``, the local corpus,
agent files, and secrets.

The report names the kind of finding, how many there are and the ids of the commits that hold
them. **It never prints what matched** (lyrics and private text stay out of terminals and logs);
look at a commit with ``git show <id>``. The names of other projects are not written in this
repository: put them, one regular expression per line, in ``.cache/history-scan-names.txt`` (or
the file given with ``--names``). The exit code is 1 when anything was found.
"""

import argparse
import getpass
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

CLONE = Path(__file__).resolve().parents[1]
DEFAULT_NAMES = CLONE / ".cache" / "history-scan-names.txt"
SHORT = 10  # characters of a commit id in the report
START = "\x01"  # marks the first line of a commit in the log stream
DEMO_FOLDER = "tests/data/demo/"


@dataclass(frozen=True)
class Rule:
    """One kind of finding.

    Attributes:
        kind: The name shown in the report.
        text: A pattern for added lines and commit messages, or ``None``.
        path: A pattern for the paths of added or changed files, or ``None``.
        allowed: A pattern for paths where the finding is fine, or ``None``.
    """

    kind: str
    text: re.Pattern[str] | None = None
    path: re.Pattern[str] | None = None
    allowed: re.Pattern[str] | None = None


def compile_(pattern: str) -> re.Pattern[str]:
    """Compile a case-insensitive pattern."""
    return re.compile(pattern, re.IGNORECASE)


SECRETS = (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    r"\bhf_[A-Za-z0-9]{30,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bxox[abp]-[A-Za-z0-9-]{10,}",
    r"(?:api[_-]?key|secret|token|password)\s*[=:]\s*['\"][^'\"\s]{12,}['\"]",
)


def build_rules(home_name: str, names: Iterable[str] = ()) -> list[Rule]:
    """Return the rules for a machine whose user is ``home_name``, plus project ``names``."""
    rules = [
        Rule("local path", text=compile_(rf"/(?:home|Users)/{re.escape(home_name)}\b")),
        Rule(
            "vault or Windows path",
            text=compile_(r"Obsidian[O]neDrive|/mnt/[a-z]/|\b[A-Z]:\\Users"),
        ),
        Rule("secret", text=compile_("|".join(SECRETS))),
        Rule(
            "audio file",
            path=compile_(r"\.(?:mp3|flac|wav|ogg|opus|m4a|aac|wma|mp4|mkv|webm|avi|mov)$"),
        ),
        Rule(
            "model or weights file",
            path=compile_(r"\.(?:ckpt|pt|pth|safetensors|onnx|gguf|bin|h5)$"),
        ),
        Rule(
            "lyrics file outside the demo folder",
            path=compile_(r"\.lrc$|(?:^|/)lyrics\.(?:json|txt)$"),
            allowed=compile_(f"^{re.escape(DEMO_FOLDER)}"),
        ),
        Rule("local corpus", path=compile_(r"^\.corpus/")),
        Rule("agent file", path=compile_(r"^(?:AGENTS|CLAUDE)\.md$|^\.claude/")),
    ]
    rules.extend(Rule(f"project name {i}", text=compile_(n)) for i, n in enumerate(names, 1) if n)
    return rules


def read_names(path: Path) -> list[str]:
    """Return the project-name patterns in ``path`` (one per line; ``#`` starts a comment)."""
    if not path.is_file():
        return []
    lines = (
        line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines()
    )
    return [line for line in lines if line]


def scan_lines(lines: Iterable[str], rules: list[Rule]) -> dict[str, list[str]]:
    """Scan a ``git log -p`` stream; return the commit ids per kind of finding (sorted, unique).

    The stream has a line of ``START`` and the commit id at the start of each commit, then the
    message, then the diff. Only added lines of the diff and the paths of the files are looked at.
    """
    found: dict[str, set[str]] = defaultdict(set)
    commit = ""
    path = ""
    in_diff = False
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith(START):
            commit, path, in_diff = line[1 : SHORT + 1], "", False
            continue
        if line.startswith("diff --git "):
            in_diff = True
            path = line.rsplit(" b/", 1)[-1]
            for rule in rules:
                if rule.path and rule.path.search(path) and not _allowed(rule, path):
                    found[rule.kind].add(commit)
            continue
        if in_diff and (not line.startswith("+") or line.startswith("+++")):
            continue
        text = line[1:] if in_diff else line
        for rule in rules:
            if rule.text and rule.text.search(text) and not _allowed(rule, path):
                found[rule.kind].add(commit)
    return {kind: sorted(ids) for kind, ids in found.items()}


def _allowed(rule: Rule, path: str) -> bool:
    """Return whether ``rule`` accepts a finding in ``path``."""
    return bool(rule.allowed and rule.allowed.search(path))


def git_log(repo: Path) -> Iterator[str]:
    """Yield the lines of the whole history of ``repo``: every ref, message and diff."""
    process = subprocess.Popen(
        [
            "git",
            "-C",
            str(repo),
            "log",
            "--all",
            "--reverse",
            "--no-color",
            "--no-renames",
            "--diff-merges=first-parent",  # a merge's own changes (a conflict fix) count too
            "--no-textconv",
            "-p",
            f"--format={START}%H%n%B",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    yield from process.stdout or ()
    _, error = process.communicate()
    if process.returncode:
        raise RuntimeError(f"git log failed: {error.strip()[-300:]}")


def commit_count(repo: Path) -> int:
    """Return the number of commits reachable from any ref."""
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--all", "--count"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(result.stdout)


def report(found: dict[str, list[str]], commits: int) -> list[str]:
    """Return the report lines: counts and commit ids, never the matched text."""
    lines = [f"scanned {commits} commits"]
    if not found:
        lines.append("no findings")
        return lines
    for kind in sorted(found):
        ids = found[kind]
        lines.append(f"{kind}: {len(ids)} commits: {' '.join(ids)}")
    return lines


def main(argv: list[str]) -> int:
    """Scan the history and print the report; return 1 when there are findings."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--repo", type=Path, default=CLONE)
    parser.add_argument("--names", type=Path, default=DEFAULT_NAMES)
    args = parser.parse_args(argv)
    names = read_names(args.names)
    if not names:
        print(f"note: no project names in {args.names}; that kind of finding is not checked")
    found = scan_lines(git_log(args.repo), build_rules(getpass.getuser(), names))
    print("\n".join(report(found, commit_count(args.repo))))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
