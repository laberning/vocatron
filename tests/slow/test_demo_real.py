"""Stage 2: ``vocatron make`` end to end on the demo songs, one per language, against references.

The songs are those of ``tests/data/demo/demo.toml``: "Verdächtig" by Systemabsturz (CC0, German)
and "My Favorite Regret" by Josh Woodward feat. Katie Pederson (CC BY 4.0, English duet), downloaded
by ``make demo-songs`` into ``.corpus/demo/``; the lyrics file of each is in ``tests/data/demo/``,
copied next to the song and never opened here. The language is detected, not set. The test runs the
whole pipeline on the GPU, then compares the start of every word with
``golden/demo/<code>/words.json`` (median error at most 100 ms, no word more than 1 s off) and five
frames, drawn by libass at fixed seconds, with the golden PNGs next to it. The references are made
by ``make demo-accept`` (``VOCATRON_DEMO_ACCEPT=1``; ``LANGUAGE=de`` for the German song, default
English) and committed only after the video has been watched. Skipped with a reason without a GPU,
without the downloaded song, or while there are no references of that language. The tests report
numbers and verdicts only, never a line of the lyrics (AGENTS.md). GPU safety as in AGENTS.md: a
timeout, the 75 % cap and half precision inside the workers, and a log synced to disk after every
line."""

import os
import shutil
import time
from collections.abc import Iterator
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from rich.console import Console

import demo_songs
from conftest import corpus_dir
from demoreal import (
    Reference,
    demo_names,
    frame_moments,
    read_reference,
    start_errors,
    verdict,
    write_reference,
)
from realworld import chosen_language
from videoreal import SAME, contact_sheet, difference, frame_at
from vocatron.cli.app import clone_folder, real_engines
from vocatron.cli.commands import Edges, run_make
from vocatron.core.alignment.file import AlignmentFile
from vocatron.core.languages import LANGUAGES
from vocatron.core.layout.file import LayoutFile
from vocatron.core.presets import PRESETS
from vocatron.core.report import ReportFile
from vocatron.engines.files import FileLog
from vocatron.engines.system import LocalSystemProbe
from vocatron.stages.config import Config
from vocatron.stages.songs import discover

CLONE = clone_folder()
GOLDEN = Path(__file__).resolve().parent / "golden" / "demo"
REPORTS = CLONE / "reports"
ACCEPT = os.environ.get("VOCATRON_DEMO_ACCEPT") == "1"
ACCEPT_LANGUAGE = chosen_language("VOCATRON_DEMO_LANGUAGE") or "en"
TIMEOUT = 1800  # seconds for the whole run

pytestmark = [pytest.mark.gpu, pytest.mark.timeout(TIMEOUT)]


@dataclass(frozen=True)
class Made:
    """One run of ``make`` on the demo song."""

    code: int
    seconds: float
    folder: Path
    language: str

    @property
    def references(self) -> Path:
        """The folder of this language's references."""
        return GOLDEN / demo_names(self.language).references


SONGS = demo_songs.load_songs(demo_songs.SONG_LIST.read_text("utf-8"))


def song_of(language: str) -> demo_songs.DemoSong:
    """Return the entry of the demo song list in ``language``."""
    return next(song for song in SONGS if song.language == language)


@pytest.fixture(scope="module", params=[song.language for song in SONGS])
def language(request: pytest.FixtureRequest) -> str:
    """The language of the demo song a test runs for (each test runs once per song)."""
    return str(request.param)


@pytest.fixture(scope="module")
def log(language: str) -> Iterator[FileLog]:
    folder = CLONE / ".cache" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    sink = FileLog(folder / demo_names(language).log)
    yield sink
    sink.close()


