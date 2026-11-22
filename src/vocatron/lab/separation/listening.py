"""The rules of the blind listening comparison of separation variants (ADR-0002).

Pure functions and models: which hard passages of a song to loop, how the trials of a test are
made and split into sessions (every passage judged twice with swapped order, repeats in later
sessions, hidden identical pairs), how loud the clips are, how the judgements are tallied and when
a candidate may replace the current variant. Reading songs, writing clips and the page are the
tool's business (``tools/listening_test.py``, ``vocatron.lab.separation.page``).

A *system* is one variant under test, a name for a way of making the karaoke mix (a model, an
ensemble, an order of the steps). The first system is the current one, the *reference*; every
other system, the *candidate*, is compared with it in a pair of trials.
"""

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from random import Random
from statistics import mean
from typing import Literal

import numpy as np
from pydantic import Field

from vocatron.core.bench import BenchRun, SongResult, summarise
from vocatron.core.separation.rules import SAMPLE_RATE, VRAM_FRACTION, Audio, peak
from vocatron.core.worker import Frozen

EXCERPT_SECONDS = 10.0
"""The length of one looped passage (8 to 12 s)."""
HOP_SECONDS = 1.0
"""The windows are tried every second."""
PASSAGES_PER_SONG = 3
"""How many hard passages are taken from each song."""
IDENTICAL_PER_PAIR = 4
"""Hidden trials per pair in which both versions are the same, to measure guessing."""
TRIALS_PER_SESSION = 36
"""A session of about 25 minutes."""
MIN_SYSTEMS = 2
"""The reference and one candidate."""
HALF = 0.5
"""A fair coin."""
CRITERIA: tuple[str, ...] = ("lead", "artefacts", "damage", "backing")
"""What the listener compares besides the overall preference: lead-voice leftovers, artefacts,
instrument damage or dullness, backing vocals kept."""
WINS_NEEDED = 20
WINS_OF = 30
"""A candidate must be preferred in at least this share of its judgements: 20 of 30."""
MAX_CONSISTENT_LOSSES = 0
"""The reference may win both judgements of this many passages at most: never clearly worse."""
CLIP_CEILING = 0.98
"""The loudest clip of a passage may not exceed this peak after levelling."""
KEY_VERSION = 2
ORDERS = 2
"""Every passage is judged in both orders."""
ORIGINAL = "original"
"""The name of the reference button's audio: the song itself."""

Choice = Literal["A", "B", "tie"]
Side = Literal["A", "B", "same"]


class Window(Frozen):
    """A stretch of a song.

    Attributes:
        start: Where it starts, in seconds.
        seconds: How long it is.
    """

    start: float
    seconds: float


def densest_windows(
    lead: Audio, count: int, length: int, hop: int, fixed: Sequence[int] = ()
) -> list[int]:
    """Return the starts (samples) of the ``count`` loudest non-overlapping windows of the lead.

    Windows of ``length`` samples are tried every ``hop`` samples; the loudest wins, then the
    loudest that does not overlap an earlier one, and so on (the earliest of equally loud ones
    first). The ``fixed`` starts are taken first and count towards ``count``. Fewer windows come
    back when the song has no room for more.
    """
    samples = lead.shape[1]
    power = np.sum(lead.astype(np.float64) ** 2, axis=0)
    total = np.concatenate(([0.0], np.cumsum(power)))
    starts = np.arange(0, max(samples - length, 0) + 1, hop)
    energy = total[np.minimum(starts + length, samples)] - total[starts]
    taken = [s for s in fixed if 0 <= s <= max(samples - length, 0)]
    free = np.ones(len(starts), dtype=bool)
    for chosen in taken:
        free &= np.abs(starts - chosen) >= length
    while len(taken) < count and free.any():
        best = int(np.argmax(np.where(free, energy, -np.inf)))
        taken.append(int(starts[best]))
        free &= np.abs(starts - starts[best]) >= length
    return sorted(taken[: max(count, len(fixed))])


