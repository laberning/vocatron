"""Progress events of a batch, the estimate behind them, and ``progress.json`` (ADR-0006).

The batch runner tells a ``ProgressSink`` what happens: a song starts, a stage starts, a stage
moves on (from the pieces the GPU workers report and from ffmpeg), a stage finishes, a song
finishes. The ``Tracker`` is the sink the command line uses: it estimates the time left from the
learnt speeds, keeps ``progress.json`` of the running song for ``vocatron status``, learns from
every stage that ran, and hands snapshots to a ``Display`` (the console).
"""

import threading
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vocatron.core.progress import (
    PROGRESS_FILE,
    WRITE_EVERY,
    Plan,
    ProgressFile,
    Timings,
    expected,
    learn,
    percent,
    song_left,
)
from vocatron.core.report import SummaryRow, row_of_report, row_of_status
from vocatron.core.status import StageOutcome
from vocatron.engines.protocols import FileStore
from vocatron.stages.report import SongResult
from vocatron.stages.stage import Engines, Song

TIMINGS_FILE = ".cache/timings.json"  # in the clone, per machine, never in git


@dataclass(frozen=True)
class SongPlan:
    """What a batch expects of one song before it starts.

    Attributes:
        song: The song.
        length: Its length in seconds, or ``None`` when unknown.
        stages: The stages that will run (the others are skipped and count zero).
    """

    song: Song
    length: float | None
    stages: tuple[str, ...]


class ProgressSink(Protocol):
    """Hears how a batch proceeds."""

    def batch_started(self, plans: Sequence[SongPlan]) -> None:
        """The batch starts with these songs."""
        ...

    def song_started(self, index: int, song: Song) -> None:
        """Song number ``index`` (from 0) starts."""
        ...

    def stage_started(self, stage: str) -> None:
        """A stage of the current song starts."""
        ...

    def stage_progress(self, fraction: float) -> None:
        """The current stage is ``fraction`` (0 to 1) done; may be called from another thread."""
        ...

    def stage_finished(
        self, stage: str, outcome: StageOutcome, seconds: float, device: str | None
    ) -> None:
        """A stage was skipped, ran (on ``device``, if it says) or failed, after ``seconds``."""
        ...

    def song_finished(self, index: int, result: SongResult) -> None:
        """Song number ``index`` is done, or was stopped (then it has no report)."""
        ...


class NullSink:
    """A sink that ignores everything."""

    def batch_started(self, plans: Sequence[SongPlan]) -> None:
        """Ignore the start of the batch."""

    def song_started(self, index: int, song: Song) -> None:
        """Ignore the start of a song."""

    def stage_started(self, stage: str) -> None:
        """Ignore the start of a stage."""

    def stage_progress(self, fraction: float) -> None:
        """Ignore the progress."""

    def stage_finished(
        self, stage: str, outcome: StageOutcome, seconds: float, device: str | None
    ) -> None:
        """Ignore the end of a stage."""

    def song_finished(self, index: int, result: SongResult) -> None:
        """Ignore the end of a song."""


@dataclass(frozen=True)
class View:
    """A snapshot of a batch for the display.

    Attributes:
        index: The number of the current song, from 1.
        total: How many songs the batch has.
        finished: How many songs are done.
        percent: How far the batch is, in percent.
        elapsed: Seconds since the batch started.
        left: The estimated seconds the batch still needs.
        song: The name of the current song.
        stage: The stage that is running, or ``None`` between stages.
        fraction: How far that stage is (0 to 1).
        song_left: The estimated seconds the current song still needs.
    """

    index: int
    total: int
    finished: int
    percent: int
    elapsed: float
    left: float
    song: str
    stage: str | None
    fraction: float
    song_left: float


class Display(Protocol):
    """What the console shows of a batch."""

    def song_started(self, index: int, total: int, name: str) -> None:
        """Say that song number ``index`` (from 1) of ``total`` starts."""
        ...

    def update(self, view: View) -> None:
        """Show the state of the batch."""
        ...

    def stage_done(
        self, song: str, stage: str, outcome: StageOutcome, seconds: float, view: View
    ) -> None:
        """Say that a stage of ``song`` is done."""
        ...

    def song_done(self, row: SummaryRow, names: Sequence[str]) -> None:
        """Show the summary line of a finished song; ``names`` are all songs of the batch."""
        ...

    def close(self) -> None:
        """The batch is over."""
        ...


def load_timings(store: FileStore, path: Path) -> Timings:
    """Return the learnt speeds at ``path``; none when there is no valid file."""
    try:
        text = store.read_text(path)
        return Timings() if text is None else Timings.model_validate_json(text)
    except ValueError, OSError:
        return Timings()


