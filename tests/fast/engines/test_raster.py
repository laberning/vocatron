"""Stage 1: text is drawn in the bundled font the way libass sizes it (ADR-0009, ADR-0023)."""

import math
from pathlib import Path

import numpy as np
import pytest

from vocatron.core.font_check import ascent_share
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser
from vocatron.engines.resources import PackageResources

FONT = PackageResources().font_file()


@pytest.fixture(scope="module")
def rasteriser() -> PillowRasteriser:
    return PillowRasteriser(FONT)


def test_the_cell_is_as_high_as_the_font_size_and_as_wide_as_the_text(
    rasteriser: PillowRasteriser,
) -> None:
    measurer = PillowMeasurer(FONT)
    for text, size in (("Hamburger Wiese", 23.04), ("Köpfchen in das Wasser", 40.0), ("W", 60.0)):
        cover = rasteriser.coverage(text, size)
        assert cover.dtype == np.uint8
        assert cover.shape[0] == round(size)
        assert abs(cover.shape[1] - math.ceil(measurer.width(text, size))) <= 1


def test_a_letter_stands_on_the_baseline_the_font_gives_the_cell() -> None:
    size = 100.0
    cover = PillowRasteriser(FONT).coverage("H", size)
    rows = np.nonzero((cover >= 128).any(axis=1))[0]
    baseline = size * ascent_share(FONT.read_bytes())
    assert abs((rows.max() + 1) - baseline) <= 1.5
    assert rows.min() > 0.1 * size  # the cap height leaves room above, inside the cell


def test_the_letters_have_full_ink_and_smooth_edges(rasteriser: PillowRasteriser) -> None:
    cover = rasteriser.coverage("Hl", 30.0)
    assert cover.max() == 255
    assert ((cover > 0) & (cover < 255)).any()


def test_nothing_is_drawn_for_a_space_and_the_array_is_never_empty(
    rasteriser: PillowRasteriser,
) -> None:
    assert rasteriser.coverage("", 20.0).shape[1] >= 1
    assert not rasteriser.coverage(" ", 20.0).any()


def test_a_larger_size_draws_more_ink(rasteriser: PillowRasteriser) -> None:
    small = rasteriser.coverage("Wiese", 20.0).astype(int).sum()
    large = rasteriser.coverage("Wiese", 40.0).astype(int).sum()
    assert large > 3 * small


def test_the_same_text_gives_the_same_picture_and_german_letters_are_drawn(
    rasteriser: PillowRasteriser,
) -> None:
    first = rasteriser.coverage("Schwänzchen in die Höh", 23.0)
    assert np.array_equal(first, rasteriser.coverage("Schwänzchen in die Höh", 23.0))
    umlauts = rasteriser.coverage("äöüß", 30.0)
    assert (umlauts >= 128).sum() > 100  # not the empty boxes of a missing glyph


def test_the_font_is_read_only_when_a_text_is_drawn(tmp_path: Path) -> None:
    rasteriser = PillowRasteriser(tmp_path / "missing.ttf")
    with pytest.raises(OSError, match="missing.ttf|cannot open"):
        rasteriser.coverage("a", 10.0)
