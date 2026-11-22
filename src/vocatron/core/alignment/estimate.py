"""Confidence per word, and times for the words that could not be measured (ADR-0002).

A word is as certain as the model was about its letters: the mean over its letters of the
highest probability the path gives that letter. A word below the threshold, and a word with no
sound at all, is estimated. Without knowing where the voice sounds, it takes the time between the
words around it, shared in proportion to the number of its letters. With the voice (ADR-0012) it
is placed where the voice starts inside that gap, with a length from the song's own measured
seconds per letter, and never leaves the gap; a measured word of moderate confidence that lies in
silence is estimated instead. Estimated words are counted and reported.

ADR-0021 refines the placement when the voice is in use and the words' lines are known: an
estimated word keeps the position the model found for it when the voice supports it (it is
kept), and a run of estimated words never crosses a line break.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from statistics import median

import numpy as np

from vocatron.core.alignment.ctc import CtcPath, Spans
from vocatron.core.alignment.tokens import Transcript
from vocatron.core.alignment.voice import CONFIDENT_WORD, VoiceActivity

MIN_CONFIDENCE = 0.1
"""A word below this confidence is estimated from its neighbours."""
LETTER_SECONDS = 0.08
"""How long a letter lasts when there is nothing to measure it by (the edges of a song)."""
MIN_LETTER_SECONDS = 0.03
"""The least seconds per letter taken from a song's measured words (they take 0.035 to 0.077)."""
MAX_LETTER_SECONDS = 0.12
"""The most seconds per letter taken from a song's measured words."""
EDGE_REACH_SECONDS = 3.0
"""How far from its only neighbour a voice start is looked for at the edges of a song, so a sound
in the intro or the outro does not pull the first or the last word away."""
HELD_TAIL_SECONDS = 0.5
"""A voice still sounding at the previous word's end that stops within this time is the held end
of that word, not the start of the next, when another voice start follows in the gap."""
MIN_FILL_SHARE = 0.5
"""The voiced time in a gap must be at least this share of the time the run needs, else the run
is not placed on the voice."""
SILENT_CONFIDENCE = 0.5
"""A measured word below this confidence can be judged to lie in silence."""
SILENT_SHARE = 0.2
"""A word with less than this voiced share lies in silence."""
MIN_JUDGED_SECONDS = 0.1
"""A measured word shorter than this is not judged for silence."""
KEEP_VOICED_SHARE = 0.5
"""An unsure word keeps the model's position when at least this share of its span is voiced. The
model finds short words in the right place with a confidence under ``MIN_CONFIDENCE``; half the
span is the same bar as ``MIN_FILL_SHARE`` asks of a run."""
KEEP_NEXT_SECONDS = 0.3
"""An unsure word keeps the model's position when it ends at most this long before the next word
of its line that is kept by confidence. The model places such words 0.14 to 0.20 s before the next
word (measured on 17 songs); 0.3 s leaves room for the pause without reaching a word further on."""
KEEP_DIRECT_SECONDS = 0.1
"""A line's first word that the model starts at most this long after the previous word's end
follows that word directly, so the voice that still sounds at its start is its own note, not the
held note of the line before. Lifted for this case, the held-note rule no longer pushed a sung
vocalise 5 s late; the 20 words it moved on 17 songs and the demo sounded better by ear."""


@dataclass(frozen=True)
class Timed:
    """The time of one word.

    Attributes:
        start: Seconds from the start of the audio.
        end: Seconds from the start of the audio.
        confidence: 0 to 1; 0 for a word with no sound.
        estimated: The time is interpolated, not measured.
        letters: Start and end of every letter of a measured word; empty when estimated.
    """

    start: float
    end: float
    confidence: float
    estimated: bool
    letters: tuple[tuple[float, float], ...] = ()


