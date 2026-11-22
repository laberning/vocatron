"""Engine protocols, the only part of ``engines`` that ``stages`` may import (ADR-0007).

Every protocol has a fake in ``tests/fakes`` so the whole pipeline runs without files, models or
a real clock in the fast tests.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from vocatron.core.alignment.chunks import Emissions
from vocatron.core.alignment.job import AcousticResult, AcousticSetup
from vocatron.core.languages import Detected
from vocatron.core.lyrics.versions import Candidate
from vocatron.core.models import ModelFile
from vocatron.core.presets import AudioSettings, Preset
from vocatron.core.scene import BackgroundMotion
from vocatron.core.separation.job import SeparationPlan, SeparationResult
from vocatron.core.separation.rules import Audio, DeviceRequest
from vocatron.core.song import MediaTags, Tags
from vocatron.core.system import TorchInfo

AUDIO_SUFFIXES = (".mp3", ".flac", ".wav", ".ogg", ".opus", ".m4a")


Progress = Callable[[int, int], None]
"""Called with the bytes downloaded so far and the total size of the file."""


class TagReadError(Exception):
    """An audio file could not be read for its tags."""


class DownloadError(Exception):
    """A download failed for good: no connection, an unexpected answer, or a wrong checksum."""


class LyricsLookupError(Exception):
    """The lyrics source could not be asked or gave an answer that cannot be right."""


def _ignore_progress(fraction: float) -> None:
    """Take no notice of the progress."""
    del fraction


def _no_limit() -> float | None:
    """Say that the song has no time limit."""
    return None


@dataclass(frozen=True)
class Watch:
    """What a long-running engine tells its caller and obeys while it works.

    Attributes:
        progress: Called with how far the work is (0 to 1), possibly from another thread.
        time_left: Returns the seconds left of the safety limit of the song, or ``None`` when it
            has none; an engine never runs longer than that.
    """

    progress: Callable[[float], None] = _ignore_progress
    time_left: Callable[[], float | None] = _no_limit


@dataclass(frozen=True)
class WorkerRequest:
    """What every GPU worker job needs.

    Attributes:
        audio: The audio file to work on.
        work_dir: The work folder; the worker's job and result files lie there while it runs.
        log_path: The song log; the worker may append to it.
        log: Writes a line to the song log.
        duration: The length of the song in seconds, or ``None`` when unknown.
        device: The device setting.
        timeout_factor_gpu: The GPU timeout in song lengths (plus two minutes).
        timeout_factor_cpu: The CPU timeout in song lengths (plus two minutes).
        watch: Progress and the time left of the song.
    """

    audio: Path
    work_dir: Path
    log_path: Path
    log: Callable[[str], None]
    duration: float | None
    device: DeviceRequest
    timeout_factor_gpu: float
    timeout_factor_cpu: float
    watch: Watch = field(default_factory=Watch, kw_only=True)


@dataclass(frozen=True)
class SeparationRequest(WorkerRequest):
    """Everything a separator needs for one song: the song and these.

    Attributes:
        plan: The models and how their outputs are combined.
    """

    plan: SeparationPlan


@dataclass(frozen=True)
class AcousticRequest(WorkerRequest):
    """Everything the acoustic model needs for one song (``audio``: the lead vocals).

    Attributes:
        backing: The backing vocals, or ``None`` when neither switch below needs them.
        sum_backing: With ``backing`` given, add it to the lead vocals for the loudness
            (``alignment.voice_source: vocals``) instead of measuring the lead alone.
        hear_backing: Also run the model on ``backing`` and return its output and the loudness of
            each stem alone (``alignment.hear_backing``, ADR-0014).
        model: The acoustic model.
        piece_seconds: The length of the pieces the model sees.
        overlap_seconds: How much consecutive pieces share.
    """

    model: AcousticSetup
    piece_seconds: float
    overlap_seconds: float
    backing: Path | None = None
    sum_backing: bool = True
    hear_backing: bool = False


@dataclass(frozen=True)
class Heard:
    """What the acoustic model made of a song.

    Attributes:
        emissions: The log-probabilities per frame.
        result: How the model ran (device, time, memory, warnings).
    """

    emissions: Emissions
    result: AcousticResult


@dataclass(frozen=True)
class RenderRequest:
    """Everything the renderer needs for one song.

    Attributes:
        ass: The subtitle file with the lyrics.
        audio: The lossless karaoke audio (``stems/karaoke.flac``).
        work_dir: The work folder, where the encoded audio is kept.
        output_dir: The output folder, where the finished files go.
        name: The ``Artist - Title`` name of the files.
        preset: The output preset (frame size, codec, quality).
        audio_settings: The audio encoder, bitrate and export.
        background: The plain background colour as ``#rrggbb``.
        duration: The length of the video in seconds (the song and the lead), or ``None`` when
            unknown.
        log: Writes a line to the song log.
        watch: Progress and the time left of the song.
        lead: The silence in seconds put before the karaoke audio in the video, the M4A and the
            FLAC export (the silent intro, ADR-0020); the subtitles already include it.
        tags: The tags of the MP4 (``media_tags``, ADR-0031, ADR-0047).
        motion: A moving gradient drawn instead of the plain background (ADR-0032), or ``None``.
    """

    ass: Path
    audio: Path
    work_dir: Path
    output_dir: Path
    name: str
    preset: Preset
    audio_settings: AudioSettings
    background: str
    duration: float | None
    log: Callable[[str], None]
    watch: Watch = field(default_factory=Watch)
    lead: float = 0.0
    tags: MediaTags = ()
    motion: BackgroundMotion | None = None


@dataclass(frozen=True)
class RenderResult:
    """What the renderer made.

    Attributes:
        files: The names of the files it wrote in the output folder (MP4 first).
        seconds: How long it took.
        audio_encoder: The encoder that made the audio (``fdkaac`` or ``ffmpeg-aac``).
        fonts: The faces libass drew with (all of them the bundled font).
    """

    files: tuple[str, ...]
    seconds: float
    audio_encoder: str
    fonts: tuple[str, ...]


@dataclass(frozen=True)
class Mp3Request:
    """Everything the MP3 encoder needs for one song (ADR-0024).

    Attributes:
        source: The lossless karaoke audio (``stems/karaoke.flac``).
        target: The MP3 file to write.
        lead: The silence in seconds put before the audio (the silent intro, ADR-0020).
        duration: The length of the MP3 in seconds (the song and the lead), or ``None`` when
            unknown.
        log: Writes a line to the song log.
        watch: Progress and the time left of the song.
        tags: The ID3 tags of the MP3 (``media_tags``, ADR-0031, ADR-0047).
    """

    source: Path
    target: Path
    lead: float
    duration: float | None
    log: Callable[[str], None]
    watch: Watch = field(default_factory=Watch)
    tags: MediaTags = ()


@dataclass(frozen=True)
class PackMember:
    """One file of a zip.

    Attributes:
        name: The name of the member in the zip.
        content: The path of the file to read, or the bytes themselves.
    """

    name: str
    content: Path | bytes


@dataclass(frozen=True)
class PackRequest:
    """A zip to write (ADR-0030).

    Attributes:
        target: The zip file to write.
        members: The files in the zip, in this order.
        time: The time stamp of every member (year, month, day, hour, minute, second), fixed so
            that the same members give the same bytes.
    """

    target: Path
    members: tuple[PackMember, ...]
    time: tuple[int, int, int, int, int, int]


class Clock(Protocol):
    """The source of the current time; injected so that tests are deterministic."""

    def now(self) -> datetime:
        """Return the current time, with a time zone."""
        ...

    def monotonic(self) -> float:
        """Return seconds on a clock that only moves forward, for measuring how long things take."""
        ...


class TagReader(Protocol):
    """Reads artist, title and duration of an audio file."""

    def read(self, path: Path) -> Tags:
        """Read the tags of ``path``.

        Raises:
            TagReadError: If the file is not a readable audio file.
        """
        ...


class LogSink(Protocol):
    """A per-song log that survives a crash: every line is on disk when ``write`` returns."""

    def write(self, line: str) -> None:
        """Append one line, flushed and synced to disk."""
        ...

    def close(self) -> None:
        """Close the log."""
        ...


class FileStore(Protocol):
    """Everything the pipeline does with files."""

    def kind(self, path: Path) -> Literal["file", "folder"] | None:
        """Say whether ``path`` is a file, a folder, or does not exist."""
        ...

    def list_audio(self, folder: Path) -> list[Path]:
        """List the audio files directly in ``folder`` (no subfolders), sorted by name."""
        ...

    def list_files(self, folder: Path, suffixes: tuple[str, ...]) -> list[Path]:
        """List the files directly in ``folder`` that end in one of ``suffixes``, sorted by name.

        A folder that does not exist has no files.
        """
        ...

    def read_text(self, path: Path) -> str | None:
        """Return the UTF-8 text of a file, or ``None`` when it does not exist.

        Raises:
            UnicodeDecodeError: If the file is not UTF-8.
            OSError: If the file exists but cannot be read (a folder, no permission).
        """
        ...

    def write_text(self, path: Path, text: str) -> None:
        """Write a text file atomically, creating missing folders."""
        ...

    def write_bytes(self, path: Path, data: bytes) -> None:
        """Write a binary file atomically, creating missing folders."""
        ...

    def sha256(self, path: Path) -> str | None:
        """Return the SHA-256 of a file's content, or ``None`` when it does not exist."""
        ...

    def size(self, path: Path) -> int | None:
        """Return the size of a file in bytes, or ``None`` when it does not exist."""
        ...

    def delete(self, path: Path) -> None:
        """Delete a file; nothing happens when it does not exist."""
        ...

    def writable(self, folder: Path) -> bool:
        """Tell whether ``folder`` can be created and written (or already can be written)."""
        ...

    def make_folder(self, path: Path) -> None:
        """Create a folder and its parents if missing."""
        ...

    def open_log(self, path: Path, follow: Callable[[str], None] | None = None) -> LogSink:
        """Open a log file for appending.

        Args:
            path: The log file.
            follow: Gets every line appended to the file while the log is open, by this log or
                by another process (a GPU worker writes to the song log itself): each line once,
                in the order of the file, the last ones at the latest when ``close`` returns.
                The lines that were in the file before are not handed on.
        """
        ...


