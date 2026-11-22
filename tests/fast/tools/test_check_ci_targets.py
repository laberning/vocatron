"""Stage 1 tests for ``tools/check_ci_targets.py``."""

from pathlib import Path

import pytest

import check_ci_targets

MAKEFILE = "CI_TARGETS := static fast\n\nstatic:\n\ttrue\n"
WORKFLOW = """name: ci
jobs:
  static:
    steps:
      - run: make static UV=uv
  fast:
    steps:
      - run: make fast UV=uv
  extra:
    steps:
      - run: make extra
"""


def test_targets_are_read_from_the_makefile() -> None:
    assert check_ci_targets.ci_targets(MAKEFILE) == ["static", "fast"]
    assert check_ci_targets.ci_targets("all:\n") == []


def test_jobs_are_split_by_name() -> None:
    jobs = check_ci_targets.job_blocks(WORKFLOW)
    assert list(jobs) == ["static", "fast", "extra"]
    assert "make fast" in jobs["fast"]
    assert check_ci_targets.job_blocks("name: x\n") == {}


def test_nothing_missing_when_every_target_has_a_job() -> None:
    assert check_ci_targets.missing_targets(MAKEFILE, WORKFLOW) == []


def test_missing_job_is_reported() -> None:
    makefile = "CI_TARGETS := static fast dup\n"
    assert check_ci_targets.missing_targets(makefile, WORKFLOW) == ["dup"]


def test_job_that_runs_another_target_is_reported() -> None:
    workflow = WORKFLOW.replace("make fast", "make slow")
    assert check_ci_targets.missing_targets(MAKEFILE, workflow) == ["fast"]


def test_main_reports_missing_targets(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    makefile = tmp_path / "Makefile"
    workflow = tmp_path / "ci.yml"
    makefile.write_text("CI_TARGETS := static dup\n")
    workflow.write_text(WORKFLOW)
    assert check_ci_targets.main([str(makefile), str(workflow)]) == 1
    assert "make dup" in capsys.readouterr().out


def test_main_passes_and_rejects_a_makefile_without_targets(tmp_path: Path) -> None:
    makefile = tmp_path / "Makefile"
    workflow = tmp_path / "ci.yml"
    workflow.write_text(WORKFLOW)
    makefile.write_text(MAKEFILE)
    assert check_ci_targets.main([str(makefile), str(workflow)]) == 0
    makefile.write_text("all:\n")
    assert check_ci_targets.main([str(makefile), str(workflow)]) == 1


def test_the_repository_itself_is_consistent() -> None:
    root = Path(__file__).resolve().parents[3]
    assert (
        check_ci_targets.main([str(root / "Makefile"), str(root / ".github/workflows/ci.yml")]) == 0
    )
