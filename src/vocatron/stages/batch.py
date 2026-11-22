"""The batch runner: songs through the stages, one song at a time (ADR-0006).

Per song and stage it computes the fingerprint, skips or runs, and writes ``status.json`` before
every stage (state ``running``) and after the last one or a failure. A failing stage fails its
song, a song that outlasts its safety limit is stopped, and a work folder that cannot be written
fails its song as well; the batch continues with the next one in every case. A stop request
(the first Ctrl-C) is honoured between stages: the song stays ``running`` in the stage that would
have come next, which ``vocatron status`` shows as interrupted. After the last stage the report
of the song is made (``stages.report``).
"""

import traceback
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from vocatron.core.errors import StageError
from vocatron.core.progress import format_duration
from vocatron.core.stage_file import Fingerprint, StageFile, is_current, make_fingerprint
from vocatron.core.status import (
    ErrorInfo,
    SongStatus,
    StageOutcome,
    combine,
    untouched_results,
)
from vocatron.engines.protocols import FileStore, LogSink, Watch
from vocatron.stages.config import Config
from vocatron.stages.models import LogListener, ModelFolder, ensure_models
from vocatron.stages.progress import NullSink, ProgressSink, SongPlan
from vocatron.stages.registry import STAGES
from vocatron.stages.report import STATUS_FILE, SongResult, make_report, read_model
from vocatron.stages.stage import (
    AUDIO,
    LOG_FILE,
    Engines,
    LogLine,
    Song,
    Stage,
    StageContext,
    declared_outputs,
    missing_outputs,
)

DISK_ERROR = "disk-error"
TIME_LIMIT = "time-limit"


class StopFlag:
    """Asks the batch to stop after the stage that is running (the first Ctrl-C)."""

    def __init__(self) -> None:
        """Start without a request."""
        self.requested = False

    def request(self) -> None:
        """Ask for a stop."""
        self.requested = True


@dataclass(frozen=True)
class Hooks:
    """How a batch talks to the outside world while it runs.

    Attributes:
        sink: Hears the progress.
        stop: Asked between stages whether to stop.
        echo: Gets every line of the song log file as it is written, by the batch or by a GPU
            worker, with the name of the song in front (``--log``); or ``None``.
    """

    sink: ProgressSink = field(default_factory=NullSink)
    stop: StopFlag = field(default_factory=StopFlag)
    echo: Callable[[str], None] | None = None


def _load_output(stage: Stage, ctx: StageContext) -> StageFile | None:
    """Return the stored, valid output of ``stage``, or ``None`` if missing or invalid."""
    try:
        return read_model(ctx.engines.store, ctx.song.work_dir / stage.output, stage.output_model)
    except ValueError:
        ctx.log(f"{stage.name}: stored {stage.output} is invalid")
        return None


def _input_hashes(stage: Stage, ctx: StageContext, config: Config) -> dict[str, str]:
    """Hash every input of ``stage``.

    Raises:
        StageError: If an input file is missing.
    """
    hashes: dict[str, str] = {}
    for name in stage.inputs:
        path = ctx.song.source if name == AUDIO else ctx.song.work_dir / name
        digest = ctx.engines.store.sha256(path)
        if digest is None:
            hint = "" if name == AUDIO else "; run `vocatron make` for this song first"
            raise StageError("missing-input", f"input {name} not found at {path}{hint}")
        hashes[name] = digest
    return hashes | stage.external_inputs(ctx, config)


def _device_of(output: StageFile) -> str | None:
    """Return the device a stage ran on, when its stage file says (the GPU stages do)."""
    device = getattr(output, "device", None)  # only the separation and alignment files have one
    return device if isinstance(device, str) else None


