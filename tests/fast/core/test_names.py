"""Stage 1: safe names and collision resolution (property tests)."""

from pathlib import PurePosixPath

from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.names import FORBIDDEN, MAX_BYTES, RESERVED, resolve_collisions, safe_name

texts = st.text(max_size=400)


@given(texts)
def test_safe_name_has_no_forbidden_characters_or_edges(text: str) -> None:
    name = safe_name(text)
    assert name
    assert not FORBIDDEN.search(name)
    assert name == name.strip(" .")
    assert len(name.encode("utf-8")) <= MAX_BYTES


@given(texts)
def test_safe_name_is_idempotent(text: str) -> None:
    once = safe_name(text)
    assert safe_name(once) == once


@given(texts)
def test_safe_name_is_never_a_reserved_device_name(text: str) -> None:
    assert safe_name(text).split(".", 1)[0].rstrip().upper() not in RESERVED


def test_safe_name_examples() -> None:
    assert safe_name("AC/DC: Back  in\tBlack?") == "AC_DC_ Back in_Black_"
    assert safe_name("...") == "untitled"
    assert safe_name("con") == "con_"
    assert safe_name("Title. ") == "Title"
    assert safe_name("Xylophone X") == "Xylophone X"
    assert safe_name("é" * 300) == "é" * 100
    assert safe_name("a" + "é" * 300) == "a" + "é" * 99  # never splits a character
    assert safe_name("." * 300 + "Song") == "Song"
    assert safe_name("a" * 199 + ". b") == "a" * 199


def test_reserved_device_names_get_an_underscore_before_any_extension() -> None:
    assert safe_name("con.txt") == "con_.txt"
    assert safe_name("CON .mp3") == "CON _.mp3"
    assert safe_name("nul.a.b") == "nul_.a.b"
    assert safe_name("Com1") == "Com1_"
    assert safe_name("console.txt") == "console.txt"
    for name in ("con.txt", "CON .mp3", "nul.a.b", "LPT9"):
        assert safe_name(safe_name(name)) == safe_name(name)


@given(st.dictionaries(st.text(min_size=1, max_size=5), st.sampled_from(["A", "a", "B", "b"])))
def test_collisions_are_unique_stable_and_keep_the_first(wanted: dict[str, str]) -> None:
    paths = {PurePosixPath("/music") / key: name for key, name in wanted.items()}
    result = resolve_collisions(paths)
    assert len(result) == len(paths)
    assert len({name.casefold() for name in result.values()}) == len(result)
    reversed_order = dict(reversed(list(paths.items())))
    assert resolve_collisions(reversed_order) == result
    for source, name in paths.items():
        assert result[source].startswith(name)


def test_collision_suffixes_follow_the_sorted_path_order() -> None:
    a, b, c = (PurePosixPath(f"/m/{n}.mp3") for n in "abc")
    result = resolve_collisions({c: "Song", a: "Song", b: "song"})
    assert result == {a: "Song", b: "song (2)", c: "Song (3)"}


def test_a_suffixed_name_does_not_collide_with_a_real_one() -> None:
    a, b, c = (PurePosixPath(f"/m/{n}.mp3") for n in "abc")
    result = resolve_collisions({a: "Song", b: "Song", c: "Song (2)"})
    assert len(set(result.values())) == 3
