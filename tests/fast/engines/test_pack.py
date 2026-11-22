"""Stage 1: the zip writer: same members, same bytes; fixed times and order (ADR-0030)."""

import zipfile
from pathlib import Path

import pytest

from fakes.files import InMemoryFileStore
from fakes.pack import FakePacker
from vocatron.core.cdg.pack import ZIP_TIME
from vocatron.engines.pack import ZipPacker
from vocatron.engines.protocols import PackMember, PackRequest


def request(target: Path, mp3: Path) -> PackRequest:
    return PackRequest(
        target=target,
        members=(PackMember("Song.mp3", mp3), PackMember("Song.cdg", b"\x00" * 240 + b"\x09\x01")),
        time=ZIP_TIME,
    )


@pytest.fixture
def mp3(tmp_path: Path) -> Path:
    path = tmp_path / "Song.mp3"
    path.write_bytes(b"ID3" + bytes(range(256)) * 4)
    return path


def test_the_zip_holds_the_members_in_the_given_order_with_their_content(
    tmp_path: Path, mp3: Path
) -> None:
    target = tmp_path / "Song.zip"
    ZipPacker().pack(request(target, mp3))
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["Song.mp3", "Song.cdg"]
        assert archive.read("Song.mp3") == mp3.read_bytes()
        assert archive.read("Song.cdg") == b"\x00" * 240 + b"\x09\x01"
        assert archive.testzip() is None
        assert [info.date_time for info in archive.infolist()] == [ZIP_TIME, ZIP_TIME]
        assert {info.create_system for info in archive.infolist()} == {3}
        assert {info.external_attr >> 16 for info in archive.infolist()} == {0o644}
        assert {info.compress_type for info in archive.infolist()} == {zipfile.ZIP_DEFLATED}


def test_the_same_members_give_the_same_bytes_whatever_the_file_times(
    tmp_path: Path, mp3: Path
) -> None:
    first, second = tmp_path / "one.zip", tmp_path / "two.zip"
    ZipPacker().pack(request(first, mp3))
    mp3.touch()  # another modification time
    mp3.write_bytes(mp3.read_bytes())
    ZipPacker().pack(request(second, mp3))
    assert first.read_bytes() == second.read_bytes()


def test_a_member_may_be_bytes_or_a_file_and_the_zip_replaces_an_old_one(
    tmp_path: Path, mp3: Path
) -> None:
    target = tmp_path / "Song.zip"
    target.write_bytes(b"old")
    ZipPacker().pack(request(target, mp3))
    assert zipfile.is_zipfile(target)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Song.mp3", "Song.zip"]  # no .part


def test_a_member_that_cannot_be_read_leaves_no_zip_and_no_partial_file(tmp_path: Path) -> None:
    target = tmp_path / "Song.zip"
    with pytest.raises(OSError, match="Song.mp3"):
        ZipPacker().pack(request(target, tmp_path / "Song.mp3"))
    assert list(tmp_path.iterdir()) == []


def test_the_fake_records_the_request_and_writes_a_listing_of_the_members() -> None:
    store = InMemoryFileStore()
    store.add(Path("/work/Song.mp3"), b"mp3 bytes")
    packer = FakePacker(store)
    packer.pack(request(Path("/out/Song.zip"), Path("/work/Song.mp3")))
    assert packer.requests[0].target == Path("/out/Song.zip")
    assert packer.packed["Song.mp3"] == b"mp3 bytes"
    assert store.files[Path("/out/Song.zip")] == b"zip Song.mp3 9, Song.cdg 242"
