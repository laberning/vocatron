"""Stage 1 checks of the documentation rules: callouts and Mermaid diagrams (ADR-0003), no ADR links
on pages for users, no credits for people, no history wording, no private places."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

import history_scan

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
CALLOUT = re.compile(r"^\s*>\s*\[!", re.MULTILINE)
FENCE = re.compile(
    r"^(?P<indent>[ \t]*)```(?P<lang>\w*)\n(?P<body>.*?)^(?P=indent)```", re.DOTALL | re.MULTILINE
)
HAND_DRAWN = re.compile(r"\A\s*---\s*\n\s*config:\s*\n\s*look:\s*handDrawn\s*\n\s*---\s*\n")
# Own colours, fixed themes and what GitHub's renderer does not support.
FORBIDDEN = re.compile(
    r"^\s*(?:style|classDef|class|linkStyle|click)\s|:::|\btheme(?:Variables)?\s*:|\bfa:|zenuml",
    re.MULTILINE | re.IGNORECASE,
)


def markdown_files() -> list[Path]:
    """Return the Markdown files of the docs site and of the repository root.

    Symlinks are left out: the agent files in the root are links to outside the repository.
    """
    return sorted(p for p in [*DOCS.rglob("*.md"), *ROOT.glob("*.md")] if not p.is_symlink())


def without_code(text: str) -> str:
    """Return ``text`` without its fenced code blocks, which may show syntax as an example."""
    return FENCE.sub("", text)


def mermaid_blocks(text: str) -> list[str]:
    """Return the bodies of the Mermaid blocks in ``text``."""
    return [m.group("body") for m in FENCE.finditer(text) if m.group("lang") == "mermaid"]


def test_site_pages_use_no_github_callouts() -> None:
    """Zensical does not render ``> [!note]``; only files read on GitHub may use it."""
    offenders = [
        str(path.relative_to(DOCS))
        for path in DOCS.rglob("*.md")
        if CALLOUT.search(without_code(path.read_text(encoding="utf-8")))
    ]
    assert offenders == []


def test_the_callout_pattern_matches_a_callout() -> None:
    assert CALLOUT.search("text\n> [!note]\n> body\n")
    assert not CALLOUT.search("write `> [!note]` in a README")
    assert not CALLOUT.search(without_code("```markdown\n> [!note]\n```\n"))


@pytest.mark.parametrize("path", markdown_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_mermaid_diagrams_follow_the_rules(path: Path) -> None:
    for body in mermaid_blocks(path.read_text(encoding="utf-8")):
        assert HAND_DRAWN.match(body), f"{path}: diagram does not start with the handDrawn config"
        assert not FORBIDDEN.search(body), f"{path}: {FORBIDDEN.search(body)}"


@pytest.mark.parametrize(
    "line",
    [
        "    style A fill:#f00",
        "    classDef x fill:#f00",
        "A:::x",
        "  theme: dark",
        "    click A call()",
        "A[fa:fa-car]",
        "zenuml",
    ],
)
def test_the_mermaid_rules_catch_a_violation(line: str) -> None:
    assert FORBIDDEN.search(line)


def test_the_mermaid_rules_accept_a_good_diagram() -> None:
    good = "---\nconfig:\n  look: handDrawn\n---\nflowchart LR\n    A[style profiles] --> B\n"
    assert HAND_DRAWN.match(good)
    assert not FORBIDDEN.search(good)
    assert not HAND_DRAWN.match("flowchart LR\n    A --> B\n")


def test_mermaid_blocks_are_found_also_when_indented() -> None:
    text = "text\n    ```mermaid\n    flowchart LR\n    ```\n```python\nx\n```\n"
    assert mermaid_blocks(text) == ["    flowchart LR\n"]


# ---- Rules of the public pages: the docs describe only the present ----------------------------

THIS_FILE = Path(__file__).resolve()
CHANGELOG = ROOT / "CHANGELOG.md"
USER_PAGES = [*(DOCS / "user").rglob("*.md"), DOCS / "index.md", ROOT / "README.md", CHANGELOG]
PRESENT_PAGES = [*USER_PAGES, *(DOCS / "dev").rglob("*.md")]
ADR_LINK = re.compile(r"adr/|\bADR-\d{4}")
# The one link a page for users may keep: the README row for developers.
README_ADR_ROW = re.compile(r"\[[^\]]*\]\(docs/adr/README\.md\)")
DECISION_CREDIT = re.compile(
    r"\([A-Z][\w'-]*(?: [A-Z][\w'-]*)*,\s*\d{4}-\d\d-\d\d[^);]*\)"  # (Name, 2026-11-02)
    r"|\b(?i:decided by) (?:[A-Z]|(?i:the (?:maintainer|owner|author))\b)"
    r"|\b[A-Z][\w-]*'s decision\b"
)
HISTORY = re.compile(
    r"before this change|made before|brings? back|the older|used to|previously|formerly"
    r"|as before|\bany ?more\b|(?:older|earlier) versions?",
    re.IGNORECASE,
)
PRIVATE = re.compile(
    r"/home/|/mnt/|file://|\b[A-Za-z]:\\|\[\[|\bVOC-\d+|vocatron-trials|Obsidian", re.IGNORECASE
)


def tracked_text_files() -> list[Path]:
    """Return the docs, root pages, source, tools and tests that rule 2 reads (not this file)."""
    paths = [*DOCS.rglob("*.md"), *ROOT.glob("*.md")]
    for folder in ("src", "tools", "tests"):
        paths += (ROOT / folder).rglob("*.py")
    return sorted(p for p in paths if not p.is_symlink() and p.resolve() != THIS_FILE)


def local_names() -> list[re.Pattern[str]]:
    """Return the names to look for from the local history-scan file (none in CI)."""
    return [history_scan.compile_(n) for n in history_scan.read_names(history_scan.DEFAULT_NAMES)]


def hits(
    path: Path, pattern: re.Pattern[str], *, skip: re.Pattern[str] | None = None
) -> Iterator[str]:
    """Yield ``file:line: text`` for each line of ``path`` that ``pattern`` matches."""
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = line if skip is None else skip.sub("", line)
        if pattern.search(text):
            yield f"{path.relative_to(ROOT)}:{number}"


def test_pages_for_users_link_no_adr() -> None:
    offenders = [h for p in USER_PAGES for h in hits(p, ADR_LINK, skip=README_ADR_ROW)]
    assert offenders == []


def test_no_one_is_credited_with_a_decision() -> None:
    offenders = [h for p in tracked_text_files() for h in hits(p, DECISION_CREDIT)]
    assert offenders == []


def test_no_local_name_appears_in_the_repository() -> None:
    names = local_names()
    offenders = [h for n in names for p in tracked_text_files() for h in hits(p, n)]
    assert offenders == []


def test_the_pages_describe_only_the_present() -> None:
    offenders = [h for p in PRESENT_PAGES for h in hits(p, HISTORY)]
    assert offenders == []


def test_the_first_release_is_described_by_topic_not_by_change() -> None:
    """The 0.1.0 section lists what Vocatron does; nothing was released before, so no history."""
    text = CHANGELOG.read_text(encoding="utf-8")
    # Only the 0.1.0 section: later releases use the usual Added, Changed, Fixed, Removed.
    section = text.split("## [0.1.0]", 1)[1].split("\n## ", 1)[0]
    headings = re.findall(r"^### (.+)$", section, re.MULTILINE)
    assert headings, "the 0.1.0 section has no topics"
    assert not {"Added", "Changed", "Fixed", "Removed"} & set(headings)


def test_the_docs_name_no_private_place() -> None:
    offenders = [h for p in markdown_files() for h in hits(p, PRIVATE)]
    assert offenders == []


@pytest.mark.parametrize(
    "line",
    [
        "see [ADR-0031](../adr/0031-tags.md)",
        "the decision is ADR-0031",
        "[x](adr/README.md)",
    ],
)
def test_the_adr_rule_catches_a_link_or_an_id(line: str) -> None:
    assert ADR_LINK.search(line)


def test_the_adr_rule_accepts_the_readme_row_and_plain_text() -> None:
    row = "| [Architecture](docs/dev/architecture.md), [decisions](docs/adr/README.md) | How |"
    assert not ADR_LINK.search(README_ADR_ROW.sub("", row))
    assert not ADR_LINK.search("An address is stored in the card.")


@pytest.mark.parametrize(
    "line",
    [
        "Option 1 (Someone, 2026-11-02).",
        "Option 1 (Someone, 2026-11-01 and 2026-11-02).",
        "chosen (Some One, 2026-11-02)",
        "This was decided by Someone.",
        "Decided by the owner.",
        "That is Someone's decision.",
    ],
)
def test_the_credit_rule_catches_a_credit(line: str) -> None:
    assert DECISION_CREDIT.search(line)


@pytest.mark.parametrize(
    "line",
    [
        "Option 1.",
        "date: 2026-11-02",
        "The maintainer decides.",
        "Whether a stage runs again is decided by fingerprints.",
        "(see below, 2026-11-02 is a date in a list)",
    ],
)
def test_the_credit_rule_accepts_a_good_line(line: str) -> None:
    assert not DECISION_CREDIT.search(line)


@pytest.mark.parametrize(
    "line",
    [
        "A video made before this change has no tags.",
        "It brings back the older look.",
        "Files used to be written here.",
        "Previously the default was two lines.",
        "The formerly separate step.",
        "It is drawn as before.",
        "The prefixes are not read any more.",
        "Older versions read them.",
    ],
)
def test_the_history_rule_catches_history_wording(line: str) -> None:
    assert HISTORY.search(line)


def test_the_history_rule_accepts_present_wording() -> None:
    assert not HISTORY.search("The default look has four lines; the file is read at the start.")
    assert not HISTORY.search("With more than two artists only the first and how many more.")


@pytest.mark.parametrize(
    "line",
    [
        "/home/someone/songs",
        # the next two are split so that the history scan does not take them for real paths
        "/mnt/" + "c/Users/someone",
        "file:///tmp/x",
        "C:" + "\\Users\\someone",
        "see [[VOC-012 Some story]]",
        "VOC-072",
        "in vocatron-trials",
        "the Obsidian vault",
    ],
)
def test_the_private_rule_catches_a_private_place(line: str) -> None:
    assert PRIVATE.search(line)


def test_the_private_rule_accepts_a_public_path() -> None:
    assert not PRIVATE.search("Write to ~/karaoke or ./out; see docs/user/install.md.")
