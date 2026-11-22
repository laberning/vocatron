"""Stage 1: the CD+G analysis of titles, partial wipes, countdowns and bars (numbers only)."""

from collections import Counter

import pytest

from fakes.cdg import (
    BLANK,
    FILL,
    FULL,
    OUTLINE,
    SOLID,
    CdgBuilder,
    draw_line,
    draw_outline_line,
    erase_line,
    filler,
    measure,
    memory_preset,
    scroll,
    tile,
    wipe_line,
)
from vocatron.core.cdg import PACKETS_PER_SECOND, TILE_WIDTH, decode
from vocatron.lab.cdg.analysis import group_lines, line_stats, passes
from vocatron.lab.cdg.tracking import track


def test_static_text_two_tile_rows_high_is_one_title_line_if_drawn_together() -> None:
    builder = CdgBuilder().at(0.5).add(*draw_line(2, 10, 39), *draw_line(3, 10, 39))
    builder.at(2.0).add(*draw_line(6, 10, 39))  # a second title line, drawn later
    builder.at(3.0).add(*draw_line(9, 10, 30))
    builder.at(3.5).add(*erase_line(2, 10, 39), *erase_line(3, 10, 39), *erase_line(6, 10, 39))
    wipe_line(builder, 4.0, 9, 10, 30)
    title = measure(builder.end(8.0), 8.0).title
    assert title is not None
    assert (title.lines, title.rows) == (2, (2, 3, 6))
    assert title.cleared_at == pytest.approx(3.5, abs=0.4)
    assert title.lyrics_from == pytest.approx(3.0)


def test_rows_that_were_not_on_the_screen_together_are_not_one_line() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 10, 39)).at(1.2).add(*erase_line(5, 10, 39))
    builder.at(1.4).add(*draw_line(6, 10, 39))
    groups = group_lines(track(decode(builder.end(3.0)).events).sessions)
    assert len(groups) == 2


def test_the_title_is_wide_static_text_drawn_before_the_first_line() -> None:
    builder = CdgBuilder().at(0.5).add(*draw_line(1, 1, 8))  # eight columns: a logo, no title
    builder.at(2.0).add(*draw_line(9, 10, 30))
    builder.at(2.5).add(*draw_line(12, 10, 39))  # a notice drawn after the first line
    wipe_line(builder, 4.0, 9, 10, 30)
    assert measure(builder.end(8.0), 8.0).title is None


def test_a_two_row_line_ends_when_its_last_row_goes_and_stays_open_while_one_remains() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 12), *draw_line(6, 8, 12))
    for column in range(8, 13):
        builder.at(3.0 + 0.1 * (column - 8)).add(
            tile(5, column, SOLID, 0, 1, xor=True), tile(6, column, SOLID, 0, 1, xor=True)
        )
    builder.at(5.0).add(*erase_line(6, 8, 12))
    open_line = measure(builder.end(6.0), 6.0).lines[0]
    assert (open_line.rows, open_line.end, open_line.end_kind) == ((5, 6), None, "open")
    builder.at(6.0).add(*draw_line(5, 8, 12, colour1=4))
    replaced = measure(builder.end(7.0), 7.0).lines[0]
    assert replaced.end_kind == "replaced"
    assert replaced.end == pytest.approx(6.0 + 4 / 300)


def test_a_wipe_in_two_halves_per_tile_advances_a_tile_per_step() -> None:
    top, bottom = (FULL,) * 6 + (0,) * 6, (0,) * 6 + (FULL,) * 6
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 12))
    for step, column in enumerate(range(8, 13)):
        builder.at(3.0 + 0.2 * step).add(tile(5, column, top, 0, 1, xor=True))
        builder.at(3.1 + 0.2 * step).add(tile(5, column, bottom, 0, 1, xor=True))
    line = measure(builder.end(6.0), 6.0).lines[0]
    assert (line.wipe_steps, line.wipe_step_px) == (10, 6)