class Tracker:
    """The sink of the command line: estimates, ``progress.json``, learning and the display."""

    def __init__(
        self, engines: Engines, display: Display, timings_path: Path | None = None
    ) -> None:
        """Estimate with the speeds learnt at ``timings_path`` (``None``: defaults, no learning)."""
        self._engines = engines
        self._display = display
        self._timings_path = timings_path
        self._timings = (
            Timings() if timings_path is None else load_timings(engines.store, timings_path)
        )
        self._lock = threading.Lock()
        self._plans: list[SongPlan] = []
        self._expected: list[Plan] = []
        self._index = 0
        self._finished_stages: list[str] = []
        self._stage: str | None = None
        self._fraction = 0.0
        self._started = 0.0
        self._written = float("-inf")
        self._done = 0
        self.rows: dict[int, SummaryRow] = {}  # the summary row of every finished song

    def _view(self) -> View:
        """Take a snapshot; the caller holds the lock."""
        now = self._engines.clock.monotonic()
        current = self._expected[self._index] if self._index < len(self._expected) else {}
        song = song_left(current, self._finished_stages, self._stage, self._fraction)
        later = sum(sum(plan.values()) for plan in self._expected[self._index + 1 :])
        left = song + later
        total = sum(sum(plan.values()) for plan in self._expected)
        name = self._plans[self._index].song.name if self._index < len(self._plans) else ""
        return View(
            index=self._index + 1,
            total=len(self._plans),
            finished=self._done,
            percent=percent(left, total, self._done, len(self._plans)),
            elapsed=now - self._started,
            left=left,
            song=name,
            stage=self._stage,
            fraction=self._fraction,
            song_left=song,
        )

    def _write_progress(self, view: View, *, force: bool) -> None:
        """Write ``progress.json`` of the current song, at most every ``WRITE_EVERY`` seconds."""
        now = self._engines.clock.monotonic()
        if self._stage is None or (not force and now - self._written < WRITE_EVERY):
            return
        self._written = now
        file = ProgressFile(
            stage=self._stage,
            fraction=min(max(self._fraction, 0.0), 1.0),
            left=view.song_left,
            updated=self._engines.clock.now().isoformat(timespec="seconds"),
        )
        path = self._plans[self._index].song.work_dir / PROGRESS_FILE
        with suppress(OSError):  # the display has the progress; only `vocatron status` misses it
            self._engines.store.write_text(path, file.model_dump_json(indent=2) + "\n")

    def batch_started(self, plans: Sequence[SongPlan]) -> None:
        """Estimate every song from the learnt speeds and start the clock."""
        with self._lock:
            self._plans = list(plans)
            self._expected = [expected(plan.stages, plan.length, self._timings) for plan in plans]
            self._started = self._engines.clock.monotonic()
            self._done = 0

    def song_started(self, index: int, song: Song) -> None:
        """Start the current song with nothing finished."""
        with self._lock:
            self._index = index
            self._finished_stages = []
            self._stage, self._fraction = None, 0.0
            self._display.song_started(index + 1, len(self._plans), song.name)
            self._display.update(self._view())

    def stage_started(self, stage: str) -> None:
        """Start a stage at zero."""
        with self._lock:
            self._stage, self._fraction = stage, 0.0
            view = self._view()
            self._write_progress(view, force=True)
            self._display.update(view)

    def stage_progress(self, fraction: float) -> None:
        """Move the current stage on."""
        with self._lock:
            self._fraction = fraction
            view = self._view()
            self._write_progress(view, force=False)
            self._display.update(view)

    def stage_finished(
        self, stage: str, outcome: StageOutcome, seconds: float, device: str | None
    ) -> None:
        """Count the stage as done and learn its speed when it ran."""
        with self._lock:
            plan = self._plans[self._index]
            if outcome.action == "ran" and plan.length:
                self._timings = learn(self._timings, stage, device or "cpu", seconds, plan.length)
            self._finished_stages.append(stage)
            self._stage, self._fraction = None, 0.0
            self._display.stage_done(plan.song.name, stage, outcome, seconds, self._view())

    def song_finished(self, index: int, result: SongResult) -> None:
        """Show the summary line, remove ``progress.json`` and keep what was learnt."""
        with self._lock:
            song = self._plans[index].song
            self._done += 1
            with suppress(OSError):  # a file nobody reads once the song is done
                self._engines.store.delete(song.work_dir / PROGRESS_FILE)
            report = result.report
            duration = self._plans[index].length
            row = (
                row_of_report(report)
                if report is not None
                else row_of_status(result.status, duration)
            )
            self.rows[index] = row
            self._display.song_done(row, [plan.song.name for plan in self._plans])
            self._save()
            self._display.update(self._view())

    def _save(self) -> None:
        """Write the learnt speeds; a file that cannot be written is only a missed lesson."""
        if self._timings_path is None:
            return
        with suppress(OSError):  # the next run learns again
            self._engines.store.write_text(
                self._timings_path, self._timings.model_dump_json(indent=2) + "\n"
            )

    def close(self) -> None:
        """The batch is over: a stage cut short loses its ``progress.json``, the display lets go.

        A song that was stopped in the middle of a stage (the second Ctrl-C) must not look as
        if it were still being made.
        """
        with self._lock:
            if self._stage is not None and self._index < len(self._plans):
                with suppress(OSError):  # a file nobody should read any more
                    path = self._plans[self._index].song.work_dir / PROGRESS_FILE
                    self._engines.store.delete(path)
            self._display.close()
