"""The ``doctor`` checks: ffmpeg, PyTorch and the GPU, the models, the output folder."""

from pathlib import Path

from vocatron.core.models import DOWNLOAD_LANGUAGE, find_model, language_models
from vocatron.core.presets import PRESETS
from vocatron.core.system import (
    Check,
    fdkaac_check,
    ffmpeg_checks,
    models_check,
    output_check,
    torch_checks,
)
from vocatron.engines.protocols import FileStore, SystemProbe
from vocatron.stages.config import Config
from vocatron.stages.models import ModelFolder


def run_checks(
    probe: SystemProbe,
    store: FileStore,
    models: ModelFolder,
    output_folder: Path,
    config: Config,
) -> list[Check]:
    """Run every check and return the results in the order they are shown.

    Args:
        probe: Reads ffmpeg and the GPU.
        store: Tells whether the output folder can be written.
        models: The model folder; the checksums of the models of a song in the configured
            language are verified; without one, those ``vocatron models download`` fetches
            (``DOWNLOAD_LANGUAGE``).
        output_folder: The output folder to check (``--output`` or ``output.folder``; the default
            is taken in the current folder, since ``doctor`` has no songs).
        config: The configuration: its preset names the video encoder to look for, and
            ``audio.encoder`` says whether ``fdkaac`` or ffmpeg's AAC is needed, and ``outputs``
            whether LAME is (CD+G).
    """
    encoder = config.audio.encoder
    needed = language_models(config.lyrics.language or DOWNLOAD_LANGUAGE)
    states = {name: models.state(find_model(name), verify=True) for name in needed}
    return [
        *ffmpeg_checks(
            probe.ffmpeg_version(),
            probe.ffmpeg_encoders(),
            PRESETS[config.preset].codec,
            needs_aac=encoder == "ffmpeg-aac",
            needs_mp3="cdg" in config.outputs,
        ),
        fdkaac_check(probe.fdkaac_version(), encoder),
        *torch_checks(probe.torch_info()),
        models_check(states),
        output_check(output_folder, writable=store.writable(output_folder)),
    ]
