"""Stage 1: the configuration page documents every setting and its default."""

from pathlib import Path

from pydantic import BaseModel

from vocatron.cli.config_file import Overrides
from vocatron.stages.config import Config

PAGE = Path(__file__).resolve().parents[2] / "docs" / "user" / "config.md"


def leaves(model: type[BaseModel], prefix: str = "") -> dict[str, object]:
    """Return every setting as ``section.key`` with its default."""
    found: dict[str, object] = {}
    for name, field in model.model_fields.items():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            found.update(leaves(annotation, f"{prefix}{name}."))
        else:
            found[f"{prefix}{name}"] = field.get_default(call_default_factory=True)
    return found


def test_every_setting_is_in_the_table_with_its_default() -> None:
    rows = {
        cells[0].strip("`"): cells[1].strip("`")
        for line in PAGE.read_text(encoding="utf-8").splitlines()
        if line.startswith("| `")
        for cells in [[c.strip() for c in line.strip("|").split("|")]]
    }
    settings = leaves(Config)
    assert set(rows) == set(settings)
    assert rows == {key: str(default) for key, default in settings.items()}


# Every command-line option that overrides a setting, with the settings it overrides.
OPTIONS = {
    "output": ("--output", {"output.folder"}),
    "language": ("--language", {"lyrics.language"}),
    "keep_backing": ("--no-backing", {"separation.keep_backing"}),
    "device": ("--device", {"separation.device", "alignment.device"}),
    "profile": ("--profile", {"profile"}),
    "preset": ("--preset", {"preset"}),
    "cdg": ("--cdg", {"outputs"}),
}


def test_every_overriding_option_is_in_the_option_column() -> None:
    assert set(OPTIONS) - {"output"} == set(Overrides.__dataclass_fields__)
    shown: dict[str, set[str]] = {}
    for line in PAGE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 4 and cells[2]:
            shown.setdefault(cells[2].strip("`"), set()).add(cells[0].strip("`"))
    assert shown == {option: settings for option, settings in OPTIONS.values()}
