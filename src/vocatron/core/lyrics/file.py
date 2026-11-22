"""``lyrics.json``: the stage file of the lyrics stage (ADR-0006, ADR-0008)."""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from vocatron.core.lyrics.clean import Removal
from vocatron.core.lyrics.document import (
    FIRST_VOICE,
    Mark,
    SingerInfo,
    Voice,
    is_single_singer,
)
from vocatron.core.lyrics.match import Match
from vocatron.core.lyrics.verdict import Source
from vocatron.core.stage_file import StageFile


class LyricLine(BaseModel):
    """One cleaned line of the lyrics, with its singers resolved.

    Attributes:
        text: The words, without singer marks.
        singers: Who sings its first word: ``1``, ``1,3`` or ``all``.
        turns: Where the singers change inside the line: the index of the word and the singers
            from there on; empty for a line sung by one voice or group.
        voice: ``2`` for a line that a second voice sings at the same time as the first: marked
            ``{&}`` in the file or sharing its ``.lrc`` time with the line before (ADR-0052);
            ``1`` otherwise (and then not written to the file). The audio can add second-voice
            lines in ``alignment.json``.
        own_mark: The line has a singer mark at its start in the file (not counting ``{&}``), so it
            keeps its singers; a second-voice line without one is drawn in the colour of singer 2
            from its start (ADR-0054); a mark in the middle of a line changes the colour from that
            word on. Not written for a line without a mark at its start.
        time: The line time in seconds from a synced ``.lrc``, a hint only.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    singers: str
    turns: list[Mark] = Field(default_factory=list)
    voice: Voice = Field(default=FIRST_VOICE, exclude_if=lambda voice: voice == FIRST_VOICE)
    own_mark: bool = Field(default=False, exclude_if=lambda own: not own)
    time: float | None = None


class LyricsFile(StageFile):
    """The lyrics with their status.

    ``reasons`` (of the base class) are the reasons for review that still stand: empty when the
    lyrics are ``ok`` or approved. ``findings`` are what the checks found whether or not the lyrics
    were approved.

    Attributes:
        source: ``sidecar`` (a file of the fan) or ``lookup`` (found online and written by
            Vocatron).
        sidecar: File name of the lyrics file next to the audio.
        sidecar_hash: SHA-256 of that file when the stage ran.
        written_hash: SHA-256 of the file as Vocatron wrote it; ``None`` for a fan's file. A file
            that differs from it was edited, which counts as approval.
        original: The text before cleaning.
        lines: The cleaned lines.
        singers: Names and colours by singer number.
        duet: The song is flagged as a duet.
        language: ISO 639-1 code of the detected language.
        match: For a lookup, how well the record matches artist and title.
        lrc_fits: Whether a synced ``.lrc`` fits the recording; ``None`` without one.
        versions_considered: For a lookup, how many records were compared.
        versions_agreeing: For a lookup, how many agree with the chosen one.
        removed: What cleaning removed (including symbols the bundled font cannot draw).
        findings: The reasons found by the checks.
        approved: A fan approved the lyrics (by editing the file or with ``lyrics approve``).
        status: ``ok`` or ``review``; ``missing`` fails the stage instead.
    """

    SCHEMA_NAME = "lyrics"
    schema_version: Literal[2, 3, 4, 5] = (
        5  # v2 to v4 read as v5: v3 added the `glyph` removal, v4 the voice, v5 `own_mark`
    )
    source: Source
    sidecar: str
    sidecar_hash: str
    written_hash: str | None = None
    original: str
    lines: list[LyricLine]
    singers: dict[int, SingerInfo]
    duet: bool
    language: str
    match: Match | None = None
    lrc_fits: bool | None = None
    versions_considered: int = 0
    versions_agreeing: int = 0
    removed: list[Removal]
    findings: list[str]
    approved: bool
    status: Literal["ok", "review"]


def approved_copy(file: LyricsFile) -> LyricsFile:
    """Return the file as a fan's approval leaves it: no reasons, status ``ok``."""
    return file.model_copy(update={"approved": True, "reasons": [], "status": "ok"})


ENSEMBLES = {2: "Duet", 3: "Trio", 4: "Quartet", 5: "Quintet"}
"""The word for a song by this many different singers (ADR-0047)."""


def ensemble_word(lines: Sequence[LyricLine]) -> str | None:
    """Return ``Duet``, ``Trio``, ``Quartet`` or ``Quintet``, or ``None`` for fewer or more singers.

    The count is the number of different singer numbers in the lines and in the changes inside
    them. Lines of ``all`` and of a group (``1,3``) add none, so a choir does not make a trio.

    Args:
        lines: The cleaned lines of ``lyrics.json``.
    """
    marks = [line.singers for line in lines]
    marks += [turn.singers for line in lines for turn in line.turns]
    return ENSEMBLES.get(len({mark for mark in marks if is_single_singer(mark)}))
