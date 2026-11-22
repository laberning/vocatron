"""Output presets and the audio settings (ADR-0009).

A preset is the shape of the file: frame size, frame rate, video codec and its quality. It does
not say how the lyrics look; that is the style profile (``vocatron.core.profiles.model``). The
audio is encoded once (``AudioSettings``) and copied into the MP4.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VideoCodec = Literal["libx264", "libsvtav1", "h264_nvenc"]
AudioEncoder = Literal["fdkaac", "ffmpeg-aac"]
AudioExport = Literal["m4a", "flac", "none"]

DEFAULT_PRESET = "4x3-720"
DEFAULT_BITRATES: dict[AudioEncoder, int] = {"fdkaac": 192, "ffmpeg-aac": 256}
"""The audio bitrate in kbit/s of each encoder unless a setting says otherwise (ADR-0009)."""


class Preset(BaseModel):
    """One output preset.

    Attributes:
        name: The name used in the configuration and with ``--preset``.
        description: One line for the documentation and the error messages.
        width: Frame width in pixels.
        height: Frame height in pixels.
        fps: Frames per second.
        codec: The ffmpeg video encoder.
        quality: The constant-quality value of the encoder (CRF; CQ for NVENC); lower is better.
        speed: The encoder's speed setting (libx264 and SVT-AV1 ``-preset``, NVENC ``-preset``).
        audio_bitrate: The audio bitrate in kbit/s this preset asks for, or ``None`` for the
            encoder's default.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    codec: VideoCodec
    quality: int = Field(ge=0)
    speed: str
    audio_bitrate: int | None = None


PRESETS: dict[str, Preset] = {
    preset.name: preset
    for preset in (
        Preset(
            name="4x3-720",
            description="960x720 (4:3, as classic karaoke), H.264",
            width=960,
            height=720,
            fps=30,
            codec="libx264",
            quality=18,
            speed="medium",
        ),
        Preset(
            name="16x9-720",
            description="1280x720 (16:9), H.264",
            width=1280,
            height=720,
            fps=30,
            codec="libx264",
            quality=18,
            speed="medium",
        ),
        Preset(
            name="16x9-1080",
            description="1920x1080 (16:9), H.264",
            width=1920,
            height=1080,
            fps=30,
            codec="libx264",
            quality=18,
            speed="medium",
        ),
        Preset(
            name="av1-720",
            description="960x720 (4:3), AV1 with SVT-AV1 (opt-in; many players cannot play it)",
            width=960,
            height=720,
            fps=30,
            codec="libsvtav1",
            quality=30,
            speed="6",
        ),
        Preset(
            name="4x3-720-nvenc",
            description="960x720 (4:3), H.264 with NVENC (needs an NVIDIA GPU; faster)",
            width=960,
            height=720,
            fps=30,
            codec="h264_nvenc",
            quality=19,
            speed="p5",
        ),
    )
}


class AudioSettings(BaseModel):
    """How the karaoke audio is encoded and exported (section ``audio``).

    Attributes:
        encoder: ``fdkaac`` (the Fraunhofer FDK encoder, an external program; the default) or
            ``ffmpeg-aac`` (ffmpeg's own AAC). There is no automatic fallback (ADR-0009).
        bitrate: The bitrate in kbit/s, or ``None`` for the preset's or the encoder's default
            (192 for ``fdkaac``, 256 for ``ffmpeg-aac``).
        export: What is kept next to the video: ``none`` (nothing, the default), ``m4a`` (the
            encoded audio) or ``flac`` (the lossless karaoke audio) (ADR-0048).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    encoder: AudioEncoder = "fdkaac"
    bitrate: int | None = Field(default=None, gt=0, le=512)
    export: AudioExport = "none"


def audio_bitrate(audio: AudioSettings, preset: Preset) -> int:
    """Return the bitrate in kbit/s: the setting, else the preset's, else the encoder's default."""
    return audio.bitrate or preset.audio_bitrate or DEFAULT_BITRATES[audio.encoder]
