"""Lines the model did not hear are placed at their ``.lrc`` time (ADR-0027).

A line is unheard when it has a line time and every word in it is estimated: the model's path
through it is arbitrary, so keeping it (ADR-0021) can put the whole line seconds from the singing.
The line time, moved by the song's rails offset, is then the best evidence left.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace

from vocatron.core.alignment.estimate import (
    LETTER_SECONDS,
    Timed,
    letter_seconds,
    on_voice,
    share,
)
from vocatron.core.alignment.voice import VoiceActivity

SNAP_SECONDS = 0.5
"""A placement on the voice whose first word starts further than this from the rail is dropped;
the line's letters are shared from the rail instead."""
AFTER_PREVIOUS_SECONDS = 0.02
"""A line starts at least this long after the start of the last measured word before it."""
OPEN_END_SECONDS = 10.0
"""How far the last line of a song may reach past its start."""
LATE_SECONDS = 1.0
"""A first-voice line that starts later than this after its rail, while a second voice sings, has
taken words of the second voice (ADR-0052): it counts as unheard."""


@dataclass(frozen=True)
class UnheardLine:
    """A line that was placed at its line time.

    Attributes:
        line: The index of the line.
        rail: The line time plus the rails offset, in seconds.
        stop: The end of the window the line's words are expected in: the next line's rail, but
            at most as far as the line's letters take at ``LETTER_SECONDS``.
    """

    line: int
    rail: float
    stop: float


@dataclass(frozen=True)
class Placed:
    """The words of a song after the unheard lines were placed.

    Attributes:
        words: One ``Timed`` per word, in order.
        lines: The lines that were placed, ascending.
    """

    words: list[Timed]
    lines: tuple[UnheardLine, ...] = ()


def place_unheard(
    words: Sequence[Timed],
    lines: Sequence[int],
    weights: Sequence[int],
    hints: Sequence[float | None],
    offset: float,
    voice: VoiceActivity | None,
) -> Placed:
    """Place every unheard line at its rail (ADR-0027).

    A line is unheard when its hint is not ``None`` and all its words are estimated. Its first
    word starts at the rail (hint plus ``offset``), raised to ``AFTER_PREVIOUS_SECONDS`` after
    the start of the last measured word before it, and never after the start of the next line.
    Its words go on the voice between that start and the start of the next line (the song's
    seconds per letter from its sure words); without voice there, or when the voice starts them
    more than ``SNAP_SECONDS`` after that start, the letters are shared over letters times
    ``LETTER_SECONDS``. The words before are cut so none overlaps, and the words stay in order.
    Lines are processed last to first, so the next line is final. Other lines are unchanged.

    Args:
        words: The timed words, in order.
        lines: The line of every word.
        weights: The number of letters of every word.
        hints: The line times of the ``.lrc`` that stay after the order check (``None`` for a
            line without one), one per line.
        offset: Seconds the singing lies after the hints (the rails offset).
        voice: Where the voice sounds, or ``None``.

    Returns:
        The words and the lines that were placed.
    """
    out = list(words)
    first: dict[int, int] = {}
    for index, line in enumerate(lines):
        first.setdefault(line, index)
    order = sorted(first)
    # The letters' own span, not a held end (ADR-0013); ``letter_seconds`` picks the sure words.
    per_letter = letter_seconds([replace(w, end=w.letters[-1][1]) for w in out if w.letters])
    placed: list[UnheardLine] = []
    for k in reversed(range(len(order))):
        line = order[k]
        a = first[line]
        b = first[order[k + 1]] if k + 1 < len(order) else len(out)
        hint = hints[line]
        if hint is None or any(not out[i].estimated for i in range(a, b)):
            continue
        rail = hint + offset
        letters = [max(weights[i], 1) for i in range(a, b)]
        start = _start(out, a, rail)
        if b < len(out):  # a rail after the next line's start must not reorder the words
            start = min(start, out[b].start)
        high = out[b].start if b < len(out) else start + OPEN_END_SECONDS
        spans = None
        if voice is not None:
            spans = on_voice(voice, [n * per_letter for n in letters], start, high, False)
        if spans is None or abs(spans[0][0] - start) > SNAP_SECONDS:
            spans = share((start, min(high, start + sum(letters) * LETTER_SECONDS)), letters)
        for j, (begin, end) in enumerate(spans):
            out[a + j] = replace(out[a + j], start=begin, end=end)
        _cut_before(out, a)
        placed.append(UnheardLine(line, rail, _stop(hints, order, k, offset, rail, sum(letters))))
    return Placed(out, tuple(reversed(placed)))


def forget_late(
    words: Sequence[Timed],
    lines: Sequence[int],
    hints: Sequence[float | None],
    offset: float,
    judged: Collection[int],
) -> list[Timed]:
    """Make the words of every judged line that starts over ``LATE_SECONDS`` after its rail unheard.

    With two voices singing, one voice's search can take frames that sing the other voice's words
    and so start a line seconds late (ADR-0052); a second-voice line that the backing does not
    carry takes the first voice's words the same way. Such a line is better placed at its rail
    (``place_unheard``) than where it was found: all its words become estimated, with their
    letters dropped; the other lines are unchanged. Only lines in ``judged`` (the lines whose
    window overlaps one of the other voice, ``rails.crowded_lines``) are looked at: far from the
    other voice a late start is the singer's own. A line is judged by its first word
    only, and only when that word is measured: an estimated first word's time is a guess, not
    evidence that the line is late.

    Args:
        words: The timed words of one voice, in order.
        lines: The line of every word.
        hints: The line times of the lines (``None`` for a line without one).
        offset: Seconds the singing lies after the hints (the rails offset).
        judged: The lines (numbered as in ``lines``) that may be made unheard.

    Returns:
        The words, in order.
    """
    out = list(words)
    seen: set[int] = set()
    for index, line in enumerate(lines):
        if line in seen:
            continue
        seen.add(line)
        hint = hints[line]
        if line not in judged or hint is None or out[index].estimated:
            continue
        if out[index].start <= hint + offset + LATE_SECONDS:
            continue
        for j in range(index, len(out)):
            if lines[j] != line:
                break
            out[j] = replace(out[j], estimated=True, letters=())
    return out


def _cut_before(out: list[Timed], first: int) -> None:
    """End the words before ``first`` at its start, so none overlaps the placed line.

    Measured words before always start earlier (see ``_start``) and only lose their end; their
    letters are cut at the same time, so no letter outlasts its word. Estimated words the model
    put after the line's start are moved to it with no length, so the words stay in order.
    """
    start = out[first].start
    for index in reversed(range(first)):
        word = out[index]
        if word.end <= start:
            return
        letters = tuple((min(a, start), min(b, start)) for a, b in word.letters)
        out[index] = replace(word, start=min(word.start, start), end=start, letters=letters)


def _start(out: Sequence[Timed], first: int, rail: float) -> float:
    """Return the rail, raised to just after the start of the last measured word before.

    Estimated words between that word and the line do not lower the floor: the start must not
    pass a measured word, or ``_cut_before`` would have to move it.
    """
    for index in reversed(range(first)):
        if not out[index].estimated:
            return max(rail, out[index].start + AFTER_PREVIOUS_SECONDS)
    return rail


def _stop(
    hints: Sequence[float | None],
    order: Sequence[int],
    k: int,
    offset: float,
    rail: float,
    letters: int,
) -> float:
    """Return where the window of the line at ``order[k]`` ends: its letters or the next rail."""
    reach = rail + letters * LETTER_SECONDS
    for line in order[k + 1 :]:
        following = hints[line]
        if following is not None:
            return min(following + offset, reach)
    return reach
