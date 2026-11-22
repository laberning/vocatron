"""Stage 1 tests for ``tools/gate.py``."""

import sys
from pathlib import Path

import pytest

import gate


def test_passing_command_writes_report_and_zero_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = gate.run_gate("demo", [sys.executable, "-c", "print('hello')"], tmp_path)
    assert code == 0
    assert (tmp_path / "demo.txt").read_text() == "hello\n"
    assert (tmp_path / "demo.status").read_text() == "0\n"
    assert "hello" in capsys.readouterr().out


def test_failing_command_records_exit_code_and_stderr(tmp_path: Path) -> None:
    script = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
    code = gate.run_gate("demo", [sys.executable, "-c", script], tmp_path)
    assert code == 3
    assert (tmp_path / "demo.status").read_text() == "3\n"
    report = (tmp_path / "demo.txt").read_text()
    assert "out" in report
    assert "err" in report


def test_command_that_cannot_start_is_recorded(tmp_path: Path) -> None:
    code = gate.run_gate("demo", ["/nonexistent/tool-for-test"], tmp_path / "nested")
    assert code == 127
    assert "cannot run" in (tmp_path / "nested" / "demo.txt").read_text()
    assert (tmp_path / "nested" / "demo.status").read_text() == "127\n"


def test_color_is_disabled_for_reports(tmp_path: Path) -> None:
    gate.run_gate(
        "demo", [sys.executable, "-c", "import os; print(os.environ['NO_COLOR'])"], tmp_path
    )
    assert (tmp_path / "demo.txt").read_text() == "1\n"


def test_main_splits_name_and_command(tmp_path: Path) -> None:
    argv = ["x", "--reports", str(tmp_path), "--", sys.executable, "-c", "pass"]
    assert gate.main(argv) == 0
    assert (tmp_path / "x.status").exists()


def test_main_without_command_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as info:
        gate.main(["x", "--reports", str(tmp_path), "--"])
    assert info.value.code == 2


def test_ansi_colors_are_stripped_from_the_report(tmp_path: Path) -> None:
    script = "print('\\x1b[1m\\x1b[31mred\\x1b[0m text')"
    gate.run_gate("demo", [sys.executable, "-c", script], tmp_path)
    assert (tmp_path / "demo.txt").read_text() == "red text\n"
