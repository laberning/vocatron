"""Reading stems back, measuring how close two signals are, and a reader of canned audio."""

from pathlib import Path

import numpy as np
import soundfile as sf

from vocatron.core.errors import StageError
from vocatron.core.separation.rules import CHANNELS, SAMPLE_RATE, Audio


def read_audio(path: Path) -> Audio:
    """Read an audio file (FLAC or WAV) as (channels, samples) float32."""
    data, _ = sf.read(path, dtype="float32", always_2d=True)
    return np.ascontiguousarray(data.T, dtype=np.float32)


def sdr_db(reference: Audio, estimate: Audio) -> float:
    """Return the signal-to-distortion ratio of ``estimate`` against ``reference`` in dB."""
    n = min(reference.shape[-1], estimate.shape[-1])
    ref = reference[..., :n].astype(np.float64)
    est = estimate[..., :n].astype(np.float64)
    return float(10 * np.log10(np.sum(ref**2) / max(np.sum((ref - est) ** 2), 1e-12)))


def decode_file(path: str, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS) -> Audio:
    """Stand in for ``engines.audio.decode`` without ffmpeg: read the file with soundfile.

    The made-up files of the fast tests are written at the rate and channel count asked for, so
    nothing is resampled; another rate is a mistake in the test and fails loudly. A mono request
    averages the channels, as ffmpeg's ``-ac 1`` does.
    """
    data, rate = sf.read(path, dtype="float32", always_2d=True)
    assert rate == sample_rate, f"{path}: written at {rate} Hz, decoded at {sample_rate} Hz"
    if channels == 1:
        data = data.mean(axis=1, keepdims=True)
    assert data.shape[1] == channels, f"{path}: {data.shape[1]} channels, {channels} asked for"
    return np.ascontiguousarray(data.T, dtype=np.float32)


class FakeAudioReader:
    """An ``AudioReader`` that hands out canned mono samples instead of decoding files.

    ``samples`` is what every file "contains": silence of one second unless a test sets it, and
    ``fail_with`` makes every read fail like an undecodable file.
    """

    def __init__(self) -> None:
        self.samples: Audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
        self.fail_with: StageError | None = None
        self.requests: list[tuple[Path, int, int]] = []

    def read(self, path: Path, sample_rate: int, channels: int) -> Audio:
        self.requests.append((path, sample_rate, channels))
        if self.fail_with is not None:
            raise self.fail_with
        return np.tile(self.samples, (channels, 1))
