"""Stage 1: what is specific to English: number words, years, ordinals, decades, syllables."""

import re
from typing import cast

import pyphen
import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.languages.base import Hyphenation
from vocatron.core.languages.en import (
    ENGLISH,
    EXCEPTIONS,
    MILLION,
    VOWELS,
    cardinal,
    ordinal,
    year,
)

UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip


def read(words: str) -> int:
    """Read an English number back into a number: the inverse of ``cardinal``."""
    total = 0
    current = 0
    for word in re.split(r"[ -]", words):
        if word in UNITS:
            current += UNITS[word]
        elif word == "hundred":
            current *= 100
        elif word == "thousand":
            total += current * 1000
            current = 0
        elif word == "million":
            total += current * MILLION
            current = 0
        else:
            assert word == "and", word
    return total + current


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "zero"), (1, "one"), (12, "twelve"), (16, "sixteen"), (21, "twenty-one"),
        (30, "thirty"), (99, "ninety-nine"), (100, "one hundred"),
        (101, "one hundred and one"), (110, "one hundred and ten"),
        (342, "three hundred and forty-two"), (1000, "one thousand"),
        (1001, "one thousand and one"), (1100, "one thousand one hundred"),
        (1101, "one thousand one hundred and one"), (21000, "twenty-one thousand"),
        (100000, "one hundred thousand"),
        (999999, "nine hundred and ninety-nine thousand nine hundred and ninety-nine"),
        (1000000, "one million"),
    ],
)  # fmt: skip
def test_cardinals_are_spelled_as_they_are_sung(n: int, words: str) -> None:
    assert cardinal(n) == words


@given(st.integers(0, MILLION))
def test_a_number_read_back_from_its_words_is_the_number(number: int) -> None:
    assert read(cardinal(number)) == number


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (1100, "eleven hundred"), (1101, "eleven oh one"), (1789, "seventeen eighty-nine"),
        (1900, "nineteen hundred"), (1905, "nineteen oh five"), (1910, "nineteen ten"),
        (1999, "nineteen ninety-nine"), (2000, "two thousand"), (2005, "two thousand five"),
        (2009, "two thousand nine"), (2010, "twenty ten"), (2024, "twenty twenty-four"),
        (2099, "twenty ninety-nine"),
    ],
)  # fmt: skip
def test_years_are_said_in_pairs_with_the_thousands_and_the_noughts_as_they_are_sung(
    n: int, words: str
) -> None:
    assert year(n) == words


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "zeroth"), (1, "first"), (2, "second"), (3, "third"), (4, "fourth"), (5, "fifth"),
        (8, "eighth"), (9, "ninth"), (11, "eleventh"), (12, "twelfth"), (20, "twentieth"),
        (21, "twenty-first"), (22, "twenty-second"), (40, "fortieth"), (99, "ninety-ninth"),
        (100, "one hundredth"), (101, "one hundred and first"), (1000, "one thousandth"),
        (1000000, "one millionth"),
    ],
)  # fmt: skip
def test_ordinals_change_the_last_word_only(n: int, words: str) -> None:
    assert ordinal(n) == words


@given(st.integers(0, MILLION))
def test_an_ordinal_differs_from_its_cardinal_in_the_last_word_only(n: int) -> None:
    words = cardinal(n)
    front = words[: max(words.rfind(" "), words.rfind("-")) + 1]
    assert ordinal(n).startswith(front)
    assert ordinal(n) != words
    assert ordinal(n).endswith(("st", "nd", "rd", "th"))


@pytest.mark.parametrize(
    ("text", "spelled"),
    [
        ("1999", "nineteen ninety-nine"),
        ("1999,", "nineteen ninety-nine,"),
        ("1050", "one thousand and fifty"),  # outside the years: a cardinal
        ("2100", "two thousand one hundred"),
        ("12345", "twelve thousand three hundred and forty-five"),
        ("1,234", "one thousand two hundred and thirty-four"),
        ("1,999", "one thousand nine hundred and ninety-nine"),  # grouped: never a year
        ("1st", "first"), ("21ST", "twenty-first"), ("1000000th", "one millionth"),
        ("60s", "sixties"), ("'60s", "'sixties"), ("1960s", "nineteen sixties"),
        ("2010s", "twenty tens"), ("1900s", "nineteen hundreds"), ("10s", "tens"),
        ("65s", "sixty-fives"),  # not a decade: digits inside a word
        ("4ever", "fourever"), ("2good", "twogood"), ("b4", "bfour"),
        ("1000001", "one zero zero zero zero zero one"),  # too big: digit by digit
        ("(42)", "(forty-two)"), ("a 7 b", "a seven b"),
        ("1999th", "one thousand nine hundred and ninety-ninth"),
    ],
)  # fmt: skip
def test_numbers_in_text(text: str, spelled: str) -> None:
    assert ENGLISH.spell_numbers(text) == spelled


def test_a_word_without_digits_stays_as_it_is() -> None:
    assert ENGLISH.spell_numbers("Twinkle,   twinkle\tstar") == "Twinkle,   twinkle\tstar"


