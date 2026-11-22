"""The commands as plain functions: engines, console and folders are passed in (ADR-0007).

``app.py`` wires in the real ones; the fast tests wire in fakes. Each returns the exit code.
"""

from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.text import Text

from vocatron.cli.config_file import ConfigError, Overrides, load_config
from vocatron.cli.console import (
    ConsoleDownloadListener,
    alignment_warnings,
    check_line,
    choose_display,
    echo_to,
    lyrics_report,
    lyrics_warnings,
    models_table,
    print_line,
    print_row,
    profiles_table,
    total_text,
)
from vocatron.core.errors import StageError, UsageError
from vocatron.core.models import (
    DEFAULT_SET,
    MODELS,
    ModelSpec,
    UnknownModelError,
    find_model,
    language_models,
)
from vocatron.core.profiles.check import check_profile
from vocatron.core.profiles.copy import copy_text, default_name, valid_name
from vocatron.core.profiles.model import BUILTIN_PROFILES, is_name, override_keys
from vocatron.core.report import exit_code_of
from vocatron.core.status import EXIT_FAILED, EXIT_USAGE
from vocatron.engines.protocols import DownloadError, SystemProbe
from vocatron.stages.alignment import load_alignment
from vocatron.stages.batch import Hooks, Options, StopFlag, run_batch
from vocatron.stages.config import Config
from vocatron.stages.doctor import run_checks
from vocatron.stages.lyrics import LYRICS_STAGE, approve, load_lyrics
from vocatron.stages.models import ModelFolder, fetch
from vocatron.stages.profiles import (
    OWN_SUFFIX,
    ProfileText,
    folder_path,
    is_chosen,
    list_profiles,
    not_found,
    profile_text,
)
from vocatron.stages.progress import TIMINGS_FILE, Tracker
from vocatron.stages.report import stored_row, write_report_text
from vocatron.stages.songs import discover
from vocatron.stages.stage import Engines, Song


def _fail(console: Console, messages: list[str]) -> int:
    """Print usage or configuration problems and return the usage exit code."""
    for message in messages:
        print_line(console, f"error: {message}")
    return EXIT_USAGE


@dataclass(frozen=True)
class Edges:
    """What the commands get from the outside world.

    Attributes:
        engines: Clock, tag reader and file store.
        console: Where results go.
        error_console: Where usage and configuration errors go.
        cwd: The current folder, where ``vocatron.yaml`` is looked for.
        probe: Reads ffmpeg and the GPU for ``doctor``.
        clone: The folder of the Vocatron clone, where the default model folder lies and the
            learnt speeds are kept.
        stop: Set by the first Ctrl-C: the batch stops after the stage that is running.
        log: Stream the song logs instead of the live display (``--log``).
    """

    engines: Engines
    console: Console
    error_console: Console
    cwd: Path
    probe: SystemProbe
    clone: Path
    stop: StopFlag = field(default_factory=StopFlag)
    log: bool = False


def _load(
    output: str | None,
    config_file: Path | None,
    edges: Edges,
    overrides: Overrides | None = None,
) -> Config:
    """Load the configuration; the default model folder lies in the clone."""
    return load_config(edges.engines.store, config_file, edges.cwd, output, edges.clone, overrides)


def _prepare(
    path: Path,
    output: str | None,
    config_file: Path | None,
    edges: Edges,
    overrides: Overrides | None = None,
) -> tuple[Config, list[Song]] | int:
    """Load the configuration and find the songs; return the usage exit code on a problem."""
    try:
        config = _load(output, config_file, edges, overrides)
        return config, discover(path, config, edges.engines)
    except ConfigError as error:
        return _fail(edges.error_console, error.messages)
    except UsageError as error:
        return _fail(edges.error_console, [str(error)])


