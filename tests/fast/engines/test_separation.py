"""Stage 1: writing stems, and the parent process that supervises the worker (with a fake one)."""

import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from fakes import fake_worker
from fakes.audio import read_audio
from vocatron.core.errors import StageError
from vocatron.core.separation.file import stem_path
from vocatron.core.separation.job import ModelSetup, SeparationPlan, SeparationResult
from vocatron.core.separation.rules import CEILING_DB, GIB, SAMPLE_RATE, Audio, DeviceRequest, peak
from vocatron.engines.protocols import SeparationRequest, Watch
from vocatron.engines.separation.output import write_flac, write_stems
from vocatron.engines.separation.process import JOB_FILE, RESULT_FILE, ProcessSeparator

CEILING = 10 ** (CEILING_DB / 20)
WORKER = Path(fake_worker.__file__)


def tone(seconds: float = 0.2, level: float = 0.5, seed: int = 0) -> Audio:
    rng = np.random.default_rng(seed)
    return (rng.uniform(-level, level, (2, int(seconds * SAMPLE_RATE)))).astype(np.float32)


def test_flac_is_24_bit_44_1_khz_stereo_and_lossless_to_24_bits(tmp_path: Path) -> None:
    audio = tone()
    write_flac(tmp_path / "a.flac", audio)
    info = sf.info(tmp_path / "a.flac")
    assert (info.format, info.subtype, info.samplerate, info.channels) == (
        "FLAC",
        "PCM_24",
        SAMPLE_RATE,
        2,
    )
    back = read_audio(tmp_path / "a.flac")
    assert back.shape == audio.shape
    assert np.max(np.abs(back - audio)) < 2**-22  # one 24-bit step
    assert not list(tmp_path.glob("*.part"))


def test_the_four_stems_are_written_and_the_karaoke_keeps_the_backing(tmp_path: Path) -> None:
    lead, backing, instrumental = tone(seed=1), tone(seed=2, level=0.2), tone(seed=3)
    gains = write_stems(tmp_path, lead, backing, instrumental, keep_backing=True)
    assert gains.model_dump() == {"lead": 1.0, "backing": 1.0, "instrumental": 1.0, "karaoke": 1.0}
    karaoke = read_audio(tmp_path / stem_path("karaoke"))
    assert np.allclose(karaoke, instrumental + backing, atol=1e-6)
    assert np.allclose(read_audio(tmp_path / stem_path("lead")), lead, atol=1e-6)


def test_without_backing_the_karaoke_is_the_instrumental(tmp_path: Path) -> None:
    instrumental = tone(seed=3)
    write_stems(tmp_path, tone(), tone(seed=2), instrumental, keep_backing=False)
    assert np.allclose(read_audio(tmp_path / stem_path("karaoke")), instrumental, atol=1e-6)


def test_a_stem_above_full_scale_is_scaled_and_the_gain_recorded(tmp_path: Path) -> None:
    instrumental = tone(level=0.9, seed=3) * np.float32(2.0)  # peaks near 1.8
    top = peak(instrumental)
    backing = tone(level=0.1, seed=2)
    gains = write_stems(tmp_path, tone(), backing, instrumental, keep_backing=True)
    assert gains.instrumental == pytest.approx(CEILING / top, rel=1e-5)
    assert gains.lead == 1.0
    assert gains.karaoke < 1  # scaled after mixing, by its own peak
    written = read_audio(tmp_path / stem_path("instrumental"))
    assert peak(written) == pytest.approx(CEILING, abs=1e-5)
    assert peak(read_audio(tmp_path / stem_path("karaoke"))) == pytest.approx(CEILING, abs=1e-5)


