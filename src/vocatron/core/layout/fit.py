"""Fit: a line that is too wide is split at the word nearest its middle, then shrunk (rule 3)."""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from vocatron.core.layout.phrases import Phrase, Piece, Turn
from vocatron.core.measure import TextMeasurer
from vocatron.core.profiles.model import Pop

SHRINK_MARGIN = 0.999  # a shrunk line ends a hair inside the limit, so rounding never tips it over
NO_POP = Pop()
MIN_WORDS_TO_WRAP = 2  # a text of one word has nowhere to be split


@dataclass(frozen=True)
class Fitted:
    """A line ready to be placed.

    Attributes:
        phrase: The syllables of the line.
        size: The font size it is drawn at (the profile's, or smaller when shrunk).
        too_wide: It is wider than the limit even at the smallest size.
        rows: The rows of a line wrapped onto several, in order; empty for a line of one row.
            They share the size and are placed, shown and hidden as one block.
        part: Which of the lines a lyric line was split into this is, counted from 0 (0 for a
            line that was not split).
    """

    phrase: Phrase
    size: float
    too_wide: bool = False
    rows: tuple[Phrase, ...] = ()
    part: int = 0

    @property
    def parts(self) -> tuple[Phrase, ...]:
        """The rows to draw: the wrapped rows, or the line itself."""
        return self.rows or (self.phrase,)


def _words(phrase: Phrase) -> list[tuple[str, float]]:
    """Return the words of a phrase, each with the time its first syllable starts."""
    words: list[tuple[str, float]] = []
    start, text = 0.0, ""
    for piece in phrase.pieces:
        start = piece.start if not text else start
        text += piece.text
        if piece.text.endswith(" "):
            words.append((text.rstrip(), start))
            text = ""
    if text:
        words.append((text.rstrip(), start))
    return words


def pop_room(phrase: Phrase, measurer: TextMeasurer, size: float, pop: Pop) -> float:
    """Return how much wider than its text a line gets while its words pop (ADR-0032).

    A word grows by ``pop.scale - 1`` of its width and pushes the rest of the line to the right.
    Words that start within ``pop.time`` of each other may be grown together, so the room is the
    largest total width of such words, times the growth.
    """
    if pop.scale <= 1:
        return 0.0
    words = [(measurer.width(text, size), start) for text, start in _words(phrase)]
    together = max(
        (
            sum(width for width, begin in words[index:] if begin < start + pop.time)
            for index, (_, start) in enumerate(words)
        ),
        default=0.0,
    )
    return (pop.scale - 1) * together


def popped_width(phrase: Phrase, measurer: TextMeasurer, size: float, pop: Pop) -> float:
    """Return the width of a line at ``size`` with the room its popping words need."""
    return measurer.width(phrase.text, size) + pop_room(phrase, measurer, size, pop)


def _split(phrase: Phrase, index: int) -> tuple[Phrase, Phrase]:
    """Split a phrase before piece ``index``; the first part loses the space it ended with.

    Each part keeps who sings its syllables: the second starts with the singers of ``index``.
    """
    head, tail = phrase.pieces[:index], phrase.pieces[index:]
    last = head[-1]
    head = (*head[:-1], Piece(last.text.rstrip(), last.start, last.end))
    turns_head = tuple(turn for turn in phrase.turns if turn.piece < index)
    turns_tail = tuple(
        Turn(turn.piece - index, turn.singers) for turn in phrase.turns if turn.piece > index
    )
    return (
        replace(phrase, pieces=head, turns=turns_head),
        replace(phrase, singers=phrase.singers_at(index), pieces=tail, turns=turns_tail),
    )


def _boundaries(pieces: Sequence[Piece], *, words: bool) -> list[int]:
    """Return the indexes where a phrase may be split: between words, or between syllables."""
    return [
        index
        for index in range(1, len(pieces))
        if not words or pieces[index - 1].text.endswith(" ")
    ]


