"""The separator that runs the worker as a child process with a timeout (ADR-0002, ADR-0007).

The process handling is shared with the alignment (``vocatron.engines.gpu_process``). The parent
imports no PyTorch.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from vocatron.core.separation.job import SeparationJob, SeparationResult
from vocatron.core.separation.rules import TIMEOUT_BASE
from vocatron.engines.gpu_process import Supervisor
from vocatron.engines.protocols import SeparationRequest

WORKER_COMMAND = (sys.executable, "-m", "vocatron.engines.separation.worker")
JOB_FILE = "separation-job.json"
RESULT_FILE = "separation-result.json"


class ProcessSeparator:
    """Separates songs in a child process."""

    def __init__(
        self, command: Sequence[str] = WORKER_COMMAND, timeout_base: float = TIMEOUT_BASE
    ) -> None:
        """Run ``command`` plus the job file; ``timeout_base`` is added to every timeout."""
        self._supervisor = Supervisor("separation", command, timeout_base)

    def separate(self, request: SeparationRequest) -> SeparationResult:
        """Run the worker on the song and return its result.

        Raises:
            StageError: ``no-gpu`` or ``vram-too-small`` for a forced GPU that cannot work,
                ``separation-timeout``, ``out-of-memory``, or ``separation-failed`` when the worker
                crashes or leaves no valid result.
        """
        choice = self._supervisor.choose(request.device)
        limit = self._supervisor.limit(
            request.duration, choice.device, request.timeout_factor_gpu, request.timeout_factor_cpu
        )
        job = SeparationJob(
            audio=str(request.audio),
            out_folder=str(request.work_dir),
            log_path=str(request.log_path),
            result_path=str(request.work_dir / RESULT_FILE),
            device=choice.device,
            **dict(request.plan),
        )
        job_path: Path = request.work_dir / JOB_FILE
        result = self._supervisor.run(
            job, job_path, limit, request.log, SeparationResult, request.watch
        )
        return result.model_copy(update={"warnings": [choice.warning] if choice.warning else []})