def plan_passages(
    lead: Audio,
    sample_rate: int = SAMPLE_RATE,
    seconds: float = EXCERPT_SECONDS,
    count: int = PASSAGES_PER_SONG,
    extra_starts: Sequence[float] = (),
) -> list[Window]:
    """Choose the hard passages of a song: where the lead voice is densest, plus chosen times.

    Args:
        lead: The lead-vocal stem of the reference system.
        sample_rate: Its sample rate.
        seconds: The length of a passage.
        count: How many passages to take in all (chosen ones included).
        extra_starts: Starts in seconds that must be among the passages.

    Raises:
        ValueError: If the stem has no audio.
    """
    if lead.shape[1] == 0:
        raise ValueError("the lead-vocal stem holds no audio")
    length = min(int(seconds * sample_rate), lead.shape[1])
    hop = max(int(HOP_SECONDS * sample_rate), 1)
    fixed = [int(s * sample_rate) for s in extra_starts]
    starts = densest_windows(lead, count, length, hop, fixed)
    return [Window(start=s / sample_rate, seconds=length / sample_rate) for s in starts]


class Passage(Frozen):
    """One passage that is looped.

    Attributes:
        id: ``p01``, ``p02``, ... in the order of the song list.
        song: The song's name.
        window: Where the passage lies in the song.
    """

    id: str
    song: str
    window: Window


class Clip(Frozen):
    """One audio file of the page: a system's version of a passage, or the original.

    Attributes:
        id: An opaque id (``c001``); it tells nothing about the system.
        passage: The passage id.
        system: The system it was made with, or ``original``.
    """

    id: str
    passage: str
    system: str


class Trial(Frozen):
    """One judgement the listener makes: A or B, with the original as reference.

    Attributes:
        id: ``t001``, ``t002``, ... in the order of the page.
        session: The session (from 1) the trial belongs to.
        passage: The passage id.
        candidate: The candidate system of the pair.
        a: The clip behind button A.
        b: The clip behind button B.
        original: The clip of the original song.
        identical: Whether A and B are the same version (a hidden check).
        repeat: Whether this is the second judgement of this passage and pair (A and B swapped).
    """

    id: str
    session: int
    passage: str
    candidate: str
    a: str
    b: str
    original: str
    identical: bool = False
    repeat: bool = False


class ListeningKey(Frozen):
    """The secret of a listening test: which system is behind which clip.

    Attributes:
        schema_version: Version of this file's layout.
        seed: The seed of the random order.
        systems: The systems; the first is the reference.
        passages: The looped passages.
        clips: Every audio file of the page.
        trials: The trials in page order.
        sessions: How many sessions the trials are split into.
    """

    schema_version: int = KEY_VERSION
    seed: int
    systems: tuple[str, ...]
    passages: tuple[Passage, ...]
    clips: tuple[Clip, ...]
    trials: tuple[Trial, ...]
    sessions: int

    @property
    def reference(self) -> str:
        """The current system, against which every other is judged."""
        return self.systems[0]

    def system_of(self, clip: str) -> str:
        """Return the system behind a clip id.

        Raises:
            KeyError: If the id is unknown.
        """
        for item in self.clips:
            if item.id == clip:
                return item.system
        raise KeyError(clip)


@dataclass(frozen=True)
class _Slot:
    """A trial before it has an id: which clips play behind A and B."""

    passage: str
    candidate: str
    a: str
    b: str
    identical: bool = False
    repeat: bool = False


