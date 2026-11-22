"""Stage 1: the lines as the layout sees them: syllables, singers and turns (ADR-0018)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fakes.timed import timed_song
from vocatron.core.layout.phrases import (
    TOGETHER_SECONDS,
    Phrase,
    Piece,
    Turn,
    by_voice,
    is_ensemble,
    marks_of,
    one_after_another,
    phrases_from,
)


def test_the_syllables_of_a_line_join_to_the_line_and_a_space_follows_each_word() -> None:
    song = timed_song("Alle meine Entchen\nschwimmen auf dem See")
    first, second = phrases_from(song.words, song.lines)
    assert first.text == "Alle meine Entchen"
    assert second.text == "schwimmen auf dem See"
    assert all(
        a.end <= b.start + 1e-9 for a, b in zip(first.pieces, first.pieces[1:], strict=False)
    )
    assert not first.pieces[-1].text.endswith(" ")


def test_the_profile_case_is_applied_to_the_text() -> None:
    song = timed_song("Alle meine")
    assert phrases_from(song.words, song.lines, "upper")[0].text == "ALLE MEINE"
    assert phrases_from(song.words, song.lines, "lower")[0].text == "alle meine"


def test_a_line_takes_the_singers_of_its_lyrics_line() -> None:
    song = timed_song("eins\nzwei", singers=["2", "all"])
    assert [p.singers for p in phrases_from(song.words, song.lines)] == ["2", "all"]


def test_phrases_come_out_ordered_by_their_start() -> None:
    song = timed_song("eins\nzwei")
    reordered = [*song.words[1:], song.words[0]]
    starts = [p.start for p in phrases_from(reordered, song.lines)]
    assert starts == sorted(starts)


def test_a_change_inside_a_line_becomes_a_turn_at_the_first_syllable_of_its_word() -> None:
    song = timed_song("Alle meine Entchen schwimmen", turns={0: [(2, "2")]})
    (phrase,) = phrases_from(song.words, song.lines)
    first_syllable = sum(len(word.syllables) for word in song.words[:2])
    assert phrase.turns == (Turn(first_syllable, "2"),)
    assert phrase.pieces[first_syllable].text.startswith("Ent")
    assert [phrase.singers_at(i) for i in (0, first_syllable - 1, first_syllable)] == [
        "1",
        "1",
        "2",
    ]


def test_a_line_without_changes_has_no_turns_and_lines_are_never_merged() -> None:
    song = timed_song("eins\nzwei", singers=["1", "2"], turns={1: []})
    phrases = phrases_from(song.words, song.lines)
    assert [p.turns for p in phrases] == [(), ()]
    assert len(phrases) == 2


def test_a_turn_outside_the_words_of_a_line_is_ignored() -> None:
    song = timed_song("eins zwei", turns={0: [(0, "2"), (2, "3"), (7, "3")]})
    assert phrases_from(song.words, song.lines)[0].turns == ()


def test_the_singers_at_a_syllable_follow_the_last_turn_before_it() -> None:
    pieces = tuple(Piece(str(i), i, i + 1) for i in range(6))
    phrase = Phrase("1", pieces, (Turn(2, "2"), Turn(4, "all")))
    assert [phrase.singers_at(i) for i in range(6)] == ["1", "1", "2", "2", "all", "all"]


def test_a_turn_at_the_second_word_is_a_turn_and_lines_beyond_the_lyrics_belong_to_singer_one() -> (
    None
):
    song = timed_song("eins zwei drei\nvier fünf", singers=["2", "3"], turns={0: [(1, "all")]})
    first, second = phrases_from(song.words, song.lines[:1])
    first_syllables = len(song.words[0].syllables)
    assert (first.singers, first.turns) == ("2", (Turn(first_syllables, "all"),))
    assert (second.singers, second.turns) == ("1", ())  # no lyrics line for it: singer 1, no turns


def test_a_line_takes_the_voice_of_the_syllables_file_or_else_of_the_lyrics_line() -> None:
    song = timed_song("eins\nzwei\ndrei")
    lines = [song.lines[0], song.lines[1].model_copy(update={"voice": 2}), song.lines[2]]
    assert [p.voice for p in phrases_from(song.words, lines)] == [1, 2, 1]
    assert [p.voice for p in phrases_from(song.words, lines, voices=[1, 1, 2])] == [1, 1, 2]


def test_a_second_voice_line_without_its_own_mark_is_tinted_with_singer_2_for_the_colour() -> None:
    song = timed_song("eins\nzwei\ndrei\nvier", singers=["1", "1", "3", "1"])
    own = song.lines[2].model_copy(update={"own_mark": True})
    lines = [song.lines[0], song.lines[1], own, song.lines[3]]
    phrases = phrases_from(song.words, lines, voices=[1, 2, 2, 1])
    assert [(p.singers, p.tint, p.shown_singers) for p in phrases] == [
        ("1", None, "1"),
        ("1", "2", "2"),  # no mark of its own: the colour of singer 2
        ("3", None, "3"),  # its own mark counts
        ("1", None, "1"),
    ]
    assert marks_of(phrases) == ["1", "3"]  # the tint makes no singer: no duet (ADR-0047)
    assert not is_ensemble(marks_of(phrases[:2]))


def test_lines_of_the_two_voices_may_overlap_but_those_of_one_voice_follow_each_other() -> None:
    first = [piece("a", 10.0, 14.0)], [piece("b", 13.0, 16.0)]  # one voice: squeezed
    second = [piece("c", 11.0, 15.0)]
    phrases = [
        Phrase("1", tuple(first[0])),
        Phrase("1", tuple(second), voice=2, tint="2"),
        Phrase("1", tuple(first[1])),
    ]
    out = by_voice(phrases)
    assert [(p.voice, p.start) for p in out] == [(1, 10.0), (2, 11.0), (1, 13.0)]
    assert out[0].end == pytest.approx(13.0)  # the first voice's line is cut by its own next line
    assert out[1].end == 15.0  # the other voice's line is not
    assert out[1].tint == "2"


def piece(text: str, start: float, end: float) -> Piece:
    return Piece(text, start, end)


def test_lines_of_two_voices_are_shown_one_after_another_until_the_next_starts() -> None:
    first = Phrase("1", (piece("a ", 0.0, 2.0), piece("b", 2.0, 6.0)))
    second = Phrase("2", (piece("c", 4.0, 7.0),))
    cut, whole = one_after_another([first, second])
    assert [(p.start, p.end) for p in cut.pieces] == [
        (0.0, 4 / 3),
        (4 / 3, 4.0),
    ]  # squeezed until c
    assert whole == second


def test_two_lines_that_start_together_share_the_time_of_the_first() -> None:
    first = Phrase("1", (piece("a", 5.0, 8.0),))
    second = Phrase("2", (piece("b", 5.0, 7.0),))
    after = Phrase("1", (piece("c", 8.0, 9.0),))  # the first voice goes on where its line ends
    squeezed, moved, kept = one_after_another([first, second, after])
    assert (squeezed.start, squeezed.end) == (5.0, 6.5)
    assert (moved.start, moved.end) == (6.5, 8.0)  # cut where the next line starts
    assert kept == after  # never pushed back


def test_a_line_that_starts_just_after_the_one_before_starts_together_with_it() -> None:
    first = Phrase("1", (piece("a", 5.0, 8.0),))
    close = Phrase("2", (piece("b", 5.0 + TOGETHER_SECONDS * 0.9, 7.0),))
    squeezed, moved = one_after_another([first, close])
    assert squeezed.end == pytest.approx(6.5)  # not squeezed into no time
    assert moved.start == pytest.approx(6.5)
    later = Phrase("2", (piece("b", 5.0 + TOGETHER_SECONDS * 1.1, 7.0),))
    cut, whole = one_after_another([first, later])
    assert (cut.end, whole) == (pytest.approx(later.start), later)


def test_a_squeezed_line_keeps_every_syllable_some_time() -> None:
    first = Phrase("1", tuple(piece("a", 1.0 + 0.1 * i, 1.1 + 0.1 * i) for i in range(30)))
    second = Phrase("2", (piece("b", 1.5, 2.0),))
    cut, _ = one_after_another([first, second])
    assert all(p.end > p.start for p in cut.pieces)
    assert (cut.start, cut.end) == (1.0, pytest.approx(1.5))


def test_lines_that_do_not_overlap_come_back_unchanged() -> None:
    lines = [Phrase("1", (piece("a", 0.0, 1.0),)), Phrase("2", (piece("b", 1.0, 2.0),))]
    assert one_after_another(lines) == lines


@given(
    st.lists(
        st.tuples(st.floats(0, 100), st.lists(st.floats(0.01, 5), min_size=1, max_size=4)),
        max_size=8,
    )
)
def test_the_result_never_overlaps_and_keeps_every_syllable(
    spans: list[tuple[float, list[float]]],
) -> None:
    phrases: list[Phrase] = []
    for start, lengths in sorted(spans):
        cursor = start
        pieces: list[Piece] = []
        for length in lengths:
            pieces.append(piece("x", cursor, cursor + length))
            cursor += length
        phrases.append(Phrase("1", tuple(pieces)))
    result = one_after_another(phrases)
    assert [len(p.pieces) for p in result] == [len(p.pieces) for p in phrases]
    assert all(a.end <= b.start + 1e-9 for a, b in zip(result, result[1:], strict=False))


def test_a_line_exactly_together_with_the_one_before_shares_its_time_and_keeps_its_turns() -> None:
    turns = (Turn(1, "2"),)
    first = Phrase("1", (piece("a ", 5.0, 6.0), piece("b", 6.0, 8.0)), turns)
    second = Phrase("2", (piece("c ", 5.1, 6.0), piece("d", 6.0, 7.0)), turns)
    assert second.start - first.start <= TOGETHER_SECONDS  # 5.1 - 5.0 rounds below it
    squeezed, moved = one_after_another([first, second])
    assert (squeezed.end, moved.start) == (6.5, 6.5)
    assert squeezed.turns == turns and moved.turns == turns
