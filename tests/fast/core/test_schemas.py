"""Stage 1: schema naming and the guards around it."""

from typing import ClassVar

import pytest
from pydantic import BaseModel

from vocatron.core.schemas import (
    extend_manifest,
    parse_manifest,
    render_manifest,
    schema_digest,
    schema_filename,
    schema_files,
    schema_name,
    schema_version,
)
from vocatron.core.song import SongInfo


class NoName(BaseModel):
    schema_version: int = 1


class NoVersion(BaseModel):
    SCHEMA_NAME: ClassVar[str] = "x"
    schema_version: str = "a"


def test_filename_combines_name_and_version() -> None:
    assert schema_filename(SongInfo) == "song.v1.json"


def test_a_model_needs_a_name_and_an_integer_version() -> None:
    with pytest.raises(TypeError, match="SCHEMA_NAME"):
        schema_name(NoName)
    with pytest.raises(TypeError, match="integer"):
        schema_version(NoVersion)


def test_schema_files_map_file_names_to_schema_text() -> None:
    files = schema_files([SongInfo])
    assert list(files) == ["song.v1.json"]
    assert '"title"' in files["song.v1.json"]


def test_digest_is_the_sha256_of_the_utf8_text() -> None:
    # sha256 of b"a\n", as `sha256sum` prints it
    expected = "87428fc522803d31065e7bce3cf03fe475096631e5e07bbd7a0fde60c4cf25c7"
    assert schema_digest("a\n") == expected
    assert schema_digest("ß") != schema_digest("ss")


def test_manifest_round_trips_sorted_in_sha256sum_format() -> None:
    digests = {"b.v1.json": "1" * 64, "a.v2.json": "f" * 64}
    text = render_manifest(digests)
    assert text == f"{'f' * 64}  a.v2.json\n{'1' * 64}  b.v1.json\n"
    assert parse_manifest(text) == digests
    assert parse_manifest("") == {}
    assert parse_manifest(f"{'0' * 64}  odd  name.json\n") == {"odd  name.json": "0" * 64}


@pytest.mark.parametrize(
    "line",
    [
        "x" * 64 + "  a.json",  # not hex
        "a" * 63 + "  a.json",  # too short
        "A" * 64 + "  a.json",  # sha256sum writes lower case
        "a" * 64 + " a.json",  # one space only
        "a" * 64 + "  ",  # no name
    ],
)
def test_malformed_manifest_lines_are_refused(line: str) -> None:
    with pytest.raises(ValueError, match="malformed"):
        parse_manifest(line + "\n")


def test_a_file_listed_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="twice"):
        parse_manifest(render_manifest({"a.json": "0" * 64}) * 2)


def test_extend_adds_new_versions_and_keeps_superseded_ones() -> None:
    known = {"x.v1.json": schema_digest("old\n")}
    extended = extend_manifest(known, {"x.v2.json": "new\n", "x.v1.json": "old\n"})
    assert extended == {"x.v1.json": schema_digest("old\n"), "x.v2.json": schema_digest("new\n")}
    assert known == {"x.v1.json": schema_digest("old\n")}  # the input is not changed


def test_extend_refuses_to_change_a_committed_schema() -> None:
    with pytest.raises(ValueError, match=r"x\.v1\.json would change"):
        extend_manifest({"x.v1.json": schema_digest("old\n")}, {"x.v1.json": "changed\n"})
