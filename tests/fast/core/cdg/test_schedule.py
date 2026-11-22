"""Stage 1: the scheduler: one packet per slot, queues by due time, lags, a tile queued once."""

from itertools import product

import numpy as np
from numpy.typing import NDArray

from vocatron.core.cdg import PACKET_SIZE, PACKETS_PER_SECOND, CdgOp, decode, parse_packets
from vocatron.core.cdg.encode import plan_tile
from vocatron.core.cdg.raster import Deadline
from vocatron.core.cdg.schedule import SLOTS_PER_TICK, Scheduled, Swap, schedule
from vocatron.core.cdg.screen import HEIGHT, TILE_COLUMNS, TILE_ROWS, WIDTH
from vocatron.core.cdg.write import load_colours, memory_preset

Frame = NDArray[np.uint8]


class Frames:
    """Targets made of frames set at ticks: a tick shows the last frame set at or before it."""

    def __init__(self, ticks: int) -> None:
        self.ticks = ticks
        self.changes: dict[int, Frame] = {0: self.blank()}
        self.drawn: dict[int, NDArray[np.bool_]] = {}
        self.deadlines: list[Deadline] = []

    @staticmethod
    def blank() -> Frame:
        return np.zeros((HEIGHT, WIDTH), dtype=np.uint8)

    def at(self, tick: int, frame: Frame, redrawn: tuple[int, int, int, int] | None = None) -> None:
        self.changes[tick] = frame
        if redrawn is not None:
            top, bottom, left, right = redrawn
            mask = np.zeros((TILE_ROWS, TILE_COLUMNS), dtype=np.bool_)
            mask[top:bottom, left:right] = True
            self.drawn[tick] = mask

    def frame(self, tick: int) -> Frame:
        return self.changes[max(t for t in self.changes if t <= tick)]

    def redrawn(self, tick: int) -> NDArray[np.bool_]:
        return self.drawn.get(tick, np.zeros((TILE_ROWS, TILE_COLUMNS), dtype=np.bool_))


def with_block(frame: Frame, tile_row: int, tile_column: int, value: int, width: int = 6) -> Frame:
    result = frame.copy()
    result[tile_row * 12 : tile_row * 12 + 12, tile_column * 6 : tile_column * 6 + width] = value
    return result


def run(frames: Frames, seconds: float, clear_first: bool = False) -> tuple[bytes, Scheduled]:
    slots = round(seconds * PACKETS_PER_SECOND)
    result = schedule(frames, [memory_preset(0)], slots, 0, clear_first)
    return result.stream, result


def test_the_stream_has_exactly_one_slot_per_packet_and_filler_where_nothing_draws() -> None:
    frames = Frames(100)
    frames.at(10, with_block(frames.frame(0), 5, 5, 3))
    stream, result = run(frames, 1.0)
    assert len(stream) == PACKETS_PER_SECOND * PACKET_SIZE
    drawing = [p.index for p in parse_packets(stream)]
    assert drawing == sorted(set(drawing))  # at most one packet per slot, in order
    assert result.drawing_packets == len(drawing) == 2  # the preset and one tile
    assert drawing[1] == SLOTS_PER_TICK * 10  # the tile goes out in the slot of its tick


def test_nothing_changing_writes_only_the_header() -> None:
    stream, result = run(Frames(100), 0.5)
    assert result.drawing_packets == 1 and result.draw_lag == result.wipe_lag == 0.0
    assert len(list(parse_packets(stream))) == 1


def tiles_sent(stream: bytes) -> list[tuple[int, int]]:
    """Return the tile of every tile packet of the stream, in order."""
    return [
        (e.row, e.column) for e in decode(stream).events if e.op in (CdgOp.TILE, CdgOp.TILE_XOR)
    ]


def test_a_tile_that_changes_again_while_it_waits_is_sent_once_with_the_newest_target() -> None:
    frames = Frames(100)
    crowd = frames.blank()
    for column in range(30):  # thirty tiles of row 1 are queued before the tile of row 2
        crowd = with_block(crowd, 1, column, 4)
    frames.at(0, with_block(crowd, 2, 2, 1))
    for tick in range(1, 4):
        frames.at(tick, with_block(frames.frame(tick - 1), 2, 2, tick + 1))
    stream, _ = run(frames, 1.0)
    assert tiles_sent(stream).count((2, 2)) == 1
    assert (decode(stream, [1.0]).frames[0] == frames.frame(3)).all()


