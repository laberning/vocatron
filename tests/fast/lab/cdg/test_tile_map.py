"""Stage 1: the tile map shows layout and colour per tile and nothing inside a tile."""

import numpy as np
import pytest

from fakes.cdg import classic_song
from vocatron.core.cdg import HEIGHT, TILE_COLUMNS, TILE_ROWS, WIDTH, decode
from vocatron.lab.cdg.tile_map import render_maps, tile_map


def test_a_flat_screen_is_all_background() -> None:
    rows = tile_map(np.full((HEIGHT, WIDTH), 7, dtype=np.uint8))
    assert rows == ["." * TILE_COLUMNS] * TILE_ROWS


def test_a_flat_tile_of_another_colour_is_lower_case_and_a_tile_with_ink_upper_case() -> None:
    frame = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    frame[0:12, 0:6] = 11  # a flat tile in colour 11
    frame[12:24, 6:12] = 2
    frame[12:24, 6:12][::2, ::2] = (
        14  # a few pixels of colour 14 on a tile of colour 2 (the background is 0)
    )
    rows = tile_map(frame)
    assert rows[0][0] == "l"  # colour 11
    assert rows[1][1] == "C"  # ink: colour 2 (the next colour, 14, has fewer pixels)


def test_the_map_of_a_tile_does_not_depend_on_where_the_ink_is_inside_it() -> None:
    first = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    second = first.copy()
    first[0:3, 0:2] = 4
    second[9:12, 4:6] = 4
    assert tile_map(first) == tile_map(second)


def test_the_synthetic_disc_has_its_title_and_lines_on_the_map() -> None:
    stream, _ = classic_song()
    frame = decode(stream, [3.0]).frames[0]
    rows = tile_map(frame)
    assert len(rows) == TILE_ROWS
    assert all(len(row) == TILE_COLUMNS for row in rows)
    assert rows[4].strip(".") != "" and rows[6].strip(".") != "" and rows[0].strip(".") == ""


@pytest.mark.parametrize("per_line", [1, 2])
def test_maps_are_laid_out_with_their_times(per_line: int) -> None:
    grid: list[str] = ["." * TILE_COLUMNS] * TILE_ROWS
    text = render_maps([(1.5, grid), (2.0, grid)], per_line)
    assert "t=   1.50 s" in text and "t=   2.00 s" in text
    assert len(text.split("\n")) == (TILE_ROWS + 2) * (2 // per_line)
