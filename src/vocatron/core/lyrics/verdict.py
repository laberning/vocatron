"""The status rules of the lyrics: ``ok``, ``review`` with reasons, or ``missing`` (ADR-0006).

``decide`` is the table of the rules; ``approval`` is the rule for what a fan's edit means.
"""

import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from vocatron.core.glyphs import describe
from vocatron.core.lyrics.clean import Removal
from vocatron.core.lyrics.match import Match
from vocatron.core.lyrics.versions import LENGTH_TOLERANCE

Status = Literal["ok", "review", "missing"]
Source = Literal["sidecar", "lookup"]

MIN_AGREEING = 2  # versions of the found lyrics that must agree to be trusted

UNSURE_MATCH = "unsure match: artist or title are not exactly those of the song"
SINGLE_SOURCE = "single source: no second version of the lyrics agrees"
SECTION_MARKERS = "section markers removed"
REPEAT_MARKERS = "repeat markers removed"
CREDITS = "credits removed"
LRC_MISMATCH = "the .lrc does not fit the recording"
DUET_WITHOUT_MARKS = "duet without singer marks"
UNKNOWN_LOOKUP = "found online by an earlier run whose checks are not known here"
REMOVAL_REASONS = {"section": SECTION_MARKERS, "repeat": REPEAT_MARKERS, "credit": CREDITS}


class Facts(BaseModel):
    """What is known about a set of lyrics when its status is decided.

    Attributes:
        source: ``sidecar`` (a file of the fan, trusted) or ``lookup`` (found online).
        lines: How many lines of lyrics are left after cleaning.
        match: For a lookup, how well the record matches artist and title; ``None`` for a file
            Vocatron wrote in a run this work folder does not remember.
        agreeing: For a lookup, how many versions agree with the chosen one.
        removals: What cleaning removed.
        lrc_fits: Whether a synced ``.lrc`` fits the recording; ``None`` without one.
        duet: The song is flagged as a duet.
        marked: Some line carries a singer mark.
    """

    model_config = ConfigDict(frozen=True)

    source: Source
    lines: int
    match: Match | None = None
    agreeing: int = 0
    removals: tuple[Removal, ...] = ()
    lrc_fits: bool | None = None
    duet: bool = False
    marked: bool = False


class Verdict(BaseModel):
    """The status of the lyrics and why.

    Attributes:
        status: ``ok``, ``review`` or ``missing``.
        reasons: The reasons for ``review``; empty otherwise.
    """

    model_config = ConfigDict(frozen=True)

    status: Status
    reasons: tuple[str, ...] = ()


class Previous(BaseModel):
    """What the stage file of an earlier run remembers about the sidecar.

    Attributes:
        sidecar_hash: SHA-256 of the sidecar when that run ended.
        written_hash: SHA-256 of the sidecar as Vocatron wrote it, or ``None`` for a fan's file.
        approved: Whether the lyrics were approved.
    """

    model_config = ConfigDict(frozen=True)

    sidecar_hash: str
    written_hash: str | None
    approved: bool


class Approval(BaseModel):
    """What a sidecar means for approval.

    Attributes:
        approved: The lyrics count as approved.
        keep_findings: The sidecar is exactly what Vocatron wrote, so the findings of the lookup
            (which cannot be recomputed from the file) stay.
    """

    model_config = ConfigDict(frozen=True)

    approved: bool
    keep_findings: bool


def glyph_reasons(removals: Sequence[Removal]) -> list[str]:
    """Say which symbols cleaning dropped from which lines, for the review reasons (ADR-0046).

    One reason for each symbol, in order of its first line, with all its lines
    (``lines 3, 7: dropped U+2665 BLACK HEART SUIT (not in the font)``), so that a symbol that
    decorates many lines gives one reason, not one for every line.
    """
    lines: dict[int, list[int]] = {}
    for removal in removals:
        if removal.kind == "glyph" and removal.character is not None:
            lines.setdefault(removal.character, []).append(removal.line)
    return [
        f"{'line' if len(rows) == 1 else 'lines'} {', '.join(map(str, rows))}: "
        f"dropped {describe(code)} (not in the font)"
        for code, rows in lines.items()
    ]


def decide(facts: Facts) -> Verdict:
    """Decide the status of lyrics from the facts.

    ``missing`` without lines. Found lyrics are ``ok`` only when at least two versions agree and
    artist and title match exactly; found lyrics whose lookup is not known any more (``match``
    is ``None``) need review for that alone; a fan's own sidecar is trusted. Cleaning, a ``.lrc``
    that does not fit and a duet without singer marks give ``review`` in both cases.
    """
    if facts.lines == 0:
        return Verdict(status="missing")
    reasons: list[str] = []
    if facts.source == "lookup" and facts.match is None:
        reasons.append(UNKNOWN_LOOKUP)
    elif facts.source == "lookup":
        if facts.match != "exact":
            reasons.append(UNSURE_MATCH)
        if facts.agreeing < MIN_AGREEING:
            reasons.append(SINGLE_SOURCE)
    reasons += glyph_reasons(facts.removals)
    for kind in ("section", "repeat", "credit"):
        count = sum(1 for removal in facts.removals if removal.kind == kind)
        if count:
            reasons.append(f"{REMOVAL_REASONS[kind]} ({count} {'line' if count == 1 else 'lines'})")
    if facts.lrc_fits is False:
        reasons.append(LRC_MISMATCH)
    if facts.duet and not facts.marked:
        reasons.append(DUET_WITHOUT_MARKS)
    return Verdict(status="review" if reasons else "ok", reasons=tuple(reasons))


def approval(sidecar_hash: str, previous: Previous | None) -> Approval:
    """Decide whether the sidecar counts as approved.

    A sidecar that differs from what Vocatron remembers was edited by the fan, which counts as
    approval. An unchanged one keeps the approval it had; the first run approves nothing.

    Args:
        sidecar_hash: SHA-256 of the sidecar now.
        previous: What the earlier run remembers; ``None`` at the first run.
    """
    if previous is None:
        return Approval(approved=False, keep_findings=False)
    if sidecar_hash != previous.sidecar_hash:
        return Approval(approved=True, keep_findings=False)
    return Approval(approved=previous.approved, keep_findings=sidecar_hash == previous.written_hash)


def lrc_fits(
    last_time: float | None, length: float | None, song_duration: float | None
) -> bool | None:
    """Check a synced ``.lrc`` against the recording: its length, and its last line.

    Args:
        last_time: The time of the last line, if the file has line times.
        length: The ``[length:]`` tag, if the file has one.
        song_duration: The length of the song.

    Returns:
        ``False`` when the tag differs from the song by more than 2 s or a line starts after the
        end of the song; ``True`` when something could be checked and fits; ``None`` otherwise.
    """
    if song_duration is None:
        return None
    checks = []
    if length is not None:
        checks.append(abs(length - song_duration) <= LENGTH_TOLERANCE)
    if last_time is not None:
        checks.append(last_time <= song_duration + LENGTH_TOLERANCE)
    return all(checks) if checks else None


def is_duet(pattern: str, *texts: str) -> bool:
    """Tell whether a song is a duet.

    Args:
        pattern: A regular expression, matched in any case.
        texts: Where to look: the file name and the title tag.
    """
    expression = re.compile(pattern, re.IGNORECASE)
    return any(expression.search(text) for text in texts)
