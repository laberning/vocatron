"""Stage 1: text is measured in the bundled font the way libass sizes it (ADR-0009)."""

from pathlib import Path

import pytest

from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.resources import FONT_FILE, PackageResources

EM_PER_CELL = 1000 / 1519  # Noto Sans: units per em over Windows ascent plus descent


@pytest.fixture(scope="module")
def measurer() -> PillowMeasurer:
    return PillowMeasurer(PackageResources().font_file())


def test_the_bundled_font_is_where_the_package_says() -> None:
    resources = PackageResources()
    assert resources.font_file() == resources.fonts_dir() / FONT_FILE
    assert resources.font_file().is_file()
    assert (resources.fonts_dir() / "OFL.txt").is_file()  # the licence travels with the font


def test_nothing_has_no_width(measurer: PillowMeasurer) -> None:
    assert measurer.width("", 50.0) == 0.0


def test_the_width_is_linear_in_the_font_size(measurer: PillowMeasurer) -> None:
    assert measurer.width("Hamburger Wiese", 80.0) == pytest.approx(
        2 * measurer.width("Hamburger Wiese", 40.0)
    )


def test_a_known_text_has_the_width_libass_draws_at_that_size(measurer: PillowMeasurer) -> None:
    # 8.956 em at an em of 0.6583 * 60 px: libass drew this text 349 px wide (stage 2 checks it)
    assert measurer.width("Hamburger Wiese", 60.0) == pytest.approx(
        8.956 * 60 * EM_PER_CELL, rel=0.01
    )


def test_wide_letters_are_wider_than_narrow_ones(measurer: PillowMeasurer) -> None:
    assert measurer.width("WWWW", 50.0) > measurer.width("iiii", 50.0)


def test_a_space_has_a_width_and_text_is_the_sum_of_its_parts_up_to_kerning(
    measurer: PillowMeasurer,
) -> None:
    assert measurer.width(" ", 50.0) > 0
    whole = measurer.width("ab cd", 50.0)
    parts = measurer.width("ab", 50.0) + measurer.width(" ", 50.0) + measurer.width("cd", 50.0)
    assert whole == pytest.approx(parts, rel=0.03)


def test_the_font_is_read_once_and_only_when_needed(tmp_path: Path) -> None:
    measurer = PillowMeasurer(tmp_path / "missing.ttf")  # nothing is read before the first width
    with pytest.raises(OSError, match="missing.ttf|cannot open"):
        measurer.width("a", 10.0)


def test_german_letters_are_in_the_font(measurer: PillowMeasurer) -> None:
    assert measurer.width("äöüß ÄÖÜ", 50.0) > measurer.width("aous AOU", 50.0) * 0.9


def test_a_missing_built_in_profile_is_none(tmp_path: Path) -> None:
    assert PackageResources(tmp_path).builtin_profile("two-line-turns") is None
    assert PackageResources().builtin_profile("no-such-profile") is None
    assert PackageResources().builtin_profile("two-line-turns") is not None
