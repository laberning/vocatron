"""Stage 1: conformance of every registered stage and the committed schemas."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from fakes.songs import FakeWorld
from vocatron.core.schemas import (
    MANIFEST_NAME,
    parse_manifest,
    schema_digest,
    schema_filename,
    schema_text,
)
from vocatron.stages.config import Config, ModelsSettings, OutputSettings
from vocatron.stages.registry import STAGES, schema_models
from vocatron.stages.stage import AUDIO, Stage, declared_outputs

AUDIO_PATH = Path("/music/Artist - Title.mp3")
SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas"


@pytest.mark.parametrize("stage", STAGES, ids=lambda s: s.name)
def test_every_stage_conforms(stage: Stage, world: FakeWorld) -> None:
    # A config section per stage; the tempo stage has no settings, and the two stages of the video
    # read the top-level keys `profile`, `profile_overrides`, `preset` and `audio` (ADR-0009), and
    # the cdg stage reads `outputs` and the profile (ADR-0023).
    assert stage.name in Config.model_fields or stage.name in {"tempo", "layout", "render", "cdg"}
    world.add_song(AUDIO_PATH)
    ctx = world.context(AUDIO_PATH)
    config = Config()
    declared = stage.declared_settings(ctx, config)
    assert isinstance(declared, BaseModel)  # usually the section itself, or what of it counts
    assert declared == stage.declared_settings(ctx, Config())
    # Where the output and the models lie never changes a result, so it is never fingerprinted.
    moved = Config(output=OutputSettings(folder="elsewhere"), models=ModelsSettings(folder="m"))
    assert stage.declared_settings(ctx, moved) == declared
    assert stage.required_models(ctx, config) == stage.required_models(ctx, Config())
    assert stage.version >= 1
    assert stage.output.endswith(".json")
    assert stage.inputs
    assert all(
        name == AUDIO or Path(name).suffix in {".json", ".flac", ".ass"} for name in stage.inputs
    )
    assert stage.output_model.model_fields["schema_version"].default >= 1


def test_stage_names_and_outputs_are_unique() -> None:
    assert len({s.name for s in STAGES}) == len(STAGES)
    outputs = [name for stage in STAGES for name in declared_outputs(stage)]
    assert len(set(outputs)) == len(outputs)  # no file is written by two stages
    for name in outputs:
        assert not Path(name).is_absolute()
        assert ".." not in Path(name).parts  # every output lies inside the work folder


def test_stage_inputs_are_outputs_of_earlier_stages() -> None:
    produced: set[str] = {AUDIO}
    for stage in STAGES:
        assert set(stage.inputs) <= produced, stage.name
        produced.update(declared_outputs(stage))


@pytest.mark.parametrize("model", schema_models(), ids=lambda m: m.__name__)
def test_committed_schema_matches_the_model(model: type[BaseModel]) -> None:
    path = SCHEMA_DIR / schema_filename(model)
    assert path.is_file(), f"{path.name} is missing: run `make schemas`"
    assert path.read_text(encoding="utf-8") == schema_text(model), (
        f"{model.__name__} changed without a schema_version bump (then run `make schemas`)"
    )


def test_committed_schema_files_never_change() -> None:
    # Superseded versions stay as they were (ADR-0006): only `make schemas` adds lines.
    manifest = parse_manifest((SCHEMA_DIR / MANIFEST_NAME).read_text(encoding="utf-8"))
    on_disk = {path.name for path in SCHEMA_DIR.glob("*.json")}
    assert sorted(set(manifest) - on_disk) == [], "a committed schema file was deleted"
    assert sorted(on_disk - set(manifest)) == [], "schema files missing in the manifest"
    changed = [
        name
        for name, digest in manifest.items()
        if schema_digest((SCHEMA_DIR / name).read_text(encoding="utf-8")) != digest
    ]
    assert changed == [], "committed schema files changed: bump schema_version instead"
    assert {schema_filename(model) for model in schema_models()} <= set(manifest)