class Request:
    """Builds a request in a work folder and remembers the log lines."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        duration: float = 100.0,
        device: DeviceRequest = "auto",
        timeout_factor_gpu: float = 2.0,
        keep_backing: bool = True,
        watch: Watch | None = None,
    ) -> None:
        self.lines: list[str] = []
        self.work = tmp_path / "work"
        self.work.mkdir()
        self.log_path = self.work / "log.txt"
        setup = ModelSetup(
            name="m", revision="r", checkpoint="c", config="y", chunk_size=10, num_overlap=2,
            precision="fp16",
        )  # fmt: skip
        self.request = SeparationRequest(
            audio=tmp_path / "a.mp3",
            work_dir=self.work,
            log_path=self.log_path,
            log=self.lines.append,
            duration=duration,
            device=device,
            timeout_factor_gpu=timeout_factor_gpu,
            timeout_factor_cpu=30.0,
            plan=SeparationPlan(
                keep_backing=keep_backing, vocals_models=(setup,), karaoke_model=setup
            ),
            watch=watch or Watch(),
        )


def separator(mode: str, free: str = str(8 * GIB), base: float = 120.0) -> ProcessSeparator:
    return ProcessSeparator((sys.executable, str(WORKER), mode, free), timeout_base=base)


def test_a_worker_that_succeeds_gives_its_result_and_leaves_no_job_files(tmp_path: Path) -> None:
    made = Request(tmp_path)
    result = separator("ok").separate(made.request)
    assert isinstance(result, SeparationResult)
    assert (result.device, result.samples, result.warnings) == ("cuda", 88200, [])
    assert not (made.work / JOB_FILE).exists()
    assert not (made.work / RESULT_FILE).exists()
    assert "timeout 320 s" in " ".join(made.lines)  # 2 x 100 s + 120 s
    assert "fake worker: ok on cuda, keep_backing=True" in made.log_path.read_text()


def test_the_job_carries_the_models_and_keep_backing(tmp_path: Path) -> None:
    made = Request(tmp_path, keep_backing=False)
    separator("ok").separate(made.request)
    assert "keep_backing=False" in made.log_path.read_text()


def test_without_a_usable_gpu_auto_falls_back_to_the_cpu_with_a_warning(tmp_path: Path) -> None:
    made = Request(tmp_path)
    result = separator("ok", free="none").separate(made.request)
    assert result.device == "cpu"
    assert "about 20x slower" in result.warnings[0]
    assert "timeout 3120 s" in " ".join(made.lines)  # 30 x 100 s + 120 s


def test_a_gpu_with_little_free_memory_is_not_chosen_by_auto(tmp_path: Path) -> None:
    result = separator("ok", free=str(GIB)).separate(Request(tmp_path).request)
    assert result.device == "cpu"


def test_cpu_is_forced_without_a_warning(tmp_path: Path) -> None:
    result = separator("ok").separate(Request(tmp_path, device="cpu").request)
    assert (result.device, result.warnings) == ("cpu", [])


def test_a_forced_gpu_that_is_not_there_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(StageError) as error:
        separator("ok", free="none").separate(Request(tmp_path, device="cuda").request)
    assert error.value.kind == "no-gpu"


def test_the_gpu_is_probed_once_per_separator_in_a_session_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probes = tmp_path / "probes.txt"
    monkeypatch.setenv("FAKE_PROBE_LOG", str(probes))
    probing = separator("ok")
    for name in ("one", "two"):
        sub = tmp_path / name
        sub.mkdir()
        probing.separate(Request(sub).request)
    assert probes.read_text().splitlines() == ["probe own_session=True"]


def test_an_unreadable_probe_counts_as_no_gpu(tmp_path: Path) -> None:
    result = separator("badprobe").separate(Request(tmp_path).request)
    assert result.device == "cpu"


def test_a_worker_that_fails_gives_a_clear_error_with_the_end_of_the_log(tmp_path: Path) -> None:
    made = Request(tmp_path)
    with pytest.raises(StageError) as error:
        separator("fail").separate(made.request)
    assert error.value.kind == "separation-failed"
    assert "code 1" in str(error.value)
    assert "fake worker: fail on cuda" in str(error.value)
    assert not (made.work / JOB_FILE).exists()


def test_a_worker_that_is_killed_reports_the_signal(tmp_path: Path) -> None:
    with pytest.raises(StageError, match="signal 9") as error:
        separator("killed").separate(Request(tmp_path).request)
    assert error.value.kind == "separation-failed"


def test_out_of_memory_has_its_own_error_and_advice(tmp_path: Path) -> None:
    with pytest.raises(StageError, match="--device cpu") as error:
        separator("oom").separate(Request(tmp_path).request)
    assert error.value.kind == "out-of-memory"


def test_a_worker_that_hangs_is_killed_at_the_timeout(tmp_path: Path) -> None:
    made = Request(tmp_path, duration=0.1, timeout_factor_gpu=1.0)
    with pytest.raises(StageError, match="did not finish within") as error:
        separator("hang", base=0.4).separate(made.request)
    assert error.value.kind == "separation-timeout"
    assert "timeout_factor_gpu" in str(error.value)
    assert any("killed" in line for line in made.lines)
    assert not (made.work / JOB_FILE).exists()


@pytest.mark.parametrize("mode", ["noresult", "garbage"])
def test_a_worker_that_leaves_no_valid_result_fails_the_song(tmp_path: Path, mode: str) -> None:
    with pytest.raises(StageError, match="no valid result") as error:
        separator(mode).separate(Request(tmp_path).request)
    assert error.value.kind == "separation-failed"


def test_a_missing_worker_command_fails_the_song_with_a_clear_error(tmp_path: Path) -> None:
    gone = ProcessSeparator((str(tmp_path / "no-such-python"),))
    with pytest.raises(StageError, match="cannot start the separation process") as error:
        gone.separate(Request(tmp_path, device="cpu").request)
    assert error.value.kind == "separation-failed"


def test_the_progress_lines_of_the_worker_reach_the_watch_and_other_lines_are_ignored(
    tmp_path: Path,
) -> None:
    heard: list[float] = []
    made = Request(tmp_path, watch=Watch(progress=heard.append))
    separator("ok").separate(made.request)
    assert heard == [0.25, 0.5, 1.0]


def test_the_time_left_of_the_song_stops_the_worker_before_its_own_timeout(
    tmp_path: Path,
) -> None:
    made = Request(tmp_path, watch=Watch(time_left=lambda: 0.4))  # its own limit is 320 s
    started = time.monotonic()
    with pytest.raises(StageError, match="time limit of this song") as error:
        separator("hang").separate(made.request)
    assert error.value.kind == "time-limit"
    assert time.monotonic() - started < 15
    assert not (made.work / JOB_FILE).exists()


def test_the_worker_runs_in_a_session_of_its_own_so_the_terminal_ctrl_c_misses_it(
    tmp_path: Path,
) -> None:
    made = Request(tmp_path)
    separator("ok").separate(made.request)
    assert "own_session=True" in made.log_path.read_text()


def test_a_second_ctrl_c_kills_the_worker_it_waits_for(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_wait = subprocess.Popen.wait

    def interrupted(self: subprocess.Popen[str], timeout: float | None = None) -> int:
        if timeout is not None and "--probe" not in str(self.args):  # the worker, not the probe
            raise KeyboardInterrupt
        return real_wait(self, timeout)

    monkeypatch.setattr(subprocess.Popen, "wait", interrupted)
    made = Request(tmp_path)
    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        separator("hang").separate(made.request)
    assert time.monotonic() - started < 15  # the worker did not sleep its 30 seconds out
