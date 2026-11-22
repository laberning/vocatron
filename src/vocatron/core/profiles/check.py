"""Check a style profile without rendering anything (ADR-0019).

A profile is good when it loads, names itself, passes the contrast rules, fits the safe area of
every output preset at its sizes, and the layout rules hold on the sample lyrics and the folk
songs (``vocatron.core.layout.sample``). A look made for CD+G (the ``cdg`` section with the marker,
ADR-0029) is checked on the CD+G screen too (``vocatron.core.cdg.check``). A problem a key causes
is reported as
``file:line:column: key: message``; a broken layout rule is a bug of the layout, not of the file,
and names file and preset only.
"""

from collections.abc import Mapping

from pydantic import JsonValue

from vocatron.core.cdg.check import check_cdg
from vocatron.core.config_errors import Issue
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.sample import sample_scenes
from vocatron.core.measure import TextMeasurer, TextRasteriser
from vocatron.core.presets import PRESETS
from vocatron.core.profiles.model import (
    Profile,
    ProfileError,
    describe_issues,
    made_for_cdg,
    parse_profile,
    profile_issues,
)
from vocatron.core.scene import Shortfall
from vocatron.core.yaml_pos import parse_yaml

FIT_KEYS = {"too-wide": ("font", "min_size"), "block": ("slots",)}
"""The key to change when a shortfall of that kind is reported."""
SCROLL_BLOCK_KEY = ("font", "size")
"""The key to change when the line being sung of a scrolling look does not fit (ADR-0033)."""


def _fit_issue(shortfall: Shortfall, preset: str, profile: Profile) -> Issue:
    """Locate a shortfall of the fit at the key that fixes it."""
    where = SCROLL_BLOCK_KEY if shortfall.kind == "block" and profile.mode == "scroll" else None
    return Issue(where or FIT_KEYS[shortfall.kind], f"{shortfall.message} (preset {preset})")


def check_profile(
    label: str,
    text: str,
    *,
    expected_name: str,
    overrides: Mapping[str, JsonValue],
    measurer: TextMeasurer,
    rasteriser: TextRasteriser,
) -> list[str]:
    """Check a profile and return its problems, ready to print; empty when it is fine.

    Args:
        label: The file name for the messages.
        text: The YAML text.
        expected_name: The name the profile must give itself (the file name without ending).
        overrides: The ``profile_overrides`` of the configuration, applied before the check.
        measurer: Measures the text for the fit; the real font gives the real answer.
        rasteriser: Draws the letters for the CD+G check of a look made for CD+G.
    """
    try:
        profile = parse_profile(label, text, overrides)
    except ProfileError as error:
        return error.messages
    _, positions = parse_yaml(label, text)
    issues: list[Issue] = []
    if profile.name != expected_name:
        issues.append(
            Issue(("name",), f"is {profile.name!r}, but the profile is {expected_name!r}")
        )
    issues += profile_issues(profile)
    layout_bugs: dict[str, None] = {}  # in order, without repeats
    for preset in PRESETS:
        for title, scene in sample_scenes(profile, measurer, preset):
            issues += [
                _fit_issue(s, preset, profile) for s in scene.shortfalls if s.kind in FIT_KEYS
            ]
            for found in scene_findings(scene, profile):
                layout_bugs[f"{label}: preset {preset}, {title}: {found}"] = None
    if made_for_cdg(profile):
        found = check_cdg(profile, measurer, rasteriser)
        issues += found.issues
        layout_bugs.update(dict.fromkeys(f"{label}: {bug}" for bug in found.bugs))
    return [*describe_issues(label, _unique(issues), positions, overrides), *layout_bugs]


def _unique(issues: list[Issue]) -> list[Issue]:
    """Return ``issues`` without repeats, in order."""
    return list(dict.fromkeys(issues))
