"""Checks shared by the tests of the worker processes."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
import torch

from vocatron.core.separation.rules import EXIT_FAILED
from vocatron.core.worker import WorkerJob


def assert_decode_failure_left_evidence(code: int, job: WorkerJob) -> None:
    """A worker that could not decode its audio exited with 1, logged why and wrote no result."""
    assert code == EXIT_FAILED
    log = Path(job.log_path).read_text()
    assert "failed: DecodeError" in log
    assert "Traceback" in log
    assert not Path(job.result_path).exists()


def assert_probe_prints_free_vram(
    main: Callable[[list[str]], int],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Check that a worker's ``--probe`` prints the free GPU memory as JSON (driver faked)."""
    # Stage 1 never touches the GPU: the driver's answer is faked.
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "mem_get_info", lambda: (3 * 2**30, 8 * 2**30))
    assert main(["--probe"]) == 0
    assert json.loads(capsys.readouterr().out) == {"free_vram": 3 * 2**30}
