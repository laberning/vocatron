"""Stage 2: the real separation models on the GPU, against the stems of the trial of ADR-0002.

The reference stems of "Denkmal" lie in the local corpus (``.corpus/reference/denkmal``, never in
git), the whole song in ``.corpus/songs`` in any audio format. A missing corpus file fails the
test (``realworld.corpus_path``). The tests report numbers only. GPU safety as in AGENTS.md: a
timeout on every test, PyTorch capped at 75 % of the GPU memory, half precision, and a log synced
to disk after every line.
"""

import os
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import torch

from fakes.audio import read_audio, sdr_db
from fakes.files import InMemoryFileStore
from fakes.lyrics import FakeLanguageDetector, FakeLyricsSource
from fakes.measure import FixedMeasurer
from fakes.pack import FakePacker
from fakes.raster import FakeRasteriser
from fakes.render import FakeMp3Encoder, FakeRenderer
from realworld import MODELS, corpus_path, corpus_song
from vocatron.core.mel import mel_filter_bank
from vocatron.core.models import KARAOKE_MODEL, KARAOKE_MODELS, VOCALS_MODELS, find_model
from vocatron.core.separation.file import STEM_NAMES, SeparationFile, stem_path
from vocatron.core.separation.job import ModelSetup
from vocatron.core.separation.rules import SAMPLE_RATE, Audio, combine_estimates, peak
from vocatron.core.stage_file import make_fingerprint
from vocatron.engines.alignment.process import ProcessAcousticModel
from vocatron.engines.audio import FfmpegAudioReader
from vocatron.engines.clock import SystemClock
from vocatron.engines.downloader import Urllib3Downloader
from vocatron.engines.files import FileLog, LocalFileStore
from vocatron.engines.resources import PackageResources
from vocatron.engines.separation.inference import load_model, separate_target
from vocatron.engines.separation.process import ProcessSeparator
from vocatron.engines.tags import TinyTagReader
from vocatron.lab.separation.listening import plan_passages
from vocatron.stages.config import Config
from vocatron.stages.separation import SeparationStage, model_setup
from vocatron.stages.songs import discover
from vocatron.stages.stage import LOG_FILE, Engines, StageContext

CLONE = Path(__file__).resolve().parents[2]
SONG = "Wir sind Helden - Denkmal"
MIN_SDR = 35.0  # dB, the acceptance bar of the story
GPU_SHARE = 0.75
TIMEOUT = 900  # seconds per test; the whole song takes about two minutes per model

pytestmark = [pytest.mark.gpu, pytest.mark.timeout(TIMEOUT)]
needs_gpu = pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA GPU")


@pytest.fixture(scope="module")
def log() -> Iterator[FileLog]:
    """A log that survives a crash of the machine: every line is synced to disk."""
    folder = CLONE / ".cache" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    sink = FileLog(folder / "stage2-separation.log")
    sink.write(f"{time.strftime('%H:%M:%S')} stage 2 separation tests start (pid {os.getpid()})")
    yield sink
    sink.close()


@pytest.fixture(autouse=True)
def gpu_cap(log: FileLog) -> None:
    """Cap PyTorch at 75 % of the GPU memory for the tests that run in this process."""
    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(GPU_SHARE)
        log.write(f"GPU capped at {GPU_SHARE:.0%}")


def setup_of(name: str) -> ModelSetup:
    return model_setup(find_model(name), MODELS)


def reference_wav(name: str) -> Audio:
    """Read a WAV file of the trial stems in ``.corpus/reference/denkmal``."""
    path = corpus_path("reference", "denkmal", name)
    assert sf.info(path).samplerate == SAMPLE_RATE
    return read_audio(path)


@pytest.mark.parametrize("name", [*VOCALS_MODELS, *KARAOKE_MODELS])
def test_every_checkpoint_loads_strictly(name: str, log: FileLog) -> None:
    setup = setup_of(name)
    model = load_model(setup, "cpu")
    count = sum(p.numel() for p in model.parameters())
    log.write(f"{name}: strict load ok, {count // 10**6} M parameters")
    assert count > 10**7


