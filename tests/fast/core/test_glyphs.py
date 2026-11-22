"""Stage 1: dropping the symbols the bundled font cannot draw (ADR-0046)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.glyphs import NOTE_SIGNS, UndrawableLetter, describe, is_letter, strip_undrawable

FONT = frozenset(ord(c) for c in "abcdefghij ")
SQRT = "√"
NOTE = "♪"
HEART = "♥"


def test_a_code_point_is_described_with_its_unicode_name() -> None:
    assert describe(0x221A) == "U+221A SQUARE ROOT"
    assert describe(0x9) == "U+0009 Cc"  # a control character has no name; its class stands in


def test_letters_marks_and_digits_are_not_symbols() -> None:
    assert [is_letter(c) for c in ("a", "Ж", "́", "7", SQRT, NOTE, "-", " ")] == [
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
    ]


def test_a_text_the_font_draws_whole_comes_back_unchanged() -> None:
    result = strip_undrawable("ab  cd", FONT, "line 1")
    assert (result.text, result.dropped, result.kept) == ("ab  cd", (), (0, 1, 2))


def test_a_symbol_inside_a_word_leaves_the_word() -> None:
    result = strip_undrawable(f"a{SQRT}b cd", FONT, "line 1")
    assert (result.text, result.dropped, result.kept) == ("ab cd", (0x221A,), (0, 1, 2))


def test_a_word_of_symbols_disappears_and_the_words_after_it_move_up() -> None:
    result = strip_undrawable(f"ab {SQRT}{HEART} cd {HEART}", FONT, "line 1")
    assert result.text == "ab cd"
    assert result.dropped == (0x221A, 0x2665)  # each once, in order of appearance
    assert result.kept == (0, 1, 1, 2, 2)  # the end of the line is index 4 of the old words


def test_white_space_the_font_lacks_becomes_a_single_space_without_a_report() -> None:
    result = strip_undrawable("ab\tcd\u3000ef", FONT, "line 1")
    assert (result.text, result.dropped, result.kept) == ("ab cd ef", (), (0, 1, 2, 3))


def test_a_variation_selector_is_no_letter_and_goes_with_its_emoji() -> None:
    assert not is_letter("\ufe0f")
    assert not is_letter("\U000e0100")
    assert is_letter("\u20e3")  # a combining keycap is a mark
    result = strip_undrawable("ab \u270c\ufe0f cd", FONT, "line 1")  # victory hand, VS-16
    assert (result.text, result.dropped) == ("ab cd", (0x270C,))


def test_a_variation_selector_after_a_drawn_character_is_dropped_without_a_report() -> None:
    result = strip_undrawable("ab\ufe0e cd", FONT, "line 1")
    assert (result.text, result.dropped) == ("ab cd", ())


def test_a_mark_after_a_dropped_symbol_goes_with_it() -> None:
    keycap = f"{SQRT}\ufe0f\u20e3"  # a symbol, a variation selector and an enclosing keycap
    result = strip_undrawable(f"a{keycap}b", FONT, "line 1")
    assert (result.text, result.dropped) == ("ab", (0x221A,))


def test_a_mark_the_font_lacks_after_a_drawn_letter_fails() -> None:
    with pytest.raises(UndrawableLetter) as caught:
        strip_undrawable(f"{SQRT}a\u20e3", FONT, "line 2")
    assert caught.value.codepoint == 0x20E3


def test_a_letter_after_a_dropped_symbol_still_fails() -> None:
    with pytest.raises(UndrawableLetter) as caught:
        strip_undrawable(f"{SQRT}Ж", FONT, "line 3")
    assert caught.value.codepoint == 0x416


def test_a_letter_the_font_lacks_fails_with_its_place_and_code_point() -> None:
    with pytest.raises(UndrawableLetter) as caught:
        strip_undrawable("ab Ж cd", FONT, "line 45")
    assert (caught.value.codepoint, caught.value.where) == (0x416, "line 45")
    assert str(caught.value) == (
        "line 45: U+0416 CYRILLIC CAPITAL LETTER ZHE is a letter the bundled font cannot draw"
    )


@given(st.text(alphabet=st.sampled_from([*"abcj \t", SQRT, NOTE, "♥", "-", "!"]), max_size=40))
def test_what_is_left_is_always_drawable_and_the_words_count_adds_up(text: str) -> None:
    result = strip_undrawable(text, FONT, "line 1")
    assert all(ord(char) in FONT for char in result.text)
    assert len(result.text.split()) == result.kept[-1]
    reported = {ord(c) for c in text if ord(c) not in FONT and not c.isspace()}
    assert set(result.dropped) == reported - set(NOTE_SIGNS)


def test_a_mark_at_the_start_of_a_word_does_not_belong_to_a_symbol_of_the_word_before() -> None:
    with pytest.raises(UndrawableLetter) as caught:
        strip_undrawable(f"a{SQRT} \u20e3b", FONT, "line 4")
    assert caught.value.codepoint == 0x20E3


def test_note_signs_are_dropped_without_a_report() -> None:
    result = strip_undrawable("\u2669 ab \u266a\u266b cd\u266c", FONT, "line 1")
    assert (result.text, result.dropped) == ("ab cd", ())


def test_the_signs_next_to_the_note_signs_are_still_reported() -> None:
    result = strip_undrawable("\u2668 ab \u266d", FONT, "line 1")  # hot springs, flat sign
    assert (result.text, result.dropped) == ("ab", (0x2668, 0x266D))
