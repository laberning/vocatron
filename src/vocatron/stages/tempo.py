"""The ``tempo`` stage: how fast is the song (ADR-0022).

It estimates one tempo from the instrumental stem with ``vocatron.core.tempo`` and writes
``tempo.json``. The layout reads it to count the countdown in beats. The stage has no settings,
so only the stem and the stage version decide when it runs again.
"""

from pydantic import BaseModel

from vocatron.core.separation.file import stem_path
from vocatron.core.stage_file import Fingerprint, StageFile
from vocatron.core.tempo import SAMPLE_RATE, TempoFile, estimate_tempo
from vocatron.stages.config import Config
from vocatron.stages.stage import StageContext, TypedStage

TEMPO_STAGE = "tempo"
TEMPO_FILE = "tempo.json"
INSTRUMENTAL = stem_path("instrumental")


class TempoSettings(BaseModel):
    """The settings of the tempo stage: none (it has no section in the configuration)."""


class TempoStage(TypedStage[TempoSettings]):
    """Estimates the tempo of the song from its instrumental stem."""

    name = TEMPO_STAGE
    version = 1
    inputs = (INSTRUMENTAL,)
    output = TEMPO_FILE
    output_model = TempoFile

    def settings_from(self, config: Config) -> TempoSettings:
        """Return no settings."""
        del config
        return TempoSettings()

    def run(
        self, ctx: StageContext, settings: TempoSettings, fingerprint: Fingerprint
    ) -> StageFile:
        """Write ``tempo.json``.

        Raises:
            StageError: ``decode-failed`` if the stem cannot be decoded.
        """
        del settings
        stem = ctx.engines.audio.read(ctx.song.work_dir / INSTRUMENTAL, SAMPLE_RATE, 1)
        tempo = estimate_tempo(stem[0])
        if tempo.bpm is None:
            ctx.log(f"tempo: tempo unclear (clarity {tempo.clarity:.2f})")
        else:
            ctx.log(f"tempo: {tempo.bpm:.1f} BPM (clarity {tempo.clarity:.2f})")
        return TempoFile(fingerprint=fingerprint, bpm=tempo.bpm, clarity=tempo.clarity)
