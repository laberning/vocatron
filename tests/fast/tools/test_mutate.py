"""Stage 1 tests for ``tools/mutate.py``: name matching, refusal, the count, the run per mutant."""

import io
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, override

import pytest

import mutate
from mutate import Outcome

NAMES = [
    "vocatron.core.cdg.encode.x_plan_tile__mutmut_1",
    "vocatron.core.cdg.encode.x_plan_tile__mutmut_2",
    "vocatron.core.cdg.encode.x__rows__mutmut_1",
    "vocatron.core.cdg.screen.xǁCdgScreenǁapply__mutmut_1",
    "vocatron.core.cdg.screen.xǁCdgScreenǁapply__mutmut_2",
    "vocatron.core.cdg.screen.xǁCdgScreenǁapply__mutmut_3",
    "vocatron.core.cdg.screen.x_apply__mutmut_1",  # a function called like the method
    "vocatron.core.cdg.encode.x_plan_tile_more__mutmut_1",  # another function with the same start
]
PLAN = "vocatron.core.cdg.encode.plan_tile"
APPLY = "vocatron.core.cdg.screen.CdgScreen.apply"


class Recorder:
    """A fake runner: counts the calls and answers by mutant name."""

    def __init__(self, answers: dict[str, Outcome] | None = None, clean: Outcome = "survived"):
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.answers = answers or {}
        self.clean = clean

    def __call__(self, mutant: str, tests: Sequence[str]) -> Outcome:
        self.calls.append((mutant, tuple(tests)))
        return self.clean if mutant == "" else self.answers.get(mutant, "killed")


def test_the_mutants_of_a_function_are_those_with_exactly_its_mangled_name() -> None:
    found = match_all(PLAN)
    assert found == {PLAN: NAMES[:2]}


def match_all(*functions: str) -> dict[str, list[str]]:
    return mutate.match_mutants(NAMES, functions)


def test_the_mutants_of_a_method_are_found_by_class_and_method() -> None:
    assert match_all(APPLY) == {APPLY: NAMES[3:6]}


def test_a_function_and_a_method_of_the_same_name_are_told_apart() -> None:
    assert match_all("vocatron.core.cdg.screen.apply") == {
        "vocatron.core.cdg.screen.apply": [NAMES[6]]
    }


def test_a_name_without_mutants_is_an_error_that_says_how_to_name_one() -> None:
    with pytest.raises(ValueError, match="no mutants for vocatron.core.cdg.encode.nope"):
        match_all(PLAN, "vocatron.core.cdg.encode.nope")


def make_tree(root: Path) -> tuple[Path, Path]:
    source, tests = root / "src", root / "tests"
    (source / "vocatron/core/cdg").mkdir(parents=True)
    (source / "vocatron/core/cdg/encode.py").write_text("", encoding="utf-8")
    (source / "vocatron/core/cdg/screen.py").write_text("", encoding="utf-8")
    (tests / "core").mkdir(parents=True)
    (tests / "core/test_a.py").write_text(
        "from vocatron.core.cdg.encode import x", encoding="utf-8"
    )
    (tests / "core/test_b.py").write_text("plan_tile(1)", encoding="utf-8")
    (tests / "core/test_c.py").write_text("vocatron.core.cdg.encode_more", encoding="utf-8")
    (tests / "core/helper.py").write_text("plan_tile(1)", encoding="utf-8")
    return source, tests


def test_the_module_is_the_longest_prefix_that_is_a_file_of_the_source(tmp_path: Path) -> None:
    source, _ = make_tree(tmp_path)
    assert mutate.module_of(PLAN, source) == "vocatron.core.cdg.encode"
    assert mutate.module_of(APPLY, source) == "vocatron.core.cdg.screen"


def test_the_tests_are_the_files_that_name_the_module_or_the_function(tmp_path: Path) -> None:
    source, tests = make_tree(tmp_path)
    found = mutate.select_tests([PLAN], tests, source)
    assert found == [(tests / "core/test_a.py").as_posix(), (tests / "core/test_b.py").as_posix()]


def test_the_tests_of_a_method_include_the_files_that_name_its_class(tmp_path: Path) -> None:
    source, tests = make_tree(tmp_path)
    (tests / "core/test_d.py").write_text("from vocatron.core.cdg import CdgScreen", "utf-8")
    (tests / "core/test_e.py").write_text("CdgScreenish", encoding="utf-8")
    assert mutate.names_of(APPLY, source) == ["vocatron.core.cdg.screen", "CdgScreen", "apply"]
    assert mutate.select_tests([APPLY], tests, source) == [(tests / "core/test_d.py").as_posix()]


