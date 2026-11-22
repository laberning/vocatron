"""What a language module is, and the text rules every module shares (ADR-0005).

A module bundles everything that depends on the language of a song: the alignment model and
its alphabet, how a written word becomes the letters the model knows, how numbers are spelled
out, and how a word is split into the syllables that are sung.
"""

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from typing import Protocol, cast

import pyphen

WORD_EDGE = re.compile(r"^(\W*)(.*?)(\W*)$", re.DOTALL)
"""A word split into the punctuation before it, its core and the punctuation after it."""
NUMBER = re.compile(r"\d+")
HYPHENS = "-‐‑"
MIN_YEAR = 1100
MAX_YEAR = 2099
MILLION = 1_000_000
"""The range every module spells: a lone four-digit number from ``MIN_YEAR`` to ``MAX_YEAR`` is a
year, anything up to ``MILLION`` a cardinal, longer runs of digits are spelled digit by digit."""
YEAR_DIGITS = 4


class LanguageModule(Protocol):
    """A language Vocatron can make karaoke in.

    Attributes:
        code: The ISO 639-1 code, lower case.
        name: The English name.
        model: The registry name of the alignment model (``vocatron.core.models``).
        alphabet: The letters the alignment model knows (lower case, without the word
            delimiter); ``normalise`` only ever returns these.
        together_two: The word for lines sung together by two singers ("Both"), shown on the
            title screen (ADR-0020).
        together_all: The word for lines sung together by three or more singers ("All").
    """

    code: str
    name: str
    model: str
    alphabet: str
    together_two: str
    together_all: str

    def normalise(self, word: str) -> str:
        """Return the letters of ``word`` as the model hears them.

        Lower case, characters outside the alphabet replaced (``ß`` as ``ss``) or dropped,
        apostrophes and hyphens dropped. The result may be empty (a lone ``&`` has no sound).
        """
        ...

    def spell_numbers(self, text: str) -> str:
        """Return ``text`` with its numbers written out as the language sings them."""
        ...

    def syllables(self, word: str) -> list[str]:
        """Split ``word`` into the syllables it is sung in.

        The parts always join to ``word`` again, punctuation stays with its syllable.
        """
        ...


def fold(word: str, alphabet: str, replacements: Mapping[str, str]) -> str:
    """Reduce ``word`` to ``alphabet``: lower case, ``replacements`` applied, accents dropped.

    A letter outside the alphabet is tried without its accent (``é`` as ``e``); whatever is
    still outside (digits, punctuation, apostrophes, hyphens, other scripts) is dropped.

    Args:
        word: The word as written.
        alphabet: The letters to keep.
        replacements: Lower-case letters spelled differently, for example ``ß`` as ``ss``.

    Returns:
        The letters, possibly none.
    """
    out: list[str] = []
    for char in word.lower():
        if char in alphabet:
            out.append(char)
        elif char in replacements:
            out.append(replacements[char])
        else:
            base = unicodedata.normalize("NFD", char)[0]
            out.append(base if base in alphabet else "")
    return "".join(out)


def edges(word: str) -> tuple[str, str, str]:
    """Split ``word`` into the punctuation before it, its core and the punctuation after it.

    Digits count as part of the core. The parts always join to ``word``.
    """
    match = cast(re.Match[str], WORD_EDGE.match(word))  # the pattern matches every string
    before, core, after = match.groups()
    return before, core, after


def is_lone_number(core: str) -> bool:
    """Tell whether ``core`` (a word without its punctuation) is nothing but digits."""
    return NUMBER.fullmatch(core) is not None


def is_cardinal(digits: str) -> bool:
    """Tell whether the run of ``digits`` is spelled as one cardinal (at most ``MILLION``)."""
    # The length test first: int() refuses strings of thousands of digits.
    return len(digits) <= len(str(MILLION)) and int(digits) <= MILLION


def spell_words(text: str, spell_core: Callable[[str], str]) -> str:
    """Apply ``spell_core`` to the core of every word of ``text``, the punctuation kept.

    Whitespace and the punctuation around each word stay as they are; a language only decides
    how the core of one word (``1999``, ``4ever``) is spelled.
    """

    def one(match: re.Match[str]) -> str:
        before, core, after = edges(match.group())
        return before + spell_core(core) + after

    return re.sub(r"\S+", one, text)


def spell_run(
    digits: str,
    *,
    whole: bool,
    cardinal: Callable[[int], str],
    year: Callable[[int], str],
) -> str:
    """Spell one run of ``digits``: a year if it stands alone as one, else a cardinal.

    Args:
        digits: The run of digits.
        whole: Whether the run is the whole word (``1999``, not ``1999th``).
        cardinal: The language's cardinal speller (0 to ``MILLION``).
        year: The language's year speller (``MIN_YEAR`` to ``MAX_YEAR``).

    Returns:
        The words; a run too long for a cardinal is spelled digit by digit.
    """
    if not is_cardinal(digits):
        return " ".join(cardinal(int(d)) for d in digits)
    n = int(digits)
    if whole and len(digits) == YEAR_DIGITS and MIN_YEAR <= n <= MAX_YEAR:
        return year(n)
    return cardinal(n)


