"""Builders for tiny songs and complete fake worlds."""

import wave
from dataclasses import replace
from pathlib import Path

from fakes.acoustic import FakeAcousticModel
from fakes.audio import FakeAudioReader
from fakes.clock import FakeClock
from fakes.files import InMemoryFileStore
from fakes.lyrics import ENTCHEN, FakeLanguageDetector, FakeLyricsSource
from fakes.measure import FixedMeasurer
from fakes.models import FakeDownloader
from fakes.pack import FakePacker
from fakes.raster import FakeRasteriser
from fakes.render import FakeMp3Encoder, FakeRenderer
from fakes.resources import FakeResources
from fakes.separation import FakeSeparator
from fakes.system import FakeSystemProbe
from fakes.tags import FakeTagReader
from vocatron.core.models import MODELS
from vocatron.core.song import Tags
from vocatron.core.status import SongStatus
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser
from vocatron.stages.batch import run_song
from vocatron.stages.config import Config
from vocatron.stages.songs import discover
from vocatron.stages.stage import Engines, Song, StageContext

DEFAULT_TAGS = Tags("Artist", "Title", 180.0)
FOLK_LYRICS = ENTCHEN  # the lyrics file next to a song unless a test says otherwise


class FakeWorld:
    """Engines made of fakes plus a helper to put songs in a folder."""

    def __init__(self) -> None:
        self.clock = FakeClock()
        self.tags = FakeTagReader()
        self.store = InMemoryFileStore()
        self.downloader = FakeDownloader(self.store)
        self.probe = FakeSystemProbe()
        self.lyrics = FakeLyricsSource()
        self.language = FakeLanguageDetector()
        self.separator = FakeSeparator(self.store)
        self.acoustic = FakeAcousticModel(self.store)
        self.measurer = FixedMeasurer()
        self.rasteriser = FakeRasteriser()
        self.renderer = FakeRenderer(self.store)
        self.mp3 = FakeMp3Encoder(self.store)
        self.packer = FakePacker(self.store)
        self.resources = FakeResources()
        self.audio = FakeAudioReader()
        # The models are big; the fakes hand out placeholders for every one of them.
        self.downloader.phantoms = {f.url for spec in MODELS for f in spec.files}
        self.engines = Engines(
            clock=self.clock,
            tags=self.tags,
            store=self.store,
            downloader=self.downloader,
            lyrics=self.lyrics,
            language=self.language,
            separator=self.separator,
            acoustic=self.acoustic,
            measurer=self.measurer,
            rasteriser=self.rasteriser,
            renderer=self.renderer,
            mp3=self.mp3,
            packer=self.packer,
            resources=self.resources,
            audio=self.audio,
        )

    def use_real_font(self) -> None:
        """Measure and draw text with the bundled font, for tests of the CD+G check, whose
        timing depends on the shapes of the letters."""
        font = self.resources.font_file()
        self.engines = replace(
            self.engines, measurer=PillowMeasurer(font), rasteriser=PillowRasteriser(font)
        )

    def song(self, path: Path, config: Config | None = None) -> Song:
        """Return the one song at ``path`` as the stages see it."""
        (found,) = discover(path, config or Config(), self.engines)
        return found

    def context(self, path: Path, config: Config | None = None) -> StageContext:
        """Return the context of the one song at ``path`` (a silent log, the default models)."""
        return StageContext(
            self.song(path, config), self.engines, lambda message: None, Path("models")
        )

    def run(self, path: Path, config: Config | None = None, *, force: bool = False) -> SongStatus:
        """Run the song at ``path`` through all the stages and return its status."""
        cfg = config or Config()
        return run_song(self.song(path, cfg), cfg, self.engines, force=force)

    def add_song(
        self,
        path: Path,
        tags: Tags | None = DEFAULT_TAGS,
        data: bytes | None = None,
        lyrics: str | None = FOLK_LYRICS,
    ) -> Path:
        """Add an audio file with canned tags (``None``: unreadable) and return its path.

        ``lyrics`` is put next to it as ``<name>.txt`` (``None``: no lyrics file).
        """
        self.store.add(path, path.name.encode() if data is None else data)
        self.tags.tags[path] = tags
        if lyrics is not None:
            self.store.add(path.with_suffix(".txt"), lyrics.encode("utf-8"))
        return path


def write_wav(
    path: Path, seconds: float = 1.5, rate: int = 8000, lyrics: str | None = FOLK_LYRICS
) -> Path:
    """Write a silent mono WAV file of ``seconds`` seconds (real files for the real engines).

    ``lyrics`` is written next to it as ``<name>.txt`` (``None``: no lyrics file).
    """
    if lyrics is not None:
        path.with_suffix(".txt").write_text(lyrics, encoding="utf-8")
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(b"\x00\x00" * int(seconds * rate))
    return path


def stored_status(world: FakeWorld, path: Path) -> SongStatus | None:
    """Return the stored ``status.json`` of the one song at ``path``, or ``None``."""
    song = world.song(path)
    text = world.store.read_text(song.work_dir / "status.json")
    return None if text is None else SongStatus.model_validate_json(text)
