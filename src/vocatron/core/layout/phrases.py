"""Phrases: the sung lines as the layout sees them (ADR-0008, ADR-0018).

Lines are never merged: each lyrics line is one phrase, and a change of singers inside it is a
turn at a syllable.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from itertools import groupby

from vocatron.core.lyrics.document import ALL, FIRST_VOICE, SECOND_VOICE, Voice
from vocatron.core.lyrics.file import LyricLine
from vocatron.core.syllables import SyllableWord


@dataclass(frozen=True)
class Piece:
    """One sung syllable; the text carries the space after a word that it ends."""

    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Turn:
    """A change of singers inside a line.

    Attributes:
        piece: The index of the first syllable the new singers sing (never 0).
        singers: Who sings from there on: ``1``, ``1,3`` or ``all``.
    """

    piece: int
    singers: str


@dataclass(frozen=True)
class Phrase:
    """A line that is sung: its syllables in order and who sings them.

    The text of the last piece never ends in a space.

    Attributes:
        singers: Who sings the first syllable.
        pieces: The syllables.
        turns: Where the singers change, by rising piece index.
        voice: ``2`` for a line the second voice sings at the same time as the first (ADR-0052),
            ``1`` otherwise. Lines of different voices may overlap in time.
        tint: The singers whose colours the line is drawn in when they are not ``singers``: a
            second-voice line without a singer mark of its own is drawn in the colour of singer 2
            (ADR-0054). It is for the colour only: ``marks_of``, ``is_ensemble`` and the titles
            ignore it, so a second voice never makes a song a duet (ADR-0047).
    """

    singers: str
    pieces: tuple[Piece, ...]
    turns: tuple[Turn, ...] = ()
    voice: Voice = FIRST_VOICE
    tint: str | None = None

    @property
    def shown_singers(self) -> str:
        """The singers whose colours the first syllable is drawn in."""
        return self.tint or self.singers

    def singers_at(self, piece: int) -> str:
        """Return who sings syllable ``piece``."""
        found = self.singers
        for turn in self.turns:
            if turn.piece <= piece:
                found = turn.singers
        return found

    @property
    def start(self) -> float:
        """When the first syllable starts."""
        return self.pieces[0].start

    @property
    def end(self) -> float:
        """When the last syllable ends."""
        return self.pieces[-1].end

    @property
    def text(self) -> str:
        """The line as written."""
        return "".join(piece.text for piece in self.pieces)


def _tidy(pieces: Sequence[Piece]) -> tuple[Piece, ...]:
    """Make the times run forward (no piece starts before the one before ends) and trim the end."""
    tidy: list[Piece] = []
    previous = float("-inf")
    for piece in pieces:
        start = max(piece.start, previous)
        end = max(piece.end, start)
        tidy.append(Piece(piece.text, start, end))
        previous = end
    last = tidy[-1]
    tidy[-1] = Piece(last.text.rstrip(), last.start, last.end)
    return tuple(tidy)


def _case(text: str, case: str) -> str:
    """Apply a profile's ``case``."""
    return {"upper": text.upper(), "lower": text.lower()}.get(case, text)


SECOND_VOICE_COLOUR = "2"
"""The singer whose colours a second-voice line without a singer mark of its own gets."""


def phrases_from(
    words: Sequence[SyllableWord],
    lines: Sequence[LyricLine],
    case: str = "as-written",
    voices: Sequence[Voice] = (),
) -> list[Phrase]:
    """Build the phrases of a song from its syllables and its lyrics lines.

    Args:
        words: Every word with its syllables (``syllables.json``), in order.
        lines: The cleaned lyrics lines (``lyrics.json``); a word's ``line`` indexes into them.
        case: The profile's ``font.case``.
        voices: The voice of every line (``syllables.json``); without one a line has the voice
            ``lyrics.json`` gives it.

    Returns:
        The phrases ordered by their start; a line without a sung syllable is left out. The lines
        of one voice come one after another (``one_after_another``); lines of the two voices may
        overlap (ADR-0054). A turn of the lyrics line is a turn at the first syllable of its word.
    """
    phrases: list[Phrase] = []
    for index, group in groupby(words, key=lambda word: word.line):
        pieces: list[Piece] = []
        members = list(group)
        for number, word in enumerate(members):
            space = " " if number < len(members) - 1 else ""
            parts = [_case(syllable.text, case) for syllable in word.syllables]
            parts[-1] += space
            pieces += [
                Piece(text, syllable.start, syllable.end)
                for text, syllable in zip(parts, word.syllables, strict=True)
            ]
        if pieces:
            line = lines[index] if index < len(lines) else None
            starts = [0]  # the piece each word starts at
            for word in members:
                starts.append(starts[-1] + len(word.syllables))
            turns = tuple(
                Turn(starts[turn.word], turn.singers)
                for turn in (line.turns if line else ())
                if 0 < turn.word < len(members)
            )
            voice = voices[index] if index < len(voices) else (line.voice if line else FIRST_VOICE)
            tint = (
                SECOND_VOICE_COLOUR
                if voice == SECOND_VOICE and not (line and line.own_mark)
                else None
            )
            phrases.append(Phrase(line.singers if line else "1", _tidy(pieces), turns, voice, tint))
    return by_voice(sorted(phrases, key=lambda phrase: phrase.start))


