"""Stage 1: a profile value is a name or a path (ADR-0019); copies of built-in profiles."""

import pytest

from fakes.resources import FakeResources
from vocatron.core.profiles.copy import copy_text, default_name, valid_name
from vocatron.core.profiles.model import BUILTIN_PROFILES, is_name, override_keys, parse_profile


@pytest.mark.parametrize("spec", ["mine", "two-line-turns", "my_look.v2", "Mine"])
def test_a_value_without_separator_and_ending_is_a_name(spec: str) -> None:
    assert is_name(spec)


@pytest.mark.parametrize(
    "spec", ["mine.yaml", "mine.YML", "./mine", "looks/mine", "/abs/mine", "C:\\looks\\mine"]
)
def test_anything_else_is_a_path(spec: str) -> None:
    assert not is_name(spec)


def test_override_keys_are_dotted_paths() -> None:
    keys = override_keys(
        {"font": {"size": 0.1}, "slots": 3, "colours": {"group": {"sung": "#fff"}}}
    )
    assert keys == ["font.size", "slots", "colours.group.sung"]


@pytest.mark.parametrize("name", ["mine", "my-look_2", "a.b"])
def test_good_names(name: str) -> None:
    assert valid_name(name)


@pytest.mark.parametrize("name", ["", "-x", "a b", "a/b", ".hidden", "ä"])
def test_bad_names(name: str) -> None:
    assert not valid_name(name)


def test_the_default_name_of_a_copy() -> None:
    assert default_name("blue-page") == "my-blue-page"


@pytest.mark.parametrize("source", BUILTIN_PROFILES)
def test_a_copy_has_the_header_and_its_own_name_and_loads(source: str) -> None:
    text = FakeResources().builtin_profile(source) or ""
    copy = copy_text(text, source, "mine", "1.2.3")
    lines = copy.splitlines()
    assert lines[0] == f"# A copy of the built-in profile {source}, made by Vocatron 1.2.3."
    assert 'name: "mine"' in lines
    assert f"name: {source}" not in lines
    profile = parse_profile("mine.yaml", copy)
    original = parse_profile(f"{source}.yaml", text)
    assert profile.model_dump() == {**original.model_dump(), "name": "mine"}


def test_the_header_of_a_copy_tells_how_to_check_and_choose_it() -> None:
    text = FakeResources().builtin_profile("blue-page") or ""
    by_name = copy_text(text, "blue-page", "mine", "1").splitlines()
    assert "`vocatron profiles check mine`" in by_name[1]
    assert by_name[2] == "# `profile: mine` in vocatron.yaml."
    by_path = copy_text(text, "blue-page", "mine", "1", "/home/a/mine.yaml").splitlines()
    assert "`vocatron profiles check /home/a/mine.yaml`" in by_path[1]
    assert by_path[2] == "# `profile: /home/a/mine.yaml` in vocatron.yaml."


def test_a_name_that_yaml_would_read_as_a_number_stays_text() -> None:
    text = FakeResources().builtin_profile("blue-page") or ""
    assert parse_profile("1.yaml", copy_text(text, "blue-page", "123", "1")).name == "123"


def test_a_profile_without_a_name_line_cannot_be_copied() -> None:
    with pytest.raises(ValueError, match="no name"):
        copy_text("slots: 2\n", "x", "y", "1")
