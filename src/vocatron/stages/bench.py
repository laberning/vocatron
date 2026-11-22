"""The sync benchmark: run the pipeline on a corpus and measure the line starts (ADR-0004).

The corpus is a folder of songs, some with a human-made ``.lrc`` (only those are references). The
alignment runs without the line times as hints (``alignment.use_lrc_times`` off); its line starts
are compared with the line times that the lyrics stage took from the ``.lrc``. Everything printed
is a number, a file name or a fixed phrase: never a line of the lyrics.
"""

from pathlib import Path

from pydantic import BaseModel, ValidationError

from vocatron.core.alignment.file import AlignmentFile
from vocatron.core.bench import (
    BenchRun,
    SongResult,
    baseline_median,
    failures,
    gate_median,
    language_problem,
    run_of,
    song_result,
    summarise,
)
from vocatron.core.languages import DEFAULT_LANGUAGE, LANGUAGES
from vocatron.core.lyrics.file import LyricsFile
from vocatron.core.status import SongStatus
from vocatron.engines.protocols import FileStore
from vocatron.stages.alignment import ALIGNMENT_FILE
from vocatron.stages.batch import run_song
from vocatron.stages.config import Config
from vocatron.stages.lyrics import LYRICS_FILE
from vocatron.stages.stage import Engines, Song


def _read[M: BaseModel](store: FileStore, path: Path, model: type[M]) -> M | None:
    """Return the JSON file at ``path`` as ``model``, or ``None`` if it is missing or invalid."""
    try:
        text = store.read_text(path)
        return None if text is None else model.model_validate_json(text)
    except ValueError, ValidationError:
        return None


def measure(
    song: Song, status: SongStatus, store: FileStore, seconds: float, language: str
) -> SongResult:
    """Measure one finished song: its line starts against the line times of its ``.lrc``.

    A song whose lyrics are in another language than ``language`` (the language of the corpus
    folder it lies in) fails and is not compared: it must not hide in the numbers of the other
    language.

    Only an ``.lrc`` the user put next to the song is a reference. Line times of lyrics that
    Vocatron looked up and wrote there are not checked by anyone, so such a song is measured
    without a comparison (estimated words and status only).
    """
    aligned = _read(store, song.work_dir / ALIGNMENT_FILE, AlignmentFile)
    lyrics = _read(store, song.work_dir / LYRICS_FILE, LyricsFile)
    found: list[float | None] = [line.start for line in aligned.lines] if aligned else []
    reference: list[float | None] = [line.time for line in lyrics.lines] if lyrics else []
    if lyrics is not None and lyrics.written_hash is not None:  # Vocatron wrote it: no reference
        reference = [None] * len(reference)
    if len(found) != len(reference):  # a stage failed halfway: nothing to compare
        found, reference = found[:0], reference[:0]
    outcome = "failed" if status.state in {"failed", "running"} else status.state
    reasons = status.reasons
    if problem := language_problem(lyrics.language if lyrics else None, language):
        outcome, found, reference = "failed", found[:0], reference[:0]
        reasons = [problem, *reasons]
    if status.error is not None:
        reasons = [f"{status.error.stage} failed: {status.error.kind}", *reasons]
    return song_result(
        outcome,
        reasons,
        found,
        reference,
        aligned.quality.estimated_share if aligned is not None else None,
        seconds,
    )


def run_bench(
    songs: list[Song], config: Config, engines: Engines, language: str = DEFAULT_LANGUAGE
) -> BenchRun:
    """Run every song through the pipeline and measure it.

    Stages whose results are current are skipped, so a second run costs only what changed.
    ``language`` is the language of the corpus folder the songs come from (see ``measure``).
    """
    results: dict[str, SongResult] = {}
    for song in songs:
        started = engines.clock.now()
        status = run_song(song, config, engines, force=False)
        seconds = (engines.clock.now() - started).total_seconds()
        results[song.source.name] = measure(song, status, engines.store, seconds, language)
    return run_of(results)


def read_run(store: FileStore, path: Path) -> BenchRun | None:
    """Return the benchmark run stored at ``path``, or ``None`` if there is none."""
    return _read(store, path, BenchRun)


def write_run(store: FileStore, path: Path, run: BenchRun) -> None:
    """Store a benchmark run."""
    store.write_text(path, run.model_dump_json(indent=2) + "\n")


def _percent(share: float | None) -> str:
    """Format a share as a percentage, or a dash."""
    return "-" if share is None else f"{share * 100:.0f}%"


def _millis(value: float | None) -> str:
    """Format milliseconds, or a dash."""
    return "-" if value is None else f"{value:.0f} ms"


def _change(now: float | None, before: float | None) -> str:
    """Format the change of a median against the baseline, or nothing."""
    if now is None or before is None:
        return ""
    return f"  ({now - before:+.0f} ms against the baseline)"


def _heading(language: str) -> str:
    """Return the heading line of one language's report."""
    module = LANGUAGES.get(language)
    return f"== {module.name if module else language} ({language}) =="


def report(last: BenchRun, baseline: BenchRun | None, language: str | None = None) -> list[str]:
    """Return the lines of the report: one per song, the overall result, and what fails.

    With a ``language`` the report starts with a heading line naming it.

    Each line gives the absolute error and the offset-corrected one (the song's median signed
    error removed); the gate judges the corrected one.

    Args:
        last: This run.
        baseline: The accepted run to compare with, if there is one.
        language: The language of the corpus folder, for the heading.
    """
    lines: list[str] = [] if language is None else [_heading(language)]
    for name, result in last.songs.items():
        before = baseline.songs.get(name) if baseline is not None else None
        summary = summarise(result.errors_ms)
        corrected = summarise(result.corrected_errors_ms or [])
        before_median = (
            summarise(before.corrected_errors_ms).median_ms
            if before is not None and before.corrected_errors_ms is not None
            else None
        )
        lines.append(
            f"{name}: {result.status}, {result.compared}/{result.lines} lines compared, "
            f"median {_millis(summary.median_ms)}, "
            f"within 200 ms {_percent(summary.within_200_ms)}, "
            f"within 500 ms {_percent(summary.within_500_ms)}, "
            f"corrected median {_millis(corrected.median_ms)}, "
            f"within 200 ms {_percent(corrected.within_200_ms)}, "
            f"within 500 ms {_percent(corrected.within_500_ms)}, "
            f"estimated words {_percent(result.estimated_share)}, "
            f"offset {_millis(result.offset_ms)}, {result.seconds:.0f} s"
            f"{_change(corrected.median_ms, before_median)}"
        )
        lines.extend(f"    review: {reason}" for reason in result.reasons)
    overall = last.overall
    corrected_overall = last.overall_corrected or summarise([])
    lines.append(
        f"overall: {overall.count} lines, median {_millis(overall.median_ms)}, within 200 ms "
        f"{_percent(overall.within_200_ms)}, within 500 ms {_percent(overall.within_500_ms)}; "
        f"corrected median {_millis(corrected_overall.median_ms)}, "
        f"within 200 ms {_percent(corrected_overall.within_200_ms)}, "
        f"within 500 ms {_percent(corrected_overall.within_500_ms)}"
        f"{_change(gate_median(last), baseline_median(baseline))}"
    )
    if baseline is None:
        lines.append("no accepted baseline yet: 'make bench-accept' accepts this run")
    elif baseline_median(baseline) is None:
        lines.append(
            "the baseline has no corrected values: only the 200 ms limit applies, "
            "'make bench-accept' accepts this run as a new baseline"
        )
    lines.extend(f"FAIL: {reason}" for reason in failures(last, baseline))
    return lines