TOGETHER_SECONDS = 0.1
"""Lines that start less than this apart start together: they share the earlier line's time
instead of the earlier one being squeezed into no time (``one_after_another``)."""


def _cut(phrase: Phrase, until: float) -> Phrase:
    """Return ``phrase`` squeezed to end at ``until``, which lies after its start.

    Every syllable keeps its share of the line's time: syllables piled up at ``until`` with no
    length would leave a wrapped row with nothing to sing.
    """
    start, end = phrase.start, phrase.end
    if end <= until:
        return phrase
    scale = (until - start) / (end - start)

    def at(time: float) -> float:
        return start + (time - start) * scale

    pieces = tuple(Piece(p.text, at(p.start), at(p.end)) for p in phrase.pieces)
    return replace(phrase, pieces=pieces)


def _moved(phrase: Phrase, by: float) -> Phrase:
    """Return ``phrase`` ``by`` seconds later."""
    pieces = tuple(Piece(p.text, p.start + by, p.end + by) for p in phrase.pieces)
    return replace(phrase, pieces=pieces)


def by_voice(phrases: Sequence[Phrase]) -> list[Phrase]:
    """Make the lines of each voice follow one another; the two voices may overlap (ADR-0054).

    Args:
        phrases: The lines ordered by their start.

    Returns:
        The lines in the same order, none starting before the one before it of its voice ends
        (``one_after_another`` per voice).
    """
    squeezed = {
        voice: iter(one_after_another([p for p in phrases if p.voice == voice]))
        for voice in {p.voice for p in phrases}
    }
    return sorted((next(squeezed[p.voice]) for p in phrases), key=lambda p: p.start)


def one_after_another(phrases: Sequence[Phrase]) -> list[Phrase]:
    """Show lines that overlap in time one after the other.

    The layout shows lines of the two voices that are sung at once one after the other in the
    looks that have no place for two lines at a time (ADR-0054); lines of one voice never
    overlap but for the rounding of the times. Each line is shown until the next
    one starts: it is squeezed into the time until then (``_cut``). Two lines that start together
    (less than ``TOGETHER_SECONDS`` apart) share the time of the earlier one: it is squeezed into
    the first half, and the later line moves to the middle, so the lines after them are never
    pushed back. Lines that do not overlap come back unchanged.

    Args:
        phrases: The lines ordered by their start.

    Returns:
        The lines in the same order, none starting before the one before ends.
    """
    out: list[Phrase] = []
    for phrase in phrases:
        current = phrase
        if out and phrase.start < out[-1].end:
            before = out[-1]
            if phrase.start > before.start + TOGETHER_SECONDS:
                out[-1] = _cut(before, phrase.start)
            else:  # together: the first half of the earlier line's time each
                half = max((before.start + before.end) / 2, phrase.start)
                out[-1] = _cut(before, half)
                current = _moved(phrase, half - phrase.start)
        out.append(current)
    return out


def shifted(phrases: Sequence[Phrase], lead: float) -> list[Phrase]:
    """Return ``phrases`` later by ``lead`` seconds (the silent intro, ADR-0020)."""
    if lead == 0:
        return list(phrases)
    return [
        replace(
            phrase, pieces=tuple(Piece(p.text, p.start + lead, p.end + lead) for p in phrase.pieces)
        )
        for phrase in phrases
    ]


def marks_of(phrases: Sequence[Phrase]) -> list[str]:
    """Return who sings, once each and in order of appearance: the marks of lines and turns."""
    marks = [phrase.singers for phrase in phrases]
    marks += [turn.singers for phrase in phrases for turn in phrase.turns]
    return list(dict.fromkeys(marks))


def numbers_in(marks: Iterable[str]) -> set[str]:
    """Return the numbers of the singers the marks name, as ``"1"``, ``"2"``; ``all`` names none."""
    return {number for mark in marks for number in mark.split(",") if number != ALL}


def is_ensemble(marks: Iterable[str]) -> bool:
    """Tell whether marks name more than one singer or any lines sung together (ADR-0020)."""
    found = list(marks)  # a group names at least two singers, so only ``all`` needs a look
    return len(numbers_in(found)) > 1 or ALL in found