def run_make(
    path: Path,
    *,
    output: str | None,
    config_file: Path | None,
    options: Options | None = None,
    overrides: Overrides | None = None,
    edges: Edges,
) -> int:
    """Run the pipeline on one song or on every song of a folder.

    ``options`` say how (``--force``, ``--offline``); ``overrides`` are the command-line options
    that override the configuration (``--language``, ``--no-backing``, ``--device``).

    Returns:
        The exit code: 0 when every song is ``ok`` or ``review``, 1 when one failed, 2 on a
        usage or configuration error or when the output folder cannot be created.
    """
    return _run(path, output, config_file, options or Options(), edges, overrides)


# What `vocatron render` runs: no AI stage, and the CD+G output, which draws the same look.
RENDER_STAGES = ("probe", "tempo", "layout", "render", "cdg")


def run_render(
    path: Path,
    *,
    output: str | None,
    config_file: Path | None,
    force: bool,
    overrides: Overrides | None = None,
    edges: Edges,
) -> int:
    """Render the video again from the work folders: probe, layout and render only.

    The stages before them are left alone, so a new profile or preset takes seconds, not a
    separation and an alignment. ``overrides`` are ``--profile`` and ``--preset``.

    Returns:
        The exit code, as for ``run_make``.
    """
    options = Options(force=force, only=RENDER_STAGES)
    return _run(path, output, config_file, options, edges, overrides)


def run_lyrics(
    path: Path,
    *,
    output: str | None,
    config_file: Path | None,
    force: bool,
    language: str | None = None,
    edges: Edges,
) -> int:
    """Run the first stages up to the lyrics (probe and lyrics) and nothing else.

    The results of the other stages already in ``status.json`` stay.

    Returns:
        The exit code, as for ``run_make``.
    """
    options = Options(force=force, until=LYRICS_STAGE)
    return _run(path, output, config_file, options, edges, Overrides(language=language))


def _run(
    path: Path,
    output: str | None,
    config_file: Path | None,
    options: Options,
    edges: Edges,
    overrides: Overrides | None,
) -> int:
    """Run the stages that ``options`` ask for on the songs of ``path``."""
    prepared = _prepare(path, output, config_file, edges, overrides)
    if isinstance(prepared, int):
        return prepared
    config, songs = prepared
    output_dir = songs[0].output_dir  # the same for every song
    try:
        edges.engines.store.make_folder(output_dir)
    except OSError as error:
        reason = error.strerror or type(error).__name__
        return _fail(
            edges.error_console, [f"cannot create the output folder {output_dir}: {reason}"]
        )
    return _batch(songs, config, options, edges)


def _batch(songs: list[Song], config: Config, options: Options, edges: Edges) -> int:
    """Run the batch with the live display, print the summary, and return the exit code.

    A stop request (the first Ctrl-C) ends the batch after the stage that is running; a second
    Ctrl-C arrives here as ``KeyboardInterrupt``, after the child process was killed. Either way
    the work that was finished stays, and the song that was running shows as interrupted.
    """
    engines, console = edges.engines, edges.console
    tracker = Tracker(engines, choose_display(console, log=edges.log), edges.clone / TIMINGS_FILE)
    hooks = Hooks(tracker, edges.stop, echo_to(console) if edges.log else None)
    started = engines.clock.monotonic()
    stopped = False
    try:
        results = run_batch(songs, config, engines, options, hooks)
        # a stop that came during the last stage of the last song stopped nothing
        stopped = len(results) < len(songs) or any(result.report is None for result in results)
    except KeyboardInterrupt:
        stopped = True
    finally:
        tracker.close()
    took = engines.clock.monotonic() - started
    rows = [tracker.rows.get(i) or stored_row(song, engines) for i, song in enumerate(songs)]
    names = [song.name for song in songs]
    if stopped:
        # the song that was running gets its line; songs never started are counted in the total
        for index, row in enumerate(rows):
            if index not in tracker.rows and row.state != "not run":
                print_row(console, row, names)
        print_line(
            console, "stopped on request; finished work is kept, run `vocatron make` again to go on"
        )
    print_line(console, total_text(rows, took))
    for song in songs:
        for note in _order_warnings(song, engines, options.until):
            print_line(console, Text(f"warning: {song.name}: {note}", style="yellow"))
    if options.until is None:
        write_report_text(songs[0].output_dir, rows, took, engines.clock.now(), engines.store)
    return max(exit_code_of(rows), EXIT_FAILED if stopped else 0)


