"""What every GPU worker process is handed: the base of the job messages (ADR-0007).

The separation and the alignment each run their heavy work in a child process that reads a job
file and writes a result file. The fields in common are here; the exit codes are in
``vocatron.core.separation.rules``. A worker tells its parent how far it is with progress lines on
its standard output, which both sides read with the functions here, and the parent never lets a
worker run longer than the time left of the song's safety limit (``effective_limit``).
"""

import re

from pydantic import BaseModel, ConfigDict

from vocatron.core.separation.rules import VRAM_FRACTION, Device


class Frozen(BaseModel):
    """Base of the messages: strict and immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkerJob(Frozen):
    """The part of a job that every worker needs.

    Attributes:
        log_path: The song log, to which the worker appends.
        result_path: Where the worker writes its result.
        device: Where to run (decided by the parent).
        vram_fraction: The share of GPU memory PyTorch may take.
    """

    log_path: str
    result_path: str
    device: Device
    vram_fraction: float = VRAM_FRACTION


PROGRESS_PREFIX = "progress "
_PROGRESS = re.compile(r"progress (?P<done>\d+) (?P<total>\d+)")
"""A worker tells its parent how far it is with lines ``progress <done> <total>``."""


def progress_line(done: int, total: int) -> str:
    """Return the line a worker prints when ``done`` of ``total`` pieces are finished."""
    return f"{PROGRESS_PREFIX}{done} {total}"


def parse_progress(line: str) -> float | None:
    """Return the fraction (0 to 1) a progress line says, or ``None`` for any other line.

    A line the worker's libraries print for their own reasons is not an error, just not progress.
    """
    if not line.startswith(PROGRESS_PREFIX):
        return None
    match = _PROGRESS.fullmatch(line.strip())
    if match is None:
        return None
    done, total = int(match["done"]), int(match["total"])
    return min(done / total, 1.0) if total else None


def effective_limit(limit: float, time_left: float | None) -> tuple[float, bool]:
    """Return how long a process may run, and whether the time left of the song set that limit.

    Args:
        limit: The seconds the process may run by its own settings.
        time_left: The seconds left of the safety limit of the song, or ``None`` for no limit.

    Returns:
        The shorter of the two (never below zero), and ``True`` when that is the song's.
    """
    if time_left is not None and time_left < limit:
        return max(time_left, 0.0), True
    return limit, False
