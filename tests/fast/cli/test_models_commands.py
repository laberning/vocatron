"""Stage 1: ``models``, ``models download``, ``doctor`` and ``make --offline`` on fakes."""

from pathlib import Path

import pytest
from syrupy.assertion import SnapshotAssertion

from fakes.models import returning, tiny_spec
from fakes.songs import FakeWorld
from fakes.stages import NeedsModelStage
from fakes.streams import CLONE, Streams
from fakes.system import GOOD_ENCODERS, GOOD_FFMPEG
from vocatron.cli.commands import run_doctor, run_make, run_models, run_models_download
from vocatron.core.models import DEFAULT_SET, MODELS, ModelSpec, find_model, language_models
from vocatron.core.system import TorchInfo
from vocatron.stages import batch, models
from vocatron.stages.batch import Options
from vocatron.stages.probe import ProbeStage

MODELS_DIR = CLONE / ".cache" / "models"
MODELS_BY_NAME = [spec.name for spec in MODELS]
MUSIC = Path("/music")


def test_models_table_is_golden_when_nothing_is_downloaded(
    world: FakeWorld, snapshot: SnapshotAssertion
) -> None:
    streams = Streams(world)
    assert run_models(config_file=None, edges=streams.edges) == 0
    assert streams.out.getvalue() == snapshot


def test_models_table_shows_every_state(world: FakeWorld) -> None:
    for file in find_model("bs-roformer-karaoke").files:
        world.store.add(MODELS_DIR / "bs-roformer-karaoke" / file.path, b"x" * file.size)
    world.store.add(
        MODELS_DIR / "bs-roformer-ep317" / "model_bs_roformer_ep_317_sdr_12.9755.yaml", b"short"
    )
    world.store.add(MODELS_DIR / "wav2vec2-de" / "pytorch_model.bin.part", b"cut")
    streams = Streams(world)
    run_models(config_file=None, edges=streams.edges)
    rows = {
        line.split()[0]: line for line in streams.out.getvalue().splitlines() if line[:1].isalpha()
    }
    assert "checksum mismatch" in rows["bs-roformer-ep317"]
    assert "checksum mismatch" in rows["bs-roformer-karaoke"]  # right size, fake bytes
    assert "partial" in rows["wav2vec2-de"]
    assert "missing" in rows["whisper-turbo"]


def test_models_lists_every_registry_model_with_its_licence(world: FakeWorld) -> None:
    streams = Streams(world)
    run_models(config_file=None, edges=streams.edges)
    out = streams.out.getvalue()
    for spec in MODELS:
        assert spec.name in out
        assert spec.licence in out
    assert str(MODELS_DIR) in out


def test_models_reports_a_broken_configuration(world: FakeWorld) -> None:
    world.store.add(Path("/work/vocatron.yaml"), b"models:\n  folder: 3\n")
    streams = Streams(world)
    assert run_models(config_file=None, edges=streams.edges) == 2
    assert "/work/vocatron.yaml:2:3: models.folder" in streams.err.getvalue()


def test_the_model_folder_can_be_moved_in_the_configuration(world: FakeWorld) -> None:
    world.store.add(Path("/work/vocatron.yaml"), b"models:\n  folder: stuff\n")
    streams = Streams(world)
    assert run_models(config_file=None, edges=streams.edges) == 0
    assert "Model folder: /work/stuff" in streams.out.getvalue()


