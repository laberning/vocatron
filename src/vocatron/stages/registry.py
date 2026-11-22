"""The ordered stage registry and the models of all committed schemas (ADR-0007).

A stage story appends its stage to ``STAGES`` in pipeline order.
"""

from pydantic import BaseModel

from vocatron.core.progress import ProgressFile
from vocatron.core.report import ReportFile
from vocatron.core.status import SongStatus
from vocatron.stages.alignment import AlignmentStage
from vocatron.stages.cdg import CdgStage
from vocatron.stages.layout import LayoutStage
from vocatron.stages.lyrics import LyricsStage
from vocatron.stages.probe import ProbeStage
from vocatron.stages.render import RenderStage
from vocatron.stages.separation import SeparationStage
from vocatron.stages.stage import Stage
from vocatron.stages.syllables import SyllablesStage
from vocatron.stages.tempo import TempoStage

STAGES: tuple[Stage, ...] = (
    ProbeStage(),
    LyricsStage(),
    SeparationStage(),
    TempoStage(),
    AlignmentStage(),
    SyllablesStage(),
    LayoutStage(),
    RenderStage(),
    CdgStage(),
)


def schema_models() -> list[type[BaseModel]]:
    """Return every model with a committed JSON schema: the files of the work folder."""
    return [SongStatus, ReportFile, ProgressFile, *(stage.output_model for stage in STAGES)]
