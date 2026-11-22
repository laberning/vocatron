"""Stage 2: the screens with the wordmark drawn by ffmpeg with libass (ADR-0055, ADR-0057).

One scene, laid out with the real font, is drawn at three moments. Inside a letter the band
colours are found, inside the counter of the O and outside the letters the colour of the field,
and in the middle of the build-up VO is filled and TRON is not yet.
"""

import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fakes.phrases import line
from vocatron.core.ass.write import write_ass
from vocatron.core.ffmpeg_cmd import frame_command
from vocatron.core.font_check import font_problems
from vocatron.core.layout.build import SongText, layout
from vocatron.core.presets import PRESETS
from vocatron.core.profiles.model import parse_profile
from vocatron.core.scene import CardElement, Scene
from vocatron.core.wordmark import BAND_COLOURS, EDGE_COLOUR, FIELD_COLOUR, bands, letters
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.resources import PackageResources

RESOURCES = PackageResources()
PRESET = PRESETS["4x3-720"]
SECONDS = 6.0
NEAR = 40  # a pixel this close (largest channel difference) to a colour has that colour
FRAME_LIMIT = 60

pytestmark = [
    pytest.mark.skipif(not RESOURCES.font_file().is_file(), reason="the bundled font is missing"),
    pytest.mark.timeout(300),
]


def rgb(colour: str) -> np.ndarray:
    return np.array([int(colour[i : i + 2], 16) for i in (1, 3, 5)])


@pytest.fixture(scope="module")
def scene() -> Scene:
    look = parse_profile("two-line-turns", RESOURCES.builtin_profile("two-line-turns") or "")
    song = SongText("Lanterns Over Marrow Bay", "The Quiet Tuesdays", SECONDS, {})
    return layout(
        [], song, look, (PRESET.width, PRESET.height), PillowMeasurer(RESOURCES.font_file())
    )


def draw(scene: Scene, seconds: float, work: Path) -> np.ndarray:
    ass = work / "title.ass"
    ass.write_text(write_ass(scene), encoding="utf-8")
    target = work / f"frame-{seconds}.png"
    command = frame_command(PRESET, "#808080", ass, RESOURCES.fonts_dir(), seconds, target)
    done = subprocess.run(command, capture_output=True, check=False, timeout=FRAME_LIMIT)
    log = done.stderr.decode(errors="replace")
    assert done.returncode == 0 and not font_problems(log), log[-400:]
    with Image.open(target) as picture:
        return np.asarray(picture.convert("RGB")).astype(int)


def pixel(
    frame: np.ndarray, scene: Scene, letter: int, x: float, y: float, kind: str = "title"
) -> np.ndarray:
    """The pixel at grid point (``x`` from the letter's left, ``y`` from its top)."""
    (card,) = [e for e in scene.elements if isinstance(e, CardElement) and e.kind == kind]
    assert card.mark is not None
    mark = card.mark
    left = letters()[letter].left
    column = round(mark.word.x + (left + x) * mark.scale)
    row = round(mark.word.y + y * mark.scale)
    return frame[row, column]


def stem(
    frame: np.ndarray, scene: Scene, letter: int, band: int, kind: str = "title"
) -> np.ndarray:
    """The pixel in the middle of the left stem of ``letter`` at the middle of a band."""
    top, bottom, _ = bands()[band]
    return pixel(frame, scene, letter, 26.0, (top + bottom) / 2, kind)


def close(found: np.ndarray, colour: str) -> bool:
    return bool(np.abs(found - rgb(colour)).max() <= NEAR)


def test_a_finished_start_screen_has_the_bands_in_a_letter_and_the_field_around_it(
    scene: Scene, tmp_path: Path
) -> None:
    frame = draw(scene, 4.0, tmp_path)
    for band, colour in enumerate(BAND_COLOURS):
        assert close(stem(frame, scene, 1, band), colour), f"band {band} of the O"
        assert close(stem(frame, scene, 7, band), colour), f"band {band} of the N"
    assert close(pixel(frame, scene, 1, 88.0, 90.0), FIELD_COLOUR), "the counter of the O"
    (card,) = [e for e in scene.elements if isinstance(e, CardElement)]
    assert card.mark is not None
    word = card.mark.word
    assert close(frame[round(word.y) - 30, round(word.x + word.w / 2)], FIELD_COLOUR)
    assert close(frame[2, 2], FIELD_COLOUR), "the field covers the picture, not the background"
    assert close(frame[-3, -3], FIELD_COLOUR)


def test_the_texts_stand_in_the_frame_when_the_screen_is_finished(
    scene: Scene, tmp_path: Path
) -> None:
    frame = draw(scene, 4.0, tmp_path)
    (card,) = [e for e in scene.elements if isinstance(e, CardElement)]
    assert card.mark is not None
    box = card.mark.frame
    inside = frame[round(box.y) : round(box.bottom), round(box.x) : round(box.right)]
    assert (inside.min(axis=2) > 200).sum() > 100, "white ink of the title"


