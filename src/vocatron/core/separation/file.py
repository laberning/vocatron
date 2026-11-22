"""The stage file of the separation stage: ``separation.json`` and the stem names (ADR-0006)."""

from typing import ClassVar, Literal

from pydantic import Field

from vocatron.core.separation.job import StemGains
from vocatron.core.separation.rules import Device
from vocatron.core.stage_file import StageFile
from vocatron.core.worker import Frozen

STEMS_FOLDER = "stems"
STEM_NAMES = ("lead", "backing", "instrumental", "karaoke")
"""The stems of a song, in the order they are listed."""
STEM_SUFFIX = ".flac"


def stem_path(name: str) -> str:
    """Return where stem ``name`` lies relative to the work folder."""
    return f"{STEMS_FOLDER}/{name}{STEM_SUFFIX}"


class UsedModel(Frozen):
    """A model a stem was made with.

    Attributes:
        name: The registry name.
        revision: The pinned revision.
    """

    name: str
    revision: str


class SeparationFile(StageFile):
    """``separation.json``: how the stems were made.

    Attributes:
        keep_backing: Whether the karaoke mix keeps the backing vocals.
        models: The models used, vocals first.
        stems: The stem files relative to the work folder.
        samples: The length of every stem in samples.
        sample_rate: Their sample rate.
        gains: The headroom gains applied.
        device: The device used.
        seconds: How long the separation took.
        peak_vram_gib: The most GPU memory used, or ``None`` on the CPU.
        warnings: What the fan should know, for example the fallback to the CPU.
    """

    SCHEMA_NAME: ClassVar[str] = "separation"
    schema_version: Literal[1] = 1
    keep_backing: bool
    models: list[UsedModel]
    stems: list[str]
    samples: int
    sample_rate: int
    gains: StemGains
    device: Device
    seconds: float
    peak_vram_gib: float | None = None
    warnings: list[str] = Field(default_factory=list)
