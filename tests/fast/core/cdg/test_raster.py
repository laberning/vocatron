"""Stage 1: the target frames of a CD+G scene: where ink is, the wipe, the edge, the bars."""

from typing import override

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from fakes.raster import FakeRasteriser
from fakes.scenes import builtin_profile, cdg_duet, cdg_entchen, profile
from vocatron.core.cdg.canvas import SAFE
from vocatron.core.cdg.palette import Palette, build_palette
from vocatron.core.cdg.raster import (
    DONE,
    STEP,
    TICKS_PER_SECOND,
    Art,
    TargetFrames,
    classify,
    first_tick_from,
    stepped,
    with_edge,
)
from vocatron.core.cdg.screen import HEIGHT, TILE_COLUMNS, TILE_ROWS, WIDTH
from vocatron.core.scene import (
    CountdownElement,
    LineElement,
    ProgressElement,
    Scene,
    SceneElement,
    TimerElement,
)

SAFE_TOP, SAFE_LEFT = round(SAFE.y), round(SAFE.x)
SAFE_BOTTOM, SAFE_RIGHT = round(SAFE.bottom), round(SAFE.right)


def tick(time: float) -> int:
    return round(time * TICKS_PER_SECOND)


def frames_of(scene: Scene) -> tuple[TargetFrames, Palette]:
    palette = build_palette(scene)
    return TargetFrames(scene, palette, FakeRasteriser()), palette


def art_of(targets: TargetFrames, element: SceneElement) -> Art:
    """Return the first art that draws ``element``."""
    return next(art for drawn, art in targets.arts if drawn is element)


def ink_columns(frame: np.ndarray, line: LineElement, palette: Palette) -> dict[int, set[int]]:
    """Return the palette indices of the ink and shade of each column within a line's rows."""
    top, bottom = int(line.box.y), int(line.box.bottom) + 1
    found: dict[int, set[int]] = {}
    for column in range(SAFE_LEFT, SAFE_RIGHT):
        values = {int(v) for v in frame[top:bottom, column]} - {palette.background}
        if values:
            found[column] = values
    return found


def test_the_scene_is_laid_out_on_the_cdg_screen_inside_its_visible_area() -> None:
    scene = cdg_entchen()
    assert (scene.width, scene.height, scene.safe) == (WIDTH, HEIGHT, SAFE)
    assert (SAFE.x, SAFE.y, SAFE.w, SAFE.h) == (6, 12, 288, 192)  # one tile inside the border
    for line in scene.lines():
        assert SAFE.x <= line.box.x and line.box.right <= SAFE.right
        assert SAFE.y <= line.box.y and line.box.bottom <= SAFE.bottom


def test_nothing_is_drawn_outside_the_safe_area_and_the_border_stays_the_background() -> None:
    scene = cdg_entchen()
    targets, palette = frames_of(scene)
    for second in (1, 8, 10, 12, 20, 30, 47, 55):
        frame = targets.frame(tick(second))
        outside = np.ones(frame.shape, dtype=bool)
        outside[SAFE_TOP:SAFE_BOTTOM, SAFE_LEFT:SAFE_RIGHT] = False
        assert (frame[outside] == palette.background).all()
        assert frame.shape == (HEIGHT, WIDTH)


def line_only(frame: np.ndarray, scene: Scene, background: int) -> np.ndarray:
    """Return ``frame`` with the countdowns blanked, so only the lines are left."""
    frame = frame.copy()
    for countdown in (e for e in scene.elements if isinstance(e, CountdownElement)):
        box = countdown.box
        rows = slice(int(box.y) - 1, int(box.bottom) + 2)
        frame[rows, int(box.x) - 1 : int(box.right) + 2] = background
    return frame


def test_the_ink_of_a_line_lies_inside_its_box() -> None:
    scene = cdg_entchen()
    targets, palette = frames_of(scene)
    line = scene.lines()[0]
    frame = line_only(targets.frame(tick(line.start + 0.01)), scene, palette.background)
    rows, columns = np.nonzero(frame != palette.background)
    assert len(rows) > 0
    assert rows.min() >= int(line.box.y) - 1 and rows.max() <= int(line.box.bottom) + 1
    assert columns.min() >= int(line.box.x) - 1 and columns.max() <= int(line.box.right) + 1


def test_a_line_is_on_screen_exactly_while_the_scene_says_so() -> None:
    scene = cdg_entchen()
    targets, palette = frames_of(scene)
    line = scene.lines()[1]
    before = targets.frame(tick(line.start) - 1)
    during = targets.frame(tick(line.start))
    after = targets.frame(tick(line.end))
    top, bottom = int(line.box.y), int(line.box.bottom)
    assert (before[top:bottom] == palette.background).all()
    assert (during[top:bottom] != palette.background).any()
    assert (after[top:bottom] == palette.background).all()


