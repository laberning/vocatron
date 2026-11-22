"""Stage 1: the second voice as far as the lyrics file tells it (ADR-0052)."""

from vocatron.core.lyrics.document import Line, parse
from vocatron.core.lyrics.voices import same_time, source_of, voices_of


def test_the_later_of_two_lines_with_one_time_is_the_second_voice() -> None:
    assert same_time([1.0, 5.0, 5.0, 9.0]) == [False, False, True, False]


def test_a_run_of_equal_times_has_one_second_voice_line_and_untimed_lines_never_count() -> None:
    assert same_time([5.0, 5.0, 5.0, None, None]) == [False, True, False, False, False]
    assert same_time([]) == []


def test_a_marked_line_and_a_line_with_the_time_of_the_one_before_are_the_second_voice() -> None:
    lines = [Line(text="a", time=1.0), Line(text="b", time=1.0), Line(text="c", voice=2, time=3.0)]
    assert voices_of(lines) == [1, 2, 2]


def test_a_file_without_marks_or_shared_times_is_one_voice() -> None:
    document = parse("[00:01.00] eins\n[00:02.00] zwei\n", "lrc")
    assert voices_of(document.lines) == [1, 1]


def test_the_source_of_a_line_is_the_time_or_the_mark() -> None:
    times = [1.0, 1.0, 3.0, None]
    assert source_of(times, [1, 2, 2, 1]) == {1: "time", 2: "mark"}


def test_a_txt_file_has_no_times_so_only_the_mark_counts() -> None:
    document = parse("eins\n{&} zwei\ndrei\n", "txt")
    assert voices_of(document.lines) == [1, 2, 1]


def test_the_first_line_is_never_the_second_voice_even_with_the_time_of_the_last() -> None:
    assert same_time([5.0, 7.0, 5.0]) == [False, False, False]
