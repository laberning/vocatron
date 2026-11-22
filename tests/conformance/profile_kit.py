"""The conformance kit of style profiles (ADR-0009): what every profile must do.

A profile is given as YAML text (a built-in profile or a fan's file). The kit checks that it
loads, names itself, that its colours have enough contrast, that its lines fit the safe area of
every output preset and that the layout rules hold on the sample lyrics and the folk songs. A look
made for CD+G (ADR-0029) is checked on the CD+G screen too, with the real font: the timing of the
packets depends on the shapes of the letters, which the fakes do not have. The checks are those of
``vocatron profiles check`` (``vocatron.core.profiles.check``); the kit asserts that they find
nothing. The tests in ``tests/fast/core/profiles/test_model_conformance.py`` run it over every
registered profile.
"""

from vocatron.core.measure import TextMeasurer, TextRasteriser
from vocatron.core.profiles.check import check_profile as find_problems
from vocatron.core.profiles.model import Profile, parse_profile
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser
from vocatron.engines.resources import PackageResources


def check_profile(
    name: str,
    text: str,
    measurer: TextMeasurer | None = None,
    rasteriser: TextRasteriser | None = None,
) -> Profile:
    """Run the kit on one profile and return it; a failing check raises ``AssertionError``."""
    font = PackageResources().font_file()
    problems = find_problems(
        name,
        text,
        expected_name=name,
        overrides={},
        measurer=measurer or PillowMeasurer(font),
        rasteriser=rasteriser or PillowRasteriser(font),
    )
    assert problems == []
    return parse_profile(name, text)