@given(st.text(alphabet="0123456789,'sthndr ", max_size=24))
def test_no_digit_survives_and_the_spoken_form_is_only_letters(text: str) -> None:
    spelled = ENGLISH.spell_numbers(text)
    assert not re.search(r"\d", spelled)
    assert set(ENGLISH.normalise(spelled)) <= set("abcdefghijklmnopqrstuvwxyz")


@pytest.mark.parametrize(
    ("text", "spelled"),
    [
        ("2099", "twenty ninety-nine"),  # the last year
        ("1100s", "eleven hundreds"),  # the first decade of a year
        ("1000s", "one thousands"),  # not a year: the number and the plural ending
        ("00s", "zeros"),
        ("10s", "tens"),
    ],
)
def test_the_edges_of_the_years_and_decades(text: str, spelled: str) -> None:
    assert ENGLISH.spell_numbers(text) == spelled


def test_an_ordinal_changes_the_last_of_several_hyphenated_words() -> None:
    assert ordinal(21021) == "twenty-one thousand and twenty-first"


def test_a_very_long_run_of_digits_is_spelled_digit_by_digit() -> None:
    assert ENGLISH.spell_numbers("9" * 5000) == " ".join(["nine"] * 5000)
    # Too long for int() as well: an ordinal or decade ending does not make it one number.
    assert ENGLISH.spell_numbers("9" * 5000 + "th") == " ".join(["nine"] * 5000) + "th"
    assert ENGLISH.spell_numbers("1000001st") == "one zero zero zero zero zero onest"


@pytest.mark.parametrize("word", sorted(EXCEPTIONS))
def test_every_exception_joins_to_the_word_in_any_case(word: str) -> None:
    for written in (word, word.upper(), word.capitalize()):
        assert "".join(ENGLISH.syllables(written)) == written
        assert [p.lower() for p in ENGLISH.syllables(written)] == [
            p.lower() for p in EXCEPTIONS[word]
        ]


@pytest.mark.parametrize(
    ("word", "parts"),
    [
        ("Twinkle", ["Twin", "kle"]),
        ("stranger", ["stranger"]),  # the dictionary's lone "s" is joined to the next part
        ("wall", ["wall"]),  # the lone "l" is joined to the part before
        ("oh", ["oh"]),
        ("you", ["you"]),  # a consonant y does not make a syllable
        ("young", ["young"]),
        ("yesterday", ["yes", "ter", "day"]),
        ("inside", ["in", "side"]),  # a silent e does not either
        ("maybe", ["may", "be"]),  # the exception list
        ("Maybe", ["May", "be"]),
        ("MAYBE", ["MAY", "BE"]),  # an exception keeps the case of the word
        ("ToNight", ["To", "Night"]),
        ("IDEA", ["I", "DE", "A"]),
        ("don't", ["don't"]),
        ("DON'T", ["DON'T"]),
        ("they're", ["they're"]),
        ("I'd", ["I'd"]),
        ("'em", ["'em"]),
        ("rock'n'roll", ["rock'n'", "roll"]),
        ("o'clock", ["o'", "clock"]),
        ("it’s", ["it’s"]),
        ("x-ray", ["x-", "ray"]),
        ("maybe-", ["may", "be-"]),  # an exception before a hyphen
        ("you're-ok", ["you're-", "ok"]),  # a contraction's ending before a hyphen stays bound
        ("a'-'b", ["a'-", "'b"]),
        ("(oh!)", ["(oh!)"]),
        ("", [""]),
        ("...", ["..."]),
    ],
)
def test_syllables(word: str, parts: list[str]) -> None:
    assert ENGLISH.syllables(word) == parts


@given(st.text(alphabet="abcdyeEY'’-.! 12", max_size=20))
def test_syllables_join_to_the_word_and_none_is_empty(word: str) -> None:
    parts = ENGLISH.syllables(word)
    assert "".join(parts) == word
    assert all(parts) or word == ""


def test_the_exceptions_are_written_in_lower_case_and_join_to_the_word() -> None:
    for word, parts in EXCEPTIONS.items():
        assert word == word.lower()
        assert "".join(parts).lower() == word
        assert len(parts) > 1


class FakeDictionary:
    """A hyphenation dictionary that cuts every word at fixed places."""

    def __init__(self, cuts: list[int]) -> None:
        self.cuts = cuts

    def positions(self, word: str) -> list[int]:
        del word
        return self.cuts


def hyphenation(cuts: list[int]) -> Hyphenation:
    fake = cast(pyphen.Pyphen, FakeDictionary(cuts))  # only positions() is used
    return Hyphenation(lambda: fake, VOWELS, {}, lone_edges=True)


def test_a_final_lone_e_joins_the_syllable_before_it_even_of_two() -> None:
    assert hyphenation([2]).syllables("abe") == ["abe"]
    assert hyphenation([1]).syllables("yam") == ["yam"]
    assert hyphenation([1, 2]).syllables("yae") == ["yae"]
    assert hyphenation([2]).syllables("abo") == ["ab", "o"]


def test_the_words_for_lines_sung_together() -> None:
    assert (ENGLISH.together_two, ENGLISH.together_all) == ("Both", "All")