@dataclass(frozen=True)
class Hyphenation:
    """How a language splits a word into the syllables that are sung.

    The dictionary decides where a word may be cut; a part without a vowel is joined to its
    neighbour, hyphenated words are split part by part, and the words in ``exceptions`` (which
    the dictionary gets wrong) are split as listed.

    Attributes:
        dictionary: Gives the (cached) pyphen dictionary; a cut needs one letter on each side.
        vowels: The letters that make a part a syllable.
        exceptions: Words the dictionary gets wrong, by lower-case word, with their syllables;
            the word is cut at the same places and keeps its own case.
        joiners: The characters after which a word is cut into pieces before the dictionary
            sees it; they stay at the end of their piece.
        glued: The joiners (a subset of ``joiners``) that bind the next piece to the one before
            it when that piece has no vowel or is one of ``endings`` (``don'`` + ``t``).
        endings: The lower-case pieces that bind to the piece before them after a glued joiner.
        lone_edges: Whether a word-initial ``y`` before another vowel (``you``) and a final
            ``e`` after a consonant (``inside``) are no syllables of their own, so the
            dictionary's cut next to them is undone.
    """

    dictionary: Callable[[], pyphen.Pyphen]
    vowels: frozenset[str]
    exceptions: Mapping[str, tuple[str, ...]]
    joiners: str = HYPHENS
    glued: str = ""
    endings: frozenset[str] = frozenset()
    lone_edges: bool = False

    def syllables(self, word: str) -> list[str]:
        """Split ``word`` into syllables; punctuation stays with its syllable."""
        before, core, after = edges(word)
        if not core:
            return [word]
        parts = self._split_core(core)
        parts[0] = before + parts[0]
        parts[-1] += after
        return parts

    def _has_vowel(self, part: str) -> bool:
        """Tell whether ``part`` holds a vowel."""
        return bool(self.vowels & set(part.lower()))

    def _binds(self, previous: str, piece: str) -> bool:
        """Tell whether ``piece`` belongs to the syllable ``previous`` it follows."""
        if previous[-1] not in self.glued:
            return False
        letters = piece.rstrip(self.joiners).lower()
        return not self._has_vowel(letters) or letters in self.endings

    def _split_core(self, core: str) -> list[str]:
        """Split a punctuation-free word, cut at its joiners first."""
        pieces = [piece for piece in re.split(f"(?<=[{self.joiners}])", core) if piece]
        if len(pieces) > 1:
            out: list[str] = []
            for piece in pieces:
                if out and self._binds(out[-1], piece):
                    out[-1] += piece
                else:
                    out.extend(self._split_core(piece))
            return out
        letters = core.rstrip(self.joiners)
        tail = core[len(letters) :]
        if (exception := self.exceptions.get(letters.lower())) is not None:
            parts = _cut(letters, exception)
        else:
            parts = self._hyphenate(letters)  # an empty word gives [""]
        parts[-1] += tail
        return parts

    def _hyphenate(self, core: str) -> list[str]:
        """Split a word without punctuation at its dictionary points; no part without a vowel."""
        cuts = [0, *[int(p) for p in self.dictionary().positions(core)], len(core)]
        parts = [core[a:b] for a, b in zip(cuts, cuts[1:], strict=False)]
        merged: list[str] = []
        for part in parts:
            if merged and not self._has_vowel(part):
                merged[-1] += part  # a lone consonant belongs to the syllable before it
            else:
                merged.append(part)
        if len(merged) > 1 and not self._has_vowel(merged[0]):
            merged[1] = merged[0] + merged[1]
            del merged[0]
        if self.lone_edges and len(merged) > 1:
            if merged[0].lower() == "y":
                merged[1] = merged[0] + merged[1]
                del merged[0]
            if len(merged) > 1 and merged[-1].lower() == "e":
                merged[-2] += merged[-1]
                del merged[-1]
        return merged


def _cut(word: str, parts: tuple[str, ...]) -> list[str]:
    """Cut ``word`` into pieces as long as ``parts``; the pieces keep the case of ``word``.

    So ``IDEE`` with the exception ``I``, ``dee`` gives ``I``, ``DEE``: the syllables always
    join to the word, whatever its case. The last piece takes the rest of the word.
    """
    out: list[str] = []
    start = 0
    for part in parts[:-1]:
        out.append(word[start : start + len(part)])
        start += len(part)
    return [*out, word[start:]]


@cache
def dictionary_of(lang: str) -> pyphen.Pyphen:
    """Return the pyphen dictionary ``lang``; a cut needs a letter on each side."""
    return pyphen.Pyphen(lang=lang, left=1, right=1)
