"""Stage 1: what is specific to German: number words, years, hyphenation."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.languages.de import GERMAN, MILLION, cardinal, year

UNITS = {
    "null": 0, "eins": 1, "ein": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6,
    "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "dreizehn": 13,
    "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16, "siebzehn": 17, "achtzehn": 18,
    "neunzehn": 19, "zwanzig": 20, "dreißig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60,
    "siebzig": 70, "achtzig": 80, "neunzig": 90,
}  # fmt: skip


def read(words: str) -> int:
    """Read a German number word back into a number: the inverse of ``cardinal``."""
    if words == "einemillion":
        return MILLION
    for marker, factor in (("tausend", 1000), ("hundert", 100)):
        if marker in words:
            head, _, tail = words.partition(marker)
            return (read(head) if head else 1) * factor + (read(tail) if tail else 0)
    if "und" in words:
        ones, _, tens = words.partition("und")
        return UNITS[ones] + UNITS[tens]
    return UNITS[words]


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (0, "null"), (1, "eins"), (12, "zwölf"), (16, "sechzehn"), (21, "einundzwanzig"),
        (30, "dreißig"), (99, "neunundneunzig"), (100, "einhundert"), (101, "einhunderteins"),
        (110, "einhundertzehn"), (342, "dreihundertzweiundvierzig"), (1000, "eintausend"),
        (1001, "eintausendeins"), (21000, "einundzwanzigtausend"),
        (100000, "einhunderttausend"),
        (999999, "neunhundertneunundneunzigtausendneunhundertneunundneunzig"),
        (1000000, "einemillion"),
    ],
)  # fmt: skip
def test_cardinals(n: int, words: str) -> None:
    assert cardinal(n) == words


@given(st.integers(0, MILLION))
def test_a_spelled_number_reads_back_as_itself(n: int) -> None:
    assert read(cardinal(n)) == n


@pytest.mark.parametrize(
    ("n", "words"),
    [
        (1100, "elfhundert"), (1789, "siebzehnhundertneunundachtzig"),
        (1900, "neunzehnhundert"), (1984, "neunzehnhundertvierundachtzig"),
        (2000, "zweitausend"), (2024, "zweitausendvierundzwanzig"),
    ],
)  # fmt: skip
def test_years_are_said_in_hundreds_until_1999(n: int, words: str) -> None:
    assert year(n) == words


def test_a_lone_four_digit_number_in_the_year_range_is_a_year_otherwise_a_cardinal() -> None:
    assert GERMAN.spell_numbers("1999") == "neunzehnhundertneunundneunzig"
    assert GERMAN.spell_numbers("1999,") == "neunzehnhundertneunundneunzig,"
    assert GERMAN.spell_numbers("1050") == "eintausendfünfzig"
    assert GERMAN.spell_numbers("2100") == "zweitausendeinhundert"
    assert GERMAN.spell_numbers("Jahr 1999 war 1999er") == (
        "Jahr neunzehnhundertneunundneunzig war eintausendneunhundertneunundneunziger"
    )


def test_digits_inside_words_are_spelled_and_joined() -> None:
    assert GERMAN.spell_numbers("Mach3") == "Machdrei"
    assert GERMAN.spell_numbers("1999er") == "eintausendneunhundertneunundneunziger"


def test_runs_of_digits_longer_than_a_million_are_read_digit_by_digit() -> None:
    assert GERMAN.spell_numbers("12345678") == "eins zwei drei vier fünf sechs sieben acht"


@pytest.mark.parametrize(
    ("word", "parts"),
    [
        ("Schmetterling", ["Schmet", "ter", "ling"]),
        ("Denkmal", ["Denk", "mal"]),
        ("Haus", ["Haus"]),
        ("Mädchen!", ["Mäd", "chen!"]),
        ("(Hallo)", ["(Hal", "lo)"]),
        ("Lied", ["Lied"]),  # no syllable without a vowel: Lie-d would not be sung
        ("—", ["—"]),
        ("-", ["-"]),
    ],
)
def test_syllables_keep_their_punctuation_and_never_lack_a_vowel(
    word: str, parts: list[str]
) -> None:
    assert GERMAN.syllables(word) == parts


def test_a_capitalised_exception_keeps_its_capital() -> None:
    assert GERMAN.syllables("Idee") == ["I", "dee"]
    assert GERMAN.syllables("idee,") == ["i", "dee,"]
    assert GERMAN.syllables("IDEE") == ["I", "DEE"]  # the word's own case: they join to it


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyzäöüßABC-,.!'(", min_size=1, max_size=25))
def test_german_syllables_join_to_the_word(word: str) -> None:
    assert "".join(GERMAN.syllables(word)) == word


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyzäöüß", min_size=1, max_size=25))
def test_every_syllable_of_a_plain_word_has_a_vowel_unless_the_word_has_none(word: str) -> None:
    parts = GERMAN.syllables(word)
    if len(parts) > 1:
        assert all(any(c in "aeiouyäöü" for c in part) for part in parts)


def test_the_ends_of_the_year_range_are_years() -> None:
    assert GERMAN.spell_numbers("1100") == "elfhundert"
    assert GERMAN.spell_numbers("2099") == "zweitausendneunundneunzig"
    assert year(2099) == "zweitausendneunundneunzig"
    assert year(1901) == "neunzehnhunderteins"


def test_a_number_above_a_million_with_seven_digits_is_read_digit_by_digit() -> None:
    assert GERMAN.spell_numbers("2000000") == "zwei null null null null null null"


def test_the_exceptions_hold_inside_hyphenated_words_and_before_a_trailing_hyphen() -> None:
    assert GERMAN.syllables("Idee-") == ["I", "dee-"]
    assert GERMAN.syllables("Idee-Haus") == ["I", "dee-", "Haus"]


def test_the_shared_text_rules_leave_the_german_results_as_they_were() -> None:
    # Recorded from the module before its hyphenation and word edges moved to ``base``
    # (an apostrophe is no joiner in German, a part without a vowel after a hyphen stays alone).
    assert GERMAN.syllables("k-l") == ["k-", "l"]
    assert GERMAN.syllables("geht's") == ["geht's"]
    assert GERMAN.syllables("idee") == ["i", "dee"]
    assert GERMAN.syllables("(Idee!)") == ["(I", "dee!)"]
    assert GERMAN.spell_numbers("'60er 1050 4ever (1999)") == (
        "'sechziger eintausendfünfzig vierever (neunzehnhundertneunundneunzig)"
    )


def test_twenty_is_the_first_number_made_of_tens() -> None:
    assert [GERMAN.spell_numbers(n) for n in ("19", "20", "120", "20000")] == [
        "neunzehn",
        "zwanzig",
        "einhundertzwanzig",
        "zwanzigtausend",
    ]


def test_the_words_for_lines_sung_together() -> None:
    assert (GERMAN.together_two, GERMAN.together_all) == ("Beide", "Alle")
