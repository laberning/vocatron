"""Stage 1 tests for ``tools/summary.py`` on recorded tool outputs and JUnit XML."""

from pathlib import Path

import pytest

import summary

RUFF = """tools/gate.py:28:35: RUF100 [*] Unused `noqa` directive
src/vocatron/core/bad.py:13:5: D103 Missing docstring in public function
Found 2 errors.
"""
PYREFLY = """ INFO Checking project configured at `/x/pyproject.toml`
ERROR src/vocatron/core/bad.py:3:8-13: Cannot find module `torch` [missing-import]
 INFO 1 errors
"""
VULTURE = "src/vocatron/core/bad.py:8: unused function 'unused_thing' (60% confidence)\n"
DEPTRY = """Scanning 14 files...

pyproject.toml: DEP002 'rich' defined as a dependency but not used in the codebase
Found 1 dependency issue.
"""
IMPORT_LINTER = """Broken contracts
core is pure
vocatron.core is not allowed to import torch:

-   vocatron.core.bad -> torch (l.3)

vocatron.core is not allowed to import vocatron.engines:

- vocatron.core.bad -> vocatron.engines.protocols (l.5)
"""
JSCPD = """Clone found (python)
 - vocatron/core/dup_a.py [1:1 - 16:18] (16 lines, 96 tokens)
   vocatron/core/dup_b.py [1:1 - 16:18]
Found 1 clones.
"""
SOCKET_FAILURE = """<testsuites><testsuite><testcase classname="t" name="test_network">
<failure message="SocketBlockedError: blocked">tests/fast/test_v6.py:5: in test_network
.cache/python/x/lib/python3.14/socket.py:850: in getaddrinfo
.venv/lib/python3.14/site-packages/pytest_socket/__init__.py:115: SocketBlockedError</failure>
</testcase></testsuite></testsuites>
"""
LOCK = "error: The lockfile at `uv.lock` needs to be updated, but `--check` was provided.\n"
JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3" failures="1" errors="1">
<testcase classname="tests.fast.test_a" name="test_ok" time="0.01"/>
<testcase classname="tests.fast.test_a" name="test_bad" time="0.01">
<failure message="assert 1 == 2">def test_bad():
&gt;       assert 1 == 2
E       assert 1 == 2

tests/fast/test_a.py:7: AssertionError</failure></testcase>
<testcase classname="tests.fast.test_b" name="test_err" time="0.01">
<error message="collection failed">no location here</error></testcase>
</testsuite></testsuites>
"""


def write_gate(reports: Path, name: str, status: int, text: str = "") -> None:
    (reports / f"{name}.status").write_text(f"{status}\n")
    (reports / f"{name}.txt").write_text(text)


def test_ruff_lines_become_file_line_message() -> None:
    assert summary.parse_text(RUFF) == [
        "tools/gate.py:28: RUF100 [*] Unused `noqa` directive",
        "src/vocatron/core/bad.py:13: D103 Missing docstring in public function",
    ]


def test_pyrefly_error_lines_are_read() -> None:
    assert summary.parse_text(PYREFLY) == [
        "src/vocatron/core/bad.py:3: Cannot find module `torch` [missing-import]"
    ]


def test_vulture_line_is_read() -> None:
    assert summary.parse_text(VULTURE) == [
        "src/vocatron/core/bad.py:8: unused function 'unused_thing' (60% confidence)"
    ]


def test_deptry_line_without_line_number() -> None:
    assert summary.parse_text(DEPTRY) == [
        "pyproject.toml: DEP002 'rich' defined as a dependency but not used in the codebase"
    ]


def test_import_linter_violations_point_at_the_importing_line() -> None:
    assert summary.parse_text(IMPORT_LINTER) == [
        "src/vocatron/core/bad.py:3: imports torch (forbidden by a layer contract)",
        "src/vocatron/core/bad.py:5: imports vocatron.engines.protocols"
        " (forbidden by a layer contract)",
    ]


def test_jscpd_clone_names_both_places() -> None:
    assert summary.parse_text(JSCPD) == [
        "vocatron/core/dup_a.py:1: 16 duplicated lines, same as vocatron/core/dup_b.py:1"
    ]


def test_junit_prefers_the_repository_location_over_site_packages(tmp_path: Path) -> None:
    path = tmp_path / "fast.xml"
    path.write_text(SOCKET_FAILURE)
    assert summary.parse_junit(path) == [
        "tests/fast/test_v6.py:5: test_network - SocketBlockedError: blocked"
    ]


def test_the_same_violation_reported_twice_is_listed_once() -> None:
    line = "- vocatron.core.bad -> torch (l.3)\n"
    twice = line + line
    assert len(summary.parse_text(twice)) == 1


def test_unstructured_output_falls_back_to_the_tail() -> None:
    assert summary.parse_text(LOCK) == [LOCK.strip()]
    long = "".join(f"line {i}\n" for i in range(30))
    assert summary.parse_text(long) == [f"line {i}" for i in range(20, 30)]


def test_junit_failures_and_errors(tmp_path: Path) -> None:
    path = tmp_path / "fast.xml"
    path.write_text(JUNIT)
    assert summary.parse_junit(path) == [
        "tests/fast/test_a.py:7: test_bad - assert 1 == 2",
        "tests.fast.test_b: test_err - collection failed",
    ]


def test_only_failed_gates_are_listed(tmp_path: Path) -> None:
    write_gate(tmp_path, "ruff-check", 0, "All checks passed!\n")
    write_gate(tmp_path, "ruff-format", 1, RUFF)
    write_gate(tmp_path, "fast", 1, "pytest noise that must not be shown\n")
    (tmp_path / "fast.xml").write_text(JUNIT)
    lines = summary.summarize(tmp_path)
    assert lines[0] == "fast: FAILED"
    assert "  tests/fast/test_a.py:7: test_bad - assert 1 == 2" in lines
    assert "ruff-format: FAILED" in lines
    assert not any("ruff-check" in line or "noise" in line for line in lines)


def test_main_prints_nothing_failed_and_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_gate(tmp_path, "ruff-check", 0)
    assert summary.main([str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == "Nothing failed."


def test_main_without_reports_asks_for_a_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert summary.main([str(tmp_path)]) == 1
    assert "make check" in capsys.readouterr().out


def test_main_returns_one_when_something_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_gate(tmp_path, "vulture", 1, VULTURE)
    assert summary.main([str(tmp_path)]) == 1
    assert "vulture: FAILED" in capsys.readouterr().out


def test_module_path_prefers_a_package_init() -> None:
    assert summary.module_path("vocatron.core") == "src/vocatron/core/__init__.py"
    assert summary.module_path("vocatron.core.nothing") == "src/vocatron/core/nothing.py"