def test_wipe_tiles_go_before_the_tiles_of_a_line_that_appears() -> None:
    frames = Frames(300)
    page = frames.blank()
    for column in range(40):  # a line of 120 tiles appears at tick 0
        for row in (6, 7, 8):
            page = with_block(page, row, column, 5)
    frames.at(0, page, (6, 9, 0, 40))
    stepped = with_block(page, 12, 3, 6)  # at tick 20 a bar step changes one tile
    frames.at(20, stepped)
    _, result = run(frames, 3.0)
    assert result.wipe_lag <= 1 / PACKETS_PER_SECOND  # it did not wait behind the line
    assert result.draw_lag > 0.3  # the 120 tiles take their time


def test_the_oldest_tile_goes_first_within_a_queue() -> None:
    frames = Frames(100)
    first = with_block(frames.frame(0), 3, 3, 2)
    second = with_block(first, 3, 4, 2)
    frames.at(0, first)
    frames.at(1, second)
    stream, _ = run(frames, 0.2)
    assert tiles_sent(stream) == [(3, 3), (3, 4)]


def test_ticks_whose_frame_was_complete_are_reported_as_settled() -> None:
    frames = Frames(100)
    frames.at(10, with_block(frames.frame(0), 4, 4, 7))
    frames.at(60, with_block(frames.frame(10), 4, 4, 1))
    stream, result = run(frames, 1.0)
    settled = result.settled
    assert 5 in settled and 9 in settled and 10 in settled and 30 in settled
    for tick in (5, 10, 30, 70):
        shown = decode(stream, [(tick + 1) / 100 - 1 / 600]).frames[0]
        assert (shown == frames.frame(tick)).all()


def test_the_lags_are_the_longest_waits_in_seconds() -> None:
    frames = Frames(100)
    page = frames.blank()
    for column in range(30):
        page = with_block(page, 6, column, 5)
    frames.at(0, page, (6, 7, 0, 30))
    _, result = run(frames, 1.0)
    assert 0.09 < result.draw_lag < 0.11  # 30 tiles and the preset, one packet each


def test_each_settled_tick_is_reported_once_in_order() -> None:
    frames = Frames(100)
    frames.at(10, with_block(frames.frame(0), 4, 4, 7))
    _, result = run(frames, 1.0)
    assert list(result.settled) == sorted(set(result.settled))
    assert 10 in result.settled and len(result.settled) <= 100


def test_a_tile_that_waits_keeps_the_due_time_it_was_first_queued_with() -> None:
    frames = Frames(100)
    crowd = frames.blank()
    for column in range(30):
        crowd = with_block(crowd, 1, column, 4)
    frames.at(0, with_block(crowd, 2, 2, 1))
    for tick in range(1, 4):
        frames.at(tick, with_block(frames.frame(tick - 1), 2, 2, tick + 1))
    stream, result = run(frames, 1.0)
    sent = [p.index for p in parse_packets(stream)]
    assert len(sent) == 32  # the preset, thirty tiles and the waiting one
    assert round(result.wipe_lag * PACKETS_PER_SECOND) == sent[-1]  # due at tick 0, not 3


def crowded(tiles: int) -> Frames:
    """Targets that change ``tiles`` tiles of row 1 at tick 10 and the tiles of row 5 at tick 12."""
    frames = Frames(100)
    crowd = frames.blank()
    for column in range(tiles):
        crowd = with_block(crowd, 1, column, 2)
    frames.at(10, crowd)
    frames.at(12, with_block(crowd, 5, 5, 3))
    return frames


def test_a_deadline_is_met_when_the_pixels_show_their_target_by_its_tick() -> None:
    frames = crowded(2)
    frames.deadlines = [Deadline(tick=40, top=12, bottom=24, left=0, right=12)]
    _, result = run(frames, 0.5)
    assert result.missed == ()


def test_a_deadline_is_missed_when_the_queue_has_not_reached_its_tiles_yet() -> None:
    frames = crowded(40)  # 40 tiles take 40 packets, more than the 6 slots to tick 12 allow
    frames.deadlines = [
        Deadline(tick=12, top=60, bottom=72, left=30, right=36),  # row 5 changes at tick 12
        Deadline(tick=60, top=60, bottom=72, left=30, right=36),  # long after
        Deadline(tick=11, top=12, bottom=24, left=234, right=240),  # the 40th tile of row 1
    ]
    _, result = run(frames, 1.0)
    assert result.missed == (2,)