def test_a_run_without_functions_is_refused_before_anything_is_generated() -> None:
    lines: list[str] = []
    recorder = Recorder()

    def refresh() -> list[str]:
        raise AssertionError("mutants must not be generated")

    assert mutate.main([], refresh=refresh, runner=recorder, out=lines.append) == 2
    assert recorder.calls == []
    assert "ALL=1" in lines[0]


def test_it_says_how_many_mutants_it_will_run_before_it_runs_one_and_runs_no_more() -> None:
    lines: list[str] = []
    recorder = Recorder()
    code = mutate.main(
        [PLAN, APPLY, "--tests", "t.py", "--jobs", "1"],
        refresh=lambda: NAMES,
        runner=recorder,
        out=lines.append,
    )
    assert code == 0
    assert lines[0].startswith("5 mutants (")
    assert [call[0] for call in recorder.calls] == ["", *NAMES[:2], *NAMES[3:6]]
    assert lines[-1] == "5 killed, 0 survived, 0 errors"


def test_a_surviving_mutant_is_named_and_makes_the_exit_code_1() -> None:
    lines: list[str] = []
    recorder = Recorder({NAMES[1]: "survived", NAMES[0]: "error"})
    code = mutate.main(
        [PLAN, "--tests", "t.py"], refresh=lambda: NAMES, runner=recorder, out=lines.append
    )
    assert code == 1
    assert f"survived: {NAMES[1]}" in lines
    assert f"could not run: {NAMES[0]}" in lines
    assert lines[-1] == "0 killed, 1 survived, 1 errors"


def test_tests_that_fail_without_a_mutant_stop_the_run_with_no_mutant_run() -> None:
    lines: list[str] = []
    recorder = Recorder(clean="killed")
    code = mutate.main(
        [PLAN, "--tests", "t.py"], refresh=lambda: NAMES, runner=recorder, out=lines.append
    )
    assert code == 2
    assert recorder.calls == [("", ("t.py",))]
    assert "fail without a mutant" in lines[-1]


def test_an_unknown_function_stops_the_run_before_any_test() -> None:
    lines: list[str] = []
    recorder = Recorder()
    code = mutate.main(
        ["a.b.c", "--tests", "t.py"], refresh=lambda: NAMES, runner=recorder, out=lines.append
    )
    assert code == 2 and recorder.calls == [] and "no mutants for a.b.c" in lines[0]


def test_no_test_file_that_names_the_function_stops_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests/fast").mkdir(parents=True)
    lines: list[str] = []
    code = mutate.main([PLAN], refresh=lambda: NAMES, runner=Recorder(), out=lines.append)
    assert code == 2
    assert "--tests" in lines[0]


def test_pytest_runs_in_the_mutants_folder_with_the_mutant_set_and_the_mutated_source_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, seen["code"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    run = mutate.pytest_runner(timeout=5)
    outcomes: dict[int, Outcome] = {}
    for code in (0, 1, 2, 5):
        seen["code"] = code
        outcomes[code] = run("m.x_f__mutmut_1", ["tests/fast/a.py"])
    assert outcomes == {0: "survived", 1: "killed", 2: "error", 5: "error"}
    assert seen["cwd"] == mutate.MUTANTS
    assert seen["env"]["MUTANT_UNDER_TEST"] == "m.x_f__mutmut_1"
    assert seen["env"]["PYTHONPATH"] == "src"
    assert seen["command"][-1] == "tests/fast/a.py" and "-n" in seen["command"]
    assert seen["timeout"] == 5


def test_a_mutant_that_hangs_the_tests_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    assert mutate.pytest_runner(timeout=1)("m.x_f__mutmut_1", ["t.py"]) == "killed"


class FlushSpy(io.StringIO):
    """Standard output that remembers whether it was flushed."""

    flushed = False

    @override
    def flush(self) -> None:
        self.flushed = True
        super().flush()


def test_the_tool_prints_each_line_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = FlushSpy()
    monkeypatch.setattr(sys, "stdout", spy)
    mutate.say("3 mutants")  # seen at once in a log file, not at the end of a long run
    assert spy.getvalue() == "3 mutants\n"
    assert spy.flushed
