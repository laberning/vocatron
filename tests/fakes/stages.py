"""A test stage that declares a model, like a real separation stage will."""

from typing import Literal

from vocatron.core.stage_file import Fingerprint, StageFile
from vocatron.stages.config import Config, ProbeSettings
from vocatron.stages.stage import AUDIO, StageContext, TypedStage


class NoteFile(StageFile):
    SCHEMA_NAME = "note"
    schema_version: Literal[1] = 1


class NeedsModelStage(TypedStage[ProbeSettings]):
    """Does nothing, but needs the model ``tiny``."""

    name = "needs-model"
    version = 1
    inputs = (AUDIO,)
    models = ("tiny",)
    output = "needs-model.json"
    output_model = NoteFile

    def settings_from(self, config: Config) -> ProbeSettings:
        return config.probe

    def run(
        self, ctx: StageContext, settings: ProbeSettings, fingerprint: Fingerprint
    ) -> StageFile:
        return NoteFile(fingerprint=fingerprint)
