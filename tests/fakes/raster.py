"""A text rasteriser that draws one box per letter, with one column of shade at its left."""

import math

import numpy as np
from numpy.typing import NDArray

from fakes.measure import ADVANCE

FULL = 255
HALF = 100  # coverage of the shade column: above the shade limit, below the ink limit


class FakeRasteriser:
    """A letter is a box in the middle of its advance; a space is empty."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, float]] = []

    def coverage(self, text: str, size: float) -> NDArray[np.uint8]:
        self.requests.append((text, size))
        rows = max(1, round(size))
        advance = ADVANCE * size
        image = np.zeros((rows, math.ceil(len(text) * advance)), dtype=np.uint8)
        top, bottom = round(rows * 0.2), round(rows * 0.85)
        for number, letter in enumerate(text):
            if letter == " ":
                continue
            left, right = round(number * advance) + 2, round((number + 1) * advance) - 1
            image[top:bottom, left:right] = FULL
            image[top:bottom, left - 1] = HALF
        return image
