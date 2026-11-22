"""Pictures of a look on CD+G: the song of the look pictures, written and decoded (ADR-0029).

The song of ``vocatron.core.profiles.picture`` is laid out in the CD+G profile of the look,
written with ``fit_stream`` and read back with our own decoder at the six moments of the
picture. The frames are pixel-exact (palette entries, no scaling), so the golden frames of the
tests and the pictures of the user docs come from the same function.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vocatron.core.cdg.decode import decode
from vocatron.core.cdg.fit import Fit, fit_stream
from vocatron.core.cdg.packet import PACKETS_PER_SECOND
from vocatron.core.cdg.raster import TICKS_PER_SECOND
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.measure import TextMeasurer, TextRasteriser
from vocatron.core.profiles.model import Profile, digest_json
from vocatron.core.profiles.picture import (
    Moment,
    PictureSong,
    digest_of,
    picture_moments,
    picture_text,
)

type Rgb = NDArray[np.uint8]

CHANNEL_SCALE = 17
"""A 4-bit channel value as an 8-bit one."""


@dataclass(frozen=True)
class CdgPicture:
    """The picture song of a look written for CD+G and decoded at six moments.

    Attributes:
        fit: The song as the stage writes it (step, stream, scene).
        moments: The six moments, moved to where the screen is settled.
        frames: The decoded frames (216 by 300 by 3, RGB), one per moment.
    """

    fit: Fit
    moments: list[Moment]
    frames: list[Rgb]


def rgb_frames(stream: bytes, times: Sequence[float]) -> list[Rgb]:
    """Decode ``stream`` with our decoder and return the RGB frame after each of ``times``.

    Each frame is shown in the palette in force at its time (a stream may replace its palette,
    ADR-0056).
    """
    decoded = decode(stream, list(times))
    return [
        np.array(palette, dtype=np.uint8)[frame] * CHANNEL_SCALE
        for frame, palette in zip(decoded.frames, decoded.palettes, strict=True)
    ]


def settled_after(fit: Fit, seconds: float) -> float:
    """Return the first time at or after ``seconds`` when the screen shows its target frame.

    A picture should not catch the writer half way through a line. If the screen never settles
    after ``seconds``, ``seconds`` itself is returned.
    """
    tick = int(seconds * TICKS_PER_SECOND)
    later = next((k for k in fit.written.scheduled.settled if k >= tick), None)
    return seconds if later is None else (later + 1) / TICKS_PER_SECOND - 1 / PACKETS_PER_SECOND


def cdg_picture(
    song: PictureSong, profile: Profile, measurer: TextMeasurer, rasteriser: TextRasteriser
) -> CdgPicture:
    """Write the picture song in the CD+G profile of ``profile`` and decode its six moments.

    Raises:
        StageError: ``cdg-palette`` if the look needs more than 16 colours.
        ValueError: If the profile has no ``cdg`` section.
    """
    phrases = phrases_from(song.words, song.lines, profile.font.case)
    fit = fit_stream(phrases, picture_text(song), profile, measurer, rasteriser)
    moments = [
        Moment(moment.name, round(settled_after(fit, moment.seconds), 3))
        for moment in picture_moments(fit.scene, fit.profile)
    ]
    frames = rgb_frames(fit.written.stream, [moment.seconds for moment in moments])
    return CdgPicture(fit, moments, frames)


def cdg_picture_digest(*, tool_version: int, picture: CdgPicture, font_sha256: str) -> str:
    """Return the digest of everything a CD+G picture is drawn from.

    It covers the inputs (the CD+G profile of the step taken, the whole scene with the singers and
    colours of each line and the start screen, the moments, the font) and not the pixels, which
    FreeType may shade differently on another machine; the golden frames of the tests allow for
    that.
    """
    fit = picture.fit
    return digest_of(
        {
            "tool": tool_version,
            "profile": digest_json(fit.profile),
            "step": fit.step.number,
            "scene": fit.scene.model_dump_json(),
            "moments": [(m.name, m.seconds) for m in picture.moments],
            "font": font_sha256,
        }
    )
