"""Stage 1: the pieces of the CD+G target frames one by one, on hand-made elements (ADR-0023).

Bars, dots, a progress bar, clipping to the visible area, which syllable a pixel column belongs
to, the redrawn tiles and the preview line; then the palette's edge, bar and capacity rules and
the encoder's shortcuts. ``core/cdg/test_raster.py`` checks the same on whole scenes.
"""

from typing import Literal

import numpy as np
import pytest

from fakes.raster import FakeRasteriser
from fakes.scenes import builtin_profile, cdg_duet, cdg_entchen, profile
from vocatron.core.cdg.canvas import SAFE
from vocatron.core.cdg.encode import plan_tile
from vocatron.core.cdg.palette import Palette, build_palette
from vocatron.core.cdg.raster import (
    BAR_END,
    CLEAR,
    Dots,
    ProgressBar,
    ShrinkingBar,
    TargetFrames,
    TextSpec,
    _crop,
    classify,
    stamp,
    stepped,
    text_sprite,
)
from vocatron.core.cdg.screen import HEIGHT, TILE_HEIGHT, TILE_WIDTH, WIDTH
from vocatron.core.errors import StageError
from vocatron.core.scene import (
    Colours,
    CountdownElement,
    LineElement,
    ProgressElement,
    Rect,
    SceneElement,
)

TOP, LEFT = round(SAFE.y), round(SAFE.x)
BOTTOM, RIGHT = round(SAFE.bottom), round(SAFE.right)


def blank() -> np.ndarray:
    return np.zeros((HEIGHT, WIDTH), dtype=np.uint8)


def countdown(
    form: Literal["shrinking-bar", "dots", "blocks"], box: Rect, count: int = 4
) -> CountdownElement:
    return CountdownElement(start=10.0, end=14.0, box=box, form=form, count=count, colour="#fff")


# --- bars and dots -----------------------------------------------------------------------------


def test_a_bar_lives_from_its_start_to_its_end() -> None:
    bar = ShrinkingBar(countdown("shrinking-bar", Rect(x=30, y=40, w=60, h=6)), 3)
    assert [bar.share(t) for t in (9.0, 10.0, 11.0, 12.0, 14.0, 20.0)] == [
        0.0, 0.0, 0.25, 0.5, 1.0, 1.0,
    ]  # fmt: skip
    moment = ShrinkingBar(
        CountdownElement(
            start=5.0, end=5.0, box=Rect(x=30, y=40, w=60, h=6), form="dots", count=1, colour="#f"
        ),
        3,
    )
    assert moment.share(5.0) == 1.0  # no life at all: over at once


def test_a_shrinking_bar_is_a_rectangle_of_its_height_and_the_state_s_width() -> None:
    bar = ShrinkingBar(countdown("shrinking-bar", Rect(x=30, y=40, w=60, h=6)), 3)
    assert bar.state(10.0) == 60 and bar.state(12.0) == stepped(60 * (1 - (1 - BAR_END) / 2), 60)
    assert bar.state(14.0) == stepped(60 * BAR_END, 60) == 3  # a step at the least
    frame = blank()
    bar.paint(frame, 21)
    rows, columns = np.nonzero(frame == 3)
    assert (rows.min(), rows.max(), columns.min(), columns.max()) == (40, 45, 30, 50)
    assert bar.box == (40, 46, 30, 90)


def test_a_bar_is_never_thinner_than_a_pixel() -> None:
    thin = ShrinkingBar(countdown("shrinking-bar", Rect(x=30, y=40, w=0.2, h=0.2)), 3)
    assert thin.box == (40, 41, 30, 31)
    assert stepped(0.5, 9) == 3 and stepped(4, 9) == 6 and stepped(40, 9) == 9
    assert stepped(0.5, 1) == 1  # never wider than the bar


