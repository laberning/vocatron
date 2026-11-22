"""Sung lines for the layout tests: a phrase of one syllable per word."""

from vocatron.core.layout.phrases import Phrase, Piece
from vocatron.core.lyrics.document import FIRST_VOICE, Voice


def line(
    start: float,
    end: float,
    text: str = "la la",
    singers: str = "1",
    voice: Voice = FIRST_VOICE,
    tint: str | None = None,
) -> Phrase:
    """One line of one syllable per word, the words evenly over ``start`` to ``end``."""
    words = text.split()
    step = (end - start) / len(words)
    pieces = tuple(
        Piece(word + (" " if i < len(words) - 1 else ""), start + i * step, start + (i + 1) * step)
        for i, word in enumerate(words)
    )
    return Phrase(singers, pieces, voice=voice, tint=tint)
