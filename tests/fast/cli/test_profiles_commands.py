"""Stage 1: ``vocatron profiles``, ``profiles check`` and ``profiles copy`` on fakes (ADR-0019)."""

from importlib.metadata import version
from pathlib import Path

import pytest

from fakes.songs import FakeWorld
from fakes.streams import Streams
from vocatron.cli import app
from vocatron.cli.commands import run_profiles, run_profiles_check, run_profiles_copy
from vocatron.core.profiles.model import BUILTIN_PROFILES

CONFIG = Path("/work/vocatron.yaml")
FOLDER = Path("/work/looks")


@pytest.fixture
def world() -> FakeWorld:
    """Fake engines that draw with the bundled font: the CD+G check of a look depends on it."""
    found = FakeWorld()
    found.use_real_font()
    return found


def configure(world: FakeWorld, text: str = "profiles_folder: looks\n") -> None:
    world.store.add(CONFIG, text.encode())


def own(world: FakeWorld, name: str, text: str | None = None) -> Path:
    path = FOLDER / f"{name}.yaml"
    body = text if text is not None else (world.resources.builtin_profile("blue-page") or "")
    world.store.add(path, body.replace("name: blue-page", f"name: {name}").encode())
    return path


def listing(world: FakeWorld) -> tuple[int, str, str]:
    streams = Streams(world)
    code = run_profiles(config_file=None, edges=streams.edges)
    return code, streams.out.getvalue(), streams.err.getvalue()


def check(world: FakeWorld, spec: str) -> tuple[int, str, str]:
    streams = Streams(world)
    code = run_profiles_check(spec, config_file=None, edges=streams.edges)
    return code, streams.out.getvalue(), streams.err.getvalue()


def copy(world: FakeWorld, source: str, target: str | None = None) -> tuple[int, str, str]:
    streams = Streams(world)
    code = run_profiles_copy(source, target, config_file=None, version="9.9", edges=streams.edges)
    return code, streams.out.getvalue(), streams.err.getvalue()


def row_of(out: str, name: str) -> str:
    return next(line for line in out.splitlines() if name in line.split())


def test_the_list_has_every_built_in_profile_with_description_mode_slots_and_source(
    world: FakeWorld,
) -> None:
    code, out, _ = listing(world)
    assert code == 0
    for name in BUILTIN_PROFILES:
        assert "built in" in row_of(out, name)
    blue = row_of(out, "blue-page")
    assert "page" in blue.split()
    assert "4" in blue.split()
    assert "Pages of four lines on dark blue" in out


def test_the_chosen_profile_is_marked(world: FakeWorld) -> None:
    _, out, _ = listing(world)
    assert row_of(out, "four-line-stack").startswith("*")
    assert not row_of(out, "blue-page").startswith("*")
    configure(world, "profile: blue-page\n")
    _, out, _ = listing(world)
    assert row_of(out, "blue-page").startswith("*")
    assert not row_of(out, "four-line-stack").startswith("*")


def test_own_profiles_are_listed_with_their_file_and_can_be_chosen(world: FakeWorld) -> None:
    configure(world, "profiles_folder: looks\nprofile: mine\n")
    own(world, "mine")
    _, out, _ = listing(world)
    mine = row_of(out, "mine")
    assert mine.startswith("*")
    assert str(FOLDER / "mine.yaml") in mine


def test_an_own_file_that_does_not_load_is_listed_as_invalid_with_a_pointer_to_check(
    world: FakeWorld,
) -> None:
    configure(world)
    own(world, "broken", "name: broken\nslots: 9\n")
    own(world, "full-page")
    code, out, _ = listing(world)
    assert code == 0
    assert "invalid" in row_of(out, "broken")
    assert "run `vocatron profiles check broken`" in " ".join(out.split())  # the cell wraps
    assert out.count("invalid: ") == 2  # the broken file and the one with a built-in name


def test_a_profiles_folder_that_is_missing_is_a_warning(world: FakeWorld) -> None:
    configure(world)
    code, out, _ = listing(world)
    assert code == 0
    assert f"warning: profiles_folder {FOLDER} is not a folder" in out


def test_a_broken_configuration_is_exit_2(world: FakeWorld) -> None:
    configure(world, "profiles_folder: 3\n")
    code, _, err = listing(world)
    assert code == 2
    assert "/work/vocatron.yaml:1:1: profiles_folder" in err


def test_check_says_ok_for_a_built_in_profile(world: FakeWorld) -> None:
    code, out, err = check(world, "blue-page")
    assert (code, out, err) == (0, "profiles/blue-page.yaml: ok\n", "")


def test_check_names_file_line_and_column_of_a_problem_and_exits_1(world: FakeWorld) -> None:
    configure(world)
    text = (world.resources.builtin_profile("blue-page") or "").replace("slots: 4", "slots: 9")
    own(world, "broken", text)
    code, out, _ = check(world, "broken")
    row = text.splitlines().index("slots: 9") + 1
    assert code == 1
    assert out.startswith(f"{FOLDER}/broken.yaml:{row}:1: slots: ")
    assert ": ok" not in out


def test_check_finds_a_colour_problem_at_its_line(world: FakeWorld) -> None:
    configure(world)
    text = (world.resources.builtin_profile("blue-page") or "").replace('"#000055"', '"#ffffff"')
    own(world, "pale", text)
    code, out, _ = check(world, "pale")
    row = text.splitlines().index(next(x for x in text.splitlines() if "singer1:" in x)) + 1
    assert code == 1
    assert f"{FOLDER}/pale.yaml:{row}:13: colours.singer1.unsung: has contrast" in out


