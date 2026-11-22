"""Stage 1: the real engines on temporary files."""

import os
import stat
import threading
import time
from datetime import UTC
from pathlib import Path

import pytest

from fakes.songs import write_wav
from vocatron.engines.clock import SystemClock
from vocatron.engines.files import FOLLOW_INTERVAL, FileLog, LocalFileStore
from vocatron.engines.protocols import TagReadError
from vocatron.engines.tags import TinyTagReader


def test_system_clock_returns_an_aware_utc_time() -> None:
    assert SystemClock().now().tzinfo is UTC


def test_tiny_tag_reader_reads_the_duration_of_a_wav_file(tmp_path: Path) -> None:
    tags = TinyTagReader().read(write_wav(tmp_path / "a.wav", seconds=2))
    assert tags.duration == pytest.approx(2, abs=0.01)
    assert tags.artist is None
    assert tags.title is None


def test_tiny_tag_reader_rejects_a_file_that_is_not_audio(tmp_path: Path) -> None:
    broken = tmp_path / "broken.txt"
    broken.write_text("not audio")
    with pytest.raises(TagReadError, match="broken.txt"):
        TinyTagReader().read(broken)


def test_kind_and_listing_ignore_subfolders_and_other_files(tmp_path: Path) -> None:
    store = LocalFileStore()
    write_wav(tmp_path / "b.WAV")
    write_wav(tmp_path / "a.wav")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "karaoke").mkdir()
    write_wav(tmp_path / "karaoke" / "inner.wav")
    assert store.list_audio(tmp_path) == [tmp_path / "a.wav", tmp_path / "b.WAV"]
    assert store.kind(tmp_path) == "folder"
    assert store.kind(tmp_path / "a.wav") == "file"
    assert store.kind(tmp_path / "missing") is None


def test_list_files_takes_the_suffixes_asked_for_and_no_subfolders(tmp_path: Path) -> None:
    store = LocalFileStore()
    for name in ("b.yaml", "a.YAML", "c.yml", "d.txt"):
        (tmp_path / name).write_text("x")
    (tmp_path / "sub.yaml").mkdir()
    assert store.list_files(tmp_path, (".yaml",)) == [tmp_path / "a.YAML", tmp_path / "b.yaml"]
    assert store.list_files(tmp_path, (".yaml", ".yml"))[-1] == tmp_path / "c.yml"
    assert store.list_files(tmp_path / "missing", (".yaml",)) == []


def test_text_round_trip_is_atomic_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    store = LocalFileStore()
    path = tmp_path / "deep" / "x.json"
    assert store.read_text(path) is None
    store.write_text(path, "one")
    store.write_text(path, "two")
    assert store.read_text(path) == "two"
    assert [p.name for p in path.parent.iterdir()] == ["x.json"]


def test_a_write_is_synced_to_disk_before_the_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "status.json"
    target_existed: list[bool] = []

    def fsync(descriptor: int) -> None:
        del descriptor
        target_existed.append(path.exists())

    monkeypatch.setattr(os, "fsync", fsync)
    LocalFileStore().write_text(path, "data")
    assert target_existed == [False]  # synced once, before the rename
    assert path.read_text() == "data"