def test_a_line_wiped_at_once_or_on_the_spot_has_no_speed() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 12), *draw_line(8, 8, 8))
    builder.at(3.0).add(*[tile(5, c, SOLID, 0, 3) for c in range(8, 13)])  # one recolour step
    builder.at(4.0).add(tile(8, 8, (FULL,) * 6 + (0,) * 6, 0, 1, xor=True))
    builder.at(4.5).add(tile(8, 8, (0,) * 6 + (FULL,) * 6, 0, 1, xor=True))
    at_once, on_the_spot = (
        line_stats(group) for group in group_lines(track(decode(builder.end(6.0)).events).sessions)
    )
    assert (at_once.wipe_steps, at_once.wipe_step_px, at_once.wipe_speed) == (1, None, None)
    assert (on_the_spot.wipe_steps, on_the_spot.wipe_step_px, on_the_spot.wipe_speed) == (
        2,
        None,
        None,
    )


def test_a_line_that_changes_colour_in_one_step_is_no_sung_line() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 19), *draw_line(8, 8, 9))
    builder.at(2.0).add(*[tile(5, c, SOLID, 0, 3, xor=True) for c in range(8, 20)])  # a fade
    for blink in range(3):  # a mark that blinks in a notice, once a second
        builder.at(3.0 + blink).add(*[tile(8, c, SOLID, 0, 1, xor=True) for c in (8, 9)])
    builder.at(6.0).add(*draw_line(10, 8, 20))
    wipe_line(builder, 8.0, 10, 8, 20)
    builder.at(8.1).add(tile(10, 9, SOLID, 0, 1, xor=True))  # stray: XOR of a wiped tile
    result = measure(builder.end(11.0), 11.0)
    assert [line.rows for line in result.lines] == [(10,)]
    assert result.gaps[0].length == pytest.approx(8.0)


@pytest.mark.parametrize(("delay", "rows"), [(1, [(5, 6)]), (3, [(5, 6)]), (4, [(6,)])])
def test_a_tile_wiped_in_one_step_packets_before_the_line_below_joins_it(
    delay: int, rows: list[tuple[int, ...]]
) -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 9), *draw_line(6, 8, 20))
    builder.at(2.0).add(*[tile(5, c, SOLID, 0, 1, xor=True) for c in (8, 9)])
    builder.add(*[filler() for _ in range(delay - 1)])
    wipe_line(builder, 2.0 + delay / PACKETS_PER_SECOND, 6, 8, 20)
    result = measure(builder.end(5.0), 5.0)
    assert [line.rows for line in result.lines] == rows


def test_a_tile_wiped_in_one_step_far_from_where_the_next_line_starts_stays_apart() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 20), *draw_line(6, 19, 20))
    builder.add(*draw_line(7, 8, 20))
    wipe_line(builder, 2.0, 5, 8, 20)
    builder.add(*[tile(6, c, SOLID, 0, 1, xor=True) for c in (19, 20)])  # a packet later
    wipe_line(builder, 3.2 + 3 / PACKETS_PER_SECOND, 7, 8, 20)  # a packet after the descender
    result = measure(builder.end(6.0), 6.0)
    assert [line.rows for line in result.lines] == [(5, 6), (7,)]


@pytest.mark.parametrize(("column", "rows"), [(10, [(5, 6)]), (11, [(6,)])])
def test_a_single_tile_wiped_in_one_step_joins_up_to_two_tiles_from_the_highlight(
    column: int, rows: list[tuple[int, ...]]
) -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, column, column), *draw_line(6, 8, 20))
    builder.at(2.0).add(tile(5, column, SOLID, 0, 1, xor=True))  # one sample in the row above
    wipe_line(builder, 2.0 + 1 / PACKETS_PER_SECOND, 6, 8, 20)  # starts two or three tiles left
    result = measure(builder.end(5.0), 5.0)
    assert [line.rows for line in result.lines] == rows


@pytest.mark.parametrize("last", [9, 12])  # two steps or five
def test_a_line_wiped_in_steps_just_before_the_line_below_stays_apart(last: int) -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, last), *draw_line(6, 8, 20))
    wipe_line(builder, 2.0 - (last - 8) * 0.1, 5, 8, last)  # the last sample at 2.0 s
    wipe_line(builder, 2.0 + 1 / PACKETS_PER_SECOND, 6, 8, 20)
    result = measure(builder.end(5.0), 5.0)
    assert [line.rows for line in result.lines] == [(5,), (6,)]


