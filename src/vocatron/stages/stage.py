"""The stage protocol and what a stage gets to work with (ADR-0006, ADR-0007).

A stage reads typed files from the work folder (and the audio), writes one typed file, and sees
engines only through their protocols. The batch runner does everything around it: fingerprint,
skip, status, log, error handling.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from vocatron.core.errors import StageError
from vocatron.core.measure import TextMeasurer, TextRasteriser
from vocatron.core.song import Identity, Tags
from vocatron.core.stage_file import Fingerprint, StageFile
from vocatron.engines.protocols import (
    AcousticModel,
    AudioReader,
    Clock,
    Downloader,
    FileStore,
    LanguageDetector,
    LyricsSource,
    Mp3Encoder,
    Packer,
    Renderer,
    Resources,
    Separator,
    TagReader,
    Watch,
)
from vocatron.stages.config import Config

AUDIO = "audio"  # the input name of the song's audio file
LOG_FILE = "log.txt"  # the song log in the work folder


@dataclass(frozen=True)
class Engines:
    """The engines the frame needs, chosen at the edge and passed in."""

    clock: Clock
    tags: TagReader
    store: FileStore
    downloader: Downloader
    lyrics: LyricsSource
    language: LanguageDetector
    separator: Separator
    acoustic: AcousticModel
    measurer: TextMeasurer
    rasteriser: TextRasteriser
    renderer: Renderer
    mp3: Mp3Encoder
    packer: Packer
    resources: Resources
    audio: AudioReader


@dataclass(frozen=True)
class Song:
    """One song to process.

    Attributes:
        source: The audio file.
        name: The unique safe name of the track and the work folder.
        identity: Artist and title.
        tags: The tags, or ``None`` when they could not be read.
        tag_error: Why the tags could not be read.
        output_dir: The output folder.
        work_dir: The work folder of this song, inside the output folder.
    """

    source: Path
    name: str
    identity: Identity
    tags: Tags | None
    tag_error: str | None
    output_dir: Path
    work_dir: Path


class LogLine(Protocol):
    """Writes one line to the log of the current song."""

    def __call__(self, message: str) -> None:
        """Write ``message``."""
        ...


@dataclass(frozen=True)
class StageContext:
    """What a stage run may use.

    Attributes:
        song: The song.
        engines: The engines, as protocols.
        log: Writes one line to the song's log file.
        models_dir: The model folder.
        watch: Where a long-running stage reports its progress, and the time left of the song.
    """

    song: Song
    engines: Engines
    log: LogLine
    models_dir: Path
    watch: Watch = field(default_factory=Watch)


class Stage(Protocol):
    """A pipeline stage as the batch runner sees it.

    Attributes:
        name: Short name, also the config section and the log prefix.
        version: The stage's code version; bump it when its output changes for the same input.
        inputs: What the stage reads: ``AUDIO`` and/or names of stage files in the work folder.
        output: File name of the stage file it writes.
        extra_outputs: The other files it writes, relative to the work folder (the stems, for
            example). The stage is skipped only when the stage file and all of these exist.
        output_model: The Pydantic model of that file.
    """

    name: str
    version: int
    inputs: tuple[str, ...]
    output: str
    extra_outputs: tuple[str, ...]
    output_model: type[StageFile]

    def declared_settings(self, ctx: StageContext, config: Config) -> BaseModel:
        """Return the settings the stage depends on; their hash is part of the fingerprint.

        ``ctx`` is the song's context: a stage may depend on the song (the language of its
        lyrics picks the alignment model).
        """
        ...

    def required_models(self, ctx: StageContext, config: Config) -> tuple[str, ...]:
        """Return the registry names of the models the stage needs; fetched before it runs."""
        ...

    def external_inputs(self, ctx: StageContext, config: Config) -> dict[str, str]:
        """Return the SHA-256 of the input files outside the work folder that exist now.

        They count as inputs next to ``inputs``, but a missing one is no error (the lyrics
        sidecar next to the audio is the example). The configuration says which files these are
        when it chooses them (a style profile).
        """
        ...

    def products(self, ctx: StageContext, stored: StageFile) -> tuple[Path, ...]:
        """Return the files the stage wrote outside the work folder, from its stage file.

        The stage is skipped only when they exist too (the finished tracks in the output folder).
        """
        ...

    def execute(self, ctx: StageContext, config: Config, fingerprint: Fingerprint) -> StageFile:
        """Run the stage and return its output, carrying ``fingerprint``."""
        ...


def declared_outputs(stage: Stage) -> tuple[str, ...]:
    """Return every file ``stage`` writes, relative to the work folder: stage file first."""
    return (stage.output, *stage.extra_outputs)


def missing_outputs(stage: Stage, ctx: StageContext, stored: StageFile | None = None) -> list[str]:
    """Return the outputs of ``stage`` that do not exist.

    These are its declared files in the work folder and, given its stored stage file, the products
    it wrote outside the work folder (named by file).
    """
    store, folder = ctx.engines.store, ctx.song.work_dir
    missing = [name for name in declared_outputs(stage) if store.size(folder / name) is None]
    if stored is not None:
        missing += [p.name for p in stage.products(ctx, stored) if store.size(p) is None]
    return missing


def read_input[M: BaseModel](ctx: StageContext, name: str, model: type[M]) -> M:
    """Read the stage file ``name`` of the work folder as ``model``.

    Raises:
        StageError: ``missing-input`` if the file is missing or does not validate.
    """
    text = ctx.engines.store.read_text(ctx.song.work_dir / name)
    try:
        if text is not None:
            return model.model_validate_json(text)
    except ValueError:
        pass
    raise StageError(
        "missing-input", f"{name} is missing or invalid; run `vocatron make` for this song first"
    )


class TypedStage[S: BaseModel](ABC):
    """Base for stages with a typed settings section: implement ``settings_from`` and ``run``.

    A stage that needs models lists their registry names in ``models`` (or overrides
    ``required_models`` when the configuration chooses them).
    """

    name: str
    version: int
    inputs: tuple[str, ...]
    models: tuple[str, ...] = ()
    output: str
    extra_outputs: tuple[str, ...] = ()
    output_model: type[StageFile]

    @abstractmethod
    def settings_from(self, config: Config) -> S:
        """Pick the stage's settings section out of the configuration."""

    @abstractmethod
    def run(self, ctx: StageContext, settings: S, fingerprint: Fingerprint) -> StageFile:
        """Do the work and return the stage file (with ``fingerprint`` set)."""

    def declared_settings(self, ctx: StageContext, config: Config) -> BaseModel:
        """Return the settings section the stage depends on."""
        del ctx
        return self.settings_from(config)

    def required_models(self, ctx: StageContext, config: Config) -> tuple[str, ...]:
        """Return ``models``."""
        del ctx, config
        return self.models

    def external_inputs(self, ctx: StageContext, config: Config) -> dict[str, str]:
        """Return no input outside the work folder; a stage that has some overrides this."""
        del ctx, config
        return {}

    def products(self, ctx: StageContext, stored: StageFile) -> tuple[Path, ...]:
        """Return no file outside the work folder; a stage that writes some overrides this."""
        del ctx, stored
        return ()

    def execute(self, ctx: StageContext, config: Config, fingerprint: Fingerprint) -> StageFile:
        """Run the stage with its own settings section."""
        return self.run(ctx, self.settings_from(config), fingerprint)
