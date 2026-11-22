"""Stage 1: the urllib3 downloader against a local HTTP server (no network beyond loopback)."""

import hashlib
import threading
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast, override

import pytest
import urllib3
from urllib3.exceptions import ProtocolError

from vocatron.core.models import ModelFile, part_path
from vocatron.engines.downloader import Urllib3Downloader, sha256_of
from vocatron.engines.protocols import DownloadError

DATA = bytes(range(256)) * 400  # 102 400 bytes
pytestmark = pytest.mark.allow_hosts(["127.0.0.1"])


class Plan:
    """What the server does for the next requests: statuses to answer, bytes to cut off after."""

    def __init__(self) -> None:
        self.statuses: list[int] = []  # answered before the normal behaviour, one per request
        self.cut_after: list[int | None] = []  # per request: send only this many bytes, then close
        self.ignore_range = False
        self.range_shift = 0  # added to the start the server names in Content-Range
        self.requests: list[str | None] = []  # the Range header of each request
        self.body = DATA


def handler_for(plan: Plan) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        @override
        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def do_GET(self) -> None:
            self.requests_header = self.headers.get("Range")
            plan.requests.append(self.requests_header)
            if plan.statuses and (status := plan.statuses.pop(0)) != 200:
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            start = 0
            if self.requests_header and not plan.ignore_range:
                start = int(self.requests_header.removeprefix("bytes=").rstrip("-"))
            body = plan.body[start:]
            self.send_response(206 if start else 200)
            if start:
                total = len(plan.body)
                named = start + plan.range_shift
                self.send_header("Content-Range", f"bytes {named}-{total - 1}/{total}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            cut = plan.cut_after.pop(0) if plan.cut_after else None
            self.wfile.write(body if cut is None else body[:cut])
            self.wfile.flush()
            self.close_connection = True

    return Handler


@contextmanager
def serve(plan: Plan) -> Generator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(plan))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/file.bin"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def model_file(url: str, data: bytes = DATA) -> ModelFile:
    return ModelFile(
        url=url, path="file.bin", size=len(data), sha256=hashlib.sha256(data).hexdigest()
    )


def downloader(attempts: int = 4) -> Urllib3Downloader:
    return Urllib3Downloader(attempts=attempts, sleep=lambda seconds: None)


def test_a_download_is_verified_and_moved_into_place(tmp_path: Path) -> None:
    seen: list[tuple[int, int]] = []
    with serve(Plan()) as url:
        target = tmp_path / "model" / "file.bin"
        downloader().download(
            model_file(url), target, lambda done, total: seen.append((done, total))
        )
    assert target.read_bytes() == DATA
    assert not part_path(target).exists()
    assert seen[0] == (0, len(DATA))
    assert seen[-1] == (len(DATA), len(DATA))


def test_a_cut_connection_is_resumed_with_a_range_request(tmp_path: Path) -> None:
    plan = Plan()
    plan.cut_after = [40_000]
    with serve(plan) as url:
        target = tmp_path / "file.bin"
        downloader().download(model_file(url), target, lambda done, total: None)
    assert target.read_bytes() == DATA
    assert plan.requests == [None, "bytes=40000-"]


