"""The real file system behind the ``FileStore`` protocol."""

import hashlib
import os
import tempfile
import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Literal

from vocatron.engines.protocols import AUDIO_SUFFIXES, LogSink

CHUNK = 1 << 20
FOLLOW_INTERVAL = 0.2  # seconds between two looks at a followed log for lines of other writers


def _umask() -> int:
    """Return the process's umask (read once, at import, before any thread runs)."""
    mask = os.umask(0)
    os.umask(mask)
    return mask


NEW_FILE_MODE = 0o666 & ~_umask()
"""The mode of a file written by the store: what ``open`` would give a new file."""


class _Follower:
    """Hands every complete line appended to a file after its start to ``handle``, each once.

    A thread looks for new lines every ``FOLLOW_INTERVAL`` seconds (another process writes to the
    file too); ``drain`` looks at once. Reading from one offset under a lock keeps the lines in
    the order of the file and hands none of them twice.
    """

    def __init__(self, path: Path, handle: Callable[[str], None]) -> None:
        """Follow ``path`` from its current end."""
        self._file = path.open("rb")
        self._file.seek(0, os.SEEK_END)
        self._handle = handle
        self._partial = b""
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def _watch(self) -> None:
        while not self._stopped.wait(FOLLOW_INTERVAL):
            self.drain()

    def drain(self, *, last: bool = False) -> None:
        """Hand on the lines that are complete now; a line still being written waits.

        With ``last`` nobody writes any more, so a line without an end (a writer that was killed
        while writing it) is handed on as it is rather than lost.
        """
        with self._lock, suppress(OSError):  # a log that cannot be read must not fail the song
            data = self._partial + self._file.read()
            *lines, self._partial = data.split(b"\n")
            if last and self._partial:
                lines.append(self._partial)
                self._partial = b""
            for line in lines:
                self._handle(line.decode("utf-8", errors="replace").rstrip("\r"))

    def close(self) -> None:
        """Stop the thread and hand on the last lines."""
        self._stopped.set()
        self._thread.join()
        self.drain(last=True)
        self._file.close()


class FileLog:
    """A log file that is flushed and synced after every line, and optionally followed."""

    def __init__(self, path: Path, follow: Callable[[str], None] | None = None) -> None:
        """Open ``path`` for appending; ``follow`` gets every line appended while it is open.

        See ``FileStore.open_log``.
        """
        self._file = path.open("a", encoding="utf-8")
        try:
            self._follower = None if follow is None else _Follower(path, follow)
        except BaseException:
            self._file.close()
            raise

    def write(self, line: str) -> None:
        """Append ``line`` and force it to disk."""
        self._file.write(line.rstrip("\n") + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())
        if self._follower is not None:
            self._follower.drain()  # our own line shows at once, after those written before it

    def close(self) -> None:
        """Close the file, after the last lines were handed on."""
        try:
            if self._follower is not None:
                self._follower.close()
        finally:
            self._file.close()


class LocalFileStore:
    """Files on the local disk."""

    def kind(self, path: Path) -> Literal["file", "folder"] | None:
        """Say whether ``path`` is a file, a folder, or missing."""
        if path.is_dir():
            return "folder"
        return "file" if path.is_file() else None

    def list_audio(self, folder: Path) -> list[Path]:
        """List the audio files directly in ``folder``, sorted."""
        return sorted(
            p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES
        )

    def list_files(self, folder: Path, suffixes: tuple[str, ...]) -> list[Path]:
        """List the files directly in ``folder`` that end in one of ``suffixes``, sorted."""
        if not folder.is_dir():
            return []
        return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in suffixes)

    def read_text(self, path: Path) -> str | None:
        """Return the text of ``path``, or ``None`` when it does not exist."""
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def write_text(self, path: Path, text: str) -> None:
        """Write ``path`` atomically and durably as UTF-8 text (see ``write_bytes``)."""
        self.write_bytes(path, text.encode("utf-8"))

    def write_bytes(self, path: Path, data: bytes) -> None:
        """Write ``path`` atomically and durably: a synced temporary file, then a rename.

        After a crash the file holds either the old or the new content, never a part of it. The
        file gets the mode a plain new file gets (``0o666`` less the umask), not the private mode
        of a temporary file, so the products in the output folder can be shared like the video.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(handle, "wb") as file:
                os.fchmod(file.fileno(), NEW_FILE_MODE)  # before the sync, so the mode is durable
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            Path(temporary).replace(path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def sha256(self, path: Path) -> str | None:
        """Return the SHA-256 of the content of ``path``, or ``None`` when it does not exist."""
        digest = hashlib.sha256()
        try:
            with path.open("rb") as file:
                while chunk := file.read(CHUNK):
                    digest.update(chunk)
        except FileNotFoundError:
            return None
        return digest.hexdigest()

    def size(self, path: Path) -> int | None:
        """Return the size of ``path`` in bytes, or ``None`` when it does not exist."""
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return None

    def delete(self, path: Path) -> None:
        """Delete the file ``path`` if it exists."""
        path.unlink(missing_ok=True)

    def writable(self, folder: Path) -> bool:
        """Tell whether ``folder``, or its nearest existing parent, is a writable folder."""
        for candidate in (folder, *folder.parents):
            if candidate.exists():
                return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)
        return False

    def make_folder(self, path: Path) -> None:
        """Create ``path`` and its parents if missing."""
        path.mkdir(parents=True, exist_ok=True)

    def open_log(self, path: Path, follow: Callable[[str], None] | None = None) -> LogSink:
        """Open the log file ``path`` for appending; see ``FileStore.open_log``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        return FileLog(path, follow)
