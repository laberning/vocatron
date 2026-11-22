"""Stage 1: the effect sections of a profile: defaults, limits, the refusal with CD+G (ADR-0032)."""

import pytest
from pydantic import JsonValue

from fakes.resources import FakeResources
from vocatron.core.profiles.model import (
    CLASSIC_PROFILES,
    EFFECT_KEYS,
    VIDEO_ONLY_PROFILES,
    ProfileError,
    background_extremes,
    digest_json,
    effects_used,
    parse_profile,
    profile_problems,
)

RESOURCES = FakeResources()
CLASSIC = RESOURCES.builtin_profile("two-line-turns") or ""
NEON = RESOURCES.builtin_profile("neon") or ""
LYRIC = RESOURCES.builtin_profile("lyric-video") or ""


def messages(text: str, overrides: dict[str, JsonValue] | None = None) -> list[str]:
    with pytest.raises(ProfileError) as error:
        parse_profile("my.yaml", text, overrides)
    return error.value.messages


@pytest.mark.parametrize("name", CLASSIC_PROFILES)
def test_the_classic_looks_use_no_effect(name: str) -> None:
    assert effects_used(parse_profile(name, RESOURCES.builtin_profile(name) or "")) == []


def test_the_default_of_every_effect_leaves_it_off() -> None:
    look = parse_profile("my.yaml", CLASSIC)
    assert (look.glow.sung, look.glow.colour) == (0.0, None)
    assert look.pop.scale == 1.0
    assert look.transition.form == "none"
    assert look.upcoming.dim == 0.0
    assert look.background_motion.colours == []
    assert effects_used(look) == []


def test_the_video_only_looks_use_effects_and_have_no_cdg_section() -> None:
    names = {
        name: parse_profile(name, RESOURCES.builtin_profile(name) or "")
        for name in VIDEO_ONLY_PROFILES
    }
    assert effects_used(names["neon"]) == ["glow", "transition", "background_motion"]
    assert effects_used(names["lyric-video"]) == ["transition", "upcoming"]
    assert all(look.cdg is None for look in names.values())


@pytest.mark.parametrize(
    ("override", "key"),
    [
        ({"pop": {"scale": 1.16}}, "pop.scale"),
        ({"pop": {"scale": 0.9}}, "pop.scale"),
        ({"pop": {"time": 0}}, "pop.time"),
        ({"glow": {"sung": 1.01}}, "glow.sung"),
        ({"glow": {"sung": -0.1}}, "glow.sung"),
        ({"glow": {"colour": "red"}}, "glow.colour"),
        ({"upcoming": {"dim": 0.81}}, "upcoming.dim"),
        ({"transition": {"form": "wobble"}}, "transition.form"),
        ({"transition": {"time": 1.5}}, "transition.time"),
        ({"background_motion": {"colours": ["#000000"]}}, "background_motion.colours"),
        ({"background_motion": {"colours": ["#000000"] * 5}}, "background_motion.colours"),
        ({"background_motion": {"colours": ["#000000", "#111111"], "speed": 2}}, "speed"),
        ({"pop": {"speed": 1}}, "pop.speed"),
    ],
)
def test_an_effect_value_outside_its_limits_is_refused_at_its_key(
    override: dict[str, JsonValue], key: str
) -> None:
    (message,) = messages(NEON, override)
    assert message.startswith("profile_overrides."), message
    assert key.rsplit(".", maxsplit=1)[-1] in message


def test_the_limits_themselves_are_allowed() -> None:
    look = parse_profile(
        "my.yaml",
        NEON,
        {
            "pop": {"scale": 1.15},
            "glow": {"sung": 1.0},
            "upcoming": {"dim": 0.8},
            "background_motion": {"colours": ["#000000", "#111111", "#222222", "#333333"]},
        },
    )
    assert (look.pop.scale, look.glow.sung, look.upcoming.dim) == (1.15, 1.0, 0.8)


