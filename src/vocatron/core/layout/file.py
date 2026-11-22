"""The stage file of the layout stage: ``layout.json`` (ADR-0006, ADR-0009)."""

from typing import ClassVar, Literal

from vocatron.core.scene import Scene
from vocatron.core.stage_file import StageFile


class LayoutFile(StageFile):
    """``layout.json``: what is on screen when, the scene of the song.

    Every renderer draws this; the ASS file of the video (``lyrics.ass``) is made from it.

    Attributes:
        profile: The name of the style profile that was used.
        scene: The scene.
    """

    SCHEMA_NAME: ClassVar[str] = "layout"
    # a v11 to v15 file reads as v16: v12 adds the line's voice, v13 the mark of the title
    # screen, v14 its pixel letters for CD+G, v15 the mark of the end screen and the symbol of
    # the break screen, v16 drops the path of the break screen, bar and timer (ADR-0040)
    schema_version: Literal[11, 12, 13, 14, 15, 16] = 16
    profile: str
    scene: Scene
