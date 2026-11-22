"""Stage 1: Mel-Band models, instrumental targets, ensembles and the karaoke input (tiny models)."""

from pathlib import Path

import numpy as np
import pytest
import torch

from fakes.audio import read_audio
from fakes.roformer import CHUNK, TINY_MEL_CONFIG, write_tiny_model
from vocatron.core.separation.file import stem_path
from vocatron.core.separation.job import SeparationJob
from vocatron.engines.audio import decode
from vocatron.engines.separation import eval_worker, worker
from vocatron.engines.separation.inference import build_model, load_model
from vocatron.engines.separation.roformer.bs_roformer import BSRoformer
from vocatron.engines.separation.roformer.config import MelModelConfig, parse_config
from vocatron.engines.separation.roformer.mel_band_roformer import MelBandRoformer
from vocatron.lab.separation.evaluation import EvalJob, EvalPair, Timing

from .test_roformer import write_wav


def test_num_bands_makes_the_configuration_a_mel_band_configuration() -> None:
    config = parse_config(TINY_MEL_CONFIG)
    assert isinstance(config, MelModelConfig)
    assert (config.num_bands, config.num_stems, config.stft_normalized) == (4, 2, True)
    assert isinstance(build_model(config), MelBandRoformer)
    assert isinstance(build_model(parse_config("model:\n  dim: 8\n  depth: 1\n")), BSRoformer)


def test_a_mel_band_model_loads_strictly_and_returns_every_stem(tmp_path: Path) -> None:
    setup = write_tiny_model(tmp_path, "mel", seed=3, mel=True)
    model = load_model(setup, "cpu")
    with torch.inference_mode():
        out = model(torch.randn(2, 2, CHUNK))
    assert out.shape == (2, 2, 2, CHUNK)  # batch, stems, channels, samples


def test_a_mel_band_model_with_one_stem_still_has_the_stem_dimension() -> None:
    config = parse_config(TINY_MEL_CONFIG.replace("num_stems: 2", "num_stems: 1"))
    with torch.inference_mode():
        out = build_model(config).eval()(torch.randn(1, 2, CHUNK))
    assert out.shape == (1, 1, 2, CHUNK)


def test_a_mel_band_checkpoint_with_a_missing_weight_is_refused(tmp_path: Path) -> None:
    setup = write_tiny_model(tmp_path, "mel", seed=3, mel=True)
    weights = torch.load(setup.checkpoint, weights_only=True)
    del weights[next(iter(weights))]
    torch.save(weights, setup.checkpoint)
    with pytest.raises(RuntimeError, match="Missing key"):
        load_model(setup, "cpu")


def job_with(
    tmp_path: Path, vocals: tuple[object, ...], *, karaoke_input: str = "vocals"
) -> SeparationJob:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return SeparationJob.model_validate(
        {
            "audio": str(write_wav(tmp_path / "song.wav", 0.5)),
            "out_folder": str(work),
            "log_path": str(work / "log.txt"),
            "result_path": str(work / "result.json"),
            "device": "cpu",
            "keep_backing": True,
            "vocals_models": vocals,
            "karaoke_model": write_tiny_model(tmp_path / "models", "karaoke", seed=2),
            "karaoke_input": karaoke_input,
        }
    )


def run(job: SeparationJob, tmp_path: Path) -> dict[str, np.ndarray]:
    path = tmp_path / "job.json"
    path.write_text(job.model_dump_json(), encoding="utf-8")
    assert worker.main([str(path)]) == 0
    return {
        name: read_audio(Path(job.out_folder) / stem_path(name))
        for name in ("lead", "backing", "instrumental", "karaoke")
    }