def run_on_gpu(name: str, audio: Audio, log: FileLog) -> Audio:
    setup = setup_of(name)
    model = load_model(setup, "cuda")
    started = time.monotonic()
    target = separate_target(model, audio, setup, "cuda", log.write)
    peak_gib = torch.cuda.max_memory_allocated() / 2**30
    log.write(f"{name}: {time.monotonic() - started:.1f} s, peak {peak_gib:.2f} GiB")
    assert (
        torch.cuda.max_memory_allocated()
        < GPU_SHARE * torch.cuda.get_device_properties(0).total_memory
    )
    return target


@needs_gpu
def test_the_vocals_model_reproduces_the_trial_stems(log: FileLog) -> None:
    mix = reference_wav("input.wav")
    vocals = run_on_gpu("bs-roformer-ep317", mix, log)
    instrumental = mix - vocals
    vocals_sdr = sdr_db(reference_wav("ep317_vocals.wav"), vocals)
    instrumental_sdr = sdr_db(reference_wav("ep317_instrumental.wav"), instrumental)
    log.write(f"ep317 vs trial: vocals {vocals_sdr:.1f} dB, instrumental {instrumental_sdr:.1f} dB")
    assert vocals_sdr >= MIN_SDR
    assert instrumental_sdr >= MIN_SDR


@needs_gpu
@pytest.mark.parametrize("name", [m for m in VOCALS_MODELS if m != "bs-roformer-ep317"])
def test_a_candidate_model_separates_an_excerpt(name: str, log: FileLog) -> None:
    (window,) = plan_passages(reference_wav("ep317_vocals.wav"), count=1)  # voice is dense
    first = round(window.start * SAMPLE_RATE)
    mix = reference_wav("input.wav")[:, first : first + round(window.seconds * SAMPLE_RATE)]
    estimate = run_on_gpu(name, mix, log)
    vocals, _ = combine_estimates(mix, [(estimate, setup_of(name).target)])
    assert vocals.shape == mix.shape
    assert np.isfinite(vocals).all()
    ratio = float(np.sqrt(np.mean(vocals**2) / np.mean(mix**2)))
    log.write(
        f"{name}: vocals are {ratio:.2f} of the mix level on a {window.seconds:.0f} s excerpt"
    )
    assert 0.1 < ratio < 1.0  # a real separation: neither silence nor a copy of the mix


@needs_gpu
@pytest.mark.parametrize("name", [m for m in KARAOKE_MODELS if m != KARAOKE_MODEL])
def test_a_candidate_karaoke_model_separates_an_excerpt(name: str, log: FileLog) -> None:
    vocals = reference_wav("anvuew_input.wav")
    (window,) = plan_passages(vocals, count=1)  # where the voice is dense
    first = round(window.start * SAMPLE_RATE)
    excerpt = vocals[:, first : first + round(window.seconds * SAMPLE_RATE)]
    lead = run_on_gpu(name, excerpt, log)
    assert lead.shape == excerpt.shape
    assert np.isfinite(lead).all()
    ratio = float(np.sqrt(np.mean(lead**2) / np.mean(excerpt**2)))
    log.write(
        f"{name}: lead is {ratio:.2f} of the vocals level on a {window.seconds:.0f} s excerpt"
    )
    assert 0.1 < ratio <= 1.1  # a real split: neither silence nor noise added


@needs_gpu
@pytest.mark.parametrize("size", [(44100, 2048, 60), (44100, 4096, 512), (44100, 2048, 256)])
def test_the_mel_filter_bank_equals_torchaudios_slaney_filters(size: tuple[int, int, int]) -> None:
    # The cu130 build of torchaudio loads only next to the CUDA build of PyTorch, so it is
    # imported here, after the GPU check, and a machine without a GPU still collects the file.
    from torchaudio.functional import melscale_fbanks  # noqa: PLC0415  # see the comment above

    rate, n_fft, n_mels = size
    expected = melscale_fbanks(
        n_fft // 2 + 1, 0.0, rate / 2, n_mels, rate, norm="slaney", mel_scale="slaney"
    ).numpy()
    ours = mel_filter_bank(rate, n_fft, n_mels)
    # float32 rounding: equal to 1e-4 of the largest weight
    assert float(np.abs(ours - expected.T).max()) <= 1e-4 * float(expected.max())


