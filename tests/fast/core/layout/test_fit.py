"""Stage 1: a line too wide is split at the word nearest its middle, then shrunk (rule 3)."""

import pytest

from fakes.measure import FixedMeasurer
from vocatron.core.layout.fit import SHRINK_MARGIN, Fitted, fit, wrap_words
from vocatron.core.layout.phrases import Phrase, Piece, Turn

MEASURER = FixedMeasurer()  # every character is half the font size wide
SIZE = 10.0  # so a character is 5 pixels


def line(*words: str, syllables: int = 1) -> Phrase:
    pieces: list[Piece] = []
    time = 0.0
    for number, word in enumerate(words):
        step = max(len(word) // syllables, 1)
        parts = [word[i : i + step] for i in range(0, len(word), step)] if syllables > 1 else [word]
        for position, part in enumerate(parts):
            spaced = part + (" " if position == len(parts) - 1 and number < len(words) - 1 else "")
            pieces.append(Piece(spaced, time, time + 0.1))
            time += 0.1
    return Phrase("1", tuple(pieces))


def texts(result: list[Fitted]) -> list[str]:
    return [item.phrase.text for item in result]


def test_a_line_that_fits_stays_as_it_is() -> None:
    (only,) = fit(line("eins", "zwei"), MEASURER, SIZE, 5.0, 100.0)
    assert only.phrase.text == "eins zwei"
    assert only.size == SIZE
    assert not only.too_wide


def test_a_line_that_is_too_wide_is_split_at_the_word_nearest_its_middle() -> None:
    # 5 + 1 + 5 + 1 + 3 + 1 + 3 = 19 characters = 95 px; the limit is 70 px
    result = fit(line("aaaaa", "bbbbb", "ccc", "ddd"), MEASURER, SIZE, 5.0, 70.0)
    assert texts(result) == ["aaaaa bbbbb", "ccc ddd"]


def test_a_split_keeps_the_sung_syllables_and_their_times() -> None:
    original = line("aaaaa", "bbbbb", "ccc", "ddd")
    result = fit(original, MEASURER, SIZE, 5.0, 70.0)
    pieces = [piece for item in result for piece in item.phrase.pieces]
    assert [(p.start, p.end) for p in pieces] == [(p.start, p.end) for p in original.pieces]
    assert not result[0].phrase.pieces[-1].text.endswith(" ")


def test_each_half_is_split_again_until_it_fits() -> None:
    result = fit(line(*["wort"] * 8), MEASURER, SIZE, 5.0, 50.0)  # 10 characters at most
    assert all(len(text) <= 10 for text in texts(result))
    assert " ".join(texts(result)) == " ".join(["wort"] * 8)


def test_one_word_that_is_too_wide_is_shrunk() -> None:
    (only,) = fit(line("aaaaaaaaaaaa"), MEASURER, SIZE, 5.0, 40.0)  # 60 px at 10; 40 px needs 6.67
    assert 6.0 < only.size < 6.7
    assert MEASURER.width(only.phrase.text, only.size) <= 40.0
    assert not only.too_wide


def test_a_word_that_would_need_less_than_the_minimum_is_split_between_syllables() -> None:
    result = fit(line("aaaaaaaaaaaa", syllables=4), MEASURER, SIZE, 8.0, 40.0)
    assert len(result) > 1
    assert "".join(texts(result)) == "aaaaaaaaaaaa"
    assert all(item.size >= 8.0 for item in result)


def test_a_single_syllable_that_cannot_fit_is_drawn_at_the_minimum_and_marked() -> None:
    (only,) = fit(line("aaaaaaaaaaaa"), MEASURER, SIZE, 8.0, 20.0)
    assert only.size == 8.0
    assert only.too_wide


def test_a_line_exactly_as_wide_as_the_limit_fits() -> None:
    (only,) = fit(line("eins", "zwei"), MEASURER, SIZE, 5.0, 45.0)  # 9 characters
    assert only.size == SIZE


def test_words_are_split_before_syllables_even_when_a_syllable_is_nearer_the_middle() -> None:
    pieces = (Piece("ab ", 0.0, 0.1), Piece("cdefg", 0.1, 0.2), Piece("hijkl", 0.2, 0.3))
    assert texts(fit(Phrase("1", pieces), MEASURER, SIZE, 5.0, 60.0)) == ["ab", "cdefghijkl"]


def test_two_words_that_do_not_fit_together_become_two_lines() -> None:
    assert texts(fit(line("eins", "zwei"), MEASURER, SIZE, 5.0, 30.0)) == ["eins", "zwei"]


def test_a_line_drawn_too_wide_keeps_its_syllables() -> None:
    (only,) = fit(line("x" * 40), MEASURER, SIZE, 8.0, 50.0)
    assert only.too_wide
    assert only.phrase.text == "x" * 40


def test_a_split_line_keeps_its_singers_on_each_half() -> None:
    original = line("aaaaa", "bbbbb", "ccc", "ddd")
    marked = Phrase("1", original.pieces, (Turn(1, "2"), Turn(2, "1,3"), Turn(3, "all")))
    first, second = (item.phrase for item in fit(marked, MEASURER, SIZE, 5.0, 70.0))
    assert texts([Fitted(first, SIZE), Fitted(second, SIZE)]) == ["aaaaa bbbbb", "ccc ddd"]
    assert (first.singers, first.turns) == ("1", (Turn(1, "2"),))
    assert (second.singers, second.turns) == ("1,3", (Turn(1, "all"),))  # the turn at 2 starts it


def test_a_half_that_starts_inside_a_stretch_of_one_singer_starts_with_that_singer() -> None:
    marked = Phrase("1", line("aaaaa", "bbbbb", "ccc", "ddd").pieces, (Turn(1, "2"),))
    first, second = (item.phrase for item in fit(marked, MEASURER, SIZE, 5.0, 70.0))
    assert (first.turns, second.singers, second.turns) == ((Turn(1, "2"),), "2", ())


def test_a_wide_line_with_two_rows_becomes_one_block_of_two_rows() -> None:
    (block,) = fit(line("aaaaa", "bbbbb", "ccc", "ddd"), MEASURER, SIZE, 5.0, 70.0, rows=2)
    assert [row.text for row in block.rows] == ["aaaaa bbbbb", "ccc ddd"]
    assert block.parts == block.rows
    assert block.phrase.text == "aaaaa bbbbb ccc ddd"  # the whole line is what is sung
    assert block.size == SIZE
    assert not block.too_wide


def test_a_line_that_fits_one_row_stays_one_row_whatever_the_rows() -> None:
    (only,) = fit(line("eins", "zwei"), MEASURER, SIZE, 5.0, 100.0, rows=2)
    assert only.rows == ()
    assert only.parts == (only.phrase,)


def test_the_rows_are_shrunk_together_until_both_fit() -> None:
    # 11 and 7 characters are 55 and 35 px; 44 px needs the size 8 for the wider row
    (block,) = fit(line("aaaaa", "bbbbb", "ccc", "ddd"), MEASURER, SIZE, 5.0, 44.0, rows=2)
    assert len(block.rows) == 2
    assert block.size == pytest.approx(SIZE * 44.0 / 55.0, rel=0.01)
    assert block.size < SIZE * 44.0 / 55.0


def test_rows_that_do_not_fit_even_at_the_smallest_size_are_split_into_lines() -> None:
    # 11 and 7 characters: the rows would need size 7.3, below the smallest size 9
    first, second = fit(line("aaaaa", "bbbbb", "ccc", "ddd"), MEASURER, SIZE, 9.0, 40.0, rows=2)
    assert (first.phrase.text, second.phrase.text) == ("aaaaa bbbbb", "ccc ddd")
    assert [row.text for row in first.rows] == ["aaaaa", "bbbbb"]  # each half may be a block too
    assert second.rows == ()


def test_one_row_splits_a_wide_line_into_lines_as_before() -> None:
    result = fit(line("aaaaa", "bbbbb", "ccc", "ddd"), MEASURER, SIZE, 5.0, 70.0)
    assert texts(result) == ["aaaaa bbbbb", "ccc ddd"]
    assert all(item.rows == () for item in result)


def test_a_single_long_word_is_shrunk_not_wrapped_whatever_the_rows() -> None:
    (only,) = fit(line("aaaaaaaaaaaa"), MEASURER, SIZE, 5.0, 40.0, rows=2)
    assert only.rows == ()
    assert only.size == pytest.approx(40.0 / 60.0 * SIZE, rel=0.01)


def test_the_rows_keep_who_sings_each_of_them() -> None:
    marked = Phrase("1", line("aaaaa", "bbbbb", "ccc", "ddd").pieces, (Turn(2, "2"),))
    (block,) = fit(marked, MEASURER, SIZE, 5.0, 70.0, rows=2)
    head, tail = block.rows
    assert (head.singers, tail.singers) == ("1", "2")


def test_two_rows_are_cut_between_words_even_when_a_syllable_is_nearer_the_middle() -> None:
    # "aa|aa |bbbbbb|bbbbbb": the syllable boundary at 11 of 17 characters is nearer the middle
    (block,) = fit(line("aaaa", "bbbbbbbbbbbb", syllables=2), MEASURER, SIZE, 5.0, 70.0, rows=2)
    assert [row.text for row in block.rows] == ["aaaa", "bbbbbbbbbbbb"]


def test_rows_exactly_as_wide_as_the_limit_keep_their_size() -> None:
    (block,) = fit(line("aaaaa", "bbbbb", "ccc", "ddd"), MEASURER, SIZE, 5.0, 55.0, rows=2)
    assert len(block.rows) == 2
    assert block.size == SIZE


def test_rows_shrunk_to_exactly_the_smallest_size_stay_one_block() -> None:
    smallest = SIZE * 44.0 / 55.0 * SHRINK_MARGIN
    (block,) = fit(line("aaaaa", "bbbbb", "ccc", "ddd"), MEASURER, SIZE, smallest, 44.0, rows=2)
    assert len(block.rows) == 2
    assert block.size == smallest


def test_after_a_split_the_later_half_may_be_a_block_of_two_rows_too() -> None:
    # "ccc ddd" | "aaaaa bbbbb": as two rows the line needs size 7.3, below 9; the halves fit
    first, second = fit(line("ccc", "ddd", "aaaaa", "bbbbb"), MEASURER, SIZE, 9.0, 40.0, rows=2)
    assert (first.phrase.text, first.rows) == ("ccc ddd", ())
    assert [row.text for row in second.rows] == ["aaaaa", "bbbbb"]


def test_a_text_is_wrapped_at_the_word_nearest_its_middle() -> None:
    assert wrap_words("aaa bb cccc dd", MEASURER, SIZE) == ("aaa bb", "cccc dd")
    assert wrap_words("a bbbbbbbbbb c", MEASURER, SIZE) == ("a bbbbbbbbbb", "c")  # 12 of 14 vs 1
    assert wrap_words("ab cd", MEASURER, SIZE) == ("ab", "cd")  # two words are enough


def test_a_text_is_wrapped_at_the_same_word_as_the_sung_line_of_it() -> None:
    text = "one two three four five"
    halves = wrap_words(text, MEASURER, SIZE)
    (block,) = fit(line(*text.split()), MEASURER, SIZE, 4.0, 60.0, rows=2)
    assert halves == tuple(part.text for part in block.rows)


def test_one_word_or_nothing_is_not_wrapped() -> None:
    assert wrap_words("Supercalifragilistic", MEASURER, SIZE) is None
    assert wrap_words("   ", MEASURER, SIZE) is None
    assert wrap_words("", MEASURER, SIZE) is None
