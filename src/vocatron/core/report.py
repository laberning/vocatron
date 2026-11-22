"""The report of a song and the summary lines of a batch (ADR-0006).

``report.json`` combines what every stage found into one verdict per song: ``ok``, ``review``
with reasons, or ``failed`` with the error, next to the quality numbers, the time each stage took
and the files that were made. The summary of a batch has one line per song and a total line;
``vocatron make`` prints it, ``vocatron status`` prints the same from the stored reports. All of
it is pure: reading the stage files and writing the report are the stages' business.
"""

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from vocatron.core.alignment.file import AlignmentFile, QualityReport
from vocatron.core.lyrics.document import SECOND_VOICE
from vocatron.core.lyrics.file import LyricsFile
from vocatron.core.lyrics.voices import source_of
from vocatron.core.progress import format_duration, format_length
from vocatron.core.status import ErrorInfo, SongStatus, State, exit_code

Verdict = Literal["ok", "review", "failed"]
SummaryState = Literal["ok", "review", "failed", "running", "interrupted", "not run"]
SUMMARY_STATES: tuple[Verdict, ...] = ("ok", "review", "failed")  # always counted in the total
STATE_WIDTH = 8
LENGTH_WIDTH = 5
TIME_WIDTH = 7
PREFIX_WIDTH = STATE_WIDTH + 1 + LENGTH_WIDTH + 2 + TIME_WIDTH + 2
"""The columns before the name: state, length and processing time with their gaps."""
NAME_SHARE = 0.5
"""The share of the terminal width the name column may take at most."""
ELLIPSIS = "…"
MAX_ARTISTS = 2
"""With more artists than this, a name shows the first one and how many more there are."""
FEATURING = re.compile(r"\s*[(\[]?\s*\b(?:feat|ft)\.\s[^)\]]*[)\]]?", re.IGNORECASE)


class CountdownNote(BaseModel):
    """What the countdowns of a song counted (ADR-0022): a note, not a reason for review.

    Attributes:
        tempo: The tempo in beats per minute, or ``None`` when it was unclear.
        unit: ``beats`` when the countdowns counted beats of the tempo, ``seconds`` when they ran
            over a fixed number of seconds.
    """

    model_config = ConfigDict(extra="forbid")

    tempo: float | None
    unit: Literal["beats", "seconds"]

    @classmethod
    def of(cls, tempo: float | None) -> CountdownNote:
        """Return the note for a song with the tempo ``tempo`` (``None``: unclear)."""
        return cls(tempo=tempo, unit="seconds" if tempo is None else "beats")


class SecondVoiceLine(BaseModel):
    """A line the second voice sings and where that came from (ADR-0052).

    Attributes:
        line: The number of the line in the lyrics (from 1).
        source: ``mark`` (``{&}`` in the lyrics file), ``time`` (the same ``.lrc`` time as the line
            before) or ``audio`` (the backing hears it and the first voice is busy).
    """

    model_config = ConfigDict(extra="forbid")

    line: int
    source: Literal["mark", "time", "audio"]


def second_voice_lines(lyrics: LyricsFile, alignment: AlignmentFile) -> list[SecondVoiceLine]:
    """Name the lines the second voice sings in the alignment and where each one came from.

    The lines of the lyrics file keep their source (``source_of``); the other lines of the second
    voice were found in the audio.

    Args:
        lyrics: ``lyrics.json``.
        alignment: ``alignment.json``.
    """
    from_file = source_of(
        [line.time for line in lyrics.lines], [line.voice for line in lyrics.lines]
    )
    return [
        SecondVoiceLine(line=index + 1, source=from_file.get(index, "audio"))
        for index, line in enumerate(alignment.lines)
        if line.voice == SECOND_VOICE
    ]


class ReportFile(BaseModel):
    """``report.json``: the verdict on one song.

    Attributes:
        schema_version: Version of this file's schema.
        name: The safe name of the song (track and work folder).
        source: File name of the audio file.
        status: ``ok``, ``review`` or ``failed``.
        reasons: Why the song needs review, each prefixed with its stage.
        error: The error when the status is ``failed``.
        duration: The length of the song in seconds, or ``None`` when unknown.
        seconds: The processing time of the song: the sum of ``stage_seconds``.
        stage_seconds: How long each stage took when it last ran.
        lyrics: The status of the lyrics (``ok``, ``review``, ...), when there are lyrics.
        quality: The quality numbers of the alignment, when it ran.
        rails: How the line times of an ``.lrc`` were used (``used``, ``ignored``, ...).
        second_voice: The lines a second voice sings at once with the first and where each came
            from (ADR-0052); empty for a song with one voice.
        countdown: The tempo and whether the countdowns counted beats or seconds, when the tempo
            stage ran.
        outputs: The files made in the output folder (the MP4 first).
        updated: When the file was written (ISO 8601, from the injected clock).
    """

    SCHEMA_NAME: ClassVar[str] = "report"
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3] = 3
    name: str
    source: str
    status: Verdict
    reasons: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None
    duration: float | None = None
    seconds: float = 0.0
    stage_seconds: dict[str, float] = Field(default_factory=dict)
    lyrics: str | None = None
    quality: QualityReport | None = None
    rails: str | None = None
    second_voice: list[SecondVoiceLine] = Field(default_factory=list)
    countdown: CountdownNote | None = None
    outputs: list[str] = Field(default_factory=list)
    updated: str


