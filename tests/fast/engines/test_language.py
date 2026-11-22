"""Stage 1: the lingua detector, with lingua replaced by a stand-in (no models are loaded)."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from vocatron.engines.language import LinguaDetector


class FakeBuilder:
    built = 0

    @classmethod
    def from_all_languages(cls) -> FakeBuilder:
        return cls()

    def build(self) -> FakeBuilder:
        FakeBuilder.built += 1
        return self

    def detect_language_of(self, text: str) -> SimpleNamespace | None:
        if not text.strip():
            return None
        german = SimpleNamespace(iso_code_639_1=SimpleNamespace(name="DE"), name="GERMAN")
        return german


class FakeLingua(ModuleType):
    LanguageDetectorBuilder = FakeBuilder


@pytest.fixture
def lingua(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "lingua", FakeLingua("lingua"))
    FakeBuilder.built = 0


@pytest.mark.usefixtures("lingua")
def test_the_detector_is_built_once_and_names_the_language() -> None:
    detector = LinguaDetector()
    assert FakeBuilder.built == 0  # lingua loads when it is first needed
    found = detector.detect("Alle meine Entchen")
    assert found is not None
    assert (found.code, found.name) == ("de", "German")
    detector.detect("Hänschen klein")
    assert FakeBuilder.built == 1


@pytest.mark.usefixtures("lingua")
def test_a_text_without_a_language_gives_none() -> None:
    assert LinguaDetector().detect("  ") is None
