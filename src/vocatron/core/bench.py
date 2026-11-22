"""The metrics of the sync benchmark and the rule that fails it (ADR-0004, stage 3).

A line-start error is how far the line starts the alignment found (without guide rails) lie from
the human-made line times of the song's ``.lrc``. The corrected error removes the song's constant
shift (the median signed error) first, so a reference shifted as a whole does not count against
the sync; the gate judges the corrected error, the absolute one is reported next to it. The
benchmark keeps numbers only: no lyrics.
"""

from collections.abc import Mapping, Sequence
from statistics import median
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from vocatron.core.languages import DEFAULT_LANGUAGE

LIMIT_MS = 200.0
"""The quality target of the vision: the overall median error may not exceed it."""
REGRESSION_MS = 50.0
"""The overall median may not be more than this much worse than the accepted baseline."""
WITHIN_NEAR_MS = 200.0
WITHIN_FAR_MS = 500.0

Outcome = Literal["ok", "review", "failed"]


class BenchFiles(NamedTuple):
    """Where the benchmark of one language keeps its songs and results.

    Attributes:
        songs: The corpus folder with the songs, below the corpus root.
        work: The work folder of the run, below ``bench``.
        last: The result of the last run, below ``bench``.
        baseline: The accepted result, below ``bench``.
    """

    songs: str
    work: str
    last: str
    baseline: str


def bench_files(language: str, model: str | None = None) -> BenchFiles:
    """Return the names the benchmark of ``language`` uses, with ``model`` as separation model.

    German (the default language) keeps ``songs``, ``work``, ``last.json`` and ``baseline.json``;
    another language appends ``-<code>`` (``songs-en``, ``work-en``, ``last-en.json``,
    ``baseline-en.json``). A model goes in front of the code (``work-<model>-en``); the baseline
    does not depend on it.
    """
    suffix = "" if language == DEFAULT_LANGUAGE else f"-{language}"
    infix = "" if model is None else f"-{model}"
    return BenchFiles(
        songs=f"songs{suffix}",
        work=f"work{infix}{suffix}",
        last=f"last{infix}{suffix}.json",
        baseline=f"baseline{suffix}.json",
    )


def language_problem(found: str | None, expected: str) -> str | None:
    """Return why a song does not belong in the corpus folder of ``expected``, or ``None``.

    ``found`` is the language its lyrics were detected as (``None``: not known, the lyrics stage
    did not finish; that is a failure of its own).
    """
    if found is None or found == expected:
        return None
    return f"the lyrics are in language {found}, this corpus folder is for {expected}"


class SongResult(BaseModel):
    """What the benchmark measured for one song.

    Attributes:
        status: The song status after the run.
        reasons: The review reasons of the song (numbers and fixed phrases, no lyrics).
        lines: How many lines the song has.
        compared: How many line starts could be compared with the reference.
        errors_ms: The absolute line-start errors in milliseconds.
        corrected_errors_ms: The absolute errors after removing ``offset_ms`` from every signed
            error (the song's constant shift); ``None`` in results from before this was measured.
        offset_ms: The median signed error (positive: found later than the reference).
        estimated_share: The share of estimated words, or ``None`` if the song did not align.
        seconds: How long the song took in total.
    """

    model_config = ConfigDict(extra="forbid")

    status: Outcome
    reasons: list[str] = Field(default_factory=list)
    lines: int = 0
    compared: int = 0
    errors_ms: list[float] = Field(default_factory=list)
    corrected_errors_ms: list[float] | None = None
    offset_ms: float | None = None
    estimated_share: float | None = None
    seconds: float = 0.0


class Summary(BaseModel):
    """The line-start errors of a song or of all songs.

    Attributes:
        count: How many line starts were compared.
        median_ms: The median absolute error, or ``None`` without a comparison.
        within_200_ms: The share of lines within 200 ms.
        within_500_ms: The share of lines within 500 ms.
    """

    model_config = ConfigDict(extra="forbid")

    count: int
    median_ms: float | None
    within_200_ms: float | None
    within_500_ms: float | None


