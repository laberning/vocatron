"""Stage 1: the time of a word split across its syllables."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.alignment.file import AlignedWord
from vocatron.core.languages.de import GERMAN
from vocatron.core.syllables import split_word


def aligned(
    text: str, letters: list[tuple[float, float]], *, estimated: bool = False
) -> AlignedWord:
    spoken = GERMAN.normalise(GERMAN.spell_numbers(text))
    return AlignedWord(
        line=0,
        text=text,
        spoken=spoken,
        start=letters[0][0] if letters else 1.0,
        end=letters[-1][1] if letters else 2.0,
        confidence=0.9,
        estimated=estimated,
        letters=letters,
    )


def spans(count: int, step: float = 0.1) -> list[tuple[float, float]]:
    return [(1.0 + i * step, 1.0 + i * step + 0.04) for i in range(count)]


def test_a_syllable_starts_where_its_first_letter_was_found_and_lasts_until_the_next() -> None:
    word = aligned("Entchen", spans(7))  # Ent-chen
    result = split_word(word, GERMAN)
    assert [s.text for s in result.syllables] == ["Ent", "chen"]
    assert result.syllables[0].start == pytest.approx(1.0)
    assert result.syllables[1].start == pytest.approx(1.3)
    assert result.syllables[0].end == result.syllables[1].start
    assert result.syllables[1].end == word.end
    assert not result.estimated


def test_a_word_of_one_syllable_keeps_the_time_of_the_word() -> None:
    word = aligned("Lied", spans(4))
    (only,) = split_word(word, GERMAN).syllables
    assert (only.start, only.end) == (word.start, word.end)


def test_an_estimated_word_shares_its_time_in_proportion_to_the_syllables() -> None:
    word = AlignedWord(
        line=0, text="Schmetterling", spoken="schmetterling", start=2.0, end=3.3,
        confidence=0.0, estimated=True,
    )  # fmt: skip
    parts = split_word(word, GERMAN).syllables  # Schmet-ter-ling: 6, 3, 4 letters
    assert [round(s.end - s.start, 3) for s in parts] == [0.6, 0.3, 0.4]
    assert parts[0].start == 2.0
    assert parts[-1].end == 3.3


def test_a_number_sung_as_a_word_is_shared_proportionally_because_its_letters_do_not_match() -> (
    None
):
    word = aligned("1999", spans(29))  # one syllable: the written number
    (only,) = split_word(word, GERMAN).syllables
    assert only.text == "1999"
    two = aligned("4ever", spans(8))  # 4e-ver: the digit has no letters of its own
    assert [s.text for s in split_word(two, GERMAN).syllables] == ["4e", "ver"]
    assert split_word(two, GERMAN).syllables[0].end == pytest.approx(
        split_word(two, GERMAN).syllables[1].start
    )


@given(st.text(alphabet="abcdefghilmnorstuäöß", min_size=1, max_size=18), st.floats(0.01, 0.5))
def test_syllables_join_to_the_word_and_fill_its_time_without_gaps(word: str, step: float) -> None:
    letters = spans(len(GERMAN.normalise(word)), step)
    if not letters:
        return
    result = split_word(aligned(word, letters), GERMAN)
    assert "".join(s.text for s in result.syllables) == word
    assert result.syllables[0].start == pytest.approx(result.start)
    assert result.syllables[-1].end == pytest.approx(result.end)
    for before, after in zip(result.syllables, result.syllables[1:], strict=False):
        assert before.end == pytest.approx(after.start)
        assert before.start < after.start


def test_a_syllable_of_one_letter_takes_its_letter_found() -> None:
    word = aligned("aber", spans(4))  # a-ber
    result = split_word(word, GERMAN)
    assert [s.text for s in result.syllables] == ["a", "ber"]
    assert [s.start for s in result.syllables] == pytest.approx([1.0, 1.1])


def test_an_estimated_word_shares_by_letters_even_with_a_syllable_of_one_letter() -> None:
    word = AlignedWord(
        line=0, text="aber", spoken="aber", start=2.0, end=2.4, confidence=0.0, estimated=True
    )
    parts = split_word(word, GERMAN).syllables
    assert [round(s.end - s.start, 3) for s in parts] == [0.1, 0.3]


def test_the_held_time_goes_to_the_last_syllable_and_earlier_ones_keep_their_times() -> None:
    word = aligned("Entchen", spans(7)).model_copy(update={"end": 4.0})  # held to 4.0 s
    first, last = split_word(word, GERMAN).syllables
    assert (first.start, first.end) == pytest.approx((1.0, 1.3))
    assert (last.start, last.end) == pytest.approx((1.3, 4.0))


def test_the_proportional_fallback_shares_the_heard_part_and_holds_the_last_syllable() -> None:
    letters = [(1.0, 1.2), (1.2, 1.4)]  # too few letters for the syllables: the fallback
    word = aligned("Schmetterling", letters).model_copy(update={"end": 3.0})
    parts = split_word(word, GERMAN).syllables  # Schmet-ter-ling: 6, 3, 4 letters
    assert [round(s.end - s.start, 3) for s in parts[:2]] == [
        round(0.4 * 6 / 13, 3),
        round(0.4 * 3 / 13, 3),
    ]
    assert parts[0].start == 1.0
    assert parts[-1].start == pytest.approx(1.0 + 0.4 * 9 / 13)
    assert parts[-1].end == 3.0
