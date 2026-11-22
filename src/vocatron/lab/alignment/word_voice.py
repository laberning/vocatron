"""Where the voice sounds under every word of a song: lead stem, backing stem and the mix.

The alignment stage measures the loudness of lead and backing vocals added (ADR-0012). This
module measures the same song with the two stems apart, with the thresholds of the voice check
(the lead's, and for the backing the lead's threshold but never closer to its own floor than the
margin, as in ADR-0014), and tells per word how much of it is voiced and how long after the
word's start the voice starts. A word is flagged when its sweep would start well before any voice
or run across a long silence. Numbers only: nothing here knows what a word says. Pure NumPy.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vocatron.core.alignment.estimate import CONFIDENT_WORD
from vocatron.core.alignment.mix import backing_sounds
from vocatron.core.alignment.voice import (
    VoiceActivity,
    find_voice,
    voiced_runs,
)
from vocatron.core.lyrics.document import SECOND_VOICE

EARLY_SECONDS = 0.3
"""A sweep that starts more than this before the voice starts is flagged ``early``."""
LONG_SILENCE_SECONDS = 0.5
"""A sweep that crosses a silence longer than this in both stems is flagged ``crosses``."""

NO_VOICE = "no-voice"
EARLY = "early"
CROSSES = "crosses"


@dataclass(frozen=True)
class WordTime:
    """A word as the alignment file has it, without its text.

    Attributes:
        line: The index of its line.
        start: Where its sweep starts, in seconds.
        end: Where its sweep ends.
        heard_end: Where the model last heard a letter (``end`` without letters).
        confidence: 0 to 1.
        estimated: Whether the time is interpolated.
        voice: The voice that sings its line, ``1`` or ``2`` (ADR-0052).
    """

    line: int
    start: float
    end: float
    heard_end: float
    confidence: float
    estimated: bool
    voice: int = 1


@dataclass(frozen=True)
class StemVoices:
    """Where the voice sounds, by stem.

    Attributes:
        lead: The voice on the lead stem.
        backing: The voice on the backing stem.
        threshold_db: The lead's threshold.
    """

    lead: VoiceActivity
    backing: VoiceActivity
    threshold_db: float

    @property
    def either(self) -> VoiceActivity:
        """The voice on the lead or on the backing."""
        return VoiceActivity(merge(self.lead.spans + self.backing.spans))


@dataclass(frozen=True)
class WordRow:
    """What the voice does under one word (``None`` where there is no voice in the word).

    Attributes:
        index: The word's index in the song.
        word: The word.
        lead_share: The voiced share of the word's span on the lead.
        backing_share: The same on the backing.
        mix_share: The same on the alignment's own voice (lead and backing added).
        lead_onset: Seconds from the word's start to the first lead voice inside it.
        backing_onset: The same for the backing.
        either_onset: The same for lead or backing.
        longest_silence: The longest stretch inside the word with no voice on either stem.
        flags: ``no-voice`` (neither stem sounds in the word), ``early`` (the voice starts more
            than ``EARLY_SECONDS`` after the word's start) and ``crosses`` (a silence longer
            than ``LONG_SILENCE_SECONDS`` inside the word).
    """

    index: int
    word: WordTime
    lead_share: float
    backing_share: float
    mix_share: float
    lead_onset: float | None
    backing_onset: float | None
    either_onset: float | None
    longest_silence: float
    flags: tuple[str, ...]


def merge(spans: Sequence[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    """Return ``spans`` ordered, with touching or overlapping ones joined."""
    out: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return tuple(out)


def confident_words(words: Sequence[WordTime]) -> list[tuple[float, float]]:
    """Return start and heard end of the measured words the voice check trusts."""
    return [
        (w.start, w.heard_end) for w in words if not w.estimated and w.confidence >= CONFIDENT_WORD
    ]


def stem_voices(
    lead_loudness: NDArray[np.float32],
    backing_loudness: NDArray[np.float32],
    seconds_per_frame: float,
    confident: Sequence[tuple[float, float]],
) -> StemVoices | None:
    """Find where the voice sounds on each stem; ``None`` if the lead's voice is not plausible.

    Args:
        lead_loudness: The lead stem's loudness per frame in dBFS.
        backing_loudness: The backing stem's, padded or trimmed to the lead's length by the caller.
        seconds_per_frame: The length of a frame.
        confident: Start and end of the confidently measured words.
    """
    detection = find_voice(lead_loudness, seconds_per_frame, confident)
    if detection.activity is None:
        return None
    mask = backing_sounds(backing_loudness, detection.threshold_db, seconds_per_frame)
    spans = tuple((a * seconds_per_frame, b * seconds_per_frame) for a, b in voiced_runs(mask))
    return StemVoices(detection.activity, VoiceActivity(spans), detection.threshold_db)


def onset(voice: VoiceActivity, start: float, end: float) -> float | None:
    """Return seconds from ``start`` to the first voice inside ``[start, end)``, or ``None``."""
    for begin, stop in voice.spans:
        if stop > start and begin < end:
            return max(begin - start, 0.0)
    return None


def longest_silence(voice: VoiceActivity, start: float, end: float) -> float:
    """Return the longest stretch of ``[start, end)`` without voice (the whole span if none)."""
    longest = 0.0
    cursor = start
    for begin, stop in voice.spans:
        if stop <= start:
            continue
        if begin >= end:
            break
        longest = max(longest, begin - cursor)
        cursor = max(cursor, stop)
    return max(longest, end - cursor, 0.0)


def word_rows(
    words: Sequence[WordTime], voices: StemVoices, mix: VoiceActivity | None = None
) -> list[WordRow]:
    """Describe what the voice does under every word.

    Args:
        words: The words in order.
        voices: The voice by stem.
        mix: The alignment's own voice (lead and backing added), for its voiced share.
    """
    either = voices.either
    rows: list[WordRow] = []
    for index, word in enumerate(words):
        s, e = word.start, word.end
        first = onset(either, s, e)
        silence = longest_silence(either, s, e)
        flags: list[str] = []
        if first is None:
            flags.append(NO_VOICE)
        elif first > EARLY_SECONDS:
            flags.append(EARLY)
        if first is not None and silence > LONG_SILENCE_SECONDS:
            flags.append(CROSSES)
        rows.append(
            WordRow(
                index=index,
                word=word,
                lead_share=voices.lead.voiced_fraction(s, e),
                backing_share=voices.backing.voiced_fraction(s, e),
                mix_share=mix.voiced_fraction(s, e) if mix is not None else 0.0,
                lead_onset=onset(voices.lead, s, e),
                backing_onset=onset(voices.backing, s, e),
                either_onset=first,
                longest_silence=silence,
                flags=tuple(flags),
            )
        )
    return rows


def _num(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def row_line(row: WordRow) -> str:
    """Return one table line for a word: numbers and flags, no text."""
    w = row.word
    est = "E" if w.estimated else " "
    return (
        f"{row.index:4d} L{w.line + 1:<3d} {w.start:7.2f} {w.end - w.start:5.2f} "
        f"c{w.confidence:4.2f}{est} lead {row.lead_share:4.2f}/{_num(row.lead_onset):>5} "
        f"back {row.backing_share:4.2f}/{_num(row.backing_onset):>5} "
        f"mix {row.mix_share:4.2f} either {_num(row.either_onset):>5} "
        f"silence {row.longest_silence:4.2f} "
        f"{' '.join(row.flags)}"
    )


def table_header() -> str:
    """Return the header of ``row_line``: index, line, start, duration, confidence, shares."""
    return (
        "word line   start   dur  conf     lead share/onset  back share/onset  mix   "
        "either-onset longest-silence flags"
    )


def summary(rows: Sequence[WordRow]) -> str:
    """Return the counts of the flags and of words by the stem that sings them.

    With a second voice (ADR-0052) the counts of its words follow.
    """
    count = {flag: sum(flag in r.flags for r in rows) for flag in (NO_VOICE, EARLY, CROSSES)}
    lead_silent = [r for r in rows if r.lead_share == 0.0]
    backing_only = [r for r in lead_silent if r.backing_share > 0.0]
    text = (
        f"{len(rows)} words: {count[NO_VOICE]} no-voice, {count[EARLY]} early, "
        f"{count[CROSSES]} crosses; {len(lead_silent)} silent on the lead, "
        f"{len(backing_only)} of them voiced on the backing"
    )
    second = [r for r in rows if r.word.voice == SECOND_VOICE]
    if not second:
        return text
    counts = [sum(flag in r.flags for r in second) for flag in (NO_VOICE, EARLY, CROSSES)]
    return (
        f"{text}; second voice {len(second)} words: {counts[0]} no-voice, {counts[1]} early, "
        f"{counts[2]} crosses"
    )
