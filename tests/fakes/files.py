"""A file store that keeps everything in memory."""

import errno
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from vocatron.engines.protocols import AUDIO_SUFFIXES, LogSink


class MemoryLog:
    """A log that keeps its lines in a list and counts how often it was closed.

    Every writer of one path shares it (as processes share a file); a line written by any of them
    goes at once to the followers of the path.
    """

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.closed = 0
        self.followers: list[Callable[[str], None]] = []

    def write(self, line: str) -> None:
        self.lines.append(line)
        for follow in list(self.followers):
            follow(line)

    def close(self) -> None:
        self.closed += 1


class FollowedLog:
    """One opening of a ``MemoryLog`` with a follower, which it drops again when closed."""

    def __init__(self, log: MemoryLog, follow: Callable[[str], None]) -> None:
        self.log = log
        self.follow = follow
        log.followers.append(follow)

    def write(self, line: str) -> None:
        self.log.write(line)

    def close(self) -> None:
        self.log.followers.remove(self.follow)
        self.log.close()


class InMemoryFileStore:
    """Files as bytes in a dictionary; folders are implied by the files and ``make_folder``."""

    def __init__(self) -> None:
        self.files: dict[Path, bytes] = {}
        self.folders: set[Path] = set()
        self.logs: dict[Path, MemoryLog] = {}
        self.writes: list[Path] = []
        self.unwritable: set[Path] = set()  # ``make_folder`` fails at or below these
        self.full: set[Path] = set()  # ``write_text`` fails at or below these: a full disk
        self.phantom_sizes: dict[Path, int] = {}  # big files that need no bytes

    def add(self, path: Path, data: bytes = b"audio") -> None:
        """Put a file in the store (not counted as a write by Vocatron)."""
        self.files[path] = data
        self.folders.update(path.parents)

    def kind(self, path: Path) -> Literal["file", "folder"] | None:
        if path in self.files:
            return "file"
        return "folder" if path in self.folders else None

    def list_audio(self, folder: Path) -> list[Path]:
        return sorted(
            p for p in self.files if p.parent == folder and p.suffix.lower() in AUDIO_SUFFIXES
        )

    def list_files(self, folder: Path, suffixes: tuple[str, ...]) -> list[Path]:
        return sorted(p for p in self.files if p.parent == folder and p.suffix.lower() in suffixes)

    def read_text(self, path: Path) -> str | None:
        data = self.files.get(path)
        return None if data is None else data.decode("utf-8")

    def write_text(self, path: Path, text: str) -> None:
        self.write_bytes(path, text.encode("utf-8"))

    def write_bytes(self, path: Path, data: bytes) -> None:
        if self.full & {path, *path.parents}:
            raise OSError(errno.ENOSPC, "No space left on device", str(path))
        self.writes.append(path)
        self.add(path, data)

    def sha256(self, path: Path) -> str | None:
        data = self.files.get(path)
        return None if data is None else hashlib.sha256(data).hexdigest()

    def add_phantom(self, path: Path, size: int) -> None:
        """Put in a file that reports ``size`` bytes without holding them (a model checkpoint)."""
        self.phantom_sizes[path] = size
        self.add(path, b"phantom")

    def size(self, path: Path) -> int | None:
        if path in self.phantom_sizes:
            return self.phantom_sizes[path]
        data = self.files.get(path)
        return None if data is None else len(data)

    def delete(self, path: Path) -> None:
        self.files.pop(path, None)

    def writable(self, folder: Path) -> bool:
        return not self.unwritable & {folder, *folder.parents} and (self.kind(folder) != "file")

    def make_folder(self, path: Path) -> None:
        if self.unwritable & {path, *path.parents}:
            raise PermissionError(13, "Permission denied", str(path))
        self.folders.add(path)
        self.folders.update(path.parents)

    def open_log(self, path: Path, follow: Callable[[str], None] | None = None) -> LogSink:
        log = self.logs.setdefault(path, MemoryLog([]))
        self.make_folder(path.parent)
        return log if follow is None else FollowedLog(log, follow)

    def log_lines(self, path: Path) -> list[str]:
        """Return the lines written to the log at ``path``."""
        return self.logs[path].lines