@pytest.mark.parametrize(
    "override",
    [
        {"glow": {"sung": 0.5}},
        {"pop": {"scale": 1.1}},
        {"transition": {"form": "fade"}},
        {"upcoming": {"dim": 0.3}},
        {"background_motion": {"colours": ["#000000", "#101030"]}},
    ],
)
def test_an_effect_with_a_cdg_section_is_refused_where_the_section_is(
    override: dict[str, JsonValue],
) -> None:
    (message,) = messages(CLASSIC, override)
    assert message.startswith("my.yaml:")
    assert ": cdg: cannot be used with the effects " in message
    assert "leave the cdg section out" in message


def test_a_cdg_section_that_is_not_made_for_cdg_is_refused_too() -> None:
    (message,) = messages(NEON + "cdg: {made_for_cdg: false}\n")
    assert "cdg: cannot be used with the effects glow, transition, background_motion" in message


def test_an_effect_that_is_off_goes_with_a_cdg_section() -> None:
    look = parse_profile(
        "my.yaml", CLASSIC, {"pop": {"scale": 1.0}, "transition": {"form": "none"}}
    )
    assert look.cdg is not None


def test_a_classic_look_may_use_effects_once_its_cdg_section_is_gone() -> None:
    look = parse_profile("my.yaml", CLASSIC, {"cdg": None, "glow": {"sung": 0.5}})
    assert effects_used(look) == ["glow"]


def test_a_moving_background_is_judged_by_its_darkest_and_lightest_colour() -> None:
    plain = parse_profile("my.yaml", NEON)
    assert background_extremes(plain) == ["#04050c", "#061a2e"]
    assert background_extremes(parse_profile("my.yaml", LYRIC)) == ["#101014"]
    assert profile_problems(plain) == []
    light = parse_profile(
        "my.yaml", NEON, {"background_motion": {"colours": ["#000000", "#ccccee"]}}
    )
    problems = profile_problems(light)
    assert any(p.startswith("singer1.unsung has contrast") for p in problems)
    assert any(p.startswith("singer1.sung has contrast") for p in problems)


def test_a_dimmed_line_is_judged_as_unsung_text_at_its_opacity() -> None:
    assert profile_problems(parse_profile("my.yaml", LYRIC)) == []
    grey: dict[str, JsonValue] = {
        "colours": {"group": {"unsung": "#808080"}},
        "upcoming": {"dim": 0.5},
    }
    problems = profile_problems(parse_profile("my.yaml", LYRIC, grey))
    assert [p for p in problems if p.startswith("upcoming.dim")] == [
        "upcoming.dim dims the unsung text of group to contrast 2.1"
    ]


def test_the_digest_of_a_look_leaves_unused_effects_out() -> None:
    classic = parse_profile("my.yaml", CLASSIC)
    text = digest_json(classic, without=frozenset({"cdg"}))
    assert not any(f'"{key}"' in text for key in EFFECT_KEYS)
    assert '"cdg"' not in text
    neon = digest_json(parse_profile("my.yaml", NEON))
    assert '"glow"' in neon
    assert '"upcoming"' not in neon


def test_the_darkest_colour_of_a_moving_background_is_found_by_its_lightness() -> None:
    # "#10ff10" comes first in the order of the text, but "#200000" is darker
    look = parse_profile(
        "my.yaml", NEON, {"background_motion": {"colours": ["#10ff10", "#200000", "#0a0a0a"]}}
    )
    assert background_extremes(look) == ["#0a0a0a", "#10ff10"]
    reversed_order = parse_profile(
        "my.yaml", NEON, {"background_motion": {"colours": ["#200000", "#10ff10"]}}
    )
    assert background_extremes(reversed_order) == ["#200000", "#10ff10"]


def test_without_dim_the_unsung_text_is_not_judged_a_second_time() -> None:
    grey: dict[str, JsonValue] = {
        "colours": {"group": {"unsung": "#303030"}},
        "upcoming": {"dim": 0.0},
    }
    problems = profile_problems(parse_profile("my.yaml", LYRIC, grey))
    assert problems
    assert not [p for p in problems if p.startswith("upcoming.dim")]
