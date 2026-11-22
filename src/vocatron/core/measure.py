"""Measuring and drawing text in the bundled font (ADR-0009, ADR-0023)."""

from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class TextMeasurer(Protocol):
    """Measures text in the bundled font.

    The unit of ``size`` is the ASS ``Fontsize``: the height of a line cell in pixels. The answer
    is in the same pixels. The real measurer takes it from the font's metrics (Pillow); tests use
    a fake with fixed advances.
    """

    def width(self, text: str, size: float) -> float:
        """Return the advance width of ``text`` at ``size``, without outline or shadow."""
        ...


class TextRasteriser(Protocol):
    """Draws text in the bundled font as a map of coverage (the CD+G output, ADR-0023).

    The unit of ``size`` is the same as for ``TextMeasurer``. The real rasteriser uses Pillow;
    tests use a fake that draws one box per letter.
    """

    def coverage(self, text: str, size: float) -> NDArray[np.uint8]:
        """Return the coverage of ``text`` at ``size``, 0 (nothing) to 255 (full), row by row.

        The array is one line cell high (``round(size)`` rows) and as wide as the advance of the
        text rounded up; its top left corner is the top of the cell at the pen's start. Parts of
        letters outside it are cut off.
        """
        ...
