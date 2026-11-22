"""Stage 1: the conformance kit, run over every registered language module (ADR-0005)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from conformance import FIXTURES
from conformance import language_kit as kit
from vocatron.core.languages import LANGUAGES
from vocatron.core.languages.base import LanguageModule

MODULES = list(LANGUAGES.values())
ids = [m.code for m in MODULES]


def test_every_registered_language_has_fixtures_and_none_is_left_over() -> None:
    assert set(LANGUAGES) == set(FIXTURES)


@pytest.mark.parametrize("module", MODULES, ids=ids)
def test_metadata(module: LanguageModule) -> None:
    kit.check_metadata(module)


@pytest.mark.parametrize("module", MODULES, ids=ids)
def test_normalisation(module: LanguageModule) -> None:
    kit.check_normalise(module, FIXTURES[module.code])


@pytest.mark.parametrize("module", MODULES, ids=ids)
def test_number_spelling(module: LanguageModule) -> None:
    kit.check_numbers(module, FIXTURES[module.code])


@pytest.mark.parametrize("module", MODULES, ids=ids)
def test_syllables(module: LanguageModule) -> None:
    kit.check_syllables(module, FIXTURES[module.code])


@pytest.mark.parametrize("module", MODULES, ids=ids)
@given(text=st.text(max_size=30))
def test_any_text_is_handled(module: LanguageModule, text: str) -> None:
    spoken = module.normalise(module.spell_numbers(text))
    assert set(spoken) <= set(module.alphabet)
    assert "".join(module.syllables(text)) == text
    assert not kit.DIGIT.search(module.spell_numbers(text))