def test_a_part_file_from_an_earlier_run_is_resumed(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    part_path(target).write_bytes(DATA[:1000])
    plan = Plan()
    with serve(plan) as url:
        downloader().download(model_file(url), target, lambda done, total: None)
    assert plan.requests == ["bytes=1000-"]
    assert target.read_bytes() == DATA


def test_a_server_that_ignores_the_range_starts_over(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    part_path(target).write_bytes(b"garbage that is not the start of the file")
    plan = Plan()
    plan.ignore_range = True
    with serve(plan) as url:
        downloader().download(model_file(url), target, lambda done, total: None)
    assert target.read_bytes() == DATA


def test_server_errors_are_retried(tmp_path: Path) -> None:
    plan = Plan()
    plan.statuses = [503, 429]
    with serve(plan) as url:
        downloader().download(model_file(url), tmp_path / "file.bin", lambda done, total: None)
    assert len(plan.requests) == 3


def test_giving_up_keeps_the_part_file_for_the_next_run(tmp_path: Path) -> None:
    plan = Plan()
    plan.cut_after = [10, 10, 10]
    target = tmp_path / "file.bin"
    with serve(plan) as url, pytest.raises(DownloadError, match="giving up after 3 attempts"):
        downloader(attempts=3).download(model_file(url), target, lambda done, total: None)
    assert part_path(target).stat().st_size == 30
    assert not target.exists()


def test_not_found_fails_at_once(tmp_path: Path) -> None:
    plan = Plan()
    plan.statuses = [404]
    with serve(plan) as url, pytest.raises(DownloadError, match="HTTP 404"):
        downloader().download(model_file(url), tmp_path / "file.bin", lambda done, total: None)
    assert len(plan.requests) == 1


def test_a_checksum_mismatch_deletes_the_file_and_fails_clearly(tmp_path: Path) -> None:
    plan = Plan()
    plan.body = DATA[:-1] + b"X"
    target = tmp_path / "file.bin"
    with serve(plan) as url, pytest.raises(DownloadError, match="checksum mismatch"):
        downloader().download(model_file(url), target, lambda done, total: None)
    assert not target.exists()
    assert not part_path(target).exists()


def test_a_part_file_that_is_too_big_is_discarded(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    part_path(target).write_bytes(DATA + b"more")
    plan = Plan()
    with serve(plan) as url:
        downloader().download(model_file(url), target, lambda done, total: None)
    assert plan.requests == [None]
    assert target.read_bytes() == DATA


def test_a_complete_part_file_is_only_verified(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    part_path(target).write_bytes(DATA)
    plan = Plan()
    with serve(plan) as url:
        downloader().download(model_file(url), target, lambda done, total: None)
    assert plan.requests == []
    assert sha256_of(target) == hashlib.sha256(DATA).hexdigest()


def test_a_wrong_content_range_is_an_error_at_once(tmp_path: Path) -> None:
    target = tmp_path / "file.bin"
    part_path(target).write_bytes(DATA[:1000])
    plan = Plan()
    plan.range_shift = 1  # the body would land one byte off
    with serve(plan) as url, pytest.raises(DownloadError, match="wrong range"):
        downloader().download(model_file(url), target, lambda done, total: None)
    assert len(plan.requests) == 1


class CannedResponse:
    """An answer that sends ``body`` and then, if ``broken``, fails like a reset connection."""

    def __init__(self, status: int, headers: dict[str, str], body: bytes, *, broken: bool) -> None:
        self.status = status
        self.headers = headers
        self.body = body
        self.broken = broken

    def stream(self, amount: int) -> Iterator[bytes]:
        del amount
        yield self.body
        if self.broken:
            raise ProtocolError("Connection broken: reset by peer")

    def release_conn(self) -> None:
        pass


class BreakingPool:
    """A pool whose first answer breaks off after 5000 bytes; the second sends the rest."""

    def __init__(self) -> None:
        self.ranges: list[str | None] = []

    def request(self, method: str, url: str, **kwargs: Any) -> CannedResponse:
        del method, url
        self.ranges.append(kwargs["headers"].get("Range"))
        if len(self.ranges) == 1:
            return CannedResponse(200, {}, DATA[:5000], broken=True)
        rest = {"Content-Range": f"bytes 5000-{len(DATA) - 1}/{len(DATA)}"}
        return CannedResponse(206, rest, DATA[5000:], broken=False)


def test_a_connection_reset_in_the_body_keeps_the_bytes_and_resumes(tmp_path: Path) -> None:
    pool = BreakingPool()
    target = tmp_path / "file.bin"
    loader = Urllib3Downloader(sleep=lambda seconds: None, pool=cast("urllib3.PoolManager", pool))
    loader.download(model_file("https://example.org/file.bin"), target, lambda done, total: None)
    assert pool.ranges == [None, "bytes=5000-"]
    assert target.read_bytes() == DATA


def test_an_unreachable_server_is_retried_then_reported(tmp_path: Path) -> None:
    file = model_file("http://127.0.0.1:9/file.bin")
    with pytest.raises(DownloadError, match="giving up after 2 attempts"):
        downloader(attempts=2).download(file, tmp_path / "file.bin", lambda done, total: None)
