"""Stage 1: the social preview picture is current and shows the wordmark on its field (ADR-0055)."""

import pytest
from PIL import Image, ImageChops

import social_preview
from vocatron.core.wordmark import BAND_COLOURS, FIELD_COLOUR


def _rgb(colour: str) -> tuple[int, int, int]:
    return (int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16))


@pytest.fixture(scope="module")
def drawn() -> Image.Image:
    return social_preview.draw()


def test_the_committed_picture_is_what_the_tool_draws(drawn: Image.Image) -> None:
    with Image.open(social_preview.TARGET) as committed:
        difference = ImageChops.difference(committed.convert("RGB"), drawn)
    assert difference.getbbox() is None, "stale: run make social-preview"


def test_the_committed_picture_has_the_size_github_wants_and_is_light() -> None:
    with Image.open(social_preview.TARGET) as picture:
        assert picture.size == social_preview.SIZE == (1280, 640)
    assert social_preview.TARGET.stat().st_size <= social_preview.MAX_BYTES


def test_the_field_fills_the_margins_and_the_bands_fill_the_letters(drawn: Image.Image) -> None:
    width, height = drawn.size
    for corner in [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]:
        assert drawn.getpixel(corner) == _rgb(FIELD_COLOUR)
    seen = {
        drawn.getpixel((x, y)) for x in range(width) for y in range(height // 3, 2 * height // 3)
    }
    assert all(_rgb(colour) in seen for colour in BAND_COLOURS)


def test_the_word_is_centred_with_room_for_cropping(drawn: Image.Image) -> None:
    field = Image.new("RGB", drawn.size, FIELD_COLOUR)
    box = ImageChops.difference(drawn, field).getbbox()
    assert box is not None
    left, top, right, bottom = box
    assert abs(left - (drawn.width - right)) <= 2 and abs(top - (drawn.height - bottom)) <= 2
    assert left >= 100 and top >= 200  # glow included


def test_an_argument_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert social_preview.main(["x"]) == 2
    assert "no arguments" in capsys.readouterr().err


def test_every_corner_of_an_outline_gets_the_same_round_join() -> None:
    square = [(20.0, 20.0), (80.0, 20.0), (80.0, 80.0), (20.0, 80.0)]
    mask = social_preview._outline((100, 100), [square], 16)
    corners = [(15, 15), (85, 15), (85, 85), (15, 85)]  # outside the lines, inside a round join
    assert [mask.getpixel(corner) for corner in corners] == [255] * 4
