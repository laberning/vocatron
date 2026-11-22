"""Stage 1: the copied Roformer code, a tiny model of it on the CPU, and the worker around it.

The models are tiny and randomly initialised; the real checkpoints are tested in stage 2.
"""

import json
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
import torch

from fakes.audio import read_audio
from fakes.roformer import CHUNK, TINY_CONFIG, write_tiny_model
from fakes.workers import assert_decode_failure_left_evidence, assert_probe_prints_free_vram
from vocatron.core.separation.file import stem_path
from vocatron.core.separation.job import SeparationJob, SeparationResult
from vocatron.core.separation.rules import EXIT_OUT_OF_MEMORY, SAMPLE_RATE, Audio, peak
from vocatron.core.worker import parse_progress
from vocatron.engines.audio import DecodeError, decode
from vocatron.engines.separation import worker
from vocatron.engines.separation.inference import build_model, load_model, separate_target
from vocatron.engines.separation.roformer.config import ModelConfig, parse_config


def test_the_config_reads_tuples_and_drops_the_training_only_keys() -> None:
    config = parse_config(TINY_CONFIG)
    assert isinstance(config, ModelConfig)
    assert config.freqs_per_bands == (11, 11, 11)
    assert (config.dim, config.depth, config.heads, config.stereo) == (8, 1, 2, True)


def test_keys_a_configuration_leaves_out_have_the_upstream_defaults() -> None:
    config = parse_config("model:\n  dim: 8\n  depth: 1\n")
    assert isinstance(config, ModelConfig)
    assert (config.mlp_expansion_factor, config.heads, config.dim_head) == (4, 8, 64)
    assert (config.stft_n_fft, config.stft_hop_length, config.stereo) == (2048, 512, False)
    assert sum(config.freqs_per_bands) == 1025


def test_a_key_the_model_does_not_know_is_an_error() -> None:
    with pytest.raises(ValueError, match="mystery"):
        parse_config(TINY_CONFIG.replace("  skip_connection: false", "  mystery: 1"))


def test_linear_attention_is_refused() -> None:
    text = TINY_CONFIG.replace("linear_transformer_depth: 0", "linear_transformer_depth: 1")
    with pytest.raises(ValueError, match="linear_transformer_depth"):
        parse_config(text)


@pytest.mark.parametrize("text", ["audio: {}\n", "- 1\n- 2\n", "model: 3\n"])
def test_a_config_without_a_model_section_is_an_error(text: str) -> None:
    with pytest.raises(ValueError, match="no 'model' section"):
        parse_config(text)


def test_the_model_returns_the_stems_in_the_shape_of_its_input() -> None:
    model = build_model(parse_config(TINY_CONFIG)).eval()
    audio = torch.randn(3, 2, CHUNK)
    with torch.inference_mode():
        out = model(audio)
    assert out.shape == (3, 1, 2, CHUNK)
    assert torch.isfinite(out).all()


def test_the_model_refuses_the_wrong_number_of_channels() -> None:
    model = build_model(parse_config(TINY_CONFIG)).eval()
    with pytest.raises(ValueError, match="takes 2 channels, got 1"):
        model(torch.randn(1, 1, CHUNK))


def test_bands_that_do_not_add_up_to_the_frequencies_are_refused() -> None:
    bad = parse_config(TINY_CONFIG).model_dump() | {"freqs_per_bands": (11, 11)}
    with pytest.raises(ValueError, match="must add up to 33 frequencies"):
        build_model(ModelConfig.model_validate(bad))


def test_the_skip_connection_variant_runs() -> None:
    config = parse_config(TINY_CONFIG).model_dump() | {"skip_connection": True, "depth": 2}
    model = build_model(ModelConfig.model_validate(config)).eval()
    assert model(torch.randn(1, 2, CHUNK)).shape == (1, 1, 2, CHUNK)


