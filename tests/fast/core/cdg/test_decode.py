"""Stage 1: the CD+G decoder on hand-built packet sequences, one test per instruction."""

import numpy as np
from hypothesis import given
from hypothesis import strategies as st
from syrupy.assertion import SnapshotAssertion

from fakes.cdg import (
    BLANK,
    SOLID,
    CdgBuilder,
    border_preset,
    classic_song,
    filler,
    memory_preset,
    packet,
    palette,
    scroll,
    tile,
    transparent,
)
from vocatron.core.cdg import (
    HEIGHT,
    PACKET_SIZE,
    WIDTH,
    CdgOp,
    CdgScreen,
    decode,
    parse_packets,
)


def final(stream: bytes) -> np.ndarray:
    return decode(stream, [1e6]).frames[0]


def test_only_drawing_packets_are_parsed_and_the_index_counts_every_packet() -> None:
    stream = filler() + filler() + memory_preset(3) + filler()
    parsed = list(parse_packets(stream))
    assert [p.index for p in parsed] == [2]
    assert parsed[0].instruction == 1
    assert len(parsed[0].data) == 16


def test_a_partial_trailing_packet_is_ignored() -> None:
    stream = memory_preset(3) + memory_preset(4)[:10]
    result = decode(stream)
    assert result.packet_count == 1
    assert len(result.events) == 1


def test_memory_preset_fills_the_whole_screen_and_repeats_are_ignored() -> None:
    result = decode(memory_preset(5) + memory_preset(5, repeat=1) + memory_preset(6, repeat=2))
    assert [e.op for e in result.events] == [CdgOp.MEMORY_PRESET]
    assert result.events[0].colour0 == 5
    assert (final(memory_preset(5)) == 5).all()


def test_border_preset_paints_only_the_ring() -> None:
    frame = final(memory_preset(2) + border_preset(7))
    assert frame[0, 0] == 7
    assert frame[HEIGHT - 1, WIDTH - 1] == 7
    assert frame[11, 150] == 7
    assert frame[12, 150] == 2
    assert frame[100, 5] == 7
    assert frame[100, 6] == 2
    assert frame[100, 294] == 7
    assert frame[203, 150] == 2
    assert frame[204, 150] == 7


def test_a_normal_tile_draws_two_colours_by_the_bits_most_significant_bit_left() -> None:
    rows = (0b100000, 0b000001, *BLANK[:10])
    frame = final(tile(2, 3, rows, colour0=4, colour1=9))
    block = frame[24:36, 18:24]
    assert list(block[0]) == [9, 4, 4, 4, 4, 4]
    assert list(block[1]) == [4, 4, 4, 4, 4, 9]
    assert (block[2:] == 4).all()
    assert (frame[:24] == 0).all()
    assert (frame[36:] == 0).all()


def test_a_tile_outside_the_grid_is_ignored() -> None:
    result = decode(tile(18, 0) + tile(0, 50) + tile(31, 63))
    assert result.events == ()
    assert (final(tile(18, 0)) == 0).all()


def test_the_high_bits_of_tile_bytes_are_ignored() -> None:
    dirty = packet(6, [0xF1, 0xF2, 0xE1, 0xC2, *([0xFF] * 12)])
    event = decode(dirty).events[0]
    assert (event.colour0, event.colour1, event.row, event.column) == (1, 2, 1, 2)
    assert event.pixels == SOLID


def test_a_xor_tile_flips_the_chosen_colours_and_twice_restores() -> None:
    base = tile(1, 1, SOLID, colour0=3, colour1=5)
    xored = tile(1, 1, (0b111000,) * 12, colour0=0, colour1=6, xor=True)
    once = final(base + xored)
    block = once[12:24, 6:12]
    assert list(block[0]) == [5 ^ 6, 5 ^ 6, 5 ^ 6, 5, 5, 5]
    assert (final(base + xored + xored) == final(base)).all()


def test_xor_with_a_colour_for_the_zero_bits_changes_the_background_too() -> None:
    frame = final(tile(0, 0, BLANK, colour0=2) + tile(0, 0, BLANK, colour0=1, xor=True))
    assert (frame[:12, :6] == 3).all()


