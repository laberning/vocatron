"""The report of a song: the last step of a run, after the stages (ADR-0006).

It is not a stage in the registry: a stage is skipped when its inputs are unchanged and does not
run after a failure, while the report must describe every finished song, ``failed`` ones too. It
reads what the stage files say, combines it with the final status and the time each stage took
into ``report.json``, and keeps the report in memory when the work folder cannot be written.
"""

from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from vocatron.core.alignment.file import AlignmentFile
from vocatron.core.cdg.file import CdgFile
from vocatron.core.lyrics.file import LyricsFile
from vocatron.core.progress import PROGRESS_FILE, ProgressFile, is_fresh, progress_text
from vocatron.core.render import RenderFile
from vocatron.core.report import (
    CountdownNote,
    Findings,
    ReportFile,
    SummaryRow,
    build_report,
    report_text,
    row_not_run,
    row_of_report,
    row_of_status,
    second_voice_lines,
)
from vocatron.core.song import SongInfo
from vocatron.core.status import SongStatus
from vocatron.core.tempo import TempoFile
from vocatron.engines.protocols import FileStore
from vocatron.stages.stage import Engines, Song

REPORT_FILE = "report.json"
REPORT_TEXT = "vocatron-report.txt"  # in the output folder, overwritten by every run
STATUS_FILE = "status.json"


@dataclass(frozen=True)
class SongResult:
    """What a run made of one song.

    Attributes:
        status: The final status; ``running`` for a song that was stopped before it was done.
        report: The report, or ``None`` for a song that was stopped.
    """

    status: SongStatus
    report: ReportFile | None


def read_model[M: BaseModel](store: FileStore, path: Path, model: type[M]) -> M | None:
    """Return the JSON file at ``path`` as ``model``, or ``None`` when it does not exist.

    Raises:
        ValueError: If the file is not UTF-8 or does not validate (``ValidationError``).
    """
    text = store.read_text(path)
    return None if text is None else model.model_validate_json(text)


def _try_read[M: BaseModel](store: FileStore, path: Path, model: type[M]) -> M | None:
    """Return the file as ``model``, or ``None`` when it is missing, invalid or unreadable."""
    try:
        return read_model(store, path, model)
    except ValueError, OSError:
        return None


def findings_of(song: Song, store: FileStore) -> Findings:
    """Read what the stage files in the work folder of ``song`` say for the report."""
    folder = song.work_dir
    info = _try_read(store, folder / "song.json", SongInfo)
    lyrics = _try_read(store, folder / "lyrics.json", LyricsFile)
    alignment = _try_read(store, folder / "alignment.json", AlignmentFile)
    render = _try_read(store, folder / "render.json", RenderFile)
    tempo = _try_read(store, folder / "tempo.json", TempoFile)
    cdg = _try_read(store, folder / "cdg.json", CdgFile)
    return Findings(
        duration=info.duration if info is not None else None,
        lyrics=lyrics.status if lyrics is not None else None,
        quality=alignment.quality if alignment is not None else None,
        rails=alignment.rails.kind if alignment is not None else None,
        second_voice=tuple(second_voice_lines(lyrics, alignment))
        if lyrics is not None and alignment is not None
        else (),
        countdown=CountdownNote.of(tempo.bpm) if tempo is not None else None,
        outputs=(tuple(render.files) if render is not None else ())
        + (tuple(cdg.files) if cdg is not None else ()),
    )


def make_report(
    song: Song, status: SongStatus, ran: dict[str, float], store: FileStore
) -> ReportFile:
    """Build the report of a finished song and write ``report.json`` if the folder allows.

    A work folder that cannot be written (a full disk, no permission) does not stop the batch:
    the report is returned all the same, so the summary can name the song and the reason.

    Args:
        song: The song.
        status: Its final status.
        ran: How long each stage that ran this time took.
        store: The file store.
    """
    previous = _try_read(store, song.work_dir / REPORT_FILE, ReportFile)
    report = build_report(status, findings_of(song, store), ran, previous)
    with suppress(OSError):  # the folder is what is broken; the status and the summary say so
        store.write_text(song.work_dir / REPORT_FILE, report.model_dump_json(indent=2) + "\n")
    return report


def stored_row(song: Song, engines: Engines) -> SummaryRow:
    """Return the summary row of a song from its stored files, without running anything.

    A stored ``running`` state is a run that was interrupted, unless ``progress.json`` was
    touched a moment ago: then the song is being made right now, and the row says how far it is.
    A song with a status but no report (a run of an older version) gets a row from the status
    alone.
    """
    store = engines.store
    status = _try_read(store, song.work_dir / STATUS_FILE, SongStatus)
    if status is None:
        return row_not_run(song.name)
    if status.state == "running":
        duration = findings_of(song, store).duration
        live = _try_read(store, song.work_dir / PROGRESS_FILE, ProgressFile)
        if live is not None and is_fresh(live, engines.clock.now()):
            text = progress_text(live.stage, live.fraction, live.left)
            return SummaryRow("running", song.name, duration, None, text)
        return row_of_status(status, duration)
    report = _try_read(store, song.work_dir / REPORT_FILE, ReportFile)
    if report is None:
        return row_of_status(status, findings_of(song, store).duration)
    return row_of_report(report)


def write_report_text(
    output_dir: Path, rows: list[SummaryRow], seconds: float, now: datetime, store: FileStore
) -> None:
    """Write ``vocatron-report.txt`` into the output folder: the summary of the run and its date.

    The file is overwritten by every run. A folder that cannot be written is not worth an error:
    the same lines were printed.
    """
    text = report_text(rows, seconds, now.strftime("%Y-%m-%d %H:%M"))
    with suppress(OSError):  # the summary was printed to the console as well
        store.write_text(output_dir / REPORT_TEXT, text)