def _handle_stage(
    stage: Stage, ctx: StageContext, config: Config, *, force: bool, offline: bool
) -> tuple[StageOutcome, str | None]:
    """Skip or run one stage, and write its stage file when it ran.

    The models the stage declares are fetched just before it runs (not when it is skipped).

    Returns:
        What happened, and the device the stage ran on if its stage file says.
    """
    fingerprint = _fingerprint(stage, ctx, config)
    stored = _current_output(stage, ctx, fingerprint, force=force)
    if stored is not None:
        ctx.log(f"{stage.name}: skipped, output is current")
        return StageOutcome(stage=stage.name, action="skipped", reasons=stored.reasons), None
    ensure_models(
        stage.required_models(ctx, config),
        folder=ModelFolder(ctx.models_dir, ctx.engines.store),
        downloader=ctx.engines.downloader,
        offline=offline,
        listener=LogListener(ctx.log),
    )
    ctx.log(f"{stage.name}: running")
    output = stage.execute(ctx, config, fingerprint)
    ctx.engines.store.write_text(
        ctx.song.work_dir / stage.output, output.model_dump_json(indent=2) + "\n"
    )
    ctx.log(f"{stage.name}: done")
    outcome = StageOutcome(stage=stage.name, action="ran", reasons=output.reasons)
    return outcome, _device_of(output)


def _fingerprint(stage: Stage, ctx: StageContext, config: Config) -> Fingerprint:
    """Return the fingerprint of ``stage``'s inputs and settings as they are now.

    Raises:
        StageError: If an input file is missing.
    """
    return make_fingerprint(
        _input_hashes(stage, ctx, config), stage.declared_settings(ctx, config), stage.version
    )


def _current_output(
    stage: Stage, ctx: StageContext, fingerprint: Fingerprint, *, force: bool
) -> StageFile | None:
    """Return ``stage``'s stored output if it is current, else ``None``: the one skip rule.

    Current means: valid, all outputs there, its fingerprint equals ``fingerprint`` and the run
    is not forced.
    """
    stored = _load_output(stage, ctx)
    if stored is not None and (missing := missing_outputs(stage, ctx, stored)):
        ctx.log(f"{stage.name}: {', '.join(missing)} missing")
        return None
    if stored is not None and is_current(stored.fingerprint, fingerprint, force=force):
        return stored
    return None


def _current_reasons(stage: Stage, ctx: StageContext, config: Config) -> list[str] | None:
    """Return the review reasons of ``stage``'s stored output if it is current now, else ``None``.

    A partial run uses this for the stages it leaves alone.
    """
    try:
        stored = _current_output(stage, ctx, _fingerprint(stage, ctx, config), force=False)
    except StageError:
        return None
    return stored.reasons if stored is not None else None


def _still_current(
    ctx: StageContext, config: Config, names: list[str]
) -> dict[str, list[str] | None]:
    """Judge the stages ``names`` after a partial run: the review reasons of those still current.

    A stage whose file is not current makes the files it writes stale, so a stage that reads one
    of them is not current either, even if its own file matches the stale input.
    """
    stale: set[str] = set()
    judged: dict[str, list[str] | None] = {}
    for stage in STAGES:
        if stage.name not in names:
            continue
        reasons = None if stale & set(stage.inputs) else _current_reasons(stage, ctx, config)
        judged[stage.name] = reasons
        if reasons is None:
            stale.update(declared_outputs(stage))
    return judged


def _status_of(
    song: Song,
    engines: Engines,
    outcomes: Sequence[StageOutcome],
    error: ErrorInfo | None,
    current: str | None = None,
) -> SongStatus:
    """Combine the outcomes so far into the status; ``current`` is the stage to run."""
    state, reasons = combine(outcomes, error, current)
    return SongStatus(
        name=song.name,
        source=song.source.name,
        state=state,
        current=current if state == "running" else None,
        reasons=reasons,
        error=error,
        stages=list(outcomes),
        updated=engines.clock.now().isoformat(timespec="seconds"),
    )


