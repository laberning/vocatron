"""The ``syllables`` stage: when is every syllable sung (ADR-0005).

It splits the words of ``alignment.json`` with the language module and shares each word's time
among its syllables (``vocatron.core.syllables``).
"""

from vocatron.core.alignment.file import AlignmentFile
from vocatron.core.errors import StageError
from vocatron.core.stage_file import Fingerprint, StageFile
from vocatron.core.syllables import SyllablesFile, split_word
from vocatron.stages.alignment import ALIGNMENT_FILE, module_of
from vocatron.stages.config import Config, SyllablesSettings
from vocatron.stages.stage import StageContext, TypedStage

SYLLABLES_STAGE = "syllables"


class SyllablesStage(TypedStage[SyllablesSettings]):
    """Splits the timed words into timed syllables."""

    name = SYLLABLES_STAGE
    # 3: the voice of every line, copied from alignment.json (ADR-0054, syllables.json v2)
    version = 3
    inputs = (ALIGNMENT_FILE,)
    output = "syllables.json"
    output_model = SyllablesFile

    def settings_from(self, config: Config) -> SyllablesSettings:
        """Return the ``syllables`` section."""
        return config.syllables

    def run(
        self, ctx: StageContext, settings: SyllablesSettings, fingerprint: Fingerprint
    ) -> StageFile:
        """Write ``syllables.json``.

        Raises:
            StageError: If ``alignment.json`` is missing or invalid, or its language has no module.
        """
        del settings
        text = ctx.engines.store.read_text(ctx.song.work_dir / ALIGNMENT_FILE)
        try:
            aligned = None if text is None else AlignmentFile.model_validate_json(text)
        except ValueError:
            aligned = None
        if aligned is None:
            raise StageError("missing-input", f"{ALIGNMENT_FILE} is missing or invalid")
        module = module_of(aligned.language)
        return SyllablesFile(
            fingerprint=fingerprint,
            language=aligned.language,
            words=[split_word(word, module) for word in aligned.words],
            voices=[line.voice for line in aligned.lines],
        )