def test_scroll_copy_wraps_and_scroll_preset_fills() -> None:
    drawn = tile(1, 0, SOLID, colour1=4) + tile(17, 0, SOLID, colour1=6)
    up = final(drawn + scroll(v_command=2, copy=True))
    assert up[0, 0] == 4  # row 1 moved to row 0
    assert up[12 * 16, 0] == 6  # row 17 moved to row 16
    down = final(drawn + scroll(v_command=1, copy=True))
    assert down[0, 0] == 6  # row 17 wrapped to row 0
    assert down[24, 0] == 4
    preset = final(drawn + scroll(v_command=2, colour=9))
    assert preset[0, 0] == 4
    assert preset[HEIGHT - 1, 0] == 9
    right = final(tile(0, 49, SOLID, colour1=8) + scroll(h_command=1, colour=2))
    assert right[0, 0] == 2
    assert right[0, 5] == 2
    assert right[0, 6] == 0
    left = final(tile(0, 0, SOLID, colour1=8) + scroll(h_command=2, colour=2, copy=True))
    assert left[0, WIDTH - 6] == 8


def test_the_fine_scroll_offset_moves_the_displayed_window() -> None:
    screen = CdgScreen()
    packets = tile(0, 1, SOLID, colour1=5) + scroll(h_offset=3, v_offset=0)
    for p in parse_packets(packets):
        screen.apply(p)
    shown = screen.frame()
    assert shown[0, 3] == 5
    assert shown[0, 2] == 0
    assert screen.pixels[0, 6] == 5  # the content itself did not move
    assert (screen.h_offset, screen.v_offset) == (3, 0)


def test_scroll_events_carry_commands_and_clamped_offsets() -> None:
    event = decode(scroll(h_command=2, v_command=1, h_offset=7, v_offset=15, copy=True)).events[0]
    assert event.op is CdgOp.SCROLL_COPY
    assert (event.h_command, event.v_command, event.h_offset, event.v_offset) == (2, 1, 5, 11)


def test_palette_loads_decode_four_bits_per_channel() -> None:
    low = [
        (0, 0, 0),
        (15, 0, 0),
        (0, 15, 0),
        (0, 0, 15),
        (1, 2, 3),
        (4, 5, 6),
        (7, 8, 9),
        (10, 11, 12),
    ]
    high = [(15, 15, 15)] * 8
    result = decode(palette(low) + palette(high, high=True))
    first, second = result.events
    assert first.op is CdgOp.PALETTE
    assert first.first_colour == 0
    assert first.colours == tuple(low)
    assert second.first_colour == 8
    assert second.colours == tuple(high)


def test_rgb_frame_uses_the_palette_scaled_to_eight_bits() -> None:
    screen = CdgScreen()
    colours = [(0, 0, 0), (15, 7, 1), *[(0, 0, 0)] * 6]
    for p in parse_packets(palette(colours) + memory_preset(1)):
        screen.apply(p)
    assert tuple(screen.rgb_frame()[5, 5]) == (255, 119, 17)


def test_transparent_colour_is_recorded_and_unknown_instructions_are_ignored() -> None:
    screen = CdgScreen()
    events = [screen.apply(p) for p in parse_packets(transparent(6) + packet(63))]
    assert events[0] is not None
    assert events[0].op is CdgOp.TRANSPARENT
    assert events[0].colour0 == 6
    assert events[1] is None
    assert screen.transparent == 6


def test_events_are_timed_by_their_packet_and_snapshots_show_the_state_at_that_time() -> None:
    stream = (
        CdgBuilder()
        .at(0.0)
        .add(memory_preset(1))
        .at(1.0)
        .add(memory_preset(2))
        .at(2.0)
        .add(memory_preset(3))
        .end(2.5)
    )
    result = decode(stream, [1.5, 0.0, 99.0, 1.0])
    assert [e.time for e in result.events] == [0.0, 1.0, 2.0]
    assert result.duration == 2.5
    assert [int(f[0, 0]) for f in result.frames] == [2, 1, 3, 2]  # in the order requested


@given(st.binary(max_size=PACKET_SIZE * 20))
def test_decoding_arbitrary_bytes_never_fails_and_is_deterministic(stream: bytes) -> None:
    first = decode(stream, [0.0, 0.05])
    second = decode(stream, [0.0, 0.05])
    assert first.events == second.events
    assert all((a == b).all() for a, b in zip(first.frames, second.frames, strict=True))
    assert all(f.shape == (HEIGHT, WIDTH) for f in first.frames)