def _order_warnings(song: Song, engines: Engines, until: str | None) -> list[str]:
    """Return the line times of the song that break the order of its lines.

    After ``vocatron lyrics`` they come from the lyrics alone; after a run that went further, from
    ``alignment.json``, where the singing decided which of two contradicting times was skipped.
    """
    if until == LYRICS_STAGE:
        lyrics = load_lyrics(song, engines)
        return [] if lyrics is None else lyrics_warnings(lyrics)
    aligned = load_alignment(song, engines)
    return [] if aligned is None else alignment_warnings(aligned)


def run_status(path: Path, *, output: str | None, config_file: Path | None, edges: Edges) -> int:
    """Print the stored summary of every song without running anything.

    A song that is being made right now (from another terminal) shows its stage, percentage
    and time left.

    Returns:
        The exit code: 1 when a stored status is ``failed`` or ``running`` (an interrupted
        run), 0 otherwise (also for songs not run yet), 2 on a usage or configuration error.
    """
    prepared = _prepare(path, output, config_file, edges)
    if isinstance(prepared, int):
        return prepared
    _, songs = prepared
    rows = [stored_row(song, edges.engines) for song in songs]
    names = [song.name for song in songs]
    for row in rows:
        print_row(edges.console, row, names)
    print_line(edges.console, total_text(rows, sum(row.seconds or 0.0 for row in rows)))
    return exit_code_of(rows)


def _load_or_fail(
    output: str | None,
    config_file: Path | None,
    edges: Edges,
    overrides: Overrides | None = None,
) -> Config | int:
    """Load the configuration; return the usage exit code on a problem."""
    try:
        return _load(output, config_file, edges, overrides)
    except ConfigError as error:
        return _fail(edges.error_console, error.messages)


def _folder_of(config: Config, edges: Edges) -> ModelFolder:
    """Return the model folder the configuration names."""
    return ModelFolder(Path(config.models.folder), edges.engines.store)


def run_models(*, config_file: Path | None, edges: Edges) -> int:
    """Print every model with its state, size and licence.

    Returns:
        0, or 2 on a configuration error.
    """
    config = _load_or_fail(None, config_file, edges)
    if isinstance(config, int):
        return config
    folder = _folder_of(config, edges)
    states = {spec.name: folder.state(spec, verify=True) for spec in MODELS}
    edges.console.print(models_table(MODELS, states, folder.folder))
    return 0


def _select(names: list[str], language: str | None) -> list[ModelSpec]:
    """Return the models called ``names`` and those a song in ``language`` needs.

    Without names and without a language, the set for an English song. ``language`` was checked
    against the registry when the configuration was loaded.

    Raises:
        UsageError: If a name is not in the registry.
    """
    wanted = [*names, *(language_models(language) if language else ())]
    try:
        return [find_model(name) for name in dict.fromkeys(wanted or DEFAULT_SET)]
    except UnknownModelError as error:
        raise UsageError(error.args[0]) from error