def _write_status(
    song: Song,
    engines: Engines,
    outcomes: Sequence[StageOutcome],
    error: ErrorInfo | None,
    current: str | None = None,
) -> SongStatus:
    """Combine the outcomes so far and write ``status.json``.

    Raises:
        OSError: If the work folder cannot be written.
    """
    status = _status_of(song, engines, outcomes, error, current)
    engines.store.write_text(song.work_dir / STATUS_FILE, status.model_dump_json(indent=2) + "\n")
    return status


def _failure(stage: Stage, ctx: StageContext, error: Exception) -> ErrorInfo:
    """Describe a stage error; an unexpected one gets its traceback in the song log."""
    if isinstance(error, StageError):
        kind = error.kind
    else:
        is_file_error = isinstance(error, OSError) and not isinstance(
            error, TimeoutError | ConnectionError
        )
        kind = DISK_ERROR if is_file_error else type(error).__name__
        for line in traceback.format_exception(error):
            ctx.log(line.rstrip())
    ctx.log(f"{stage.name}: failed: {kind}: {error}")
    return ErrorInfo(stage=stage.name, kind=kind, message=_message(error))


def _message(error: Exception) -> str:
    """Return what to tell about an error; a file error names the reason and the file."""
    if isinstance(error, OSError) and error.strerror:
        where = f": {error.filename}" if error.filename else ""
        return f"{error.strerror}{where}"
    return str(error)


@dataclass(frozen=True)
class Options:
    """How a batch runs.

    Attributes:
        force: Run every stage again, even if its output is current.
        offline: A stage whose models are missing fails instead of downloading them.
        until: End each song after the stage of that name.
        only: Run only the stages of these names.
    """

    force: bool = False
    offline: bool = False
    until: str | None = None
    only: tuple[str, ...] | None = None


def time_limit(config: Config, length: float | None) -> float | None:
    """Return the safety limit of a song in seconds: its length times a factor plus a base.

    ``None`` when the length is not known: there is nothing to scale.
    """
    if length is None:
        return None
    return config.batch.time_limit_factor * length + config.batch.time_limit_base


def _selected(options: Options) -> list[Stage]:
    """Return the stages a run with ``options`` handles, in order."""
    names = [stage.name for stage in STAGES]
    if options.only is not None:
        return [stage for stage in STAGES if stage.name in options.only]
    end = len(STAGES) if options.until is None else names.index(options.until) + 1
    return list(STAGES[:end])


def plan_song(song: Song, config: Config, engines: Engines, options: Options) -> SongPlan:
    """Return which stages will run for ``song``: those whose stored result is not current.

    A stage whose input another stage of the song is about to make again counts as running too.
    Only the estimate of the time left depends on this.
    """
    names = [stage.name for stage in _selected(options)]
    length = song.tags.duration if song.tags is not None else None
    if options.force:
        return SongPlan(song, length, tuple(names))
    ctx = StageContext(song, engines, _silent, Path(config.models.folder))
    try:
        judged = _still_current(ctx, config, names)
    except OSError:  # a file that cannot be read now: expect the whole song to run
        return SongPlan(song, length, tuple(names))
    return SongPlan(song, length, tuple(name for name in names if judged[name] is None))


def _silent(message: str) -> None:
    """Drop a log line."""
    del message


