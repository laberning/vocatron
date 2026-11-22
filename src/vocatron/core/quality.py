"""The quality report of an alignment and the rules that make a song ``review`` (ADR-0008).

Five things make an alignment look doubtful: many estimated words, a long silence inside a
line, many words that are too short or too long to be sung, lines placed at their line time
with little voice there (ADR-0027), and lines whose first words sit before a silent gap, which
means the line time is early (ADR-0053). The reasons contain numbers only.
"""

from collections.abc import Sequence

from vocatron.core.alignment.file import AlignedWord, QualityReport
from vocatron.core.alignment.unheard import UnheardLine
from vocatron.core.alignment.voice import VoiceActivity

MAX_ESTIMATED_SHARE = 0.10
"""More estimated words than this share of all words need review."""
MAX_GAP = 3.0
"""A silence longer than this many seconds inside a line needs review."""
SHORT_WORD = 0.06
"""A measured word held for less than this many seconds is suspicious."""
LONG_WORD = 3.0
"""A measured word heard for longer than this many seconds is suspicious."""
MAX_ODD_WORDS = 5
"""More suspicious words than this need review."""
MIN_UNHEARD_VOICE = 0.5
"""An unheard line placed at its line time needs review when less than this share of its window
is voiced (ADR-0027)."""
MAX_LISTED_LINES = 5
"""How many line numbers the unheard-lines reason names before it counts the rest."""
SPLIT_GAP = 1.5
"""A gap of at least this many seconds inside a line, after weakly measured first words, shows a
line time that is early (ADR-0053)."""
SPLIT_CONFIDENCE = 0.5
"""The first words of a split line have a mean confidence below this."""
SPLIT_SILENT = 0.5
"""The voice must sound in less than this share of the gap."""
NOT_FITTING = "lyrics times do not fit"
"""The reason when the times of an ``.lrc`` disagree with the singing."""


def report(words: Sequence[AlignedWord]) -> QualityReport:
    """Measure the quality of an alignment.

    The length of an estimated word is a guess, so only measured words count as too short or
    too long; the estimated share already covers them. A measured word is too short when even its
    held length (to ``end``) is short, and too long when the part the model heard (to
    ``AlignedWord.heard_end``) is long, so neither a short word held to the end of the voice nor
    a held note is odd (ADR-0017); a gap is judged on the held ends.
    """
    estimated = sum(w.estimated for w in words)
    longest, gap_line = 0.0, None
    for before, after in zip(words, words[1:], strict=False):
        gap = after.start - before.end
        if before.line == after.line and gap > longest:
            longest, gap_line = gap, after.line
    measured = [w for w in words if not w.estimated]
    return QualityReport(
        words=len(words),
        estimated=estimated,
        estimated_share=estimated / len(words) if words else 0.0,
        longest_gap=longest,
        gap_line=gap_line,
        too_short=sum(w.end - w.start < SHORT_WORD for w in measured),
        too_long=sum(w.heard_end - w.start > LONG_WORD for w in measured),
    )


def reasons(quality: QualityReport) -> list[str]:
    """Return why the alignment needs review, short enough for a summary line; empty if fine.

    The exact counts are in the quality report; a word of odd length is a measured word shorter
    than ``SHORT_WORD`` or longer than ``LONG_WORD``.
    """
    found: list[str] = []
    if quality.estimated_share > MAX_ESTIMATED_SHARE:
        found.append(
            f"{quality.estimated_share:.0%} of words estimated (max {MAX_ESTIMATED_SHARE:.0%})"
        )
    if quality.longest_gap > MAX_GAP:
        found.append(
            f"{quality.longest_gap:.1f} s gap in line {(quality.gap_line or 0) + 1} "
            f"(max {MAX_GAP:.0f} s)"
        )
    odd = quality.too_short + quality.too_long
    if odd > MAX_ODD_WORDS:
        found.append(f"{odd} words of odd length (max {MAX_ODD_WORDS})")
    return found


def unheard_reasons(lines: Sequence[UnheardLine], voice: VoiceActivity | None) -> list[str]:
    """Return why unheard lines need review (ADR-0027); empty if none or the voice is unknown.

    A line placed at its line time needs review when less than ``MIN_UNHEARD_VOICE`` of its
    window is voiced: nothing in the audio backs the line time up. The reason names the line
    numbers (at most ``MAX_LISTED_LINES``, then a count).

    Args:
        lines: The lines that were placed at their line time.
        voice: Where the voice sounds; ``None`` when it is not known (nothing to judge by).
    """
    if voice is None:
        return []
    doubtful = [
        line.line + 1
        for line in lines
        if voice.voiced_fraction(line.rail, line.stop) < MIN_UNHEARD_VOICE
    ]
    if not doubtful:
        return []
    named = listed(doubtful, MAX_LISTED_LINES)
    if len(doubtful) == 1:
        return [f"little voice where line {named} was placed at its time"]
    return [f"little voice where lines {named} were placed at their time"]


def split_reasons(words: Sequence[AlignedWord], voice: VoiceActivity | None) -> list[str]:
    """Return why lines whose time looks early need review (ADR-0053); empty if none or no voice.

    A line is split when its longest gap (from the held end of a word to the start of the next,
    so a held note is no gap) is at least ``SPLIT_GAP`` long, the voice sounds in less than
    ``SPLIT_SILENT`` of it, and the words before the gap have a mean confidence below
    ``SPLIT_CONFIDENCE`` and none of them is estimated: the first words were pulled into the
    singing before, and the rest of the line is sung later. The reason names the line numbers (at
    most ``MAX_LISTED_LINES``).

    Args:
        words: The aligned words in order.
        voice: Where the voice sounds; ``None`` when it is not known (nothing to judge by).
    """
    if voice is None:
        return []
    split: list[int] = []
    start = 0
    while start < len(words):
        stop = start
        while stop < len(words) and words[stop].line == words[start].line:
            stop += 1
        if _is_split(words[start:stop], voice):
            split.append(words[start].line + 1)
        start = stop
    if not split:
        return []
    named = listed(split, MAX_LISTED_LINES)
    if len(split) == 1:
        return [f"line {named}: its time looks early"]
    return [f"lines {named}: their times look early"]


def _is_split(line: Sequence[AlignedWord], voice: VoiceActivity) -> bool:
    """Tell whether one line's first words sit before a silent gap with low confidence."""
    best = max(range(1, len(line)), key=lambda k: line[k].start - line[k - 1].end, default=None)
    if best is None:
        return False
    begin, end = line[best - 1].end, line[best].start
    if end - begin < SPLIT_GAP or voice.voiced_fraction(begin, end) >= SPLIT_SILENT:
        return False
    before = line[:best]
    if any(w.estimated for w in before):  # a guessed time is no weak measurement
        return False
    return sum(w.confidence for w in before) / len(before) < SPLIT_CONFIDENCE


def listed(numbers: Sequence[int], limit: int) -> str:
    """Return line numbers for a message: at most ``limit`` of them, then how many more."""
    named = ", ".join(str(number) for number in numbers[:limit])
    more = len(numbers) - limit
    return f"{named} and {more} more" if more > 0 else named
