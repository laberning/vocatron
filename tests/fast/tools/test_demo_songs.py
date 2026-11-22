"""Stage 1 tests for ``tools/demo_songs.py``: a fake downloader, no network."""

import hashlib
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import NoReturn

import pytest

import demo_songs
from demo_songs import DemoSong, DemoSongError

AUDIO = b"not really audio"
SHA = hashlib.sha256(AUDIO).hexdigest()
URL = "https://example.invalid/song.mp3"


def song() -> DemoSong:
    return DemoSong(
        file="Made Up.mp3",
        artist="A",
        title="T",
        language="en",
        licence="CC0",
        licence_url="https://example.invalid/licence",
        source_url="https://example.invalid/page",
        download_url=URL,
        sha256=SHA,
        seconds=1.0,
    )


class FakeDownloader:
    """Writes ``content`` and remembers which URLs were asked for."""

    def __init__(self, content: bytes = AUDIO) -> None:
        self.content = content
        self.urls: list[str] = []

    def __call__(self, url: str, target: Path) -> None:
        self.urls.append(url)
        target.write_bytes(self.content)


def test_a_missing_file_is_downloaded_and_checked(tmp_path: Path) -> None:
    fake = FakeDownloader()
    assert demo_songs.fetch(song(), tmp_path / "demo", fake) == "downloaded"
    assert (tmp_path / "demo" / "Made Up.mp3").read_bytes() == AUDIO
    assert fake.urls == [URL]
    assert list((tmp_path / "demo").glob("*.part")) == []


def test_a_good_file_is_not_downloaded_again(tmp_path: Path) -> None:
    (tmp_path / "Made Up.mp3").write_bytes(AUDIO)
    fake = FakeDownloader(b"other")
    assert demo_songs.fetch(song(), tmp_path, fake) == "present"
    assert fake.urls == []
    assert (tmp_path / "Made Up.mp3").read_bytes() == AUDIO


def test_a_damaged_file_is_replaced(tmp_path: Path) -> None:
    (tmp_path / "Made Up.mp3").write_bytes(b"half")
    assert demo_songs.fetch(song(), tmp_path, FakeDownloader()) == "downloaded"
    assert (tmp_path / "Made Up.mp3").read_bytes() == AUDIO


def test_a_wrong_checksum_fails_with_both_sums_and_keeps_nothing(tmp_path: Path) -> None:
    with pytest.raises(DemoSongError, match="wrong checksum") as raised:
        demo_songs.fetch(song(), tmp_path, FakeDownloader(b"changed"))
    wrong = hashlib.sha256(b"changed").hexdigest()
    assert SHA in str(raised.value)
    assert wrong in str(raised.value)
    assert list(tmp_path.iterdir()) == []


def test_a_failed_download_keeps_no_half_file(tmp_path: Path) -> None:
    def broken(url: str, target: Path) -> NoReturn:
        del url
        target.write_bytes(b"half")
        raise DemoSongError("download failed")

    with pytest.raises(DemoSongError, match="download failed"):
        demo_songs.fetch(song(), tmp_path, broken)
    assert list(tmp_path.iterdir()) == []


def test_the_song_list_is_read_and_a_bad_entry_is_named() -> None:
    text = """
[[song]]
file = "A.mp3"
artist = "x"
title = "A"
language = "de"
licence = "CC0"
licence_url = "u"
source_url = "s"
download_url = "d"
sha256 = "00"
seconds = 2.5
"""
    (only,) = demo_songs.load_songs(text)
    assert (only.stem, only.seconds) == ("A", 2.5)
    assert demo_songs.load_songs("") == []
    with pytest.raises(DemoSongError, match="bad song entry"):
        demo_songs.load_songs('[[song]]\nfile = "A.mp3"\n')


def test_main_downloads_once_and_a_second_run_downloads_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listing = tmp_path / "demo.toml"
    listing.write_text(
        f'[[song]]\nfile = "Made Up.mp3"\nartist = "a"\ntitle = "t"\nlanguage = "en"\n'
        f'licence = "l"\nlicence_url = "u"\nsource_url = "s"\ndownload_url = "{URL}"\n'
        f'sha256 = "{SHA}"\nseconds = 1.0\n',
        encoding="utf-8",
    )
    folder = tmp_path / "audio"
    arguments = ["--folder", str(folder), "--list", str(listing)]
    fake = FakeDownloader()
    assert demo_songs.main(arguments, fake) == 0
    assert demo_songs.main(arguments, fake) == 0
    assert len(fake.urls) == 1
    out = capsys.readouterr().out
    assert "downloaded" in out
    assert "present" in out


def test_main_fails_with_a_message_on_a_wrong_checksum(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listing = tmp_path / "demo.toml"
    listing.write_text(
        f'[[song]]\nfile = "Made Up.mp3"\nartist = "a"\ntitle = "t"\nlanguage = "en"\n'
        f'licence = "l"\nlicence_url = "u"\nsource_url = "s"\ndownload_url = "{URL}"\n'
        f'sha256 = "{SHA}"\nseconds = 1.0\n',
        encoding="utf-8",
    )
    code = demo_songs.main(
        ["--folder", str(tmp_path / "a"), "--list", str(listing)], FakeDownloader(b"x")
    )
    assert code == 1
    assert "wrong checksum" in capsys.readouterr().err


def test_the_committed_song_list_is_complete_and_has_credits_and_lyrics_but_no_audio() -> None:
    folder = demo_songs.SONG_LIST.parent
    songs = demo_songs.load_songs(demo_songs.SONG_LIST.read_text("utf-8"))
    assert [item.language for item in songs] == ["de", "en"]
    credits_text = (folder / "CREDITS.md").read_text("utf-8")
    for item in songs:
        assert re.fullmatch(r"[0-9a-f]{64}", item.sha256)
        assert item.download_url.startswith("https://")
        assert item.licence_url.startswith("https://")
        assert (folder / f"{item.stem}.txt").is_file()  # existence only: never opened
        assert f"## {item.title}" in credits_text
    audio = {".mp3", ".flac", ".wav", ".ogg", ".opus", ".m4a"}
    assert [p.name for p in folder.iterdir() if p.suffix in audio] == []


def test_the_real_downloader_tries_again_and_gives_up_with_a_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def refuse(request: urllib.request.Request, timeout: float) -> NoReturn:
        del timeout
        calls.append(request.full_url)
        raise urllib.error.URLError("server error 500")

    monkeypatch.setattr(demo_songs, "PAUSE", 0.0)
    monkeypatch.setattr(demo_songs, "ATTEMPTS", 2)
    monkeypatch.setattr(demo_songs.urllib.request, "urlopen", refuse)
    with pytest.raises(DemoSongError, match=r"after 2 attempts \(<urlopen error server error 500>"):
        demo_songs.http_download("https://example.invalid/x", tmp_path / "x")
    assert len(calls) == 2
