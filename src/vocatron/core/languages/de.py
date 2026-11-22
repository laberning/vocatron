"""German: model alphabet, normalisation, number spelling and syllables (ADR-0005)."""

import pyphen

from vocatron.core.languages.base import (
    MAX_YEAR,
    MILLION,
    MIN_YEAR,
    NUMBER,
    Hyphenation,
    dictionary_of,
    fold,
    is_lone_number,
    spell_run,
    spell_words,
)

ALPHABET = "abcdefghijklmnopqrstuvwxyzäöü"
"""The letters of the German wav2vec2 model (its vocabulary has more, rare ones)."""
REPLACEMENTS = {"ß": "ss"}
VOWELS = frozenset("aeiouyäöü")
EXCEPTIONS: dict[str, tuple[str, ...]] = {"idee": ("I", "dee")}
"""Words the hyphenation dictionary gets wrong, by lower-case word, with their syllables (the
word is cut at the same places and keeps its own case)."""

UNITS = [
    "null",
    "eins",
    "zwei",
    "drei",
    "vier",
    "fünf",
    "sechs",
    "sieben",
    "acht",
    "neun",
    "zehn",
    "elf",
    "zwölf",
    "dreizehn",
    "vierzehn",
    "fünfzehn",
    "sechzehn",
    "siebzehn",
    "achtzehn",
    "neunzehn",
]
TENS = {2: "zwanzig", 3: "dreißig", 4: "vierzig", 5: "fünfzig", 6: "sechzig", 7: "siebzig"}
TENS |= {8: "achtzig", 9: "neunzig"}


def _below_hundred(n: int, *, prefix: bool) -> str:
    """Spell 0..99; ``prefix`` is the form before ``hundert`` or ``tausend`` (``ein``)."""
    if n < len(UNITS):
        return "ein" if n == 1 and prefix else UNITS[n]
    tens, ones = divmod(n, 10)
    return TENS[tens] if ones == 0 else f"{UNITS[ones] if ones > 1 else 'ein'}und{TENS[tens]}"


def _below_thousand(n: int, *, prefix: bool) -> str:
    """Spell 0..999; ``prefix`` is the form before ``tausend``."""
    hundreds, rest = divmod(n, 100)
    if hundreds == 0:
        return _below_hundred(rest, prefix=prefix)
    head = f"{'ein' if hundreds == 1 else UNITS[hundreds]}hundert"
    return head if rest == 0 else head + _below_hundred(rest, prefix=prefix)


def cardinal(n: int) -> str:
    """Spell a whole number from 0 to one million the way German writes it in one word.

    Raises:
        ValueError: If ``n`` is negative or above one million.
    """
    if not 0 <= n <= MILLION:
        raise ValueError(f"cannot spell {n}: only 0 to {MILLION}")
    if n == MILLION:
        return "einemillion"
    thousands, rest = divmod(n, 1000)
    if thousands == 0:
        return _below_thousand(rest, prefix=False)
    head = _below_thousand(thousands, prefix=True) + "tausend"
    return head if rest == 0 else head + _below_thousand(rest, prefix=False)


def year(n: int) -> str:
    """Spell a year from 1100 to 2099 as it is said: ``neunzehnhundertneunundneunzig``.

    Raises:
        ValueError: If ``n`` is outside 1100 to 2099.
    """
    if not MIN_YEAR <= n <= MAX_YEAR:
        raise ValueError(f"not a year between {MIN_YEAR} and {MAX_YEAR}: {n}")
    if n >= 2000:  # noqa: PLR2004  # the century that is said as thousands
        return cardinal(n)
    hundreds, rest = divmod(n, 100)
    head = f"{UNITS[hundreds]}hundert"
    return head if rest == 0 else head + _below_hundred(rest, prefix=False)


def _dictionary() -> pyphen.Pyphen:
    """Return the German hyphenation dictionary: a split needs one letter on each side."""
    return dictionary_of("de_DE")


HYPHENATION = Hyphenation(_dictionary, VOWELS, EXCEPTIONS)


def _spell_core(core: str) -> str:
    """Spell the numbers of the core of one word."""
    whole = is_lone_number(core)
    return NUMBER.sub(
        lambda m: spell_run(m.group(), whole=whole, cardinal=cardinal, year=year), core
    )


class German:
    """The German language module."""

    code = "de"
    name = "German"
    model = "wav2vec2-de"
    alphabet = ALPHABET
    together_two = "Beide"
    together_all = "Alle"

    def normalise(self, word: str) -> str:
        """Return the letters of ``word`` for the model: lower case, ``ß`` as ``ss``, no marks."""
        return fold(word, ALPHABET, REPLACEMENTS)

    def spell_numbers(self, text: str) -> str:
        """Write the numbers of ``text`` out, word by word.

        A word that is a lone number from 1100 to 2099 is a year; any other number up to a
        million is a cardinal, spelled in one word; digits inside a word (``4ever``) are spelled
        and joined to it; longer runs of digits are spelled digit by digit.
        """
        return spell_words(text, _spell_core)

    def syllables(self, word: str) -> list[str]:
        """Split ``word`` with the hyphenation dictionary; punctuation stays with its syllable."""
        return HYPHENATION.syllables(word)


GERMAN = German()