@dataclass(frozen=True)
class Findings:
    """What the stage files say about a song, for the report.

    Attributes:
        duration: The length of the song in seconds, or ``None``.
        lyrics: The status of the lyrics, if known.
        quality: The quality numbers of the alignment, if it ran.
        rails: How the guide rails were used, if the alignment ran.
        second_voice: The lines of the second voice and their sources, if the alignment ran.
        countdown: The tempo and the unit of the countdowns, if the tempo stage ran.
        outputs: The files the render stage made.
    """

    duration: float | None = None
    lyrics: str | None = None
    quality: QualityReport | None = None
    rails: str | None = None
    second_voice: tuple[SecondVoiceLine, ...] = ()
    countdown: CountdownNote | None = None
    outputs: tuple[str, ...] = ()


def build_report(
    status: SongStatus,
    findings: Findings,
    ran: Mapping[str, float],
    previous: ReportFile | None,
) -> ReportFile:
    """Combine the status of a finished song with what the stage files say.

    Args:
        status: The final status of the song (not ``running``).
        findings: What the stage files say.
        ran: How long each stage that ran this time took, in seconds.
        previous: The report of the earlier run, whose times stay for the stages that were
            skipped this time, so the processing time is that of making the whole song.

    Raises:
        ValueError: If the song is still ``running``: an interrupted song has no report.
    """
    if status.state == "running":
        raise ValueError("a song that is still running has no report")
    times = {**(previous.stage_seconds if previous is not None else {}), **ran}
    failed = status.state == "failed"
    return ReportFile(
        name=status.name,
        source=status.source,
        status=status.state,
        reasons=status.reasons,
        error=status.error,
        duration=findings.duration,
        seconds=round(sum(times.values()), 2),
        stage_seconds={stage: round(seconds, 2) for stage, seconds in times.items()},
        lyrics=findings.lyrics,
        quality=findings.quality,
        rails=findings.rails,
        second_voice=list(findings.second_voice),
        countdown=findings.countdown,
        outputs=[] if failed else list(findings.outputs),
        updated=status.updated,
    )


@dataclass(frozen=True)
class SummaryRow:
    """One line of the summary.

    Attributes:
        state: The state shown first. ``interrupted`` is shown as ``running`` (the stored status
            of a run that stopped in a stage), ``running`` is a song being made right now.
        name: The name of the song.
        length: The length of the song in seconds, or ``None``.
        seconds: The processing time, or ``None``.
        detail: The reasons for a ``review`` song, the error for a failed one, where an
            interrupted song stopped or how far a running song is; empty for an ``ok`` song.
    """

    state: SummaryState
    name: str
    length: float | None = None
    seconds: float | None = None
    detail: str = ""


def row_of_report(report: ReportFile) -> SummaryRow:
    """Return the summary row of a finished song."""
    if report.status == "review":
        detail = f"({'; '.join(report.reasons)})"
    elif report.status == "failed":
        error = report.error
        detail = "" if error is None else f"{error.stage}: {error.message}"
    else:
        detail = ""  # the track is named like the song: repeating it says nothing
    return SummaryRow(report.status, report.name, report.duration, report.seconds, detail)


def row_of_status(status: SongStatus, duration: float | None = None) -> SummaryRow:
    """Return the summary row of a song that has no report: it stopped, or never got one.

    A song whose stored state is ``running`` was interrupted in the stage ``current``.
    """
    if status.state == "running":
        return SummaryRow(
            "interrupted", status.name, duration, None, f"interrupted in {status.current}"
        )
    state: Verdict = status.state
    detail = f"({'; '.join(status.reasons)})" if state == "review" else ""
    if state == "failed" and status.error is not None:
        detail = f"{status.error.stage}: {status.error.message}"
    return SummaryRow(state, status.name, duration, None, detail)


def row_not_run(name: str) -> SummaryRow:
    """Return the row of a song that was never run."""
    return SummaryRow("not run", name)


