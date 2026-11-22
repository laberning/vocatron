"""Console output: the live batch display, one line per song and a summary (ADR-0006)."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import override

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from vocatron.core.alignment.file import AlignmentFile
from vocatron.core.alignment.rails import order_notes, skipped_note
from vocatron.core.lyrics.file import LyricsFile
from vocatron.core.models import ModelFile, ModelSpec, human_size
from vocatron.core.models import State as ModelState
from vocatron.core.profiles.model import made_for_cdg
from vocatron.core.progress import format_duration
from vocatron.core.report import STATE_WIDTH, SummaryRow, format_row, name_width, total_line
from vocatron.core.status import StageOutcome, State
from vocatron.core.system import Check
from vocatron.stages.profiles import ProfileEntry
from vocatron.stages.progress import View

STYLES: dict[State, str] = {"ok": "green", "review": "yellow", "failed": "red", "running": "red"}
ROW_STYLES: dict[str, str] = {**STYLES, "interrupted": STYLES["running"], "not run": "dim"}
MIN_PROGRESS_SIZE = 1 << 20  # smaller files are done before a progress line would help
NOT_RUN = "not run"


def terminal_width(console: Console) -> int | None:
    """Return the width rows are cut to: the terminal's, or ``None`` when output is not one."""
    return console.width if console.is_terminal else None


def styled_row(row: SummaryRow, names: Sequence[str], width: int | None) -> Text:
    """Format one summary row to fit ``width``, with its state coloured.

    Args:
        row: The song.
        names: The names of all songs in the list, so the name column is the same on every row.
        width: The width to fit, see ``terminal_width``.
    """
    line = Text(format_row(row, name_width(names, width), width))
    line.stylize(ROW_STYLES[row.state], 0, STATE_WIDTH)
    return line


def print_line(console: Console, line: Text | str) -> None:
    """Print one line of output that rich must never break (it would wrap at 80 columns in a pipe).

    A plain string is printed as it is, without markup or highlighting. A terminal may still fold
    a very long line visually; the text itself stays one line.
    """
    text = Text(line) if isinstance(line, str) else line
    console.print(text, soft_wrap=True)


def print_row(console: Console, row: SummaryRow, names: Sequence[str]) -> None:
    """Print one summary row: cut to a terminal's width, whole and unwrapped anywhere else.

    Rich wraps at 80 columns when the output is not a terminal; ``soft_wrap`` keeps the uncut
    row of a file or a pipe on one line.
    """
    width = terminal_width(console)
    console.print(styled_row(row, names, width), soft_wrap=width is None)


def total_text(rows: Sequence[SummaryRow], seconds: float | None) -> Text:
    """Format the total line of a batch."""
    return Text(total_line(rows, seconds))


def batch_text(view: View) -> str:
    """Format the live line of the batch: songs done, percentage, time elapsed and left."""
    return (
        f"[{view.finished}/{view.total}] {view.percent}%  "
        f"elapsed {format_duration(view.elapsed)}  about {format_duration(view.left)} left"
    )


def song_text(view: View) -> str:
    """Format the live line of the current song: its stage, the stage's progress, time left."""
    if view.stage is None:
        return f"{view.song}"
    return (
        f"{view.song}: {view.stage} {round(view.fraction * 100)}%  "
        f"about {format_duration(view.song_left)} left"
    )