class Downloader(Protocol):
    """Fetches one model file: resumable, checked, and never into a system temporary folder."""

    def download(self, file: ModelFile, destination: Path, progress: Progress) -> None:
        """Download ``file`` to ``destination``.

        The data goes to ``<destination>.part`` first, which a later call resumes. On success the
        checksum is verified and the part file is renamed to ``destination``; on a mismatch it is
        deleted.

        Raises:
            DownloadError: If the file cannot be fetched or has the wrong checksum.
        """
        ...


class SystemProbe(Protocol):
    """Reads facts about the machine for ``doctor``; returns ``None`` for what is not there."""

    def ffmpeg_version(self) -> str | None:
        """Return the output of ``ffmpeg -version``, or ``None`` if ffmpeg cannot be run."""
        ...

    def ffmpeg_encoders(self) -> str | None:
        """Return the output of ``ffmpeg -encoders``, or ``None`` if it cannot be run."""
        ...

    def torch_info(self) -> TorchInfo | None:
        """Return what PyTorch reports, or ``None`` when PyTorch is not installed."""
        ...

    def fdkaac_version(self) -> str | None:
        """Return the first line of ``fdkaac --help`` (its version), or ``None`` if missing."""
        ...


class LyricsSource(Protocol):
    """Finds lyrics records for a song (LRCLIB), for the fan's own files (ADR-0002)."""

    def find(self, artist: str | None, title: str, duration: float | None) -> list[Candidate]:
        """Return the records that may be the lyrics of the song, best guess first.

        The records are not yet checked against artist and title.

        Raises:
            LyricsLookupError: If the source cannot be reached or answers wrongly.
        """
        ...