def _middle(phrase: Phrase, indexes: list[int], size: float, measurer: TextMeasurer) -> int:
    """Return the split index whose first part is nearest to half the line's width."""
    half = measurer.width(phrase.text, size) / 2
    return min(
        indexes,
        key=lambda i: abs(
            measurer.width("".join(p.text for p in phrase.pieces[:i]).rstrip(), size) - half
        ),
    )


def wrap_words(text: str, measurer: TextMeasurer, size: float) -> tuple[str, str] | None:
    """Split a text at the word nearest its middle, the way a sung line is wrapped (rule 3).

    Returns:
        The two halves, or ``None`` when the text is a single word.
    """
    words = text.split()
    if len(words) < MIN_WORDS_TO_WRAP:
        return None
    spaced = [Piece(f"{word} ", 0.0, 0.0) for word in words[:-1]]
    pieces = (*spaced, Piece(words[-1], 0.0, 0.0))
    phrase = Phrase(singers="", pieces=pieces)
    head, tail = _split(phrase, _middle(phrase, _boundaries(pieces, words=True), size, measurer))
    return head.text, tail.text


def _two_rows(  # a line, how to measure it and the size window
    phrase: Phrase, measurer: TextMeasurer, size: float, min_size: float, limit: float, pop: Pop
) -> Fitted | None:
    """Wrap a line onto two rows at the word nearest its middle, shrunk until both fit.

    Returns:
        The block, or ``None`` if the line has no word to split at or its rows do not fit even at
        ``min_size``.
    """
    indexes = _boundaries(phrase.pieces, words=True)
    if not indexes:
        return None
    head, tail = _split(phrase, _middle(phrase, indexes, size, measurer))
    widest = max(popped_width(head, measurer, size, pop), popped_width(tail, measurer, size, pop))
    block = size if widest <= limit else size * limit / widest * SHRINK_MARGIN
    return Fitted(phrase, block, rows=(head, tail)) if block >= min_size else None


def fit(  # noqa: PLR0913  # a line, how to measure it and the size window; ``rows``, ``pop`` options
    phrase: Phrase,
    measurer: TextMeasurer,
    size: float,
    min_size: float,
    limit: float,
    rows: int = 1,
    *,
    pop: Pop = NO_POP,
) -> list[Fitted]:
    """Make a line fit in ``limit`` pixels.

    With ``rows`` of 2 a line that is too wide is first wrapped onto two rows at the word nearest
    its middle, shrunk (not below ``min_size``) until both rows fit; they stay one block. A line
    that does not fit even so, and every line with one row, is split into lines as follows.

    A line that is too wide is split at the word nearest its middle, each half again if needed.
    A single word that does not fit is shrunk, never below ``min_size``; if it still does not
    fit it is split between syllables, and as a last resort drawn at ``min_size`` and marked
    ``too_wide``.

    Args:
        phrase: The line.
        measurer: Measures the text.
        size: The font size.
        min_size: The smallest font size.
        limit: The widest a line may be, outline and shadow already taken off.
        rows: How many rows a line may be wrapped onto (1 or 2).
        pop: The growth of the word being sung; the room it needs counts as part of the width,
            so a popping word never pushes a line out of the safe area (ADR-0032).
    """
    width = popped_width(phrase, measurer, size, pop)
    if width <= limit:
        return [Fitted(phrase, size)]
    if rows > 1 and (block := _two_rows(phrase, measurer, size, min_size, limit, pop)):
        return [block]
    pieces = phrase.pieces
    for words in (True, False):
        if words is False:
            shrunk = size * limit / width * SHRINK_MARGIN
            if shrunk >= min_size:
                return [Fitted(phrase, shrunk)]
        indexes = _boundaries(pieces, words=words)
        if indexes:
            head, tail = _split(phrase, _middle(phrase, indexes, size, measurer))
            return [
                *fit(head, measurer, size, min_size, limit, rows, pop=pop),
                *fit(tail, measurer, size, min_size, limit, rows, pop=pop),
            ]
    return [Fitted(phrase, min_size, too_wide=True)]
