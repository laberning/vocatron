"""The ``vocatron`` command line application.

The help text of the application and of every command is taken from the docstrings of the
command functions (ADR-0003), so code documentation and user help have one source.
"""

import sys
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console

import vocatron
from vocatron.cli.commands import (
    Edges,
    run_doctor,
    run_lyrics,
    run_lyrics_approve,
    run_lyrics_show,
    run_make,
    run_models,
    run_models_download,
    run_profiles,
    run_profiles_check,
    run_profiles_copy,
    run_render,
    run_status,
)
from vocatron.cli.config_file import Overrides
from vocatron.cli.interrupt import stop_on_interrupt
from vocatron.core.separation.rules import DeviceRequest
from vocatron.engines.alignment.process import ProcessAcousticModel
from vocatron.engines.audio import FfmpegAudioReader
from vocatron.engines.clock import SystemClock
from vocatron.engines.downloader import Urllib3Downloader
from vocatron.engines.files import LocalFileStore
from vocatron.engines.language import LinguaDetector
from vocatron.engines.lrclib import LrclibSource
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.pack import ZipPacker
from vocatron.engines.raster import PillowRasteriser
from vocatron.engines.render import FfmpegRenderer
from vocatron.engines.resources import PackageResources
from vocatron.engines.separation.process import ProcessSeparator
from vocatron.engines.system import LocalSystemProbe
from vocatron.engines.tags import TinyTagReader
from vocatron.stages.batch import Options
from vocatron.stages.stage import Engines

app = App(name="vocatron", version=version("vocatron"))
models_app = App(name="models", help="List the AI models Vocatron uses, or download them.")
app.command(models_app)
lyrics_app = App(name="lyrics", help="Find, check and approve the lyrics of songs.")
app.command(lyrics_app)
profiles_app = App(
    name="profiles", help="List the style profiles, check an own profile or copy a built-in one."
)
app.command(profiles_app)

Language = Annotated[
    str | None,
    Parameter(help="Language of the songs (ISO 639-1 code, e.g. de); default: detected."),
]
ModelsLanguage = Annotated[
    str | None,
    Parameter(help="Also download what a song in this language needs (e.g. en); default: English."),
]
Device = Annotated[
    DeviceRequest | None,
    Parameter(help="Where the vocal separation runs: auto, cuda or cpu; default: auto."),
]
Output = Annotated[
    str | None,
    Parameter(help="Output folder; a relative path is relative to the current folder."),
]
Profile = Annotated[
    str | None,
    Parameter(help="Style profile: a built-in name or a YAML file; overrides profile."),
]
Preset = Annotated[
    str | None, Parameter(help="Output preset, for example 4x3-720; overrides preset.")
]
ConfigFile = Annotated[
    Path | None, Parameter(help="Configuration file; default: vocatron.yaml in the current folder.")
]


def clone_folder() -> Path:
    """Return the folder of the Vocatron clone (the package lives in ``<clone>/src/vocatron``)."""
    return Path(vocatron.__file__).resolve().parents[2]


def real_engines() -> Engines:
    """Return the real engines."""
    resources = PackageResources()
    renderer = FfmpegRenderer(resources.fonts_dir())
    return Engines(
        clock=SystemClock(),
        tags=TinyTagReader(),
        store=LocalFileStore(),
        downloader=Urllib3Downloader(),
        lyrics=LrclibSource(),
        language=LinguaDetector(),
        separator=ProcessSeparator(),
        acoustic=ProcessAcousticModel(),
        measurer=PillowMeasurer(resources.font_file()),
        rasteriser=PillowRasteriser(resources.font_file()),
        renderer=renderer,
        mp3=renderer,
        packer=ZipPacker(),
        resources=resources,
        audio=FfmpegAudioReader(),
    )


def real_edges() -> Edges:
    """Wire in the real engines and the real console."""
    return Edges(
        engines=real_engines(),
        console=Console(),
        error_console=Console(stderr=True),
        cwd=Path.cwd(),
        probe=LocalSystemProbe(),
        clone=clone_folder(),
    )


@app.default
def overview() -> None:
    """Turn a song and its lyrics into a karaoke track, locally.

    Vocatron does this with as little manual work as possible. Without a command it shows this
    help.
    """
    app.help_print()


