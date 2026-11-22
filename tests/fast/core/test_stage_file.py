"""Stage 1: fingerprints and the skip rule."""

from pathlib import PurePosixPath

from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from vocatron.core.stage_file import (
    Fingerprint,
    hash_bytes,
    is_current,
    make_fingerprint,
    settings_hash,
)


class Settings(BaseModel):
    a: int = 1
    b: str = "x"


hashes = st.dictionaries(st.text(min_size=1, max_size=5), st.text(min_size=1, max_size=8))


def test_hash_bytes_is_sha256() -> None:
    assert hash_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class Unsorted(BaseModel):
    z: int = 1
    a: str = "é"
    path: PurePosixPath = PurePosixPath("/x")


def test_settings_hash_is_the_sha256_of_canonical_ascii_json() -> None:
    canonical = b'{"a":"\\u00e9","path":"/x","z":1}'
    assert settings_hash(Unsorted()) == hash_bytes(canonical)


def test_settings_hash_ignores_field_order_and_reflects_values() -> None:
    assert settings_hash(Settings(a=1, b="x")) == settings_hash(Settings(b="x", a=1))
    assert settings_hash(Settings(a=2)) != settings_hash(Settings(a=1))


@given(hashes, st.integers(0, 5))
def test_fingerprint_equals_itself_and_changes_with_every_part(
    inputs: dict[str, str], v: int
) -> None:
    base = make_fingerprint(inputs, Settings(), v)
    assert base == make_fingerprint(dict(inputs), Settings(), v)
    assert base != make_fingerprint(inputs, Settings(a=9), v)
    assert base != make_fingerprint(inputs, Settings(), v + 1)
    for key, value in inputs.items():
        assert base != make_fingerprint({**inputs, key: value + "!"}, Settings(), v)
    assert base != make_fingerprint({**inputs, "extra\n": "1"}, Settings(), v)


def test_is_current_rules() -> None:
    now = Fingerprint(inputs={"audio": "1"}, settings="s", stage_version=1)
    other = Fingerprint(inputs={"audio": "2"}, settings="s", stage_version=1)
    assert is_current(now, now, force=False)
    assert not is_current(now, now, force=True)
    assert not is_current(other, now, force=False)
    assert not is_current(None, now, force=False)
