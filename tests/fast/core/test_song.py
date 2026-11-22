"""Stage 1: song identity from tags and file names."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.lyrics.document import Mark
from vocatron.core.lyrics.file import LyricLine, LyricsFile, ensemble_word
from vocatron.core.names import FORBIDDEN
from vocatron.core.song import (
    KARAOKE_COMMENT,
    KARAOKE_GENRE,
    Identity,
    SongInfo,
    Tags,
    identify,
    media_tags,
)
from vocatron.core.stage_file import Fingerprint


def test_tags_win_over_the_file_name() -> None:
    identity = identify(Tags(" Queen ", "Bohemian Rhapsody", 1.0), "01 - something else")
    assert identity == Identity(artist="Queen", title="Bohemian Rhapsody")
    assert identity.name == "Queen - Bohemian Rhapsody"


def test_file_name_is_split_at_the_first_separator() -> None:
    assert identify(None, "ABBA - Mamma Mia - Remix") == Identity(
        artist="ABBA", title="Mamma Mia - Remix"
    )


def test_an_artist_tag_beats_the_artist_from_the_file_name() -> None:
    assert identify(Tags("Tag", None, None), "Name - Song") == Identity(artist="Tag", title="Song")


def test_a_file_name_without_separator_is_the_title() -> None:
    identity = identify(Tags(None, None, None), "just a song")
    assert identity == Identity(artist=None, title="just a song")
    assert identity.name == "just a song"


def test_a_title_tag_alone_stays_without_artist() -> None:
    assert identify(Tags(None, "Only Title", None), "A - B") == Identity(
        artist=None, title="Only Title"
    )


def test_empty_pieces_fall_back() -> None:
    assert identify(None, "Artist - ").title == "Artist -"
    assert identify(None, "").title == "untitled"


@given(st.text(max_size=50), st.text(max_size=50), st.text(max_size=80))
def test_the_name_is_always_safe(artist: str, title: str, stem: str) -> None:
    for identity in (identify(Tags(artist, title, None), stem), identify(None, stem)):
        assert identity.name
        assert not FORBIDDEN.search(identity.name)


def info(artist: str | None) -> SongInfo:
    return SongInfo(
        fingerprint=Fingerprint(inputs={}, settings="", stage_version=1),
        artist=artist,
        title="Title",
        name="x",
        source_file="x.mp3",
        duration=1.0,
    )


def lyrics_of(*marks: str, turns: tuple[str, ...] = ()) -> LyricsFile:
    """Return lyrics whose lines are sung by ``marks`` and whose first line turns to ``turns``."""
    lines = [LyricLine(text="la", singers=mark) for mark in marks]
    if turns and lines:
        lines[0] = LyricLine(
            text="la la", singers=marks[0], turns=[Mark(word=1, singers=t) for t in turns]
        )
    return LyricsFile(
        fingerprint=Fingerprint(inputs={}, settings="", stage_version=1),
        source="sidecar",
        sidecar="x.txt",
        sidecar_hash="0",
        original="",
        lines=lines,
        singers={},
        duet=False,
        language="en",
        removed=[],
        findings=[],
        approved=False,
        status="ok",
    )


def test_the_media_tags_are_title_artist_genre_and_comment_in_this_order() -> None:
    assert media_tags(info("Artist"), lyrics_of("1")) == (
        ("title", "Title"),
        ("artist", "Artist"),
        ("genre", KARAOKE_GENRE),
        ("comment", KARAOKE_COMMENT),
    )
    assert (KARAOKE_GENRE, KARAOKE_COMMENT) == ("Karaoke", "Karaoke version made with Vocatron")


def test_a_song_without_an_artist_gets_no_artist_tag() -> None:
    assert [key for key, _ in media_tags(info(None), lyrics_of("1"))] == [
        "title",
        "genre",
        "comment",
    ]


@pytest.mark.parametrize(
    ("marks", "word"),
    [(("1", "2"), "Duet"), (("1", "2", "3"), "Trio"), (("4", "1", "3", "2"), "Quartet"),
     (("1", "2", "3", "4", "5"), "Quintet")],
)  # fmt: skip
def test_the_word_comes_last_after_the_comment(marks: tuple[str, ...], word: str) -> None:
    tags = media_tags(info("Artist"), lyrics_of(*marks))
    assert tags[-2:] == (("comment", KARAOKE_COMMENT), ("tag", word))


def test_one_singer_or_none_gives_no_tag_field() -> None:
    assert "tag" not in dict(media_tags(info("A"), lyrics_of("1", "1")))
    assert "tag" not in dict(media_tags(info("A"), lyrics_of()))


def test_a_song_flagged_as_a_duet_only_by_its_name_gets_no_tag_field() -> None:
    lyrics = lyrics_of("1", "1").model_copy(update={"duet": True})
    assert "tag" not in dict(media_tags(info("A"), lyrics))


def test_the_singers_of_a_change_inside_a_line_count() -> None:
    assert ensemble_word(lyrics_of("1", turns=("2",)).lines) == "Duet"


def test_all_and_groups_add_no_singers() -> None:
    assert ensemble_word(lyrics_of("1", "all", "1,2", "2").lines) == "Duet"
    assert ensemble_word(lyrics_of("all", "1,3", "1", turns=("all",)).lines) is None
    assert ensemble_word(lyrics_of("1", "2", turns=("1,3", "all")).lines) == "Duet"


@given(
    marks=st.lists(st.sampled_from(["1", "2", "3", "4", "5", "all", "1,2", "2,5"]), max_size=12),
    turns=st.lists(st.sampled_from(["1", "2", "3", "4", "5", "all", "3,4"]), max_size=4),
)
def test_the_word_follows_the_number_of_different_singer_numbers(
    marks: list[str], turns: list[str]
) -> None:
    lyrics = lyrics_of(*marks, turns=tuple(turns))
    counted = {m for m in [*marks, *(turns if marks else [])] if m.isdecimal()}
    expected = {2: "Duet", 3: "Trio", 4: "Quartet", 5: "Quintet"}.get(len(counted))
    assert ensemble_word(lyrics.lines) == expected