class PlainDisplay:
    """Prints one plain line per finished stage and per finished song: no terminal is needed.

    With ``stages`` off (``--log``, which streams the log instead) only the songs' lines remain.
    """

    def __init__(self, console: Console, *, stages: bool = True) -> None:
        """Print to ``console``."""
        self._console = console
        self._stages = stages

    def song_started(self, index: int, total: int, name: str) -> None:
        """Print ``[i/n] name ...``."""
        print_line(self._console, Text(f"[{index}/{total}] {name} ...", style="dim"))

    def update(self, view: View) -> None:
        """Print nothing: a plain log has no place for a bar."""

    def stage_done(
        self, song: str, stage: str, outcome: StageOutcome, seconds: float, view: View
    ) -> None:
        """Print how a stage ended."""
        del song, view
        if not self._stages:
            return
        took = "" if outcome.action == "skipped" else f" in {format_duration(seconds)}"
        print_line(self._console, Text(f"  {stage}: {outcome.action}{took}", style="dim"))

    def song_done(self, row: SummaryRow, names: Sequence[str]) -> None:
        """Print the summary line of the song."""
        print_row(self._console, row, names)

    def close(self) -> None:
        """Nothing to let go of."""


class LiveDisplay(PlainDisplay):
    """The batch line and the current song line as a live display; finished songs scroll above."""

    def __init__(self, console: Console) -> None:
        """Show on ``console``, which is a terminal."""
        super().__init__(console, stages=False)
        self._live = Live(console=console, transient=True, refresh_per_second=4)
        self._started = False

    @override
    def song_started(self, index: int, total: int, name: str) -> None:
        """The live line names the song; nothing is printed."""
        del index, total, name

    @override
    def update(self, view: View) -> None:
        """Show the two lines."""
        if not self._started:
            self._live.start()
            self._started = True
        self._live.update(Group(Text(batch_text(view)), Text(song_text(view), style="dim")))

    @override
    def close(self) -> None:
        """Take the live lines away, leaving the summary lines."""
        if self._started:
            self._live.stop()
            self._started = False


def choose_display(console: Console, *, log: bool) -> PlainDisplay:
    """Return the live display on a terminal, else plain lines; ``--log`` streams the log."""
    if log:
        return PlainDisplay(console, stages=False)
    return LiveDisplay(console) if console.is_terminal else PlainDisplay(console)


def echo_to(console: Console) -> Callable[[str], None]:
    """Return what prints a log line (``--log``) as it is written, exactly as it is."""

    def echo(line: str) -> None:
        print_line(console, line)

    return echo


MODEL_STYLES: dict[ModelState, str] = {
    "present": "green",
    "missing": "dim",
    "partial": "yellow",
    "mismatch": "red",
}
MODEL_LABELS: dict[ModelState, str] = {
    "present": "present",
    "missing": "missing",
    "partial": "partial",
    "mismatch": "checksum mismatch",
}
LICENCE_NOTE = (
    "Model weights are data that Vocatron downloads and loads; they are not part of Vocatron and "
    "keep their own licences."
)


def models_table(
    specs: Sequence[ModelSpec], states: Mapping[str, ModelState], folder: Path
) -> Group:
    """Format the model list.

    A table of name, purpose, state, size and licence, then the folder and the note on licences.
    """
    table = Table(box=None, pad_edge=False)
    for column in ("Name", "Purpose", "State", "Size", "Licence"):
        table.add_column(column, no_wrap=column != "Purpose")
    for spec in specs:
        state = states[spec.name]
        table.add_row(
            spec.name,
            spec.purpose,
            Text(MODEL_LABELS[state], style=MODEL_STYLES[state]),
            human_size(spec.size),
            spec.licence,
        )
    return Group(table, Text(f"\nModel folder: {folder}\n{LICENCE_NOTE}"))


def profiles_table(
    entries: Sequence[ProfileEntry], chosen: Callable[[ProfileEntry], bool]
) -> Table:
    """Format the list of profiles: name, description, mode, slots, CD+G and source.

    The CD+G column says whether the look is made for CD+G (ADR-0029): ``yes`` or ``no``.

    The profile the configuration chooses is marked with ``*``. A profile that does not load is
    listed as invalid, with its first problem and the command that checks it.
    """
    table = Table(box=None, pad_edge=False)
    table.add_column("")
    for column in ("Name", "Description", "Mode", "Slots", "CD+G", "Source"):
        table.add_column(column, no_wrap=column != "Description")
    for entry in entries:
        mark = "*" if chosen(entry) else ""
        profile = entry.profile
        if profile is None:
            what = Text(
                f"invalid: {entry.problem}\nrun `vocatron profiles check {entry.name}`", style="red"
            )
            table.add_row(mark, entry.name, what, "-", "-", "-", entry.source)
        else:
            table.add_row(
                mark,
                entry.name,
                profile.description,
                profile.mode,
                "-" if profile.mode == "scroll" else str(profile.slots),
                "yes" if made_for_cdg(profile) else "no",
                entry.source,
            )
    return table


