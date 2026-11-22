"""Colours as ``#rrggbb`` text: parsing, contrast, ASS spelling and 12-bit rounding.

The contrast rules are rule 18 of ADR-0009; the rounding to 12 bits is that of CD+G (ADR-0029).
"""

import re

HEX_PATTERN = r"#[0-9a-fA-F]{6}"
_HEX = re.compile(HEX_PATTERN)
SRGB_KNEE = 0.04045  # where the sRGB curve turns from a line into a power
CHANNEL_SCALE = 17  # 255 / 15: a 4-bit channel value as an 8-bit one
_SHORT_HEX = re.compile(r"#[0-9a-fA-F]{3}")

type Rgb = tuple[int, int, int]


def parse_hex(colour: str) -> Rgb:
    """Return the red, green and blue values (0 to 255) of ``#rrggbb``.

    Raises:
        ValueError: If ``colour`` is not ``#rrggbb``.
    """
    if _HEX.fullmatch(colour) is None:
        raise ValueError(f"{colour!r} is not a colour like #rrggbb")
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def _linear(value: int) -> float:
    """Return one sRGB channel (0 to 255) as linear light (0 to 1)."""
    share = value / 255
    return share / 12.92 if share <= SRGB_KNEE else ((share + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    """Return the relative luminance (0 black, 1 white) after WCAG 2."""
    red, green, blue = (_linear(v) for v in parse_hex(colour))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    """Return the WCAG contrast ratio of two colours (1 for equal colours, 21 at most)."""
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def distance(first: str, second: str) -> float:
    """Return the Euclidean distance of two colours in sRGB (0 to about 441)."""
    return (
        sum((a - b) ** 2 for a, b in zip(parse_hex(first), parse_hex(second), strict=True)) ** 0.5
    )


def blend(top: str, bottom: str, opacity: float) -> str:
    """Return ``top`` laid over ``bottom`` at ``opacity`` (1 opaque, 0 invisible) as ``#rrggbb``."""
    mixed = (
        round(a * opacity + b * (1 - opacity))
        for a, b in zip(parse_hex(top), parse_hex(bottom), strict=True)
    )
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def ass_colour(colour: str, alpha: float = 1.0) -> str:
    """Return ``&HAABBGGRR`` for ASS; ``alpha`` is the opacity (1 opaque, 0 invisible)."""
    red, green, blue = parse_hex(colour)
    transparent = round((1 - alpha) * 255)
    return f"&H{transparent:02X}{blue:02X}{green:02X}{red:02X}"


def ass_alpha(opacity: float) -> str:
    """Return ``&HAA&`` for ASS from an opacity (1 opaque, 0 invisible)."""
    return f"&H{round((1 - opacity) * 255):02X}&"


def long_hex(colour: str) -> str:
    """Return ``colour`` as ``#rrggbb`` in lower case.

    A ``#rgb`` colour has every digit doubled: ``#3af`` is ``#33aaff``.

    Raises:
        ValueError: If ``colour`` is neither ``#rgb`` nor ``#rrggbb``.
    """
    if _SHORT_HEX.fullmatch(colour) is not None:
        return "#" + "".join(2 * digit for digit in colour[1:].lower())
    return "#{:02x}{:02x}{:02x}".format(*parse_hex(colour))


def to_12bit(colour: str) -> Rgb:
    """Return ``#rrggbb`` rounded to the nearest value of 4 bits per channel (0 to 15)."""
    red, green, blue = parse_hex(colour)
    return (
        round(red / CHANNEL_SCALE),
        round(green / CHANNEL_SCALE),
        round(blue / CHANNEL_SCALE),
    )


def from_12bit(colour: Rgb) -> str:
    """Return a colour of 4 bits per channel as ``#rrggbb``."""
    return "#" + "".join(f"{value * CHANNEL_SCALE:02x}" for value in colour)


def round_12bit(colour: str) -> str:
    """Return ``colour`` rounded to the nearest 12-bit colour, as ``#rrggbb`` (CD+G, ADR-0029)."""
    return from_12bit(to_12bit(colour))
