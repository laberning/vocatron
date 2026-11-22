"""Stage 1: the CD+G analysis on synthetic discs built from packets (numbers only)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from syrupy.assertion import SnapshotAssertion

from fakes.cdg import (
    BLANK,
    FILL,
    SOLID,
    CdgBuilder,
    border_preset,
    classic_song,
    draw_line,
    draw_outline_line,
    erase_line,
    measure,
    memory_preset,
    palette,
    scroll,
    tile,
    transparent,
    wipe_line,
)
from vocatron.core.cdg import PACKET_SIZE, TILE_WIDTH, decode
from vocatron.lab.cdg.analysis import Analysis, group_lines
from vocatron.lab.cdg.tracking import DRAW_GAP, Change, track


@pytest.fixture(scope="module")
def song() -> Analysis:
    stream, duration = classic_song()
    return measure(stream, duration)


def test_the_title_phase_runs_from_the_first_tile_to_the_first_wipe(song: Analysis) -> None:
    title = song.title
    assert title is not None
    assert title.shown_from == pytest.approx(0.5)
    assert title.cleared_at == pytest.approx(6.0)
    assert title.first_wipe == pytest.approx(9.0)
    assert title.duration == pytest.approx(8.5)
    assert title.rows == (4, 6)
    assert title.lines == 2


def test_the_lines_their_rows_and_how_many_are_visible(song: Analysis) -> None:
    assert [line.rows for line in song.lines] == [(5,), (8,), (5,)]
    assert song.lines_per_screen == 2
    assert song.lines_per_screen_max == 2
    assert song.row_positions == (((5,), 2), ((8,), 1))


def test_centred_lines_are_recognised(song: Analysis) -> None:
    assert song.alignment.kind == "centred"
    assert song.alignment.centre_offset == pytest.approx(0.0)
    assert song.alignment.left_stdev > song.alignment.centre_stdev
    assert (song.lines[0].left, song.lines[0].right) == (48, 252)


def test_lead_in_is_the_time_from_the_draw_to_the_first_wipe(song: Analysis) -> None:
    assert [line.lead_in for line in song.lines] == pytest.approx([2.0, 5.8, 1.6])
    assert song.lead_in == pytest.approx(2.0)


def test_the_wipe_runs_one_tile_per_step(song: Analysis) -> None:
    first = song.lines[0]
    assert first.wipe_method == "xor"
    assert first.wipe_steps == 34
    assert first.wipe_step_px == 6
    assert first.wipe_speed == pytest.approx((252 - 54) / 3.3)
    assert song.wipe_step_px == 6
    assert (first.wipe_sample_px, song.wipe_sample_px) == (6, 6)
    assert song.wipe_methods == (("xor", 3),)


def test_hold_and_how_lines_go(song: Analysis) -> None:
    assert song.lines[0].hold == pytest.approx(17.0 + 33 / 300 - 12.3)
    assert song.lines[1].hold == pytest.approx(17.2 + 21 / 300 - 15.1)
    assert song.lines[2].hold is None
    assert song.lines[2].end_kind == "open"
    assert dict(song.end_kinds) == {"cleared": 2, "open": 1}
    assert song.presets == 2
    assert song.scrolls == 0


def test_gaps_and_the_break_with_its_countdown(song: Analysis) -> None:
    kinds = [gap.kind for gap in song.gaps]
    assert kinds == ["intro", "between", "between", "outro"]
    intro, short, long, outro = song.gaps
    assert intro.is_break
    assert intro.countdown is None
    assert not short.is_break
    assert long.is_break
    assert long.length == pytest.approx(40.0 - 15.1)
    assert long.sung_rows_at_middle == ()
    assert long.other_rows_at_middle == ()
    assert long.other_changes == 4
    countdown = long.countdown
    assert countdown is not None
    assert countdown.ticks == 4
    assert countdown.interval == pytest.approx(1.0)
    assert countdown.first_tick == pytest.approx(36.0)
    assert countdown.length == pytest.approx(4.0)
    assert countdown.before_wipe == pytest.approx(1.0)
    assert (countdown.left_column, countdown.rows) == (1, (3,))
    assert (countdown.draws, countdown.erases) == (4, 0)
    assert outro.countdown is None
    assert song.ending == pytest.approx(50.0 - 42.7)


def test_the_palette_and_the_colours_of_each_singer(song: Analysis) -> None:
    palette = song.palette
    assert palette.background is not None
    assert palette.background.index == 0
    assert palette.unsung is not None
    assert (palette.unsung.index, palette.unsung.rgb) == (2, (15, 15, 15))
    assert palette.sung is not None
    assert (palette.sung.index, palette.sung.rgb) == (3, (15, 0, 0))
    assert palette.edge is None
    pairs = [(s.unsung.index, s.sung.index, s.lines) for s in song.singers]
    assert pairs == [(2, 3, 2), (4, 5, 1)]


def test_the_text_still_standing_at_the_end(song: Analysis) -> None:
    assert song.rows_at_end == (3, 5)


def test_a_stream_without_wipes_has_no_lines_and_no_numbers() -> None:
    result = measure(memory_preset(0) + b"".join(draw_line(4, 5, 30)), 5.0)
    assert result.lines == ()
    assert result.title is None
    assert result.lead_in is None
    assert result.ending is None
    assert result.alignment.kind == "unknown"


def test_a_line_two_tile_rows_high_is_one_line_when_its_rows_are_wiped_together() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 20), *draw_line(6, 8, 20))
    builder.at(4.0).add(*draw_line(9, 8, 20), *draw_line(10, 8, 20))
    for column in range(8, 21):
        step = 0.1 * (column - 8)
        builder.at(6.0 + step).add(
            tile(5, column, SOLID, 0, 1, xor=True), tile(6, column, SOLID, 0, 1, xor=True)
        )
    for column in range(8, 21):
        step = 0.1 * (column - 8)
        builder.at(9.0 + step).add(
            tile(9, column, SOLID, 0, 1, xor=True), tile(10, column, SOLID, 0, 1, xor=True)
        )
    result = measure(builder.end(12.0), 12.0)
    assert [line.rows for line in result.lines] == [(5, 6), (9, 10)]


def test_an_outline_font_composed_by_xor_is_not_a_wipe_and_gives_an_edge_colour() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_outline_line(5, 8, 12, outline=1, fill=3))
    wipe_line(builder, 3.0, 5, 8, 12, flip=1, pixels=FILL)  # the fill goes 3 -> 2
    result = measure(builder.end(6.0), 6.0)
    line = result.lines[0]
    assert line.first_wipe == pytest.approx(3.0)
    assert line.lead_in == pytest.approx(2.0)
    assert result.palette.edge is not None
    assert (result.palette.edge.index, result.palette.edge.count) == (1, 5)
    assert result.palette.unsung is not None
    assert (result.palette.unsung.index, result.palette.unsung.count) == (3, 5)
    assert (line.unsung, line.sung) == (3, 2)


def test_a_wipe_that_starts_right_after_the_draw_is_a_wipe() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_outline_line(5, 8, 12))
    wipe_line(builder, 1.3, 5, 8, 12, pixels=FILL)  # 0.3 s after the draw (R1.11)
    builder.at(3.0).add(*draw_line(8, 8, 12))
    wipe_line(builder, 3.1, 8, 8, 12)  # a plain line, XOR soon after the draw (R2.8)
    first, second = measure(builder.end(6.0), 6.0).lines
    assert first.lead_in == pytest.approx(0.3, abs=0.05)
    assert second.lead_in == pytest.approx(0.1, abs=0.05)
    assert (first.wipe_steps, second.wipe_steps) == (5, 5)


def test_smoothed_text_drawn_in_xor_layers_on_the_same_tile_is_not_a_wipe() -> None:
    layers: list[bytes] = []
    for column in range(8, 13):  # each tile, then a bit plane XOR-ed onto it: shade 1 -> 3
        layers += [tile(5, column, SOLID, 0, 1), tile(5, column, FILL, 0, 2, xor=True)]
    builder = CdgBuilder().at(1.0).add(*layers)
    wipe_line(builder, 3.0, 5, 8, 12, flip=8)  # every shade goes up by 8
    (line,) = measure(builder.end(6.0), 6.0).lines
    assert line.lead_in == pytest.approx(2.0)
    assert line.wipe_steps == 5
    assert (line.unsung, line.sung) == (3, 11)


def test_an_xor_with_the_colour_of_the_text_erases_it() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 10, colour1=2))
    wipe_line(builder, 2.0, 5, 8, 10)  # 2 -> 3
    builder.at(4.0).add(*[tile(5, c, SOLID, 0, 3, xor=True) for c in range(8, 11)])  # 3 -> 0
    result = track(decode(builder.end(6.0)).events)
    session = result.sessions[0]
    assert (session.end_kind, session.tiles) == ("cleared", 0)
    assert session.end == pytest.approx(4.0 + 2 / 300)
    assert [c.ink for c in result.changes] == [True, True, True, False, False, False]


def test_text_drawn_and_erased_by_xor_on_a_filled_background_uses_the_background_colour() -> None:
    builder = CdgBuilder().at(0.5).add(memory_preset(12))
    builder.at(1.0).add(*[tile(5, c, SOLID, 0, 7, xor=True) for c in range(8, 11)])  # 12 ^ 7 = 11
    wipe_line(builder, 2.0, 5, 8, 10, flip=4)  # 11 ^ 4 = 15
    builder.at(4.0).add(*[tile(5, c, SOLID, 0, 3, xor=True) for c in range(8, 11)])  # 15 ^ 3 = 12
    result = measure(builder.end(6.0), 6.0)
    line = result.lines[0]
    assert (line.unsung, line.sung, line.end_kind) == (11, 15, "cleared")
    assert result.palette.background is not None
    assert result.palette.background.index == 12


def test_blocks_wiped_one_after_the_other_are_a_countdown_not_a_line() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(2, 12, 14), *draw_line(2, 17, 19))
    builder.add(*draw_line(2, 22, 24), *draw_line(2, 27, 29))  # four blocks of three tiles
    builder.at(1.5).add(*draw_line(8, 8, 30))
    for tick, first in enumerate((12, 17, 22, 27)):  # one block per 0.6 s, the line follows
        for column in range(first, first + 3):
            builder.at(3.0 + 0.6 * tick).add(tile(2, column, SOLID, 0, 1, xor=True))
    wipe_line(builder, 5.0, 8, 8, 30)
    result = measure(builder.end(9.0), 9.0)
    assert [line.rows for line in result.lines] == [(8,)]
    countdown = result.gaps[0].countdown
    assert countdown is not None
    assert (countdown.ticks, countdown.recoloured, countdown.rows) == (4, 12, (2,))
    assert countdown.interval == pytest.approx(0.6, abs=0.01)
    assert countdown.before_wipe == pytest.approx(5.0 - (3.0 + 1.8), abs=0.05)


def test_adjoining_chunks_wiped_at_a_regular_pace_are_a_line_not_a_countdown() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(2, 12, 23), *draw_line(8, 8, 30))
    for tick, first in enumerate((12, 15, 18, 21)):  # chunks of three tiles that touch
        for column in range(first, first + 3):
            builder.at(3.0 + 0.6 * tick).add(tile(2, column, SOLID, 0, 1, xor=True))
    wipe_line(builder, 5.0, 8, 8, 30)
    result = measure(builder.end(9.0), 9.0)
    assert [line.rows for line in result.lines] == [(2,), (8,)]
    assert all(gap.countdown is None for gap in result.gaps)


def test_wiped_blocks_far_before_the_next_line_are_a_line_not_a_countdown() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(2, 12, 14), *draw_line(2, 17, 19))
    builder.add(*draw_line(2, 22, 24), *draw_line(2, 27, 29))
    builder.at(1.5).add(*draw_line(8, 8, 30))
    for tick, first in enumerate((12, 17, 22, 27)):
        for column in range(first, first + 3):
            builder.at(3.0 + 0.6 * tick).add(tile(2, column, SOLID, 0, 1, xor=True))
    wipe_line(builder, 12.0, 8, 8, 30)  # more than COUNTDOWN_MAX_BEFORE_WIPE later
    result = measure(builder.end(15.0), 15.0)
    assert [line.rows for line in result.lines] == [(2,), (8,)]
    assert all(gap.countdown is None for gap in result.gaps)


def test_a_recolour_wipe_redraws_tiles_in_the_sung_colour() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 12, colour1=2))
    for step, column in enumerate(range(8, 13)):
        builder.at(3.0 + step * 0.1).add(tile(5, column, SOLID, 0, 3))
    builder.at(4.0).add(*draw_line(5, 8, 12, colour1=3))  # the sung line sent again
    line = measure(builder.end(6.0), 6.0).lines[0]
    assert line.wipe_method == "recolour"
    assert (line.rows, line.end_kind) == ((5,), "open")
    assert (line.unsung, line.sung) == (2, 3)
    assert line.wipe_steps == 5


def test_repeated_packets_are_ignored() -> None:
    packets = draw_line(5, 8, 10) * 3
    result = track(decode(b"".join(packets)).events)
    assert len(result.changes) == 3
    assert result.sessions[0].tiles == 3


def test_a_line_replaced_tile_by_tile_ends_as_replaced_and_the_new_line_is_one_session() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 12, colour1=2))
    wipe_line(builder, 3.0, 5, 8, 12)
    different = tuple([0b101010] * 12)
    for step, column in enumerate(range(8, 13)):
        builder.at(6.0 + step * 0.05).add(tile(5, column, different, 0, 2))
    result = track(decode(builder.end(8.0)).events)
    assert [(s.end_kind, s.tiles) for s in result.sessions] == [("replaced", 0), ("open", 5)]
    assert result.sessions[0].end == pytest.approx(6.2)


def test_a_scroll_moves_the_text_and_a_scroll_preset_loses_what_leaves() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(0, 8, 10), *draw_line(5, 8, 10))
    builder.at(2.0).add(scroll(v_command=2, colour=0))
    result = track(decode(builder.end(3.0)).events)
    assert result.scrolls == pytest.approx((2.0,))
    assert [s.end_kind for s in result.sessions] == ["scrolled", "open"]
    assert result.sessions[1].rows == {5}  # the rows it was drawn in
    builder.at(3.0).add(*erase_line(4, 8, 10))  # the moved text is cleared where it went
    moved = track(decode(builder.end(4.0)).events)
    assert moved.sessions[1].end_kind == "cleared"
    assert moved.sessions[1].end == pytest.approx(3.0 + 2 / 300)  # the third tile


def test_a_countdown_that_erases_one_tile_per_second_is_found() -> None:
    builder = CdgBuilder().at(2.0).add(*draw_line(3, 1, 4))
    for tick, column in enumerate(range(1, 5)):
        builder.at(6.0 + tick).add(*erase_line(3, column, column))
    builder.at(10.0).add(*draw_line(5, 8, 20))
    wipe_line(builder, 11.0, 5, 8, 20)
    result = measure(builder.end(14.0), 14.0)
    countdown = result.gaps[0].countdown
    assert countdown is not None
    assert (countdown.ticks, countdown.draws, countdown.erases) == (4, 0, 4)


@given(st.binary(max_size=PACKET_SIZE * 60))
def test_the_analysis_of_arbitrary_bytes_never_fails(stream: bytes) -> None:
    first = measure(stream, 1.0)
    assert first == measure(stream, 1.0)


@given(
    st.lists(
        st.tuples(st.integers(0, 17), st.integers(0, 49), st.sampled_from([BLANK, SOLID])),
        max_size=40,
    )
)
def test_a_screen_preset_ends_every_session(draws: list[tuple[int, int, tuple[int, ...]]]) -> None:
    builder = CdgBuilder()
    for step, (row, column, pixels) in enumerate(draws):
        builder.at(step * 0.01).add(tile(row, column, pixels, 0, 1))
    builder.at(1.0).add(memory_preset(0))
    result = track(decode(builder.end(2.0)).events)
    assert all(s.end is not None for s in result.sessions)


def test_equally_wide_lines_are_told_apart_by_their_place() -> None:
    builder = CdgBuilder()
    for step, row in enumerate((3, 6, 9)):
        builder.at(1.0 + 4 * step).add(*draw_line(row, 2, 20))
        wipe_line(builder, 2.0 + 4 * step, row, 2, 20)
    left = measure(builder.end(16.0), 16.0)
    assert left.alignment.kind == "left"
    assert left.alignment.left_median == 12


def test_a_wiped_row_next_to_static_text_is_not_one_line() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 20), *draw_line(6, 8, 20))
    wipe_line(builder, 3.0, 5, 8, 20)
    groups = group_lines(track(decode(builder.end(6.0)).events).sessions)
    assert [sorted(row for s in group for row in s.rows) for group in groups] == [[5], [6]]


def test_text_drawn_by_xor_alone_and_a_wipe_over_a_blank_tile_count() -> None:
    builder = CdgBuilder().at(1.0).add(tile(5, 8, SOLID, 0, 2))
    builder.add(tile(5, 9, SOLID, 0, 2, xor=True), tile(5, 10, BLANK, 0, 2, xor=True))
    builder.at(3.0).add(tile(5, 8, SOLID, 0, 1, xor=True))
    builder.at(3.1).add(tile(5, 9, SOLID, 0, 1, xor=True))
    builder.at(3.2).add(tile(5, 10, SOLID, 0, 1, xor=True))  # over a blank tile
    result = track(decode(builder.end(5.0)).events)
    assert result.sessions[0].tiles == 2
    assert [w.frontier for w in result.sessions[0].wipes] == [54, 60, 66]


def test_a_horizontal_scroll_copy_wraps_text_and_a_preset_drops_it() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 0, 0), *draw_line(6, 10, 10))
    builder.at(2.0).add(scroll(h_command=2, copy=True))
    kept = track(decode(builder.end(3.0)).events)
    assert [s.end_kind for s in kept.sessions] == ["open", "open"]
    builder.at(3.0).add(scroll(h_command=2))
    builder.at(4.0).add(scroll(h_command=2))
    dropped = track(decode(builder.end(5.0)).events)
    assert dropped.scrolls == pytest.approx((2.0, 3.0, 4.0))
    assert sorted(s.end_kind for s in dropped.sessions) == ["open", "open"]


def test_the_colours_are_read_from_the_palette_at_the_first_wipe() -> None:
    first = [(1, 1, 1)] * 8
    later = [(2, 2, 2)] * 8
    builder = CdgBuilder().add(palette(first)).at(1.0).add(*draw_line(5, 8, 12, colour1=2))
    wipe_line(builder, 3.0, 5, 8, 12)
    builder.at(5.0).add(palette(later))
    result = measure(builder.end(6.0), 6.0)
    assert result.palette.unsung is not None
    assert result.palette.unsung.rgb == (1, 1, 1)


def test_a_border_preset_and_a_transparent_colour_change_no_text() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 12), border_preset(3), transparent(0))
    result = track(decode(builder.end(2.0)).events)
    assert result.sessions[0].tiles == 5
    assert result.presets == ()


def test_page_mode_shows_a_page_of_lines_wipes_them_in_turn_and_clears_it_with_a_preset() -> None:
    builder = CdgBuilder()
    for page, start in enumerate((1.0, 16.5)):
        builder.at(start).add(*[t for row in (3, 6, 9, 12) for t in draw_line(row, 8, 30)])
        for turn, row in enumerate((3, 6, 9, 12)):
            wipe_line(builder, start + 2.0 + 3 * turn - page * 0.5, row, 8, 30)
        builder.at(start + 15.0).add(memory_preset(0))
    result = measure(builder.end(33.0), 33.0)
    assert len(result.lines) == 8
    assert (result.lines_per_screen, result.lines_per_screen_max) == (4, 4)
    assert dict(result.end_kinds) == {"preset": 8}
    assert result.presets == 2
    assert result.row_positions == (((3,), 2), ((6,), 2), ((9,), 2), ((12,), 2))


def test_line_mode_replaces_each_line_in_its_rows_after_it_was_sung() -> None:
    builder = CdgBuilder()
    for turn in range(4):
        row = (5, 8)[turn % 2]
        start = 1.0 + 6 * turn
        builder.at(start).add(*draw_line(row, 8, 30, colour1=2))  # over the sung line
        wipe_line(builder, start + 2.0, row, 8, 30)  # sung until start + 4.2
    result = measure(builder.end(26.0), 26.0)
    assert dict(result.end_kinds) == {"replaced": 2, "open": 2}
    assert result.redraw_delay == pytest.approx(12.0 - 4.2)
    assert result.lines_per_screen_max == 2


def test_a_scrolling_disc_reports_the_row_where_each_line_was_sung() -> None:
    builder = CdgBuilder()
    for turn in range(4):
        start = 1.0 + 5 * turn
        builder.at(start).add(*draw_line(14, 8, 30))
        wipe_line(builder, start + 1.0, 14, 8, 30)
        for step in range(3):
            builder.at(start + 4.0 + 0.1 * step).add(scroll(v_command=2, colour=0))
    result = measure(builder.end(22.0), 22.0)
    assert result.row_positions == (((14,), 4),)
    assert result.scrolls == 12
    assert [line.lead_in for line in result.lines] == pytest.approx([1.0] * 4)


def test_duet_singers_with_one_unsung_colour_differ_by_their_sung_colour() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 20)).at(1.2).add(*draw_line(8, 8, 20))
    wipe_line(builder, 3.0, 5, 8, 20, flip=1)
    wipe_line(builder, 6.0, 8, 8, 20, flip=6)
    result = measure(builder.end(10.0), 10.0)
    assert [(s.unsung.index, s.sung.index, s.lines) for s in result.singers] == [
        (2, 3, 1),
        (2, 4, 1),
    ]
    assert [(s.unsung.count, s.sung.count) for s in result.singers] == [(1, 1), (1, 1)]


def test_a_smooth_wipe_of_one_pixel_column_at_a_time_has_a_speed_and_small_steps() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 12))
    time = 3.0
    for column in range(8, 13):
        for pixel in range(TILE_WIDTH):
            builder.at(time).add(tile(5, column, (1 << (5 - pixel),) * 12, 0, 1, xor=True))
            time += 0.02
    line = measure(builder.end(6.0), 6.0).lines[0]
    assert line.wipe_speed == pytest.approx(29 / (29 * 0.02))
    assert line.wipe_steps == 10
    assert line.wipe_step_px == 3  # only the speed times STEP_GAP
    assert line.wipe_sample_px == 1  # the granularity: one pixel column per sample


def test_a_wipe_by_syllables_steps_by_the_syllable_and_samples_by_the_tile() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 16))
    for syllable in range(3):  # three syllables of three tiles each, sent in one burst
        columns = range(8 + 3 * syllable, 11 + 3 * syllable)
        builder.at(3.0 + 0.5 * syllable).add(*[tile(5, c, SOLID, 0, 1, xor=True) for c in columns])
    line = measure(builder.end(6.0), 6.0).lines[0]
    assert (line.wipe_steps, line.wipe_step_px, line.wipe_sample_px) == (3, 18, 6)
    assert line.wipe_speed == pytest.approx((17 * 6 - 9 * 6) / (1.0 + 2 / 300))


def test_a_wipe_starting_soon_after_the_draw_is_measured_from_draw_gap_on() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 20))
    wipe_line(builder, 1.0 + DRAW_GAP + 0.1, 5, 8, 20)
    line = measure(builder.end(4.0), 4.0).lines[0]
    assert line.lead_in == pytest.approx(DRAW_GAP + 0.1)
    assert line.wipe_steps == 13


def test_a_tile_of_one_colour_clears_and_a_partial_clear_leaves_the_line_open() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 10))
    builder.at(2.0).add(tile(5, 8, SOLID, 3, 3))
    result = track(decode(builder.end(3.0)).events)
    assert (result.sessions[0].tiles, result.sessions[0].end) == (2, None)
    assert result.changes[-1] == Change(2.0, 5, 8, False, 0)


def test_the_extent_of_a_line_is_its_ink_not_its_tiles() -> None:
    narrow = (0, 0b001100, 0b000100, *([0] * 9))
    builder = CdgBuilder().at(1.0).add(tile(5, 8, narrow, 0, 2), tile(5, 9, (0b100010,) * 12))
    session = track(decode(builder.end(2.0)).events).sessions[0]
    assert (session.left, session.right) == (8 * 6 + 2, 10 * 6 - 1)


def test_a_wipe_belongs_to_the_text_it_covers_not_to_newer_text_in_the_row() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 20))
    builder.at(2.0).add(tile(5, 2, SOLID, 0, 2))  # a countdown dot in the same row
    wipe_line(builder, 3.0, 5, 8, 20)
    result = track(decode(builder.end(5.0)).events)
    assert [len(s.wipes) for s in result.sessions] == [13, 0]


def test_a_line_drawn_again_after_its_wipe_is_new_text() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_line(5, 8, 10))
    wipe_line(builder, 2.0, 5, 8, 10)
    builder.at(4.0).add(*draw_line(5, 8, 10))  # the same chorus again, unsung
    result = track(decode(builder.end(5.0)).events)
    assert [(s.end_kind, s.tiles) for s in result.sessions] == [("replaced", 0), ("open", 3)]


def test_scrolls_keep_text_up_to_the_edges_and_drop_or_wrap_what_crosses_them() -> None:
    corners = [tile(1, 1, SOLID, 0, 2), tile(16, 48, SOLID, 0, 2)]
    up_left = CdgBuilder().at(1.0).add(*corners).at(2.0).add(scroll(2, 2))
    kept = track(decode(up_left.end(3.0)).events)
    assert [s.end for s in kept.sessions] == [None, None]
    down_right = CdgBuilder().at(1.0).add(*corners).at(2.0).add(scroll(1, 1))
    dropped = track(decode(down_right.end(3.0)).events)
    assert [s.end for s in dropped.sessions] == [None, None]
    dropped_again = CdgBuilder().at(1.0).add(*corners).at(2.0).add(scroll(1, 1), scroll(1, 1))
    gone = track(decode(dropped_again.end(3.0)).events)
    assert [(s.end_kind, s.end) for s in gone.sessions][1] == (
        "scrolled",
        pytest.approx(2 + 1 / 300),
    )
    wrapped = CdgBuilder().at(1.0).add(*corners).at(2.0).add(scroll(2, 2, copy=True))
    wrapped.add(scroll(2, 2, copy=True)).at(3.0).add(*erase_line(17, 49, 49))
    result = track(decode(wrapped.end(4.0)).events)
    assert result.sessions[0].end_kind == "cleared"  # row 1, column 1 went round to 17, 49


def test_only_scroll_commands_that_move_the_content_count_as_scrolls() -> None:
    builder = CdgBuilder().at(1.0).add(scroll(h_offset=3), scroll(v_command=1), scroll(h_command=1))
    assert track(decode(builder.end(2.0)).events).scrolls == pytest.approx(
        (1 + 1 / 300, 1 + 2 / 300)
    )


def test_presets_and_palettes_are_kept_with_their_times() -> None:
    low = [(1, 1, 1)] * 8
    high = [(2, 2, 2)] * 8
    builder = CdgBuilder().at(1.0).add(memory_preset(0)).at(2.0).add(palette(high, high=True))
    builder.add(palette(low))
    result = track(decode(builder.end(3.0)).events)
    assert result.presets == pytest.approx((1.0,))
    assert result.palettes[0] == (0.0, ((0, 0, 0),) * 16)
    assert result.palettes[-1] == (pytest.approx(2 + 1 / 300), (*low, *high))


def test_the_analysis_of_the_synthetic_disc_is_golden(
    song: Analysis, snapshot: SnapshotAssertion
) -> None:
    assert song == snapshot
