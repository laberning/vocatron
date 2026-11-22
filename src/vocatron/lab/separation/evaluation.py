"""The rules of the objective evaluation of separation models (ADR-0002, ADR-0004).

Pure functions and messages for ``tools/separation_eval.py``: which material there is, how the
scores of a candidate are collected and summarised per group of songs, how an ensemble is
formed, what the MP3-against-Ogg check compares, and which candidates to propose as finalists.
Reading and writing audio and running the models are the tool's and the worker's business.
"""

import math
from collections.abc import Mapping, Sequence

from pydantic import Field

from vocatron.core.separation.job import ModelSetup
from vocatron.core.worker import Frozen, WorkerJob
from vocatron.lab.separation.metrics import MEASURES, Scores, Summary, summarise

ALL = "all"
"""The name of the group of all scored material."""
REFERENCE = "bs-roformer-ep317"
"""The model the candidates are compared with: the default of the stage A comparison (ADR-0002),
replaced as default by ``bs-roformer-leap`` in ADR-0011."""
ENSEMBLES: tuple[tuple[str, str], ...] = (
    ("mel-band-deux", "mel-band-flowersv10"),
    ("bs-roformer-ep317", "bs-roformer-leap-inst"),
)
"""The pairs whose waveform average is evaluated from the cached outputs of both members."""
FINALISTS = 3
"""How many candidates to propose."""
FULLNESS_MARGIN_DB = 0.2
"""A fuller candidate this close to the best SDR may take a finalist's place."""


class Item(Frozen):
    """One piece of material: a mixture and the true instrumental of it.

    Attributes:
        id: A short unique name; it names the cached outputs, so it carries no spaces.
        group: The group of the material (``official``, ``woodward``, ...).
        mix: The mixture file, relative to the corpus folder.
        truth: The true instrumental, relative to the corpus folder.
        source: The format of the mixture (``ogg``, ``mp3``, ``wav``), for the report.
    """

    id: str
    group: str
    mix: str
    truth: str
    source: str = ""


class Items(Frozen):
    """The ``items.json`` of a material folder.

    Attributes:
        items: The material in it.
        note: Where it comes from and under which licence.
    """

    items: tuple[Item, ...]
    note: str = ""


class EvalPair(Frozen):
    """One file for the worker to separate.

    Attributes:
        name: The item id; the output is ``<name>.wav`` in the model's folder.
        audio: The file to separate.
        output: Where the estimated instrumental goes.
    """

    name: str
    audio: str
    output: str


class EvalJob(WorkerJob):
    """What the evaluation worker is asked to do: one model, several files.

    Attributes:
        model: The model setup, as the separation worker loads it.
        pairs: The files to separate; those whose output exists are skipped.
        timings_path: Where one JSON line per finished file is appended.
    """

    model: ModelSetup
    pairs: tuple[EvalPair, ...]
    timings_path: str


class EvalResult(Frozen):
    """What the evaluation worker hands back.

    Attributes:
        seconds: How long the job took.
        peak_vram_gib: The most GPU memory used, or ``None`` on the CPU.
        done: How many files were separated (not counting skipped ones).
    """

    seconds: float
    peak_vram_gib: float | None = None
    done: int = 0


class Timing(Frozen):
    """The cost of separating one file.

    Attributes:
        name: The item id.
        audio_seconds: The length of the file.
        seconds: How long the separation took (loading the model excluded).
        peak_vram_gib: The most GPU memory used while it ran, or ``None`` on the CPU.
    """

    name: str
    audio_seconds: float
    seconds: float
    peak_vram_gib: float | None = None


class Failure(Frozen):
    """A job that did not finish.

    Attributes:
        model: The candidate.
        items: The files the job was to separate.
        kind: The error kind (``out-of-memory``, ``separation-timeout``, ...).
        message: The first line of the error message.
    """

    model: str
    items: tuple[str, ...]
    kind: str
    message: str = Field(max_length=500)


def ensemble_name(members: tuple[str, str]) -> str:
    """Return the name an ensemble of two models is reported under."""
    return "ensemble " + " + ".join(members)


def group_rows(
    scores: Mapping[str, Scores], groups: Mapping[str, str]
) -> dict[str, dict[str, Summary]]:
    """Summarise the scores of one candidate over all material and over each group.

    Args:
        scores: The scores by item id; items the candidate has none for are simply absent.
        groups: The group of every item id.

    Returns:
        ``{group: {measure: summary}}`` with ``ALL`` first, then the groups in name order.
    """
    names = [ALL, *sorted({groups[item] for item in scores if item in groups})]
    table: dict[str, dict[str, Summary]] = {}
    for name in names:
        chosen = [s for item, s in scores.items() if name == ALL or groups.get(item) == name]
        table[name] = {m: summarise([getattr(s, m) for s in chosen]) for m in MEASURES}
    return table


def timing_summary(timings: Sequence[Timing]) -> tuple[float | None, float | None]:
    """Return the separation time per second of audio and the peak GPU memory in GiB.

    Both are ``None`` without a timing; the memory is also ``None`` for timings from the CPU.
    """
    audio = sum(t.audio_seconds for t in timings)
    peaks = [t.peak_vram_gib for t in timings if t.peak_vram_gib is not None]
    speed = sum(t.seconds for t in timings) / audio if audio > 0 else None
    return speed, (max(peaks) if peaks else None)


def propose_finalists(
    means: Mapping[str, tuple[float, float]], reference: str = REFERENCE, count: int = FINALISTS
) -> list[str]:
    """Propose the candidates for the listening test.

    The ``count`` best by mean SDR, without the reference. If a candidate outside them is within
    ``FULLNESS_MARGIN_DB`` of the best SDR and fuller than every one of them, it takes the place
    of the last, since fullness is what the first listening test could not hear.

    Args:
        means: ``{candidate: (mean SDR, mean fullness)}``; ``nan`` means not measured.
        reference: The model the finalists are compared with; never proposed.
        count: How many to propose.
    """
    ranked = sorted(
        (name for name, (sdr, _) in means.items() if name != reference and not math.isnan(sdr)),
        key=lambda name: -means[name][0],
    )
    chosen = ranked[:count]
    if not chosen or len(ranked) <= count:
        return chosen
    fuller = [
        name
        for name in ranked[count:]
        if means[chosen[0]][0] - means[name][0] <= FULLNESS_MARGIN_DB
        and all(means[name][1] > means[c][1] for c in chosen)
    ]
    if fuller:
        chosen[-1] = max(fuller, key=lambda name: means[name][1])
    return chosen


def plus_minus(summary: Summary, digits: int = 2) -> str:
    """Format a summary as ``mean ± error``; ``-`` for no data, no error for a single value."""
    if summary.count == 0:
        return "-"
    if math.isnan(summary.error):
        return f"{summary.mean:.{digits}f}"
    return f"{summary.mean:.{digits}f} ± {summary.error:.{digits}f}"
