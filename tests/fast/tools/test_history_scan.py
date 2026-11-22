"""Stage 1 tests for ``tools/history_scan.py``: a temporary git repository with planted findings."""

import os
import subprocess
from pathlib import Path

import pytest

import history_scan
from history_scan import START

# Built from pieces so that this file itself holds nothing the scanner would find.
HOME = "/ho" + "me/anna/music"
VAULT_MARK = "Obsidian" + "OneDrive"
TOKEN = "gh" + "p_" + "a1" * 20
PROJECT = "zebra-" + "karaoke"
RULES = history_scan.build_rules("anna", [PROJECT])


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, check=True, env=env,
    )  # fmt: skip
    return result.stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str = "work") -> str:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")[: history_scan.SHORT]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


def scan(repo: Path) -> dict[str, list[str]]:
    return history_scan.scan_lines(history_scan.git_log(repo), RULES)


def test_a_clean_history_has_no_findings(repo: Path) -> None:
    commit(repo, {"src/a.py": "print('hi')\n", "tests/data/demo/Song.txt": "la la\n"})
    assert scan(repo) == {}
    assert history_scan.report({}, history_scan.commit_count(repo)) == [
        "scanned 1 commits",
        "no findings",
    ]


@pytest.mark.parametrize(
    ("kind", "files", "message"),
    [
        ("local path", {"a.md": f"see {HOME}\n"}, "work"),
        ("vault or Windows path", {"a.md": f"in {VAULT_MARK}\n"}, "work"),
        ("secret", {"a.txt": f"token {TOKEN}\n"}, "work"),
        ("audio file", {"songs/a.mp3": "x"}, "work"),
        ("model or weights file", {"m/weights.safetensors": "x"}, "work"),
        ("lyrics file outside the demo folder", {"songs/a.lrc": "[00:01.00] la\n"}, "work"),
        ("lyrics file outside the demo folder", {"x/lyrics.json": "{}"}, "work"),
        ("local corpus", {".corpus/notes.md": "x"}, "work"),
        ("agent file", {"CLAUDE.md": "x"}, "work"),
        ("project name 1", {"a.md": f"like {PROJECT}\n"}, "work"),
        ("project name 1", {"a.md": "x\n"}, f"copied from {PROJECT}"),
    ],
)
def test_each_kind_of_finding_is_reported_with_its_commit(
    repo: Path, kind: str, files: dict[str, str], message: str
) -> None:
    commit(repo, {"ok.py": "x = 1\n"})
    bad = commit(repo, files, message)
    commit(repo, {"ok2.py": "y = 2\n"})
    assert scan(repo) == {kind: [bad]}


def test_a_finding_that_was_deleted_later_is_still_found(repo: Path) -> None:
    bad = commit(repo, {"a.md": f"see {HOME}\n"})
    commit(repo, {"a.md": "clean\n"})
    assert scan(repo) == {"local path": [bad]}


def test_lyrics_files_are_fine_in_the_demo_folder(repo: Path) -> None:
    commit(repo, {"tests/data/demo/Artist - Title.lrc": "[00:01.00] la\n"})
    assert scan(repo) == {}


def test_removed_lines_and_other_users_paths_are_not_findings(repo: Path) -> None:
    commit(repo, {"a.md": "x\n"})
    commit(repo, {"a.md": "/ho" + "me/bob/music\n"})
    assert scan(repo) == {}


def test_every_ref_is_scanned(repo: Path) -> None:
    commit(repo, {"a.py": "x = 1\n"})
    git(repo, "checkout", "-q", "-b", "side")
    bad = commit(repo, {"b.md": f"see {HOME}\n"})
    git(repo, "checkout", "-q", "main")
    assert scan(repo) == {"local path": [bad]}


def test_a_change_made_in_a_merge_commit_is_found(repo: Path) -> None:
    commit(repo, {"a.py": "x = 1\n"})
    git(repo, "checkout", "-q", "-b", "side")
    commit(repo, {"b.py": "y = 2\n"})
    git(repo, "checkout", "-q", "main")
    commit(repo, {"c.py": "z = 3\n"})
    git(repo, "merge", "-q", "--no-ff", "--no-commit", "side")
    (repo / "d.md").write_text(f"see {HOME}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "merge")
    merge = git(repo, "rev-parse", "HEAD")[: history_scan.SHORT]
    assert scan(repo) == {"local path": [merge]}


def test_the_report_names_counts_and_ids_but_never_the_matched_text() -> None:
    stream = [f"{START}{'a' * 40}\n", "message\n", "diff --git a/x.md b/x.md\n", f"+see {HOME}\n"]
    found = history_scan.scan_lines(stream, RULES)
    lines = history_scan.report(found, 1)
    assert lines == ["scanned 1 commits", f"local path: 1 commits: {'a' * history_scan.SHORT}"]
    assert HOME not in "\n".join(lines)


def test_names_are_read_from_a_file_with_comments(tmp_path: Path) -> None:
    names = tmp_path / "names.txt"
    names.write_text("# other projects\nfoo-bar  # one\n\nbaz\n", encoding="utf-8")
    assert history_scan.read_names(names) == ["foo-bar", "baz"]
    assert history_scan.read_names(tmp_path / "missing.txt") == []


def test_main_exits_one_with_findings_and_zero_without(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    names = tmp_path / "n.txt"
    commit(repo, {"a.py": "x = 1\n"})
    assert history_scan.main(["--repo", str(repo), "--names", str(names)]) == 0
    assert "no project names" in capsys.readouterr().out
    commit(repo, {"songs/a.flac": "x"})
    assert history_scan.main(["--repo", str(repo), "--names", str(names)]) == 1
    assert "audio file: 1 commits" in capsys.readouterr().out


def test_a_failing_git_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="git log failed"):
        list(history_scan.git_log(tmp_path / "does-not-exist"))
