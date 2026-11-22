"""Stage 1: the acoustic worker with a tiny random wav2vec2: pieces, frames, exit codes."""

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import torch

from fakes.acoustic import VOCABULARY
from fakes.wav2vec import write_tiny_model
from fakes.workers import assert_decode_failure_left_evidence, assert_probe_prints_free_vram
from vocatron.core.alignment.chunks import SAMPLE_RATE, STRIDE, frame_count
from vocatron.core.alignment.job import AcousticJob, AcousticResult, AcousticSetup
from vocatron.core.separation.rules import EXIT_OUT_OF_MEMORY
from vocatron.engines.alignment import worker
from vocatron.engines.alignment.inference import load_vocabulary


def make_job(tmp_path: Path, audio: Path, piece: float = 1.0, overlap: float = 0.25) -> AcousticJob:
    folder = tmp_path / "model"
    if not folder.exists():
        write_tiny_model(folder)
    return AcousticJob(
        audio=str(audio),
        emissions_path=str(tmp_path / "frames.npy"),
        loudness_path=str(tmp_path / "loudness.npy"),
        log_path=str(tmp_path / "log.txt"),
        result_path=str(tmp_path / "result.json"),
        device="cpu",
        model=AcousticSetup(name="tiny", revision="r", folder=str(folder), precision="fp16"),
        piece_seconds=piece,
        overlap_seconds=overlap,
    )


def noise(tmp_path: Path, seconds: float) -> Path:
    path = tmp_path / "lead.wav"
    rng = np.random.default_rng(0)
    sf.write(path, rng.normal(0, 0.1, int(seconds * 44100)).astype(np.float32), 44100)
    return path


def run(job: AcousticJob, tmp_path: Path) -> int:
    path = tmp_path / "job.json"
    path.write_text(job.model_dump_json(), encoding="utf-8")
    return worker.main([str(path)])


def test_the_worker_writes_one_row_of_log_probabilities_per_frame(tmp_path: Path) -> None:
    job = make_job(tmp_path, noise(tmp_path, 3.0))
    assert run(job, tmp_path) == 0
    result = AcousticResult.model_validate_json(Path(job.result_path).read_text())
    frames = np.load(job.emissions_path)
    samples = round(3.0 * SAMPLE_RATE)
    assert frames.shape == (frame_count(samples), len(VOCABULARY)) == (result.frames, 38)
    assert frames.dtype == np.float32
    assert np.allclose(np.exp(frames).sum(axis=1), 1.0, atol=1e-4)  # log-probabilities
    assert result.seconds_per_frame == STRIDE / SAMPLE_RATE
    assert result.vocabulary == list(VOCABULARY)
    assert (result.device, result.peak_vram_gib) == ("cpu", None)


def test_the_worker_writes_the_loudness_of_the_unnormalised_song_per_frame(
    tmp_path: Path,
) -> None:
    job = make_job(tmp_path, noise(tmp_path, 3.0))
    assert run(job, tmp_path) == 0
    loudness = np.load(job.loudness_path)
    assert loudness.shape == (frame_count(round(3.0 * SAMPLE_RATE)),)
    assert loudness.dtype == np.float32
    # noise of std 0.1, band-limited by the resampling from 44.1 to 16 kHz: about -24 dBFS
    assert -27.0 < loudness.mean() < -22.0


def test_a_backing_stem_is_added_to_the_lead_for_the_loudness_but_not_for_the_model(
    tmp_path: Path,
) -> None:
    quiet = tmp_path / "lead.wav"
    sf.write(quiet, np.zeros(3 * 44100, dtype=np.float32), 44100)
    backing = tmp_path / "backing.wav"
    rng = np.random.default_rng(1)
    sf.write(backing, rng.normal(0, 0.1, 2 * 44100).astype(np.float32), 44100)  # shorter
    alone = make_job(tmp_path, quiet)
    assert run(alone, tmp_path) == 0
    assert np.load(alone.loudness_path).max() < -90.0  # digital silence
    frames_alone = np.load(alone.emissions_path)
    both = make_job(tmp_path, quiet).model_copy(update={"backing": str(backing)})
    assert run(both, tmp_path) == 0
    loudness = np.load(both.loudness_path)
    assert loudness.shape == (frame_count(3 * SAMPLE_RATE),)  # as long as the longer one
    assert loudness[: frame_count(SAMPLE_RATE)].mean() > -30.0  # the backing sounds
    assert loudness[-20:].max() < -90.0  # and is padded with zeros
    assert np.array_equal(np.load(both.emissions_path), frames_alone)  # the model hears the lead


