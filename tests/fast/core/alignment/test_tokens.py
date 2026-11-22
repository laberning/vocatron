"""Stage 1: from lyric lines to targets and back to words."""

import pytest

from fakes.acoustic import SECONDS_PER_FRAME, VOCABULARY, sung
from vocatron.core.alignment.solve import solve
from vocatron.core.alignment.tokens import (
    blank_id,
    build_transcript,
    line_of_target,
    lower_case_vocabulary,
    spoken_form,
)
from vocatron.core.languages.de import GERMAN
from vocatron.core.languages.en import ENGLISH

IDS = {token: index for index, token in enumerate(VOCABULARY)}


def spell(ids: tuple[int, ...]) -> str:
    return "".join(VOCABULARY[i] for i in ids)


def test_words_are_the_pieces_of_a_line_and_targets_separate_them_with_the_delimiter() -> None:
    transcript = build_transcript(["Alle Entchen", "auf dem See"], GERMAN, VOCABULARY)
    assert [w.text for w in transcript.words] == ["Alle", "Entchen", "auf", "dem", "See"]
    assert [w.line for w in transcript.words] == [0, 0, 1, 1, 1]
    assert spell(transcript.targets) == "alle|entchen|auf|dem|see"
    assert transcript.lines == 2


def test_every_word_owns_exactly_its_letters_in_the_targets() -> None:
    transcript = build_transcript(["Schön ist die Straße"], GERMAN, VOCABULARY)
    for word, slot in zip(transcript.words, transcript.slots, strict=True):
        assert slot is not None
        first, last = slot
        assert spell(transcript.targets[first : last + 1]) == word.spoken
    assert transcript.words[3].spoken == "strasse"


def test_numbers_are_spoken_but_shown_as_written() -> None:
    transcript = build_transcript(["Nummer 21"], GERMAN, VOCABULARY)
    assert [w.text for w in transcript.words] == ["Nummer", "21"]
    assert transcript.words[1].spoken == "einundzwanzig"
    assert spoken_form("1999", GERMAN) == "neunzehnhundertneunundneunzig"


def test_a_word_without_sound_has_no_slot_and_no_delimiter() -> None:
    transcript = build_transcript(["ja — nein"], GERMAN, VOCABULARY)
    assert transcript.slots[1] is None
    assert spell(transcript.targets) == "ja|nein"


def test_a_line_that_starts_with_a_silent_word_does_not_start_with_a_delimiter() -> None:
    transcript = build_transcript(["– ja"], GERMAN, VOCABULARY)
    assert spell(transcript.targets) == "ja"


def test_the_delimiter_belongs_to_the_line_of_the_word_after_it() -> None:
    transcript = build_transcript(["ab cd", "ef"], GERMAN, VOCABULARY)
    assert spell(transcript.targets) == "ab|cd|ef"
    assert line_of_target(transcript) == [0, 0, 0, 0, 0, 1, 1, 1]


def test_a_vocabulary_without_the_letters_or_the_delimiter_is_an_error() -> None:
    with pytest.raises(ValueError, match="delimiter"):
        build_transcript(["ja"], GERMAN, ["<pad>", "j", "a"])
    with pytest.raises(ValueError, match="lacks the letters"):
        build_transcript(["jä"], GERMAN, ["<pad>", "|", "j", "a"])


def test_the_blank_is_the_pad_token() -> None:
    assert blank_id(VOCABULARY) == 0
    with pytest.raises(ValueError, match="blank"):
        blank_id(["a", "|"])


def test_targets_belong_to_the_line_of_their_word_after_a_word_without_sound() -> None:
    transcript = build_transcript(["—", "ja nein"], GERMAN, VOCABULARY)
    assert line_of_target(transcript) == [1] * len(transcript.targets)


UPPER_CASE = tuple(t.upper() if t.isalpha() else t for t in VOCABULARY)  # the English model's kind


def test_an_upper_case_vocabulary_is_lowered_and_special_tokens_stay() -> None:
    lowered = lower_case_vocabulary(UPPER_CASE)
    assert lowered == list(VOCABULARY)
    assert {"<pad>", "<s>", "</s>", "<unk>", "|", "'", "-"} <= set(lowered)
    assert lower_case_vocabulary(["[PAD]", "<UNK>", "A", "b"]) == ["[PAD]", "<UNK>", "a", "b"]
    # Only a token in brackets on both sides is special; a half-bracketed one is lowered.
    assert lower_case_vocabulary(["[X", "X]", "<X", "X>"]) == ["[x", "x]", "<x", "x>"]


def test_a_lower_case_vocabulary_comes_out_unchanged() -> None:
    assert lower_case_vocabulary(VOCABULARY) == list(VOCABULARY)  # the German model's vocabulary
    assert lower_case_vocabulary([]) == []


def test_two_tokens_that_become_the_same_are_refused() -> None:
    with pytest.raises(ValueError, match="'A' and 'a' are the same in lower case"):
        lower_case_vocabulary(["<pad>", "A", "a"])


def test_an_upper_case_vocabulary_cannot_be_aligned_before_it_is_lowered() -> None:
    with pytest.raises(ValueError, match="lacks the letters"):
        build_transcript(["Twinkle"], ENGLISH, UPPER_CASE)
    transcript = build_transcript(["Twinkle"], ENGLISH, lower_case_vocabulary(UPPER_CASE))
    assert spell(transcript.targets) == "twinkle"


def test_english_lines_are_aligned_on_canned_log_probabilities_with_a_lowered_vocabulary() -> None:
    lines = ["Twinkle, twinkle, little star", "Mary's lamb in 1999"]
    emissions, transcript, spikes = sung(lines, {0: 100, 1: 400}, module=ENGLISH)
    solution = solve(emissions, lines, None, ENGLISH)
    assert [w.spoken for w in solution.transcript.words] == [
        "twinkle", "twinkle", "little", "star", "marys", "lamb", "in", "nineteenninetynine"
    ]  # fmt: skip
    for slot, timed in zip(transcript.slots, solution.words, strict=True):
        assert slot is not None
        assert timed.start == pytest.approx(spikes[slot[0]] * SECONDS_PER_FRAME)
        assert not timed.estimated
