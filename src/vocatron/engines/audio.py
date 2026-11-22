"""Decoding a song with ffmpeg: stereo 44.1 kHz for separation, mono 16 kHz for alignment."""

import subprocess
from pathlib import Path

import numpy as np

from vocatron.core.errors import StageError
from vocatron.core.separation.rules import CHANNELS, SAMPLE_RATE, Audio

DECODE_TIMEOUT = 600  # seconds; a hung ffmpeg must not hang the worker


class DecodeError(Exception):
    """ffmpeg could not decode the audio file."""


def _ffmpeg(command: list[str], data: bytes | None, what: str) -> bytes:
    """Run ffmpeg with ``data`` on its input and return its output.

    Raises:
        DecodeError: If ffmpeg is missing, fails or times out; ``what`` says what was attempted.
    """
    try:
        result = subprocess.run(
            command, input=data, capture_output=True, check=False, timeout=DECODE_TIMEOUT
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DecodeError(f"cannot run ffmpeg: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        raise DecodeError(f"ffmpeg could not {what}: {detail}")
    return result.stdout


def decode(path: str, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS) -> Audio:
    """Decode ``path`` to float32 audio shaped (channels, samples).

    Args:
        path: The audio file.
        sample_rate: The sample rate to resample to (44.1 kHz by default).
        channels: The number of channels to mix to (stereo by default).

    Raises:
        DecodeError: If ffmpeg is missing, fails or times out, or the file holds no audio.
    """
    command = [
        "ffmpeg", "-nostdin", "-v", "error", "-i", path, "-vn",
        "-ac", str(channels), "-ar", str(sample_rate), "-f", "f32le", "-",
    ]  # fmt: skip
    samples = np.frombuffer(_ffmpeg(command, None, f"decode {path}"), dtype="<f4")
    if samples.size == 0:
        raise DecodeError(f"{path} holds no audio")
    return np.ascontiguousarray(samples.reshape(-1, channels).T)


class FfmpegAudioReader:
    """Reads audio files with ffmpeg (``AudioReader``)."""

    def read(self, path: Path, sample_rate: int, channels: int) -> Audio:
        """Decode ``path`` to float32 samples shaped (channels, samples).

        Raises:
            StageError: ``decode-failed`` if ffmpeg cannot decode the file.
        """
        try:
            return decode(str(path), sample_rate, channels)
        except DecodeError as error:
            raise StageError("decode-failed", str(error)) from error