def run_models_download(
    names: list[str], *, language: str | None = None, config_file: Path | None, edges: Edges
) -> int:
    """Download the named models and verify them.

    Args:
        names: The models to download.
        language: Also download what a song in this language needs (``--language``).
        config_file: The configuration file given with ``--config``.
        edges: Where the command meets the world.

    Without names and without a language it downloads what an English song needs.

    Returns:
        0, 1 when a download fails, 2 on a configuration error, an unsupported language or an
        unknown name.
    """
    config = _load_or_fail(None, config_file, edges, Overrides(language=language))
    if isinstance(config, int):
        return config
    try:
        specs = _select(names, language)
    except UsageError as error:
        return _fail(edges.error_console, [str(error)])
    folder = _folder_of(config, edges)
    try:
        listener = ConsoleDownloadListener(edges.console)
        fetched = fetch(specs, folder, edges.engines.downloader, listener)
    except DownloadError as error:
        print_line(edges.error_console, f"error: {error}")
        return EXIT_FAILED
    done = {spec.name for spec in fetched}
    for spec in specs:
        if spec.name not in done:
            print_line(edges.console, f"{spec.name}: already present and verified")
    return 0


def run_doctor(*, output: str | None, config_file: Path | None, edges: Edges) -> int:
    """Check the machine and print one line per check with what to fix.

    Returns:
        0 when every check passed, 1 when something needs fixing, 2 on a configuration error.
    """
    config = _load_or_fail(output, config_file, edges)
    if isinstance(config, int):
        return config
    output_folder = edges.cwd / config.output.folder
    checks = run_checks(
        edges.probe, edges.engines.store, _folder_of(config, edges), output_folder, config
    )
    for check in checks:
        edges.console.print(check_line(check))
    failed = [check for check in checks if not check.ok]
    warned = sum(check.warning is not None for check in checks)
    notes = f" ({warned} with a note)" if warned else ""
    print_line(
        edges.console,
        f"{len(failed)} of {len(checks)} checks need attention"
        if failed
        else f"everything is ready{notes}",
    )
    return EXIT_FAILED if failed else 0


def run_lyrics_show(
    path: Path, *, output: str | None, config_file: Path | None, edges: Edges
) -> int:
    """Print the status, the reasons and the flagged lines of the lyrics of every song.

    Returns:
        0, or 2 on a usage or configuration error.
    """
    prepared = _prepare(path, output, config_file, edges)
    if isinstance(prepared, int):
        return prepared
    for song in prepared[1]:
        for row in lyrics_report(song.name, load_lyrics(song, edges.engines)):
            print_line(edges.console, row)
    return 0


def run_lyrics_approve(
    path: Path,
    *,
    output: str | None,
    config_file: Path | None,
    language: str | None = None,
    edges: Edges,
) -> int:
    """Approve the lyrics files next to the songs as they are, and refresh the song status.

    The status is refreshed like ``run_lyrics`` with the same options, so ``language`` (the
    ``--language`` option) must be the one the lyrics were checked with, or the lyrics stage runs
    again with the other setting.

    Returns:
        0 when every song's lyrics are approved, 1 when one cannot be or its refreshed status is
        ``failed``, 2 on a usage or configuration error.
    """
    prepared = _prepare(path, output, config_file, edges, Overrides(language=language))
    if isinstance(prepared, int):
        return prepared
    config, songs = prepared
    refused = 0
    for song in songs:
        problem = approve(song, edges.engines)
        if problem is None:
            print_line(edges.console, f"approved {song.name}")
            options = Options(until=LYRICS_STAGE)
            (result,) = run_batch([song], config, edges.engines, options)
            if result.status.error is not None:
                problem = f"the song failed after the approval: {result.status.error.message}"
        if problem is not None:
            refused += 1
            print_line(edges.error_console, f"error: {song.name}: {problem}")
    return EXIT_FAILED if refused else 0


def run_profiles(*, config_file: Path | None, edges: Edges) -> int:
    """Print every built-in and own profile, and mark the one the configuration chooses.

    Returns:
        0, or 2 on a configuration error.
    """
    config = _load_or_fail(None, config_file, edges)
    if isinstance(config, int):
        return config
    store, folder = edges.engines.store, folder_path(config.profiles_folder)
    entries = list_profiles(folder, store, edges.engines.resources)
    edges.console.print(profiles_table(entries, lambda entry: is_chosen(entry, config.profile)))
    if folder is not None and store.kind(folder) != "folder":
        print_line(edges.console, f"\nwarning: profiles_folder {folder} is not a folder")
    return 0


