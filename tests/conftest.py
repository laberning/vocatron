"""Shared pytest configuration: Hypothesis profile and the stage 2 and 3 logic.

Stage 2 (``tests/slow``) and stage 3 (``tests/bench``) are skipped with a clear reason when
there is no GPU or no corpus, and a run of a stage that has no tests yet reports that and passes.
Their failures are reported without any value of the run (``safe_failure``), and their captured
output and warning messages are hidden, since a value may hold a line of the copyrighted lyrics
in the corpus.
"""

import os
import shutil
import subprocess
import warnings
from collections.abc import Generator
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings

# Derandomised and without deadline, so a failure reproduces on every machine.
settings.register_profile(
    "ci",
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("ci")

STAGE_FOLDERS = {"slow": "stage 2", "bench": "stage 3"}
TESTS_DIR = Path(__file__).resolve().parent  # stage folders are judged relative to this folder
GPU_QUERY_TIMEOUT = 30  # seconds; a hanging driver must not hang the test run
FULL_REPORTS = "VOCATRON_FULL_REPORTS"  # "1": full failure reports in stages 2 and 3
HIDDEN = "(hidden in stage 2 and 3: it may hold lyrics; VOCATRON_FULL_REPORTS=1 shows it)"


def corpus_dir() -> Path:
    """Return the local song corpus folder (``VOCATRON_CORPUS``, default ``.corpus/``)."""
    return Path(os.environ.get("VOCATRON_CORPUS", ".corpus"))


def gpu_available() -> bool:
    """Tell whether an NVIDIA GPU is present (``nvidia-smi -L`` works).

    Deliberately does not import torch, which stage 1 never loads.
    """
    path = shutil.which("nvidia-smi")
    if path is None:
        return False
    try:
        result = subprocess.run(
            [path, "-L"], capture_output=True, check=False, timeout=GPU_QUERY_TIMEOUT
        )
    except OSError, subprocess.SubprocessError:
        return False
    return result.returncode == 0


NO_GPU = "this stage 2 test needs an NVIDIA GPU (nvidia-smi found none)"


def skip_reason(marker: str) -> str | None:
    """Return why the tests of a stage folder cannot run here, or ``None`` if they can.

    Stage 2 runs everywhere; only its tests marked ``gpu`` are skipped without a GPU (see
    ``pytest_collection_modifyitems``). Stage 3 needs the corpus.
    """
    if marker == "slow":
        return None
    return None if corpus_dir().is_dir() else f"stage 3 needs the corpus {corpus_dir()}"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark tests by stage folder and skip stage 2 and 3 with a clear reason when impossible."""
    del config
    reasons: dict[str, str | None] = {}  # each check runs once, and only if the stage has tests
    gpu: bool | None = None  # asked only if a test needs it
    for item in items:
        if (marker := stage_folder(item.path)) is not None:
            if marker not in reasons:
                reasons[marker] = skip_reason(marker)
            item.add_marker(getattr(pytest.mark, marker))
            if (reason := reasons[marker]) is not None:
                item.add_marker(pytest.mark.skip(reason=reason))
            elif item.get_closest_marker("gpu") is not None:
                gpu = gpu_available() if gpu is None else gpu
                if not gpu:
                    item.add_marker(pytest.mark.skip(reason=NO_GPU))


def stage_folder(path: str | Path) -> str | None:
    """Return the stage folder (``slow`` or ``bench``) of ``path`` below the tests folder.

    Only the part below the tests folder counts, so a clone inside a folder named ``bench`` or
    ``slow`` does not turn the fast tests into stage 2 or 3 tests.
    """
    try:
        parts = Path(path).resolve().relative_to(TESTS_DIR).parts
    except ValueError:
        return None
    return parts[0] if parts and parts[0] in STAGE_FOLDERS else None


def stage_of(path: str) -> str | None:
    """Return the stage (2 or 3) whose folder contains ``path``, or ``None``."""
    folder = stage_folder(path.split("::", 1)[0])
    return None if folder is None else STAGE_FOLDERS[folder]


def stage_without_tests(args: list[str]) -> str | None:
    """Return the stage name when every path given to pytest lies in one stage 2 or 3 folder."""
    stages = {stage_of(arg) for arg in args}
    return stages.pop() if len(stages) == 1 and None not in stages else None


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Turn "no tests collected" into a pass with a clear message for stages 2 and 3."""
    if exitstatus != pytest.ExitCode.NO_TESTS_COLLECTED:
        return
    stage = stage_without_tests([str(arg) for arg in session.config.args])
    if stage is not None:
        print(f"\n{stage} has no tests yet")
        session.exitstatus = pytest.ExitCode.OK


def is_test_code(path: str | Path) -> bool:
    """Tell whether ``path`` is test code: a stage 2 or 3 test or a module of the tests folder."""
    return stage_folder(path) is not None or Path(path).resolve().parent == TESTS_DIR


def safe_failure(excinfo: pytest.ExceptionInfo[BaseException]) -> str:
    """Describe a failure by place, type and the test's own message, without any value of the run.

    A full report shows the arguments of every frame, the values pytest finds in a failed
    ``assert`` and the message of any error, and each may hold a line of the lyrics. What is left:
    the last line of the test code that took part (file and line), the type of the error, and the
    message the test wrote (its first line, without the values pytest adds after it): of a
    ``pytest.fail``, or of an ``assert`` in test code. The message of an ``assert`` elsewhere (in
    Vocatron or a library) is not the test's and may quote its input, so it is left out.
    """
    error = excinfo.value
    place = "unknown place"
    for entry in reversed(excinfo.traceback):
        if is_test_code(entry.path):
            place = f"{entry.path}:{entry.lineno + 1}"
            break
    own = isinstance(error, pytest.fail.Exception) or (
        isinstance(error, AssertionError)
        and len(excinfo.traceback) > 0
        and is_test_code(excinfo.traceback[-1].path)
    )
    message = ""
    if own:
        first = str(error).split("\n", 1)[0].strip()
        message = "" if first.startswith("assert ") else first  # no message: only pytest's values
    name = type(error).__name__
    return f"{place}: {name}: {message}" if message else f"{place}: {name}"


def full_reports() -> bool:
    """Tell whether the owner of the corpus asked for full reports (``VOCATRON_FULL_REPORTS=1``)."""
    return os.environ.get(FULL_REPORTS) == "1"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Keep the values of a stage 2 or 3 test out of its report (``safe_failure``).

    The captured output is hidden in every report, passed ones too (``-rA``, ``junit_logging``):
    the song logs and the summaries it holds may quote lyrics.
    """
    report = yield
    if stage_folder(item.path) is None or full_reports():
        return report
    if report.failed and call.excinfo is not None:
        report.longrepr = safe_failure(call.excinfo)
    report.sections = [(title, HIDDEN) for title, _ in report.sections]
    return report


class WarningGuard:
    """Hides the message of a warning raised in a stage 2 or 3 test (it may quote a word).

    The warnings summary keeps the place, the category and the line of code that warned.
    """

    def __init__(self, root: Path) -> None:
        """Judge node ids relative to ``root``, the rootdir of the run."""
        self.root = root

    @pytest.hookimpl(tryfirst=True)
    def pytest_warning_recorded(
        self, warning_message: warnings.WarningMessage, nodeid: str
    ) -> None:
        """Replace the message before the terminal and other plugins see it."""
        if nodeid and stage_folder(self.root / nodeid.split("::", 1)[0]) is not None:
            warning_message.message = Warning(HIDDEN)  # the category stays


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``WarningGuard`` unless full reports are asked for."""
    if not full_reports():
        config.pluginmanager.register(WarningGuard(config.rootpath), "vocatron-warning-guard")
