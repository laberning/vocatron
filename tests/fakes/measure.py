"""A text measurer with fixed advances: every character is the same width."""

ADVANCE = 0.5  # of the font size, per character


class FixedMeasurer:
    """Every character, space included, is ``ADVANCE`` times the font size wide."""

    def width(self, text: str, size: float) -> float:
        return len(text) * ADVANCE * size