def test_a_checkpoint_loads_strictly(tmp_path: Path) -> None:
    setup = write_tiny_model(tmp_path, "tiny", seed=1)
    model = load_model(setup, "cpu")
    assert not model.training
    reference = build_model(parse_config(TINY_CONFIG)).eval()
    reference.load_state_dict(torch.load(setup.checkpoint, weights_only=True), strict=True)
    audio = torch.randn(1, 2, CHUNK)
    with torch.inference_mode():
        assert torch.equal(model(audio), reference(audio))


def test_a_checkpoint_with_missing_or_extra_weights_is_refused(tmp_path: Path) -> None:
    setup = write_tiny_model(tmp_path, "tiny", seed=1)
    weights = torch.load(setup.checkpoint, weights_only=True)
    del weights["final_norm.gamma"]
    torch.save(weights, setup.checkpoint)
    with pytest.raises(RuntimeError, match="Missing key"):
        load_model(setup, "cpu")
    weights["final_norm.gamma"] = torch.ones(8)
    weights["stray"] = torch.ones(1)
    torch.save(weights, setup.checkpoint)
    with pytest.raises(RuntimeError, match="Unexpected key"):
        load_model(setup, "cpu")


def test_a_checkpoint_may_hold_its_weights_under_state_dict(tmp_path: Path) -> None:
    setup = write_tiny_model(tmp_path, "tiny", seed=1)
    weights = torch.load(setup.checkpoint, weights_only=True)
    torch.save({"state_dict": weights}, setup.checkpoint)
    load_model(setup, "cpu")


def test_a_whole_song_goes_through_the_model_chunk_by_chunk(tmp_path: Path) -> None:
    setup = write_tiny_model(tmp_path, "tiny", seed=1)
    model = load_model(setup, "cpu")
    audio = (np.random.default_rng(0).uniform(-0.5, 0.5, (2, CHUNK * 3 + 100))).astype(np.float32)
    lines: list[str] = []
    target = separate_target(model, audio, setup, "cpu", lines.append)
    assert target.shape == audio.shape
    assert np.isfinite(target).all()
    assert lines[0].startswith("tiny: chunk 1/") and lines[-1].startswith("tiny: chunk ")


def test_the_same_audio_gives_the_same_stem_twice(tmp_path: Path) -> None:
    setup = write_tiny_model(tmp_path, "tiny", seed=1)
    model = load_model(setup, "cpu")
    audio = (np.random.default_rng(2).uniform(-0.5, 0.5, (2, CHUNK + 500))).astype(np.float32)
    first = separate_target(model, audio, setup, "cpu", lambda line: None)
    second = separate_target(model, audio, setup, "cpu", lambda line: None)
    assert np.array_equal(first, second)


