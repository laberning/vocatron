"""Stage 1: the parent process that supervises the acoustic worker (with a fake one)."""

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from fakes import fake_worker
from vocatron.core.alignment.job import AcousticSetup
from vocatron.core.errors import StageError
from vocatron.core.separation.rules import GIB, DeviceRequest
from vocatron.engines.alignment.process import (
    BACKING_EMISSIONS_FILE,
    BACKING_LOUDNESS_FILE,
    EMISSIONS_FILE,
    JOB_FILE,
    LEAD_LOUDNESS_FILE,
    LOUDNESS_FILE,
    RESULT_FILE,
    ProcessAcousticModel,
)
from vocatron.engines.protocols import AcousticRequest

WORKER = Path(fake_worker.__file__)


class Request:
    """Builds a request in a work folder and remembers the log lines."""

    def __init__(self, tmp_path: Path, *, device: DeviceRequest = "auto") -> None:
        self.lines: list[str] = []
        self.work = tmp_path / "work"
        self.work.mkdir()
        self.log_path = self.work / "log.txt"
        self.request = AcousticRequest(
            audio=tmp_path / "lead.flac",
            work_dir=self.work,
            log_path=self.log_path,
            log=self.lines.append,
            duration=100.0,
            device=device,
            timeout_factor_gpu=1.0,
            timeout_factor_cpu=15.0,
            model=AcousticSetup(name="m", revision="r", folder="f", precision="fp16"),
            piece_seconds=30.0,
            overlap_seconds=2.0,
        )


def model(mode: str, free: str = str(8 * GIB), base: float = 120.0) -> ProcessAcousticModel:
    return ProcessAcousticModel((sys.executable, str(WORKER), mode, free), timeout_base=base)


def test_a_worker_that_succeeds_gives_the_frames_and_leaves_no_files(tmp_path: Path) -> None:
    made = Request(tmp_path)
    heard = model("ok").log_probs(made.request)
    assert heard.emissions.log_probs.shape == (7, 4)
    assert heard.emissions.log_probs.dtype == np.float32
    assert heard.emissions.vocabulary == ("<pad>", "|", "a", "b")
    assert heard.emissions.seconds_per_frame == 0.02
    assert heard.emissions.loudness is not None
    assert heard.emissions.loudness.shape == (7,)
    assert (heard.result.device, heard.result.warnings) == ("cuda", [])
    assert sorted(p.name for p in made.work.iterdir()) == ["log.txt"]
    for name in (JOB_FILE, RESULT_FILE, EMISSIONS_FILE, LOUDNESS_FILE):
        assert not (made.work / name).exists()
    assert "timeout 220 s" in " ".join(made.lines)  # 1 x 100 s + 120 s
    assert "alignment: starting the worker on cuda" in " ".join(made.lines)


def test_a_worker_that_hears_the_backing_gives_its_part_and_leaves_no_files(
    tmp_path: Path,
) -> None:
    made = Request(tmp_path)
    request = replace(made.request, backing=tmp_path / "backing.flac", hear_backing=True)
    heard = model("ok").log_probs(request)
    part = heard.emissions.backing
    assert part is not None
    assert part.log_probs.shape == (7, 4)
    assert part.lead_loudness.shape == part.backing_loudness.shape == (7,)
    assert sorted(p.name for p in made.work.iterdir()) == ["log.txt"]
    for name in (BACKING_EMISSIONS_FILE, LEAD_LOUDNESS_FILE, BACKING_LOUDNESS_FILE):
        assert not (made.work / name).exists()
    assert heard.emissions.loudness is not None


def test_a_worker_that_does_not_hear_the_backing_gives_no_part(tmp_path: Path) -> None:
    assert model("ok").log_probs(Request(tmp_path).request).emissions.backing is None


def test_without_a_usable_gpu_the_cpu_runs_with_a_warning_and_the_cpu_timeout(
    tmp_path: Path,
) -> None:
    made = Request(tmp_path)
    heard = model("ok", free="none").log_probs(made.request)
    assert heard.result.device == "cpu"
    assert "about 20x slower" in heard.result.warnings[0]
    assert "timeout 1620 s" in " ".join(made.lines)  # 15 x 100 s + 120 s


def test_a_forced_gpu_that_is_not_there_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(StageError) as error:
        model("ok", free="none").log_probs(Request(tmp_path, device="cuda").request)
    assert error.value.kind == "no-gpu"


@pytest.mark.parametrize(
    ("mode", "kind", "text"),
    [
        ("fail", "alignment-failed", "code 1"),
        ("killed", "alignment-failed", "signal 9"),
        ("oom", "out-of-memory", "ran out of memory"),
        ("noresult", "alignment-failed", "no valid result"),
        ("garbage", "alignment-failed", "no valid result"),
        ("badframes", "alignment-failed", "shape"),
        ("badloudness", "alignment-failed", "shape"),
        ("noloudness", "alignment-failed", "no valid frames"),
        ("badbacking", "alignment-failed", "shape"),
        ("nobacking", "alignment-failed", "no valid frames"),
    ],
)
def test_a_worker_that_goes_wrong_gives_a_typed_error_and_leaves_no_files(
    tmp_path: Path, mode: str, kind: str, text: str
) -> None:
    made = Request(tmp_path)
    made.request = replace(made.request, backing=tmp_path / "backing.flac", hear_backing=True)
    with pytest.raises(StageError, match=text) as error:
        model(mode).log_probs(made.request)
    assert error.value.kind == kind
    assert sorted(p.name for p in made.work.iterdir()) == ["log.txt"]


def test_a_worker_that_hangs_is_killed_at_the_timeout(tmp_path: Path) -> None:
    made = Request(tmp_path)
    with pytest.raises(StageError, match="alignment did not finish") as error:
        model("hang", base=0.5).log_probs(replace(made.request, duration=0.0))
    assert error.value.kind == "alignment-timeout"
    assert "alignment.timeout_factor_gpu" in str(error.value)


def test_a_missing_worker_is_an_error(tmp_path: Path) -> None:
    missing = ProcessAcousticModel(("/no/such/program",))
    with pytest.raises(StageError, match="cannot start the alignment process"):
        missing.log_probs(Request(tmp_path).request)