@pytest.fixture(scope="module")
def made(language: str, log: FileLog) -> Made:
    """Make the song once in a fresh folder; skip when it is not downloaded or has no reference."""
    song = song_of(language)
    names = demo_names(language)
    audio = corpus_dir().resolve() / "demo" / song.file
    if ACCEPT and language != ACCEPT_LANGUAGE:
        pytest.skip(f"'make demo-accept' writes the references of {ACCEPT_LANGUAGE} only")
    if not audio.is_file():
        pytest.skip(f"the demo song is not downloaded: run 'make demo-songs' ({audio})")
    if not ACCEPT and not (GOLDEN / names.references / "words.json").is_file():
        pytest.skip(
            f"no references for {language} yet: run 'make demo-accept"
            f"{'' if language == 'de' else f' LANGUAGE={language}'}' and watch the video before "
            "committing them"
        )
    if demo_songs.sha256_of(audio) != song.sha256:
        pytest.fail("the downloaded demo song has the wrong checksum: run 'make demo-songs'")
    folder = audio.parent / names.make
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir()
    shutil.copy(audio, folder / audio.name)
    shutil.copy(demo_songs.SONG_LIST.parent / f"{song.stem}.txt", folder / f"{song.stem}.txt")
    console = Console(file=StringIO(), width=200, color_system=None)  # no summary in the test log
    edges = Edges(real_engines(), console, console, folder, LocalSystemProbe(), CLONE)
    started = time.monotonic()
    code = run_make(folder, output=None, config_file=None, edges=edges)
    seconds = time.monotonic() - started
    log.write(f"make: exit {code}, {seconds:.0f} s")
    return Made(code, seconds, folder, language)


def work_folder(run: Made) -> Path:
    """Return the work folder of the one song."""
    (song,) = discover(run.folder, Config(), real_engines())
    return song.work_dir


def test_the_song_is_made_and_the_word_starts_match_the_reference(made: Made, log: FileLog) -> None:
    assert made.code == 0, f"make failed; see the work folder under {made.folder}"
    work = work_folder(made)
    report = ReportFile.model_validate_json((work / "report.json").read_text("utf-8"))
    assert report.status in {"ok", "review"}
    alignment = AlignmentFile.model_validate_json((work / "alignment.json").read_text("utf-8"))
    # The language is detected, not set: the song must be aligned with its own language's model.
    assert alignment.language == made.language, f"detected as {alignment.language}"
    assert alignment.model == LANGUAGES[made.language].model
    starts = [word.start for word in alignment.words]
    log.write(f"status {report.status}, {len(starts)} words, {len(report.reasons)} reasons")
    if ACCEPT:
        scene = LayoutFile.model_validate_json((work / "layout.json").read_text("utf-8")).scene
        write_reference(made.references / "words.json", Reference(starts, frame_moments(scene)))
        return
    reference = read_reference(made.references / "words.json")
    errors = start_errors(starts, reference.starts)
    log.write(f"word starts: median {errors.median * 1000:.0f} ms, worst {errors.worst:.2f} s")
    assert verdict(errors) is None, verdict(errors)


def test_five_frames_match_the_golden_frames(made: Made, tmp_path: Path, log: FileLog) -> None:
    work = work_folder(made)
    scene = LayoutFile.model_validate_json((work / "layout.json").read_text("utf-8")).scene
    moments = (
        frame_moments(scene) if ACCEPT else read_reference(made.references / "words.json").frames
    )
    assert len(moments) == 5
    preset = PRESETS[Config().preset]
    frames: list[Image.Image] = []
    for name, seconds in moments.items():
        frame = frame_at(work / "lyrics.ass", scene, seconds, tmp_path / "frame.png", preset)
        golden = made.references / f"{name}.png"
        if ACCEPT:
            made.references.mkdir(parents=True, exist_ok=True)
            Image.fromarray(frame).save(golden, optimize=True)
        else:
            share = difference(frame, np.asarray(Image.open(golden).convert("RGB")))
            log.write(f"frame {name}: {share:.4%} of the pixels differ")
            assert share <= SAME, f"{name}: {share:.4%} of the pixels differ from the golden frame"
        frames.append(Image.fromarray(frame))
    REPORTS.mkdir(exist_ok=True)
    contact_sheet(frames).save(REPORTS / demo_names(made.language).sheet, optimize=True)
