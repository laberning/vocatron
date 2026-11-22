"""The conformance kit of language modules (ADR-0005): what every module must do.

A module brings its own fixtures (``Fixtures``, registered in ``FIXTURES``); the tests in
``tests/fast/core/languages/test_conformance.py`` run this kit over every registered module and
fail for a module without fixtures.
"""

import re
from dataclasses import dataclass

from vocatron.core.languages.base import LanguageModule
from vocatron.core.models import find_model

DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class Fixtures:
    """What a language module is checked against, written by its author.

    Attributes:
        normalise: Written words and the letters the model should hear.
        numbers: Texts with numbers and how they are spelled.
        syllables: Words and their syllables.
        words: More words (public-domain or invented) for the general checks.
    """

    normalise: dict[str, str]
    numbers: dict[str, str]
    syllables: dict[str, list[str]]
    words: list[str]


def check_metadata(module: LanguageModule) -> None:
    """The module names itself, its alphabet is clean and its model is in the registry."""
    assert re.fullmatch(r"[a-z]{2}", module.code), module.code
    assert module.name
    assert module.alphabet == "".join(sorted(set(module.alphabet)))  # no duplicates
    assert module.alphabet == module.alphabet.lower()
    assert " " not in module.alphabet and "|" not in module.alphabet
    for word in (module.together_two, module.together_all):  # the words for singing together
        assert word.strip() == word and word, word
        assert not DIGIT.search(word), word
    assert module.together_two != module.together_all
    spec = find_model(module.model)
    assert "alignment" in spec.purpose
    assert spec.licence


def check_normalise(module: LanguageModule, fixtures: Fixtures) -> None:
    """Normalisation gives the fixture's letters, only alphabet letters, and is stable."""
    for written, spoken in fixtures.normalise.items():
        assert module.normalise(written) == spoken, written
    for word in [*fixtures.normalise, *fixtures.words, "", " ", "42", "—", "'", "x-y"]:
        spoken = module.normalise(word)
        assert set(spoken) <= set(module.alphabet), word
        assert module.normalise(spoken) == spoken, word  # the round trip loses nothing more
        assert module.normalise(word.upper()) == module.normalise(word.lower()), word


def check_numbers(module: LanguageModule, fixtures: Fixtures) -> None:
    """Numbers are spelled as the fixture says, and nothing else changes."""
    for text, spelled in fixtures.numbers.items():
        assert module.spell_numbers(text) == spelled, text
        assert not DIGIT.search(module.spell_numbers(text)), text
        assert set(module.normalise(module.spell_numbers(text))) <= set(module.alphabet)
    for word in fixtures.words:
        assert module.spell_numbers(word) == word  # no digits, no change


def check_syllables(module: LanguageModule, fixtures: Fixtures) -> None:
    """Syllables are the fixture's, and always join to the word."""
    for word, parts in fixtures.syllables.items():
        assert module.syllables(word) == parts, word
    words = [*fixtures.syllables, *fixtures.words, "", "!", "42", "a-b", "(ja)"]
    for word in [*words, *(w.upper() for w in words), *(w.lower() for w in words)]:
        parts = module.syllables(word)
        assert "".join(parts) == word, word
        assert all(parts) or word == "", word
