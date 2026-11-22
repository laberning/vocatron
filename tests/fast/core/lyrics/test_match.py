"""Stage 1: matching of artist and title, grouping of versions, choice of the best one."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fakes.lyrics import ENTCHEN, HAENSCHEN, VOGEL, synced_of
from vocatron.core.lyrics.match import match_record, normalise
from vocatron.core.lyrics.versions import (
    Candidate,
    choose,
    fits_length,
    group_versions,
    record_text,
)

SONG = (180.0, "Alle meine Entchen")


def record(record_id: int, text: str | None, **more: object) -> Candidate:
    fields: dict[str, object] = {
        "source_id": record_id,
        "artist": "Volkslied",
        "title": "Alle meine Entchen",
        "duration": 180.0,
        "plain": text,
    }
    return Candidate.model_validate(fields | more)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Alle meine Entchen", "alle meine entchen"),
        ("Alle Meine Entchen (Live)", "alle meine entchen"),
        ("Alle meine Entchen - 2011 Remastered", "alle meine entchen"),
        ("Hänschen klein feat. Anna", "hanschen klein"),
        ("Straße", "strasse"),
        ("Hänschen, klein!", "hanschen klein"),
    ],
)
def test_names_are_normalised(name: str, expected: str) -> None:
    assert normalise(name) == expected


@pytest.mark.parametrize(
    ("artist", "title", "found_artist", "found_title", "expected"),
    [
        ("Volkslied", "Hänschen klein", "volkslied", "Hanschen Klein", "exact"),
        ("Volkslied", "Hänschen klein", "Volkslied feat. Anna", "Hänschen klein (Live)", "exact"),
        ("Anna & Ben", "Hänschen klein", "Ben, Anna", "Hänschen klein", "exact"),
        ("Anna", "Hänschen klein", "Anna and Ben", "Hänschen klein", "close"),
        ("Volkslied", "Hänschen klein", "Volkslied", "Hänschen klein 2", "close"),
        ("Volkslied", "Hänschen klein", "Anna", "Hänschen klein", "none"),
        ("Volkslied", "Hänschen klein", "Volkslied", "Kommt ein Vogel geflogen", "none"),
        (None, "Hänschen klein", "Volkslied", "Hänschen klein", "close"),
        ("Volkslied", "Hänschen klein", None, "Hänschen klein", "close"),
        ("", "Hänschen klein", "Volkslied", "Hänschen klein", "close"),
        ("Volkslied", "Max & Moritz", "Volkslied", "Max and Moritz", "exact"),
        ("The Volksmusikanten", "Hänschen klein", "Volksmusikanten", "Hänschen klein", "exact"),
        ("Volkslied", "Hänschen klein", "Volksliedd", "Hänschen klein", "close"),
        ("Anna & Ben", "Hänschen klein", "Anna & Benn", "Hänschen klein", "close"),
        ("Anna & Ben", "Hänschen klein", "Ben & Anna", "Hänschen klein 2", "close"),
        # similarity exactly at the threshold (17 of 20 letters in common) still counts
        (None, "abcdefghijklmnopqrst", None, "abcdefghijklmnopqxyz", "close"),
        (None, "abcdefghijklmnopqrst", None, "abcdefghijklmnopwxyz", "none"),
    ],
)
def test_records_are_matched_by_artist_and_title(
    artist: str | None, title: str, found_artist: str | None, found_title: str, expected: str
) -> None:
    assert match_record(artist, title, found_artist, found_title) == expected


@given(st.text(min_size=1, max_size=20))
def test_normalising_twice_changes_nothing(name: str) -> None:
    assert normalise(normalise(name)) == normalise(name)


def test_records_are_grouped_by_the_similarity_of_their_text() -> None:
    first, second, other = record(1, ENTCHEN), record(2, ENTCHEN.upper()), record(3, VOGEL)
    groups = group_versions(
        [record(4, None), record(5, "x", instrumental=True), first, other, second]
    )
    assert [[c.source_id for c in group] for group in groups] == [[1, 2], [3]]


def test_a_record_with_only_synced_lyrics_is_grouped_by_its_words() -> None:
    synced_only = record(2, None, synced=synced_of(ENTCHEN))
    assert [len(g) for g in group_versions([record(1, ENTCHEN), synced_only])] == [2]


def test_the_largest_group_wins() -> None:
    choice = choose(
        [record(1, VOGEL), record(2, ENTCHEN), record(3, ENTCHEN), record(4, ENTCHEN)], 180
    )
    assert choice is not None
    assert (choice.agreeing, choice.considered) == (3, 4)
    assert choice.chosen.plain == ENTCHEN


def test_a_tie_goes_to_the_group_with_a_fitting_synced_version() -> None:
    plain = record(1, VOGEL)
    synced = record(2, ENTCHEN, synced=synced_of(ENTCHEN))
    choice = choose([plain, synced], 180)
    assert choice is not None
    assert choice.chosen.source_id == 2
    assert choice.synced is not None


def test_a_synced_version_of_the_wrong_length_is_not_used() -> None:
    wrong = record(1, ENTCHEN, synced=synced_of(ENTCHEN), duration=200.0)
    choice = choose([wrong], 180)
    assert choice is not None
    assert choice.synced is None
    assert choice.chosen.source_id == 1


def test_the_plain_text_closest_in_length_is_chosen_inside_a_group() -> None:
    far, near = record(1, ENTCHEN, duration=100.0), record(2, ENTCHEN, duration=181.0)
    choice = choose([far, near], 180)
    assert choice is not None
    assert choice.chosen.source_id == 2
    unknown = choose([far, near], None)
    assert unknown is not None
    assert unknown.chosen.source_id == 1


def test_a_tie_without_synced_lyrics_goes_to_the_first_found() -> None:
    choice = choose([record(1, HAENSCHEN), record(2, VOGEL)], 180)
    assert choice is not None
    assert choice.chosen.source_id == 1


def test_no_lyrics_no_choice() -> None:
    assert choose([], 180) is None
    assert choose([record(1, None), record(2, "x", instrumental=True)], 180) is None


@pytest.mark.parametrize(
    ("duration", "song", "expected"),
    [
        (180.0, 181.9, True),
        (180.0, 182.0, True),
        (180.0, 182.1, False),
        (None, 180.0, False),
        (180.0, None, False),
    ],
)
def test_the_length_must_fit_within_two_seconds(
    duration: float | None, song: float | None, expected: bool
) -> None:
    assert fits_length(duration, song) is expected


def test_messy_text_still_groups_with_the_clean_text() -> None:
    assert (
        len(
            group_versions(
                [record(1, ENTCHEN), record(2, f"[Strophe 1]\n{ENTCHEN}\nText: Volksgut\n")]
            )
        )
        == 1
    )


def test_versions_that_differ_in_many_small_places_still_group() -> None:
    """Long texts are compared without the junk heuristic of difflib, which would split them."""
    words = " ".join((ENTCHEN + HAENSCHEN + VOGEL).split()).split()
    varied = " ".join(f"{word}s" if index % 5 == 0 else word for index, word in enumerate(words))
    assert [len(g) for g in group_versions([record(1, " ".join(words)), record(2, varied)])] == [2]


def test_line_breaks_and_punctuation_do_not_split_versions() -> None:
    one_line = record(1, "Hänschen klein ging allein\n")
    two_lines = record(2, "Hänschen klein\nging allein!\n")
    assert [len(g) for g in group_versions([one_line, two_lines])] == [2]
    short = [record(3, "Hänschen klein"), record(4, "...Hänschen klein!")]
    assert [len(g) for g in group_versions(short)] == [2]
    split = [record(5, "Hänschen klein"), record(6, "Hänschen\nklein")]
    assert [len(g) for g in group_versions(split)] == [2]


def test_similarity_exactly_at_the_threshold_is_the_same_version() -> None:
    same = group_versions([record(1, "abcdefghij"), record(2, "abcdefghix")])  # 9 of 10 letters
    assert [len(g) for g in same] == [2]
    other = group_versions([record(1, "abcdefghij"), record(2, "abcdefghxy")])
    assert [len(g) for g in other] == [1, 1]


def test_inside_a_group_a_plain_text_wins_over_a_closer_synced_only_record() -> None:
    synced_only = record(1, None, synced=synced_of(ENTCHEN), duration=183.0)  # does not fit
    plain = record(2, ENTCHEN, duration=190.0)
    choice = choose([synced_only, plain], 180)
    assert choice is not None
    assert (choice.chosen.source_id, choice.synced) == (2, None)


def test_a_record_without_a_length_is_the_last_choice() -> None:
    choice = choose([record(1, ENTCHEN, duration=None), record(2, ENTCHEN, duration=250.0)], 180)
    assert choice is not None
    assert choice.chosen.source_id == 2


def test_the_text_of_a_record_is_its_plain_text_else_its_synced_lyrics() -> None:
    assert record_text(record(1, ENTCHEN)) == (ENTCHEN, "txt")
    synced = synced_of(ENTCHEN)
    assert record_text(record(2, " \n", synced=synced)) == (synced, "lrc")
    assert record_text(record(3, None)) == ("", "lrc")


def test_a_found_text_that_starts_like_a_singer_header_is_still_grouped() -> None:
    fenced = record(1, "---\n" + ENTCHEN)
    assert [len(g) for g in group_versions([fenced, record(2, ENTCHEN)])] == [2]
