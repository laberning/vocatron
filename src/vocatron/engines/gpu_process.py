"""The parent side of a GPU worker process, shared by the separation and the alignment.

A hung driver or a crash of the GPU work must fail one song, never the batch: the parent starts
``python -m <worker module> <job.json>``, waits for it for a limited time, kills it on expiry,
and turns exit codes into typed stage errors. The parent imports no PyTorch (ADR-0002, ADR-0007).
"""

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ValidationError

from vocatron.core.errors import StageError
from vocatron.core.separation.rules import (
    DEFAULT_DURATION,
    EXIT_OUT_OF_MEMORY,
    TIMEOUT_BASE,
    VRAM_FRACTION,
    Device,
    DeviceChoice,
    DeviceRequest,
    choose_device,
    timeout_seconds,
)
from vocatron.core.worker import WorkerJob, effective_limit, parse_progress
from vocatron.engines.child import run_child
from vocatron.engines.protocols import Watch

PROBE_TIMEOUT = 120.0  # seconds; importing PyTorch and asking the driver
LOG_TAIL = 8  # lines of the song log shown in an error message


def _report(watch: Watch) -> Callable[[str], None]:
    """Return what reads the worker's standard output: progress lines go to ``watch``."""

    def handle(line: str) -> None:
        if (fraction := parse_progress(line)) is not None:
            watch.progress(fraction)

    return handle


def _tail(path: Path) -> str:
    """Return the last lines of the song log, for an error message."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-LOG_TAIL:])


class Supervisor:
    """Runs jobs of one kind in a child process: ``separation`` or ``alignment``."""

    def __init__(
        self, task: str, command: Sequence[str], timeout_base: float = TIMEOUT_BASE
    ) -> None:
        """Run ``command`` plus the job file; ``timeout_base`` is added to every timeout.

        Args:
            task: The name used in log lines and error codes (``separation``).
            command: The worker command, without the job file.
            timeout_base: Seconds added to the song-length part of every timeout.
        """
        self._task = task
        self._command = tuple(command)
        self._timeout_base = timeout_base
        self._probed = False
        self._free_vram: int | None = None

    def _free_gpu_memory(self) -> int | None:
        """Ask the worker once how much GPU memory is free; ``None`` when there is no usable GPU."""
        if not self._probed:
            self._free_vram = self._probe()
            self._probed = True
        return self._free_vram

    def _probe(self) -> int | None:
        """Run the worker's ``--probe``; any failure counts as no GPU.

        The probe runs in a session of its own like the worker: a first Ctrl-C must not kill it,
        or the stage it belongs to would quietly run on the CPU.
        """
        try:
            result = subprocess.run(
                [*self._command, "--probe"],
                capture_output=True,
                text=True,
                check=True,
                timeout=PROBE_TIMEOUT,
                start_new_session=True,
            )
            free = json.loads(result.stdout.strip().splitlines()[-1])["free_vram"]
        except OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError:
            return None
        return free if isinstance(free, int) else None

    def choose(self, requested: DeviceRequest) -> DeviceChoice:
        """Decide where the job runs.

        Raises:
            StageError: ``no-gpu`` or ``vram-too-small`` for a forced GPU that cannot work.
        """
        return choose_device(requested, self._free_gpu_memory())

    def limit(
        self, duration: float | None, device: Device, factor_gpu: float, factor_cpu: float
    ) -> float:
        """Return how many seconds the worker may run for a song of ``duration`` seconds."""
        length = duration if duration is not None else DEFAULT_DURATION
        return timeout_seconds(length, device, factor_gpu, factor_cpu, self._timeout_base)

    def run[R: BaseModel](
        self,
        job: WorkerJob,
        job_path: Path,
        limit: float,
        log: Callable[[str], None],
        result_model: type[R],
        watch: Watch | None = None,
    ) -> R:
        """Run the worker on ``job`` and return its result.

        Args:
            job: The job; its ``result_path`` and ``log_path`` say where the worker writes.
            job_path: Where to write the job file for the worker.
            limit: How many seconds the worker may run.
            log: Writes a line to the song log.
            result_model: The result the worker writes.
            watch: Gets the progress the worker reports, and says how much time the song has
                left; the worker is stopped when that runs out.

        Raises:
            StageError: ``<task>-timeout``, ``time-limit`` when the song's safety limit ran out,
                ``out-of-memory``, or ``<task>-failed`` when the worker cannot start, crashes or
                leaves no valid result.
        """
        result_path = Path(job.result_path)
        job_path.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        result_path.unlink(missing_ok=True)
        log(f"{self._task}: starting the worker on {job.device}, timeout {limit:.0f} s")
        try:
            code = self._execute(job_path, limit, job.device, log, watch or Watch())
            return self._result(result_path, code, Path(job.log_path), result_model)
        finally:
            job_path.unlink(missing_ok=True)
            result_path.unlink(missing_ok=True)

    def _execute(
        self, job_path: Path, limit: float, device: str, log: Callable[[str], None], watch: Watch
    ) -> int:
        """Run the worker; kill it when it overruns. Return its exit code.

        The worker runs in a session of its own, so the Ctrl-C of the terminal reaches this
        process only: the first one lets the stage finish, a second one lands here and kills it.
        """
        bound, by_song = effective_limit(limit, watch.time_left())
        try:
            ended = run_child([*self._command, str(job_path)], bound, _report(watch))
        except OSError as error:
            raise StageError(
                f"{self._task}-failed", f"cannot start the {self._task} process: {error}"
            ) from error
        except subprocess.TimeoutExpired:
            log(f"{self._task}: the worker did not finish within {bound:.0f} s; killed")
            if by_song:
                raise StageError(
                    "time-limit",
                    f"the time limit of this song ran out while the {self._task} was "
                    "running; the process was stopped",
                ) from None
            raise StageError(
                f"{self._task}-timeout",
                f"{self._task} did not finish within {bound:.0f} s on the {device}; the "
                f"process was stopped. Raise {self._task}.timeout_factor_gpu or "
                "timeout_factor_cpu, or choose another --device.",
            ) from None
        text = ended.errors.strip()
        if text:
            log(f"{self._task}: worker stderr: {text.splitlines()[-1]}")
        return ended.code

    def _result[R: BaseModel](
        self, result_path: Path, code: int, log_path: Path, result_model: type[R]
    ) -> R:
        """Turn the exit code and the result file into the result or a typed error."""
        if code == EXIT_OUT_OF_MEMORY:
            raise StageError(
                "out-of-memory",
                f"the GPU ran out of memory (the cap is {VRAM_FRACTION:.0%} of it); close other "
                "programs that use the GPU, or use --device cpu",
            )
        if code != 0:
            how = f"signal {-code}" if code < 0 else f"code {code}"
            raise StageError(
                f"{self._task}-failed",
                f"the {self._task} process stopped with {how}; the end of the log:\n"
                f"{_tail(log_path)}",
            )
        try:
            return result_model.model_validate_json(result_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise StageError(
                f"{self._task}-failed", f"the {self._task} process left no valid result: {error}"
            ) from error
