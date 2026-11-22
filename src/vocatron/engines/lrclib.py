"""The LRCLIB client on urllib3 (ADR-0002).

LRCLIB needs no key. The requests name Vocatron in the ``User-Agent``. The lyrics are fetched for
the fan's own files and never redistributed. A request is repeated once after a connection error
or a server error.
"""

import json
from importlib.metadata import version
from urllib.parse import urlsplit

import urllib3
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from urllib3.exceptions import HTTPError

from vocatron.core.lyrics.versions import Candidate
from vocatron.engines.protocols import LyricsLookupError

BASE_URL = "https://lrclib.net"
PROJECT_URL = "https://github.com/laberning/vocatron"
TIMEOUT = urllib3.Timeout(connect=10.0, read=20.0)
ATTEMPTS = 2  # one retry
NOT_FOUND = 404
SERVER_ERROR = 500
OK = 200


def user_agent() -> str:
    """Return the ``User-Agent`` that names Vocatron, its version and its home."""
    return f"Vocatron/{version('vocatron')} (+{PROJECT_URL})"


class _Record(BaseModel):
    """A record as LRCLIB writes it; unknown fields are ignored."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int | None = None
    track_name: str = Field(alias="trackName")
    artist_name: str | None = Field(default=None, alias="artistName")
    album_name: str | None = Field(default=None, alias="albumName")
    duration: float | None = None
    instrumental: bool = False
    plain_lyrics: str | None = Field(default=None, alias="plainLyrics")
    synced_lyrics: str | None = Field(default=None, alias="syncedLyrics")

    def candidate(self) -> Candidate:
        """Return the record as a candidate."""
        return Candidate(
            source_id=self.id,
            artist=self.artist_name,
            title=self.track_name,
            album=self.album_name,
            duration=self.duration,
            instrumental=self.instrumental,
            plain=self.plain_lyrics,
            synced=self.synced_lyrics,
        )


def _unique(candidates: list[Candidate]) -> list[Candidate]:
    """Drop the records that appear twice (the exact record is also in the search results)."""
    seen: set[int] = set()
    unique: list[Candidate] = []
    for candidate in candidates:
        if candidate.source_id is not None:
            if candidate.source_id in seen:
                continue
            seen.add(candidate.source_id)
        unique.append(candidate)
    return unique


class LrclibSource:
    """Asks LRCLIB for lyrics: the exact record first, then a search."""

    def __init__(
        self, *, base_url: str = BASE_URL, pool: urllib3.PoolManager | None = None
    ) -> None:
        """Create the client.

        Args:
            base_url: The server; tests point it at a local one.
            pool: The connection pool; by default one with a timeout, the ``User-Agent`` and no
                hidden retries.
        """
        self._base = base_url.rstrip("/")
        self._pool = pool or urllib3.PoolManager(
            timeout=TIMEOUT,
            retries=urllib3.Retry(connect=0, read=0, status=0, other=0, redirect=2),
            headers={"User-Agent": user_agent()},
        )

    def find(self, artist: str | None, title: str, duration: float | None) -> list[Candidate]:
        """Return the exact record (``/api/get``) and the search results (``/api/search``).

        Raises:
            LyricsLookupError: If LRCLIB cannot be reached or answers with something unusable.
        """
        found: list[Candidate] = []
        if artist is not None and duration is not None:
            exact = self._get(
                "/api/get",
                {"artist_name": artist, "track_name": title, "duration": str(round(duration))},
            )
            if isinstance(exact, dict):
                found.append(self._record(exact))
        query = (
            {"track_name": title}
            if artist is None
            else {"track_name": title, "artist_name": artist}
        )
        listed = self._get("/api/search", query)
        if isinstance(listed, list):
            found += [self._record(item) for item in listed]
        return _unique(found)

    @staticmethod
    def _record(data: object) -> Candidate:
        """Read one record.

        Raises:
            LyricsLookupError: If it is not a record.
        """
        try:
            return _Record.model_validate(data).candidate()
        except ValidationError as error:
            raise LyricsLookupError(f"LRCLIB sent a record that cannot be read: {error}") from error

    def _get(self, path: str, fields: dict[str, str]) -> object:
        """Ask for ``path`` and return the JSON answer; ``None`` for 404.

        Raises:
            LyricsLookupError: After the last failed attempt or on an unexpected answer.
        """
        url = f"{self._base}{path}"
        host = urlsplit(url).netloc
        reason = ""
        for _ in range(ATTEMPTS):
            try:
                response = self._pool.request("GET", url, fields=fields)
            except HTTPError as error:
                reason = f"{type(error).__name__}"
                continue
            if response.status == NOT_FOUND:
                return None
            if response.status >= SERVER_ERROR:
                reason = f"HTTP {response.status}"
                continue
            if response.status != OK:
                raise LyricsLookupError(f"{host}{path}: HTTP {response.status}")
            try:
                answer: object = json.loads(response.data)  # of unknown shape; checked by _record
                return answer
            except ValueError as error:
                raise LyricsLookupError(f"{host}{path}: the answer is not JSON") from error
        raise LyricsLookupError(f"{host} not reachable ({reason})")
