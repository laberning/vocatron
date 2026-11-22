"""Stage 2: the real lingua detector on public-domain song texts (German and English)."""

from fakes.lyrics import ENTCHEN, HAENSCHEN, MARY, TWINKLE, VOGEL
from vocatron.engines.language import LinguaDetector

GRACE = (
    "Amazing grace! how sweet the sound\n"
    "That saved a wretch like me!\n"
    "I once was lost, but now am found;\n"
    "Was blind, but now I see.\n"
)
ROW = (
    "Row, row, row your boat\n"
    "Gently down the stream\n"
    "Merrily, merrily, merrily, merrily\n"
    "Life is but a dream\n"
)


def code_of(detector: LinguaDetector, text: str) -> str | None:
    found = detector.detect(text)
    return None if found is None else found.code


def test_lingua_recognises_german_folk_songs() -> None:
    detector = LinguaDetector()
    for text in (ENTCHEN, VOGEL):
        found = detector.detect(text)
        assert found is not None
        assert found.code == "de"


def test_lingua_recognises_english_public_domain_songs() -> None:
    detector = LinguaDetector()
    for text in (TWINKLE, MARY, GRACE, ROW):
        found = detector.detect(text)
        assert found is not None
        assert (found.code, found.name) == ("en", "English")


def test_a_short_english_line_is_recognised_but_a_single_word_is_not_to_be_trusted() -> None:
    detector = LinguaDetector()
    assert code_of(detector, "Mary had a little lamb") == "en"
    # One word or an exclamation has too little to go on: lingua answers with some other
    # language or none at all. That is what ``--language`` and ``lyrics.language`` are for.
    for text in ("Hello", "Oh yeah", "la la la"):
        code = code_of(detector, text)
        assert code is None or len(code) == 2


def test_a_german_song_with_one_english_line_is_still_german() -> None:
    detector = LinguaDetector()
    for text in (ENTCHEN, HAENSCHEN, VOGEL):
        mixed = text + "Twinkle, twinkle, little star\n"
        assert code_of(detector, mixed) == "de"
