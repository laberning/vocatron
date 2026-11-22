"""Stage 1: the texts of the start screen without symbols the font cannot draw (ADR-0046)."""

import pytest

from vocatron.core.glyphs import UndrawableLetter
from vocatron.core.layout.start_text import drawable_text
from vocatron.core.lyrics.document import SingerInfo

FONT = frozenset(ord(c) for c in "abcdefghijklmnopqrstuvwxyz 12")


def test_symbols_are_dropped_from_title_artist_and_singer_names_with_a_reason_each() -> None:
    singers = {1: SingerInfo(name="ab♥", colour="#112233"), 2: SingerInfo(colour="#445566")}
    shown = drawable_text("ab √ cd", "ef♥", singers, FONT)
    assert (shown.title, shown.artist) == ("ab cd", "ef")
    assert shown.singers == {1: SingerInfo(name="ab", colour="#112233"), 2: singers[2]}
    assert shown.dropped == (
        "the title: dropped U+221A SQUARE ROOT (not in the font)",
        "the artist: dropped U+2665 BLACK HEART SUIT (not in the font)",
        "the name of singer 1: dropped U+2665 BLACK HEART SUIT (not in the font)",
    )


def test_texts_the_font_draws_are_left_alone() -> None:
    shown = drawable_text("ab  cd", None, {}, FONT)
    assert (shown.title, shown.artist, shown.dropped) == ("ab  cd", None, ())


@pytest.mark.parametrize(
    ("title", "artist", "where"),
    [("ab Ж", "cd", "the title"), ("ab", "Ж", "the artist")],
)
def test_a_letter_the_font_lacks_fails(title: str, artist: str, where: str) -> None:
    with pytest.raises(UndrawableLetter, match=f"^{where}: U\\+0416"):
        drawable_text(title, artist, {}, FONT)


def test_a_singer_name_with_a_missing_letter_names_the_singer() -> None:
    with pytest.raises(UndrawableLetter, match="the name of singer 3"):
        drawable_text("ab", None, {3: SingerInfo(name="Ж")}, FONT)


def test_a_letter_whose_capital_the_font_lacks_fails_when_the_texts_are_shown_in_capitals() -> None:
    lower_only = frozenset(ord(c) for c in "abc ")
    assert drawable_text("abc", "cab", {}, lower_only).title == "abc"  # as written it is fine
    with pytest.raises(UndrawableLetter, match="^the title in capitals: "):
        drawable_text("abc", None, {}, lower_only, capitals=True)
    without_b = lower_only | frozenset(ord(c) for c in "AC")
    with pytest.raises(UndrawableLetter, match="^the artist in capitals: "):
        drawable_text("a", "cab", {}, without_b, capitals=True)