def test_a_failed_write_removes_its_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(self: Path, target: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(OSError, match="disk full"):
        LocalFileStore().write_text(tmp_path / "x.json", "data")
    assert list(tmp_path.iterdir()) == []


def test_bytes_round_trip_and_leave_no_temporary_file(tmp_path: Path) -> None:
    store = LocalFileStore()
    path = tmp_path / "deep" / "Song.cdg"
    store.write_bytes(path, b"\x09\x00one")
    store.write_bytes(path, b"\x09\x00two")
    assert path.read_bytes() == b"\x09\x00two"
    assert [p.name for p in path.parent.iterdir()] == ["Song.cdg"]


def test_a_written_file_has_the_mode_of_a_plain_new_file(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.write_bytes(b"x")  # what ffmpeg's video gets next to it
    LocalFileStore().write_bytes(tmp_path / "Song.cdg", b"x")
    LocalFileStore().write_text(tmp_path / "Song.lrc", "x")
    wanted = stat.S_IMODE(plain.stat().st_mode)
    assert stat.S_IMODE((tmp_path / "Song.cdg").stat().st_mode) == wanted
    assert stat.S_IMODE((tmp_path / "Song.lrc").stat().st_mode) == wanted


def test_sha256_of_content_and_of_a_missing_file(tmp_path: Path) -> None:
    store = LocalFileStore()
    (tmp_path / "empty").write_bytes(b"")
    assert store.sha256(tmp_path / "empty") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert store.sha256(tmp_path / "missing") is None


def test_make_folder_and_log_are_on_disk_after_every_line(tmp_path: Path) -> None:
    store = LocalFileStore()
    store.make_folder(tmp_path / "a" / "b")
    log = store.open_log(tmp_path / "a" / "b" / "log.txt")
    log.write("first")
    assert (tmp_path / "a" / "b" / "log.txt").read_text() == "first\n"  # before close
    log.write("second\n")
    log.close()
    store.open_log(tmp_path / "a" / "b" / "log.txt").write("third")
    assert (tmp_path / "a" / "b" / "log.txt").read_text() == "first\nsecond\nthird\n"


class Heard:
    """Collects followed lines; ``wait_for`` blocks until a line arrived (from the thread)."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.arrived = threading.Event()

    def __call__(self, line: str) -> None:
        self.lines.append(line)
        self.arrived.set()


def test_a_followed_log_hands_on_its_own_lines_at_once_and_not_the_old_ones(
    tmp_path: Path,
) -> None:
    path = tmp_path / "log.txt"
    path.write_text("from an earlier run\n")
    heard = Heard()
    log = LocalFileStore().open_log(path, heard)
    log.write("first")
    assert heard.lines == ["first"]  # at once, before close
    log.close()
    assert heard.lines == ["first"]  # each line once


def test_a_followed_log_hands_on_the_lines_of_another_writer_live_and_in_order(
    tmp_path: Path,
) -> None:
    path = tmp_path / "log.txt"
    heard = Heard()
    log = LocalFileStore().open_log(path, heard)
    worker = FileLog(path)  # another process appending to the same file
    log.write("parent: start")
    heard.arrived.clear()
    worker.write("worker: piece 1 of 2")
    assert heard.arrived.wait(10)  # while both are still open: live
    log.write("parent: between")
    worker.close()
    with path.open("a", encoding="utf-8") as raw:
        raw.write("worker: piece 2 ")  # a line still being written waits for its end
        raw.flush()
        time.sleep(3 * FOLLOW_INTERVAL)  # the follower looked more than once meanwhile
        assert heard.lines[-1] == "parent: between"
        raw.write("of 2\n")
    log.close()  # hands on what is complete by now
    assert heard.lines == [
        "parent: start",
        "worker: piece 1 of 2",
        "parent: between",
        "worker: piece 2 of 2",
    ]


def test_closing_a_followed_log_hands_on_a_line_without_end_and_stops_the_follower(
    tmp_path: Path,
) -> None:
    path = tmp_path / "log.txt"
    before = set(threading.enumerate())
    heard = Heard()
    log = LocalFileStore().open_log(path, heard)
    with path.open("a", encoding="utf-8") as raw:
        raw.write("worker: killed while writ")  # its writer is gone: the line never ends
    log.close()
    assert heard.lines == ["worker: killed while writ"]  # not lost
    assert set(threading.enumerate()) <= before  # no follower thread is left running


def test_size_delete_and_writable_on_the_local_file_store(tmp_path: Path) -> None:
    store = LocalFileStore()
    file = tmp_path / "a.bin"
    assert store.size(file) is None
    file.write_bytes(b"12345")
    assert store.size(file) == 5
    store.delete(file)
    store.delete(file)  # nothing happens when it is gone
    assert store.size(file) is None
    assert store.writable(tmp_path)
    assert store.writable(tmp_path / "new" / "deeper")  # can be created below tmp_path
    file.write_bytes(b"x")
    assert not store.writable(file)  # a file is no folder
    assert not store.writable(file / "below")