def check_line(check: Check) -> Table:
    """Format one ``doctor`` check: a mark, its name, what was found, and the fix if any.

    The text wraps inside its own column, so a long fix stays aligned.
    """
    mark = Text("\u2713", style="green") if check.ok else Text("\u2717", style="red")
    if check.warning is not None:
        mark = Text("!", style="yellow")
    detail = Text(check.detail)
    if check.fix is not None:
        detail.append(f"\nfix: {check.fix}", style="yellow")
    if check.warning is not None:
        detail.append(f"\nnote: {check.warning}", style="yellow")
    grid = Table.grid(padding=(0, 1))
    grid.add_column(width=1)
    grid.add_column(min_width=13, no_wrap=True)
    grid.add_column()
    grid.add_row(mark, check.name, detail)
    return grid


class ConsoleDownloadListener:
    """Prints the licence, each file and its progress in steps of a tenth."""

    def __init__(self, console: Console) -> None:
        """Print to ``console``."""
        self._console = console
        self._step = -1

    def licence(self, spec: ModelSpec) -> None:
        """Print the licence notice and the source of the model."""
        url = f", {spec.licence_url}" if spec.licence_url else ""
        print_line(self._console, f"{spec.notice()} ({spec.source}, {spec.revision}{url})")

    def file_started(self, spec: ModelSpec, file: ModelFile) -> None:
        """Print which file is fetched."""
        self._step = -1
        label = f"  {spec.name}/{file.path} ({human_size(file.size)})"
        print_line(self._console, Text(label, style="dim"))

    def progress(self, done: int, total: int) -> None:
        """Print a line when a new tenth of the file is done (not for small files)."""
        step = done * 10 // total if total else 0
        if step > self._step and total >= MIN_PROGRESS_SIZE:
            self._step = step
            print_line(self._console, Text(f"    {step * 10}%", style="dim"))

    def file_finished(self, spec: ModelSpec, file: ModelFile) -> None:
        """Print that the file passed its checksum."""
        del spec
        print_line(self._console, Text(f"  {file.path} verified", style="green"))


def lyrics_warnings(file: LyricsFile) -> list[str]:
    """Return one note per line time of the lyrics that breaks the order of the lines."""
    return order_notes([line.time for line in file.lines])


def alignment_warnings(file: AlignmentFile) -> list[str]:
    """Return one note per line time that the alignment skipped for breaking the order."""
    return [skipped_note(hint.line, hint.time) for hint in file.rails.dropped]


def lyrics_report(name: str, file: LyricsFile | None) -> list[Text]:
    """Format what the lyrics checks found for one song: status, reasons and flagged lines.

    A song whose lyrics were not checked yet gets the line ``not run``.
    """
    if file is None:
        return [Text.assemble((f"{NOT_RUN:<8}", "dim"), " ", name)]
    state: State = "ok" if file.status == "ok" else "review"
    facts = f"{file.sidecar}, {file.source}, language {file.language}"
    if file.approved:
        facts += ", approved"
    rows = [Text.assemble((f"{file.status:<8}", STYLES[state]), " ", name, (f"  ({facts})", "dim"))]
    rows += [Text(f"  {finding}", style="yellow") for finding in file.findings]
    rows += [Text(f"  warning: {note}", style="yellow") for note in lyrics_warnings(file)]
    rows += [Text(f"  line {r.line} [{r.kind}] {r.text}", style="dim") for r in file.removed]
    return rows
