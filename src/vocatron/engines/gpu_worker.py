"""What every GPU worker process does around its work (ADR-0002, ADR-0007).

``python -m <worker module> <job.json>`` reads the job, does the work, writes the result file and
exits with 0 (done), 1 (failed) or 3 (out of memory). While it works it prints
``progress <done> <total>`` lines on its standard output for the parent. ``--probe`` prints the
free GPU memory instead. Every step is logged to the song log and synced to disk, so a crash
leaves evidence. This module imports PyTorch; the parent side (``gpu_process``) does not.
"""

import json
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import torch

from vocatron.core.separation.rules import EXIT_FAILED, EXIT_OUT_OF_MEMORY
from vocatron.core.worker import WorkerJob, progress_line
from vocatron.engines.clock import SystemClock
from vocatron.engines.files import FileLog
from vocatron.engines.protocols import LogSink

GIB = 1 << 30


class Logger:
    """Writes timestamped lines to the song log."""

    def __init__(self, sink: LogSink, task: str) -> None:
        """Write to ``sink``; every line says it comes from the ``task`` worker."""
        self._sink = sink
        self._task = task
        self._clock = SystemClock()

    def __call__(self, message: str) -> None:
        """Write one line, synced to disk."""
        stamp = self._clock.now().isoformat(timespec="seconds")
        self._sink.write(f"{stamp} {self._task} worker: {message}")

    @staticmethod
    def progress(done: int, total: int) -> None:
        """Tell the parent that ``done`` of ``total`` pieces are finished (standard output)."""
        print(progress_line(done, total), flush=True)


class WorkerResult(Protocol):
    """What a worker hands back: it can be written as JSON and says what it cost."""

    @property
    def seconds(self) -> float:
        """How long the work took."""
        ...

    @property
    def peak_vram_gib(self) -> float | None:
        """The most GPU memory used, or ``None`` on the CPU."""
        ...

    def model_dump_json(self) -> str:
        """Return the result as JSON."""
        ...


def probe() -> int:
    """Print what the GPU offers as JSON: ``{"free_vram": bytes or null}``."""
    free: int | None = None
    if torch.cuda.is_available():
        free = int(torch.cuda.mem_get_info()[0])
    print(json.dumps({"free_vram": free}))
    return 0


def cap_memory(job: WorkerJob, log: Logger, note: str = "fp16") -> None:
    """Cap the GPU memory PyTorch may take at the job's share, when the job runs on the GPU."""
    if job.device == "cuda":
        torch.cuda.set_per_process_memory_fraction(job.vram_fraction)
        total = torch.cuda.get_device_properties(0).total_memory
        log(f"GPU memory capped at {job.vram_fraction:.0%} of {total / GIB:.2f} GiB, {note}")


def peak_vram_gib(device: str) -> float | None:
    """Return the most GPU memory PyTorch has used in GiB, or ``None`` on the CPU."""
    return torch.cuda.max_memory_allocated() / GIB if device == "cuda" else None


def run_worker[J: WorkerJob](
    argv: list[str], task: str, job_model: type[J], work: Callable[[J, Logger], WorkerResult]
) -> int:
    """Run a worker: ``argv`` is ``["--probe"]`` or the path of the job file.

    Args:
        argv: The command-line arguments after the module.
        task: The name in the log lines (``separation``).
        job_model: The job message.
        work: Does the job and returns its result.

    Returns:
        The exit code: 0 done, 1 failed, 3 out of GPU memory.
    """
    if argv == ["--probe"]:
        return probe()
    job = job_model.model_validate_json(Path(argv[0]).read_text(encoding="utf-8"))
    sink = FileLog(Path(job.log_path))
    log = Logger(sink, task)
    try:
        result = work(job, log)
        Path(job.result_path).write_text(result.model_dump_json(), encoding="utf-8")
        log(f"finished in {result.seconds:.1f} s, peak VRAM {result.peak_vram_gib}")
        return 0
    except torch.OutOfMemoryError as error:
        log(f"out of memory: {error}")
        return EXIT_OUT_OF_MEMORY
    except Exception as error:  # the process boundary: whatever happens must reach the log
        log(f"failed: {type(error).__name__}: {error}")
        for line in traceback.format_exception(error):
            log(line.rstrip())
        return EXIT_FAILED
    finally:
        sink.close()