def test_a_line_wiped_only_in_part_is_no_sung_line() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 30), *draw_line(8, 8, 30))
    wipe_line(builder, 2.0, 5, 8, 15)  # a third of it, at an ordinary pace
    wipe_line(builder, 5.0, 8, 8, 30)
    result = measure(builder.end(9.0), 9.0)
    assert [line.rows for line in result.lines] == [(8,)]


def test_an_xor_with_another_colour_or_long_after_the_wipe_on_an_empty_tile_is_new_text() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 9, colour1=2))
    wipe_line(builder, 3.0, 5, 8, 9)
    builder.at(3.3).add(tile(5, 10, SOLID, 0, 5, xor=True))  # another XOR colour: text
    result = track(decode(builder.end(6.0)).events)
    assert [(w.frontier, w.pixels) for w in result.sessions[0].wipes] == [(54, 72), (60, 72)]
    assert [s.tiles for s in result.sessions] == [2, 1]
    late = CdgBuilder().at(1.0).add(*draw_line(5, 8, 9, colour1=2))
    wipe_line(late, 3.0, 5, 8, 9)
    late.at(4.0).add(tile(5, 10, SOLID, 0, 1, xor=True))  # the wipe colour, but 0.9 s later
    assert len(track(decode(late.end(6.0)).events).sessions) == 2


def test_a_wipe_running_on_past_the_text_adds_samples_without_changing_the_colours() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 10, colour1=4))
    wipe_line(builder, 3.0, 5, 8, 13)  # the highlight runs past the text on columns 11 to 13
    builder.at(4.0).add(*draw_line(8, 8, 12))
    wipe_line(builder, 6.0, 8, 8, 12)
    result = measure(builder.end(8.0), 8.0)
    assert [(line.unsung, line.sung) for line in result.lines] == [(4, 5), (2, 3)]
    assert result.lines[0].wipe_steps == 6
    assert {(s.unsung.index, s.sung.index) for s in result.singers} == {(4, 5), (2, 3)}


@pytest.mark.parametrize(
    ("first", "widths", "kind"),
    [
        ([8, 8, 8, 8], [30, 20, 10, 25], "left"),
        ([10, 20, 30, 15], [30, 20, 10, 25], "right"),
        ([15, 15, 15], [20, 20, 20], "centred"),
    ],
)
def test_the_alignment_is_the_edge_that_varies_least(
    first: list[int], widths: list[int], kind: str
) -> None:
    builder = CdgBuilder()
    for turn, (left, width) in enumerate(zip(first, widths, strict=True)):
        builder.at(1.0 + 4 * turn).add(*draw_line(3 + 3 * turn, left, left + width - 1))
        wipe_line(builder, 1.5 + 4 * turn, 3 + 3 * turn, left, left + width - 1)
    assert measure(builder.end(20.0), 20.0).alignment.kind == kind


def test_a_countdown_after_the_title_and_before_the_first_line_is_found_in_the_intro() -> None:
    builder = CdgBuilder().at(0.5).add(*draw_line(4, 10, 39))
    builder.at(3.0).add(*erase_line(4, 10, 39))
    for tick in range(3):  # exactly three ticks, each eight columns wide
        builder.at(5.0 + tick).add(*draw_line(2, 8 * tick, 8 * tick + 7))
    builder.at(7.5).add(*draw_line(9, 10, 30))
    wipe_line(builder, 8.5, 9, 10, 30)
    countdown = measure(builder.end(12.0), 12.0).gaps[0].countdown
    assert countdown is not None
    assert (countdown.ticks, countdown.left_column, countdown.length) == (3, 0, pytest.approx(3.5))