@pytest.fixture
def tiny(world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = tiny_spec("bs-roformer-ep317", {"a.bin": b"a" * 2_000_000, "b.json": b"{}"}, "GPL-3.0")
    world.downloader.serve(spec, {"a.bin": b"a" * 2_000_000, "b.json": b"{}"})
    monkeypatch.setattr("vocatron.cli.commands.find_model", returning(spec))


def test_download_fetches_the_default_set_and_prints_the_licence(
    world: FakeWorld, tiny: None, snapshot: SnapshotAssertion
) -> None:
    streams = Streams(world)
    assert run_models_download([], config_file=None, edges=streams.edges) == 0
    assert streams.out.getvalue() == snapshot
    assert len(DEFAULT_SET) == 3


def test_download_says_when_a_model_is_already_there(world: FakeWorld, tiny: None) -> None:
    run_models_download(["bs-roformer-ep317"], config_file=None, edges=Streams(world).edges)
    streams = Streams(world)
    assert run_models_download(["bs-roformer-ep317"], config_file=None, edges=streams.edges) == 0
    assert streams.out.getvalue() == "bs-roformer-ep317: already present and verified\n"


def test_download_reports_a_broken_configuration(world: FakeWorld) -> None:
    world.store.add(Path("/work/vocatron.yaml"), b"models:\n  folder: 3\n")
    streams = Streams(world)
    assert run_models_download([], config_file=None, edges=streams.edges) == 2
    assert "/work/vocatron.yaml:2:3: models.folder" in streams.err.getvalue()
    assert world.downloader.calls == []


def test_download_of_an_unknown_name_is_a_usage_error(world: FakeWorld) -> None:
    streams = Streams(world)
    assert run_models_download(["nope"], config_file=None, edges=streams.edges) == 2
    assert "unknown model 'nope'" in streams.err.getvalue()
    assert world.downloader.calls == []


def test_a_failing_download_exits_with_one_and_says_why(world: FakeWorld, tiny: None) -> None:
    world.downloader.fail_on = {"fake://bs-roformer-ep317/a.bin"}
    streams = Streams(world)
    assert run_models_download(["bs-roformer-ep317"], config_file=None, edges=streams.edges) == 1
    assert "connection lost" in streams.err.getvalue()


@pytest.fixture
def models_in_place(world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> FakeWorld:
    """Every model that ``doctor`` checks by default is in the model folder (tiny stand-ins)."""
    specs = {n: tiny_spec(n, {"f": n.encode()}) for n in DEFAULT_SET}

    def find(name: str) -> ModelSpec:
        return specs[name]

    monkeypatch.setattr("vocatron.stages.doctor.find_model", find)
    for name in specs:
        world.store.add(MODELS_DIR / name / "f", name.encode())
    return world


def test_doctor_is_happy_when_everything_is_in_place(models_in_place: FakeWorld) -> None:
    streams = Streams(models_in_place)
    assert run_doctor(output=None, config_file=None, edges=streams.edges) == 0
    assert streams.out.getvalue().splitlines()[-1] == "everything is ready"
    assert "✗" not in streams.out.getvalue()


def test_doctor_prints_what_to_fix_and_exits_with_one(
    world: FakeWorld, snapshot: SnapshotAssertion
) -> None:
    world.probe.version = GOOD_FFMPEG.replace("--enable-libass ", "")
    world.probe.encoders = GOOD_ENCODERS.replace("libx264", "xyz")
    world.probe.fdkaac = None
    world.probe.torch = TorchInfo("2.14.1+cpu", None, None, None)
    world.store.unwritable.add(Path("/work/karaoke"))
    streams = Streams(world)
    assert run_doctor(output=None, config_file=None, edges=streams.edges) == 1
    assert streams.out.getvalue() == snapshot


def test_doctor_without_ffmpeg_or_pytorch(world: FakeWorld) -> None:
    world.probe.version = None
    world.probe.encoders = None
    world.probe.torch = None
    streams = Streams(world)
    assert run_doctor(output="out", config_file=None, edges=streams.edges) == 1
    assert streams.out.getvalue().count("fix:") == 5  # ffmpeg, libass, encoders, PyTorch, models


def test_doctor_checks_the_output_option(world: FakeWorld) -> None:
    world.store.unwritable.add(Path("/locked"))
    streams = Streams(world)
    run_doctor(output="/locked/out", config_file=None, edges=streams.edges)
    assert "/locked/out cannot be written" in streams.out.getvalue()


def test_doctor_reports_a_broken_configuration(world: FakeWorld) -> None:
    world.store.add(Path("/work/vocatron.yaml"), b"nope: 1\n")
    streams = Streams(world)
    assert run_doctor(output=None, config_file=None, edges=streams.edges) == 2
    assert "nope" in streams.err.getvalue()


def test_make_offline_fails_a_song_whose_models_are_missing(
    world: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = tiny_spec("tiny", {"w": b"w"})
    monkeypatch.setattr(models, "find_model", returning(spec))
    monkeypatch.setattr(batch, "STAGES", (ProbeStage(), NeedsModelStage()))
    world.add_song(MUSIC / "a.mp3")
    streams = Streams(world)
    code = run_make(
        MUSIC, output=None, config_file=None, options=Options(offline=True), edges=streams.edges
    )
    assert code == 1
    assert "vocatron models download tiny" in streams.out.getvalue()
    assert world.downloader.calls == []


def test_doctor_without_a_gpu_is_only_a_note(models_in_place: FakeWorld) -> None:
    models_in_place.probe.torch = TorchInfo("2.14.1+cpu", None, None, None)
    streams = Streams(models_in_place)
    assert run_doctor(output=None, config_file=None, edges=streams.edges) == 0
    out = streams.out.getvalue()
    assert "! GPU" in out
    assert "note: PyTorch finds no CUDA GPU" in out
    assert "fix:" not in out
    assert out.splitlines()[-1] == "everything is ready (1 with a note)"


def fetched_models(world: FakeWorld) -> set[str]:
    return {destination.parent.name for _, destination in world.downloader.calls}


def test_download_with_a_language_fetches_what_a_song_in_it_needs(world: FakeWorld) -> None:
    streams = Streams(world)
    assert run_models_download([], language="en", config_file=None, edges=streams.edges) == 0
    assert fetched_models(world) == set(language_models("en"))
    assert "wav2vec2-en" in streams.out.getvalue()
    assert "wav2vec2-de" not in fetched_models(world)


def test_download_without_names_or_language_fetches_the_english_set(
    world: FakeWorld,
) -> None:
    assert run_models_download([], config_file=None, edges=Streams(world).edges) == 0
    assert fetched_models(world) == set(language_models("en"))
    assert "wav2vec2-de" not in fetched_models(world)


def test_download_adds_the_named_models_to_those_of_the_language_without_doubles(
    world: FakeWorld,
) -> None:
    streams = Streams(world)
    args = ["wav2vec2-de", "bs-roformer-leap"]
    assert run_models_download(args, language="en", config_file=None, edges=streams.edges) == 0
    assert fetched_models(world) == {*language_models("en"), "wav2vec2-de"}
    assert len(world.downloader.calls) == len({url for url, _ in world.downloader.calls})


def test_download_of_an_unsupported_language_is_a_usage_error(world: FakeWorld) -> None:
    streams = Streams(world)
    assert run_models_download([], language="fr", config_file=None, edges=streams.edges) == 2
    assert "--language: " in streams.err.getvalue()
    assert "language 'fr' is not supported" in streams.err.getvalue()
    assert world.downloader.calls == []


def models_line(output: str) -> str:
    """Return the doctor's models check as one line (the console wraps it)."""
    text = " ".join(output.split())
    return text[text.index("models ") : text.index(" output folder")]


def test_doctor_checks_the_models_of_the_configured_language(world: FakeWorld) -> None:
    streams = Streams(world)
    run_doctor(output=None, config_file=None, edges=streams.edges)
    assert "wav2vec2-en" in models_line(streams.out.getvalue())
    assert "wav2vec2-de" not in models_line(streams.out.getvalue())
    world.store.add(Path("/work/vocatron.yaml"), b"lyrics:\n  language: de\n")
    german = Streams(world)
    run_doctor(output=None, config_file=None, edges=german.edges)
    assert "wav2vec2-de" in models_line(german.out.getvalue())
    assert "wav2vec2-en" not in models_line(german.out.getvalue())


def test_doctor_is_happy_with_what_models_download_fetched_without_a_language(
    world: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The install guide's order: ``models download``, then ``doctor``, both without a language."""
    files = {name: {"f": name.encode()} for name in MODELS_BY_NAME}
    specs = {name: tiny_spec(name, content) for name, content in files.items()}
    for name, spec in specs.items():
        world.downloader.serve(spec, files[name])
    monkeypatch.setattr("vocatron.cli.commands.find_model", specs.__getitem__)
    monkeypatch.setattr("vocatron.stages.doctor.find_model", specs.__getitem__)
    assert run_models_download([], config_file=None, edges=Streams(world).edges) == 0
    streams = Streams(world)
    assert run_doctor(output=None, config_file=None, edges=streams.edges) == 0
    assert "✓ models" in streams.out.getvalue()


def test_doctor_asks_for_lame_only_when_cdg_is_on(models_in_place: FakeWorld) -> None:
    models_in_place.probe.encoders = GOOD_ENCODERS.replace("libmp3lame", "mp2")
    streams = Streams(models_in_place)
    assert run_doctor(output=None, config_file=None, edges=streams.edges) == 0
    models_in_place.store.add(Path("/work/vocatron.yaml"), b"outputs: [mp4, cdg]\n")
    streams = Streams(models_in_place)
    assert run_doctor(output=None, config_file=None, edges=streams.edges) == 1
    assert "libmp3lame" in streams.out.getvalue()
