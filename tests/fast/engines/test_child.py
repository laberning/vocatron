"""Stage 1: watched child processes leave nothing behind (real, short-lived Python children)."""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from vocatron.engines.child import run_child

SLEEPER = "import os, sys, time; print(os.getpid(), os.getsid(0), flush=True); time.sleep(30)"


def alive(pid: int) -> bool:
    """Tell whether ``pid`` still exists, a zombie that nobody reaped included."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def gone_soon(pid: int) -> bool:
    """Tell whether ``pid`` (not our child, so reaped by someone else) is dead within seconds."""
    for _ in range(100):
        stat = Path(f"/proc/{pid}/stat")
        try:
            if stat.read_text().split(") ", 1)[1].startswith("Z"):  # dead, waiting to be reaped
                return True
        except FileNotFoundError, IndexError:
            return True
        time.sleep(0.05)
    return False


def test_a_child_reports_its_lines_its_code_and_its_errors() -> None:
    lines: list[str] = []
    script = "import sys; print('one'); print('two'); sys.stderr.write('oops\\n'); sys.exit(3)"
    ended = run_child([sys.executable, "-c", script], 30, lines.append)
    assert lines == ["one", "two"]
    assert (ended.code, ended.errors) == (3, "oops")


class Announced:
    """Runs the sleeper; the wait for it raises ``error`` once the child said who it is."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
        self.lines: list[str] = []
        self.started = threading.Event()
        real_wait = subprocess.Popen.wait

        def wait(process: subprocess.Popen[bytes], timeout: float | None = None) -> int:
            if timeout is not None:  # the wait for the child, not the one that reaps it
                self.started.wait(10)
                raise error
            return real_wait(process, timeout)

        monkeypatch.setattr(subprocess.Popen, "wait", wait)

    def heard(self, line: str) -> None:
        self.lines.append(line)
        self.started.set()

    def run(self) -> None:
        run_child([sys.executable, "-c", SLEEPER], 30, self.heard)

    def pid_and_session(self) -> tuple[int, int]:
        pid, session = (int(part) for part in self.lines[0].split())
        return pid, session


def test_a_child_that_overruns_is_killed_and_runs_in_a_session_of_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Announced(monkeypatch, subprocess.TimeoutExpired("sleeper", 30))
    with pytest.raises(subprocess.TimeoutExpired):
        child.run()
    pid, session = child.pid_and_session()
    assert pid == session  # the Ctrl-C of the terminal does not reach it
    assert not alive(pid)  # killed and reaped: no process is left holding the GPU


def test_a_second_ctrl_c_while_waiting_kills_and_reaps_the_child() -> None:
    lines: list[str] = []
    announced = threading.Event()

    def heard(line: str) -> None:
        lines.append(line)
        announced.set()

    def press_ctrl_c() -> None:
        if announced.wait(10):
            signal.pthread_kill(threading.main_thread().ident or 0, signal.SIGINT)

    previous = signal.signal(signal.SIGINT, signal.default_int_handler)  # a real Ctrl-C
    try:
        threading.Thread(target=press_ctrl_c, daemon=True).start()
        with pytest.raises(KeyboardInterrupt):
            run_child([sys.executable, "-c", SLEEPER], 30, heard)
    finally:
        signal.signal(signal.SIGINT, previous)
    assert not alive(int(lines[0].split()[0]))  # no zombie either: Python leaves that to us


def test_a_killed_child_takes_what_it_started_along(monkeypatch: pytest.MonkeyPatch) -> None:
    child = Announced(monkeypatch, subprocess.TimeoutExpired("parent", 30))
    starter = (
        "import subprocess, sys, time; "
        f"helper = subprocess.Popen([sys.executable, '-c', {SLEEPER!r}], stdout=sys.stdout); "
        "time.sleep(30)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_child([sys.executable, "-c", starter], 30, child.heard)
    helper = int(child.lines[0].split()[0])
    assert gone_soon(helper)  # its own group went with it: nothing keeps the pipe or the GPU


def test_a_missing_program_cannot_be_started(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run_child([str(tmp_path / "nothing")], 1, lambda line: None)
