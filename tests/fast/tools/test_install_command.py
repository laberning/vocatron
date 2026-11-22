"""Stage 1 tests for ``tools/install_command.py`` on temporary folders, never the real bin dir."""

from pathlib import Path

import pytest

import install_command


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    command = tmp_path / "clone" / ".venv" / "bin" / "vocatron"
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\n")
    return tmp_path / "clone"


def target_of(clone: Path) -> Path:
    return clone / ".venv" / "bin" / "vocatron"


def test_fresh_install_creates_folder_and_link(
    tmp_path: Path, clone: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    link = tmp_path / "bin" / "sub" / "vocatron"
    assert install_command.install(link, target_of(clone), str(link.parent)) == 0
    assert link.is_symlink() and link.resolve() == target_of(clone).resolve()
    assert "Warning" not in capsys.readouterr().err


def test_install_is_idempotent(tmp_path: Path, clone: Path) -> None:
    link = tmp_path / "bin" / "vocatron"
    for _ in range(2):
        assert install_command.install(link, target_of(clone), str(link.parent)) == 0
    assert link.resolve() == target_of(clone).resolve()


def test_install_replaces_a_foreign_symlink(tmp_path: Path, clone: Path) -> None:
    other = tmp_path / "other"
    other.write_text("x")
    link = tmp_path / "bin" / "vocatron"
    link.parent.mkdir()
    link.symlink_to(other)
    assert install_command.install(link, target_of(clone), str(link.parent)) == 0
    assert link.resolve() == target_of(clone).resolve()
    assert other.read_text() == "x"


def test_install_replaces_a_broken_symlink(tmp_path: Path, clone: Path) -> None:
    link = tmp_path / "bin" / "vocatron"
    link.parent.mkdir()
    link.symlink_to(tmp_path / "gone")
    assert install_command.install(link, target_of(clone), str(link.parent)) == 0
    assert link.resolve() == target_of(clone).resolve()


def test_install_refuses_a_regular_file(
    tmp_path: Path, clone: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    link = tmp_path / "bin" / "vocatron"
    link.parent.mkdir()
    link.write_text("mine")
    assert install_command.install(link, target_of(clone), str(link.parent)) == 1
    assert link.read_text() == "mine" and not link.is_symlink()
    assert "not replacing" in capsys.readouterr().err


def test_install_without_target_says_run_setup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    link = tmp_path / "bin" / "vocatron"
    assert install_command.install(link, tmp_path / "none", str(link.parent)) == 1
    assert "make setup" in capsys.readouterr().err
    assert not link.parent.exists()


def test_install_warns_when_folder_is_not_on_path(
    tmp_path: Path, clone: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    link = tmp_path / "bin" / "vocatron"
    assert install_command.install(link, target_of(clone), f"/usr/bin::{tmp_path}") == 0
    assert link.is_symlink()
    err = capsys.readouterr().err
    assert "not on your PATH" in err and "export PATH" in err


def test_install_does_not_warn_with_unnormalised_path_entry(tmp_path: Path, clone: Path) -> None:
    (tmp_path / "bin").mkdir()
    link = tmp_path / "bin" / "vocatron"
    path_env = f"{tmp_path}/bin/../bin"
    assert install_command.install(link, target_of(clone), path_env) == 0


def test_uninstall_removes_own_link(
    tmp_path: Path, clone: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    link = tmp_path / "bin" / "vocatron"
    install_command.install(link, target_of(clone), "")
    assert install_command.uninstall(link, clone) == 0
    assert not link.is_symlink()
    assert target_of(clone).exists()
    assert "Removed" in capsys.readouterr().out


def test_uninstall_leaves_a_foreign_link(
    tmp_path: Path, clone: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "otherclone" / "vocatron"
    other.parent.mkdir()
    other.write_text("x")
    link = tmp_path / "bin" / "vocatron"
    link.parent.mkdir()
    link.symlink_to(other)
    assert install_command.uninstall(link, clone) == 1
    assert link.is_symlink()
    assert "does not point into this clone" in capsys.readouterr().err


def test_uninstall_leaves_a_regular_file(tmp_path: Path, clone: Path) -> None:
    link = tmp_path / "vocatron"
    link.write_text("mine")
    assert install_command.uninstall(link, clone) == 1
    assert link.exists()


def test_uninstall_with_nothing_there(tmp_path: Path, clone: Path) -> None:
    assert install_command.uninstall(tmp_path / "bin" / "vocatron", clone) == 0


def test_main_installs_and_uninstalls(
    tmp_path: Path, clone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    args = ["--bindir", str(tmp_path / "bin"), "--clone", str(clone)]
    assert install_command.main(["install", *args]) == 0
    assert (tmp_path / "bin" / "vocatron").is_symlink()
    assert install_command.main(["uninstall", *args]) == 0
    assert not (tmp_path / "bin" / "vocatron").is_symlink()


def test_path_warning_names_an_absolute_folder(
    tmp_path: Path, clone: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert install_command.install(Path("bin") / "vocatron", target_of(clone), "/usr/bin") == 0
    assert f'export PATH="{tmp_path / "bin"}:$PATH"' in capsys.readouterr().err