def _resolve_profile(spec: str, config: Config, edges: Edges) -> ProfileText | str:
    """Find the profile ``spec`` (a name, or a path relative to the current folder).

    Returns:
        The profile, or the message why there is none.
    """
    store, folder = edges.engines.store, folder_path(config.profiles_folder)
    where = spec if is_name(spec) else str(edges.cwd / spec)
    try:
        found = profile_text(where, folder, store, edges.engines.resources)
    except StageError as error:
        return str(error)
    return not_found(spec, folder, store) if found is None else found


def run_profiles_check(spec: str, *, config_file: Path | None, edges: Edges) -> int:
    """Check a profile without rendering: it loads, fits and keeps the layout rules.

    The ``profile_overrides`` of the configuration are applied first, and named in the output.
    Problems print as ``file:line:column: message``; a clean profile prints ``ok``.

    Returns:
        0 when the profile is fine, 1 when it has problems, 2 on a configuration or usage error
        (no such profile, or a name that is both built in and in the profiles folder).
    """
    config = _load_or_fail(None, config_file, edges)
    if isinstance(config, int):
        return config
    found = _resolve_profile(spec, config, edges)
    if isinstance(found, str):
        return _fail(edges.error_console, [found])
    if config.profile_overrides:
        keys = ", ".join(override_keys(config.profile_overrides))
        print_line(edges.console, f"applying profile_overrides of the configuration: {keys}")
    name = spec if is_name(spec) else Path(spec).stem
    problems = check_profile(
        found.label,
        found.text,
        expected_name=name,
        overrides=config.profile_overrides,
        measurer=edges.engines.measurer,
        rasteriser=edges.engines.rasteriser,
    )
    for problem in problems:
        print_line(edges.console, problem)
    if not problems:
        print_line(edges.console, f"{found.label}: ok")
    return EXIT_FAILED if problems else 0


def run_profiles_copy(
    source: str, target: str | None, *, config_file: Path | None, version: str, edges: Edges
) -> int:
    """Write an editable copy of a built-in profile; never overwrite a file.

    ``target`` is a new name (the file goes into ``profiles_folder``), a file path (relative to
    the current folder) or nothing (``my-<source>`` in ``profiles_folder``).

    Returns:
        0 when the copy was written, 1 when the file exists, 2 on a configuration or usage error.
    """
    config = _load_or_fail(None, config_file, edges)
    if isinstance(config, int):
        return config
    text = edges.engines.resources.builtin_profile(source)
    if text is None:
        known = ", ".join(BUILTIN_PROFILES)
        return _fail(edges.error_console, [f"{source!r} is not a built-in profile; known: {known}"])
    wanted = target if target is not None else default_name(source)
    folder = folder_path(config.profiles_folder)
    if is_name(wanted):
        if folder is None:
            return _fail(
                edges.error_console,
                [f"cannot copy to the name {wanted!r}: set profiles_folder in the configuration"],
            )
        path, name = folder / f"{wanted}{OWN_SUFFIX}", wanted
    else:
        path = edges.cwd / wanted
        name = path.stem
    if not valid_name(name) or (is_name(wanted) and name in BUILTIN_PROFILES):
        return _fail(
            edges.error_console,
            [
                f"{name!r} cannot be the name of an own profile: use letters, digits, - and _, "
                "and not the name of a built-in profile"
            ],
        )
    if edges.engines.store.kind(path) is not None:
        print_line(edges.error_console, f"error: {path} exists already; it is not overwritten")
        return EXIT_FAILED
    chosen_by = name if is_name(wanted) else str(path)
    edges.engines.store.write_text(path, copy_text(text, source, name, version, chosen_by))
    print_line(edges.console, f"wrote {path}")
    print_line(edges.console, f"check it with: vocatron profiles check {chosen_by}")
    return 0
