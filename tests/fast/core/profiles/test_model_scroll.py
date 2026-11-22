"""Stage 1: the scroll mode of a profile: defaults, limits, refusals, the digest (ADR-0033)."""

import pytest
from pydantic import JsonValue

from fakes.resources import FakeResources
from vocatron.core.profiles.model import (
    Profile,
    ProfileError,
    Scroll,
    digest_json,
    parse_profile,
    profile_problems,
)

RESOURCES = FakeResources()
CLASSIC = RESOURCES.builtin_profile("two-line-turns") or ""
SCROLL = RESOURCES.builtin_profile("lyric-scroll") or ""
MODE: dict[str, JsonValue] = {"mode": "scroll"}


def messages(text: str, overrides: dict[str, JsonValue] | None = None) -> list[str]:
    with pytest.raises(ProfileError) as error:
        parse_profile("my.yaml", text, overrides)
    return error.value.messages


def scrolling(**overrides: JsonValue) -> Profile:
    """The classic look in scroll mode, without its CD+G section."""
    return parse_profile("my.yaml", CLASSIC, {"mode": "scroll", "cdg": None, **overrides})


def test_the_defaults_of_the_scroll_section() -> None:
    section = Scroll()
    assert (section.current, section.before, section.after, section.glide) == (0.42, 2, 3, 0.4)
    assert section.dim_sung is None
    assert section.min_glide is None
    assert section.shortest_glide == 0.3


@pytest.mark.parametrize(
    ("scroll", "shortest"),
    [
        ({}, 0.3),
        ({"glide": 0.2}, 0.2),
        ({"glide": 0.25}, 0.25),
        ({"glide": 1.0}, 0.3),
        ({"glide": 0.2, "min_glide": 0.1}, 0.1),
        ({"glide": 0.8, "min_glide": 0.6}, 0.6),
    ],
)
def test_min_glide_left_out_is_the_smaller_of_its_default_and_glide(
    scroll: dict[str, JsonValue], shortest: float
) -> None:
    look = scrolling(scroll=scroll)
    assert look.scroll.shortest_glide == shortest
    assert profile_problems(look) == []


def test_a_look_in_line_mode_has_the_default_section() -> None:
    assert parse_profile("my.yaml", CLASSIC).scroll == Scroll()


def test_lyric_scroll_has_its_shipped_values() -> None:
    look = parse_profile("lyric-scroll", SCROLL)
    assert (look.mode, look.line_rows, look.cdg) == ("scroll", 2, None)
    assert (look.scroll.current, look.scroll.before, look.scroll.after) == (0.42, 2, 3)
    assert look.upcoming.dim == 0.5 and look.dim_sung == 0.5
    assert look.transition.form == "none"
    assert look.background_motion.colours
    assert profile_problems(look) == []


def test_sung_lines_are_dimmed_like_upcoming_lines_unless_the_section_says_otherwise() -> None:
    assert scrolling(upcoming={"dim": 0.3}).dim_sung == 0.3
    assert scrolling(upcoming={"dim": 0.3}, scroll={"dim_sung": 0.6}).dim_sung == 0.6
    assert scrolling(upcoming={"dim": 0.3}, scroll={"dim_sung": 0.0}).dim_sung == 0.0


@pytest.mark.parametrize(
    ("override", "key"),
    [
        ({"current": 0.19}, "current"),
        ({"current": 0.81}, "current"),
        ({"before": -1}, "before"),
        ({"before": 3}, "before"),
        ({"after": 0}, "after"),
        ({"after": 5}, "after"),
        ({"glide": 0.19}, "glide"),
        ({"glide": 1.01}, "glide"),
        ({"min_glide": 0.09}, "min_glide"),
        ({"min_glide": 1.01}, "min_glide"),
        ({"glide": 0.4, "min_glide": 0.5}, "min_glide"),
        ({"glide": 0.2, "min_glide": 0.3}, "min_glide"),
        ({"dim_sung": 0.81}, "dim_sung"),
        ({"dim_sung": -0.1}, "dim_sung"),
        ({"speed": 1}, "speed"),
    ],
)
def test_a_scroll_value_outside_its_limits_is_refused_at_its_key(
    override: dict[str, JsonValue], key: str
) -> None:
    (message,) = messages(SCROLL, {"scroll": override})
    assert message.startswith("profile_overrides.scroll."), message
    assert key in message


def test_the_limits_themselves_are_allowed() -> None:
    low: dict[str, JsonValue] = {
        "current": 0.2, "before": 0, "after": 1, "glide": 0.2, "min_glide": 0.1, "dim_sung": 0
    }  # fmt: skip
    high: dict[str, JsonValue] = {
        "current": 0.8, "before": 2, "after": 4, "glide": 1.0, "min_glide": 1.0, "dim_sung": 0.8
    }  # fmt: skip
    assert scrolling(scroll=low).scroll.glide == 0.2
    assert scrolling(scroll=high).scroll.glide == 1.0
    assert scrolling(scroll=low).scroll.shortest_glide == 0.1
    assert scrolling(scroll=high).scroll.shortest_glide == 1.0


def test_a_scroll_section_needs_the_mode() -> None:
    (message,) = messages(CLASSIC, {"scroll": {"after": 2}})
    assert "the scroll section needs mode: scroll" in message


@pytest.mark.parametrize(
    ("override", "wanted"),
    [
        ({"preview": {"show": True}, "slots": 1}, "preview.show"),
        ({"page": {"min_lines": 1, "slot_per_row": True}, "line_rows": 2}, "slot_per_row"),
        ({"page": {"min_lines": 2}}, "page section"),
        ({"transition": {"form": "fade"}}, "transition"),
    ],
)
def test_the_settings_of_other_modes_are_refused_in_scroll_mode(
    override: dict[str, JsonValue], wanted: str
) -> None:
    found = messages(CLASSIC, {"mode": "scroll", "cdg": None, **override})
    assert any(wanted in message for message in found), found


def test_a_scroll_look_with_a_cdg_section_is_refused_at_the_section() -> None:
    found = messages(CLASSIC, MODE)
    assert len(found) == 1
    assert "cdg" in found[0] and "mode: scroll" in found[0]
    assert "leave the cdg section out" in found[0]


def test_a_scroll_look_with_effects_and_a_cdg_section_names_both_reasons() -> None:
    found = messages(CLASSIC, {"mode": "scroll", "upcoming": {"dim": 0.3}})
    assert len(found) == 2
    assert any("effects upcoming" in m for m in found)
    assert any("mode: scroll" in m for m in found)


def test_the_slots_do_not_matter_in_scroll_mode() -> None:
    assert scrolling(slots=6).mode == "scroll"
    assert scrolling(slots=1).mode == "scroll"


def test_the_digest_of_a_look_that_does_not_scroll_leaves_the_section_out() -> None:
    assert '"scroll"' not in digest_json(parse_profile("my.yaml", CLASSIC))
    assert '"scroll"' not in digest_json(parse_profile("my.yaml", CLASSIC), without=frozenset())
    scroll = parse_profile("lyric-scroll", SCROLL)
    assert '"scroll":{"current":0.42' in digest_json(scroll)
