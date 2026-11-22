"""English: model alphabet, normalisation, number spelling and syllables (ADR-0005, ADR-0016)."""

import re

import pyphen

from vocatron.core.languages.base import (
    HYPHENS,
    MAX_YEAR,
    MILLION,
    MIN_YEAR,
    NUMBER,
    Hyphenation,
    dictionary_of,
    fold,
    is_cardinal,
    is_lone_number,
    spell_run,
    spell_words,
)

ALPHABET = "abcdefghijklmnopqrstuvwxyz"
"""The letters of the English wav2vec2 model (its vocabulary also holds ``'``, which is never a
target: ``normalise`` drops apostrophes)."""
REPLACEMENTS = {"æ": "ae", "œ": "oe"}
VOWELS = frozenset("aeiouy")
EXCEPTIONS: dict[str, tuple[str, ...]] = {
    "maybe": ("may", "be"),
    "mary": ("ma", "ry"),
    "above": ("a", "bove"),
    "tonight": ("to", "night"),
    "away": ("a", "way"),
    "alone": ("a", "lone"),
    "around": ("a", "round"),
    "across": ("a", "cross"),
    "idea": ("I", "de", "a"),
    "over": ("o", "ver"),
    "crazy": ("cra", "zy"),
    "heavy": ("hea", "vy"),
    "city": ("ci", "ty"),
    "eleven": ("e", "lev", "en"),
    "evening": ("eve", "ning"),
    "gonna": ("gon", "na"),
    "gimme": ("gim", "me"),
    "lemme": ("lem", "me"),
}
"""Words the hyphenation dictionary gets wrong, by lower-case word, with their syllables (the
word is cut at the same places and keeps its own case)."""
APOSTROPHES = "'’"
ENDINGS = frozenset({"s", "t", "d", "m", "ll", "re", "ve", "em"})
"""What follows the apostrophe of a contraction and is sung with the word before it
(``don't``, ``you're``, ``I've``)."""

THOUSANDS_START = 2000
THOUSANDS_END = 2010
HUNDRED = 100
TEN = 10
UNITS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty", 7: "seventy"}
TENS |= {8: "eighty", 9: "ninety"}
ORDINALS = {
    "one": "first",
    "two": "second",
    "three": "third",
    "five": "fifth",
    "eight": "eighth",
    "nine": "ninth",
    "twelve": "twelfth",
}
GROUPED = re.compile(r"\d{1,3}(?:,\d{3})+")
ORDINAL = re.compile(r"(\d+)(?:st|nd|rd|th)", re.IGNORECASE)
DECADE = re.compile(r"(\d{2}|\d{4})s", re.IGNORECASE)


def _below_hundred(n: int) -> str:
    """Spell 0..99: ``twenty-one``."""
    if n < len(UNITS):
        return UNITS[n]
    tens, ones = divmod(n, 10)
    return TENS[tens] if ones == 0 else f"{TENS[tens]}-{UNITS[ones]}"


def _below_thousand(n: int) -> str:
    """Spell 0..999 as it is sung: ``one hundred and one``."""
    hundreds, rest = divmod(n, 100)
    if hundreds == 0:
        return _below_hundred(rest)
    head = f"{UNITS[hundreds]} hundred"
    return head if rest == 0 else f"{head} and {_below_hundred(rest)}"


def cardinal(n: int) -> str:
    """Spell a whole number from 0 to one million as it is sung: ``one thousand and one``.

    Raises:
        ValueError: If ``n`` is negative or above one million.
    """
    if not 0 <= n <= MILLION:
        raise ValueError(f"cannot spell {n}: only 0 to {MILLION}")
    if n == MILLION:
        return "one million"
    thousands, rest = divmod(n, 1000)
    if thousands == 0:
        return _below_thousand(rest)
    head = _below_thousand(thousands) + " thousand"
    if rest == 0:
        return head
    return (
        f"{head} and {_below_hundred(rest)}"
        if rest < HUNDRED
        else f"{head} {_below_thousand(rest)}"
    )