@pytest.mark.parametrize(
    ("times", "columns", "width", "ticks"),
    [
        ([5.0, 6.0], [1, 2], 1, None),  # two ticks are too few
        ([5.0, 6.0, 7.0], [1, 2, 3], 9, None),  # ticks wider than a countdown
        ([5.0, 6.0, 7.0], [1, 20, 40], 1, None),  # ticks far apart on the screen
        ([5.0, 6.0, 7.0, 7.3, 7.6], [1, 2, 3, 4, 5], 1, 3),  # the rhythm breaks after three
        ([5.0, 5.2, 5.4], [1, 2, 3], 1, None),  # too fast for a countdown
        ([5.0, 5.5, 6.0, 6.25, 6.5], [1, 2, 3, 4, 5], 1, 3),  # half-second ticks, then faster
    ],
)
def test_changes_that_are_no_countdown_or_only_partly(
    times: list[float], columns: list[int], width: int, ticks: int | None
) -> None:
    builder = CdgBuilder()
    for time, column in zip(times, columns, strict=True):
        builder.at(time).add(*draw_line(2, column, column + width - 1))
    builder.at(8.0).add(*draw_line(9, 10, 30))
    wipe_line(builder, 9.0, 9, 10, 30)
    countdown = measure(builder.end(12.0), 12.0).gaps[0].countdown
    assert (None if countdown is None else countdown.ticks) == ticks


def test_regular_draws_after_the_last_line_are_no_countdown() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(9, 10, 30))
    wipe_line(builder, 2.0, 9, 10, 30)
    for tick in range(4):
        builder.at(6.0 + tick).add(tile(2, 1 + tick, SOLID, 0, 2))
    outro = measure(builder.end(12.0), 12.0).gaps[-1]
    assert (outro.kind, outro.other_changes, outro.countdown) == ("outro", 4, None)


@pytest.mark.parametrize(("h", "v", "row", "column"), [(0, 1, 17, 5), (1, 0, 5, 49)])
def test_a_scroll_preset_drops_text_that_crosses_one_edge(
    h: int, v: int, row: int, column: int
) -> None:
    builder = CdgBuilder().at(1.0).add(tile(row, column, SOLID, 0, 2)).at(2.0).add(scroll(h, v))
    assert track(decode(builder.end(3.0)).events).sessions[0].end_kind == "scrolled"


def test_text_drawn_on_after_a_scroll_stays_one_session() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(14, 8, 10)).add(scroll(v_command=2))
    builder.add(*draw_line(13, 11, 13))
    result = track(decode(builder.end(2.0)).events)
    assert [s.tiles for s in result.sessions] == [6]


def test_a_gap_opens_only_when_every_line_sung_together_has_been_wiped() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 40)).at(1.2).add(*draw_line(8, 8, 10))
    samples = [(3.0 + 0.1 * i, 5, 8 + i) for i in range(33)]  # a long line, 3.0 to 6.2 s
    samples += [(3.05 + 0.1 * i, 8, 8 + i) for i in range(3)]  # a short one sung with it
    for time, row, column in sorted(samples):
        builder.at(time).add(tile(row, column, SOLID, 0, 1, xor=True))
    builder.at(8.0).add(*draw_line(11, 8, 20))
    wipe_line(builder, 14.0, 11, 8, 20)
    builder.at(16.0).add(*draw_line(14, 8, 10), *draw_line(16, 8, 8))
    builder.at(18.0).add(tile(14, 8, SOLID, 0, 1, xor=True))
    builder.at(18.5).add(tile(16, 8, SOLID, 0, 1, xor=True))  # the short one ends first
    builder.at(19.0).add(tile(14, 9, SOLID, 0, 1, xor=True))
    builder.at(20.0).add(tile(14, 10, SOLID, 0, 1, xor=True))
    result = measure(builder.end(30.0), 30.0)
    between = [(g.start, g.end, g.is_break) for g in result.gaps if g.kind == "between"]
    assert between[0] == (pytest.approx(6.2), pytest.approx(14.0), False)
    outro = result.gaps[-1]
    assert (outro.kind, outro.start) == ("outro", pytest.approx(20.0))
    assert result.ending == pytest.approx(30.0 - outro.start)


def test_a_line_wiped_in_two_steps_of_three_pixels_has_a_speed() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 8))
    builder.at(3.0).add(tile(5, 8, (0b111000,) * 12, 0, 1, xor=True))
    builder.at(3.5).add(tile(5, 8, (0b000111,) * 12, 0, 1, xor=True))
    line = measure(builder.end(5.0), 5.0).lines[0]
    assert (line.wipe_steps, line.wipe_step_px, line.wipe_sample_px) == (2, 3, 3)
    assert line.wipe_speed == pytest.approx(3 / 0.5)


