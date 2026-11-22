"""Stage 1 tests of the stage 2 and 3 logic in ``tests/conftest.py``."""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

NEEDS_GPU = "import pytest\n\npytestmark = pytest.mark.gpu\n\n\ndef test_a():\n"
NEEDS_GPU_FAILING = NEEDS_GPU + "    assert False\n"
NEEDS_GPU_PASSING = NEEDS_GPU + "    pass\n"

CONFTEST = Path(__file__).parents[1] / "conftest.py"


@pytest.fixture
def project(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> pytest.Pytester:
    """A pytester project with the real conftest, no corpus and no ``nvidia-smi``."""
    monkeypatch.setenv("VOCATRON_CORPUS", str(pytester.path / "no-such-corpus"))
    monkeypatch.setenv("PATH", "")  # no nvidia-smi
    pytester.makeconftest(CONFTEST.read_text(encoding="utf-8"))
    pytester.mkpydir("slow")
    pytester.mkpydir("bench")
    return pytester


def test_slow_and_bench_tests_are_marked_and_skipped_with_a_reason(
    project: pytest.Pytester,
) -> None:
    project.makepyfile(**{"slow/test_a": NEEDS_GPU_FAILING})
    project.makepyfile(**{"bench/test_b": "def test_b():\n    assert False\n"})
    project.makepyfile(test_c="def test_c():\n    pass\n")
    result = project.runpytest("-rs", "-p", "no:randomly", "-m", "slow or bench or not slow")
    result.assert_outcomes(passed=1, skipped=2)
    result.stdout.fnmatch_lines_random(
        ["*stage 3 needs the corpus*", "*stage 2 test needs an NVIDIA GPU*"]
    )


def test_only_the_folders_directly_below_the_tests_folder_count(project: pytest.Pytester) -> None:
    """A clone inside a folder named ``bench`` must not turn fast tests into stage 3 tests."""
    project.mkpydir("other")
    project.mkpydir("other/bench")
    project.makepyfile(**{"other/bench/test_d": "def test_d():\n    pass\n"})
    project.runpytest("-p", "no:randomly", "other").assert_outcomes(passed=1)


def test_a_stage_test_selected_by_node_id_is_still_a_stage_test(project: pytest.Pytester) -> None:
    project.makepyfile(**{"slow/test_a": NEEDS_GPU_FAILING})
    project.runpytest("-p", "no:randomly", "slow/test_a.py::test_a").assert_outcomes(skipped=1)


def test_slow_tests_run_when_a_gpu_is_found(
    project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = project.mkdir("fake-bin")
    fake = tools / "nvidia-smi"
    fake.write_text("#!/bin/sh\necho 'GPU 0: Fake'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools))
    project.makepyfile(**{"slow/test_a": "def test_a():\n    pass\n"})
    project.runpytest("-p", "no:randomly", "slow").assert_outcomes(passed=1)


def test_a_failing_nvidia_smi_means_no_gpu(
    project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = project.mkdir("fake-bin")
    fake = tools / "nvidia-smi"
    fake.write_text("#!/bin/sh\nexit 9\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tools))
    project.makepyfile(**{"slow/test_a": NEEDS_GPU_PASSING})
    project.runpytest("-p", "no:randomly", "slow").assert_outcomes(skipped=1)


@pytest.mark.parametrize(("folder", "stage"), [("slow", "stage 2"), ("bench", "stage 3")])
def test_a_stage_without_tests_says_so_and_passes(
    project: pytest.Pytester, folder: str, stage: str
) -> None:
    result = project.runpytest("-p", "no:randomly", folder)
    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines([f"{stage} has no tests yet"])


def test_other_folders_without_tests_still_fail(project: pytest.Pytester) -> None:
    project.mkpydir("fast")
    result = project.runpytest("-p", "no:randomly", "fast")
    assert result.ret == pytest.ExitCode.NO_TESTS_COLLECTED
    result.stdout.no_fnmatch_line("*has no tests yet*")


def test_mixing_stage_folders_without_tests_still_fails(project: pytest.Pytester) -> None:
    result = project.runpytest("-p", "no:randomly", "slow", "bench")
    assert result.ret == pytest.ExitCode.NO_TESTS_COLLECTED


def test_a_stage_2_test_without_the_gpu_marker_runs_without_a_gpu(project: pytest.Pytester) -> None:
    # ADR-0015: only the tests that need a GPU are skipped; make slow-cpu runs the others
    project.makepyfile(**{"slow/test_a": "def test_a():\n    pass\n"})
    project.runpytest("-p", "no:randomly", "slow").assert_outcomes(passed=1)


LEAKY = """import warnings

import pytest

ENGINE = {}  # an assert outside the test code, as in Vocatron or a library
exec(compile("def engine(text):\\n    assert not text, text\\n", "lib/engine.py", "exec"), ENGINE)


def check(text):
    assert text == "other words", "the words differ"


def test_a_message():
    check("secret words")


def test_no_message():
    words = ["secret words"]
    assert not words


def test_an_error():
    raise ValueError("secret words")


def test_output():
    print("secret words")
    pytest.fail("failed on purpose")


def test_an_engine_assert():
    ENGINE["engine"]("secret words")


def test_passing_output():
    print("secret words")


def test_a_warning():
    text = "secret words"
    warnings.warn(text)  # the line of code is shown, so it must not hold the text itself
"""


@pytest.mark.parametrize("style", ["auto", "long", "short", "line", "native"])
def test_a_failing_stage_test_shows_no_value_of_the_run(
    project: pytest.Pytester, style: str
) -> None:
    project.makepyfile(**{"slow/test_a": LEAKY})
    junit = project.path / "junit.xml"
    result = project.runpytest(
        *("-p", "no:randomly", "-l", "-rA", f"--tb={style}", "slow"),
        *("-o", "junit_logging=all", f"--junitxml={junit}"),
    )
    result.assert_outcomes(failed=5, passed=2, warnings=1)
    assert "secret" not in result.stdout.str() + result.stderr.str()
    assert "secret" not in junit.read_text(encoding="utf-8")
    result.stdout.fnmatch_lines_random(
        [
            "*slow/test_a.py:10: AssertionError: the words differ*",
            "*slow/test_a.py:19: AssertionError",
            "*slow/test_a.py:23: ValueError",
            "*slow/test_a.py:28: Failed: failed on purpose*",
            "*slow/test_a.py:32: AssertionError",
            "*UserWarning: (hidden in stage 2 and 3*",
        ]
    )


def test_a_failing_fast_test_and_a_full_report_on_request_show_everything(
    project: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.makepyfile(test_b=LEAKY)
    assert "secret" in project.runpytest("-p", "no:randomly", "test_b.py").stdout.str()
    project.makepyfile(**{"slow/test_a": LEAKY})
    monkeypatch.setenv("VOCATRON_FULL_REPORTS", "1")
    assert "secret" in project.runpytest("-p", "no:randomly", "slow").stdout.str()
