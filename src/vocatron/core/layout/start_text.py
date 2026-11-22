"""The texts of the start screen without the symbols the bundled font cannot draw (ADR-0046)."""

from collections.abc import Container
from typing import NamedTuple

from vocatron.core.glyphs import describe, strip_undrawable
from vocatron.core.lyrics.document import SingerInfo


class DrawableText(NamedTuple):
    """Title, artist and singer names as the font can draw them.

    Attributes:
        title: The title.
        artist: The artist, or ``None``.
        singers: The singers with their cleaned names.
        dropped: A review reason for every symbol that was dropped.
    """

    title: str
    artist: str | None
    singers: dict[int, SingerInfo]
    dropped: tuple[str, ...]


def drawable_text(
    title: str,
    artist: str | None,
    singers: dict[int, SingerInfo],
    drawable: Container[int],
    capitals: bool = False,
) -> DrawableText:
    """Drop the symbols the font cannot draw from the texts of the start screen.

    Args:
        title: The title.
        artist: The artist, or ``None``.
        singers: The singers from the lyrics file.
        drawable: The code points of the font.
        capitals: Title and artist are shown in capitals (the start screen with the wordmark,
            ADR-0055), so a letter its capital lacks fails too.

    Raises:
        UndrawableLetter: If a letter, mark or digit of a text is not in the font.
    """
    reasons: list[str] = []

    def clear(text: str, where: str) -> str:
        found = strip_undrawable(text, drawable, where)
        reasons.extend(
            f"{where}: dropped {describe(code)} (not in the font)" for code in found.dropped
        )
        return found.text

    shown_title = clear(title, "the title")
    shown_artist = None if artist is None else clear(artist, "the artist")
    if capitals:  # the capitals are made in the layout; they must be drawable too
        strip_undrawable(shown_title.upper(), drawable, "the title in capitals")
        if shown_artist is not None:
            strip_undrawable(shown_artist.upper(), drawable, "the artist in capitals")
    named = {
        number: singer
        if singer.name is None
        else singer.model_copy(update={"name": clear(singer.name, f"the name of singer {number}")})
        for number, singer in singers.items()
    }
    return DrawableText(shown_title, shown_artist, named, tuple(reasons))