def test_dots_are_discs_in_a_row_that_go_out_the_last_first() -> None:
    dots = Dots(countdown("dots", Rect(x=30, y=40, w=80, h=10)), 5)
    assert [dots.state(t) for t in (10.0, 10.9, 11.1, 12.5, 13.5, 14.0)] == [4, 4, 3, 2, 1, 0]
    assert dots.box == (40, 50, 30, 30 + 60 + 10)  # four dots 20 pixels apart, 10 wide
    frame = blank()
    dots.paint(frame, 2)
    lit = frame == 5
    assert lit[40:50, 30:40].any() and lit[40:50, 50:60].any() and not lit[:, 70:].any()
    disc = lit[40:50, 30:40]
    assert np.array_equal(disc, disc[::-1]) and np.array_equal(disc, disc[:, ::-1])
    assert np.array_equal(disc, disc.T)  # round: the same both ways
    assert disc[5].all() and disc[:, 5].all()  # the middle row and column are full
    assert not disc[0, 0] and not disc[0, 9]  # the corners are not
    assert int(disc.sum()) == 80  # the pixel centres within the radius of 5


def test_blocks_are_full_squares_and_a_dot_is_at_least_two_pixels() -> None:
    blocks = Dots(countdown("blocks", Rect(x=30, y=40, w=80, h=10)), 5)
    frame = blank()
    blocks.paint(frame, 1)
    assert (frame[40:50, 30:40] == 5).all() and int((frame == 5).sum()) == 100
    tiny = Dots(countdown("blocks", Rect(x=30, y=40, w=8, h=0.4), count=2), 5)
    assert tiny.box[1] - tiny.box[0] == 2


def test_dots_without_time_are_out() -> None:
    gone = Dots(
        CountdownElement(
            start=5.0, end=5.0, box=Rect(x=30, y=40, w=40, h=8), form="dots", count=2, colour="#f"
        ),
        5,
    )
    assert gone.state(5.0) == 0


def test_a_progress_bar_is_a_frame_with_a_fill_from_the_left() -> None:
    element = ProgressElement(
        start=10.0, end=20.0, box=Rect(x=30, y=100, w=100, h=10), fill="#fff", frame="#888"
    )
    bar = ProgressBar(element, (4, 5, 0))
    inner = 100 - 2 * 2  # the frame is a fifth of the height: two pixels
    assert bar.state(10.0) == stepped(inner * BAR_END, inner) == 3
    assert bar.state(15.0) == stepped(inner * (BAR_END + (1 - BAR_END) / 2), inner) == 51
    assert bar.state(20.0) == inner
    frame = np.full((HEIGHT, WIDTH), 9, dtype=np.uint8)
    bar.paint(frame, 30)
    box = frame[100:110, 30:130]
    assert (frame[99, 30:130] == 9).all() and (frame[110, 30:130] == 9).all()
    assert (frame[100:110, 29] == 9).all() and (frame[100:110, 130] == 9).all()
    ring = np.ones(box.shape, dtype=bool)
    ring[2:8, 2:98] = False
    assert (box[ring] == 5).all()  # the frame
    assert (box[2:8, 2:32] == 4).all()  # the fill, 30 pixels
    assert (box[2:8, 32:98] == 0).all()  # the rest of the inside is the background


# --- clipping to the visible area --------------------------------------------------------------


def test_a_mask_is_stamped_only_where_it_lies_in_the_visible_area() -> None:
    mask = np.ones((5, 7), dtype=bool)
    for top, left in ((TOP - 2, LEFT - 3), (BOTTOM - 2, RIGHT - 3), (50, 60)):
        frame = blank()
        stamp(frame, top, left, mask, 7)
        wanted = blank()
        wanted[max(top, TOP) : min(top + 5, BOTTOM), max(left, LEFT) : min(left + 7, RIGHT)] = 7
        assert np.array_equal(frame, wanted), (top, left)
    # wholly outside: nothing is drawn and nothing fails
    for top, left in ((0, 0), (-10, 60), (50, -10), (BOTTOM + 5, 60), (50, RIGHT + 5)):
        outside = blank()
        stamp(outside, top, left, np.ones((3, 3), dtype=bool), 7)
        assert not outside.any(), (top, left)


def test_a_sprite_is_cut_to_the_visible_area() -> None:
    picture = np.arange(5 * 7, dtype=np.int16).reshape(5, 7)
    for top, left in ((TOP - 2, LEFT - 3), (BOTTOM - 2, RIGHT - 3), (50, 60)):
        sprite = _crop(top, left, picture, picture + 100)
        row0, col0 = max(TOP - top, 0), max(LEFT - left, 0)
        row1, col1 = min(BOTTOM - top, 5), min(RIGHT - left, 7)
        assert (sprite.top, sprite.left) == (top + row0, left + col0)
        assert np.array_equal(sprite.unsung, picture[row0:row1, col0:col1])
        assert np.array_equal(sprite.sung, picture[row0:row1, col0:col1] + 100)
    gone = _crop(0, 0, picture, picture)
    assert (gone.top, gone.left) == (0, 0)
    assert gone.unsung.shape == gone.sung.shape == (0, 0)