def test_the_wipe_moves_in_steps_of_the_step_width_and_ends_at_the_end_of_the_line() -> None:
    scene = cdg_entchen()
    targets, _ = frames_of(scene)
    line = scene.lines()[0]
    art = art_of(targets, line)
    states = [art.state(t / 100) for t in range(tick(line.sing_start) - 5, tick(line.sing_end) + 5)]
    steps = {s for s in states if s != DONE}
    assert all(s % STEP == 0 for s in steps)
    assert states == sorted(states)
    assert states[0] == 0 and states[-1] == DONE


def test_pixels_left_of_the_front_are_sung_and_right_of_it_unsung() -> None:
    scene = cdg_entchen()
    targets, palette = frames_of(scene)
    line = scene.lines()[0]
    unsung = palette.ink(line.colours.unsung)
    sung = palette.ink(line.colours.sung)
    time = (line.sing_start + line.sing_end) / 2
    frame = targets.frame(tick(time))
    front = line.wipe_front(tick(time) / 100, scene.look)
    edge = int(front // STEP) * STEP + round(line.text_x)
    columns = ink_columns(frame, line, palette)
    assert any(v & set(sung) for c, v in columns.items() if c < edge)
    assert all(v <= set(sung) for c, v in columns.items() if c < edge)
    assert all(v <= set(unsung) for c, v in columns.items() if c >= edge)
    assert any(v & set(unsung) for c, v in columns.items() if c >= edge)


def test_a_change_of_singers_inside_a_line_sweeps_in_each_singers_colour() -> None:
    scene = cdg_duet()
    targets, palette = frames_of(scene)
    (turned,) = [line for line in scene.lines() if line.turns][:1]
    (turn,) = turned.turns
    after_turn = turned.spans[turn.span].x0 + round(turned.text_x)
    time = turned.sing_end + 0.5  # all of it is sung
    frame = targets.frame(tick(time) - 1)
    columns = ink_columns(frame, turned, palette)
    first, second = palette.ink(turned.colours.sung), palette.ink(turn.colours.sung)
    assert first != second
    assert all(v <= set(first) for c, v in columns.items() if c < after_turn - 2)
    assert all(v <= set(second) for c, v in columns.items() if c > after_turn + 2)


def test_letters_get_an_edge_only_when_the_edge_colour_differs_from_the_background() -> None:
    plain_scene = cdg_entchen()
    plain, plain_palette = frames_of(plain_scene)
    line = plain_scene.lines()[0]
    plain_frame = line_only(
        plain.frame(tick(line.start + 0.01)), plain_scene, plain_palette.background
    )
    assert {int(v) for v in np.unique(plain_frame)} <= {
        plain_palette.background,
        *plain_palette.ink(line.colours.unsung),
    }  # the black edge is the background: not drawn
    red = cdg_entchen(profile(colours={"singer1": {"edge": "#ff0000"}}))
    edged, palette = frames_of(red)
    frame = line_only(edged.frame(tick(line.start + 0.01)), red, palette.background)
    edge_pixels = frame == palette.flat("#ff0000")
    assert edge_pixels.any()
    ink = np.isin(frame, palette.ink(line.colours.unsung))
    # every edge pixel touches ink or shade within the outline width (at least one pixel)
    grown = ink.copy()
    for dy in (-2, -1, 0, 1, 2):
        for dx in (-2, -1, 0, 1, 2):
            grown |= np.roll(ink, (dy, dx), axis=(0, 1))
    assert not (edge_pixels & ~grown).any()
    assert not (edge_pixels & ink).any()


def test_the_edge_is_the_ring_around_ink_and_shade() -> None:
    cover = np.zeros((5, 5), dtype=np.uint8)
    cover[2, 2] = 255
    classes = with_edge(classify(cover), 1)
    assert classes.shape == (7, 7)
    assert (classes == 3).sum() == 8 and classes[3, 3] == 2
    assert classify(np.array([[0, 47, 48, 127, 128, 255]], dtype=np.uint8)).tolist() == [
        [0, 0, 1, 1, 2, 2]
    ]


def test_the_countdown_bar_shrinks_in_steps() -> None:
    scene = cdg_entchen()
    targets, _ = frames_of(scene)
    countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
    art = art_of(targets, countdown)
    span = countdown.end - countdown.start
    widths = [art.state(countdown.start + i * span / 10) for i in range(11)]
    assert widths == sorted(widths, reverse=True)
    assert widths[0] == round(countdown.box.w) > widths[-1] >= 1
    assert all(w % STEP == 0 for w in widths[1:-1])


def test_the_dots_go_out_one_per_beat_the_last_first() -> None:
    scene = cdg_entchen(profile(countdown={"form": "dots"}))
    targets, _ = frames_of(scene)
    countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
    assert countdown.beat is not None and countdown.count == 4
    art = art_of(targets, countdown)
    lit = [art.state(countdown.start + (n + 0.5) * countdown.beat) for n in range(countdown.count)]
    assert lit == [4, 3, 2, 1]


def test_blocks_are_squares_and_dots_are_round() -> None:
    shapes = {}
    for form in ("dots", "blocks"):
        scene = cdg_entchen(profile(countdown={"form": form}))
        targets, palette = frames_of(scene)
        countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
        frame = targets.frame(tick(countdown.start + 0.01))
        shapes[form] = int((frame == palette.flat(countdown.colour)).sum())
    assert shapes["dots"] < shapes["blocks"]


def test_progress_bars_fill_from_the_left() -> None:
    scene = cdg_entchen(profile(breaks={"form": "progress"}))
    targets, _ = frames_of(scene)
    bar = next(e for e in scene.elements if isinstance(e, ProgressElement))
    art = art_of(targets, bar)
    fills = [art.state(bar.start + i * (bar.end - bar.start) / 8) for i in range(9)]
    assert fills == sorted(fills) and fills[0] < fills[-1]


class NumberedRasteriser(FakeRasteriser):
    """Draws a number as a bar at a column that depends on the number, so every number differs."""

    @override
    def coverage(self, text: str, size: float) -> np.ndarray:
        image = super().coverage(text, size)
        if text.isdigit():
            image[:] = 0
            image[:, int(text) % image.shape[1]] = 255
        return image


def test_the_timer_shows_the_seconds_left() -> None:
    scene = cdg_entchen(builtin_profile("three-line"))
    timer = next(e for e in scene.elements if isinstance(e, TimerElement))
    palette = build_palette(scene)
    targets = TargetFrames(scene, palette, NumberedRasteriser())
    art = art_of(targets, timer)
    palette.ink(timer.colour)  # the timer's colour is one of the text colours (no KeyError)
    top, bottom, left, right = art.box
    inside = np.zeros((HEIGHT, WIDTH), dtype=bool)
    inside[top:bottom, left:right] = True
    assert top >= timer.box.y - 1 and bottom <= timer.box.bottom + 1  # in the timer's tiles
    seen: list[tuple[int, np.ndarray]] = []
    for step in range(int((timer.end - timer.start) * 10)):  # every tenth of a second
        time = timer.start + step / 10 + 0.05
        left_now = timer.seconds_left(time)
        assert art.state(time) == left_now
        frame = targets.frame(tick(time))
        if not seen or seen[-1][0] != left_now:
            seen.append((left_now, frame))
    assert [n for n, _ in seen] == list(range(timer.total, 0, -1))  # the digits change per second
    for (_, before), (_, after) in zip(seen, seen[1:], strict=False):
        differing = before != after
        assert differing.any()  # each number looks different from the one before
        assert not (differing & ~inside).any()  # and only the timer's own pixels change


def test_a_second_of_the_timer_is_one_frame() -> None:
    scene = cdg_entchen(builtin_profile("three-line"))
    timer = next(e for e in scene.elements if isinstance(e, TimerElement))
    targets, _ = frames_of(scene)
    first, last = timer.start + 0.1, timer.changes()[0] - 0.05
    assert targets.frame(tick(first)) is targets.frame(tick(last))  # the same array: no change
    after = targets.frame(tick(timer.changes()[0] + 0.02))
    assert after is not targets.frame(tick(first))
    appear = targets.redrawn(tick(timer.start))
    assert appear.any()  # the timer appears with the screen: its tiles are redrawn


def test_redrawn_tiles_are_those_of_the_elements_that_appear_or_go() -> None:
    scene = cdg_entchen()
    targets, _ = frames_of(scene)
    line = scene.lines()[0]
    appear = targets.redrawn(tick(line.start))
    assert appear.shape == (TILE_ROWS, TILE_COLUMNS) and appear.any()
    top, left = int(line.box.y) // 12, int(line.box.x) // 6
    assert appear[top : top + 3, left : left + 3].any()
    assert not targets.redrawn(tick(line.start) + 7).any()  # nothing appears or goes


def test_a_frame_is_shared_while_nothing_changes() -> None:
    targets, _ = frames_of(cdg_entchen())
    assert targets.frame(tick(3.0)) is targets.frame(tick(3.0) + 1)
    assert targets.ticks == tick(60.0) + 1


def test_the_title_card_is_text_in_the_middle_of_the_screen_and_is_gone_after_it() -> None:
    targets, palette = frames_of(cdg_entchen())
    drawn = targets.frame(tick(2.0)) != palette.background
    rows = np.nonzero(drawn.any(axis=1))[0]
    assert rows.min() >= SAFE_TOP and rows.max() < SAFE_BOTTOM
    middle = (SAFE_TOP + SAFE_BOTTOM) / 2
    assert rows.min() < middle < rows.max()
    assert not (targets.frame(tick(6.0) - 1) != targets.frame(tick(2.0))).any()
    later = targets.frame(tick(6.1)) != palette.background
    assert not later[: SAFE_TOP + 80].any()  # the title is gone; the lines are in the lower third


@pytest.mark.parametrize("step", [1, 2, 3, 6])
def test_the_wipe_the_bars_and_the_progress_fill_move_in_the_looks_step(step: int) -> None:
    scene = cdg_entchen(profile(breaks={"form": "progress"}))
    targets = TargetFrames(scene, build_palette(scene), FakeRasteriser(), step)
    line = scene.lines()[0]
    wipe = {
        art_of(targets, line).state(t / 100)
        for t in range(tick(line.sing_start), tick(line.sing_end) + 5)
    } - {DONE}
    assert wipe and all(s % step == 0 for s in wipe)
    countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
    span = countdown.end - countdown.start
    bar = [art_of(targets, countdown).state(countdown.start + i * span / 20) for i in range(1, 20)]
    assert all(w % step == 0 or w == round(countdown.box.w) for w in bar)
    progress = next(e for e in scene.elements if isinstance(e, ProgressElement))
    fill = [
        art_of(targets, progress).state(progress.start + i * (progress.end - progress.start) / 20)
        for i in range(1, 20)
    ]
    assert all(f % step == 0 or f >= round(progress.box.w) - 12 for f in fill)


def test_a_coarser_step_changes_fewer_tiles_of_the_picture() -> None:
    scene = cdg_entchen()
    palette = build_palette(scene)

    def changes(step: int) -> int:
        targets = TargetFrames(scene, palette, FakeRasteriser(), step)
        line = scene.lines()[0]
        frames = [targets.frame(t) for t in range(tick(line.sing_start), tick(line.sing_end))]
        return sum(not np.array_equal(a, b) for a, b in zip(frames, frames[1:], strict=False))

    assert changes(1) > changes(3) > changes(6) > 0


def test_stepped_rounds_up_to_the_step_inside_one_and_the_width() -> None:
    assert [stepped(w, 100, 6) for w in (0.2, 6, 6.1, 99, 200)] == [6, 6, 12, 100, 100]
    assert stepped(5, 100) == 6  # three by default
    assert stepped(0.0, 100, 1) == 1


def test_a_deadline_holds_the_box_of_its_line_its_first_syllable_and_the_tick_it_appears() -> None:
    scene = cdg_entchen()
    targets, _ = frames_of(scene)
    lines = scene.lines()
    assert len(targets.deadlines) == len(lines)
    on_a_tick = 0
    for line, deadline in zip(lines, targets.deadlines, strict=True):
        box = art_of(targets, line).box
        assert (deadline.top, deadline.bottom, deadline.left, deadline.right) == box
        assert deadline.tick == int(line.sing_start * TICKS_PER_SECOND)
        # the first tick at or after the line's start: the first frame that shows it
        assert deadline.shown / TICKS_PER_SECOND >= line.start - 1e-9
        assert (deadline.shown - 1) / TICKS_PER_SECOND < line.start
        on_a_tick += deadline.shown == line.start * TICKS_PER_SECOND
    assert on_a_tick > 0  # a start on a tick is not rounded up to the next one


# ------------------------------------------------------------------ the start screen's swap tick


@given(st.floats(min_value=0.0, max_value=600.0, allow_nan=False))
def test_the_first_tick_of_the_song_is_the_first_whose_time_is_not_before_the_end(
    seconds: float,
) -> None:
    tick = first_tick_from(seconds)
    assert tick / TICKS_PER_SECOND >= seconds
    assert tick == 0 or (tick - 1) / TICKS_PER_SECOND < seconds


@pytest.mark.parametrize(
    ("seconds", "tick"), [(0.0, 0), (0.001, 1), (0.07, 7), (0.29, 29), (4.0, 400), (4.001, 401)]
)
def test_the_first_tick_from_a_time_on_examples(seconds: float, tick: int) -> None:
    assert first_tick_from(seconds) == tick  # 0.07 * 100 is 7.000000000000001 in floats


def test_a_scene_without_the_pixel_title_has_no_swap_tick() -> None:
    scene = cdg_entchen()
    assert TargetFrames(scene, build_palette(scene), FakeRasteriser()).swap_tick is None