@given(
    st.integers(0, 17),
    st.integers(0, 49),
    st.lists(st.integers(0, 63), min_size=12, max_size=12),
    st.integers(0, 15),
    st.integers(0, 15),
    st.integers(0, 15),
)
def test_xor_twice_restores_and_a_preset_clears(
    row: int, column: int, rows: list[int], base: int, colour0: int, colour1: int
) -> None:
    pixels = tuple(rows)
    start = memory_preset(base) + tile(row, column, pixels, 3, 12)
    flip = tile(row, column, pixels, colour0, colour1, xor=True)
    assert (final(start + flip + flip) == final(start)).all()
    assert (final(start + flip + memory_preset(base)) == base).all()


def test_scroll_preset_fills_the_side_the_content_left() -> None:
    drawn = tile(0, 1, SOLID, colour1=4)
    down = final(drawn + scroll(v_command=1, colour=7))
    assert down[12, 6] == 4
    assert down[0, 6] == 7
    left = final(drawn + scroll(h_command=2, colour=7))
    assert left[0, 0] == 4
    assert left[0, WIDTH - 1] == 7


def test_a_normal_tile_replaces_what_was_there() -> None:
    frame = final(tile(0, 0, SOLID, colour1=5) + tile(0, 0, (0b110000,) * 12, 2, 6))
    assert list(frame[0, :6]) == [6, 6, 2, 2, 2, 2]


def test_the_vertical_fine_offset_moves_the_window_up_into_the_content() -> None:
    screen = CdgScreen()
    for p in parse_packets(tile(1, 0, SOLID, colour1=5) + scroll(v_offset=4)):
        screen.apply(p)
    shown = screen.frame()
    assert shown[8, 0] == 5  # content row 12 is shown at row 8
    assert shown[7, 0] == 0
    assert shown[20, 0] == 0


def test_a_new_screen_is_black_without_border_offsets_or_transparency() -> None:
    screen = CdgScreen()
    assert screen.palette == [(0, 0, 0)] * 16
    assert (screen.border, screen.transparent, screen.h_offset, screen.v_offset) == (0, None, 0, 0)
    assert not screen.rgb_frame().any()


def test_border_preset_events_carry_the_colour_and_the_screen_keeps_it() -> None:
    screen = CdgScreen()
    events = [screen.apply(p) for p in parse_packets(filler() + border_preset(0x37))]
    assert events[0] is not None
    assert (events[0].packet, events[0].op, events[0].colour0) == (1, CdgOp.BORDER_PRESET, 7)
    assert screen.border == 7


def test_the_two_colour_table_loads_fill_their_half_of_the_palette() -> None:
    screen = CdgScreen()
    low = [(1, 0, 0)] * 8
    high = [(0, 0, 9)] * 8
    for p in parse_packets(palette(high, high=True) + palette(low)):
        screen.apply(p)
    assert screen.palette == low + high


def test_a_scroll_command_of_three_does_not_move_the_content() -> None:
    drawn = tile(1, 1, SOLID, colour1=4)
    assert (final(drawn + scroll(h_command=3, v_command=3, colour=9)) == final(drawn)).all()


def test_the_events_of_the_synthetic_disc_are_golden(snapshot: SnapshotAssertion) -> None:
    stream, _ = classic_song()
    lines = [
        f"{e.packet} {e.op} c0={e.colour0} c1={e.colour1} at={e.row},{e.column} "
        f"px={','.join(str(x) for x in e.pixels)} colours={e.colours}"
        for e in decode(stream).events
    ]
    assert "\n".join(lines) == snapshot


def test_scroll_and_transparent_events_carry_their_packet_and_colour() -> None:
    events = decode(filler() + scroll(v_command=1, colour=9) + transparent(4)).events
    assert [(e.packet, e.op, e.colour0) for e in events] == [
        (1, CdgOp.SCROLL_PRESET, 9),
        (2, CdgOp.TRANSPARENT, 4),
    ]
    assert (events[0].rows_moved, events[0].columns_moved) == (1, 0)


def test_every_snapshot_carries_the_palette_in_force_at_its_time() -> None:
    first = [(1, 2, 3)] * 8
    second = [(9, 8, 7)] * 8
    stream = (
        CdgBuilder()
        .at(0.0)
        .add(palette(first), palette(first, high=True))
        .at(1.0)
        .add(palette(second))
        .end(2.0)
    )
    result = decode(stream, [1.5, 0.5])
    assert [p[0] for p in result.palettes] == [(9, 8, 7), (1, 2, 3)]  # in the order requested
    assert [p[8] for p in result.palettes] == [(1, 2, 3)] * 2
    assert all(len(p) == 16 for p in result.palettes)
