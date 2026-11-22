"""The stage file of the render stage: ``render.json`` (ADR-0006, ADR-0009)."""

from typing import ClassVar, Literal

from vocatron.core.stage_file import StageFile


class RenderFile(StageFile):
    """``render.json``: what the render stage made.

    Attributes:
        preset: The output preset that was used.
        audio_encoder: ``fdkaac`` or ``ffmpeg-aac``.
        files: The names of the files in the output folder: the MP4, the audio export if any, and
            the enhanced LRC.
        fonts: The faces libass drew with; all of them the bundled font.
        seconds: How long the renderer took.
    """

    SCHEMA_NAME: ClassVar[str] = "render"
    schema_version: Literal[1] = 1
    preset: str
    audio_encoder: str
    files: list[str]
    fonts: list[str]
    seconds: float