class _Log:
    """The song log: a file that is synced after every line, and optionally followed.

    With an echo (``--log``) the whole file is followed while the song runs: the lines written
    here and those the GPU workers write themselves reach the echo once each, in the order of
    the file, with the name of the song in front.

    A log that cannot be written must not fail the song or hide the real error, so a line that
    cannot be written is dropped; the status says what is wrong with the folder.
    """

    def __init__(self, song: Song, engines: Engines, echo: Callable[[str], None] | None) -> None:
        self._song = song
        self._engines = engines
        self._echo = echo
        self._sink: LogSink | None = None

    def _follow(self, line: str) -> None:
        """Hand a line of the log file to the echo, with the name of the song."""
        if self._echo is not None:
            self._echo(f"{self._song.name}: {line}")

    def open(self) -> None:
        """Open the log file; the work folder is made first.

        Raises:
            OSError: If the work folder cannot be written.
        """
        self._engines.store.make_folder(self._song.work_dir)
        follow = None if self._echo is None else self._follow
        self._sink = self._engines.store.open_log(self._song.work_dir / LOG_FILE, follow)

    def __call__(self, message: str) -> None:
        """Write one line with the time (the follower echoes it from the file)."""
        if self._sink is not None:
            stamp = self._engines.clock.now().isoformat(timespec="seconds")
            with suppress(OSError):  # see the class docstring
                self._sink.write(f"{stamp} {message}")

    def close(self) -> None:
        """Close the log file."""
        if self._sink is not None:
            with suppress(OSError):  # see the class docstring
                self._sink.close()


@dataclass
class _SongRun:
    """One song while it runs: what it was given, and what the failure paths need to describe it.

    Attributes:
        song: The song.
        config: The configuration.
        engines: The engines.
        options: How the batch runs.
        hooks: How the batch talks to the outside world.
        log: The song log.
        outcomes: What happened to the stages so far.
        error: The error of the failed stage, if one failed.
        current: The stage about to run or running.
        seconds: How long each stage that ran took.
    """

    song: Song
    config: Config
    engines: Engines
    options: Options
    hooks: Hooks
    log: _Log
    outcomes: list[StageOutcome] = field(default_factory=list)
    error: ErrorInfo | None = None
    current: str | None = None
    seconds: dict[str, float] = field(default_factory=dict)


def make_song(
    song: Song, config: Config, engines: Engines, options: Options, hooks: Hooks | None = None
) -> SongResult:
    """Run one song through the stages and return its status and report.

    With ``options.offline`` a stage whose models are missing fails instead of downloading them.
    With ``until`` the run ends after the stage of that name; with ``only`` just the stages of
    those names run. The final status keeps what ``status.json`` recorded for the stages that did
    not run and replaces only the results of this run.

    A song that stops because ``hooks.stop`` asked for it keeps the state ``running`` in the stage
    that would have come next and has no report.

    Never raises for a failing stage, a song that outlasts its safety limit or a work folder that
    cannot be written: all of these become the status of the song.
    """
    hooks = hooks or Hooks()
    run = _SongRun(song, config, engines, options, hooks, _Log(song, engines, hooks.echo))
    try:
        run.log.open()
        return _run_stages(run)
    except OSError as caught:  # the work folder cannot be written: failed, in memory only
        return _unwritable(run, caught)
    finally:
        run.log.close()


def _unwritable(run: _SongRun, caught: OSError) -> SongResult:
    """Return the result of a song whose work folder cannot be written (a full disk, no rights).

    The song is ``failed`` in the stage that was about to run or running, with the reason; the
    status exists in memory and in the summary only, and the batch goes on.
    """
    stage = run.current or (run.outcomes[-1].stage if run.outcomes else STAGES[0].name)
    error = run.error or ErrorInfo(
        stage=stage, kind=DISK_ERROR, message=f"cannot write the work folder: {_message(caught)}"
    )
    outcomes = list(run.outcomes)
    if not any(outcome.action == "failed" for outcome in outcomes):
        # after the last stage it is that stage whose result could not be recorded
        outcomes = [outcome for outcome in outcomes if outcome.stage != stage]
        outcomes.append(StageOutcome(stage=stage, action="failed"))
    status = _status_of(run.song, run.engines, outcomes, error)
    return SongResult(status, make_report(run.song, status, run.seconds, run.engines.store))