@needs_gpu
def test_the_karaoke_model_reproduces_the_trial_stems(log: FileLog) -> None:
    vocals = reference_wav("anvuew_input.wav")
    lead = run_on_gpu(KARAOKE_MODEL, vocals, log)
    backing = vocals - lead
    lead_sdr = sdr_db(reference_wav("anvuew_lead.wav"), lead)
    backing_sdr = sdr_db(reference_wav("anvuew_backing.wav"), backing)
    log.write(f"anvuew vs trial: lead {lead_sdr:.1f} dB, backing {backing_sdr:.1f} dB")
    assert lead_sdr >= MIN_SDR
    assert backing_sdr >= MIN_SDR


@needs_gpu
def test_the_stage_separates_a_whole_song_through_the_worker_process(
    tmp_path: Path, log: FileLog
) -> None:
    config = Config.model_validate({"output": {"folder": str(tmp_path / "karaoke")}})
    engines = Engines(
        clock=SystemClock(),
        tags=TinyTagReader(),
        store=LocalFileStore(),
        downloader=Urllib3Downloader(),
        lyrics=FakeLyricsSource(),  # the stage does not touch the lyrics
        language=FakeLanguageDetector(),
        separator=ProcessSeparator(),
        acoustic=ProcessAcousticModel(),
        measurer=FixedMeasurer(),  # the stage does not draw
        rasteriser=FakeRasteriser(),
        renderer=FakeRenderer(InMemoryFileStore()),
        mp3=FakeMp3Encoder(InMemoryFileStore()),
        packer=FakePacker(InMemoryFileStore()),
        resources=PackageResources(),
        audio=FfmpegAudioReader(),
    )
    (song,) = discover(corpus_song(SONG), config, engines)
    engines.store.make_folder(song.work_dir)
    song_log = engines.store.open_log(song.work_dir / LOG_FILE)

    def to_log(message: str) -> None:
        song_log.write(message)

    context = StageContext(song, engines, to_log, MODELS.folder)
    stage = SeparationStage()
    fingerprint = make_fingerprint({}, stage.declared_settings(context, config), stage.version)

    started = time.monotonic()
    file = stage.execute(context, config, fingerprint)
    seconds = time.monotonic() - started
    song_log.close()
    log.write(f"stage on a whole song: {seconds:.1f} s")

    assert isinstance(file, SeparationFile)
    assert file.device == "cuda"
    assert file.peak_vram_gib is not None
    assert file.peak_vram_gib < GPU_SHARE * torch.cuda.get_device_properties(0).total_memory / 2**30
    assert song.tags is not None
    assert song.tags.duration is not None
    stems = {name: read_audio(song.work_dir / stem_path(name)) for name in STEM_NAMES}
    for name, audio in stems.items():
        info = sf.info(song.work_dir / stem_path(name))
        assert (info.subtype, info.samplerate, info.channels) == ("PCM_24", SAMPLE_RATE, 2), name
        assert audio.shape[1] == file.samples, name
        assert peak(audio) <= 1.0, name  # no clipping
        level = 20 * np.log10(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
        assert -50 < level < -6, f"{name}: {level:.1f} dBFS"  # a sane level
    assert abs(file.samples / SAMPLE_RATE - song.tags.duration) < 0.5
    worker_log = (song.work_dir / LOG_FILE).read_text(encoding="utf-8")
    assert "GPU memory capped at 75%" in worker_log
    assert "finished in" in worker_log
    gains = file.gains.model_dump()
    log.write(f"gains {gains}, peak {peak(stems['instrumental']):.3f}")
    assert all(0 < gain <= 1 for gain in gains.values())
