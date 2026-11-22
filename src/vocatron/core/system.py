"""Pure judgements about the machine: ffmpeg, encoders, PyTorch and the GPU (ADR-0002).

The engines read the facts (command output, the GPU through PyTorch); this module decides what
they mean. ``vocatron doctor`` and ``tools/check_system.py`` share it.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from vocatron.core.models import State
from vocatron.core.separation.rules import CPU_SLOWDOWN

MIN_FFMPEG_MAJOR = 8
MIN_VRAM_GIB = 6
"""The total GPU memory a machine needs. The trials of ADR-0002 peaked at 3.0 GiB (wav2vec2 on a
198-second song), which needs 4 GiB under the 75 % cap; longer songs need more. This judges the
machine; how much memory is free is a question for the stage that uses the GPU, when it runs."""
DEFAULT_VIDEO_ENCODER = "libx264"
AUDIO_ENCODER = "aac"
MP3_ENCODER = "libmp3lame"
"""The MP3 encoder of the CD+G pair (ADR-0024)."""
FDKAAC = "fdkaac"
GIB = 1 << 30


@dataclass(frozen=True)
class TorchInfo:
    """What PyTorch reports about the machine.

    Attributes:
        version: The PyTorch version string.
        cuda_version: The CUDA version PyTorch was built for, or ``None`` for a CPU build.
        gpu_name: The name of the first GPU, or ``None`` when CUDA finds none.
        vram_bytes: Its total memory in bytes, or ``None``.
    """

    version: str
    cuda_version: str | None
    gpu_name: str | None
    vram_bytes: int | None


@dataclass(frozen=True)
class Check:
    """The result of one ``doctor`` check.

    Attributes:
        name: What was checked.
        detail: What was found (also when everything is fine).
        fix: What to do about it, or ``None`` when the check passed.
        warning: Something to know that does not stop Vocatron from working; the check still
            passes.
    """

    name: str
    detail: str
    fix: str | None = None
    warning: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the check passed (a warning does not fail it)."""
        return self.fix is None


def ffmpeg_missing_problem() -> str:
    """Return the message for an ffmpeg that is not installed."""
    return (
        f"ffmpeg {MIN_FFMPEG_MAJOR} or newer with libass is not installed "
        "(or not on PATH). Install it with your package manager, for example "
        "'sudo apt install ffmpeg' or 'brew install ffmpeg'."
    )


def version_problems(version_output: str) -> list[str]:
    """Judge the version in the output of ``ffmpeg -version``."""
    match = re.search(r"ffmpeg version (?:n?(\d+)|N-\d+)", version_output)
    if match is None:
        return [
            "Could not read the ffmpeg version from 'ffmpeg -version'; "
            f"version {MIN_FFMPEG_MAJOR} or newer is required."
        ]
    if match.group(1) is not None and int(match.group(1)) < MIN_FFMPEG_MAJOR:  # N-: git build
        return [
            f"ffmpeg {match.group(1)} is too old; version {MIN_FFMPEG_MAJOR} or newer is required."
        ]
    return []


def libass_problems(version_output: str) -> list[str]:
    """Judge whether the build in the output of ``ffmpeg -version`` has libass."""
    if "--enable-libass" in version_output:
        return []
    return [
        "This ffmpeg was built without libass, which is needed to render subtitles. "
        "Install a build with libass (most distribution packages have it)."
    ]


def ffmpeg_problems(version_output: str | None) -> list[str]:
    """Judge the output of ``ffmpeg -version``.

    Args:
        version_output: Standard output of ``ffmpeg -version``, or ``None`` when ffmpeg is not
            installed.

    Returns:
        One message per problem; empty when ffmpeg is usable.
    """
    if version_output is None:
        return [ffmpeg_missing_problem()]
    return version_problems(version_output) + libass_problems(version_output)


def ffmpeg_version_text(version_output: str) -> str:
    """Return the version token of ``ffmpeg -version`` (``8.0.1``), or ``unknown``."""
    match = re.search(r"ffmpeg version (\S+)", version_output)
    return match.group(1) if match else "unknown"


def encoder_names(encoders_output: str) -> set[str]:
    """Return the encoder names listed by ``ffmpeg -encoders``."""
    return set(re.findall(r"^\s*[VAS][.\w]{5}\s+(\S+)", encoders_output, flags=re.MULTILINE))


def _wanted_encoders(video: str, *, needs_aac: bool, needs_mp3: bool) -> list[str]:
    """Return the ffmpeg encoders the configuration needs, the video encoder first."""
    return [
        video,
        *([AUDIO_ENCODER] if needs_aac else []),
        *([MP3_ENCODER] if needs_mp3 else []),
    ]


def encoder_problems(
    encoders_output: str | None,
    video: str = DEFAULT_VIDEO_ENCODER,
    *,
    needs_aac: bool = False,
    needs_mp3: bool = False,
) -> list[str]:
    """Judge the output of ``ffmpeg -encoders``.

    Args:
        encoders_output: The output, or ``None`` when it could not be read.
        video: The video encoder the output preset uses (``libx264`` unless the preset asks for
            another).
        needs_aac: ffmpeg's own AAC encoder is needed (``audio.encoder: ffmpeg-aac``).
        needs_mp3: LAME is needed for the MP3 of the CD+G pair (``cdg`` in ``outputs``).
    """
    if encoders_output is None:
        return ["Could not list the ffmpeg encoders."]
    names = encoder_names(encoders_output)
    problems: list[str] = []
    if video not in names:
        problems.append(f"ffmpeg has no {video} encoder. Install an ffmpeg build with {video}.")
    if needs_aac and AUDIO_ENCODER not in names:
        problems.append(f"ffmpeg has no {AUDIO_ENCODER} encoder. Install a full ffmpeg build.")
    if needs_mp3 and MP3_ENCODER not in names:
        problems.append(
            f"ffmpeg has no {MP3_ENCODER} encoder, which CD+G needs. "
            "Install an ffmpeg build with libmp3lame."
        )
    return problems


