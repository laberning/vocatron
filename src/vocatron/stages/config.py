"""The configuration model: defaults, and one settings section per stage (ADR-0006).

Defaults come from these models, then ``vocatron.yaml`` overrides them, then command-line
options. Unknown keys are errors. A stage story adds its settings model and its section here;
the stage declares which section it depends on, so changed settings re-run exactly that stage.
"""

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue

from vocatron.core.languages import LANGUAGES
from vocatron.core.models import DEFAULT_VOCALS_MODEL, KARAOKE_MODEL, KARAOKE_MODELS, VOCALS_MODELS
from vocatron.core.presets import DEFAULT_PRESET, PRESETS, AudioSettings
from vocatron.core.profiles.model import DEFAULT_PROFILE
from vocatron.core.separation.rules import DeviceRequest


def _regular_expression(value: str) -> str:
    """Require a valid regular expression.

    Raises:
        ValueError: If the pattern does not compile.
    """
    try:
        re.compile(value)
    except re.error as error:
        raise ValueError(f"not a valid regular expression: {error}") from error
    return value


RegularExpression = Annotated[str, AfterValidator(_regular_expression)]


def _supported_language(value: str) -> str:
    """Require the code of a supported language (ADR-0005).

    Raises:
        ValueError: If Vocatron does not support the language.
    """
    if value not in LANGUAGES:
        supported = ", ".join(f"{code} ({language.name})" for code, language in LANGUAGES.items())
        raise ValueError(f"language {value!r} is not supported; supported: {supported}")
    return value


LanguageCode = Annotated[str, AfterValidator(_supported_language)]


class Settings(BaseModel):
    """Base of every configuration section: strict, with no unknown keys."""

    model_config = ConfigDict(extra="forbid")


class OutputSettings(Settings):
    """Where the results go (section ``output``).

    Attributes:
        folder: The output folder; finished tracks go here, the work folders of the songs below
            it. The default ``karaoke`` is inside the folder that holds the songs; the loader
            makes a folder from the file or the command line absolute (``vocatron.cli``).
    """

    folder: str = Field(default="karaoke", min_length=1)


DEFAULT_MODELS_FOLDER = ".cache/models"


class ModelsSettings(Settings):
    """Where the downloaded models are kept (section ``models``).

    Attributes:
        folder: The model folder. The default lies in the clone of Vocatron; the loader makes a
            folder from the file absolute against the folder of the file (``vocatron.cli``).
    """

    folder: str = Field(default=DEFAULT_MODELS_FOLDER, min_length=1)


class ProbeSettings(Settings):
    """Settings of the ``probe`` stage (section ``probe``).

    Attributes:
        min_duration: Songs shorter than this many seconds fail; real songs are far longer.
    """

    min_duration: float = Field(default=1.0, ge=0)


class LyricsSettings(Settings):
    """Settings of the ``lyrics`` stage (section ``lyrics``).

    Attributes:
        duet_pattern: A regular expression (any case); a song whose file name or title tag
            contains a match is a duet.
        lookup: Look the lyrics up online when no lyrics file lies next to the song.
        language: The language of every song (ISO 639-1 code, for example ``de``); ``None``
            detects it from the lyrics.
    """

    duet_pattern: RegularExpression = Field(default="duet(t)?", min_length=1)
    lookup: bool = True
    language: LanguageCode | None = None


def _vocals_model(value: str) -> str:
    """Require the name of a registered vocals and instrumental model.

    Raises:
        ValueError: If the model is not one of them.
    """
    if value not in VOCALS_MODELS:
        raise ValueError(
            f"model {value!r} is not a vocals model; known: {', '.join(VOCALS_MODELS)}"
        )
    return value


VocalsModel = Annotated[str, AfterValidator(_vocals_model)]


def _karaoke_model(value: str) -> str:
    """Require the name of a registered lead and backing vocals model.

    Raises:
        ValueError: If the model is not one of them.
    """
    if value not in KARAOKE_MODELS:
        raise ValueError(
            f"model {value!r} is not a karaoke model; known: {', '.join(KARAOKE_MODELS)}"
        )
    return value


