"""A downloader that serves canned bytes into the in-memory store, and tiny model specs."""

import hashlib
from collections.abc import Callable
from pathlib import Path

from fakes.files import InMemoryFileStore
from vocatron.core.models import ModelFile, ModelSpec
from vocatron.engines.protocols import DownloadError, Progress


def tiny_spec(name: str, files: dict[str, bytes], licence: str = "MIT") -> ModelSpec:
    """Build a model whose files have the given content; URLs are ``fake://<name>/<path>``."""
    return ModelSpec(
        name=name,
        source_name=f"acme/{name}",
        purpose="testing",
        source="nowhere",
        revision="r1",
        licence=licence,
        licence_url=None,
        inference={},
        files=tuple(
            ModelFile(
                url=f"fake://{name}/{path}",
                path=path,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
            for path, data in files.items()
        ),
    )


def returning(spec: ModelSpec) -> Callable[[str], ModelSpec]:
    """Return a stand-in for ``find_model`` that answers ``spec`` for every name."""

    def find(name: str) -> ModelSpec:
        del name
        return spec

    return find


class FakeDownloader:
    """Serves ``contents[url]`` into the store; records what was asked for."""

    def __init__(self, store: InMemoryFileStore) -> None:
        self.store = store
        self.contents: dict[str, bytes] = {}
        self.calls: list[tuple[str, Path]] = []
        self.fail_on: set[str] = set()  # URLs that fail like a lost connection
        self.phantoms: set[str] = set()  # URLs of big files served as empty placeholders

    def serve(self, spec: ModelSpec, files: dict[str, bytes]) -> None:
        """Make the files of ``spec`` available."""
        for file in spec.files:
            self.contents[file.url] = files[file.path]

    def download(self, file: ModelFile, destination: Path, progress: Progress) -> None:
        self.calls.append((file.url, destination))
        if file.url in self.phantoms:
            self.store.add_phantom(destination, file.size)
            return
        if file.url in self.fail_on:
            raise DownloadError(f"{file.url}: connection lost")
        data = self.contents.get(file.url)
        if data is None:
            raise DownloadError(f"{file.url}: HTTP 404")
        progress(0, file.size)
        if hashlib.sha256(data).hexdigest() != file.sha256:
            raise DownloadError(f"{file.url}: checksum mismatch")
        self.store.add(destination, data)
        progress(file.size, file.size)
