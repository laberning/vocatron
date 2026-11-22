"""Stage 1 tests for ``tools/check_version.py``."""

from pathlib import Path

import pytest

import check_version

PYPROJECT = '[project]\nname = "x"\nversion = "0.1.0"\n'
CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-11-01\n"
ROOT = Path(__file__).resolve().parents[3]


def test_a_matching_tag_has_no_problems() -> None:
    assert check_version.problems("v0.1.0", PYPROJECT, CHANGELOG) == []


def test_a_tag_that_differs_from_the_version_is_reported() -> None:
    (message,) = check_version.problems("v0.1.0", PYPROJECT.replace("0.1.0", "0.0.9"), CHANGELOG)
    assert "version 0.0.9" in message


def test_a_missing_changelog_section_is_reported() -> None:
    (message,) = check_version.problems("v0.2.0", PYPROJECT.replace("0.1.0", "0.2.0"), CHANGELOG)
    assert "[0.2.0]" in message


def test_both_problems_are_reported_together() -> None:
    assert len(check_version.problems("v0.3.0", PYPROJECT, CHANGELOG)) == 2


@pytest.mark.parametrize("tag", ["0.1.0", "v0.1", "v0.1.0-rc1", "latest", ""])
def test_a_tag_of_the_wrong_form_is_refused(tag: str) -> None:
    (message,) = check_version.problems(tag, PYPROJECT, CHANGELOG)
    assert "vMAJOR.MINOR.PATCH" in message


def test_a_project_without_version_is_reported() -> None:
    assert check_version.problems("v0.1.0", "[project]\nname='x'\n", CHANGELOG)


def test_main_needs_exactly_one_tag(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_version.main([]) == 2
    assert "usage" in capsys.readouterr().out


def test_main_checks_the_files_of_the_clone(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_version.main(["v9.9.9"]) == 1
    assert "v9.9.9" in capsys.readouterr().out


def test_the_clone_has_a_changelog_section_for_its_own_version() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    version = next(
        line.split('"')[1] for line in pyproject.splitlines() if line.startswith("version = ")
    )
    assert check_version.problems(f"v{version}", pyproject, changelog) == []
