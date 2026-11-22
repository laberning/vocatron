"""The registry of supported languages (ADR-0005).

A song has one language, detected from its lyrics. Each supported language is a module
(``LanguageModule``) registered here: German (``de.py``) and English (``en.py``). A new module
passes the same conformance kit as the others (``tests/conformance``).
"""

from typing import NamedTuple

from vocatron.core.languages.base import LanguageModule
from vocatron.core.languages.de import GERMAN
from vocatron.core.languages.en import ENGLISH


class Detected(NamedTuple):
    """What the language detector found.

    Attributes:
        code: The ISO 639-1 code, lower case.
        name: The English name.
    """

    code: str
    name: str


LANGUAGES: dict[str, LanguageModule] = {GERMAN.code: GERMAN, ENGLISH.code: ENGLISH}
DEFAULT_LANGUAGE = GERMAN.code
"""The language assumed before a song's own is known (the settings pin, the benchmark)."""


def is_supported(code: str) -> bool:
    """Tell whether Vocatron supports the language with this code."""
    return code in LANGUAGES


def unsupported_message(detected: Detected) -> str:
    """Return the error for a song whose lyrics are in an unsupported language."""
    supported = ", ".join(language.name for language in LANGUAGES.values())
    return (
        f"the lyrics are in {detected.name} ({detected.code}), which Vocatron does not support "
        f"yet; supported: {supported}. A language is added as a module (ADR-0005)"
    )