@app.command
def make(  # noqa: PLR0913  # cyclopts needs one parameter per command-line option
    path: Path,
    *,
    output: Output = None,
    config: ConfigFile = None,
    force: bool = False,
    offline: bool = False,
    language: Language = None,
    no_backing: bool = False,
    device: Device = None,
    profile: Profile = None,
    preset: Preset = None,
    cdg: bool = False,
    log: bool = False,
) -> int:
    """Run the pipeline on a song or on every song of a folder.

    Only the audio files directly in a folder are used. Results go to the output folder
    (default: karaoke/ next to the songs), one work folder per song below it. Stages whose inputs
    and settings did not change are skipped.

    Args:
        path: An audio file, or a folder with audio files.
        output: Output folder; a relative path is relative to the current folder.
        config: Configuration file; default: vocatron.yaml in the current folder.
        force: Run every stage again, even if its output is current.
        offline: Never download models; a stage whose models are missing fails with the command
            that fetches them.
        language: Language of the songs (ISO 639-1 code, for example de) instead of the one
            detected from the lyrics; overrides lyrics.language.
        no_backing: Take the backing vocals out of the karaoke track too; overrides
            separation.keep_backing.
        device: Where the vocal separation runs: auto (the GPU when at least 2 GiB of its memory
            are free, else the CPU), cuda or cpu; overrides separation.device.
        profile: Style profile: the name of a built-in profile or a YAML file; overrides profile.
        preset: Output preset (4x3-720, 16x9-720, 16x9-1080, av1-720 or 4x3-720-nvenc); overrides
            preset.
        cdg: Also make Song.mp3 and Song.cdg for this run; adds cdg to outputs.
        log: Show the log of each song as it is written instead of the live progress display.
    """
    edges = replace(real_edges(), log=log)
    with stop_on_interrupt(edges.stop, edges.error_console):
        return run_make(
            path.resolve(),
            output=output,
            config_file=config,
            options=Options(force=force, offline=offline),
            overrides=Overrides(
                language=language,
                keep_backing=False if no_backing else None,
                device=device,
                profile=profile,
                preset=preset,
                cdg=cdg,
            ),
            edges=edges,
        )


@app.command
def render(  # cyclopts needs one parameter per command-line option
    path: Path,
    *,
    output: Output = None,
    config: ConfigFile = None,
    force: bool = False,
    profile: Profile = None,
    preset: Preset = None,
) -> int:
    """Render the video again from the work folder of a song, without the AI stages.

    Runs only the layout and the render, so a new style profile or output preset takes seconds
    for the layout and about the length of the song for the video. The song must have been made
    with `vocatron make` before.

    Args:
        path: An audio file, or a folder with audio files.
        output: Output folder; a relative path is relative to the current folder.
        config: Configuration file; default: vocatron.yaml in the current folder.
        force: Render again even if nothing changed.
        profile: Style profile: the name of a built-in profile or a YAML file; overrides profile.
        preset: Output preset (4x3-720, 16x9-720, 16x9-1080, av1-720 or 4x3-720-nvenc); overrides
            preset.
    """
    edges = real_edges()
    with stop_on_interrupt(edges.stop, edges.error_console):
        return run_render(
            path.resolve(),
            output=output,
            config_file=config,
            force=force,
            overrides=Overrides(profile=profile, preset=preset),
            edges=edges,
        )


@app.command
def status(path: Path, *, output: Output = None, config: ConfigFile = None) -> int:
    """Show the stored status of a song or of every song of a folder, without running anything.

    Args:
        path: An audio file, or a folder with audio files.
        output: Output folder; a relative path is relative to the current folder.
        config: Configuration file; default: vocatron.yaml in the current folder.
    """
    return run_status(path.resolve(), output=output, config_file=config, edges=real_edges())


@models_app.default
def models(*, config: ConfigFile = None) -> int:
    """List the models with their state, size and licence.

    Args:
        config: Configuration file; default: vocatron.yaml in the current folder.
    """
    return run_models(config_file=config, edges=real_edges())


@models_app.command(name="download")
def models_download(*names: str, language: ModelsLanguage = None, config: ConfigFile = None) -> int:
    """Download models into the model folder and verify their checksums.

    Without names and without a language, downloads what an English song needs. A download that
    was cut off is resumed.

    Args:
        names: Names of the models to download, as `vocatron models` lists them.
        language: Download what a song in this language needs (ISO 639-1 code, e.g. en).
        config: Configuration file; default: vocatron.yaml in the current folder.
    """
    return run_models_download(
        list(names), language=language, config_file=config, edges=real_edges()
    )


