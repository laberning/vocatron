"""Draw the social preview picture of the repository: the wordmark on its dark field (ADR-0055).

Run with ``make social-preview``. GitHub shows the picture when a link to the repository is
shared; it is uploaded by hand under Settings, General, Social preview. The picture is 1280 by
640 pixels: the wordmark from the polygons of ``vocatron.core.wordmark``, drawn like the logo
files (the cyan edge and its glow, the seven colour bands, the thin light edge), on the video's
dark field, since a transparent picture would be shown on any colour. It is drawn with Pillow at
``SUPERSAMPLE`` times the size and scaled down for smooth edges. A fast test fails when the
committed file differs from what this draws. ``TARGET`` and ``draw`` are also used by the tests.
"""

import sys
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from vocatron.core.logo import BLUR, EDGE_OPACITY
from vocatron.core.wordmark import (
    EDGE_COLOUR,
    EDGE_LIGHT,
    EDGE_WIDTH,
    FIELD_COLOUR,
    LETTER_HEIGHT,
    LIGHT_WIDTH,
    bands,
    letters,
    word_width,
)

SIZE = (1280, 640)
"""The size GitHub recommends for a social preview."""
WORD_PIXELS = 960
"""How wide the word is drawn; the rest is margin, as some sites crop the edges."""
SUPERSAMPLE = 3
"""How many times larger the picture is drawn before it is scaled down."""
ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / ".github" / "social-preview.png"
MAX_BYTES = 1_000_000  # GitHub takes up to 1 MB


Points = list[tuple[float, float]]


def _contours(scale: float, width: int, height: int) -> list[Points]:
    """Return every contour of the word in pixels, scaled by ``scale`` and centred."""
    left = (width - word_width() * scale) / 2
    top = (height - LETTER_HEIGHT * scale) / 2
    return [
        [(left + x * scale, top + y * scale) for x, y in contour]
        for letter in letters()
        for contour in letter.contours
    ]


def _outline(size: tuple[int, int], contours: Sequence[Points], width: float) -> Image.Image:
    """Return a mask of the contours drawn as closed lines ``width`` pixels wide.

    Each line runs on to the second point again, so the first corner gets its round join too
    (Pillow rounds only the joins between segments).
    """
    mask = Image.new("L", size, 0)
    pen = ImageDraw.Draw(mask)
    for contour in contours:
        pen.line([*contour, *contour[:2]], fill=255, width=round(width), joint="curve")
    return mask


def _inside(size: tuple[int, int], contours: Sequence[Points]) -> Image.Image:
    """Return a mask of the inside of the letters: even-odd, so the counters stay open."""
    mask = Image.new("1", size, 0)
    for contour in contours:
        shape = Image.new("1", size, 0)
        ImageDraw.Draw(shape).polygon(contour, fill=1)
        mask = ImageChops.logical_xor(mask, shape)
    return mask


def draw() -> Image.Image:
    """Return the social preview picture."""
    width, height = SIZE[0] * SUPERSAMPLE, SIZE[1] * SUPERSAMPLE
    scale = WORD_PIXELS * SUPERSAMPLE / word_width()
    contours = _contours(scale, width, height)
    picture = Image.new("RGB", (width, height), FIELD_COLOUR)
    edge = _outline((width, height), contours, EDGE_WIDTH * scale)
    picture.paste(EDGE_COLOUR, mask=edge.filter(ImageFilter.GaussianBlur(BLUR * scale)))
    picture.paste(EDGE_COLOUR, mask=edge.point(lambda value: round(value * EDGE_OPACITY)))
    stripes = Image.new("RGB", (width, height), FIELD_COLOUR)
    pen = ImageDraw.Draw(stripes)
    top = (height - LETTER_HEIGHT * scale) / 2
    for upper, lower, colour in bands():
        pen.rectangle((0, top + upper * scale, width, top + lower * scale + 1), fill=colour)
    picture.paste(stripes, mask=_inside((width, height), contours))
    picture.paste(EDGE_LIGHT, mask=_outline((width, height), contours, LIGHT_WIDTH * scale))
    return picture.resize(SIZE, Image.Resampling.LANCZOS)


def main(argv: Sequence[str]) -> int:
    """Draw the picture into ``TARGET``; return the exit code."""
    if argv:
        print("error: social_preview takes no arguments", file=sys.stderr)
        return 2
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    draw().save(TARGET, optimize=True)
    size = TARGET.stat().st_size
    print(f"wrote {TARGET.relative_to(ROOT)}: {size / 1e3:.0f} kB")
    return 0 if size <= MAX_BYTES else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
