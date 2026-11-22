"""The acoustic model that runs its worker as a child process with a timeout (ADR-0002).

The process handling is shared with the separation (``vocatron.engines.gpu_process``). The parent
imports no PyTorch; the frames and the loudness per frame come back in NumPy files (with the
backing heard, three more: its frames and the loudness of each stem alone, ADR-0014).
"""

import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from vocatron.core.alignment.chunks import BackingPart, Emissions
from vocatron.core.alignment.job import AcousticJob, AcousticResult
from vocatron.core.errors import StageError
from vocatron.core.separation.rules import TIMEOUT_BASE
from vocatron.engines.gpu_process import Supervisor
from vocatron.engines.protocols import AcousticRequest, Heard

WORKER_COMMAND = (sys.executable, "-m", "vocatron.engines.alignment.worker")
JOB_FILE = "alignment-job.json"
RESULT_FILE = "alignment-result.json"
EMISSIONS_FILE = "alignment-emissions.npy"
LOUDNESS_FILE = "alignment-loudness.npy"
BACKING_EMISSIONS_FILE = "alignment-backing-emissions.npy"
LEAD_LOUDNESS_FILE = "alignment-lead-loudness.npy"
BACKING_LOUDNESS_FILE = "alignment-backing-loudness.npy"


class ProcessAcousticModel:
    """Runs the acoustic model in a child process."""

    def __init__(
        self, command: Sequence[str] = WORKER_COMMAND, timeout_base: float = TIMEOUT_BASE
    ) -> None:
        """Run ``command`` plus the job file; ``timeout_base`` is added to every timeout."""
        self._supervisor = Supervisor("alignment", command, timeout_base)

    def log_probs(self, request: AcousticRequest) -> Heard:
        """Run the worker on the lead vocals and return the log-probabilities.

        Raises:
            StageError: ``no-gpu`` or ``vram-too-small`` for a forced GPU that cannot work,
                ``alignment-timeout``, ``out-of-memory``, or ``alignment-failed`` when the worker
                crashes or leaves no valid result.
        """
        choice = self._supervisor.choose(request.device)
        limit = self._supervisor.limit(
            request.duration, choice.device, request.timeout_factor_gpu, request.timeout_factor_cpu
        )
        emissions_path = request.work_dir / EMISSIONS_FILE
        loudness_path = request.work_dir / LOUDNESS_FILE
        extra = (
            request.work_dir / BACKING_EMISSIONS_FILE,
            request.work_dir / LEAD_LOUDNESS_FILE,
            request.work_dir / BACKING_LOUDNESS_FILE,
        )
        job = AcousticJob(
            audio=str(request.audio),
            backing=None if request.backing is None else str(request.backing),
            sum_backing=request.sum_backing,
            hear_backing=request.hear_backing,
            backing_emissions_path=str(extra[0]) if request.hear_backing else None,
            lead_loudness_path=str(extra[1]) if request.hear_backing else None,
            backing_loudness_path=str(extra[2]) if request.hear_backing else None,
            emissions_path=str(emissions_path),
            loudness_path=str(loudness_path),
            log_path=str(request.log_path),
            result_path=str(request.work_dir / RESULT_FILE),
            device=choice.device,
            model=request.model,
            piece_seconds=request.piece_seconds,
            overlap_seconds=request.overlap_seconds,
        )
        try:
            result = self._supervisor.run(
                job,
                request.work_dir / JOB_FILE,
                limit,
                request.log,
                AcousticResult,
                request.watch,
            )
            log_probs = _read(emissions_path, result, (len(result.vocabulary),), np.float32)
            loudness = _read(loudness_path, result, (), np.float32)
            backing = None
            if request.hear_backing:
                backing = BackingPart(
                    _read(extra[0], result, (len(result.vocabulary),), np.float32),
                    _read(extra[1], result, (), np.float32),
                    _read(extra[2], result, (), np.float32),
                )
        finally:
            for path in (emissions_path, loudness_path, *extra):
                path.unlink(missing_ok=True)
        warnings = [choice.warning] if choice.warning else []
        return Heard(
            Emissions(
                log_probs, result.seconds_per_frame, tuple(result.vocabulary), loudness, backing
            ),
            result.model_copy(update={"warnings": warnings}),
        )


def _read(
    path: Path, result: AcousticResult, trailing: tuple[int, ...], dtype: type[np.float32]
) -> NDArray[np.float32]:
    """Read a frame file the worker wrote and check it against its result.

    Args:
        path: The ``.npy`` file.
        result: What the worker reported; the file has ``result.frames`` rows.
        trailing: The shape of every row (``(vocabulary,)`` for log-probabilities, ``()`` for
            the loudness).
        dtype: The type the file must have.

    Raises:
        StageError: ``alignment-failed`` if the file is missing, unreadable or the wrong shape.
    """
    try:
        frames = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as error:
        raise StageError(
            "alignment-failed", f"the alignment process left no valid frames: {error}"
        ) from error
    wanted = (result.frames, *trailing)
    if frames.dtype != dtype or frames.shape != wanted:
        raise StageError(
            "alignment-failed", f"the alignment frames have shape {frames.shape}, not {wanted}"
        )
    return frames