class LanguageDetector(Protocol):
    """Detects the language of a text (lingua)."""

    def detect(self, text: str) -> Detected | None:
        """Return the language of ``text``, or ``None`` when it cannot be told."""
        ...


class Separator(Protocol):
    """Separates a song into lead vocals, backing vocals, instrumental and the karaoke mix."""

    def separate(self, request: SeparationRequest) -> SeparationResult:
        """Write the four stems to ``<work_dir>/stems`` and describe what was done.

        Raises:
            StageError: If the separation fails, times out, runs out of memory, or the device
                that was asked for is not usable; the message says what to do.
        """
        ...


class AudioReader(Protocol):
    """Decodes an audio file of the work folder (a stem) to samples."""

    def read(self, path: Path, sample_rate: int, channels: int) -> Audio:
        """Return the audio of ``path`` as float32 samples shaped (channels, samples).

        Args:
            path: The audio file.
            sample_rate: The rate to resample to.
            channels: The number of channels to mix to.

        Raises:
            StageError: ``decode-failed`` if the file cannot be decoded.
        """
        ...


class AcousticModel(Protocol):
    """Turns singing into per-frame log-probabilities of the letters of the language (wav2vec2)."""

    def log_probs(self, request: AcousticRequest) -> Heard:
        """Run the model over the whole song.

        Raises:
            StageError: If the model fails, times out, runs out of memory, or the device that was
                asked for is not usable; the message says what to do.
        """
        ...


class Renderer(Protocol):
    """Draws a scene's subtitle file and the karaoke audio into an MP4 (and the audio export)."""

    def render(self, request: RenderRequest) -> RenderResult:
        """Encode the audio once, burn the lyrics onto the background and write the files.

        Raises:
            StageError: If a program is missing, fails or times out, or libass drew with a font
                other than the bundled one.
        """
        ...


class Mp3Encoder(Protocol):
    """Encodes the karaoke audio to the MP3 of a CD+G pair."""

    def encode_mp3(self, request: Mp3Request) -> None:
        """Write the MP3 with the silent intro in front of the audio.

        Raises:
            StageError: If a program is missing (or has no MP3 encoder), fails or times out.
        """
        ...


class Packer(Protocol):
    """Packs files into a zip (ADR-0030)."""

    def pack(self, request: PackRequest) -> None:
        """Write the zip with the members in the given order and the given time stamp.

        The same members give the same bytes. The target appears whole or not at all.

        Raises:
            OSError: If a member cannot be read or the zip cannot be written.
        """
        ...


class Resources(Protocol):
    """What ships inside the package."""

    def builtin_profile(self, name: str) -> str | None:
        """Return the YAML text of the built-in profile ``name``, or ``None`` if there is none."""
        ...

    def fonts_dir(self) -> Path:
        """Return the folder with the bundled font."""
        ...

    def drawable_characters(self) -> frozenset[int]:
        """Return the code points the bundled font can draw (ADR-0046)."""
        ...