@profiles_app.default
def profiles(*, config: ConfigFile = None) -> int:
    """List the built-in and own style profiles, and mark the one the configuration chooses.

    Own profiles are the YAML files in the folder that `profiles_folder` names. A file that does
    not load is listed as invalid; `vocatron profiles check` tells why.

    Args:
        config: Configuration file; default: vocatron.yaml in the current folder.
    """
    return run_profiles(config_file=config, edges=real_edges())


@profiles_app.command(name="check")
def profiles_check(profile: str, *, config: ConfigFile = None) -> int:
    """Check a profile without rendering: it loads, fits the screen and keeps the layout rules.

    Applies the `profile_overrides` of the configuration first. Prints problems as
    `file:line:column: message`, or `ok`. Exit code 0 when fine, 1 on problems, 2 on a
    configuration or usage error.

    Args:
        profile: The name of a built-in or own profile, or the path of a YAML file.
        config: Configuration file; default: vocatron.yaml in the current folder.
    """
    return run_profiles_check(profile, config_file=config, edges=real_edges())


@profiles_app.command(name="copy")
def profiles_copy(source: str, target: str | None = None, *, config: ConfigFile = None) -> int:
    """Write an editable copy of a built-in profile, to change it and make an own look.

    A bare name goes into the folder `profiles_folder` names; a path (relative to the current
    folder) is used as it is. Without a target the copy is called my-<source>. A file that
    exists is never overwritten.

    Args:
        source: The name of the built-in profile to copy.
        target: The name of the copy, or the path of its file; default: my-<source>.
        config: Configuration file; default: vocatron.yaml in the current folder.
    """
    return run_profiles_copy(
        source, target, config_file=config, version=version("vocatron"), edges=real_edges()
    )


@app.command
def doctor(*, output: Output = None, config: ConfigFile = None) -> int:
    """Check that this machine is ready: ffmpeg, PyTorch and the GPU, the models, the output folder.

    Prints one line per check and what to fix. Exit code 1 when something needs fixing.

    Args:
        output: Output folder to check; a relative path is relative to the current folder.
        config: Configuration file; default: vocatron.yaml in the current folder.
    """
    return run_doctor(output=output, config_file=config, edges=real_edges())


@lyrics_app.default
def lyrics(
    path: Path,
    *,
    output: Output = None,
    config: ConfigFile = None,
    force: bool = False,
    language: Language = None,
) -> int:
    """Find and check the lyrics of a song or of every song of a folder (probe and lyrics only).

    Uses a Song.lrc or Song.txt next to the song; otherwise looks the lyrics up and writes them
    next to the song. Prints one line per song with its status.

    Args:
        path: An audio file, or a folder with audio files.
        output: Output folder; a relative path is relative to the current folder.
        config: Configuration file; default: vocatron.yaml in the current folder.
        force: Run both stages again, even if their output is current.
        language: Language of the songs (ISO 639-1 code, for example de) instead of the one
            detected from the lyrics; overrides lyrics.language.
    """
    return run_lyrics(
        path.resolve(),
        output=output,
        config_file=config,
        force=force,
        language=language,
        edges=real_edges(),
    )


@lyrics_app.command
def show(path: Path, *, output: Output = None, config: ConfigFile = None) -> int:
    """Print the lyrics status, the reasons for review and the flagged lines of each song.

    Args:
        path: An audio file, or a folder with audio files.
        output: Output folder; a relative path is relative to the current folder.
        config: Configuration file; default: vocatron.yaml in the current folder.
    """
    return run_lyrics_show(path.resolve(), output=output, config_file=config, edges=real_edges())


@lyrics_app.command
def approve(
    path: Path, *, output: Output = None, config: ConfigFile = None, language: Language = None
) -> int:
    """Approve the lyrics file next to each song as it is now.

    A lyrics file you edited counts as approved by itself; this is for a file you checked and left
    unchanged.

    Args:
        path: An audio file, or a folder with audio files.
        output: Output folder; a relative path is relative to the current folder.
        config: Configuration file; default: vocatron.yaml in the current folder.
        language: The language the lyrics were checked with, as for vocatron lyrics.
    """
    return run_lyrics_approve(
        path.resolve(), output=output, config_file=config, language=language, edges=real_edges()
    )


def main() -> None:
    """Run the ``vocatron`` command line."""
    app(sys.argv[1:])