KaraokeModel = Annotated[str, AfterValidator(_karaoke_model)]
ENSEMBLE_SIZE = 2
"""An ensemble averages the instrumentals of exactly this many models."""


def _distinct(value: list[str]) -> list[str]:
    """Require the models of an ensemble to differ (one model twice only doubles the runtime).

    Raises:
        ValueError: If a model appears twice.
    """
    if len(set(value)) != len(value):
        raise ValueError("the models of an ensemble must differ")
    return value


Ensemble = Annotated[
    list[VocalsModel],
    Field(min_length=ENSEMBLE_SIZE, max_length=ENSEMBLE_SIZE),
    AfterValidator(_distinct),
]


class SeparationSettings(Settings):
    """Settings of the ``separation`` stage (section ``separation``).

    Attributes:
        model: The registered model that separates the vocals from the instrumental, or a list of
            two whose instrumentals are averaged on the waveform (an ensemble; it costs the
            runtime of both).
        karaoke_model: The registered model that splits the vocals into lead and backing.
        karaoke_input: What the karaoke model gets: the ``vocals`` stem of the first model (today's
            order) or the full ``mix``. With ``mix`` the vocals model still runs, for the
            instrumental and backing stems.
        keep_backing: Keep the backing vocals in the karaoke track; ``False`` removes them too.
        voice_source: Where the loudness for the voice activity is measured: ``vocals`` (lead
            and backing vocals added, the default, so words the separation put into the backing
            are found) or ``lead`` (the lead vocals alone).
        device: ``auto`` (the GPU when at least 2 GiB are free, else the CPU), ``cuda`` or ``cpu``.
        timeout_factor_gpu: The worker may run this many song lengths plus two minutes on the GPU.
        timeout_factor_cpu: The same on the CPU.
    """

    model: VocalsModel | Ensemble = DEFAULT_VOCALS_MODEL
    karaoke_model: KaraokeModel = KARAOKE_MODEL
    karaoke_input: Literal["vocals", "mix"] = "vocals"
    keep_backing: bool = True
    device: DeviceRequest = "auto"
    timeout_factor_gpu: float = Field(default=2.0, gt=0)
    timeout_factor_cpu: float = Field(default=30.0, gt=0)

    @property
    def vocals_models(self) -> tuple[str, ...]:
        """The vocals models to run: the one of ``model``, or the two of an ensemble."""
        return (self.model,) if isinstance(self.model, str) else tuple(self.model)


class AlignmentSettings(Settings):
    """Settings of the ``alignment`` stage (section ``alignment``).

    Attributes:
        use_lrc_times: Use the line times of an ``.lrc`` as guide rails (after checking them
            against the singing); ``false`` aligns without them.
        voice_activity: Place words the model could not hear where the voice sounds in the
            separated vocals (ADR-0012), and end measured words where the voice stops
            (ADR-0013); ``false`` shares the time between the neighbouring words and ends
            words where the model last heard a letter.
        voice_source: Where the loudness for the voice activity is measured: ``vocals`` (lead
            and backing vocals added, the default) or ``lead`` (the lead vocals alone).
        hear_backing: Let the acoustic model also hear the backing vocals, where the lead is
            silent and the backing sounds, so words the separation put into the backing are
            measured (ADR-0014); ``false`` aligns on the lead vocals alone.
        device: ``auto`` (the GPU when at least 2 GiB are free, else the CPU), ``cuda`` or
            ``cpu``.
        timeout_factor_gpu: The acoustic model may run this many song lengths plus two minutes
            on the GPU.
        timeout_factor_cpu: The same on the CPU.
    """

    use_lrc_times: bool = True
    voice_activity: bool = True
    voice_source: Literal["lead", "vocals"] = "vocals"
    hear_backing: bool = True
    device: DeviceRequest = "auto"
    timeout_factor_gpu: float = Field(default=1.0, gt=0)
    timeout_factor_cpu: float = Field(default=15.0, gt=0)


