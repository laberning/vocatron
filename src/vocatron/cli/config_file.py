"""Load ``vocatron.yaml`` into a validated ``Config`` (ADR-0002, ADR-0006).

The file is parsed with ruamel.yaml, which knows the line and column of every key, and validated
with Pydantic. Errors name file, line and column. Precedence: defaults, then the file, then the
command-line options.

A relative output folder is anchored where it was written: ``--output`` at the current folder,
``output.folder`` in the file at the folder of the file. Only the default (``karaoke``) stays
relative, so that it lands inside the folder holding the songs. The model folder works the same
way, except that its default is anchored at the clone of Vocatron. ``profiles_folder`` (no
default) is anchored at the folder of the file. A profile given as a path is anchored too, but a
profile name (ADR-0019) stays a name.
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from vocatron.core.config_errors import Issue, Positions, describe_all
from vocatron.core.profiles.model import is_name
from vocatron.core.yaml_pos import YamlSyntaxError, parse_yaml
from vocatron.engines.protocols import FileStore
from vocatron.stages.config import Config, ModelsSettings, OutputSettings, Settings

DEFAULT_FILE = "vocatron.yaml"


class ConfigError(Exception):
    """The configuration is wrong; ``messages`` are ready to print, one per problem."""

    def __init__(self, messages: list[str]) -> None:
        """Create the error from its printable messages."""
        super().__init__("\n".join(messages))
        self.messages = messages


def _parse(file: str, text: str) -> tuple[object, Positions]:
    """Parse YAML text; return the data and the position of every key.

    Raises:
        ConfigError: If the text is not valid YAML.
    """
    try:
        return parse_yaml(file, text)
    except YamlSyntaxError as error:
        raise ConfigError([str(error)]) from error


def _anchor_profile(spec: str, base: Path) -> str:
    """Make the path of a profile file absolute against ``base`` (a name stays, ADR-0019)."""
    return spec if is_name(spec) else str(base / spec)


def _anchor[S: OutputSettings | ModelsSettings](section: S, base: Path) -> S:
    """Make a relative folder absolute against ``base`` (an absolute one stays)."""
    return section.model_copy(update={"folder": str(base / section.folder)})


@dataclass(frozen=True)
class Overrides:
    """Command-line options that override the configuration file.

    Attributes:
        language: ``--language``, overriding ``lyrics.language``.
        keep_backing: ``--no-backing`` gives ``False``, overriding ``separation.keep_backing``.
        device: ``--device``, overriding ``separation.device`` and ``alignment.device``.
        profile: ``--profile``, overriding ``profile``.
        preset: ``--preset``, overriding ``preset``.
        cdg: ``--cdg`` gives ``True``: ``cdg`` is added to ``outputs`` for this run.
    """

    language: str | None = None
    keep_backing: bool | None = None
    device: str | None = None
    profile: str | None = None
    preset: str | None = None
    cdg: bool = False


def load_config(
    store: FileStore,
    explicit: Path | None,
    cwd: Path,
    output: str | None = None,
    clone: Path | None = None,
    overrides: Overrides | None = None,
) -> Config:
    """Build the configuration.

    Args:
        store: Reads the file.
        explicit: The file given with ``--config`` (relative to ``cwd``); otherwise
            ``vocatron.yaml`` in ``cwd`` is used if it exists.
        cwd: The current folder.
        output: The ``--output`` option (relative to ``cwd``), which overrides ``output.folder``.
        clone: The folder of the Vocatron clone, where the default model folder lies; without it
            the default stays relative.
        overrides: The command-line options that override the file.

    Returns:
        The validated configuration.

    Raises:
        ConfigError: If the file is missing (when given) or unreadable, is not valid YAML, or does
            not validate, or if an option has an invalid value.
    """
    path = cwd / (explicit if explicit is not None else DEFAULT_FILE)
    try:
        text = store.read_text(path)
    except (OSError, UnicodeDecodeError) as error:  # a folder, no permission, not UTF-8
        raise ConfigError([f"{path}: cannot read: {error}"]) from error
    if text is None and explicit is not None:
        raise ConfigError([f"{path}: file not found"])
    config = Config()
    if text is not None:
        data, positions = _parse(str(path), text)
        try:
            config = Config.model_validate({} if data is None else data)
        except ValidationError as error:
            issues = [Issue(tuple(e["loc"]), e["msg"]) for e in error.errors()]
            raise ConfigError(describe_all(str(path), issues, positions)) from error
        config = _anchor_file(config, path.parent)
    if clone is not None and "folder" not in config.models.model_fields_set:
        config = config.model_copy(update={"models": _anchor(config.models, clone)})
    if output is not None:
        section = _override(config.output, "folder", output, "--output")
        config = config.model_copy(update={"output": _anchor(section, cwd)})
    return _apply(config, overrides or Overrides(), cwd)


def _anchor_file(config: Config, base: Path) -> Config:
    """Anchor the folders and the profile path written in the file at the folder of the file."""
    changes: dict[str, object] = {}
    if "folder" in config.output.model_fields_set:
        changes["output"] = _anchor(config.output, base)
    if "folder" in config.models.model_fields_set:
        changes["models"] = _anchor(config.models, base)
    if config.profiles_folder is not None:
        changes["profiles_folder"] = str(base / config.profiles_folder)
    if "profile" in config.model_fields_set:
        changes["profile"] = _anchor_profile(config.profile, base)
    return config.model_copy(update=changes)


def _apply(config: Config, overrides: Overrides, cwd: Path) -> Config:
    """Return ``config`` with the options that were given; a profile path is relative to ``cwd``."""
    if overrides.profile is not None:
        config = config.model_copy(update={"profile": _anchor_profile(overrides.profile, cwd)})
    if overrides.preset is not None:
        config = _override(config, "preset", overrides.preset, "--preset")
    if overrides.language is not None:
        lyrics = _override(config.lyrics, "language", overrides.language, "--language")
        config = config.model_copy(update={"lyrics": lyrics})
    if overrides.cdg and "cdg" not in config.outputs:
        config = config.model_copy(update={"outputs": [*config.outputs, "cdg"]})
    separation = config.separation
    alignment = config.alignment
    if overrides.keep_backing is not None:
        separation = _override(separation, "keep_backing", overrides.keep_backing, "--no-backing")
    if overrides.device is not None:
        separation = _override(separation, "device", overrides.device, "--device")
        alignment = _override(alignment, "device", overrides.device, "--device")
    return config.model_copy(update={"separation": separation, "alignment": alignment})


def _override[S: Settings](section: S, key: str, value: str | bool, option: str) -> S:
    """Return ``section`` with ``key`` set to the value of a command-line option, validated.

    Raises:
        ConfigError: If the value is invalid; the message names the option.
    """
    try:
        return section.model_validate({**section.model_dump(), key: value})
    except ValidationError as error:
        raise ConfigError([f"{option}: {e['msg']}" for e in error.errors()]) from error
