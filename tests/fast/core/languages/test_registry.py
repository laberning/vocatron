"""Stage 1: the registry of supported languages."""

import pytest

from vocatron.core import languages
from vocatron.core.languages import (
    DEFAULT_LANGUAGE,
    LANGUAGES,
    Detected,
    is_supported,
    unsupported_message,
)
from vocatron.core.languages.base import LanguageModule
from vocatron.core.languages.de import GERMAN
from vocatron.core.languages.en import ENGLISH


class French:
    """A stand-in for a third language module."""

    code = "fr"
    name = "French"
    model = "wav2vec2-fr"
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    together_two = "Les deux"
    together_all = "Tous"

    def normalise(self, word: str) -> str:
        return word.lower()

    def spell_numbers(self, text: str) -> str:
        return text

    def syllables(self, word: str) -> list[str]:
        return [word]


def test_german_and_english_are_supported_and_others_are_not() -> None:
    assert is_supported("de")
    assert is_supported("en")
    assert not is_supported("fr")
    assert set(LANGUAGES) == {"de", "en"}
    assert LANGUAGES["de"] is GERMAN
    assert LANGUAGES["en"] is ENGLISH
    assert DEFAULT_LANGUAGE == "de"


def test_the_message_names_the_found_and_the_supported_languages() -> None:
    message = unsupported_message(Detected("fr", "French"))
    assert "French (fr)" in message
    assert "supported: German, English." in message


def test_the_message_lists_every_supported_language(monkeypatch: pytest.MonkeyPatch) -> None:
    module: LanguageModule = French()
    monkeypatch.setitem(languages.LANGUAGES, "fr", module)
    assert "supported: German, English, French." in unsupported_message(Detected("es", "Spanish"))