def short_name(name: str) -> str:
    """Shorten a song name for a summary line; the files keep the full name.

    ``Artist 1, Artist 2, Artist 3 - Title (feat. Artist 2)`` becomes ``Artist 1 +2 - Title``:
    with more than ``MAX_ARTISTS`` artists only the first is named, and a featuring part of the
    title goes, since those artists are named before the dash anyway.
    """
    artists, dash, title = name.partition(" - ")
    if not dash:
        return name
    title = FEATURING.sub("", title).strip() or title
    names = artists.split(", ")
    if len(names) > MAX_ARTISTS:
        artists = f"{names[0]} +{len(names) - 1}"
    return f"{artists} - {title}"


def char_columns(char: str) -> int:
    """Return how many terminal columns one character takes: 2 wide, 0 combining, else 1."""
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1


def columns(text: str) -> int:
    """Return how many terminal columns ``text`` takes (wide characters such as CJK count 2)."""
    return sum(char_columns(char) for char in text)


def clip(text: str, width: int) -> str:
    """Cut ``text`` to ``width`` columns, ending with ``…`` when something was cut."""
    if columns(text) <= width:
        return text
    if width <= 0:
        return ""
    kept: list[str] = []
    used = 0
    for char in text:
        size = char_columns(char)
        if used + size > width - 1:  # leave a column for the ellipsis
            break
        kept.append(char)
        used += size
    return "".join(kept) + ELLIPSIS


def pad(text: str, width: int) -> str:
    """Fill ``text`` with spaces to ``width`` columns."""
    return text + " " * max(width - columns(text), 0)


def name_width(names: Sequence[str], width: int | None = None) -> int:
    """Return the width of the name column: the longest short name, capped on a terminal.

    Args:
        names: The full names of the songs.
        width: The width of the terminal; ``None`` for a file, which has no limit.
    """
    longest = max((columns(short_name(name)) for name in names), default=0)
    if width is None:
        return longest
    return min(longest, int(width * NAME_SHARE), max(width - PREFIX_WIDTH, 0))


def format_row(row: SummaryRow, names: int, width: int | None = None) -> str:
    """Format one row: state, length, processing time, name and detail, in columns.

    Args:
        row: The song.
        names: The width of the name column in terminal columns; longer names are cut with ``…``.
        width: The width of the terminal; the detail is cut to fit it. ``None`` (a file) keeps
            the whole detail.
    """
    shown = "running" if row.state == "interrupted" else row.state
    seconds = "-" if row.seconds is None else format_duration(row.seconds)
    length = format_length(row.length)
    prefix = f"{shown:<{STATE_WIDTH}} {length:>{LENGTH_WIDTH}}  {seconds:>{TIME_WIDTH}}  "
    line = f"{prefix}{pad(clip(short_name(row.name), names), names)}  {row.detail}".rstrip()
    return line if width is None else clip(line, width)


def format_rows(rows: Sequence[SummaryRow], width: int | None = None) -> list[str]:
    """Format the rows with one name column for all (see ``name_width``)."""
    names = name_width([row.name for row in rows], width)
    return [format_row(row, names, width) for row in rows]


def total_line(rows: Sequence[SummaryRow], seconds: float | None) -> str:
    """Format the count of songs per state and the time all of it took.

    Interrupted, running and not-run songs are named only when there are any.

    Args:
        rows: One row per song.
        seconds: The time the batch took, or the processing time of its songs; ``None`` leaves
            it out.
    """
    parts = [f"{sum(1 for row in rows if row.state == state)} {state}" for state in SUMMARY_STATES]
    for state in ("running", "interrupted", "not run"):
        count = sum(1 for row in rows if row.state == state)
        if count:
            parts.append(f"{count} {state}")
    noun = "song" if len(rows) == 1 else "songs"
    took = "" if seconds is None else f" in {format_duration(seconds)}"
    return f"{len(rows)} {noun}: {', '.join(parts)}{took}"


def exit_code_of(rows: Sequence[SummaryRow]) -> int:
    """Return the exit code of a batch: 1 if any song failed or was interrupted, else 0.

    A song that was never run does not count.
    """
    states: list[State] = [
        "running" if row.state in {"interrupted", "running"} else row.state
        for row in rows
        if row.state != "not run"
    ]
    return exit_code(states)


def report_text(rows: Sequence[SummaryRow], seconds: float, date: str) -> str:
    """Return the text of ``vocatron-report.txt``: the date, the lines of the songs, the total."""
    lines = [f"Vocatron report, {date}", "", *format_rows(rows), "", total_line(rows, seconds)]
    return "\n".join(lines) + "\n"
