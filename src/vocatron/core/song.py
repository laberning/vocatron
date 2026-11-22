"""Song identity and ``song.json`` (ADR-0006).

The identity (artist and title, from the tags with the file name as fallback) names the output
track and the work folder.
"""

from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict

from vocatron.core.lyrics.file import LyricsFile, ensemble_word
from vocatron.core.names import FALLBACK, safe_name
from vocatron.core.stage_file import StageFile

ARTIST_TITLE_SEPARATOR = " - "
KARAOKE_GENRE = "Karaoke"
"""The genre tag of every output: libraries keep the karaoke versions apart from the originals
(ADR-0031)."""
KARAOKE_COMMENT = "Karaoke version made with Vocatron"
"""The comment tag of every output (ADR-0031)."""


type MediaTags = tuple[tuple[str, str], ...]
"""Ordered ``(key, value)`` tag pairs for the outputs (ADR-0031)."""


class Tags(NamedTuple):
    """What the tags of an audio file say; every field may be missing."""

    artist: str | None
    title: str | None
    duration: float | None


class Identity(BaseModel):
    """Who a song is.

    Attributes:
        artist: The artist, or ``None`` when neither tags nor file name say.
        title: The title; never empty.
    """

    model_config = ConfigDict(frozen=True)

    artist: str | None
    title: str

    @property
    def name(self) -> str:
        """The safe ``Artist - Title`` name (just the title without an artist)."""
        text = self.title if self.artist is None else f"{self.artist} - {self.title}"
        return safe_name(text)


def _clean(text: str | None) -> str | None:
    """Return ``text`` stripped, or ``None`` when it is empty."""
    stripped = (text or "").strip()
    return stripped or None


def identify(tags: Tags | None, file_stem: str) -> Identity:
    """Work out artist and title of a song.

    The tags win. Without a title tag the file name is used: ``Artist - Title`` is split at the
    first separator (an artist tag still wins), anything else is the title.

    Args:
        tags: The tags, or ``None`` when they could not be read.
        file_stem: The file name without its extension.
    """
    artist = _clean(tags.artist) if tags else None
    title = _clean(tags.title) if tags else None
    if title is None:
        head, separator, tail = file_stem.partition(ARTIST_TITLE_SEPARATOR)
        if separator and _clean(tail):
            title = _clean(tail)
            artist = artist or _clean(head)
        else:
            title = _clean(file_stem)
    return Identity(artist=artist, title=title or FALLBACK)


class SongInfo(StageFile):
    """The ``song.json`` stage file written by the probe stage.

    Attributes:
        artist: The artist, or ``None``.
        title: The title.
        name: The safe name of the track and the work folder.
        source_file: File name of the audio file.
        duration: Length in seconds, or ``None`` when unknown.
    """

    SCHEMA_NAME = "song"
    schema_version: Literal[1] = 1
    artist: str | None
    title: str
    name: str
    source_file: str
    duration: float | None


def media_tags(info: SongInfo, lyrics: LyricsFile) -> MediaTags:
    """Return the tags of the MP4 and the MP3 as ordered ``(key, value)`` pairs (ADR-0031).

    The song's own artist and title (the same as the file name and the title card), then the
    fixed genre and comment, then ``tag`` with ``Duet`` to ``Quintet`` when the lyrics have two to
    five singers (ADR-0047). No artist tag without an artist.

    Args:
        info: The song's ``song.json``.
        lyrics: The song's ``lyrics.json``, for its singers.
    """
    artist = () if info.artist is None else (("artist", info.artist),)
    word = ensemble_word(lyrics.lines)
    ensemble = () if word is None else (("tag", word),)
    return (
        ("title", info.title),
        *artist,
        ("genre", KARAOKE_GENRE),
        ("comment", KARAOKE_COMMENT),
        *ensemble,
    )
