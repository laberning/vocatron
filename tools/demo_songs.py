"""Download the freely licensed demo songs into ``.corpus/demo/`` and check their SHA-256.

``make demo-songs`` runs this. The song list is ``tests/data/demo/demo.toml``. A file that is
there and has the right checksum is left alone; a missing or damaged one is downloaded again;
a download with the wrong checksum is removed and fails with a message. Only audio is fetched.
This is the one place that uses the network for the demo songs (the fast tests use a fake).
"""

import argparse
import hashlib
import sys
import time
import tomllib
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CLONE = Path(__file__).resolve().parents[1]
SONG_LIST = CLONE / "tests" / "data" / "demo" / "demo.toml"
DEFAULT_FOLDER = CLONE / ".corpus" / "demo"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) vocatron-demo-songs"
TIMEOUT = 120  # seconds for one connection
ATTEMPTS = 4  # the Internet Archive answers now and then with a 5xx; try again after a pause
PAUSE = 5.0  # seconds between two attempts
CHUNK = 1 << 20

Download = Callable[[str, Path], None]
"""Fetches a URL into a file path (the network edge; tests pass a fake)."""


class DemoSongError(Exception):
    """A demo song cannot be provided; the message says which and why."""


@dataclass(frozen=True)
class DemoSong:
    """One demo song of ``demo.toml``.

    Attributes:
        file: The name of the audio file in the demo folder; its stem names the lyrics file.
        artist: The artist.
        title: The title.
        language: The language of the lyrics (``de`` or ``en``).
        licence: The licence's name.
        licence_url: Where the licence is written down.
        source_url: The artist's page of the song.
        download_url: Where the audio file is fetched from.
        sha256: The checksum the downloaded file must have, as lower-case hexadecimal text.
        seconds: The length of the song.
    """

    file: str
    artist: str
    title: str
    language: str
    licence: str
    licence_url: str
    source_url: str
    download_url: str
    sha256: str
    seconds: float

    @property
    def stem(self) -> str:
        """Return the file name without suffix: the name of the song and of its lyrics file."""
        return Path(self.file).stem


def load_songs(text: str) -> list[DemoSong]:
    """Read the song list.

    Args:
        text: The content of ``demo.toml``.

    Returns:
        The songs in file order.

    Raises:
        DemoSongError: If an entry lacks a field or has an unknown one.
    """
    entries = tomllib.loads(text).get("song", [])
    songs: list[DemoSong] = []
    for entry in entries:
        try:
            songs.append(DemoSong(**entry))
        except TypeError as error:
            raise DemoSongError(f"demo.toml: bad song entry ({error})") from error
    return songs


def sha256_of(path: Path) -> str:
    """Return the SHA-256 of a file as lower-case hexadecimal text."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def fetch(song: DemoSong, folder: Path, download: Download) -> str:
    """Make sure the audio of ``song`` is in ``folder`` with the right checksum.

    Args:
        song: The song.
        folder: The demo folder.
        download: Fetches a URL into a file.

    Returns:
        ``"present"`` when a good file was there, ``"downloaded"`` otherwise.

    Raises:
        DemoSongError: If the downloaded file has the wrong checksum or the download fails;
            nothing is kept in either case.
    """
    target = folder / song.file
    if target.is_file() and sha256_of(target) == song.sha256:
        return "present"
    folder.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.unlink(missing_ok=True)
    try:
        download(song.download_url, partial)
    except BaseException:
        partial.unlink(missing_ok=True)  # a broken download leaves no half file behind
        raise
    found = sha256_of(partial)
    if found != song.sha256:
        partial.unlink()
        raise DemoSongError(
            f"{song.file}: wrong checksum from {song.download_url}: expected {song.sha256}, "
            f"got {found}. The source changed or the download broke; nothing was kept."
        )
    partial.replace(target)
    return "downloaded"


def http_download(url: str, target: Path) -> None:
    """Fetch ``url`` into ``target``, trying again after a server error.

    Raises:
        DemoSongError: If every attempt failed.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    problem = ""
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(PAUSE)
        try:
            with (
                urllib.request.urlopen(request, timeout=TIMEOUT) as response,
                target.open("wb") as out,
            ):
                while block := response.read(CHUNK):
                    out.write(block)
            return
        except OSError as error:  # URLError and timeouts are OSErrors too
            problem = str(error)
    raise DemoSongError(f"{url}: download failed after {ATTEMPTS} attempts ({problem})")


def main(argv: list[str], download: Download = http_download) -> int:
    """Provide every demo song; print one line per song (file name, state, size)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER, help="where the audio goes")
    parser.add_argument("--list", type=Path, default=SONG_LIST, help="the song list (TOML)")
    args = parser.parse_args(argv)
    try:
        songs = load_songs(args.list.read_text("utf-8"))
        for song in songs:
            state = fetch(song, args.folder, download)
            size = (args.folder / song.file).stat().st_size
            print(
                f"{song.file}: {state} ({size} bytes, sha256 ok; {song.licence}, {song.source_url})"
            )
    except (DemoSongError, OSError) as error:
        print(f"demo-songs: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