def test_in_the_middle_of_the_build_up_vo_is_filled_and_tron_is_not(
    scene: Scene, tmp_path: Path
) -> None:
    frame = draw(scene, 0.95, tmp_path)
    assert close(stem(frame, scene, 1, 3), BAND_COLOURS[3]), "VO is filled"
    assert not close(stem(frame, scene, 7, 3), BAND_COLOURS[3]), "TRON is not filled yet"
    assert close(stem(frame, scene, 7, 3), FIELD_COLOUR), "TRON is still the dark field"
    (card,) = [e for e in scene.elements if isinstance(e, CardElement)]
    assert card.mark is not None
    middle = card.mark.frame
    assert close(
        frame[round(middle.y + middle.h / 2), round(middle.x + middle.w / 2)], FIELD_COLOUR
    )


# ---- the end and break screens (ADR-0057)


@pytest.fixture(scope="module")
def song_scene() -> Scene:
    """A song with a break of thirty seconds and an end screen, in a page look."""
    look = parse_profile("two-line-turns", RESOURCES.builtin_profile("two-line-turns") or "")
    song = SongText("Lanterns Over Marrow Bay", "The Quiet Tuesdays", 80.0, {})
    lines = [line(8.0, 10.0, "la la"), line(40.0, 42.0, "li li")]
    measurer = PillowMeasurer(RESOURCES.font_file())
    return layout(lines, song, look, (PRESET.width, PRESET.height), measurer)


def card_of(scene: Scene, kind: str) -> CardElement:
    (found,) = [e for e in scene.elements if isinstance(e, CardElement) and e.kind == kind]
    return found


def test_the_end_screen_has_the_bands_in_a_letter_and_the_field_around_it(
    song_scene: Scene, tmp_path: Path
) -> None:
    end = card_of(song_scene, "end")
    assert end.mark is not None
    frame = draw(song_scene, end.start + 0.2, tmp_path)  # before the fade starts
    for band, colour in enumerate(BAND_COLOURS):
        assert close(stem(frame, song_scene, 1, band, "end"), colour), f"band {band} of the O"
    assert close(frame[2, 2], FIELD_COLOUR), "the field covers the picture"
    box = end.mark.frame
    inside = frame[round(box.y) : round(box.bottom), round(box.x) : round(box.right)]
    assert (inside.min(axis=2) > 200).sum() > 100, "white ink of the title"


def test_the_break_screen_has_the_finished_v_with_bands_and_no_field(
    song_scene: Scene, tmp_path: Path
) -> None:
    card = card_of(song_scene, "break")
    assert card.symbol is not None
    box = card.symbol
    frame = draw(song_scene, card.start + 2.0, tmp_path)
    inside = frame[round(box.y) : round(box.bottom), round(box.x) : round(box.right)]
    cyan = np.abs(inside - rgb(EDGE_COLOUR)).max(axis=2) <= NEAR
    assert cyan.sum() > 50, "the cyan edge of the V"
    for colour in BAND_COLOURS:
        assert (np.abs(inside - rgb(colour)).max(axis=2) <= NEAR // 4).any(), colour
    assert not (np.abs(inside - rgb(FIELD_COLOUR)).max(axis=2) <= NEAR // 4).any(), "no field"
    # the middle of the V's left stem is filled with a band colour, not the background
    stem_x, stem_y = round(box.x + box.w * 0.27), round(box.y + box.h * 0.25)
    assert any(close(frame[stem_y, stem_x], colour) for colour in BAND_COLOURS), "a filled letter"
    assert close(frame[2, 2], "#808080"), "no field: the background shows"


def test_in_a_scroll_look_the_break_screen_stands_alone_with_the_v_and_the_notice(
    tmp_path: Path,
) -> None:
    """Halfway through a long break the V is filled and nothing else is on screen (ADR-0040)."""
    look = parse_profile("lyric-scroll", RESOURCES.builtin_profile("lyric-scroll") or "")
    song = SongText("Lanterns Over Marrow Bay", "The Quiet Tuesdays", 80.0, {})
    lines = [line(8.0, 10.0, "la la"), line(40.0, 42.0, "li li")]
    measurer = PillowMeasurer(RESOURCES.font_file())
    scene = layout(lines, song, look, (PRESET.width, PRESET.height), measurer)
    card = card_of(scene, "break")
    assert card.symbol is not None
    frame = draw(scene, (card.start + card.end) / 2, tmp_path)
    box = card.symbol
    stem_x, stem_y = round(box.x + box.w * 0.27), round(box.y + box.h * 0.25)
    assert not close(frame[stem_y, stem_x], "#808080"), "the stem is filled"
    assert not close(frame[stem_y, stem_x], EDGE_COLOUR), "with a band, not the edge"
    notice = card.lines[0]  # the notice is there: ink in its box
    inside = frame[
        round(notice.box.y) : round(notice.box.bottom),
        round(notice.box.x) : round(notice.box.right),
    ]
    assert (np.abs(inside - rgb("#808080")).max(axis=2) > NEAR).any(), "the notice is drawn"
    outside = frame.copy()  # and no lyrics: the rest of the picture is the background
    pad = 20
    outside[
        max(round(card.box.y) - pad, 0) : round(card.box.bottom) + pad,
        max(round(card.box.x) - pad, 0) : round(card.box.right) + pad,
    ] = rgb("#808080")
    assert np.abs(outside - rgb("#808080")).max() <= NEAR, "something else is on screen"
