"""A system probe with canned answers."""

from vocatron.core.system import TorchInfo

GOOD_FFMPEG = """ffmpeg version 8.0.1-3ubuntu2 Copyright (c) 2000-2025 the FFmpeg developers
built with gcc 15
configuration: --prefix=/usr --enable-gpl --enable-libass --enable-libx264
"""
GOOD_ENCODERS = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC (codec h264)
 A....D aac                  AAC (Advanced Audio Coding)
 A....D libmp3lame           libmp3lame MP3 (MPEG audio layer 3) (codec mp3)
"""
GOOD_FDKAAC = "fdkaac 1.0.0"
GOOD_TORCH = TorchInfo("2.14.1+cu130", "13.0", "Fake GPU 8000", 8 * 1024**3)


class FakeSystemProbe:
    """Answers with what the test set; the defaults describe a healthy machine."""

    def __init__(self) -> None:
        self.version: str | None = GOOD_FFMPEG
        self.encoders: str | None = GOOD_ENCODERS
        self.torch: TorchInfo | None = GOOD_TORCH
        self.fdkaac: str | None = GOOD_FDKAAC

    def ffmpeg_version(self) -> str | None:
        return self.version

    def ffmpeg_encoders(self) -> str | None:
        return self.encoders

    def torch_info(self) -> TorchInfo | None:
        return self.torch

    def fdkaac_version(self) -> str | None:
        return self.fdkaac