class BenchRun(BaseModel):
    """The result of one benchmark run (``last.json``, ``baseline.json``).

    Attributes:
        schema_version: Version of this file's schema (2 adds the offset-corrected errors; files
            of version 1 stay readable).
        songs: The result per song, by file name.
        overall: The absolute errors of all songs together.
        overall_corrected: The offset-corrected errors of all songs together, or ``None`` if
            the run does not have them (version 1).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2] = 2
    songs: dict[str, SongResult]
    overall: Summary
    overall_corrected: Summary | None = None


def line_errors(found: Sequence[float | None], reference: Sequence[float | None]) -> list[float]:
    """Return the signed error in milliseconds of every line that has both a start and a time.

    Args:
        found: Where the alignment starts each line, in seconds.
        reference: The human-made line times, in seconds.

    Returns:
        Found minus reference per comparable line, in milliseconds.
    """
    return [
        (f - r) * 1000.0
        for f, r in zip(found, reference, strict=True)
        if f is not None and r is not None
    ]


def song_result(
    status: Outcome,
    reasons: Sequence[str],
    found: Sequence[float | None],
    reference: Sequence[float | None],
    estimated_share: float | None,
    seconds: float,
) -> SongResult:
    """Build the result of one song from the line starts found and the reference times."""
    signed = line_errors(found, reference)
    offset = median(signed) if signed else None
    return SongResult(
        status=status,
        reasons=list(reasons),
        lines=len(found),
        compared=len(signed),
        errors_ms=[round(abs(e), 1) for e in signed],
        corrected_errors_ms=[] if offset is None else [round(abs(e - offset), 1) for e in signed],
        offset_ms=None if offset is None else round(offset, 1),
        estimated_share=estimated_share,
        seconds=round(seconds, 1),
    )


def summarise(errors_ms: Sequence[float]) -> Summary:
    """Summarise absolute errors in milliseconds."""
    count = len(errors_ms)
    if count == 0:
        return Summary(count=0, median_ms=None, within_200_ms=None, within_500_ms=None)
    return Summary(
        count=count,
        median_ms=median(errors_ms),
        within_200_ms=sum(e <= WITHIN_NEAR_MS for e in errors_ms) / count,
        within_500_ms=sum(e <= WITHIN_FAR_MS for e in errors_ms) / count,
    )


def run_of(songs: Mapping[str, SongResult]) -> BenchRun:
    """Build a benchmark run from the results per song; the overall errors pool all songs."""
    pooled = [e for result in songs.values() for e in result.errors_ms]
    corrected: Summary | None = None
    if all(r.corrected_errors_ms is not None or not r.errors_ms for r in songs.values()):
        corrected = summarise(
            [e for r in songs.values() for e in r.corrected_errors_ms or []],
        )
    return BenchRun(songs=dict(songs), overall=summarise(pooled), overall_corrected=corrected)


def gate_median(run: BenchRun) -> float | None:
    """Return the median the gate judges: the offset-corrected one, else the absolute one."""
    corrected = run.overall_corrected
    return corrected.median_ms if corrected is not None else run.overall.median_ms


def baseline_median(baseline: BenchRun | None) -> float | None:
    """Return the baseline's offset-corrected median, or ``None`` if it has none."""
    corrected = baseline.overall_corrected if baseline is not None else None
    return corrected.median_ms if corrected is not None else None


def failures(last: BenchRun, baseline: BenchRun | None) -> list[str]:
    """Return why a run fails the benchmark; empty when it passes.

    It fails when a song failed, when the overall offset-corrected median error exceeds 200 ms,
    or when it is more than 50 ms worse than the baseline's. Without a baseline, or with one that
    has no corrected values (see ``baseline_median``), only the first two rules apply.
    """
    found = [f"{name}: the run failed" for name, r in last.songs.items() if r.status == "failed"]
    now = gate_median(last)
    what = (
        "overall median error"
        if last.overall_corrected is None
        else "overall corrected median error"
    )
    if now is None:
        return [*found, "no line start could be compared with a reference"]
    if now > LIMIT_MS:
        found.append(f"{what} {now:.0f} ms is above the {LIMIT_MS:.0f} ms limit")
    before = baseline_median(baseline)
    if before is not None and now > before + REGRESSION_MS:
        found.append(
            f"{what} {now:.0f} ms is {now - before:.0f} ms worse than "
            f"the baseline ({before:.0f} ms; allowed: {REGRESSION_MS:.0f} ms)"
        )
    return found
