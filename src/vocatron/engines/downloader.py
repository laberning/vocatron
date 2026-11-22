"""The model downloader on urllib3: resume, timeouts, retries and a SHA-256 check (ADR-0002).

One module fetches every model file, whether it lives on Hugging Face or in a GitHub release.
Data goes to ``<file>.part`` next to the destination, never into a system temporary folder.
"""

import hashlib
import re
import time
from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path

import urllib3
from urllib3.exceptions import HTTPError

from vocatron.core.models import ModelFile, part_path
from vocatron.engines.protocols import DownloadError, Progress

CHUNK = 1 << 20
ATTEMPTS = 5
TIMEOUT = urllib3.Timeout(connect=15.0, read=60.0)
RETRY_STATUS = frozenset(
    {
        HTTPStatus.REQUEST_TIMEOUT,
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }
)
USER_AGENT = "vocatron"
CONTENT_RANGE = re.compile(r"bytes (\d+)-\d+/(\d+|\*)")


class _Retry(Exception):
    """An attempt failed in a way that is worth another try (the part file is kept)."""


def sha256_of(path: Path) -> str:
    """Return the SHA-256 of a file as lower-case hex."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class Urllib3Downloader:
    """Downloads model files over HTTP(S) with urllib3."""

    def __init__(
        self,
        *,
        attempts: int = ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
        pool: urllib3.PoolManager | None = None,
    ) -> None:
        """Create the downloader.

        Args:
            attempts: How often one file is tried before it fails.
            sleep: Waits between attempts (injected so that tests do not wait).
            pool: The connection pool; by default one with a timeout and no hidden retries.
        """
        self._attempts = attempts
        self._sleep = sleep
        self._pool = pool or urllib3.PoolManager(
            timeout=TIMEOUT,
            retries=urllib3.Retry(connect=0, read=0, status=0, other=0, redirect=5),
            headers={"User-Agent": USER_AGENT},
        )

    def download(self, file: ModelFile, destination: Path, progress: Progress) -> None:
        """Download ``file`` to ``destination``, resuming ``<destination>.part`` if it exists.

        Raises:
            DownloadError: After the last failed attempt, on an answer that cannot be right
                (such as 404), or when the finished file has the wrong checksum (it is deleted).
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        part = part_path(destination)
        reason = ""
        for attempt in range(self._attempts):
            if attempt:
                self._sleep(min(2.0**attempt, 30.0))
            try:
                self._fetch(file, part, progress)
                break
            except _Retry as retry:
                reason = str(retry)
        else:
            raise DownloadError(
                f"{file.url}: giving up after {self._attempts} attempts ({reason}). "
                "Run the command again to resume."
            )
        self._finish(file, part, destination)

    def _fetch(self, file: ModelFile, part: Path, progress: Progress) -> None:
        """Make one attempt: ask for the rest of the file and append it to ``part``."""
        have = part.stat().st_size if part.exists() else 0
        if have > file.size:
            part.unlink()
            have = 0
        if have == file.size:
            return
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            # A body cut short is judged by our own size check, so that the bytes that did arrive
            # are written and the next attempt resumes after them.
            response = self._pool.request(
                "GET",
                file.url,
                headers=headers,
                preload_content=False,
                enforce_content_length=False,
            )
        except HTTPError as error:
            raise _Retry(type(error).__name__) from error
        try:
            have = self._accept(response.status, response.headers.get("Content-Range"), have, file)
            self._write(response, part, have, file, progress)
        except HTTPError, OSError:
            # a cut connection or a timeout in the middle; the data so far stays in the part file
            raise _Retry("connection lost") from None
        finally:
            response.release_conn()

    @staticmethod
    def _accept(status: int, content_range: str | None, have: int, file: ModelFile) -> int:
        """Check the answer and return the offset at which the body starts.

        Raises:
            DownloadError: On an answer that more attempts will not fix.
            _Retry: On a server error.
        """
        if status == HTTPStatus.PARTIAL_CONTENT:
            match = CONTENT_RANGE.match(content_range or "")
            if match is None or int(match.group(1)) != have:
                raise DownloadError(f"{file.url}: the server answered with a wrong range")
            return have
        if status == HTTPStatus.OK:
            return 0  # the server ignored the range: start again
        if status in RETRY_STATUS:
            raise _Retry(f"HTTP {status}")
        raise DownloadError(f"{file.url}: HTTP {status}")

    @staticmethod
    def _write(
        response: urllib3.BaseHTTPResponse,
        part: Path,
        offset: int,
        file: ModelFile,
        progress: Progress,
    ) -> None:
        """Write the body to ``part`` from ``offset`` on, reporting progress."""
        done = offset
        with part.open("r+b" if offset else "wb") as out:
            out.seek(offset)
            progress(done, file.size)
            for chunk in response.stream(CHUNK):
                out.write(chunk)
                done += len(chunk)
                progress(done, file.size)
            out.flush()
        if done != file.size:
            raise _Retry(f"got {done} of {file.size} bytes")

    @staticmethod
    def _finish(file: ModelFile, part: Path, destination: Path) -> None:
        """Verify the finished part file and move it into place; delete it on a mismatch."""
        actual = sha256_of(part)
        if actual != file.sha256:
            part.unlink()
            raise DownloadError(
                f"{file.url}: checksum mismatch (expected {file.sha256}, got {actual}); "
                "the file was deleted"
            )
        part.replace(destination)
