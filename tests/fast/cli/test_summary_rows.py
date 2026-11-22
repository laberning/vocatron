"""Stage 1: summary rows and other output lines on a terminal and in a pipe (``cli.console``)."""

from io import StringIO

from rich.console import Console

from vocatron.cli.console import print_line, print_row
from vocatron.core.report import SummaryRow

ROW = SummaryRow("review", "Artist - Title", 211.0, 150.0, "alignment: " + "x" * 120)


def test_in_a_pipe_a_long_row_stays_whole_on_one_line() -> None:
    stream = StringIO()
    print_row(Console(file=stream, width=80, color_system=None), ROW, [ROW.name])
    (line,) = stream.getvalue().splitlines()
    assert line.endswith("x" * 120)


def test_on_a_terminal_a_long_row_is_cut_to_the_width() -> None:
    stream = StringIO()
    terminal = Console(file=stream, width=80, force_terminal=True, color_system=None)
    print_row(terminal, ROW, [ROW.name])
    (line,) = stream.getvalue().splitlines()
    assert len(line) == 80
    assert line.endswith("…")


def test_in_a_pipe_a_long_output_line_stays_whole() -> None:
    stream = StringIO()
    note = "warning: Artist - Title: " + "line 23: time 02:23.00 is out of order, skipped " * 3
    print_line(Console(file=stream, width=80, color_system=None), note)
    assert stream.getvalue() == note + "\n"


def test_square_brackets_in_a_name_are_printed_as_they_are() -> None:
    stream = StringIO()
    print_line(Console(file=stream, width=80, color_system=None), "approved Song [Live] [bold]")
    assert stream.getvalue() == "approved Song [Live] [bold]\n"


def test_a_row_with_wide_characters_fits_the_terminal() -> None:
    stream = StringIO()
    row = SummaryRow("ok", "アーティスト - " + "とても長い歌のタイトル" * 3, 180.0, 60.0, "")
    terminal = Console(file=stream, width=80, force_terminal=True, color_system=None)
    print_row(terminal, row, [row.name])
    assert len(stream.getvalue().splitlines()) == 1
