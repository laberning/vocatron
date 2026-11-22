"""Versions of the lyrics of one song: grouping by text and the choice of the best-supported one.

Several records of the same song usually carry slightly different texts. Records whose texts are
similar form a group; the group with most members wins, a group with a synced version that fits
the song wins a tie (Findings, ADR-0008).
"""

import re
from difflib import SequenceMatcher

from pydantic import BaseModel, ConfigDict

from vocatron.core.lyrics.clean import clean
from vocatron.core.lyrics.document import Kind, parse

SAME_TEXT = 0.9  # similarity from which two lyrics texts are the same version
LENGTH_TOLERANCE = 2.0  # seconds by which a synced version may differ from the recording
NON_WORD = re.compile(r"[^\w]+")


class Candidate(BaseModel):
    """One lyrics record from a lookup.

    Attributes:
        source_id: The id of the record at the source, if any.
        artist: The artist of the record.
        title: The title of the record.
        album: The album of the record.
        duration: The length of the recording the record belongs to, in seconds.
        instrumental: The source says the song has no lyrics.
        plain: The lyrics as plain text.
        synced: The lyrics as ``.lrc`` text.
    """

    model_config = ConfigDict(frozen=True)

    source_id: int | None = None
    artist: str | None = None
    title: str
    album: str | None = None
    duration: float | None = None
    instrumental: bool = False
    plain: str | None = None
    synced: str | None = None


class Choice(BaseModel):
    """The version chosen from the records found.

    Attributes:
        chosen: The record whose text is used.
        considered: How many records were compared.
        agreeing: How many records have a text similar to the chosen one (including itself).
        synced: A record of the winning group with synced lyrics that fit the recording, if any.
    """

    model_config = ConfigDict(frozen=True)

    chosen: Candidate
    considered: int
    agreeing: int
    synced: Candidate | None


def fits_length(duration: float | None, song_duration: float | None) -> bool:
    """Tell whether a recording of ``duration`` seconds is the length of the song within 2 s."""
    if duration is None or song_duration is None:
        return False
    return abs(duration - song_duration) <= LENGTH_TOLERANCE


def record_text(candidate: Candidate) -> tuple[str, Kind]:
    """Return the lyrics of a record and their kind: the plain text, else the synced lyrics."""
    plain = candidate.plain
    if plain is not None and plain.strip():
        return plain, "txt"
    return candidate.synced or "", "lrc"


def has_plain(candidate: Candidate) -> bool:
    """Tell whether a record has plain lyrics with something in them."""
    return record_text(candidate)[1] == "txt"


def _key(candidate: Candidate) -> str:
    """Return the sung words of a record in lower case, for comparison.

    Junk (headings, repeat markers, credits) is cleaned away first, so a messy version groups
    with a clean one.
    """
    lines = clean(parse(*record_text(candidate), header=False).lines).lines
    return NON_WORD.sub(" ", " ".join(line.text for line in lines).casefold()).strip()


def _similar(first: str, second: str) -> bool:
    """Tell whether two texts are the same version of the lyrics."""
    return SequenceMatcher(None, first, second, autojunk=False).ratio() >= SAME_TEXT


def group_versions(candidates: list[Candidate]) -> list[list[Candidate]]:
    """Group records by the similarity of their texts, in order of first appearance.

    Records without a text and instrumentals are left out.
    """
    groups: list[tuple[str, list[Candidate]]] = []
    for candidate in candidates:
        key = _key(candidate)
        if candidate.instrumental or not key:
            continue
        for head, members in groups:
            if _similar(head, key):
                members.append(candidate)
                break
        else:
            groups.append((key, [candidate]))
    return [members for _, members in groups]


def _synced_fit(members: list[Candidate], song_duration: float | None) -> Candidate | None:
    """Return the first synced record of a group that fits the recording."""
    for member in members:
        if member.synced and fits_length(member.duration, song_duration):
            return member
    return None


def _closest(members: list[Candidate], song_duration: float | None) -> Candidate:
    """Return the record with a plain text whose length is closest to the song's."""
    texts = [m for m in members if has_plain(m)] or members
    if song_duration is None:
        return texts[0]
    return min(
        texts, key=lambda m: float("inf") if m.duration is None else abs(m.duration - song_duration)
    )


def choose(candidates: list[Candidate], song_duration: float | None) -> Choice | None:
    """Choose the best-supported version.

    The largest group wins; on a tie the group with a synced version that fits the recording, then
    the group that was found first. Inside the group a fitting synced record is preferred.

    Args:
        candidates: The records that match the song.
        song_duration: The length of the song in seconds, if known.

    Returns:
        The choice, or ``None`` when no record has lyrics.
    """
    groups = group_versions(candidates)
    if not groups:
        return None
    ranked = sorted(
        enumerate(groups),
        key=lambda item: (
            -len(item[1]),
            _synced_fit(item[1], song_duration) is None,
            item[0],
        ),
    )
    members = ranked[0][1]
    synced = _synced_fit(members, song_duration)
    return Choice(
        chosen=synced or _closest(members, song_duration),
        considered=sum(len(group) for group in groups),
        agreeing=len(members),
        synced=synced,
    )