# --- text --------------------------------------------------------------------------------------


class SolidRasteriser:
    """Ink everywhere: every pixel column of the text is a letter."""

    def coverage(self, text: str, size: float) -> np.ndarray:
        return np.full((round(size), len(text) * 4), 255, dtype=np.uint8)


def two_colour_palette() -> tuple[Palette, Colours, Colours]:
    scene = cdg_duet()
    palette = build_palette(scene)
    first, second = scene.lines()[0].colours, scene.lines()[1].colours
    assert first.sung != second.sung
    return palette, first, second


def test_a_pixel_column_belongs_to_the_syllable_its_centre_lies_in() -> None:
    palette, first, second = two_colour_palette()
    spec = TextSpec("abcdef", 12.0, 0.0, 100.0, 100.0)
    sprite = text_sprite(SolidRasteriser(), palette, spec, [10.0], [first, second])
    radius = 1  # an edge of zero is still drawn as one pixel
    assert sprite.unsung.shape == (12 + 2 * radius, 24 + 2 * radius)
    assert (sprite.top, sprite.left) == (100 - radius, 100 - radius)
    row = sprite.sung[6]
    assert row[radius + 9] == palette.ink(first.sung)[0]  # centre 9.5: the first syllable
    assert row[radius + 10] == palette.ink(second.sung)[0]  # centre 10.5: the second
    assert sprite.unsung[6, radius + 10] == palette.ink(second.unsung)[0]
    assert row[0] == CLEAR == sprite.unsung[0, 0]  # the edge is the background: not drawn


def test_a_wider_edge_pads_the_sprite_by_its_whole_pixels() -> None:
    palette, first, _ = two_colour_palette()
    spec = TextSpec("ab", 12.0, 2.4, 100.0, 100.0)
    sprite = text_sprite(SolidRasteriser(), palette, spec, [], [first])
    assert sprite.unsung.shape == (12 + 4, 8 + 4)


def test_an_edge_in_another_colour_than_the_background_is_drawn() -> None:
    scene = cdg_entchen(profile(colours={"singer1": {"edge": "#ff0000"}}))
    palette = build_palette(scene)
    colours = scene.lines()[0].colours
    sprite = text_sprite(
        SolidRasteriser(), palette, TextSpec("ab", 12.0, 1.0, 100, 100), [], [colours]
    )
    assert sprite.unsung[0, 0] == palette.flat("#ff0000")


def test_coverage_classes_are_small_numbers() -> None:
    classes = classify(np.array([[0, 47, 48, 127, 128, 255]], dtype=np.uint8))
    assert classes.dtype == np.uint8
    assert classes.tolist() == [[0, 0, 1, 1, 2, 2]]


def test_the_preview_line_is_drawn_in_its_own_colour() -> None:
    scene = cdg_entchen(builtin_profile("one-line-preview"))
    palette = build_palette(scene)
    targets = TargetFrames(scene, palette, FakeRasteriser())
    previews = [(e, art) for e, art in targets.arts if e.kind == "preview"]
    assert previews
    element, art = previews[0]
    frame = blank()
    art.paint(frame, art.state(element.start))
    top, bottom, left, right = art.box
    ink = palette.ink(element.line.colour)
    assert np.isin(frame[top:bottom, left:right], list(ink)).any()