def measure(
    transcript: Transcript, path: CtcPath, spans: Spans, seconds_per_frame: float
) -> list[Timed | None]:
    """Read the time and confidence of every word off the path.

    Args:
        transcript: The words and their targets.
        path: The best path.
        spans: The frames of every target.
        seconds_per_frame: The length of a frame.

    Returns:
        One entry per word; ``None`` for a word with no sound.
    """
    posterior = np.exp(path.scores)
    peaks = [
        float(posterior[a : b + 1].max()) for a, b in zip(spans.first, spans.last, strict=True)
    ]
    out: list[Timed | None] = []
    for slot in transcript.slots:
        if slot is None:
            out.append(None)
            continue
        first, last = slot
        letters = tuple(
            (
                float(spans.first[i]) * seconds_per_frame,
                float(spans.last[i] + 1) * seconds_per_frame,
            )
            for i in range(first, last + 1)
        )
        out.append(
            Timed(
                letters[0][0],
                letters[-1][1],
                float(np.mean(peaks[first : last + 1])),
                False,
                letters,
            )
        )
    return out


@dataclass(frozen=True)
class Settled:
    """The words of a song after the estimation.

    Attributes:
        words: One ``Timed`` per word, in order, without overlaps.
        placed: How many estimated words were placed on the voice.
        re_estimated: How many measured words in silence were estimated instead.
        kept: How many unsure words kept the model's position (ADR-0021).
    """

    words: list[Timed]
    placed: int = 0
    re_estimated: int = 0
    kept: int = 0


def confident_spans(measured: Sequence[Timed | None]) -> list[tuple[float, float]]:
    """Return start and end of the confidently measured words (they tell the song's levels)."""
    return [(m.start, m.end) for m in measured if m is not None and m.confidence >= CONFIDENT_WORD]


def letter_seconds(measured: Sequence[Timed | None]) -> float:
    """Return the song's seconds per letter: the median over its confident words, clamped.

    Falls back to ``LETTER_SECONDS`` without a confident word.
    """
    rates = [
        (m.end - m.start) / len(m.letters)
        for m in measured
        if m is not None and m.confidence >= CONFIDENT_WORD and m.letters
    ]
    if not rates:
        return LETTER_SECONDS
    return min(max(median(rates), MIN_LETTER_SECONDS), MAX_LETTER_SECONDS)


def _silent(
    measured: Sequence[Timed | None], threshold: float, voice: VoiceActivity
) -> frozenset[int]:
    """Return the measured words of moderate confidence that lie in silence.

    Only words that would be kept are judged: at least ``threshold`` and under
    ``SILENT_CONFIDENCE`` confident, at least ``MIN_JUDGED_SECONDS`` long and voiced for less
    than ``SILENT_SHARE`` of their time.
    """
    return frozenset(
        i
        for i, m in enumerate(measured)
        if m is not None
        and threshold <= m.confidence < SILENT_CONFIDENCE
        and m.end - m.start >= MIN_JUDGED_SECONDS
        and voice.voiced_fraction(m.start, m.end) < SILENT_SHARE
    )


def settle(
    measured: Sequence[Timed | None],
    weights: Sequence[int],
    duration: float,
    threshold: float = MIN_CONFIDENCE,
    voice: VoiceActivity | None = None,
    lines: Sequence[int] | None = None,
) -> Settled:
    """Give every word a time: keep the confident ones, estimate the rest.

    With the voice, a measured word in silence (``_silent``) is estimated instead, but only if the
    voice places its run; otherwise it keeps its measured time, as without the voice.

    With the voice and the ``lines`` of the words (ADR-0021), an unsure word keeps the model's
    position when the voice supports it (``_kept``), and a run of estimated words stays inside
    its line (``_runs``): a run that starts a line is placed backwards from the next word, a run
    that ends a line reaches forward from its last word.

    Args:
        measured: The measured words (``None`` for a word with no sound).
        weights: The number of letters of each word; an estimated run shares its time by them.
        duration: The length of the audio, the end of the last run.
        threshold: The confidence below which a measured word is estimated.
        voice: Where the voice sounds; ``None`` places runs between their neighbours.
        lines: The line of every word; ``None`` lets runs cross line breaks and keeps no unsure
            word, as without the voice.

    Returns:
        The words in order, without overlaps, and how many the voice placed, re-estimated or kept.
    """
    demoted = frozenset[int]() if voice is None else _silent(measured, threshold, voice)
    while True:
        song = _Song(measured, weights, duration, voice, 0.0, lines)
        settled, unplaced = _settle(song, threshold, demoted)
        back = demoted & unplaced
        if not back:  # every re-estimated word was placed by the voice
            return settled
        demoted -= back


