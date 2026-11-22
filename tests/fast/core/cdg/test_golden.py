"""Stage 1: golden pictures of every classic look on CD+G at six moments of a made-up duet.

The song is twelve invented lines of two singers and a group with a long break
(``fakes.picture_song``), laid out in the CD+G profile of the look and drawn in the bundled font by
Pillow. The frames come out of our own decoder, which reads the packets back, at the six moments of
the picture (the title screen, a line sung together, a line or page change, the break screen, the
countdown, the end screen), each moved to where the screen is settled (ADR-0029). A golden
picture is 300 by 216 pixels in the palette's colours; ``VOCATRON_UPDATE_GOLDEN=1`` writes them
again (a deliberate act, and the pictures are looked at before they are committed).
"""

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fakes.picture_song import made_up_song
from fakes.resources import FakeResources
from vocatron.core.cdg.fit import fit_stream
from vocatron.core.cdg.picture import CdgPicture, cdg_picture, rgb_frames, settled_after
from vocatron.core.colour import round_12bit
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.layout.sample import sample_piece
from vocatron.core.profiles.model import CLASSIC_PROFILES, parse_profile
from vocatron.core.scene import TimerElement
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser

GOLDEN = Path(__file__).resolve().parents[3] / "data" / "cdg"
SLUGS = ("title", "sung", "change", "break", "countdown", "end")
SAME = 0.002  # the share of pixels that may differ (another FreeType may shade an edge)
RESOURCES = FakeResources()
FONT = RESOURCES.font_file()


def picture_of(name: str) -> CdgPicture:
    profile = parse_profile(name, RESOURCES.builtin_profile(name) or "")
    return cdg_picture(made_up_song(), profile, PillowMeasurer(FONT), PillowRasteriser(FONT))


@pytest.fixture(scope="module", params=CLASSIC_PROFILES)
def drawn(request: pytest.FixtureRequest) -> tuple[str, CdgPicture]:
    return request.param, picture_of(request.param)


def test_the_decoded_frames_match_the_golden_pictures(drawn: tuple[str, CdgPicture]) -> None:
    name, picture = drawn
    for slug, frame in zip(SLUGS, picture.frames, strict=True):
        path = GOLDEN / name / f"{slug}.png"
        if os.environ.get("VOCATRON_UPDATE_GOLDEN"):
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(frame).save(path)
        golden = np.asarray(Image.open(path).convert("RGB"))
        assert golden.shape == frame.shape == (216, 300, 3)
        differing = float((golden != frame).any(axis=2).mean())
        assert differing <= SAME, f"{name}/{slug}: {differing:.4f} of the pixels differ"


EXTRA = [("tall-page", "wrapped"), ("three-line", "timer")]
"""The looks whose six moments do not show their special feature, with the extra moment: a line
wrapped onto two rows over two slots, and the timer of a break screen."""


@pytest.mark.parametrize(("name", "slug"), EXTRA)
def test_the_wrapped_line_and_the_timer_match_their_golden_pictures(name: str, slug: str) -> None:
    profile = parse_profile(name, RESOURCES.builtin_profile(name) or "")
    song, text = sample_piece()  # a long first line and a break of twenty seconds
    phrases = phrases_from(song.words, song.lines, profile.font.case)
    fit = fit_stream(phrases, text, profile, PillowMeasurer(FONT), PillowRasteriser(FONT))
    lines = fit.scene.lines()
    if slug == "wrapped":
        assert lines[1].row == 1
        seconds = (lines[0].sing_start + lines[1].sing_end) / 2
    else:
        (timer,) = [e for e in fit.scene.elements if isinstance(e, TimerElement)]
        seconds = timer.end - 7.5  # the timer shows 8
    (frame,) = rgb_frames(fit.written.stream, [round(settled_after(fit, seconds), 3)])
    path = GOLDEN / name / f"{slug}.png"
    if os.environ.get("VOCATRON_UPDATE_GOLDEN"):
        Image.fromarray(frame).save(path)
    golden = np.asarray(Image.open(path).convert("RGB"))
    differing = float((golden != frame).any(axis=2).mean())
    assert differing <= SAME, f"{name}/{slug}: {differing:.4f} of the pixels differ"


def lit(frame: np.ndarray, rows: slice | None = None) -> np.ndarray:
    """Return which pixels are not the background (black or the look's background)."""
    background = frame[0, 0]  # the border is the background colour
    return (frame != background).any(axis=2)[rows or slice(None)]


def test_the_moments_show_what_their_names_say(drawn: tuple[str, CdgPicture]) -> None:
    name, picture = drawn
    title, sung, change, interval, countdown, end = picture.frames
    assert lit(title).any(), name  # the title screen has text
    assert not np.array_equal(title, sung) and not np.array_equal(sung, change), name
    look = parse_profile(name, RESOURCES.builtin_profile(name) or "")
    sung_colour = round_12bit(look.colours.group.sung)  # a group sings the moment
    wanted = np.array([int(sung_colour[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.uint8)
    assert (sung == wanted).all(axis=2).any(), f"{name}: no sung pixel while a line is sung"
    assert lit(countdown).any() and lit(change).any(), name
    assert lit(interval).any() and lit(end).any(), name  # a break screen and an end screen