def hearing(tmp_path: Path, lead: Path, backing: Path, *, sum_backing: bool) -> AcousticJob:
    """A job that also hears the backing; its three extra files are in ``tmp_path``."""
    return make_job(tmp_path, lead).model_copy(
        update={
            "backing": str(backing),
            "sum_backing": sum_backing,
            "hear_backing": True,
            "backing_emissions_path": str(tmp_path / "backing-frames.npy"),
            "lead_loudness_path": str(tmp_path / "lead-loudness.npy"),
            "backing_loudness_path": str(tmp_path / "backing-loudness.npy"),
        }
    )


def test_hearing_the_backing_runs_the_model_again_on_the_backing_fitted_to_the_lead(
    tmp_path: Path,
) -> None:
    lead = tmp_path / "lead.wav"
    sf.write(lead, np.zeros(3 * 44100, dtype=np.float32), 44100)
    backing = tmp_path / "backing.wav"
    rng = np.random.default_rng(1)
    sf.write(backing, rng.normal(0, 0.1, 2 * 44100).astype(np.float32), 44100)  # shorter
    job = hearing(tmp_path, lead, backing, sum_backing=False)
    assert run(job, tmp_path) == 0
    frames = frame_count(3 * SAMPLE_RATE)
    heard = np.load(str(job.backing_emissions_path))
    assert heard.shape == np.load(job.emissions_path).shape == (frames, len(VOCABULARY))
    assert np.allclose(np.exp(heard).sum(axis=1), 1.0, atol=1e-4)
    assert not np.array_equal(heard, np.load(job.emissions_path))  # it heard other audio
    lead_loudness = np.load(str(job.lead_loudness_path))
    backing_loudness = np.load(str(job.backing_loudness_path))
    assert lead_loudness.shape == backing_loudness.shape == (frames,)
    assert lead_loudness.max() < -90.0  # the lead is digital silence
    assert backing_loudness[: frame_count(SAMPLE_RATE)].mean() > -30.0
    assert backing_loudness[-20:].max() < -90.0  # padded with zeros to the lead's length
    assert np.array_equal(np.load(job.loudness_path), lead_loudness)  # not summed
    log = Path(job.log_path).read_text()
    assert "hearing the backing vocals" in log


def test_a_longer_backing_is_trimmed_and_the_summed_loudness_file_stays_as_before(
    tmp_path: Path,
) -> None:
    lead = tmp_path / "lead.wav"
    sf.write(lead, np.zeros(2 * 44100, dtype=np.float32), 44100)
    backing = tmp_path / "backing.wav"
    rng = np.random.default_rng(2)
    sf.write(backing, rng.normal(0, 0.1, 3 * 44100).astype(np.float32), 44100)  # longer
    job = hearing(tmp_path, lead, backing, sum_backing=True)
    assert run(job, tmp_path) == 0
    frames = frame_count(2 * SAMPLE_RATE)
    assert np.load(str(job.backing_emissions_path)).shape[0] == frames
    assert np.load(str(job.backing_loudness_path)).shape == (frames,)
    assert np.load(job.loudness_path).shape == (frame_count(3 * SAMPLE_RATE),)  # as sum_waves gave


def test_without_hearing_the_backing_the_three_extra_files_are_not_written(
    tmp_path: Path,
) -> None:
    job = make_job(tmp_path, noise(tmp_path, 1.0))
    assert run(job, tmp_path) == 0
    assert sorted(p.name for p in tmp_path.glob("*.npy")) == ["frames.npy", "loudness.npy"]


def test_a_job_that_hears_the_backing_needs_the_backing_and_its_paths(tmp_path: Path) -> None:
    job = make_job(tmp_path, noise(tmp_path, 1.0))
    with pytest.raises(ValueError, match="needs the backing vocals"):
        AcousticJob.model_validate({**job.model_dump(), "hear_backing": True})


