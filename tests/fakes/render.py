"""A renderer that writes small canned files into the in-memory store and records its requests."""

from collections.abc import Callable
from pathlib import Path

from fakes.files import InMemoryFileStore
from vocatron.core.errors import StageError
from vocatron.core.font_check import BUNDLED_FACE
from vocatron.core.id3 import id3_tag
from vocatron.engines.protocols import Mp3Request, RenderRequest, RenderResult


class FakeRenderer:
    """Writes ``<name>.mp4`` and the audio export; never starts a program."""

    def __init__(self, store: InMemoryFileStore) -> None:
        self.store = store
        self.requests: list[RenderRequest] = []
        self.fail_with: StageError | None = None
        self.during: Callable[[RenderRequest], None] | None = None  # runs while "working"

    def render(self, request: RenderRequest) -> RenderResult:
        self.requests.append(request)
        request.watch.progress(0.5)
        if self.during is not None:
            self.during(request)
        request.watch.progress(1.0)
        if self.fail_with is not None:
            raise self.fail_with
        ass = self.store.read_text(request.ass) or ""
        files = [f"{request.name}.mp4"]
        self.store.add(request.output_dir / files[0], f"video {request.preset.name} {ass}".encode())
        export = request.audio_settings.export
        if export != "none":
            files.append(f"{request.name}.{export}")
            self.store.add(request.output_dir / files[1], f"audio {export}".encode())
        return RenderResult(
            files=tuple(files),
            seconds=0.1,
            audio_encoder=request.audio_settings.encoder,
            fonts=(BUNDLED_FACE,),
        )


FAKE_FONTS_DIR = Path("/package/fonts")


class FakeMp3Encoder:
    """Writes a small canned MP3 into the in-memory store and records its requests."""

    def __init__(self, store: InMemoryFileStore) -> None:
        self.store = store
        self.requests: list[Mp3Request] = []
        self.fail_with: StageError | None = None
        self.during: Callable[[Mp3Request], None] | None = None  # runs while "working"

    def encode_mp3(self, request: Mp3Request) -> None:
        self.requests.append(request)
        if self.during is not None:
            self.during(request)
        request.watch.progress(1.0)
        if self.fail_with is not None:
            raise self.fail_with
        self.store.add(request.target, id3_tag(request.tags) + f"mp3 lead {request.lead}".encode())
