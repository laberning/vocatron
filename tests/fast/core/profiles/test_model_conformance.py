"""Stage 1: every registered style profile passes the conformance kit (ADR-0009)."""

import pytest

from conformance.profile_kit import check_profile
from fakes.resources import FakeResources
from vocatron.core.profiles.model import (
    BUILTIN_PROFILES,
    CLASSIC_PROFILES,
    MAX_POP_SCALE,
    VIDEO_ONLY_PROFILES,
    effects_used,
    made_for_cdg,
)
from vocatron.engines.resources import PackageResources


@pytest.mark.parametrize("name", CLASSIC_PROFILES)
def test_a_classic_profile_passes_the_kit(name: str) -> None:
    text = FakeResources().builtin_profile(name)
    assert text is not None, f"profiles/{name}.yaml is missing"
    checked = check_profile(name, text)  # with the CD+G check, since every classic look has it
    assert checked.name == name
    assert made_for_cdg(checked), f"profiles/{name}.yaml is a classic look: made_for_cdg: true"
    assert effects_used(checked) == [], f"profiles/{name}.yaml is a classic look: no effects"


@pytest.mark.parametrize("name", VIDEO_ONLY_PROFILES)
def test_a_video_only_profile_passes_the_kit_and_uses_effects(name: str) -> None:
    text = FakeResources().builtin_profile(name)
    assert text is not None, f"profiles/{name}.yaml is missing"
    checked = check_profile(name, text)
    assert checked.name == name
    assert checked.cdg is None, f"profiles/{name}.yaml is for the video only: no cdg section"
    assert effects_used(checked), f"profiles/{name}.yaml is a modern look: it uses an effect"


def test_a_video_only_look_with_the_largest_pop_passes_the_kit() -> None:
    # no built-in look pops, so an own look with every effect of neon and the largest pop: its
    # lines must still fit every preset with the room for the growing word (ADR-0032)
    text = FakeResources().builtin_profile("neon") or ""
    checked = check_profile("neon", text + f"pop: {{scale: {MAX_POP_SCALE}, time: 0.25}}\n")
    assert "pop" in effects_used(checked)


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_the_shipped_package_has_every_built_in_profile(name: str) -> None:
    assert PackageResources().builtin_profile(name) is not None


@pytest.mark.parametrize("name", CLASSIC_PROFILES)
def test_a_look_without_the_marker_passes_the_kit_without_the_cdg_check(name: str) -> None:
    text = FakeResources().builtin_profile(name) or ""
    mp4_only = text[: text.index("# On CD+G")]
    assert not made_for_cdg(check_profile(name, mp4_only))