def torch_problems(info: TorchInfo | None) -> list[str]:
    """Judge PyTorch and the GPU; ``None`` means PyTorch cannot be imported."""
    if info is None:
        return ["PyTorch is not installed. Run 'make setup' (or 'make env')."]
    if info.gpu_name is None or info.vram_bytes is None:
        if info.cuda_version is None:
            return [
                "PyTorch finds no CUDA GPU (this is a CPU build of PyTorch).",
                "On a machine with an NVIDIA GPU and its driver, run 'make env TORCH_EXTRA=cuda'.",
            ]
        return [
            "PyTorch finds no CUDA GPU.",
            "Install the NVIDIA driver, or run on a machine with an NVIDIA GPU.",
        ]
    if info.vram_bytes < MIN_VRAM_GIB * GIB:
        return [
            f"The GPU has {info.vram_bytes / GIB:.1f} GiB of memory; "
            f"at least {MIN_VRAM_GIB} GiB are needed."
        ]
    return []


def _fix(problems: list[str]) -> str | None:
    """Join the problems into the text of a fix, or ``None`` when there are none."""
    return " ".join(problems) or None


def ffmpeg_checks(
    version_output: str | None,
    encoders_output: str | None,
    video: str = DEFAULT_VIDEO_ENCODER,
    *,
    needs_aac: bool = False,
    needs_mp3: bool = False,
) -> list[Check]:
    """Build the ffmpeg, libass and encoder checks (the arguments as for ``encoder_problems``)."""
    if version_output is None:
        fix = ffmpeg_missing_problem()
        return [
            Check("ffmpeg", "not found", fix),
            Check("libass", "unknown without ffmpeg", fix),
            Check("encoders", "unknown without ffmpeg", fix),
        ]
    version = version_problems(version_output)
    libass = libass_problems(version_output)
    encoders = encoder_problems(encoders_output, video, needs_aac=needs_aac, needs_mp3=needs_mp3)
    wanted = " and ".join(_wanted_encoders(video, needs_aac=needs_aac, needs_mp3=needs_mp3))
    return [
        Check("ffmpeg", f"version {ffmpeg_version_text(version_output)}", _fix(version)),
        Check("libass", "not built in" if libass else "built in", _fix(libass)),
        Check("encoders", "incomplete" if encoders else wanted, _fix(encoders)),
    ]


def fdkaac_check(first_line: str | None, encoder: str) -> Check:
    """Build the ``fdkaac`` check.

    Args:
        first_line: The first line of the program's help (it names the version), or ``None``
            when it is not installed.
        encoder: The configured ``audio.encoder``; only ``fdkaac`` needs the program.
    """
    if encoder != FDKAAC:
        return Check(FDKAAC, f"not needed (audio.encoder is {encoder})")
    if first_line is None:
        return Check(
            FDKAAC,
            "not found",
            "Install fdkaac (for example 'sudo apt install fdkaac' or 'brew install fdk-aac'), "
            "or set audio.encoder to ffmpeg-aac to use ffmpeg's own AAC encoder.",
        )
    return Check(FDKAAC, first_line.strip())


def torch_checks(info: TorchInfo | None) -> list[Check]:
    """Build the PyTorch and GPU checks."""
    problems = torch_problems(info)
    if info is None:
        return [Check("PyTorch", "not installed", _fix(problems))]
    torch_check = Check("PyTorch", f"{info.version}, CUDA {info.cuda_version or 'none'}")
    warning = _fix(problems)
    if warning is not None:
        warning += f" Otherwise the separation runs on the CPU, about {CPU_SLOWDOWN} times slower."
    if info.gpu_name is None or info.vram_bytes is None:
        return [torch_check, Check("GPU", "none found", warning=warning)]
    detail = f"{info.gpu_name}, {info.vram_bytes / GIB:.1f} GiB"
    return [torch_check, Check("GPU", detail, warning=warning)]


def models_check(states: Mapping[str, State]) -> Check:
    """Build the models check from the state of each model a song of the language needs."""
    bad = {name: state for name, state in states.items() if state != "present"}
    if not bad:
        return Check("models", f"{len(states)} of {len(states)} present")
    names = " ".join(bad)
    listing = ", ".join(f"{name} ({state})" for name, state in bad.items())
    return Check(
        "models",
        f"{len(states) - len(bad)} of {len(states)} present; {listing}",
        f"Run 'vocatron models download {names}'.",
    )


def output_check(folder: Path, *, writable: bool) -> Check:
    """Build the output folder check; ``writable`` says whether it can be created and written."""
    if writable:
        return Check("output folder", str(folder))
    return Check(
        "output folder",
        f"{folder} cannot be written",
        "Choose another folder with --output or output.folder, or fix its permissions.",
    )
