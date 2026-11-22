"""The ``separation`` stage: lead vocals, backing vocals, instrumental and the karaoke mix.

The heavy work is done by the ``Separator`` engine, which runs it in a child process (ADR-0002,
ADR-0007). The stage hands it the models and settings, checks that all four stems are there and
writes ``separation.json``. Which device ran and how long it took are recorded but are not part
of the fingerprint, since they do not change the result; the models with their inference
settings and ``keep_backing`` are.
"""

from typing import Literal, override

from pydantic import BaseModel

from vocatron.core.errors import StageError
from vocatron.core.models import ModelPin, ModelSpec, find_model
from vocatron.core.separation.file import STEM_NAMES, SeparationFile, UsedModel, stem_path
from vocatron.core.separation.job import ModelSetup, SeparationPlan
from vocatron.core.separation.rules import SAMPLE_RATE
from vocatron.core.stage_file import Fingerprint, StageFile
from vocatron.engines.protocols import SeparationRequest
from vocatron.stages.config import Config, SeparationSettings
from vocatron.stages.models import ModelFolder
from vocatron.stages.stage import AUDIO, LOG_FILE, StageContext, TypedStage, missing_outputs

SEPARATION_STAGE = "separation"


class Pinned(BaseModel):
    """The settings the separation depends on.

    Attributes:
        models: The vocals model (two for an ensemble) and the karaoke model with their pins.
        keep_backing: Whether the karaoke mix keeps the backing vocals.
    """

    models: list[ModelPin]
    keep_backing: bool


class PinnedFromMix(Pinned):
    """The settings when the karaoke model gets the full mix.

    A separate class so that the default order keeps its fingerprint and stored results stay
    current.

    Attributes:
        karaoke_input: Always ``mix``.
    """

    karaoke_input: Literal["mix"] = "mix"


def _file(spec: ModelSpec, suffix: str) -> str:
    """Return the path of the model file ending in ``suffix``."""
    (path,) = [f.path for f in spec.files if f.path.endswith(suffix)]
    return path


def model_setup(spec: ModelSpec, folder: ModelFolder) -> ModelSetup:
    """Return how the worker loads a model from the model folder (the pin's inference settings)."""
    files = {f.path: f for f in spec.files}
    return ModelSetup(
        name=spec.name,
        revision=spec.revision,
        checkpoint=str(folder.path_of(spec, files[_file(spec, ".ckpt")])),
        config=str(folder.path_of(spec, files[_file(spec, ".yaml")])),
        chunk_size=int(spec.inference["chunk_size"]),
        num_overlap=int(spec.inference["num_overlap"]),
        precision=str(spec.inference["precision"]),
        target="instrumental" if spec.inference.get("target") == "instrumental" else "vocals",
    )


class SeparationStage(TypedStage[SeparationSettings]):
    """Separates the song into lead, backing, instrumental and karaoke stems."""

    name = SEPARATION_STAGE
    version = 1
    inputs = (AUDIO,)
    output = "separation.json"
    extra_outputs = tuple(stem_path(name) for name in STEM_NAMES)
    output_model = SeparationFile

    def settings_from(self, config: Config) -> SeparationSettings:
        """Return the ``separation`` section."""
        return config.separation

    @override
    def declared_settings(self, ctx: StageContext, config: Config) -> BaseModel:
        """Return the models with their pins, ``keep_backing`` and a karaoke input of ``mix``.

        Device and timeouts are not part of it.
        """
        settings = self.settings_from(config)
        specs = [find_model(name) for name in self.required_models(ctx, config)]
        pins = [spec.pin() for spec in specs]
        if settings.karaoke_input == "mix":
            return PinnedFromMix(models=pins, keep_backing=settings.keep_backing)
        return Pinned(models=pins, keep_backing=settings.keep_backing)

    @override
    def required_models(self, ctx: StageContext, config: Config) -> tuple[str, ...]:
        """Return the vocals model or models of the configuration and the karaoke model."""
        del ctx
        settings = config.separation
        return (*settings.vocals_models, settings.karaoke_model)

    def run(
        self, ctx: StageContext, settings: SeparationSettings, fingerprint: Fingerprint
    ) -> StageFile:
        """Separate the song and write ``separation.json``.

        Raises:
            StageError: If the separator fails (``separation-failed``, ``separation-timeout``,
                ``out-of-memory``, ``no-gpu``, ``vram-too-small``) or leaves a stem missing.
        """
        folder = ModelFolder(ctx.models_dir, ctx.engines.store)
        vocals = [find_model(name) for name in settings.vocals_models]
        karaoke = find_model(settings.karaoke_model)
        song = ctx.song
        request = SeparationRequest(
            audio=song.source,
            work_dir=song.work_dir,
            log_path=song.work_dir / LOG_FILE,
            log=ctx.log,
            duration=song.tags.duration if song.tags is not None else None,
            device=settings.device,
            timeout_factor_gpu=settings.timeout_factor_gpu,
            timeout_factor_cpu=settings.timeout_factor_cpu,
            watch=ctx.watch,
            plan=SeparationPlan(
                keep_backing=settings.keep_backing,
                vocals_models=tuple(model_setup(spec, folder) for spec in vocals),
                karaoke_model=model_setup(karaoke, folder),
                karaoke_input=settings.karaoke_input,
            ),
        )
        result = ctx.engines.separator.separate(request)
        stems = list(self.extra_outputs)
        missing = [path for path in missing_outputs(self, ctx) if path in stems]
        if missing:
            raise StageError("separation-failed", f"the separator did not write {missing[0]}")
        notes = [spec.licence_warning() for spec in (*vocals, karaoke)]
        warnings = [*(note for note in notes if note is not None), *result.warnings]
        for warning in warnings:
            ctx.log(f"separation: warning: {warning}")
        ctx.log(
            f"separation: {result.samples / SAMPLE_RATE:.1f} s of audio on {result.device} in "
            f"{result.seconds:.1f} s, peak VRAM {result.peak_vram_gib}, gains {result.gains}"
        )
        return SeparationFile(
            fingerprint=fingerprint,
            keep_backing=settings.keep_backing,
            models=[UsedModel(name=m.name, revision=m.revision) for m in (*vocals, karaoke)],
            stems=stems,
            samples=result.samples,
            sample_rate=SAMPLE_RATE,
            gains=result.gains,
            device=result.device,
            seconds=result.seconds,
            peak_vram_gib=result.peak_vram_gib,
            warnings=warnings,
        )