def test_the_log_names_each_step_and_each_piece(tmp_path: Path) -> None:
    job = make_job(tmp_path, noise(tmp_path, 3.0))
    run(job, tmp_path)
    log = Path(job.log_path).read_text()
    for step in (
        "decoding",
        "loading tiny on cpu",
        "4 pieces of 1 s",
        "piece 4 of 4 done",
        "finished in",
    ):
        assert step in log
    assert "alignment worker:" in log


def test_the_worker_tells_its_parent_after_each_piece(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = make_job(tmp_path, noise(tmp_path, 3.0))
    assert run(job, tmp_path) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("progress")]
    assert lines == ["progress 1 4", "progress 2 4", "progress 3 4", "progress 4 4"]


def test_one_piece_and_many_pieces_make_the_same_number_of_frames(tmp_path: Path) -> None:
    audio = noise(tmp_path, 2.5)
    many = make_job(tmp_path, audio)
    assert run(many, tmp_path) == 0
    split = np.load(many.emissions_path)
    one = many.model_copy(update={"piece_seconds": 60.0})
    assert run(one, tmp_path) == 0
    assert np.load(one.emissions_path).shape == split.shape


def test_the_vocabulary_is_read_in_the_order_of_the_ids(tmp_path: Path) -> None:
    folder = tmp_path / "m"
    folder.mkdir()
    (folder / "vocab.json").write_text(json.dumps({"b": 1, "a": 0}), encoding="utf-8")
    assert load_vocabulary(folder) == ["a", "b"]
    (folder / "vocab.json").write_text(json.dumps({"a": 0, "b": 2}), encoding="utf-8")
    with pytest.raises(ValueError, match="does not number"):
        load_vocabulary(folder)


def test_a_song_that_cannot_be_decoded_exits_with_one_and_leaves_evidence_in_the_log(
    tmp_path: Path,
) -> None:
    job = make_job(tmp_path, tmp_path / "missing.wav")
    assert_decode_failure_left_evidence(run(job, tmp_path), job)


def test_a_missing_backing_stem_is_a_failure_with_evidence_in_the_log(tmp_path: Path) -> None:
    job = make_job(tmp_path, noise(tmp_path, 1.0)).model_copy(
        update={"backing": str(tmp_path / "missing.flac")}
    )
    assert_decode_failure_left_evidence(run(job, tmp_path), job)
    assert not Path(job.loudness_path).exists()


def test_an_out_of_memory_error_exits_with_its_own_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(job: AcousticJob, log: worker.Logger) -> AcousticResult:
        raise torch.OutOfMemoryError("CUDA out of memory")

    monkeypatch.setattr(worker, "align", full)
    job = make_job(tmp_path, noise(tmp_path, 0.5))
    assert run(job, tmp_path) == EXIT_OUT_OF_MEMORY
    assert "out of memory" in Path(job.log_path).read_text()


def test_the_probe_prints_the_free_gpu_memory_as_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_probe_prints_free_vram(worker.main, monkeypatch, capsys)


def test_the_backing_is_normalised_on_its_own_and_heard_over_the_same_pieces(
    tmp_path: Path,
) -> None:
    rng = np.random.default_rng(3)
    voice = rng.normal(0, 0.1, 3 * 44100).astype(np.float32)
    lead = tmp_path / "lead.wav"
    sf.write(lead, voice, 44100, subtype="FLOAT")
    frames: list[np.ndarray] = []
    for scale in (1.0, 0.1):
        backing = tmp_path / f"backing-{scale}.wav"
        sf.write(backing, voice * scale, 44100, subtype="FLOAT")
        job = hearing(tmp_path, lead, backing, sum_backing=False)
        assert run(job, tmp_path) == 0
        frames.append(np.load(str(job.backing_emissions_path)))
        lead_frames = np.load(job.emissions_path)
    # the same audio as the lead gives the lead's frames, a quieter copy too (own normalisation)
    assert np.allclose(frames[0], lead_frames, atol=1e-4)
    assert np.allclose(frames[1], lead_frames, atol=1e-4)
