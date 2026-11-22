"""Measures text in the bundled font with Pillow (FreeType), the way libass sizes it (ADR-0009)."""

from pathlib import Path
from typing import TYPE_CHECKING

from vocatron.core.font_check import em_per_cell

if TYPE_CHECKING:
    from PIL.ImageFont import FreeTypeFont

REFERENCE_PX = 1000  # the em the font is measured at; widths scale linearly from it


class PillowMeasurer:
    """The width of text in a font file at an ASS ``Fontsize``.

    The font is measured once at a large size and the result scaled, so the answer is linear in
    the size and needs no hinting. Pillow is imported and the font read on first use.
    """

    def __init__(self, font_file: Path) -> None:
        """Remember the font file; nothing is read until the first measurement."""
        self._file = font_file
        self._loaded: tuple[FreeTypeFont, float] | None = None
        self._ems: dict[str, float] = {}

    def _load(self) -> tuple[FreeTypeFont, float]:
        """Return the font at the reference size and the em that one ``Fontsize`` is worth."""
        if self._loaded is None:
            from PIL import ImageFont  # noqa: PLC0415  # heavy import, only when text is measured

            font = ImageFont.truetype(str(self._file), REFERENCE_PX)
            self._loaded = (font, em_per_cell(self._file.read_bytes()))
        return self._loaded

    def width(self, text: str, size: float) -> float:
        """Return the advance width of ``text`` at ``size`` (an ASS ``Fontsize``) in pixels."""
        font, per_cell = self._load()
        if text not in self._ems:
            self._ems[text] = float(font.getlength(text)) / REFERENCE_PX
        return self._ems[text] * size * per_cell