def test_check_takes_a_file_relative_to_the_current_folder(world: FakeWorld) -> None:
    world.store.add(
        Path("/work/x/mine.yaml"),
        (world.resources.builtin_profile("blue-page") or "")
        .replace("name: blue-page", "name: mine")
        .encode(),
    )
    code, out, _ = check(world, "x/mine.yaml")
    assert (code, out) == (0, "/work/x/mine.yaml: ok\n")


def test_check_wants_the_file_to_name_itself_like_its_file(world: FakeWorld) -> None:
    configure(world)
    own(world, "mine", (world.resources.builtin_profile("blue-page") or ""))  # name: mine
    world.store.add(FOLDER / "other.yaml", world.store.files[FOLDER / "mine.yaml"])
    code, out, _ = check(world, "other")
    assert code == 1
    assert "name: is 'mine', but the profile is 'other'" in out


def test_check_applies_the_overrides_of_the_configuration_and_names_them(
    world: FakeWorld,
) -> None:
    configure(world, "profile_overrides:\n  colours:\n    singer1: {sung: '#000066'}\n")
    code, out, _ = check(world, "blue-page")
    assert code == 1
    assert out.startswith("applying profile_overrides of the configuration: colours.singer1.sung\n")
    assert "profile_overrides.colours.singer1.sung" in out


def test_check_of_an_unknown_name_lists_the_known_ones_and_is_exit_2(world: FakeWorld) -> None:
    configure(world)
    own(world, "mine")
    code, out, err = check(world, "nope")
    assert (code, out) == (2, "")
    assert "'nope' not found" in err
    assert "mine" in err
    assert "blue-page" in err


def test_check_of_a_missing_file_is_exit_2(world: FakeWorld) -> None:
    code, _, err = check(world, "x/none.yaml")
    assert code == 2
    assert "x/none.yaml" in err


def test_check_of_a_name_that_clashes_is_exit_2_with_the_way_out(world: FakeWorld) -> None:
    configure(world)
    own(world, "blue-page")
    code, _, err = check(world, "blue-page")
    assert code == 2
    assert "profile_overrides" in err
    assert "vocatron profiles copy blue-page" in err


def test_check_with_a_broken_configuration_is_exit_2(world: FakeWorld) -> None:
    configure(world, "profile: [1]\n")
    assert check(world, "blue-page")[0] == 2


def test_a_copy_with_a_broken_configuration_is_exit_2_and_writes_nothing(world: FakeWorld) -> None:
    configure(world, "profiles_folder: 3\n")
    code, out, err = copy(world, "blue-page", "mine")
    assert code == 2
    assert "/work/vocatron.yaml:1:1: profiles_folder" in err
    assert out == ""


def test_a_copy_goes_into_the_folder_under_the_given_name_and_passes_check(
    world: FakeWorld,
) -> None:
    configure(world)
    code, out, _ = copy(world, "blue-page", "mine")
    path = FOLDER / "mine.yaml"
    assert code == 0
    assert f"wrote {path}" in out
    text = world.store.read_text(path) or ""
    assert text.startswith("# A copy of the built-in profile blue-page, made by Vocatron 9.9.")
    assert 'name: "mine"' in text
    assert check(world, "mine")[:2] == (0, f"{path}: ok\n")


def test_a_copy_without_a_name_is_called_my_and_the_source(world: FakeWorld) -> None:
    configure(world)
    assert copy(world, "full-page")[0] == 0
    assert (FOLDER / "my-full-page.yaml") in world.store.files


def test_a_copy_to_a_path_needs_no_folder(world: FakeWorld) -> None:
    code, out, _ = copy(world, "one-line-preview", "x/fancy.yaml")
    assert code == 0
    assert "vocatron profiles check /work/x/fancy.yaml" in out
    written = world.store.read_text(Path("/work/x/fancy.yaml")) or ""
    assert 'name: "fancy"' in written
    assert "# `profile: /work/x/fancy.yaml` in vocatron.yaml." in written
    assert check(world, "x/fancy.yaml")[0] == 0


def test_a_copy_to_a_bare_name_without_a_folder_is_an_error(world: FakeWorld) -> None:
    code, out, err = copy(world, "blue-page", "mine")
    assert (code, out) == (2, "")
    assert "profiles_folder" in err
    assert world.store.writes == []
    assert copy(world, "blue-page")[0] == 2  # the default name is a bare name too


def test_a_copy_never_overwrites_a_file(world: FakeWorld) -> None:
    configure(world)
    path = own(world, "mine", "name: mine\nmy own text\n")
    code, _, err = copy(world, "blue-page", "mine")
    assert code == 1
    assert "exists already" in err
    assert world.store.read_text(path) == "name: mine\nmy own text\n"
    assert world.store.writes == []


def test_a_copy_needs_a_built_in_source_and_a_usable_name(world: FakeWorld) -> None:
    configure(world)
    assert copy(world, "mine")[0] == 2
    assert "known: two-line-turns" in copy(world, "mine")[2]
    assert copy(world, "blue-page", "full-page")[0] == 2  # a built-in name
    assert copy(world, "blue-page", "x/-bad name.yaml")[0] == 2
    assert world.store.writes == []


def test_the_app_commands_run_the_functions_with_the_real_edges(
    world: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    streams = Streams(world)
    monkeypatch.setattr(app, "real_edges", lambda: streams.edges)
    assert app.profiles(config=None) == 0
    assert app.profiles_check("blue-page", config=None) == 0
    assert app.profiles_copy("blue-page", "x/mine.yaml", config=None) == 0
    out = streams.out.getvalue()
    assert "blue-page" in out
    assert "wrote /work/x/mine.yaml" in out
    assert "A copy of the built-in profile blue-page, made by Vocatron " + version("vocatron") in (
        world.store.read_text(Path("/work/x/mine.yaml")) or ""
    )
