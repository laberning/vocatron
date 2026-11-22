"""The stage file of the CD+G output: ``cdg.json`` (ADR-0006, ADR-0023, ADR-0029)."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from vocatron.core.stage_file import StageFile


class CdgValues(BaseModel):
    """The CD+G values a file was written with: the look's ``cdg`` section and the fallback.

    Attributes:
        slots: Lines on screen at most.
        font_px: The line cell in pixels.
        min_font_px: The smallest line cell in pixels.
        edge_px: The outline in pixels.
        wipe_columns: The pixels the wipe moves at a time (6 after the last fallback step).
        lead_in_min: The lead-in minimum in seconds (raised by the fallback steps).
    """

    model_config = ConfigDict(extra="forbid")

    slots: int
    font_px: int
    min_font_px: int
    edge_px: int
    wipe_columns: int
    lead_in_min: float


class CdgFile(StageFile):
    """``cdg.json``: what the cdg stage made.

    Attributes:
        enabled: Whether ``cdg`` is in the config's ``outputs``. When it is not, the stage only
            writes this file and the other fields keep their defaults.
        profile: The name of the style profile that was used.
        files: The names of the files in the output folder: the MP3 and the CD+G file, or only the
            zip that holds both (``cdg_zip``).
        zipped: The pair was packed into a zip (ADR-0030).
        values: The CD+G values used, after the fallback step.
        step: The fallback step taken (0: the look as declared; the steps are in ADR-0029).
        step_name: What the step does, in words.
        in_time: Every line was fully drawn before its first syllable and the wipe was at most
            50 ms behind. False when no fallback step reached the timing.
        late_lines: How many lines were drawn late (0 when ``in_time``).
        palette: The 16 palette entries as ``#rrggbb`` (the 12-bit colours of the file).
        packets: The number of packets in the CD+G file (300 per second).
        drawing_packets: How many of them draw (the others are filler).
        draw_lag: The longest wait in seconds of a tile of a line that appears or goes, from the
            moment it changed to the packet that drew it.
        wipe_lag: The same for the tiles of a wipe, a countdown or a progress bar.
        seconds: How long the stage took.
    """

    SCHEMA_NAME: ClassVar[str] = "cdg"
    schema_version: Literal[2] = 2
    enabled: bool
    profile: str = ""
    files: list[str] = []
    zipped: bool = False
    values: CdgValues | None = None
    step: int = 0
    step_name: str = ""
    in_time: bool = True
    late_lines: int = 0
    palette: list[str] = []
    packets: int = 0
    drawing_packets: int = 0
    draw_lag: float = 0.0
    wipe_lag: float = 0.0
    seconds: float = 0.0
