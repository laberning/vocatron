"""The model folder: what is in it, and getting what is missing (ADR-0002, ADR-0007).

``ModelFolder`` judges the state of each model with the pure rules of ``vocatron.core.models``.
``fetch`` downloads what is not there, and ``ensure_models`` is what a stage's declaration turns
into: download on first use, or, offline, a message naming the command to run.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from vocatron.core.errors import StageError
from vocatron.core.models import (
    ModelFile,
    ModelSpec,
    Observed,
    State,
    file_state,
    find_model,
    human_size,
    model_state,
    part_path,
)
from vocatron.engines.protocols import Downloader, DownloadError, FileStore
from vocatron.stages.stage import LogLine


class DownloadListener(Protocol):
    """Hears how a download proceeds; the command line shows it, the runner logs it."""

    def licence(self, spec: ModelSpec) -> None:
        """A model is about to be downloaded; show its licence."""
        ...

    def file_started(self, spec: ModelSpec, file: ModelFile) -> None:
        """A file download starts (or resumes)."""
        ...

    def progress(self, done: int, total: int) -> None:
        """Bytes of the current file done so far."""
        ...

    def file_finished(self, spec: ModelSpec, file: ModelFile) -> None:
        """The current file is complete and verified."""
        ...


class ModelFolder:
    """The folder that holds the models, one subfolder per model."""

    def __init__(self, folder: Path, store: FileStore) -> None:
        """Look at ``folder`` through ``store``."""
        self.folder = folder
        self._store = store

    def path_of(self, spec: ModelSpec, file: ModelFile | None = None) -> Path:
        """Return the folder of ``spec``, or the path of one of its files."""
        base = self.folder / spec.name
        return base if file is None else base / file.path

    def file_state(self, spec: ModelSpec, file: ModelFile, *, verify: bool) -> State:
        """Judge one file; ``verify`` also computes its SHA-256 (slow for big files)."""
        path = self.path_of(spec, file)
        size = self._store.size(path)
        digest = self._store.sha256(path) if verify and size is not None else None
        has_part = self._store.size(part_path(path)) is not None
        return file_state(file, Observed(size=size, sha256=digest, has_part=has_part))

    def remove(self, path: Path) -> None:
        """Delete a file of the model folder."""
        self._store.delete(path)

    def state(self, spec: ModelSpec, *, verify: bool) -> State:
        """Judge a model; ``verify`` checks checksums, otherwise only sizes are compared."""
        return model_state([self.file_state(spec, f, verify=verify) for f in spec.files])


def fetch(
    specs: Iterable[ModelSpec],
    folder: ModelFolder,
    downloader: Downloader,
    listener: DownloadListener,
    *,
    verify: bool = True,
) -> list[ModelSpec]:
    """Download every file of ``specs`` that is not correct on disk.

    A file with a wrong size or checksum is deleted first; an interrupted download is resumed.

    Args:
        specs: The models to bring up to date.
        folder: The model folder.
        downloader: Fetches the files.
        listener: Told what happens.
        verify: Compare checksums of the files already there (slow for big files); otherwise
            only their sizes, which is enough right after a verified download.

    Returns:
        The models that needed a download.

    Raises:
        DownloadError: If a file cannot be fetched or fails its checksum.
    """
    fetched: list[ModelSpec] = []
    for spec in specs:
        todo = [f for f in spec.files if folder.file_state(spec, f, verify=verify) != "present"]
        if not todo:
            continue
        listener.licence(spec)
        for file in todo:
            destination = folder.path_of(spec, file)
            folder.remove(destination)  # a wrong file goes; the .part file of a cut stays
            listener.file_started(spec, file)
            downloader.download(file, destination, listener.progress)
            listener.file_finished(spec, file)
        fetched.append(spec)
    return fetched


class LogListener:
    """Writes the licence and the files of a download to the song log; no progress."""

    def __init__(self, log: LogLine) -> None:
        """Write to ``log``."""
        self._log = log

    def licence(self, spec: ModelSpec) -> None:
        """Log the licence notice of the model."""
        self._log(f"models: downloading {spec.name} ({spec.notice()})")

    def file_started(self, spec: ModelSpec, file: ModelFile) -> None:
        """Log the file."""
        self._log(f"models: {spec.name}/{file.path} ({human_size(file.size)}) from {file.url}")

    def progress(self, done: int, total: int) -> None:
        """Ignore progress; the log has one line per file."""
        del done, total

    def file_finished(self, spec: ModelSpec, file: ModelFile) -> None:
        """Log that the file is verified."""
        self._log(f"models: {spec.name}/{file.path} verified")


def ensure_models(
    names: Iterable[str],
    *,
    folder: ModelFolder,
    downloader: Downloader,
    offline: bool,
    listener: DownloadListener,
) -> None:
    """Make sure the models a stage declares are in the folder.

    Missing models are downloaded on first use, unless ``offline``.

    Args:
        names: The registry names the stage declares.
        folder: The model folder.
        downloader: Fetches missing files.
        offline: Never download; fail with the command to run instead.
        listener: Told what is downloaded.

    Raises:
        StageError: ``models-missing`` offline, ``model-download`` when a download fails.
        UnknownModelError: If a name is not in the registry (a bug in the stage).
    """
    specs = [find_model(name) for name in names]
    wanted = [spec for spec in specs if folder.state(spec, verify=False) != "present"]
    if not wanted:
        return
    if offline:
        listing = " ".join(spec.name for spec in wanted)
        raise StageError(
            "models-missing",
            f"models are missing or incomplete and --offline is set; run "
            f"'vocatron models download {listing}' first",
        )
    try:
        fetch(wanted, folder, downloader, listener, verify=False)
    except DownloadError as error:
        raise StageError("model-download", str(error)) from error
