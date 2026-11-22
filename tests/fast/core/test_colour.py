"""Stage 1: colours as #rrggbb text."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.colour import (
    ass_alpha,
    ass_colour,
    blend,
    contrast_ratio,
    distance,
    from_12bit,
    long_hex,
    luminance,
    parse_hex,
    round_12bit,
    to_12bit,
)

COLOURS = st.tuples(*[st.integers(0, 255)] * 3).map(lambda c: "#{:02x}{:02x}{:02x}".format(*c))


def test_a_colour_is_read_as_red_green_blue() -> None:
    assert parse_hex("#3399ff") == (0x33, 0x99, 0xFF)


@pytest.mark.parametrize("text", ["3399ff", "#39f", "#3399fg", "", "#3399ff00"])
def test_anything_but_six_hex_digits_after_a_hash_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="not a colour"):
        parse_hex(text)


def test_black_and_white_are_the_extremes_of_the_contrast() -> None:
    assert luminance("#000000") == 0.0
    assert luminance("#ffffff") == pytest.approx(1.0)
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert contrast_ratio("#336699", "#336699") == 1.0


def test_the_distance_is_zero_for_equal_colours_and_large_for_opposites() -> None:
    assert distance("#123456", "#123456") == 0.0
    assert distance("#000000", "#ffffff") == pytest.approx(441.67, abs=0.01)


def test_ass_wants_blue_green_red_and_the_transparency() -> None:
    assert ass_colour("#3399ff") == "&H00FF9933"
    assert ass_colour("#000000", 0.6) == "&H66000000"
    assert ass_colour("#ffffff", 0.0) == "&HFFFFFFFF"


def test_the_luminance_follows_the_srgb_curve_of_wcag() -> None:
    assert luminance("#777777") == pytest.approx(0.18447, abs=1e-4)  # on the power part
    assert luminance("#0a0a0a") == pytest.approx(10 / 255 / 12.92, abs=1e-6)  # on the line part
    assert contrast_ratio("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)


def test_a_colour_is_rounded_to_the_nearest_12_bit_value() -> None:
    assert round_12bit("#3399ff") == "#3399ff"  # already a 12-bit colour
    assert round_12bit("#3a9bfe") == "#3399ff"
    assert round_12bit("#080808") == "#000000"  # 8 is nearer 0 than 17
    assert round_12bit("#090909") == "#111111"  # 9 is nearer 17 than 0
    assert round_12bit("#0a0a0a") == "#111111"
    assert round_12bit("#fefefe") == "#ffffff"


def test_a_12_bit_colour_has_four_bits_per_channel_and_comes_back_as_hex() -> None:
    assert to_12bit("#3a9bfe") == (3, 9, 15)
    assert from_12bit((3, 9, 15)) == "#3399ff"
    assert from_12bit((0, 0, 0)) == "#000000"


@given(COLOURS)
def test_rounding_is_idempotent_and_moves_each_channel_by_at_most_eight(colour: str) -> None:
    rounded = round_12bit(colour)
    assert round_12bit(rounded) == rounded
    assert from_12bit(to_12bit(colour)) == rounded
    assert all(abs(a - b) <= 8 for a, b in zip(parse_hex(colour), parse_hex(rounded), strict=True))


@given(st.tuples(*[st.integers(0, 15)] * 3))
def test_every_12_bit_colour_survives_the_round_trip(bits: tuple[int, int, int]) -> None:
    assert to_12bit(from_12bit(bits)) == bits


def test_a_short_colour_has_every_digit_doubled_and_a_long_one_is_lower_case() -> None:
    assert long_hex("#3af") == "#33aaff"
    assert long_hex("#3AF") == "#33aaff"
    assert long_hex("#3399FF") == "#3399ff"
    assert round_12bit(long_hex("#f0a")) == "#ff00aa"  # a #rgb colour is a 12-bit colour already


@pytest.mark.parametrize("text", ["3af", "#3a", "#3af0", "#3agf", ""])
def test_a_colour_that_is_neither_rgb_nor_rrggbb_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="not a colour"):
        long_hex(text)


def test_blend_mixes_by_opacity_and_writes_lower_case_hex() -> None:
    assert blend("#ffffff", "#000000", 0.5) == "#808080"
    assert blend("#ABCDEF", "#000000", 1.0) == "#abcdef"
    assert blend("#ABCDEF", "#123456", 0.0) == "#123456"
    assert blend("#ff0000", "#0000ff", 0.25) == "#4000bf"


def test_ass_alpha_is_the_transparency_in_hex() -> None:
    assert (ass_alpha(1.0), ass_alpha(0.0), ass_alpha(0.5)) == ("&H00&", "&HFF&", "&H80&")
