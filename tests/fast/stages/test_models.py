"""Stage 1: the model folder, fetching and ensure_models on fakes."""

from pathlib import Path

import pytest

from fakes.models import returning, tiny_spec
from fakes.songs import FakeWorld
from vocatron.core.errors import StageError
from vocatron.core.models import MODELS, ModelFile, ModelSpec, UnknownModelError
from vocatron.stages import models as models_module
from vocatron.stages.models import LogListener, ModelFolder, ensure_models, fetch

FOLDER = Path("/models")
FILES = {"weights.bin": b"w" * 100, "config.json": b"{}"}
SPEC = tiny_spec("tiny", FILES, licence="Apache-2.0")


class Heard:
    """A download listener that records what it hears."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def licence(self, spec: ModelSpec) -> None:
        self.events.append(f"licence {spec.notice()}")

    def file_started(self, spec: ModelSpec, file: ModelFile) -> None:
        self.events.append(f"start {spec.name}/{file.path}")

    def progress(self, done: int, total: int) -> None:
        pass

    def file_finished(self, spec: ModelSpec, file: ModelFile) -> None:
        self.events.append(f"done {spec.name}/{file.path}")


@pytest.fixture
def world() -> FakeWorld:
    world = FakeWorld()
    world.downloader.serve(SPEC, FILES)
    return world


@pytest.fixture
def known(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the tiny model known to the registry lookup."""
    monkeypatch.setattr(models_module, "find_model", returning(SPEC))


def folder_of(world: FakeWorld) -> ModelFolder:
    return ModelFolder(FOLDER, world.store)


def test_a_model_is_missing_then_present_after_a_fetch(world: FakeWorld) -> None:
    folder = folder_of(world)
    assert folder.state(SPEC, verify=True) == "missing"
    heard = Heard()
    assert fetch([SPEC], folder, world.downloader, heard) == [SPEC]
    assert folder.state(SPEC, verify=True) == "present"
    assert heard.events == [
        "licence acme/tiny: licence Apache-2.0",
        "start tiny/weights.bin",
        "done tiny/weights.bin",
        "start tiny/config.json",
        "done tiny/config.json",
    ]
    assert (FOLDER / "tiny" / "weights.bin") in world.store.files


def test_a_present_model_is_not_downloaded_again(world: FakeWorld) -> None:
    folder = folder_of(world)
    fetch([SPEC], folder, world.downloader, Heard())
    world.downloader.calls.clear()
    assert fetch([SPEC], folder, world.downloader, Heard()) == []
    assert world.downloader.calls == []


def test_only_the_missing_files_are_fetched(world: FakeWorld) -> None:
    world.store.add(FOLDER / "tiny" / "weights.bin", FILES["weights.bin"])
    fetch([SPEC], folder_of(world), world.downloader, Heard())
    assert [url for url, _ in world.downloader.calls] == ["fake://tiny/config.json"]


def test_a_corrupt_file_is_found_by_verifying_and_replaced(world: FakeWorld) -> None:
    folder = folder_of(world)
    fetch([SPEC], folder, world.downloader, Heard())
    world.store.add(FOLDER / "tiny" / "weights.bin", b"x" * 100)  # right size, wrong content
    assert folder.state(SPEC, verify=False) == "present"  # a size check cannot see it
    assert folder.state(SPEC, verify=True) == "mismatch"
    fetch([SPEC], folder, world.downloader, Heard())
    assert folder.state(SPEC, verify=True) == "present"


def test_a_part_file_makes_a_model_partial(world: FakeWorld) -> None:
    world.store.add(FOLDER / "tiny" / "weights.bin.part", b"w" * 10)
    assert folder_of(world).state(SPEC, verify=True) == "partial"


def test_a_model_with_one_file_is_partial(world: FakeWorld) -> None:
    world.store.add(FOLDER / "tiny" / "config.json", FILES["config.json"])
    assert folder_of(world).state(SPEC, verify=True) == "partial"


def test_ensure_downloads_on_first_use_and_logs(world: FakeWorld, known: None) -> None:
    lines: list[str] = []

    def log(message: str) -> None:
        lines.append(message)

    ensure_models(
        ["tiny"],
        folder=folder_of(world),
        downloader=world.downloader,
        offline=False,
        listener=LogListener(log),
    )
    assert folder_of(world).state(SPEC, verify=True) == "present"
    assert lines[0] == "models: downloading tiny (acme/tiny: licence Apache-2.0)"
    assert lines[1].startswith("models: tiny/weights.bin (100 B) from fake://tiny/weights.bin")
    assert lines[-1] == "models: tiny/config.json verified"


def test_ensure_does_nothing_when_the_models_are_there(world: FakeWorld, known: None) -> None:
    folder = folder_of(world)
    fetch([SPEC], folder, world.downloader, Heard())
    world.downloader.calls.clear()
    ensure_models(
        ["tiny"], folder=folder, downloader=world.downloader, offline=True, listener=Heard()
    )
    assert world.downloader.calls == []


def test_ensure_without_models_asks_for_nothing(world: FakeWorld) -> None:
    ensure_models(
        [], folder=folder_of(world), downloader=world.downloader, offline=True, listener=Heard()
    )
    assert world.downloader.calls == []


def test_offline_fails_and_names_the_command(world: FakeWorld, known: None) -> None:
    with pytest.raises(StageError, match="vocatron models download tiny") as caught:
        ensure_models(
            ["tiny"],
            folder=folder_of(world),
            downloader=world.downloader,
            offline=True,
            listener=Heard(),
        )
    assert caught.value.kind == "models-missing"
    assert world.downloader.calls == []


def test_a_failed_download_becomes_a_stage_error(world: FakeWorld, known: None) -> None:
    world.downloader.fail_on = {"fake://tiny/weights.bin"}
    with pytest.raises(StageError, match="connection lost") as caught:
        ensure_models(
            ["tiny"],
            folder=folder_of(world),
            downloader=world.downloader,
            offline=False,
            listener=Heard(),
        )
    assert caught.value.kind == "model-download"


def test_an_unknown_name_is_a_bug(world: FakeWorld) -> None:
    with pytest.raises(UnknownModelError):
        ensure_models(
            ["nope"],
            folder=folder_of(world),
            downloader=world.downloader,
            offline=False,
            listener=Heard(),
        )


def test_paths_lie_in_a_folder_per_model(world: FakeWorld) -> None:
    spec = MODELS[0]
    folder = folder_of(world)
    assert folder.path_of(spec) == FOLDER / spec.name
    assert folder.path_of(spec, spec.files[0]) == FOLDER / spec.name / spec.files[0].path
    assert folder.state(spec, verify=False) == "missing"
