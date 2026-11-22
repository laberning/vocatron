"""Child processes that are watched while they run: the GPU workers and ffmpeg (ADR-0007).

A child runs in a session of its own, so the Ctrl-C of the terminal reaches Vocatron only: the
first one lets the stage finish, a second one interrupts the wait here and kills the child. Its
standard output is read line by line while it runs (the progress lines), its error output is
kept for the message of a failure. A child that overruns its limit is killed as well; nothing is
left behind holding the GPU.
"""

import os
import signal
import subprocess
import threading
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import IO

READER_JOIN = 5.0  # seconds to wait for the last lines of a child that ended
REAP_WAIT = 5.0  # seconds to wait for a killed child to be gone


@dataclass(frozen=True)
class Ended:
    """A child that ended by itself.

    Attributes:
        code: Its exit code (negative for the signal that killed it).
        errors: What it wrote on its error output.
    """

    code: int
    errors: str


def _read(stream: IO[bytes] | None, handle: Callable[[str], None]) -> threading.Thread:
    """Start a thread that hands every line of ``stream`` to ``handle``, and return it."""

    def pump() -> None:
        if stream is not None:
            for raw in stream:
                handle(raw.decode(errors="replace").rstrip("\r\n"))

    thread = threading.Thread(target=pump, daemon=True)
    thread.start()
    return thread


def kill(process: subprocess.Popen[bytes]) -> None:
    """Kill a child that runs in a session of its own, with everything it started, and reap it.

    The whole process group goes, so no helper process of the child is left holding the GPU or
    a pipe. The wait for it is short and bounded: Python does not reap a child itself when a
    Ctrl-C interrupted the wait for it, and a zombie would linger until Vocatron exits.
    """
    with suppress(ProcessLookupError, PermissionError):  # already gone
        os.killpg(process.pid, signal.SIGKILL)
    process.kill()  # the child itself, should its group be gone already
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=REAP_WAIT)


def run_child(command: Sequence[str], limit: float, on_line: Callable[[str], None]) -> Ended:
    """Run ``command`` in a session of its own and wait at most ``limit`` seconds for it.

    Args:
        command: The program and its arguments.
        limit: How many seconds it may run.
        on_line: Gets every line of its standard output while it runs (from another thread).

    Returns:
        Its exit code and its error output.

    Raises:
        OSError: If it cannot be started (``FileNotFoundError`` when the program is missing).
        subprocess.TimeoutExpired: If it ran longer than ``limit``; it was killed.
    """
    errors: list[str] = []
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    with process:  # leaving waits for the child, so a killed one is reaped
        readers: list[threading.Thread] = []
        try:
            readers = [_read(process.stdout, on_line), _read(process.stderr, errors.append)]
            process.wait(timeout=limit)
        except BaseException:  # overrun, or a second Ctrl-C: leave no child behind
            kill(process)
            raise
        finally:
            for reader in readers:
                reader.join(timeout=READER_JOIN)
    return Ended(int(process.returncode), "\n".join(errors))