def make_key(
    passages: Sequence[Passage], systems: Sequence[str], seed: int, per_session: int
) -> ListeningKey:
    """Make the clips and trials of a test.

    Every candidate is judged twice on every passage, once in each order; the second judgements
    (swapped) come after all first judgements, so they fall in later sessions. Each pair also
    gets ``IDENTICAL_PER_PAIR`` hidden trials in which both buttons play the reference's version
    (as two separate clips). Within the two halves the order is random, and the clip ids are
    numbered at random, so that neither the order nor an id tells which system plays.

    Args:
        passages: The passages of all songs.
        systems: The systems; the first is the reference.
        seed: The seed of the random order; the same seed gives the same test.
        per_session: How many trials a session holds at most.

    Raises:
        ValueError: If the systems are not distinct and at least two, there is no passage, or
            ``per_session`` is below 1.
    """
    if (
        len(systems) < MIN_SYSTEMS
        or len(set(systems)) != len(systems)
        or ORIGINAL in systems
        or not passages
        or per_session < 1
    ):
        raise ValueError("a test needs distinct systems (at least two), passages and sessions")
    rng = Random(seed)
    clips: list[Clip] = []

    def new_clip(passage: str, system: str) -> str:
        clips.append(Clip(id=f"c{len(clips) + 1:03d}", passage=passage, system=system))
        return clips[-1].id

    base = {(p.id, s): new_clip(p.id, s) for p in passages for s in (ORIGINAL, *systems)}
    firsts: list[_Slot] = []
    seconds: list[_Slot] = []
    reference = systems[0]
    for candidate in systems[1:]:
        for passage in passages:
            ref, cand = base[passage.id, reference], base[passage.id, candidate]
            a, b = (cand, ref) if rng.random() < HALF else (ref, cand)
            firsts.append(_Slot(passage.id, candidate, a, b))
            seconds.append(_Slot(passage.id, candidate, b, a, repeat=True))
        for passage in rng.sample(list(passages), min(IDENTICAL_PER_PAIR, len(passages))):
            twin = new_clip(passage.id, reference)
            slot = _Slot(passage.id, candidate, base[passage.id, reference], twin, identical=True)
            (firsts if rng.random() < HALF else seconds).append(slot)
    rng.shuffle(firsts)
    rng.shuffle(seconds)
    # the clips were numbered in a fixed pattern (original, reference, candidates per passage);
    # a random renumbering makes the ids opaque, so no id gives a system away
    numbers = [clip.id for clip in clips]
    rng.shuffle(numbers)
    opaque = dict(zip((clip.id for clip in clips), numbers, strict=True))
    trials = tuple(
        Trial(
            id=f"t{number:03d}",
            session=(number - 1) // per_session + 1,
            passage=slot.passage,
            candidate=slot.candidate,
            a=opaque[slot.a],
            b=opaque[slot.b],
            original=opaque[base[slot.passage, ORIGINAL]],
            identical=slot.identical,
            repeat=slot.repeat,
        )
        for number, slot in enumerate(firsts + seconds, start=1)
    )
    renamed = sorted(
        (clip.model_copy(update={"id": opaque[clip.id]}) for clip in clips),
        key=lambda clip: clip.id,
    )
    return ListeningKey(
        seed=seed,
        systems=tuple(systems),
        passages=tuple(passages),
        clips=tuple(renamed),
        trials=trials,
        sessions=trials[-1].session,
    )


def match_levels(clips: Sequence[Audio]) -> list[Audio]:
    """Give the clips of one passage the same loudness, so that louder does not sound better.

    Every clip is scaled to the mean RMS of the group; if that would push the loudest clip over
    ``CLIP_CEILING``, all are scaled down by one common factor. Silent clips stay as they are.
    """
    levels = [float(np.sqrt(np.mean(clip.astype(np.float64) ** 2))) for clip in clips]
    audible = [level for level in levels if level > 0]
    if not audible:
        return list(clips)
    target = mean(audible)
    scaled = [
        (clip * np.float32(target / level)).astype(np.float32) if level > 0 else clip
        for clip, level in zip(clips, levels, strict=True)
    ]
    top = max(peak(clip) for clip in scaled)
    if top > CLIP_CEILING:
        scaled = [(clip * np.float32(CLIP_CEILING / top)).astype(np.float32) for clip in scaled]
    return scaled


class Judgement(Frozen):
    """The listener's verdict on one trial.

    Attributes:
        trial: The trial id (``t012``).
        preference: ``A`` or ``B`` is better overall, or ``tie`` (cannot tell).
        criteria: Per criterion which button is better, or ``same``; criteria not filled in are
            left out.
    """

    trial: str
    preference: Choice
    criteria: dict[str, Side] = Field(default_factory=dict)


class Results(Frozen):
    """What the listening page saves: one judgement per trial judged so far."""

    judgements: tuple[Judgement, ...]


def merge_results(parts: Sequence[Results]) -> Results:
    """Join the results of several sessions; a trial judged twice keeps its later judgement."""
    latest: dict[str, Judgement] = {}
    for part in parts:
        for item in part.judgements:
            latest[item.trial] = item
    return Results(judgements=tuple(latest.values()))


