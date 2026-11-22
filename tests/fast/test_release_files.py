"""Stage 1 checks of the files a release needs: community files, workflows, the version."""

import re
import subprocess
import tomllib
from pathlib import Path

import check_ci_targets

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
GUARD = "github.event.repository.private == false"


def test_the_community_files_exist() -> None:
    for name in (
        "LICENSE",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "docs/contributing.md",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
    ):
        assert (ROOT / name).is_file(), name


def test_the_docs_workflow_does_nothing_while_the_repository_is_private() -> None:
    jobs = check_ci_targets.job_blocks((WORKFLOWS / "docs.yml").read_text(encoding="utf-8"))
    assert set(jobs) == {"build", "deploy"}
    for name, block in jobs.items():
        assert GUARD in block, name


def test_the_tag_job_runs_only_on_version_tags() -> None:
    jobs = check_ci_targets.job_blocks((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    assert "startsWith(github.ref_name, 'v')" in jobs["tag-check"]
    assert "make tag-check" in jobs["tag-check"]


def test_the_version_is_a_release_version() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", project["version"])
    assert project["version"] != "0.0.0"


def test_the_readme_shows_the_ci_badge_and_links_the_docs() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "actions/workflows/ci.yml/badge.svg" in text
    assert "docs/user/install.md" in text


def test_third_party_credits_both_demo_songs() -> None:
    text = (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert "Systemabsturz" in text
    assert "Josh Woodward" in text


def test_no_workflow_pins_uv_and_every_job_runs_on_one_runner() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert re.fullmatch(r"==\d+\.\d+\.\d+", project["tool"]["uv"]["required-version"])
    runners: set[str] = set()
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s+version:", text, re.MULTILINE), path.name
        # setup-uv publishes no major tags since v8: only a full version resolves.
        for ref in re.findall(r"uses:\s*astral-sh/setup-uv@(\S+)", text):
            assert re.fullmatch(r"v\d+\.\d+\.\d+", ref), (path.name, ref)
        runners.update(re.findall(r"^\s+runs-on:\s*(\S+)", text, re.MULTILINE))
    assert runners == {"ubuntu-26.04"}


def test_make_installs_the_uv_version_pinned_in_pyproject() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pinned = project["tool"]["uv"]["required-version"].removeprefix("==")
    shown = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-s",
            "--eval=uv-version: ; @echo $(UV_VERSION)",
            "uv-version",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert shown.stdout.strip() == pinned
