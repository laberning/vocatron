"""Stage 1: the LRCLIB client against a local server answering with hand-written JSON.

The records are written by hand in LRCLIB's format around public-domain songs; nothing is recorded
from the real service and nothing leaves the machine.
"""

import json
import threading
from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import override
from urllib.parse import parse_qs, urlsplit

import pytest

from fakes.lyrics import ENTCHEN, VOGEL, lrclib_record, synced_of
from vocatron.engines.lrclib import LrclibSource, user_agent
from vocatron.engines.protocols import LyricsLookupError

pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])


class Plan:
    """What the server answers: a body or status per path, and what it was asked."""

    def __init__(self) -> None:
        self.answers: dict[str, list[tuple[int, bytes]]] = {}
        self.requests: list[tuple[str, dict[str, list[str]], str | None]] = []

    def answer(self, path: str, status: int, body: object = b"") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.answers.setdefault(path, []).append((status, data))


def handler_for(plan: Plan) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        @override
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            plan.requests.append((url.path, parse_qs(url.query), self.headers.get("User-Agent")))
            queue = plan.answers.get(url.path, [])
            status, body = queue.pop(0) if len(queue) > 1 else (queue[0] if queue else (404, b""))
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


@contextmanager
def serving(plan: Plan) -> Generator[LrclibSource]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(plan))
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    )
    thread.start()
    try:
        yield LrclibSource(base_url=f"http://127.0.0.1:{server.server_port}/")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def entchen(record_id: int, **more: object) -> dict[str, object]:
    return lrclib_record(
        record_id=record_id,
        artist="Volkslied",
        title="Alle meine Entchen",
        duration=180.0,
        plainLyrics=ENTCHEN,
        **more,
    )


def test_the_exact_record_comes_first_then_the_search_results_without_duplicates() -> None:
    plan = Plan()
    plan.answer("/api/get", 200, entchen(1, syncedLyrics=synced_of(ENTCHEN)))
    plan.answer("/api/search", 200, [entchen(1), entchen(2), {**entchen(3), "extra": "ignored"}])
    with serving(plan) as source:
        found = source.find("Volkslied", "Alle meine Entchen", 179.6)
    assert [c.source_id for c in found] == [1, 2, 3]
    assert found[0].synced == synced_of(ENTCHEN)
    assert found[1].plain == ENTCHEN
    assert found[0].artist == "Volkslied"
    get, search = plan.requests
    assert get[0:2] == (
        "/api/get",
        {"artist_name": ["Volkslied"], "track_name": ["Alle meine Entchen"], "duration": ["180"]},
    )
    assert search[1] == {"track_name": ["Alle meine Entchen"], "artist_name": ["Volkslied"]}
    assert get[2] == search[2] == user_agent()
    assert user_agent().startswith("Vocatron/")
    assert "https://github.com/laberning/vocatron" in user_agent()


def test_without_artist_or_duration_only_the_search_runs() -> None:
    plan = Plan()
    plan.answer(
        "/api/search", 200, [lrclib_record(record_id=7, artist="x", title="VOGEL", duration=1)]
    )
    with serving(plan) as source:
        assert [c.source_id for c in source.find(None, "Kommt ein Vogel geflogen", None)] == [7]
        source.find("Volkslied", "Kommt ein Vogel geflogen", None)
    assert [path for path, _, _ in plan.requests] == ["/api/search", "/api/search"]
    assert plan.requests[0][1] == {"track_name": ["Kommt ein Vogel geflogen"]}


def test_not_found_is_an_empty_answer() -> None:
    with serving(Plan()) as source:
        assert source.find("Volkslied", "Unbekannt", 100) == []


def test_a_server_error_is_tried_once_more() -> None:
    plan = Plan()
    plan.answer("/api/get", 503)
    plan.answer("/api/get", 200, entchen(1))
    plan.answer("/api/search", 404)
    with serving(plan) as source:
        assert [c.source_id for c in source.find("Volkslied", "Alle meine Entchen", 180)] == [1]
    assert [path for path, _, _ in plan.requests] == ["/api/get", "/api/get", "/api/search"]


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (500, b"", "not reachable \\(HTTP 500\\)"),
        (403, b"", "HTTP 403"),
        (200, b"<html>", "not JSON"),
        (200, [{"trackName": 5}], "cannot be read"),
    ],
)
def test_a_failing_or_unreadable_answer_is_a_lookup_error(
    status: int, body: object, message: str
) -> None:
    plan = Plan()
    plan.answer("/api/search", status, body)
    with serving(plan) as source, pytest.raises(LyricsLookupError, match=message):
        source.find(None, "Kommt ein Vogel geflogen", None)


def test_an_unreachable_server_is_a_lookup_error() -> None:
    with serving(Plan()) as source:
        pass  # the server is gone now
    with pytest.raises(LyricsLookupError, match="not reachable"):
        source.find(None, VOGEL, None)