def _settle(
    song: _Song, threshold: float, demoted: frozenset[int]
) -> tuple[Settled, frozenset[int]]:
    """Settle the words of ``song`` with the ``demoted`` ones estimated.

    Returns:
        The words and the indices of the estimated words that the voice did not place.
    """
    measured, voice, lines = song.measured, song.voice, song.lines
    keep = [
        m is not None and i not in demoted and m.confidence >= threshold
        for i, m in enumerate(measured)
    ]
    out: list[Timed | None] = [m if k else None for m, k in zip(measured, keep, strict=True)]
    per_letter = letter_seconds([m for m, k in zip(measured, keep, strict=True) if k])
    song = replace(song, per_letter=per_letter)
    kept = 0
    if voice is not None and lines is not None:
        for index in _kept(measured, keep, demoted, voice, lines):
            out[index] = _keep_end(out, song, index)
            kept += 1
    placed = 0
    unplaced: set[int] = set()
    for first, stop in reversed(_runs(out, lines if voice is not None else None)):
        if _fill(out, song, first, stop):
            placed += stop - first
        else:
            unplaced.update(range(first, stop))
    words = [t for t in out if t is not None]
    return Settled(words, placed, len(demoted), kept), frozenset(unplaced)


def _kept(
    measured: Sequence[Timed | None],
    keep: Sequence[bool],
    demoted: frozenset[int],
    voice: VoiceActivity,
    lines: Sequence[int],
) -> list[int]:
    """Return the unsure words that keep the model's position (ADR-0021).

    A word kept by confidence is never among them, nor a word in ``demoted`` (the silence
    re-estimates). It is kept when at least ``KEEP_VOICED_SHARE`` of its span is voiced, or when
    it ends at most ``KEEP_NEXT_SECONDS`` before the next word, if that is of its line and kept by
    confidence (``keep``, so a kept word is never the anchor of another). A line's first word
    counts as voiced only if the voice at its start began after the previous word's end, or if it
    starts at most ``KEEP_DIRECT_SECONDS`` after that end; otherwise the held note of the line
    before does not count.
    """
    chosen: list[int] = []
    for i, m in enumerate(measured):
        if m is None or keep[i] or i in demoted:
            continue
        follower = measured[i + 1] if i + 1 < len(measured) else None
        near = (
            follower is not None
            and keep[i + 1]
            and lines[i + 1] == lines[i]
            and 0.0 <= follower.start - m.end <= KEEP_NEXT_SECONDS
        )
        first_of_line = i == 0 or lines[i - 1] != lines[i]
        previous_end = _previous_end(measured, i) if first_of_line else None
        direct = previous_end is not None and 0.0 <= m.start - previous_end <= KEEP_DIRECT_SECONDS
        voiced = voice.voiced_fraction(m.start, m.end) >= KEEP_VOICED_SHARE and (
            previous_end is None or direct or not _held_over(voice, m.start, previous_end)
        )
        if voiced or near:
            chosen.append(i)
    return chosen


def _previous_end(measured: Sequence[Timed | None], index: int) -> float:
    """Return the model's end of the nearest word before ``index`` that has one (0 without)."""
    for found in reversed(measured[:index]):
        if found is not None:
            return found.end
    return 0.0


def _held_over(voice: VoiceActivity, start: float, previous_end: float) -> bool:
    """Return whether the voice sounding at ``start`` began before ``previous_end``."""
    return any(a < previous_end - 1e-6 and a <= start < b for a, b in voice.spans)


def _keep_end(out: Sequence[Timed | None], song: _Song, index: int) -> Timed:
    """Return the kept word ``index``, estimated, at the model's start.

    It ends at the later of the model's end and its letters times the song's seconds per letter,
    but never after the next word's start.
    """
    found = song.measured[index]
    assert found is not None  # only words with a model position are kept
    limit = song.duration
    for k in range(index + 1, len(out)):
        follower = out[k] or song.measured[k]
        if follower is not None:
            limit = follower.start
            break
    wanted = found.start + max(song.weights[index], 1) * song.per_letter
    return Timed(found.start, max(found.end, min(wanted, limit)), found.confidence, True)


