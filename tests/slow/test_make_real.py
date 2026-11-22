"""Stage 2: ``vocatron make`` on two real corpus songs, end to end with the real engines.

Two short songs of ``.corpus/songs`` (in any audio format, with the lyrics files next to them)
are copied into a fresh ``.corpus/make-real/songs`` and made on the GPU: separation, alignment
and the video with the real tools; a missing corpus file fails the test
(``realworld.corpus_path``). A second run must skip everything. The tests report counts, sizes,
times and verdicts only, never a line of the lyrics (AGENTS.md): no assertion message here
contains the text of the summary, whose last column may name reasons. GPU safety as in
AGENTS.md: a timeout on every test, the 75 % cap and half precision inside the workers, and a
log synced to disk after every line.
"""

import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from conftest import corpus_dir
from realworld import corpus_path, corpus_song
from vocatron.cli.app import clone_folder, real_engines
from vocatron.cli.commands import Edges, run_make, run_status
from vocatron.core.layout.file import LayoutFile
from vocatron.core.report import ReportFile
from vocatron.engines.files import FileLog
from vocatron.engines.system import LocalSystemProbe
from vocatron.stages.config import Config
from vocatron.stages.songs import discover

CLONE = clone_folder()
SONGS = ("Wir sind Helden - Denkmal", "Udo Lindenberg & Apache 207 - Komet")
FOLDER = corpus_dir().resolve() / "make-real" / "songs"
OUTPUT = FOLDER / "karaoke"
TIMEOUT = 3000  # seconds for the whole first run: two songs, about five minutes each
LENGTH_TOLERANCE = 1.5  # seconds between the song and its video

pytestmark = [pytest.mark.gpu, pytest.mark.timeout(TIMEOUT)]


@dataclass(frozen=True)
class Made:
    """One run of ``make``: the exit code, the text it printed and how long it took."""

    code: int
    out: str
    seconds: float


def edges(out: StringIO) -> Edges:
    """The real engines, with the consoles in ``out`` so that no summary reaches the test log."""
    console = Console(file=out, width=200, color_system=None)
    return Edges(real_engines(), console, console, FOLDER, LocalSystemProbe(), CLONE)


def make() -> Made:
    out = StringIO()
    started = time.monotonic()
    code = run_make(FOLDER, output=None, config_file=None, edges=edges(out))
    return Made(code, out.getvalue(), time.monotonic() - started)


@pytest.fixture(scope="module")
def log() -> Iterator[FileLog]:
    folder = CLONE / ".cache" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    sink = FileLog(folder / "stage2-make.log")
    yield sink
    sink.close()


@pytest.fixture(scope="module")
def first(log: FileLog) -> Made:
    """The first run on a fresh output folder: everything is made."""
    sources = [(corpus_song(name), corpus_path("songs", f"{name}.lrc")) for name in SONGS]
    shutil.rmtree(FOLDER, ignore_errors=True)  # no copy of an earlier format may stay behind
    FOLDER.mkdir(parents=True)
    for audio, lyrics in sources:
        shutil.copy(audio, FOLDER / audio.name)
        shutil.copy(lyrics, FOLDER / lyrics.name)
    made = make()
    log.write(f"first run: exit {made.code}, {made.seconds:.0f} s")
    return made


def names_of_tracks() -> list[str]:
    """Return the names of the tracks and work folders (the tags decide, not the file names)."""
    return [song.name for song in discover(FOLDER, Config(), real_engines())]


def report_of(name: str) -> ReportFile:
    return ReportFile.model_validate_json((OUTPUT / name / "report.json").read_text("utf-8"))


def lead_of(name: str) -> float:
    """Return the silence the layout put before the song (the intro, ADR-0020)."""
    layout = LayoutFile.model_validate_json((OUTPUT / name / "layout.json").read_text("utf-8"))
    return layout.scene.lead


def video_seconds(path: Path) -> float:
    """Return the length of a video in seconds, from ffprobe."""
    done = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return float(done.stdout.strip())


def test_two_songs_go_from_audio_to_video_with_a_report_each(first: Made, log: FileLog) -> None:
    assert first.code == 0, "a song failed; see the work folders under .corpus/make-real"
    assert len(names_of_tracks()) == len(SONGS)
    for name in names_of_tracks():
        report = report_of(name)
        log.write(
            f"{len(name)}-character name: {report.status}, {len(report.reasons)} reasons, "
            f"{report.seconds:.0f} s, stages {sorted(report.stage_seconds)}"
        )
        assert report.status in {"ok", "review"}
        assert report.duration is not None
        assert report.quality is not None
        assert report.quality.words > 0
        assert set(report.stage_seconds) >= {"separation", "alignment", "render"}
        video = OUTPUT / f"{name}.mp4"
        assert video.stat().st_size > 100_000
        assert abs(video_seconds(video) - report.duration - lead_of(name)) < LENGTH_TOLERANCE
        assert (OUTPUT / f"{name}.lrc").is_file()
        assert report.outputs[0] == video.name


def test_the_summary_has_one_line_per_song_and_a_total(first: Made) -> None:
    lines = [line for line in first.out.splitlines() if line.startswith(("ok ", "review "))]
    assert len(lines) == len(SONGS)
    assert first.out.count(" songs: ") == 1
    assert (OUTPUT / "vocatron-report.txt").is_file()


def test_the_progress_and_the_learnt_speeds_were_kept(first: Made, log: FileLog) -> None:
    timings = CLONE / ".cache" / "timings.json"
    assert timings.is_file()
    text = timings.read_text("utf-8")
    assert "separation:cuda" in text
    assert "render:" in text
    for name in names_of_tracks():
        assert not (OUTPUT / name / "progress.json").exists()
    log.write(f"timings file: {len(text)} characters")


def test_a_second_run_skips_everything_and_status_shows_the_same_lines(
    first: Made, log: FileLog
) -> None:
    before = {name: report_of(name).stage_seconds for name in names_of_tracks()}
    again = make()
    log.write(f"second run: exit {again.code}, {again.seconds:.1f} s")
    assert again.code == 0
    assert again.seconds < 120
    assert {name: report_of(name).stage_seconds for name in names_of_tracks()} == before
    out = StringIO()
    assert run_status(FOLDER, output=None, config_file=None, edges=edges(out)) == 0
    shown = [line for line in out.getvalue().splitlines() if line.startswith(("ok ", "review "))]
    assert len(shown) == len(SONGS)
