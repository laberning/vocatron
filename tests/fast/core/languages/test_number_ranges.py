"""Stage 1: what every language's number speller refuses (the shared range, ADR-0005)."""

from collections.abc import Callable

import pytest

from vocatron.core.languages import de, en
from vocatron.core.languages.base import MAX_YEAR, MILLION, MIN_YEAR

CARDINALS: list[Callable[[int], str]] = [de.cardinal, en.cardinal]
YEARS: list[Callable[[int], str]] = [de.year, en.year]


@pytest.mark.parametrize("cardinal", CARDINALS, ids=["de", "en"])
@pytest.mark.parametrize("n", [-1, MILLION + 1])
def test_numbers_out_of_range_are_an_error(cardinal: Callable[[int], str], n: int) -> None:
    with pytest.raises(ValueError, match="only 0 to"):
        cardinal(n)


@pytest.mark.parametrize("year", YEARS, ids=["de", "en"])
@pytest.mark.parametrize("n", [MIN_YEAR - 1, MAX_YEAR + 1])
def test_a_year_out_of_range_is_an_error(year: Callable[[int], str], n: int) -> None:
    with pytest.raises(ValueError, match="not a year"):
        year(n)


@pytest.mark.parametrize("n", [-1, MILLION + 1])
def test_an_english_ordinal_out_of_range_is_an_error(n: int) -> None:
    with pytest.raises(ValueError, match="only 0 to"):
        en.ordinal(n)