def judgements_by_trial(key: ListeningKey, results: Results) -> dict[str, Judgement]:
    """Return the judgement of every trial.

    Raises:
        ValueError: If a trial is judged twice or unknown, a criterion is unknown, or trials are
            not judged yet (the message names how many).
    """
    known = {trial.id for trial in key.trials}
    table: dict[str, Judgement] = {}
    for item in results.judgements:
        if item.trial not in known:
            raise ValueError(f"unknown trial {item.trial}")
        if item.trial in table:
            raise ValueError(f"trial {item.trial} is judged twice")
        if unknown := sorted(set(item.criteria) - set(CRITERIA)):
            raise ValueError(f"unknown criterion {unknown[0]} in trial {item.trial}")
        table[item.trial] = item
    if missing := sorted(known - table.keys()):
        raise ValueError(
            f"{len(missing)} of {len(known)} trials are not judged (first: {missing[0]})"
        )
    return table


def sign_test_p(wins: int, losses: int) -> float:
    """Return the one-sided p-value that ``wins`` or more of ``wins + losses`` are by chance.

    The sign test with a fair coin; ties are left out by the caller.
    """
    n = wins + losses
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / 2**n


@dataclass(frozen=True)
class PairTally:
    """How a candidate fared against the reference.

    Attributes:
        candidate: The candidate system.
        judged: The judgements of the pair, hidden identical trials left out.
        wins: Trials in which the candidate was preferred.
        losses: Trials in which the reference was preferred.
        ties: Trials in which the listener could not tell.
        p_value: The sign test's one-sided p-value for the candidate being better.
        consistent_wins: Passages the candidate won in both orders.
        consistent_losses: Passages the reference won in both orders.
        flips: Passages where the two orders gave different winners (a win and a loss).
        passages: The passages judged twice.
        identical: Hidden identical trials judged.
        identical_tied: Of them, how many were judged "cannot tell".
        criteria: Per criterion ``(candidate better, reference better, same)`` counts.
    """

    candidate: str
    judged: int
    wins: int
    losses: int
    ties: int
    p_value: float
    consistent_wins: int
    consistent_losses: int
    flips: int
    passages: int
    identical: int
    identical_tied: int
    criteria: Mapping[str, tuple[int, int, int]]


def tally(key: ListeningKey, table: Mapping[str, Judgement], candidate: str) -> PairTally:
    """Count the judgements of one candidate against the reference.

    Args:
        key: The secret.
        table: The judgement of every trial (``judgements_by_trial``).
        candidate: The candidate system.
    """
    wins = losses = ties = identical = identical_tied = 0
    by_passage: dict[str, list[str]] = defaultdict(list)
    criteria = {name: [0, 0, 0] for name in CRITERIA}
    for trial in key.trials:
        if trial.candidate != candidate:
            continue
        item = table[trial.id]
        if trial.identical:
            identical += 1
            identical_tied += item.preference == "tie"
            continue
        picked = {"A": trial.a, "B": trial.b}.get(item.preference)
        system = key.system_of(picked) if picked is not None else None
        outcome = "tie" if system is None else ("win" if system == candidate else "loss")
        wins, losses, ties = (
            wins + (outcome == "win"),
            losses + (outcome == "loss"),
            ties + (outcome == "tie"),
        )
        by_passage[trial.passage].append(outcome)
        for name, side in item.criteria.items():
            if side == "same":
                criteria[name][2] += 1
                continue
            better = key.system_of(trial.a if side == "A" else trial.b)
            criteria[name][0 if better == candidate else 1] += 1
    both = [outcomes for outcomes in by_passage.values() if len(outcomes) == ORDERS]
    return PairTally(
        candidate=candidate,
        judged=wins + losses + ties,
        wins=wins,
        losses=losses,
        ties=ties,
        p_value=sign_test_p(wins, losses),
        consistent_wins=sum(o == ["win", "win"] for o in both),
        consistent_losses=sum(o == ["loss", "loss"] for o in both),
        flips=sum(sorted(o) == ["loss", "win"] for o in both),
        passages=len(both),
        identical=identical,
        identical_tied=identical_tied,
        criteria={name: (c[0], c[1], c[2]) for name, c in criteria.items()},
    )