class SyllablesSettings(Settings):
    """Settings of the ``syllables`` stage (section ``syllables``); it has none yet."""


class BatchSettings(Settings):
    """How a batch treats one song (section ``batch``); no stage depends on it.

    Attributes:
        time_limit_factor: A song may take this many song lengths in all stages together ...
        time_limit_base: ... plus this many seconds. A song that takes longer is stopped and
            ``failed`` with "time limit"; the batch goes on.
    """

    time_limit_factor: float = Field(default=10.0, gt=0)
    time_limit_base: float = Field(default=600.0, ge=0)


def _known_preset(value: str) -> str:
    """Require the name of an output preset (ADR-0009).

    Raises:
        ValueError: If there is no such preset.
    """
    if value not in PRESETS:
        raise ValueError(f"preset {value!r} is not known; known: {', '.join(PRESETS)}")
    return value


PresetName = Annotated[str, AfterValidator(_known_preset)]


OutputKind = Literal["mp4", "cdg"]
"""A product of a run: the karaoke video with its audio and LRC, or the CD+G pair (ADR-0023)."""


def _makes_the_video(value: list[OutputKind]) -> list[OutputKind]:
    """Require ``mp4`` in the list: the render stage also writes the LRC and the audio.

    Raises:
        ValueError: If the list has no ``mp4``.
    """
    if "mp4" not in value:
        raise ValueError("outputs must contain mp4 (a CD+G only run is not supported yet)")
    return value


Outputs = Annotated[list[OutputKind], AfterValidator(_makes_the_video)]


def _video_only() -> list[OutputKind]:
    """Return the default outputs: the video alone."""
    return ["mp4"]


class Config(Settings):
    """The whole configuration of Vocatron.

    Attributes:
        output: Output folder settings.
        models: Model folder settings.
        probe: Settings of the probe stage.
        lyrics: Settings of the lyrics stage.
        separation: Settings of the separation stage.
        alignment: Settings of the alignment stage.
        syllables: Settings of the syllables stage.
        batch: Safety limit of a song.
        profile: The style profile of the lyrics: the name of a built-in profile or the path
            of a YAML file (the ``layout`` stage).
        profile_overrides: Values that replace those of the profile, with the same keys.
        profiles_folder: A folder with own profiles (YAML files), chosen by file name like
            built-in ones; relative to the configuration file. None: no own profiles.
        preset: The output preset (frame size and video codec) of the ``render`` stage.
        audio: How the karaoke audio is encoded and exported (the ``render`` stage).
        outputs: What a run makes: ``mp4`` (the video, the audio export and the LRC), and ``cdg``
            to add ``Song.mp3`` and ``Song.cdg`` next to it (the ``cdg`` stage, ADR-0023). The
            list must contain ``mp4``.
        cdg_zip: Pack ``Song.mp3`` and ``Song.cdg`` into ``Song.zip`` instead of writing them
            loose (the ``cdg`` stage, ADR-0030). Only used when ``cdg`` is in ``outputs``.
    """

    output: OutputSettings = Field(default_factory=OutputSettings)
    models: ModelsSettings = Field(default_factory=ModelsSettings)
    probe: ProbeSettings = Field(default_factory=ProbeSettings)
    lyrics: LyricsSettings = Field(default_factory=LyricsSettings)
    separation: SeparationSettings = Field(default_factory=SeparationSettings)
    alignment: AlignmentSettings = Field(default_factory=AlignmentSettings)
    syllables: SyllablesSettings = Field(default_factory=SyllablesSettings)
    batch: BatchSettings = Field(default_factory=BatchSettings)
    profile: str = Field(default=DEFAULT_PROFILE, min_length=1)
    profile_overrides: dict[str, JsonValue] = Field(default_factory=dict)
    profiles_folder: str | None = Field(default=None, min_length=1)
    preset: PresetName = DEFAULT_PRESET
    audio: AudioSettings = Field(default_factory=AudioSettings)
    outputs: Outputs = Field(default_factory=_video_only)
    cdg_zip: bool = False
