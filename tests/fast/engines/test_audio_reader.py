"""Stage 1: the ffmpeg audio reader of the work folder."""

import wave
from pathlib import Path

import numpy as np
import pytest

from fakes.audio import FakeAudioReader
from fakes.songs import write_wav
from vocatron.core.errors import StageError
from vocatron.engines.audio import FfmpegAudioReader
from vocatron.engines.protocols import AudioReader


def test_a_file_is_read_at_the_rate_and_channels_asked_for(tmp_path: Path) -> None:
    audio = FfmpegAudioReader().read(write_wav(tmp_path / "a.wav", 1.0, 8000), 4000, 1)
    assert audio.dtype == np.float32
    assert audio.shape[0] == 1
    assert abs(audio.shape[1] - 4000) <= 2


def test_a_file_that_cannot_be_decoded_is_a_stage_error(tmp_path: Path) -> None:
    with pytest.raises(StageError) as error:
        FfmpegAudioReader().read(tmp_path / "missing.flac", 22050, 1)
    assert error.value.kind == "decode-failed"
    empty = tmp_path / "empty.wav"
    with wave.open(str(empty), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(8000)
    with pytest.raises(StageError, match="holds no audio"):
        FfmpegAudioReader().read(empty, 22050, 1)


def test_the_real_reader_and_the_fake_both_satisfy_the_protocol() -> None:
    readers: list[AudioReader] = [FfmpegAudioReader(), FakeAudioReader()]
    assert len(readers) == 2


def test_the_fake_hands_out_its_samples_in_the_channels_asked_for() -> None:
    fake = FakeAudioReader()
    fake.samples = np.ones(10, dtype=np.float32)
    assert fake.read(Path("x.flac"), 22050, 2).shape == (2, 10)
    assert fake.requests == [(Path("x.flac"), 22050, 2)]
    fake.fail_with = StageError("decode-failed", "no")
    with pytest.raises(StageError):
        fake.read(Path("x.flac"), 22050, 1)