def tiles_of(boxes: list[tuple[int, int, int, int]]) -> np.ndarray:
    """Return the tiles (18 by 50) that the boxes touch."""
    tiles = np.zeros((HEIGHT // TILE_HEIGHT, WIDTH // TILE_WIDTH), dtype=bool)
    for top, bottom, left, right in boxes:
        tiles[
            top // TILE_HEIGHT : (bottom - 1) // TILE_HEIGHT + 1,
            left // TILE_WIDTH : (right - 1) // TILE_WIDTH + 1,
        ] = True
    return tiles


def test_the_tiles_of_the_elements_that_appear_or_go_are_those_their_boxes_touch() -> None:
    scene = cdg_entchen()
    targets = TargetFrames(scene, build_palette(scene), FakeRasteriser())
    for line in scene.lines():
        tick = round(line.start * 100)
        moment, before = tick / 100, (tick - 1) / 100
        changing = [
            art.box
            for element, art in targets.arts
            if element.visible(moment) != element.visible(before)
        ]
        assert changing
        assert np.array_equal(targets.redrawn(tick), tiles_of(changing)), line.text


def test_a_box_that_ends_on_a_tile_edge_marks_only_the_tiles_it_covers() -> None:
    box = Rect(x=2 * TILE_WIDTH, y=2 * TILE_HEIGHT, w=12, h=12)
    bar = countdown("shrinking-bar", box).model_copy(update={"colour": "#ffffff"})
    scene = cdg_entchen().model_copy(update={"elements": [bar]})
    targets = TargetFrames(scene, build_palette(scene), FakeRasteriser())
    marked = np.argwhere(targets.redrawn(round(bar.start * 100)))
    assert marked.tolist() == [[2, 2], [2, 3]]  # one tile row, two tile columns, nothing beyond
    assert np.argwhere(targets.redrawn(round(bar.end * 100))).tolist() == [[2, 2], [2, 3]]


def test_what_is_there_at_the_first_tick_is_redrawn_and_nothing_before() -> None:
    scene = cdg_entchen()
    targets = TargetFrames(scene, build_palette(scene), FakeRasteriser())
    shown = [e for e in scene.elements if e.visible(0.0)]
    assert targets.redrawn(0).any() == bool(shown)
    assert not targets.redrawn(1).any()


# --- the palette -------------------------------------------------------------------------------


def test_the_edge_of_every_line_and_turn_gets_its_entry() -> None:
    edged = profile(colours={"singer1": {"edge": "#ff0000"}, "singer2": {"edge": "#00ff00"}})
    palette = build_palette(cdg_duet(edged))
    assert palette.entries[palette.flat("#ff0000")] == (15, 0, 0)
    assert palette.entries[palette.flat("#00ff00")] == (0, 15, 0)


def test_both_colours_of_every_progress_bar_get_an_entry() -> None:
    scene = cdg_entchen(profile(breaks={"form": "progress"}))
    bars = [e for e in scene.elements if isinstance(e, ProgressElement)]
    assert bars
    first = bars[0]
    changed = [
        e.model_copy(update={"fill": "#ff0000", "frame": "#00ff00"}) if e is first else e
        for e in scene.elements
    ]
    palette = build_palette(scene.model_copy(update={"elements": changed}))
    assert palette.entries[palette.flat("#ff0000")] == (15, 0, 0)
    assert palette.entries[palette.flat("#00ff00")] == (0, 15, 0)


def test_two_flat_colours_share_a_pair_so_seven_text_colours_still_fit() -> None:
    edge = "#ffcc00"  # the colour of the countdowns: two flat colours with the background
    scene = cdg_entchen(profile(colours={"singer1": {"edge": edge}}))
    lines = scene.lines()
    sung = ["#ff00ff", "#00ffff", "#ffff00", "#0000ff", "#00ff00"]
    changed: list[SceneElement] = []
    for element in scene.elements:
        if isinstance(element, LineElement) and element in lines:
            number = lines.index(element)
            unsung = "#888888" if number == 0 else element.colours.unsung
            colours = Colours(unsung=unsung, sung=sung[number], edge=edge)
            changed.append(element.model_copy(update={"colours": colours}))
        else:
            changed.append(element)
    palette = build_palette(scene.model_copy(update={"elements": changed}))
    assert len(palette.text_entries) == 7 and len(palette.flat_entries) == 2
    assert palette.flat(edge) == 1
    assert sorted(palette.text_entries.values()) == [2, 4, 6, 8, 10, 12, 14]


def test_the_error_lists_the_colours_one_by_one() -> None:
    scene = cdg_duet()
    changed = [
        e.model_copy(
            update={
                "colours": Colours(
                    unsung=f"#{17 * n:02x}2040", sung=f"#40{17 * n:02x}20", edge="#000000"
                )
            }
        )
        if e.kind == "line"
        else e
        for n, e in enumerate(scene.elements)
    ]
    with pytest.raises(StageError) as caught:
        build_palette(scene.model_copy(update={"elements": changed}))
    names = str(caught.value).split(": ")[-1].split(", ")
    assert all(len(name) == 7 and name.startswith("#") for name in names)


# --- the encoder -------------------------------------------------------------------------------


def tile(values: np.ndarray) -> np.ndarray:
    return values.astype(np.uint8).reshape(TILE_HEIGHT, TILE_WIDTH)


def test_a_change_by_two_values_everywhere_is_one_xor_block() -> None:
    current = tile(np.arange(TILE_HEIGHT * TILE_WIDTH) % 16)  # sixteen colours: no cheap redraw
    flips = tile(np.where(np.arange(TILE_HEIGHT * TILE_WIDTH) % 3 == 0, 4, 6))
    (op,) = plan_tile(current, tile(current ^ flips))
    assert op.xor and (op.colour0, op.colour1) == (4, 6)


def test_a_change_of_many_values_in_few_bits_is_one_block_per_bit() -> None:
    current = tile(np.arange(TILE_HEIGHT * TILE_WIDTH) % 16)
    diff = tile(np.arange(TILE_HEIGHT * TILE_WIDTH) % 4)  # values 0 to 3: two bit planes
    ops = plan_tile(current, tile(current ^ diff))
    assert [(op.xor, op.colour0, op.colour1) for op in ops] == [(True, 0, 1), (True, 0, 2)]


def test_an_area_of_one_colour_is_one_normal_block_without_pixels() -> None:
    current = tile(np.arange(TILE_HEIGHT * TILE_WIDTH) % 16)
    (op,) = plan_tile(current, np.full((TILE_HEIGHT, TILE_WIDTH), 9, dtype=np.uint8))
    assert not op.xor and (op.colour0, op.colour1) == (9, 9) and op.pixels == (0,) * TILE_HEIGHT


def test_a_tile_of_three_colours_from_noise_is_a_block_of_the_two_commonest_and_one_xor() -> None:
    current = tile(np.arange(TILE_HEIGHT * TILE_WIDTH) % 16)
    target = np.zeros((TILE_HEIGHT, TILE_WIDTH), dtype=np.uint8)
    target[:, 2:5] = 7
    target[:, 5] = 3
    block, layer = plan_tile(current, target)
    assert not block.xor and {block.colour0, block.colour1} == {0, 7}
    assert layer.xor and layer.pixels == (1,) * TILE_HEIGHT


def test_a_short_life_is_shared_out_too() -> None:
    short = CountdownElement(
        start=10.0, end=10.5, box=Rect(x=30, y=40, w=60, h=6), form="dots", count=2, colour="#f"
    )
    assert ShrinkingBar(short, 3).share(10.25) == 0.5
    assert Dots(short, 3).state(10.3) == 1


def test_a_thin_progress_bar_has_a_frame_of_one_pixel_and_a_wide_one_fills_evenly() -> None:
    thin = ProgressElement(
        start=10.0, end=20.0, box=Rect(x=30, y=100, w=100, h=5), fill="#fff", frame="#888"
    )
    frame = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    ProgressBar(thin, (4, 5, 0)).paint(frame, 30)
    assert (frame[101:104, 31:61] == 4).all() and frame[100, 31] == 5
    wide = thin.model_copy(update={"box": Rect(x=0, y=0, w=1000, h=5)})
    assert ProgressBar(wide, (4, 5, 0)).state(15.0) == stepped(998 * 0.505, 998) == 504


def test_a_progress_bar_narrower_than_its_frame_still_has_a_fill_of_one_pixel() -> None:
    narrow = ProgressElement(
        start=10.0, end=20.0, box=Rect(x=30, y=100, w=3, h=10), fill="#fff", frame="#888"
    )
    assert ProgressBar(narrow, (4, 5, 0)).state(20.0) == 1


def test_the_colour_of_a_countdown_before_a_progress_bar_keeps_its_entry() -> None:
    scene = cdg_entchen(profile(breaks={"form": "progress"}))
    bar = next(e for e in scene.elements if isinstance(e, ProgressElement))
    changed = [
        e.model_copy(update={"colour": "#00ffff"})
        if isinstance(e, CountdownElement) and e.start < bar.start
        else e
        for e in scene.elements
    ]
    assert changed != scene.elements
    palette = build_palette(scene.model_copy(update={"elements": changed}))
    assert palette.entries[palette.flat("#00ffff")] == (0, 15, 15)