def _run_stages(run: _SongRun) -> SongResult:
    """Run the selected stages of the song of ``run``; see ``make_song``."""
    song, config, engines, options, hooks = (
        run.song,
        run.config,
        run.engines,
        run.options,
        run.hooks,
    )
    started = engines.clock.monotonic()
    length = song.tags.duration if song.tags is not None else None
    limit = time_limit(config, length)

    def time_left() -> float | None:
        return None if limit is None else limit - (engines.clock.monotonic() - started)

    line: LogLine = run.log
    watch = Watch(progress=hooks.sink.stage_progress, time_left=time_left)
    ctx = StageContext(song, engines, line, Path(config.models.folder), watch)
    recorded = _read_status(engines.store, song)  # before the loop overwrites it
    for stage in _selected(options):
        run.current = stage.name
        if hooks.stop.requested:
            run.log(f"stopped on request before {stage.name}")
            return SongResult(
                _write_status(song, engines, run.outcomes, run.error, stage.name), None
            )
        _write_status(
            song, engines, run.outcomes, run.error, current=stage.name
        )  # crash: "running"
        hooks.sink.stage_started(stage.name)
        stage_started = engines.clock.monotonic()
        device: str | None = None
        try:
            if (left := time_left()) is not None and left <= 0:
                raise StageError(
                    TIME_LIMIT,
                    f"the time limit of {format_duration(limit)} for this song was reached "
                    f"before {stage.name}",
                )
            outcome, device = _handle_stage(
                stage, ctx, config, force=options.force, offline=options.offline
            )
        except Exception as caught:  # one song must never stop the batch
            run.error = _failure(stage, ctx, caught)
            outcome = StageOutcome(stage=stage.name, action="failed")
        seconds = engines.clock.monotonic() - stage_started
        run.outcomes.append(outcome)
        if outcome.action != "skipped":
            run.seconds[stage.name] = seconds
        hooks.sink.stage_finished(stage.name, outcome, seconds, device)
        if outcome.action == "failed" or stage.name == options.until:
            break
    run.current = None
    later = _not_run(options)
    kept, kept_error = untouched_results(recorded, later, _still_current(ctx, config, later))
    order = [stage.name for stage in STAGES]
    results = sorted([*run.outcomes, *kept], key=lambda outcome: order.index(outcome.stage))
    status = _write_status(song, engines, results, run.error or kept_error)
    return SongResult(status, make_report(song, status, run.seconds, engines.store))


def run_song(  # noqa: PLR0913  # the options of one run; Options carries them for a batch
    song: Song,
    config: Config,
    engines: Engines,
    *,
    force: bool,
    offline: bool = False,
    until: str | None = None,
    only: tuple[str, ...] | None = None,
) -> SongStatus:
    """Run one song through the stages and return its final status; see ``make_song``."""
    options = Options(force=force, offline=offline, until=until, only=only)
    return make_song(song, config, engines, options).status


def _not_run(options: Options) -> list[str]:
    """Return the names of the stages a run leaves alone: after ``until``, or not in ``only``."""
    handled = {stage.name for stage in _selected(options)}
    return [stage.name for stage in STAGES if stage.name not in handled]


def _read_status(store: FileStore, song: Song) -> SongStatus | None:
    """Return the stored ``status.json`` of a song, or ``None`` if there is no valid one."""
    try:
        return read_model(store, song.work_dir / STATUS_FILE, SongStatus)
    except ValueError:
        return None


def run_batch(
    songs: list[Song],
    config: Config,
    engines: Engines,
    options: Options,
    hooks: Hooks | None = None,
) -> list[SongResult]:
    """Run every song, one after the other, and return their results in order.

    The batch stops after the song whose stage was running when ``stop`` was requested; the
    songs after it are not started and have no result.
    """
    hooks = hooks or Hooks()
    sink = hooks.sink
    sink.batch_started([plan_song(song, config, engines, options) for song in songs])
    results: list[SongResult] = []
    for index, song in enumerate(songs):
        if hooks.stop.requested:
            break
        sink.song_started(index, song)
        result = make_song(song, config, engines, options, hooks)
        sink.song_finished(index, result)
        results.append(result)
    return results
