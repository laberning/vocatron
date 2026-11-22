"""Stage 1 tests for ``tools/diff_cover_gate.py`` (skip logic and command line)."""

import subprocess
import sys
from pathlib import Path

import pytest

import diff_cover_gate


def no_ref(ref: str) -> bool:
    del ref
    return False


def any_ref(ref: str) -> bool:
    del ref
    return True


def test_unknown_ref_does_not_exist() -> None:
    assert not diff_cover_gate.ref_exists("no-such-ref-for-the-test")


def test_missing_base_skips_and_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(diff_cover_gate, "ref_exists", no_ref)
    assert diff_cover_gate.main([]) == 0
    assert "skipped: no origin/main yet" in capsys.readouterr().out


def test_missing_coverage_file_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(diff_cover_gate, "ref_exists", any_ref)
    assert diff_cover_gate.main(["--coverage", str(tmp_path / "none.xml")]) == 1
    assert "no coverage data" in capsys.readouterr().out


def test_diff_cover_runs_with_base_and_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run(
        command: list[str], check: bool, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del check
        assert env["GIT_CONFIG_KEY_" + str(int(env["GIT_CONFIG_COUNT"]) - 1)] == "core.quotepath"
        calls.append(command)
        return subprocess.CompletedProcess(command, 3)

    coverage = tmp_path / "coverage.xml"
    coverage.write_text("<coverage/>")
    monkeypatch.setattr(diff_cover_gate, "ref_exists", any_ref)
    monkeypatch.setattr("subprocess.run", fake_run)
    assert diff_cover_gate.main(["--base", "origin/dev", "--coverage", str(coverage)]) == 3
    assert calls == [
        [
            sys.executable,
            "-m",
            "diff_cover.diff_cover_tool",
            str(coverage),
            "--compare-branch=origin/dev",
            "--fail-under=90",
            "--include-untracked",
        ]
    ]


def test_diff_cover_sees_non_ascii_paths_unquoted_without_changing_git_config() -> None:
    env = diff_cover_gate.git_env({"PATH": "/bin"})
    assert env == {
        "PATH": "/bin",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.quotepath",
        "GIT_CONFIG_VALUE_0": "false",
    }


def test_settings_already_passed_through_the_environment_are_kept() -> None:
    env = diff_cover_gate.git_env(
        {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "a.b", "GIT_CONFIG_VALUE_0": "c"}
    )
    assert (env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_KEY_1"], env["GIT_CONFIG_COUNT"]) == (
        "a.b",
        "core.quotepath",
        "2",
    )
