"""A separator that writes tiny canned stems into the in-memory store, and a fake worker."""

from collections.abc import Callable
from pathlib import Path

from fakes.files import InMemoryFileStore
from vocatron.core.errors import StageError
from vocatron.core.separation.file import STEM_NAMES, stem_path
from vocatron.core.separation.job import SeparationResult, StemGains
from vocatron.core.separation.rules import SAMPLE_RATE
from vocatron.engines.protocols import SeparationRequest

FAKE_SECONDS = 2


class FakeSeparator:
    """Writes ``stems/<name>.flac`` as small byte strings and records what it was asked."""

    def __init__(self, store: InMemoryFileStore) -> None:
        self.store = store
        self.during: Callable[[SeparationRequest], None] | None = None  # runs while "working"
        self.requests: list[SeparationRequest] = []
        self.fail_with: StageError | None = None  # fails every song
        self.fail_for: dict[Path, StageError] = {}  # fails the songs with these audio files
        self.skip: set[str] = set()  # stems it forgets to write
        self.warnings: list[str] = []
        self.gains = StemGains()

    def separate(self, request: SeparationRequest) -> SeparationResult:
        self.requests.append(request)
        request.watch.progress(0.5)
        if self.during is not None:
            self.during(request)
        request.watch.progress(1.0)
        if self.fail_with is not None:
            raise self.fail_with
        if request.audio in self.fail_for:
            raise self.fail_for[request.audio]
        for name in STEM_NAMES:
            if name in self.skip:
                continue
            body = f"{name} backing={request.plan.keep_backing}".encode()
            self.store.add(request.work_dir / Path(stem_path(name)), body)
        return SeparationResult(
            samples=FAKE_SECONDS * SAMPLE_RATE,
            gains=self.gains,
            device="cpu",
            seconds=0.5,
            warnings=self.warnings,
        )