def write_wav(path: Path, seconds: float, rate: int = 8000, channels: int = 1) -> Path:
    rng = np.random.default_rng(5)
    samples = (rng.uniform(-0.4, 0.4, int(seconds * rate) * channels) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(samples.tobytes())
    return path


def test_decoding_gives_44_1_khz_stereo_float(tmp_path: Path) -> None:
    audio = decode(str(write_wav(tmp_path / "a.wav", 0.5)))
    assert audio.dtype == np.float32
    assert audio.shape[0] == 2
    assert abs(audio.shape[1] - SAMPLE_RATE // 2) <= 2
    assert np.array_equal(audio[0], audio[1])  # mono becomes two equal channels
    assert 0.2 < peak(audio) < 0.5


def test_decoding_a_missing_file_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(DecodeError, match="could not decode"):
        decode(str(tmp_path / "missing.wav"))


def test_decoding_a_file_without_audio_is_a_clear_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty.wav"
    with wave.open(str(empty), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(8000)
    with pytest.raises(DecodeError, match="holds no audio"):
        decode(str(empty))


def test_a_missing_ffmpeg_is_a_clear_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def broken(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(subprocess, "run", broken)
    with pytest.raises(DecodeError, match="cannot run ffmpeg"):
        decode(str(tmp_path / "a.wav"))


def make_job(tmp_path: Path, audio: Path, *, keep_backing: bool = True) -> SeparationJob:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    models = tmp_path / "models"
    return SeparationJob(
        audio=str(audio),
        out_folder=str(work),
        log_path=str(work / "log.txt"),
        result_path=str(work / "result.json"),
        device="cpu",
        keep_backing=keep_backing,
        vocals_models=(write_tiny_model(models, "vocals", seed=1),),
        karaoke_model=write_tiny_model(models, "karaoke", seed=2),
    )


def run_worker(job: SeparationJob, tmp_path: Path) -> int:
    path = tmp_path / "job.json"
    path.write_text(job.model_dump_json(), encoding="utf-8")
    return worker.main([str(path)])


def test_the_worker_writes_four_stems_that_add_up_to_the_song(tmp_path: Path) -> None:
    song = write_wav(tmp_path / "song.wav", 0.6)
    job = make_job(tmp_path, song)
    assert run_worker(job, tmp_path) == 0
    result = SeparationResult.model_validate_json(Path(job.result_path).read_text())
    assert result.device == "cpu"
    assert result.peak_vram_gib is None
    stems: dict[str, Audio] = {
        name: read_audio(Path(job.out_folder) / stem_path(name))
        for name in ("lead", "backing", "instrumental", "karaoke")
    }
    assert {s.shape[1] for s in stems.values()} == {result.samples}
    mix = decode(str(song))
    assert result.samples == mix.shape[1]
    # lead + backing is the vocals, and vocals + instrumental is the mix (to 24-bit precision)
    total = stems["lead"] + stems["backing"] + stems["instrumental"]
    assert float(np.max(np.abs(total - mix))) < 1e-4
    assert np.allclose(stems["karaoke"], stems["instrumental"] + stems["backing"], atol=1e-5)
    log = Path(job.log_path).read_text()
    for step in ("decoding", "loading vocals on cpu", "loading karaoke on cpu", "writing stems"):
        assert step in log


def test_the_worker_tells_its_parent_how_far_it_is_over_both_models(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = make_job(tmp_path, write_wav(tmp_path / "song.wav", 0.6))
    assert run_worker(job, tmp_path) == 0
    heard = [
        fraction
        for line in capsys.readouterr().out.splitlines()
        if (fraction := parse_progress(line)) is not None
    ]
    assert heard == sorted(heard)  # it only moves forward
    assert heard[-1] == 1.0
    assert 0.5 in heard  # the first model is half of the work


def test_without_backing_the_worker_makes_the_karaoke_from_the_instrumental(tmp_path: Path) -> None:
    job = make_job(tmp_path, write_wav(tmp_path / "song.wav", 0.4), keep_backing=False)
    assert run_worker(job, tmp_path) == 0
    karaoke = read_audio(Path(job.out_folder) / stem_path("karaoke"))
    instrumental = read_audio(Path(job.out_folder) / stem_path("instrumental"))
    assert np.allclose(karaoke, instrumental, atol=1e-6)


def test_a_song_that_cannot_be_decoded_exits_with_one_and_leaves_evidence_in_the_log(
    tmp_path: Path,
) -> None:
    job = make_job(tmp_path, tmp_path / "missing.wav")
    assert_decode_failure_left_evidence(run_worker(job, tmp_path), job)


def test_an_out_of_memory_error_exits_with_its_own_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(job: SeparationJob, log: worker.Logger) -> SeparationResult:
        raise torch.OutOfMemoryError("CUDA out of memory")

    monkeypatch.setattr(worker, "separate", full)
    job = make_job(tmp_path, write_wav(tmp_path / "song.wav", 0.2))
    assert run_worker(job, tmp_path) == EXIT_OUT_OF_MEMORY
    assert "out of memory" in Path(job.log_path).read_text()


def test_the_probe_prints_the_free_gpu_memory_as_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_probe_prints_free_vram(worker.main, monkeypatch, capsys)


def test_the_probe_says_null_without_cuda(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert worker.main(["--probe"]) == 0
    assert json.loads(capsys.readouterr().out) == {"free_vram": None}
