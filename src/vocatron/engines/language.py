"""Language detection with lingua (ADR-0005). The heavy import happens on first use."""

from typing import TYPE_CHECKING

from vocatron.core.languages import Detected

if TYPE_CHECKING:
    from lingua import LanguageDetector


class LinguaDetector:
    """Detects the language of lyrics with lingua-language-detector."""

    def __init__(self) -> None:
        """Create the detector; lingua is loaded when it is first needed."""
        self._detector: LanguageDetector | None = None

    def detect(self, text: str) -> Detected | None:
        """Return the most likely language of ``text``, or ``None`` when lingua cannot tell."""
        if self._detector is None:
            from lingua import LanguageDetectorBuilder  # noqa: PLC0415  # heavy import, only when used

            self._detector = LanguageDetectorBuilder.from_all_languages().build()
        language = self._detector.detect_language_of(text)
        if language is None:
            return None
        return Detected(language.iso_code_639_1.name.lower(), language.name.title())