def test_the_colour_counters_count_each_tile_once_and_composing_moves_its_count() -> None:
    builder = (
        CdgBuilder()
        .at(1.0)
        .add(*[tile(5, c, OUTLINE, 0, 1) for c in range(8, 13)], *draw_line(5, 13, 14))
    )
    builder.at(1.1).add(*[tile(5, c, FILL, 0, 3, xor=True) for c in range(8, 12)])
    session = track(decode(builder.end(2.0)).events).sessions[0]
    assert session.backgrounds == Counter({0: 7})
    # four composed (fill 3, edge 1), one ring left alone (1), two drawn in 2
    assert session.unsungs == Counter({3: 4, 1: 1, 2: 2})
    assert session.edges == Counter({1: 4})


def test_a_gap_of_exactly_the_break_length_is_a_break() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 9), *draw_line(8, 8, 9))
    wipe_line(builder, 2.9, 5, 8, 9)
    wipe_line(builder, 11.0, 8, 8, 9)
    between = measure(builder.end(12.0), 12.0).gaps[1]
    assert (between.kind, between.length, between.is_break) == ("between", 8.0, True)


@pytest.mark.parametrize("irregular", [False, True])
def test_a_bar_wiped_at_an_even_pace_through_a_break_is_a_progress_bar_not_a_line(
    irregular: bool,
) -> None:
    builder = CdgBuilder().at(0.5).add(*draw_line(3, 10, 30), *draw_line(8, 1, 48))
    wipe_line(builder, 2.0, 3, 10, 30)  # an even line too, but only 2.1 s long
    for step, column in enumerate(range(1, 49)):  # one tile per 0.2 s, 9.4 s in all
        late = 0.15 if irregular and column == 24 else 0.0
        builder.at(5.0 + 0.2 * step + late).add(tile(8, column, SOLID, 0, 1, xor=True))
    builder.at(13.0).add(*draw_line(12, 10, 30))
    wipe_line(builder, 15.0, 12, 10, 30)
    result = measure(builder.end(18.0), 18.0)
    if irregular:  # no longer even: a (slow) sung line
        assert [line.rows for line in result.lines] == [(3,), (8,), (12,)]
        assert all(gap.bar is None for gap in result.gaps)
        return
    assert [line.rows for line in result.lines] == [(3,), (12,)]
    between = result.gaps[1]
    assert (between.kind, between.is_break) == ("between", True)
    assert between.bar == pytest.approx(9.4, abs=0.01)
    assert result.gaps[0].bar is None


def test_colours_changing_in_place_or_a_crawling_highlight_are_no_sung_line() -> None:
    builder = CdgBuilder().at(0.5).add(*draw_line(5, 8, 20), *draw_line(7, 8, 8))
    builder.at(2.0).add(tile(5, 8, SOLID, 0, 1, xor=True))  # one tile of 13 changes colour
    for step in range(6):  # one pixel column per second: 1 px/s
        builder.at(2.0 + step).add(tile(7, 8, (0b100000 >> step,) * 12, 0, 1, xor=True))
    builder.at(9.0).add(*draw_line(12, 10, 30))
    wipe_line(builder, 10.0, 12, 10, 30)
    result = measure(builder.end(14.0), 14.0)
    assert [line.rows for line in result.lines] == [(12,)]
    assert result.gaps[0].length == pytest.approx(10.0)


def test_a_row_shared_by_two_lines_is_wiped_twice_and_joins_each_of_them() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(4, 8, 20), *draw_line(5, 8, 20))
    builder.add(*draw_line(6, 8, 20))  # row 5: descenders of one line, ascenders of the next
    for first, rows in ((2.0, (4, 5)), (4.0, (5, 6))):
        for step, column in enumerate(range(8, 21)):
            builder.at(first + 0.1 * step).add(
                *[tile(row, column, SOLID, 0, 1, xor=True) for row in rows]
            )
    result = measure(builder.end(7.0), 7.0)
    assert [line.rows for line in result.lines] == [(4, 5), (5, 6)]
    assert result.lines_per_screen_max == 2