def _runs(out: Sequence[Timed | None], lines: Sequence[int] | None) -> list[tuple[int, int]]:
    """Return the runs of unplaced words as ``(first, stop)``; with ``lines`` none spans two."""
    runs: list[tuple[int, int]] = []
    first = None
    for i, placed in enumerate(out):
        if placed is None and first is not None and lines is not None and lines[i] != lines[first]:
            runs.append((first, i))
            first = None
        if placed is None and first is None:
            first = i
        elif placed is not None and first is not None:
            runs.append((first, i))
            first = None
    if first is not None:
        runs.append((first, len(out)))
    return runs


def _gap(
    out: Sequence[Timed | None], first: int, stop: int, duration: float
) -> tuple[float, float, bool] | None:
    """Return the gap of the run ``first`` to ``stop - 1``: its start, its end and whether it leads.

    A leading run has no neighbour before it (the start of the song). At the edges the gap
    reaches ``EDGE_REACH_SECONDS`` from the only neighbour. ``None`` without any neighbour.
    """
    before, after = _gap_ends(out, first, stop)
    if before is not None and after is not None:
        return before.end, max(after.start, before.end), False
    if after is not None:
        return max(after.start - EDGE_REACH_SECONDS, 0.0), after.start, True
    if before is not None:
        return before.end, max(min(before.end + EDGE_REACH_SECONDS, duration), before.end), False
    return None


def _first_start(pieces: Sequence[tuple[float, float, bool]], low: float) -> float | None:
    """Return where a run starts: the first voice start in the gap, or its beginning if voiced.

    A voice that sounds from the start of the gap (the previous word's held note) and stops
    within ``HELD_TAIL_SECONDS`` is that word's tail when another voice start follows.
    """
    if not pieces:
        return None
    begin, end, onset = pieces[0]
    if onset:
        return begin
    if len(pieces) > 1 and end - low < HELD_TAIL_SECONDS:
        return pieces[1][0]
    return low


def _snap(pieces: Sequence[tuple[float, float, bool]], cursor: float) -> float:
    """Return ``cursor``, or the next voice start if the voice is silent at ``cursor``."""
    for begin, end, _ in pieces:
        if cursor < end - 1e-6:  # a word that ends with a stretch of voice does not start in it
            return max(cursor, begin)
    return cursor


def on_voice(
    voice: VoiceActivity, lengths: Sequence[float], low: float, high: float, leading: bool
) -> list[tuple[float, float]] | None:
    """Place a run of words of the given lengths on the voice inside the gap ``[low, high]``.

    Returns:
        Start and end of every word, in order and inside the gap, or ``None`` when the gap has no
        usable voice start or too little voiced time for the run.
    """
    pieces = [(max(a, low), min(b, high), a >= low) for a, b in voice.spans if b > low and a < high]
    need = sum(lengths)
    if leading:  # the voice start nearest to the neighbour that leaves room
        starts = [begin for begin, _, onset in pieces if onset and begin <= high - need]
        start = starts[-1] if starts else None
    else:
        start = _first_start(pieces, low)
    if start is None:  # a start at the gap's end finds no voiced time below
        return None
    voiced = sum(max(end - max(begin, start), 0.0) for begin, end, _ in pieces)
    if voiced < MIN_FILL_SHARE * need:
        return None
    cursor = start
    spans: list[tuple[float, float]] = []
    for length in lengths:
        cursor = _snap(pieces, cursor)
        spans.append((cursor, cursor + length))
        cursor += length
    overshoot = spans[-1][1] - start
    if start + overshoot > high:  # compress into the gap
        scale = (high - start) / overshoot
        spans = [(start + (a - start) * scale, start + (b - start) * scale) for a, b in spans]
    return spans


@dataclass(frozen=True)
class _Song:
    """What the estimation of a run needs to know about the song."""

    measured: Sequence[Timed | None]
    weights: Sequence[int]
    duration: float
    voice: VoiceActivity | None
    per_letter: float
    lines: Sequence[int] | None = None