def test_an_instrumental_model_gives_the_instrumental_and_the_vocals_are_the_rest(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    model = write_tiny_model(models, "inst", seed=1, mel=True, target="instrumental")
    stems = run(job_with(tmp_path, (model.model_dump(),)), tmp_path)
    mix = decode(str(tmp_path / "song.wav"))
    total = stems["lead"] + stems["backing"] + stems["instrumental"]
    assert float(np.max(np.abs(total - mix))) < 1e-4
    estimate = load_model(model, "cpu")(torch.from_numpy(mix).unsqueeze(0))[0, 0].detach().numpy()
    assert stems["instrumental"].shape == estimate.shape


def test_two_vocals_models_are_averaged_on_the_waveform(tmp_path: Path) -> None:
    models = tmp_path / "models"
    first = write_tiny_model(models, "one", seed=1)
    second = write_tiny_model(models, "two", seed=5, mel=True, target="instrumental")
    both = run(job_with(tmp_path, (first.model_dump(), second.model_dump())), tmp_path)
    mix = decode(str(tmp_path / "song.wav"))
    total = both["lead"] + both["backing"] + both["instrumental"]
    assert float(np.max(np.abs(total - mix))) < 1e-4
    log = (tmp_path / "work" / "log.txt").read_text()
    assert "loading one on cpu" in log
    assert "loading two on cpu" in log
    assert "loading karaoke on cpu" in log


def test_the_karaoke_model_can_get_the_whole_song_instead_of_the_vocals(tmp_path: Path) -> None:
    model = write_tiny_model(tmp_path / "models", "voc", seed=1)
    from_vocals = run(job_with(tmp_path, (model.model_dump(),)), tmp_path)
    from_mix = run(job_with(tmp_path, (model.model_dump(),), karaoke_input="mix"), tmp_path)
    assert np.allclose(from_vocals["instrumental"], from_mix["instrumental"])
    assert not np.allclose(from_vocals["lead"], from_mix["lead"])
    mix = decode(str(tmp_path / "song.wav"))
    # the karaoke track is the song minus the lead vocals, whichever the input was
    assert float(np.max(np.abs(from_mix["karaoke"] + from_mix["lead"] - mix))) < 1e-4


def test_the_evaluation_worker_separates_what_is_missing_and_logs_one_timing_per_file(
    tmp_path: Path,
) -> None:
    model = write_tiny_model(tmp_path / "models", "voc", seed=1, mel=True, target="instrumental")
    first, second = write_wav(tmp_path / "a.wav", 0.3), write_wav(tmp_path / "b.wav", 0.3)
    done = tmp_path / "out" / "b.wav"
    done.parent.mkdir()
    done.write_bytes(b"already there")
    job = EvalJob(
        log_path=str(tmp_path / "log.txt"),
        result_path=str(tmp_path / "result.json"),
        device="cpu",
        model=model,
        pairs=(
            EvalPair(name="a", audio=str(first), output=str(tmp_path / "out" / "a.wav")),
            EvalPair(name="b", audio=str(second), output=str(done)),
        ),
        timings_path=str(tmp_path / "timings.jsonl"),
    )
    path = tmp_path / "job.json"
    path.write_text(job.model_dump_json(), encoding="utf-8")
    assert eval_worker.main([str(path)]) == 0
    (line,) = (tmp_path / "timings.jsonl").read_text().splitlines()
    timing = Timing.model_validate_json(line)
    assert timing.name == "a"
    assert timing.audio_seconds == pytest.approx(0.3, abs=0.01)
    estimate = read_audio(tmp_path / "out" / "a.wav")
    assert estimate.shape == decode(str(first)).shape
    assert done.read_bytes() == b"already there"
    log = (tmp_path / "log.txt").read_text()
    assert "1 of 2 files to separate" in log


def test_a_mel_band_model_refuses_audio_with_the_wrong_number_of_channels() -> None:
    model = build_model(parse_config(TINY_MEL_CONFIG)).eval()
    with pytest.raises(ValueError, match="takes 2 channels"):
        model(torch.randn(1, 1, CHUNK))


def test_a_mel_band_model_with_skip_connections_runs() -> None:
    text = TINY_MEL_CONFIG.replace("  depth: 1\n", "  depth: 2\n  skip_connection: true\n")
    with torch.inference_mode():
        out = build_model(parse_config(text)).eval()(torch.randn(1, 2, CHUNK))
    assert out.shape == (1, 2, 2, CHUNK)


def test_the_evaluation_worker_has_nothing_to_do_when_every_output_exists(tmp_path: Path) -> None:
    model = write_tiny_model(tmp_path / "models", "voc", seed=1)
    done = tmp_path / "a.wav"
    done.write_bytes(b"x")
    job = EvalJob(
        log_path=str(tmp_path / "log.txt"),
        result_path=str(tmp_path / "result.json"),
        device="cpu",
        model=model,
        pairs=(EvalPair(name="a", audio=str(tmp_path / "none.wav"), output=str(done)),),
        timings_path=str(tmp_path / "timings.jsonl"),
    )
    path = tmp_path / "job.json"
    path.write_text(job.model_dump_json(), encoding="utf-8")
    assert eval_worker.main([str(path)]) == 0
    assert not (tmp_path / "timings.jsonl").exists()
