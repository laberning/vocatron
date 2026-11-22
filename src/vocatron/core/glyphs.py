"""Characters the bundled font cannot draw (ADR-0046).

A symbol the font lacks is dropped from a text and reported; a letter, mark or digit it lacks
fails, since leaving it out would change the words. A note sign (decoration in lyrics found
online, never sung), a mark that belongs to a dropped symbol (the keycap around an emoji), a
variation selector (which only picks how a character looks, as in an emoji) and white space the
font lacks go without a report. Lyrics cleaning and the start screen share these rules.
"""

import unicodedata
from collections.abc import Container
from typing import NamedTuple

LETTER_CATEGORIES = ("L", "M", "N")  # Unicode major classes that are not symbols
VARIATION_SELECTORS = (range(0xFE00, 0xFE10), range(0xE0100, 0xE01F0))
NOTE_SIGNS = range(0x2669, 0x266D)  # quarter, eighth, beamed eighth and beamed sixteenth notes


class UndrawableLetter(ValueError):
    """A letter, mark or digit that the bundled font cannot draw.

    Attributes:
        codepoint: The code point.
        where: Where it stands, for example ``line 45`` or ``the title``.
    """

    def __init__(self, codepoint: int, where: str) -> None:
        """Say which character is missing and where."""
        self.codepoint = codepoint
        self.where = where
        super().__init__(f"{where}: {describe(codepoint)} is a letter the bundled font cannot draw")


class Stripped(NamedTuple):
    """A text without the symbols the font cannot draw.

    Attributes:
        text: What is left, words separated by single spaces when something was dropped.
        dropped: The code points that were dropped, each once, in order of appearance.
        kept: For every word of the original (split at white space) and one more for the end,
            how many words of ``text`` stand before it.
    """

    text: str
    dropped: tuple[int, ...]
    kept: tuple[int, ...]


def describe(codepoint: int) -> str:
    """Return ``U+221A SQUARE ROOT``: the code point and its Unicode name."""
    name = unicodedata.name(chr(codepoint), unicodedata.category(chr(codepoint)))
    return f"U+{codepoint:04X} {name}"


def is_letter(char: str) -> bool:
    """Tell whether a character is a letter, a mark or a digit (not a symbol).

    A variation selector is a mark to Unicode, but it only picks how the character before it
    looks (``U+FE0F`` after an emoji), so it does not count.
    """
    if any(ord(char) in selectors for selectors in VARIATION_SELECTORS):
        return False
    return unicodedata.category(char)[0] in LETTER_CATEGORIES


def _silent(char: str, after_dropped: bool) -> bool:
    """Tell whether a character the font lacks goes without a report.

    A note sign is decoration; a variation selector, and a mark right after a character that was
    dropped (it belongs to that character), are part of what was dropped already or invisible.
    """
    if ord(char) in NOTE_SIGNS:
        return True
    is_mark = unicodedata.category(char).startswith("M")
    return is_mark and (after_dropped or not is_letter(char))


def strip_undrawable(text: str, drawable: Container[int], where: str) -> Stripped:
    """Drop the symbols of ``text`` that the font cannot draw.

    A text the font can draw whole comes back unchanged. Otherwise the words are rebuilt: a
    symbol inside a word leaves the word, a word of symbols disappears, and white space the
    font lacks becomes a single space. Note signs, marks of a dropped symbol, variation selectors
    and white space are dropped without being listed in ``dropped``.

    Args:
        text: The text.
        drawable: The code points of the font.
        where: Where the text stands, for the error.

    Raises:
        UndrawableLetter: If a letter, mark or digit is not in the font.
    """
    words = text.split()
    unchanged = Stripped(text, (), tuple(range(len(words) + 1)))
    if all(ord(char) in drawable for char in text):
        return unchanged
    dropped: dict[int, None] = {}
    kept: list[int] = []
    rebuilt: list[str] = []
    for word in words:
        kept.append(len(rebuilt))
        stays: list[str] = []
        after_dropped = False
        for char in word:
            if ord(char) in drawable:
                stays.append(char)
                after_dropped = False
                continue
            if not _silent(char, after_dropped):
                if is_letter(char):
                    raise UndrawableLetter(ord(char), where)
                dropped[ord(char)] = None
            after_dropped = True
        if stays:
            rebuilt.append("".join(stays))
    kept.append(len(rebuilt))
    return Stripped(" ".join(rebuilt), tuple(dropped), tuple(kept))