def test_a_short_line_sharing_a_row_with_a_long_one_is_as_wide_as_its_own_part() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(7, 19, 28), *draw_line(8, 19, 28))
    builder.add(*draw_line(9, 8, 38), *draw_line(10, 8, 38))  # row 9: shared by both lines
    for step, column in enumerate(range(19, 29)):
        builder.at(2.0 + 0.1 * step).add(
            *[tile(r, column, SOLID, 0, 1, xor=True) for r in (7, 8, 9)]
        )
    for step, column in enumerate(range(8, 39)):
        builder.at(4.0 + 0.1 * step).add(*[tile(r, column, SOLID, 0, 1, xor=True) for r in (9, 10)])
    stream = builder.end(9.0)
    shared = next(s for s in track(decode(stream).events).sessions if s.rows == {9})
    assert [(part.left, part.right) for part in passes(shared)] == [(114, 174), (48, 234)]
    short, long = measure(stream, 9.0).lines
    assert (short.rows, short.left, short.right) == ((7, 8, 9), 19 * TILE_WIDTH, 29 * TILE_WIDTH)
    assert (long.rows, long.left, long.right) == ((9, 10), 8 * TILE_WIDTH, 39 * TILE_WIDTH)


def test_a_descender_wiped_in_one_sample_during_the_line_joins_it() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 20), *draw_line(6, 14, 14))
    wipe_line(builder, 2.0, 5, 8, 13)
    builder.add(tile(6, 14, SOLID, 0, 1, xor=True))  # with column 14 of row 5
    wipe_line(builder, 2.6, 5, 14, 20)
    result = measure(builder.end(5.0), 5.0)
    assert [line.rows for line in result.lines] == [(5, 6)]


def test_dots_drawn_and_erased_by_xor_on_a_filled_background_are_a_countdown() -> None:
    builder = CdgBuilder().at(0.5).add(memory_preset(12))
    builder.at(1.0).add(*[tile(2, c, SOLID, 0, 7, xor=True) for c in range(1, 5)])  # 12 ^ 7
    for tick, column in enumerate(range(1, 5)):  # 11 ^ 7 = 12: the dot is gone
        builder.at(4.5 + tick).add(tile(2, column, SOLID, 0, 7, xor=True))
    builder.at(8.0).add(*[tile(9, c, SOLID, 0, 7, xor=True) for c in range(10, 31)])
    wipe_line(builder, 9.0, 9, 10, 30, flip=4)
    result = measure(builder.end(12.0), 12.0)
    countdown = result.gaps[0].countdown
    assert countdown is not None
    assert (countdown.ticks, countdown.draws, countdown.erases) == (4, 0, 4)
    assert (result.lines[0].unsung, result.lines[0].sung) == (11, 15)


def test_wide_text_that_stays_through_the_first_wipe_is_a_notice_not_a_title() -> None:
    builder = CdgBuilder().at(0.5).add(*draw_line(2, 10, 39))
    builder.at(2.0).add(*draw_line(9, 10, 30))
    wipe_line(builder, 3.0, 9, 10, 30)
    assert measure(builder.end(6.0), 6.0).title is None


def test_text_xor_ed_onto_a_flat_box_takes_the_box_as_its_background() -> None:
    builder = CdgBuilder().at(0.5).add(*[tile(5, c, BLANK, 5, 5) for c in range(8, 13)])
    builder.at(1.0).add(*[tile(5, c, OUTLINE, 0, 3, xor=True) for c in range(8, 13)])  # 5 ^ 3
    wipe_line(builder, 2.0, 5, 8, 12, pixels=OUTLINE)  # 6 ^ 1 = 7
    result = measure(builder.end(4.0), 4.0)
    assert (result.lines[0].unsung, result.lines[0].sung) == (6, 7)
    assert result.palette.background is not None
    assert result.palette.background.index == 5