# ------------------------------------ clear before draw, deadlines on the shown frame


def half_tile(frame: Frame, tile_row: int, tile_column: int, value: int, right: bool) -> Frame:
    """Return ``frame`` with one half of a tile (three columns) in ``value``."""
    result = frame.copy()
    left = tile_column * 6 + (3 if right else 0)
    result[tile_row * 12 : tile_row * 12 + 12, left : left + 3] = value
    return result


def text_page(rows: range, value: int, right: bool, columns: int = 4) -> Frame:
    """Return a frame with a half tile in ``value`` in every tile of ``rows`` by ``columns``."""
    page = Frames.blank()
    for row in rows:
        for column in range(columns):
            page = half_tile(page, row, column, value, right)
    return page


def tile_states(stream: bytes, row: int, column: int) -> list[bytes]:
    """Return the distinct pixels of one tile after each packet of the stream, in order."""
    times = [
        (index + 1) / PACKETS_PER_SECOND - 1 / (2 * PACKETS_PER_SECOND)
        for index in range(len(stream) // PACKET_SIZE)
    ]
    states: list[bytes] = []
    for frame in decode(stream, times).frames:
        tile = frame[row * 12 : row * 12 + 12, column * 6 : column * 6 + 6].tobytes()
        if not states or states[-1] != tile:
            states.append(tile)
    return states


def test_a_tile_that_shows_other_text_is_cleared_before_the_new_text_is_drawn() -> None:
    frames = Frames(100)
    frames.at(0, text_page(range(3, 5), 3, right=False), (3, 5, 0, 4))
    frames.at(30, text_page(range(3, 5), 4, right=True), (3, 5, 0, 4))
    stream, result = run(frames, 1.0, clear_first=True)
    old = text_page(range(3, 5), 3, right=False)[36:48, 0:6].tobytes()
    new = text_page(range(3, 5), 4, right=True)[36:48, 0:6].tobytes()
    blank = bytes(72)
    # the tile goes from the old text through the background to the new text: never a mix
    assert tile_states(stream, 3, 0) == [blank, old, blank, new]
    assert (decode(stream, [1.0]).frames[0] == frames.frame(30)).all()
    assert result.draw_lag > 0


def test_all_tiles_of_a_change_are_cleared_before_the_first_is_drawn_and_drawn_from_the_top() -> (
    None
):
    frames = Frames(100)
    frames.at(0, text_page(range(3, 5), 3, right=False), (3, 5, 0, 4))
    frames.at(30, text_page(range(3, 5), 4, right=True), (3, 5, 0, 4))
    stream, _ = run(frames, 1.0, clear_first=True)
    changing = tiles_sent(stream)[len(tiles_sent(stream)) - 16 :]
    # the first page took one packet a tile; the change takes a clearing and a drawing of each
    clears, draws = changing[:8], changing[8:]
    assert sorted(clears) == sorted(draws) == sorted({(r, c) for r in (3, 4) for c in range(4)})
    assert clears == sorted(clears) and draws == sorted(draws)  # row by row, from the top


def test_a_blank_tile_is_drawn_without_clearing_and_a_tile_that_goes_is_cleared_in_one_packet() -> (
    None
):
    frames = Frames(100)
    page = text_page(range(3, 4), 3, right=False, columns=1)
    frames.at(10, page, (3, 4, 0, 1))
    frames.at(50, Frames.blank(), (3, 4, 0, 1))
    stream, _ = run(frames, 1.0, clear_first=True)
    text = page[36:48, 0:6]
    assert tile_states(stream, 3, 0) == [bytes(72), text.tobytes(), bytes(72)]
    drawn = len(plan_tile(np.zeros((12, 6), dtype=np.uint8), text))
    assert tiles_sent(stream).count((3, 0)) == drawn + 1  # the draw as it is, and one to clear


def test_a_tile_waiting_to_be_wiped_is_cleared_first_when_text_appears_or_goes_there() -> None:
    frames = Frames(100)
    crowd = frames.blank()
    for column in range(30):  # thirty tiles of row 1 are queued before the tile of row 2
        crowd = with_block(crowd, 1, column, 4)
    frames.at(0, with_block(crowd, 2, 2, 1))
    frames.at(1, with_block(crowd, 2, 2, 2))  # a wipe step changes the tile
    frames.at(2, Frames.blank(), (2, 3, 2, 3))  # then the line goes (the tile is redrawn)
    stream, _ = run(frames, 1.0, clear_first=True)
    assert (decode(stream, [1.0]).frames[0] == Frames.blank()).all()


def test_a_line_that_appears_when_it_is_sung_and_is_not_drawn_yet_misses_its_deadline() -> None:
    frames = Frames(100)
    frames.at(40, text_page(range(3, 6), 3, right=False, columns=20), (3, 6, 0, 20))
    box = {"top": 36, "bottom": 72, "left": 0, "right": 120}
    frames.deadlines = [Deadline(tick=40, shown=40, **box)]  # it appears at the tick it is sung
    _, result = run(frames, 1.0, clear_first=True)
    assert result.missed == (0,)  # sixty tiles are not there yet: it is compared with itself
    frames.deadlines = [Deadline(tick=40, **box)]  # the old judgement: the frame before the tick
    _, result = run(frames, 1.0, clear_first=True)
    assert result.missed == ()  # compared with the empty screen before it, it passed


def test_a_line_is_judged_against_the_frame_it_is_shown_in_when_that_is_before_its_tick() -> None:
    frames = Frames(100)
    frames.at(30, text_page(range(3, 6), 3, right=False, columns=20), (3, 6, 0, 20))
    box = {"top": 36, "bottom": 72, "left": 0, "right": 120}
    frames.deadlines = [Deadline(tick=32, shown=30, **box), Deadline(tick=90, shown=30, **box)]
    _, result = run(frames, 1.5, clear_first=True)
    assert result.missed == (0,)  # two ticks are too few for sixty tiles, sixty ticks are enough


def test_a_line_drawn_before_it_is_sung_meets_its_deadline() -> None:
    frames = Frames(100)
    frames.at(10, text_page(range(3, 4), 3, right=False, columns=2), (3, 4, 0, 2))
    frames.deadlines = [Deadline(tick=40, top=36, bottom=48, left=0, right=12, shown=10)]
    _, result = run(frames, 1.0, clear_first=True)
    assert result.missed == ()


def test_the_wait_of_a_tile_that_only_has_to_go_counts_until_its_clearing_is_sent() -> None:
    frames = Frames(100)
    page = text_page(range(3, 4), 3, right=False, columns=1)
    frames.at(10, page, (3, 4, 0, 1))
    crowd = page
    for column in range(1, 41):  # forty tiles of a wipe go first when the line goes at tick 50
        crowd = with_block(crowd, 1, column, 4)
    frames.at(50, crowd)
    frames.at(51, with_block(crowd, 3, 0, 0), (3, 4, 0, 1))
    _, result = run(frames, 1.0, clear_first=True)
    assert result.draw_lag > 0.1  # it waited for the wipe, from its tick to the clearing


def test_a_look_that_does_not_clear_first_redraws_straight_into_the_new_text() -> None:
    frames = Frames(100)
    frames.at(0, text_page(range(3, 5), 3, right=False), (3, 5, 0, 4))
    frames.at(30, text_page(range(3, 5), 4, right=True), (3, 5, 0, 4))
    stream, result = run(frames, 1.0)
    old = text_page(range(3, 5), 3, right=False)[36:48, 0:6].tobytes()
    new = text_page(range(3, 5), 4, right=True)[36:48, 0:6].tobytes()
    assert tile_states(stream, 3, 0) == [bytes(72), old, new]  # no clearing in between
    cleared, _ = run(frames, 1.0, clear_first=True)
    assert len(tiles_sent(cleared)) > len(tiles_sent(stream))  # clearing costs packets
    assert (decode(stream, [1.0]).frames[0] == frames.frame(30)).all()
    assert result.draw_lag > 0


def wiped_then_replaced(clear_first: bool) -> tuple[list[bytes], Scheduled, Frames]:
    """A tile with text waits behind thirty wipe tiles when the text in it is replaced."""
    frames = Frames(100)
    old = text_page(range(2, 3), 3, right=False, columns=1)
    frames.at(0, old, (2, 3, 0, 1))
    crowd = old
    for column in range(1, 31):  # thirty tiles of row 1 go before the tile of row 2
        crowd = with_block(crowd, 1, column, 4)
    frames.at(20, with_block(crowd, 2, 0, 5, width=3))  # a wipe step in the tile of the text
    frames.at(21, half_tile(with_block(crowd, 2, 0, 0), 2, 0, 6, right=True), (2, 3, 0, 1))
    stream, result = run(frames, 1.0, clear_first)
    return tile_states(stream, 2, 0), result, frames


def test_a_tile_waiting_to_be_wiped_keeps_its_wait_and_shows_no_mix_when_its_text_is_replaced() -> (
    None
):
    states, result, frames = wiped_then_replaced(clear_first=True)
    old, new = (frames.frame(tick)[24:36, 0:6].tobytes() for tick in (0, 21))
    assert states == [bytes(72), old, bytes(72), new]  # cleared before the new text
    assert result.draw_lag >= 0.1  # from tick 20, behind the thirty tiles of the wipe


def test_a_line_look_redraws_a_tile_waiting_to_be_wiped_straight_into_the_new_text() -> None:
    states, _, frames = wiped_then_replaced(clear_first=False)
    old, new = (frames.frame(tick)[24:36, 0:6].tobytes() for tick in (0, 21))
    assert states == [bytes(72), old, new]  # no clearing in a line look


def test_a_deadline_looks_only_at_the_columns_of_its_line() -> None:
    frames = Frames(100)
    line = with_block(frames.blank(), 3, 5, 2)
    frames.at(10, line, (3, 4, 5, 6))
    crowd = line
    for column in range(40):  # forty tiles of rows 1 and 2 go first
        crowd = with_block(with_block(crowd, 1, column, 4), 2, column, 4)
    frames.at(20, with_block(with_block(crowd, 3, 0, 7), 3, 10, 7))  # left and right of the line
    frames.deadlines = [Deadline(tick=22, top=36, bottom=48, left=30, right=36, shown=10)]
    _, result = run(frames, 1.0)
    assert result.missed == ()  # the tiles beside it are not drawn yet, but they are not its own


# ------------------------------------------------------------------ the swap (ADR-0056)


def swap_packets() -> list[bytes]:
    return [memory_preset(0), load_colours([(1, 2, 3)] * 8, high=False)]


def test_a_swap_drops_what_waits_sends_its_packets_and_clears_the_model_screen() -> None:
    frames = Frames(200)
    title = frames.frame(0)
    for row, column in product(range(2, 10), range(TILE_COLUMNS)):
        title = with_block(title, row, column, 5)  # more tiles (400) than fit before the swap
    frames.at(0, title)
    frames.at(20, Frames.blank())  # the swap tick: the song's frames, still empty
    frames.at(20, with_block(Frames.blank(), 8, 8, 4))  # and its first tile
    slots = round(1.0 * PACKETS_PER_SECOND)
    result = schedule(frames, [memory_preset(0)], slots, 0, False, Swap(20, swap_packets()))
    packets = list(parse_packets(result.stream))
    at_swap = [p for p in packets if p.index >= 20 * SLOTS_PER_TICK]
    assert [p.instruction for p in at_swap[:2]] == [1, 30]  # the preset, then the colours
    assert at_swap[2].instruction in (6, 38)  # and the song's tile
    assert at_swap[0].index == 20 * SLOTS_PER_TICK
    drawn_before = [
        p for p in packets if p.instruction in (6, 38) and p.index < 20 * SLOTS_PER_TICK
    ]
    assert 0 < len(drawn_before) <= 20 * SLOTS_PER_TICK  # the rest of it was dropped
    final = decode(result.stream, [1.0]).frames[0]
    assert (final[: 12 * 8] == 0).all()  # the tiles of the start screen are gone
    assert (final == frames.frame(30)).all()


def test_the_lag_of_the_start_screens_tiles_is_not_counted() -> None:
    frames = Frames(200)
    screen = Frames.blank()
    for column in range(40):
        screen = with_block(screen, 4, column, 5)  # tiles the start screen draws from the start
    frames.at(0, screen)
    frames.at(100, Frames.blank())
    without = schedule(frames, [], 200, 0, False)
    with_swap = schedule(frames, [], 200, 0, False, Swap(100, [memory_preset(0)]))
    assert without.wipe_lag > 0.05  # the 40 tiles take their time
    assert with_swap.wipe_lag == with_swap.draw_lag == 0.0
