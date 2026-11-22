"""Reads facts about the machine: ffmpeg through its command line, the GPU through PyTorch."""

import shutil
import subprocess
import warnings

from vocatron.core.system import TorchInfo

COMMAND_TIMEOUT = 30  # seconds; a broken binary must not hang the command


def run_ffmpeg(*args: str) -> str | None:
    """Run ffmpeg with ``args``; return its output, or ``None`` if it cannot be run."""
    path = shutil.which("ffmpeg")
    if path is None:
        return None
    try:
        result = subprocess.run(
            [path, *args], capture_output=True, text=True, check=True, timeout=COMMAND_TIMEOUT
        )
    except OSError, subprocess.SubprocessError:
        return None
    return result.stdout


class LocalSystemProbe:
    """The real machine."""

    def ffmpeg_version(self) -> str | None:
        """Return the output of ``ffmpeg -version``, or ``None`` if ffmpeg cannot be run."""
        return run_ffmpeg("-version")

    def ffmpeg_encoders(self) -> str | None:
        """Return the output of ``ffmpeg -encoders``, or ``None`` if it cannot be run."""
        return run_ffmpeg("-hide_banner", "-encoders")

    def fdkaac_version(self) -> str | None:
        """Return the first line of ``fdkaac --help``, or ``None`` if it cannot be run."""
        path = shutil.which("fdkaac")
        if path is None:
            return None
        try:
            result = subprocess.run(
                [path, "--help"],
                capture_output=True,
                text=True,
                check=False,
                timeout=COMMAND_TIMEOUT,
            )
        except OSError, subprocess.SubprocessError:
            return None
        lines = (result.stdout + result.stderr).strip().splitlines()
        return lines[0] if lines else None

    def torch_info(self) -> TorchInfo | None:
        """Return version, CUDA version, GPU name and VRAM from PyTorch (imported here, lazily)."""
        try:
            with warnings.catch_warnings():
                # PyTorch warns when NumPy is absent; Vocatron adds NumPy with the first stage that
                # needs it, and the machine check does not use it.
                warnings.filterwarnings("ignore", message="Failed to initialize NumPy")
                import torch  # noqa: PLC0415  # heavy import, only when the machine is asked
        except ImportError:
            return None
        gpu_name: str | None = None
        vram: int | None = None
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram = int(torch.cuda.get_device_properties(0).total_memory)
        return TorchInfo(
            version=str(torch.__version__),
            cuda_version=torch.version.cuda,
            gpu_name=gpu_name,
            vram_bytes=vram,
        )