def test_a_normal_tile_of_another_shape_or_over_a_composed_tile_is_new_text() -> None:
    builder = CdgBuilder().at(1.0).add(*[tile(5, c, OUTLINE, 0, 1) for c in range(8, 11)])
    builder.at(3.0).add(*[tile(5, c, FILL, 0, 4) for c in range(8, 11)])  # another shape
    shapes = track(decode(builder.end(4.0)).events)
    assert ([s.end_kind for s in shapes.sessions], shapes.sessions[0].wipes) == (
        ["replaced", "open"],
        [],
    )
    composed = CdgBuilder().at(1.0).add(*draw_outline_line(5, 8, 10, outline=1, fill=3))
    composed.at(3.0).add(*draw_line(5, 8, 10, colour1=4))  # the same ink, one colour
    result = track(decode(composed.end(4.0)).events)
    assert ([s.end_kind for s in result.sessions], result.sessions[0].wipes) == (
        ["replaced", "open"],
        [],
    )


@pytest.mark.parametrize(("width", "countdown"), [(8, True), (9, False)])
def test_wiped_blocks_may_be_as_wide_as_a_countdown_tick_and_no_wider(
    width: int, countdown: bool
) -> None:
    firsts = [1 + (width + 1) * block for block in range(4)]
    builder = CdgBuilder().at(1.0)
    for first in firsts:
        builder.add(*draw_line(2, first, first + width - 1))
    builder.at(1.5).add(*draw_line(8, 8, 30))
    for tick, first in enumerate(firsts):
        builder.at(3.0 + 0.6 * tick).add(
            *[tile(2, c, SOLID, 0, 1, xor=True) for c in range(first, first + width)]
        )
    wipe_line(builder, 5.0, 8, 8, 30)
    result = measure(builder.end(9.0), 9.0)
    assert (result.gaps[0].countdown is not None) == countdown
    assert len(result.lines) == (1 if countdown else 2)
    if countdown:
        assert result.gaps[0].countdown is not None
        assert (result.gaps[0].countdown.draws, result.gaps[0].countdown.erases) == (0, 0)


def test_wiped_blocks_followed_by_a_wipe_of_the_rest_of_their_row_are_a_line() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(2, 12, 40))
    builder.at(1.5).add(*draw_line(8, 8, 30))
    for tick, first in enumerate((12, 17, 22, 27)):
        for column in range(first, first + 3):
            builder.at(3.0 + 0.6 * tick).add(tile(2, column, SOLID, 0, 1, xor=True))
    wipe_line(builder, 5.0, 2, 31, 40)  # the rest of the row, tile by tile
    wipe_line(builder, 6.5, 8, 8, 30)
    result = measure(builder.end(10.0), 10.0)
    assert [line.rows for line in result.lines] == [(2,), (8,)]


def test_wiped_blocks_count_from_their_last_block_to_the_next_line() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(2, 12, 14), *draw_line(2, 17, 19))
    builder.add(*draw_line(2, 22, 24), *draw_line(2, 27, 29))
    builder.at(1.5).add(*draw_line(8, 8, 30))
    for tick, first in enumerate((12, 17, 22, 27)):  # the last block at 4.8 s
        for column in range(first, first + 3):
            builder.at(3.0 + 0.6 * tick).add(tile(2, column, SOLID, 0, 1, xor=True))
    wipe_line(builder, 7.5, 8, 8, 30)  # 2.7 s after the last block, 3.3 s after the one before
    result = measure(builder.end(11.0), 11.0)
    assert [line.rows for line in result.lines] == [(8,)]
    assert result.gaps[0].countdown is not None


def test_a_bar_with_more_samples_after_it_filled_is_still_a_progress_bar() -> None:
    builder = CdgBuilder().at(0.5).add(*draw_line(3, 10, 30), *draw_line(8, 1, 48))
    wipe_line(builder, 2.0, 3, 10, 30)
    for step, column in enumerate(range(1, 49)):
        builder.at(5.0 + 0.2 * step).add(tile(8, column, SOLID, 0, 1, xor=True))
    builder.at(14.5).add(tile(8, 5, FILL, 0, 4, xor=True))  # e.g. a glyph top, later and left
    builder.at(14.6).add(*draw_line(12, 10, 30))
    wipe_line(builder, 15.0, 12, 10, 30)
    result = measure(builder.end(18.0), 18.0)
    assert [line.rows for line in result.lines] == [(3,), (12,)]
    assert result.gaps[1].bar == pytest.approx(9.4, abs=0.01)
