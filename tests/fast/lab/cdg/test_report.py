"""Stage 1: the text tables of the CD+G analysis."""

from syrupy.assertion import SnapshotAssertion

from fakes.cdg import FILL, CdgBuilder, classic_song, draw_outline_line, wipe_line
from vocatron.core.cdg import decode
from vocatron.lab.cdg.analysis import analyse
from vocatron.lab.cdg.report import song_block, vendor_block


def test_the_song_block_names_the_measured_numbers() -> None:
    stream, duration = classic_song()
    text = song_block("a.cdg", analyse(decode(stream).events, duration))
    assert "song a.cdg: 50.0 s, 3 wiped lines" in text
    assert "phase 8.50 s, first line drawn 7.00 s, rows [4, 6], 2 lines" in text
    assert "lines per screen: median 2.0, max 2; tile rows [5]x2, [8]x1" in text
    assert "alignment: centred" in text
    assert "lead-in (drawn to first wipe): median 2.00 s" in text
    assert "= " in text and "tiles/s" in text
    assert "#2 (fff) -> #3 (f00) x2" in text
    assert "countdown: 4 ticks every 1.00 s from 36.0 s" in text
    assert "intro gap 0.0-9.0 s (9.0 s) BREAK" in text


def test_a_song_without_lines_has_dashes_not_numbers() -> None:
    text = song_block("empty", analyse([], 3.0))
    assert "title: none found" in text
    assert "lead-in (drawn to first wipe): median -" in text
    assert "singers: -" in text


def test_the_vendor_block_takes_medians_over_the_songs() -> None:
    stream, duration = classic_song()
    one = analyse(decode(stream).events, duration)
    text = vendor_block("Vendor", [("a", one), ("b", one), ("c", analyse([], 1.0))])
    assert "vendor Vendor: 3 songs" in text
    assert "lead-in (median): 2.00 s" in text
    assert "breaks / countdowns / progress bars found: 4 / 2 / 0" in text
    assert "alignment: centred x2" in text
    assert "most colour pairs in one song: 2" in text


def test_a_vendor_without_songs_does_not_fail() -> None:
    assert "0 songs" in vendor_block("Nobody", [])


def test_the_report_blocks_are_golden(snapshot: SnapshotAssertion) -> None:
    stream, duration = classic_song()
    one = analyse(decode(stream).events, duration)
    empty = analyse([], 1.0)
    text = "\n\n".join(
        [song_block("a.cdg", one), song_block("b.cdg", empty), vendor_block("V", [("a", one)])]
    )
    assert text == snapshot


def test_the_song_block_shows_the_edge_colour_of_an_outline_font() -> None:
    builder = CdgBuilder().at(1.0).add(*draw_outline_line(5, 8, 12, outline=1, fill=2))
    wipe_line(builder, 3.0, 5, 8, 12, pixels=FILL)
    text = song_block("o.cdg", analyse(decode(builder.end(6.0)).events, 6.0))
    assert "unsung #2 (000), sung #3 (000), edge #1 (000)" in text