def _fill(out: list[Timed | None], song: _Song, first: int, stop: int) -> bool:
    """Estimate the run of words ``first`` to ``stop - 1`` between its kept neighbours.

    With the voice and the words' lines the run lies in its line (``_line_window``); runs are
    filled right to left, so the word after a run is placed, or measured or kept.

    Returns:
        Whether the voice placed the run (else it is shared between its neighbours).
    """
    run = [max(song.weights[i], 1) for i in range(first, stop)]
    wish = sum(run) * LETTER_SECONDS
    spans = None
    bounds: tuple[float, float] | None = None
    if song.voice is not None:
        window = None
        if song.lines is not None:
            window = _line_window(out, song.lines, first, stop, song.duration, wish)
        if window is not None:
            gap, bounds = window
        else:
            gap = _gap(out, first, stop, song.duration)
        if gap is not None:
            spans = on_voice(song.voice, [n * song.per_letter for n in run], *gap)
    placed = spans is not None
    if spans is None:
        if bounds is None:
            bounds = _bounds(out, first, stop, song.duration, wish)
        spans = share(bounds, run)
    for offset, (begin, end) in enumerate(spans):
        found = song.measured[first + offset]
        out[first + offset] = Timed(begin, end, found.confidence if found else 0.0, True)
    return placed


def _line_window(
    out: Sequence[Timed | None],
    lines: Sequence[int],
    first: int,
    stop: int,
    duration: float,
    wish: float,
) -> tuple[tuple[float, float, bool], tuple[float, float]] | None:
    """Return the gap for the voice and the span to share for a run that keeps to its line.

    A run that starts its line (or is a whole line) with a placed word after it is placed
    backwards from that word, above the end of the word before it (``leading``). A run that ends
    its line reaches forward from its last word, to the next placed word but at most
    ``EDGE_REACH_SECONDS``; so does a whole last line, from the word before it. A run inside a
    line lies between its neighbours, as ever. ``None`` for a run inside a line or without any
    neighbour (the song's whole lyrics); the caller then takes the earlier gap.
    """
    starts = first == 0 or lines[first - 1] != lines[first]
    ends = stop == len(out) or lines[stop] != lines[stop - 1]
    before = next((t for t in reversed(out[:first]) if t is not None), None)
    after = next((t for t in out[stop:] if t is not None), None)
    if starts and after is not None:
        low = before.end if before is not None else max(after.start - EDGE_REACH_SECONDS, 0.0)
        high = max(after.start, low)
        return (low, high, True), (max(low, high - wish), high)
    if ends and before is not None and (not starts or after is None):
        cap = after.start if after is not None else duration
        high = max(min(before.end + EDGE_REACH_SECONDS, cap), before.end)
        return (before.end, high, False), (before.end, min(high, before.end + wish))
    return None


def _gap_ends(
    out: Sequence[Timed | None], first: int, stop: int
) -> tuple[Timed | None, Timed | None]:
    """Return the placed words directly before and after the run ``first`` to ``stop - 1``."""
    after = out[stop] if stop < len(out) else None
    before = out[first - 1] if first > 0 else None
    return before, after


def _bounds(
    out: Sequence[Timed | None], first: int, stop: int, duration: float, wish: float
) -> tuple[float, float]:
    """Return the span a run shares between its neighbours; at the edges ``wish`` seconds long."""
    before, after = _gap_ends(out, first, stop)
    if before is not None and after is not None:
        low, high = before.end, after.start
    elif after is not None:
        low, high = max(after.start - wish, 0.0), after.start
    elif before is not None:
        low, high = before.end, min(before.end + wish, duration)
    else:
        low, high = 0.0, duration
    return low, max(high, low)


def share(bounds: tuple[float, float], run: Sequence[int]) -> list[tuple[float, float]]:
    """Share the span between the bounds among the words of the run in proportion to the letters."""
    low, high = bounds
    cursor = low
    spans: list[tuple[float, float]] = []
    for weight in run:
        end = cursor + (high - low) * weight / sum(run)
        spans.append((cursor, end))
        cursor = end
    return spans
