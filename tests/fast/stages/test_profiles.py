"""Stage 1: own profiles by name, the clash with built-in names, the listing (ADR-0019)."""

from pathlib import Path

import pytest

from fakes.songs import FakeWorld
from vocatron.core.errors import StageError
from vocatron.core.profiles.model import BUILTIN_PROFILES
from vocatron.core.stage_file import settings_hash
from vocatron.stages.config import Config
from vocatron.stages.layout import LayoutStage
from vocatron.stages.profiles import (
    is_chosen,
    known_names,
    list_profiles,
    load_profile,
    profile_text,
)

FOLDER = Path("/looks")


def put(world: FakeWorld, name: str, text: str | None = None, *, base: str = "blue-page") -> Path:
    """Put an own profile into the folder, a copy of a built-in one unless ``text`` is given."""
    path = FOLDER / f"{name}.yaml"
    body = text if text is not None else (world.resources.builtin_profile(base) or "")
    world.store.add(path, body.replace(f"name: {base}", f"name: {name}").encode())
    return path


def test_an_own_name_resolves_to_the_file_of_the_folder(world: FakeWorld) -> None:
    path = put(world, "mine")
    found = profile_text("mine", FOLDER, world.store, world.resources)
    assert found is not None
    assert (found.label, found.path) == (str(path), path)
    profile = load_profile("mine", {}, FOLDER, world.store, world.resources)
    assert (profile.name, profile.mode) == ("mine", "page")


def test_a_built_in_name_still_resolves_to_the_package(world: FakeWorld) -> None:
    found = profile_text("blue-page", FOLDER, world.store, world.resources)
    assert found is not None
    assert (found.label, found.path) == ("profiles/blue-page.yaml", None)


def test_a_name_that_is_built_in_and_in_the_folder_is_an_error_with_the_way_out(
    world: FakeWorld,
) -> None:
    put(world, "blue-page")
    with pytest.raises(StageError) as error:
        profile_text("blue-page", FOLDER, world.store, world.resources)
    assert error.value.kind == "invalid-profile"
    assert "/looks/blue-page.yaml" in str(error.value)
    assert "profile_overrides" in str(error.value)
    assert "vocatron profiles copy blue-page" in str(error.value)


def test_an_unknown_name_lists_the_names_that_exist(world: FakeWorld) -> None:
    put(world, "mine")
    with pytest.raises(StageError) as error:
        load_profile("nope", {}, FOLDER, world.store, world.resources)
    for name in (*BUILTIN_PROFILES, "mine"):
        assert name in str(error.value)


def test_a_value_with_an_ending_is_a_path_even_in_the_folder(world: FakeWorld) -> None:
    put(world, "mine")
    assert profile_text("mine.yaml", FOLDER, world.store, world.resources) is None
    found = profile_text(str(FOLDER / "mine.yaml"), None, world.store, world.resources)
    assert found is not None


def test_known_names_have_built_in_first_and_skip_clashing_files(world: FakeWorld) -> None:
    put(world, "zeta")
    put(world, "alpha")
    put(world, "full-page")
    assert known_names(FOLDER, world.store) == [*BUILTIN_PROFILES, "alpha", "zeta"]
    assert known_names(None, world.store) == list(BUILTIN_PROFILES)


def test_the_folder_does_not_change_the_fingerprint_of_the_layout(world: FakeWorld) -> None:
    plain = LayoutStage().settings_from(Config())
    with_folder = LayoutStage().settings_from(Config(profiles_folder="/looks"))
    assert with_folder.folder == "/looks"
    assert settings_hash(with_folder) == settings_hash(plain)
    assert set(plain.model_dump()) == {"profile", "overrides", "width", "height"}


def test_the_listing_has_built_in_and_own_profiles_and_the_invalid_ones(world: FakeWorld) -> None:
    put(world, "mine")
    put(world, "broken", "name: broken\nslots: 9\n")
    put(world, "two-line-turns")
    entries = {
        (e.name, e.path is None): e for e in list_profiles(FOLDER, world.store, world.resources)
    }
    assert [e.name for e in entries.values() if e.path is None] == list(BUILTIN_PROFILES)
    mine = entries[("mine", False)]
    assert (mine.source, mine.problem) == (str(FOLDER / "mine.yaml"), None)
    assert mine.profile is not None
    assert mine.profile.description
    broken = entries[("broken", False)]
    assert broken.profile is None
    assert broken.problem is not None
    assert "slots" in broken.problem
    clash = entries[("two-line-turns", False)]
    assert clash.profile is None
    assert clash.problem is not None
    assert "built-in" in clash.problem


def test_only_files_ending_in_exactly_yaml_are_own_profiles(world: FakeWorld) -> None:
    put(world, "mine")
    world.store.add(FOLDER / "Other.YAML", b"name: Other\n")
    world.store.add(FOLDER / "third.yml", b"name: third\n")
    own = [e.name for e in list_profiles(FOLDER, world.store, world.resources) if e.path]
    assert own == ["mine"]
    assert known_names(FOLDER, world.store)[-1] == "mine"


def test_the_chosen_profile_is_found_by_name_or_by_path(world: FakeWorld) -> None:
    put(world, "mine")
    put(world, "full-page")
    entries = list_profiles(FOLDER, world.store, world.resources)

    def chosen(spec: str) -> list[str]:
        return [f"{e.name}:{e.source}" for e in entries if is_chosen(e, spec)]

    assert chosen("mine") == [f"mine:{FOLDER}/mine.yaml"]
    assert chosen("full-page") == ["full-page:built in"]  # the clashing file is never chosen
    assert chosen(f"{FOLDER}/../looks/mine.yaml") == [f"mine:{FOLDER}/mine.yaml"]
    assert chosen("/elsewhere/x.yaml") == []


def test_a_file_that_cannot_be_read_is_an_invalid_profile_in_the_listing_and_an_error_otherwise(
    world: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = put(world, "mine")
    real = world.store.read_text

    def unreadable(file: Path) -> str | None:
        if file == path:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        return real(file)

    monkeypatch.setattr(world.store, "read_text", unreadable)
    with pytest.raises(StageError, match="cannot read"):
        profile_text("mine", FOLDER, world.store, world.resources)
    (mine,) = [e for e in list_profiles(FOLDER, world.store, world.resources) if e.path == path]
    assert mine.profile is None
    assert mine.problem is not None
    assert "cannot read" in mine.problem
