"""The logo files: the wordmark and the V symbol as SVG text (ADR-0055).

Both are drawn from the polygons of ``vocatron.core.wordmark``, the same ones the video draws:
the letters edged in glowing cyan (an SVG blur filter), filled with the seven colour bands and
edged once more with a thin light line. The background is transparent, so the files read on
light and dark pages alike; the video's dark field is not drawn. ``make logo`` writes the files
into ``docs/assets/logo/``; a fast test fails when they differ from this text.
Pure: no I/O.
"""

from vocatron.core.wordmark import (
    EDGE_COLOUR,
    EDGE_LIGHT,
    EDGE_WIDTH,
    LETTER_HEIGHT,
    LIGHT_WIDTH,
    Letter,
    bands,
    letters,
    symbol,
    word_width,
)

PAD = 60.0
"""The room around the letters, in grid units; it holds the glow."""
BLUR = 9.0
"""The blur of the glow, in grid units."""
FILE_NAMES = {"wordmark": "wordmark.svg", "symbol": "symbol.svg"}
"""The files ``make logo`` writes, by what they show."""


def _number(value: float) -> str:
    """Format a coordinate with at most three decimals."""
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _path(shapes: tuple[Letter, ...]) -> str:
    """Return the ``d`` of one path that draws every contour of ``shapes``."""
    parts = []
    for letter in shapes:
        for contour in letter.contours:
            points = " L".join(f"{_number(x)},{_number(y)}" for x, y in contour)
            parts.append(f"M{points} Z")
    return " ".join(parts)


def _svg(shapes: tuple[Letter, ...], width: float) -> str:
    """Return the SVG text of ``shapes`` (``width`` wide, ``LETTER_HEIGHT`` high), unbacked."""
    total_w, total_h = width + 2 * PAD, LETTER_HEIGHT + 2 * PAD
    path = _path(shapes)
    rows = "".join(
        f'<rect x="0" y="{_number(top)}" width="{_number(width)}" '
        f'height="{_number(bottom - top + 0.5)}" fill="{colour}"/>'
        for top, bottom, colour in bands()
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_number(total_w)} '
        f'{_number(total_h)}" role="img" aria-label="Vocatron">\n'
        f'<defs><filter id="glow" x="-20%" y="-40%" width="140%" height="180%">'
        f'<feGaussianBlur stdDeviation="{_number(BLUR)}"/></filter>'
        f'<clipPath id="letters"><path d="{path}" clip-rule="evenodd"/></clipPath></defs>\n'
        f'<g transform="translate({_number(PAD)},{_number(PAD)})">\n'
        f'<path d="{path}" fill="none" stroke="{EDGE_COLOUR}" stroke-width="{_number(EDGE_WIDTH)}" '
        f'stroke-linejoin="round" filter="url(#glow)"/>\n'
        f'<path d="{path}" fill="none" stroke="{EDGE_COLOUR}" stroke-width="{_number(EDGE_WIDTH)}" '
        f'stroke-linejoin="round" opacity="0.55"/>\n'
        f'<g clip-path="url(#letters)">{rows}</g>\n'
        f'<path d="{path}" fill="none" stroke="{EDGE_LIGHT}" stroke-width="{_number(LIGHT_WIDTH)}" '
        f'stroke-linejoin="round" fill-rule="evenodd"/>\n'
        f"</g>\n</svg>\n"
    )


def wordmark_svg() -> str:
    """Return the SVG text of the wordmark: the eight letters on a transparent background."""
    return _svg(letters(), word_width())


def symbol_svg() -> str:
    """Return the SVG text of the symbol: the letter V alone on a transparent background."""
    shape = symbol()
    return _svg((shape,), shape.width)


def logo_files() -> dict[str, str]:
    """Return the text of every logo file by its file name."""
    return {FILE_NAMES["wordmark"]: wordmark_svg(), FILE_NAMES["symbol"]: symbol_svg()}
