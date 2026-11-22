"""Ctrl-C during a batch: the first one stops politely, the second one at once (ADR-0006).

The first Ctrl-C only sets the stop flag; the batch finishes the stage that is running (a stage
can be minutes of GPU work, and its result is worth keeping) and then stops before the next one.
A second Ctrl-C raises ``KeyboardInterrupt`` in the batch, which kills the child process of the
stage on its way out. The child processes run in sessions of their own, so the terminal's Ctrl-C
reaches Vocatron only.
"""

import signal
from collections.abc import Generator
from contextlib import contextmanager
from types import FrameType

from rich.console import Console

from vocatron.cli.console import print_line
from vocatron.stages.batch import StopFlag

FIRST_NOTICE = (
    "Ctrl-C: finishing the stage that is running, then stopping. "
    "Press Ctrl-C again to stop at once."
)


@contextmanager
def stop_on_interrupt(stop: StopFlag, console: Console) -> Generator[None]:
    """Turn the first Ctrl-C into a stop request on ``stop``, and let the second one through.

    The handler of Ctrl-C that was there before is put back on leaving.
    """

    def handler(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        if stop.requested:
            raise KeyboardInterrupt
        stop.request()
        print_line(console, FIRST_NOTICE)

    previous = signal.signal(signal.SIGINT, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
