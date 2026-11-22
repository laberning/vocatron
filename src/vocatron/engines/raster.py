"""Draws text in the bundled font with Pillow (FreeType) for the CD+G output (ADR-0023)."""

import math
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from vocatron.core.font_check import ascent_share, em_per_cell

if TYPE_CHECKING:
    from PIL.ImageFont import FreeTypeFont

FULL = 255


class PillowRasteriser:
    """The coverage of text in a font file at an ASS ``Fontsize``.

    The font is sized as libass sizes it, so the letters have the width the layout measured
    (``PillowMeasurer``): the em is ``size`` times the font's ``em_per_cell``, and the baseline
    lies at the font's Windows ascent below the top of the line cell. Pillow is imported and the
    font read on first use.
    """

    def __init__(self, font_file: Path) -> None:
        """Remember the font file; nothing is read until the first text is drawn."""
        self._file = font_file
        self._metrics: tuple[float, float] | None = None
        self._fonts: dict[float, FreeTypeFont] = {}

    def _scale(self) -> tuple[float, float]:
        """Return the em per cell pixel and the share of the cell above the baseline."""
        if self._metrics is None:
            data = self._file.read_bytes()
            self._metrics = (em_per_cell(data), ascent_share(data))
        return self._metrics

    def coverage(self, text: str, size: float) -> NDArray[np.uint8]:
        """Return the coverage of ``text`` at ``size``; see ``TextRasteriser.coverage``."""
        from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415  # heavy import, lazily

        per_cell, ascent = self._scale()
        em = size * per_cell
        if em not in self._fonts:
            self._fonts[em] = ImageFont.truetype(str(self._file), em)
        font = self._fonts[em]
        rows = max(1, round(size))
        image = Image.new("L", (max(1, math.ceil(font.getlength(text))), rows), 0)
        ImageDraw.Draw(image).text((0, size * ascent), text, font=font, fill=FULL, anchor="ls")
        return np.asarray(image, dtype=np.uint8)
