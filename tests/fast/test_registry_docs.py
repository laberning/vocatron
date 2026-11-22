"""Stage 1: the registry, the code and THIRD_PARTY.md name the same models."""

import hashlib
import re
from pathlib import Path

import pytest

from fakes.songs import FakeWorld
from vocatron.core.languages import LANGUAGES
from vocatron.core.models import MODELS
from vocatron.stages.config import Config, LyricsSettings
from vocatron.stages.registry import STAGES

ROOT = Path(__file__).resolve().parents[2]
THIRD_PARTY = (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
REGISTRY_MODULE = ROOT / "src" / "vocatron" / "core" / "models.py"
# How models are named in code: the publishers' repository or file names.
MODEL_NAME = re.compile(
    r"\b(?:[\w-]+/(?:wav2vec2|whisper)[\w.-]*|model_bs_roformer[\w.]*|karaoke_bs_roformer[\w.]*)"
)


def models_table_rows() -> list[str]:
    """Return the rows of the "Models (downloaded at runtime)" table of THIRD_PARTY.md."""
    section = THIRD_PARTY.split("## Models (downloaded at runtime)", 1)[1].split("\n## ", 1)[0]
    return [line for line in section.splitlines() if line.startswith("| ") and "`" in line]


def test_every_registry_model_has_a_row_with_its_pins_and_licence() -> None:
    rows = models_table_rows()
    for spec in MODELS:
        (row,) = [r for r in rows if f"`{spec.source_name}`" in r]
        assert spec.licence.lower() in row.lower(), spec.name
        assert spec.revision[:8] in row, spec.name
        for sha in re.findall(r"[0-9a-f]{64}", row):
            assert sha in {f.sha256 for f in spec.files}, spec.name


def test_every_row_of_third_party_is_in_the_registry() -> None:
    names = {spec.source_name for spec in MODELS}
    rows = models_table_rows()
    assert len(rows) == len(names)
    for row in rows:
        found = re.search(r"`([^`]+)`", row.split("|")[2])
        assert found is not None
        assert found.group(1) in names


def test_every_checksum_in_the_models_section_is_a_registry_checksum() -> None:
    section = THIRD_PARTY.split("## Models (downloaded at runtime)", 1)[1].split("\n## ", 1)[0]
    known = {f.sha256 for spec in MODELS for f in spec.files}
    assert set(re.findall(r"\b[0-9a-f]{64}\b", section)) <= known


def test_the_bundled_font_files_have_the_checksums_that_third_party_records() -> None:
    section = THIRD_PARTY.split("## Bundled assets", 1)[1].split("\n## ", 1)[0]
    for name in ("NotoSans-Bold.ttf", "OFL.txt"):
        data = (ROOT / "src" / "vocatron" / "fonts" / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() in section, f"{name} differs from THIRD_PARTY.md"


@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_stages_declare_only_models_of_the_registry(language: str) -> None:
    names = {spec.name for spec in MODELS}
    world = FakeWorld()
    audio = Path("/music/Artist - Title.mp3")
    world.add_song(audio)
    ctx = world.context(audio)
    config = Config(lyrics=LyricsSettings(language=language))
    for stage in STAGES:
        assert set(stage.required_models(ctx, config)) <= names, (stage.name, language)


def test_code_names_no_model_that_the_registry_lacks() -> None:
    known = {spec.source_name for spec in MODELS}
    for path in (ROOT / "src").rglob("*.py"):
        if path == REGISTRY_MODULE:
            continue
        for name in MODEL_NAME.findall(path.read_text(encoding="utf-8")):
            assert name.rstrip(".") in known, f"{path.name} names {name}"


def test_third_party_marks_exactly_the_non_commercial_models_so() -> None:
    rows = models_table_rows()
    for spec in MODELS:
        (row,) = [r for r in rows if f"`{spec.source_name}`" in r]
        assert ("non-commercial" in row) == spec.non_commercial, spec.name