def year(n: int) -> str:
    """Spell a year from 1100 to 2099 as it is said: ``nineteen ninety-nine``.

    The years 2000 to 2009 are ``two thousand five``, a full hundred is ``nineteen hundred``,
    a rest below ten is ``nineteen oh five``.

    Raises:
        ValueError: If ``n`` is outside 1100 to 2099.
    """
    if not MIN_YEAR <= n <= MAX_YEAR:
        raise ValueError(f"not a year between {MIN_YEAR} and {MAX_YEAR}: {n}")
    if THOUSANDS_START <= n < THOUSANDS_END:
        return (
            "two thousand" if n == THOUSANDS_START else f"two thousand {UNITS[n - THOUSANDS_START]}"
        )
    hundreds, rest = divmod(n, HUNDRED)
    head = _below_hundred(hundreds)
    if rest == 0:
        return f"{head} hundred"
    return f"{head} oh {UNITS[rest]}" if rest < TEN else f"{head} {_below_hundred(rest)}"


def ordinal(n: int) -> str:
    """Spell the ordinal of ``n`` (0 to one million): ``twenty-first``, ``one hundredth``.

    Raises:
        ValueError: If ``n`` is negative or above one million.
    """
    words = cardinal(n)
    split = max(words.rfind(" "), words.rfind("-")) + 1  # the last word starts here
    front, last = words[:split], words[split:]
    if last in ORDINALS:
        return front + ORDINALS[last]
    return front + (last[:-1] + "ieth" if last.endswith("y") else last + "th")


def _plural(words: str) -> str:
    """Put the last word of a spelled number in the plural: ``sixty`` as ``sixties``."""
    return words[:-1] + "ies" if words.endswith("y") else words + "s"


def _decade(digits: str) -> str | None:
    """Spell the digits of a decade (``60``, ``1960``) in the plural, else return ``None``."""
    n = int(digits)
    if n % TEN != 0:
        return None
    if len(digits) == 2:  # noqa: PLR2004  # 60s
        return _plural(cardinal(n))
    return _plural(year(n)) if MIN_YEAR <= n <= MAX_YEAR else None


def _run(match: re.Match[str], *, whole: bool) -> str:
    """Spell one run of digits of a word."""
    return spell_run(match.group(), whole=whole, cardinal=cardinal, year=year)


def _spell_core(core: str) -> str:
    """Spell the numbers of the core of one word (see ``English.spell_numbers``)."""
    if GROUPED.fullmatch(core):  # 1,999 is a cardinal, never a year
        return NUMBER.sub(lambda m: _run(m, whole=False), core.replace(",", ""))
    # The length test first: int() refuses strings of thousands of digits.
    if (found := ORDINAL.fullmatch(core)) and is_cardinal(found.group(1)):
        return ordinal(int(found.group(1)))
    elif (found := DECADE.fullmatch(core)) and (decade := _decade(found.group(1))):
        return decade
    whole = is_lone_number(core)
    return NUMBER.sub(lambda m: _run(m, whole=whole), core)


def _dictionary() -> pyphen.Pyphen:
    """Return the American English hyphenation dictionary: a split needs a letter on each side."""
    return dictionary_of("en_US")


HYPHENATION = Hyphenation(
    _dictionary,
    VOWELS,
    EXCEPTIONS,
    joiners=HYPHENS + APOSTROPHES,
    glued=APOSTROPHES,
    endings=ENDINGS,
    lone_edges=True,
)


class English:
    """The English language module."""

    code = "en"
    name = "English"
    model = "wav2vec2-en"
    alphabet = ALPHABET
    together_two = "Both"
    together_all = "All"

    def normalise(self, word: str) -> str:
        """Return the letters of ``word`` for the model: lower case, no marks, no apostrophes."""
        return fold(word, ALPHABET, REPLACEMENTS)

    def spell_numbers(self, text: str) -> str:
        """Write the numbers of ``text`` out, word by word, as they are sung.

        A word that is a lone number from 1100 to 2099 is a year (``nineteen oh five``); any
        other number up to a million is a cardinal (``one hundred and one``); ``21st`` is an
        ordinal, ``60s`` and ``1960s`` are decades; digits inside a word (``4ever``) are spelled
        and joined to it; longer runs of digits are spelled digit by digit.
        """
        return spell_words(text, _spell_core)

    def syllables(self, word: str) -> list[str]:
        """Split ``word`` with the hyphenation dictionary; punctuation stays with its syllable.

        An apostrophe stays with the syllable before it, and the ending of a contraction
        (``'t``, ``'re``, ``'ve``) is sung with its word.
        """
        return HYPHENATION.syllables(word)


ENGLISH = English()