def song_errors(candidate: SongResult, reference: SongResult) -> tuple[list[float], list[float]]:
    """Return the line-start errors of a song in both runs (offset-corrected if both have them)."""
    if candidate.corrected_errors_ms is not None and reference.corrected_errors_ms is not None:
        return candidate.corrected_errors_ms, reference.corrected_errors_ms
    return candidate.errors_ms, reference.errors_ms


def common_medians(candidate: BenchRun, reference: BenchRun) -> tuple[float | None, float | None]:
    """Return the overall median line-start errors of two benchmark runs on their common songs.

    Only songs that were compared in both runs count, so that a song one run could not measure
    does not decide between the variants. Where both runs have the offset-corrected errors of a
    song (as the benchmark gate judges), those are compared, else the absolute ones.

    Returns:
        The candidate's and the reference's median in milliseconds (``None`` without a song).
    """
    own: list[float] = []
    base: list[float] = []
    for name, result in candidate.songs.items():
        other = reference.songs.get(name)
        if not result.errors_ms or other is None or not other.errors_ms:
            continue
        mine, theirs = song_errors(result, other)
        own.extend(mine)
        base.extend(theirs)
    return summarise(own).median_ms, summarise(base).median_ms


@dataclass(frozen=True)
class Check:
    """One condition of the decision rule.

    Attributes:
        name: What is checked.
        ok: Whether it holds.
        detail: The numbers behind it.
    """

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class Verdict:
    """Whether a candidate may become the default.

    Attributes:
        checks: Every condition with its outcome.
    """

    checks: tuple[Check, ...]

    @property
    def passes(self) -> bool:
        """Whether all conditions hold."""
        return all(check.ok for check in self.checks)


def wins_needed(judged: int) -> int:
    """Return how many wins of ``judged`` judgements the rule asks for: 20 of 30, in proportion."""
    return max(-(-judged * WINS_NEEDED // WINS_OF), 1)


def decide(
    result: PairTally,
    *,
    sync_median_ms: float | None,
    reference_sync_median_ms: float | None,
    peak_vram_gib: float | None,
    gpu_gib: float,
) -> Verdict:
    """Apply the decision rule to a candidate.

    The candidate may replace the reference only if it is preferred in at least 20 of 30
    judgements (in proportion for other counts; ties do not count as preferred), is never clearly
    worse (no passage on which the reference won both orders, ``MAX_CONSISTENT_LOSSES``), does not
    make the sync benchmark worse (overall median error, offset-corrected where measured, not above
    the reference's), and fits the GPU within the 75 % cap (``VRAM_FRACTION``). A number that is
    missing fails its condition.

    Args:
        result: The tally of the candidate against the reference.
        sync_median_ms: The candidate's overall median line-start error in the benchmark.
        reference_sync_median_ms: The reference's.
        peak_vram_gib: The candidate's peak GPU memory in GiB.
        gpu_gib: The GPU's memory in GiB.
    """
    needed = wins_needed(result.judged)
    sync_ok = (
        sync_median_ms is not None
        and reference_sync_median_ms is not None
        and sync_median_ms <= reference_sync_median_ms
    )
    vram_ok = peak_vram_gib is not None and peak_vram_gib <= VRAM_FRACTION * gpu_gib
    return Verdict(
        (
            Check(
                f"preferred in at least {WINS_NEEDED} of {WINS_OF} judgements",
                result.judged > 0 and result.wins >= needed,
                f"{result.wins} of {result.judged} (needs {needed}); "
                f"sign test p {result.p_value:.3f}",
            ),
            Check(
                "never clearly worse",
                result.consistent_losses <= MAX_CONSISTENT_LOSSES,
                f"the reference won both orders on {result.consistent_losses} passage(s)",
            ),
            Check(
                "sync benchmark not worse",
                sync_ok,
                f"median {sync_median_ms} ms against {reference_sync_median_ms} ms",
            ),
            Check(
                f"fits the GPU within the {round(VRAM_FRACTION * 100)} % cap",
                vram_ok,
                f"peak {peak_vram_gib} GiB of {VRAM_FRACTION * gpu_gib:.1f} GiB",
            ),
        )
    )
