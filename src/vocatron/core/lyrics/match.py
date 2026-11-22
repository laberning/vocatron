"""Matching of the artist and title of a song with those of a lyrics record (Findings, ADR-0002).

Names are compared after normalisation: case, accents, ``feat.`` parts, brackets and punctuation
do not count. A record is dropped when it does not match, and it is only trusted when it matches
exactly.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal

Match = Literal["exact", "close", "none"]

CLOSE = 0.85  # similarity from which two names count as the same
BRACKETS = re.compile(r"[(\[{][^()\[\]{}]*[)\]}]")
FEATURING = re.compile(r"\b(?:feat|ft|featuring)\b\.?.*$")
VERSION_SUFFIX = re.compile(
    r"\s+-\s+(?:\d{4}\s+)?(?:remaster\w*|live|radio edit|single version|album version|mono|stereo|"
    r"version).*$"
)
ARTIST_SEPARATOR = re.compile(r"\s*(?:,|&|\band\b|\bund\b|\bx\b)\s*")
NON_WORD = re.compile(r"[^\w]+")


def normalise(name: str) -> str:
    """Normalise a name for comparison: lower case, no accents, brackets, ``feat.`` or punctuation.

    ``ß`` becomes ``ss``; the result is lower-case words separated by single spaces.
    """
    folded = unicodedata.normalize("NFKD", name.casefold())
    text = "".join(char for char in folded if not unicodedata.combining(char))
    text = BRACKETS.sub(" ", text)
    text = VERSION_SUFFIX.sub("", text.strip())
    text = FEATURING.sub("", text)
    return NON_WORD.sub(" ", text.replace("&", " and ")).strip()


def _artists(name: str) -> frozenset[str]:
    """Return the normalised artists of an artist credit (``A & B``, ``A, B``, ``A and B``).

    The credit is split before it is normalised, which would remove the separators.
    """
    parts = (normalise(part) for part in ARTIST_SEPARATOR.split(FEATURING.sub("", name.casefold())))
    return frozenset(part.removeprefix("the ") for part in parts if part)


def _similar(first: str, second: str) -> bool:
    """Tell whether two normalised names are the same name with a small difference."""
    return first == second or SequenceMatcher(None, first, second).ratio() >= CLOSE


def _artist_match(wanted: str, found: str) -> Match:
    """Compare two artist credits."""
    first, second = _artists(wanted), _artists(found)
    if first == second:
        return "exact"
    if first.issubset(second) or second.issubset(first):
        return "close"
    return "close" if _similar(" ".join(sorted(first)), " ".join(sorted(second))) else "none"


def match_record(
    artist: str | None, title: str, found_artist: str | None, found_title: str
) -> Match:
    """Compare the artist and title of a song with those of a record.

    Args:
        artist: The artist of the song, or ``None`` when unknown.
        title: The title of the song.
        found_artist: The artist of the record, or ``None``.
        found_title: The title of the record.

    Returns:
        ``exact`` when both match after normalisation, ``close`` when they are similar (or the
        artist cannot be compared), ``none`` when the record is another song.
    """
    wanted_title, found = normalise(title), normalise(found_title)
    if not _similar(wanted_title, found):
        return "none"
    title_exact = wanted_title == found
    if artist is None or found_artist is None or not normalise(artist):
        return "close"
    artist_match = _artist_match(artist, found_artist)
    return "close" if artist_match == "exact" and not title_exact else artist_match
