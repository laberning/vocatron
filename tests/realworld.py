"""Real engines and corpus helpers for the stage 2 and 3 tests.

The tests report numbers only: never a line of the lyrics (AGENTS.md).
"""

import math
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from conftest import corpus_dir
from vocatron.cli.app import real_engines
from vocatron.core.alignment.file import AlignmentFile
from vocatron.core.languages import LANGUAGES
from vocatron.core.lyrics.file import LyricsFile
from vocatron.core.stage_file import make_fingerprint
from vocatron.engines.files import LocalFileStore
from vocatron.engines.protocols import AUDIO_SUFFIXES
from vocatron.stages.alignment import AlignmentStage
from vocatron.stages.config import Config
from vocatron.stages.models import ModelFolder
from vocatron.stages.stage import Song, StageContext

CLONE = Path(__file__).resolve().parents[1]
CORPUS_PAGE = "docs/dev/corpus.md"
MODELS = ModelFolder(CLONE / ".cache" / "models", LocalFileStore())


def corpus_path(*parts: str) -> Path:
    """Return a file or folder of the local corpus that a test needs, as an absolute path.

    Call it inside a test or fixture. Without any corpus, or without the corpus folder that
    ``parts`` start with, the test is skipped with a message that names the folder and
    ``docs/dev/corpus.md``, which lists what each folder must hold. When that folder is there but
    a file or folder below it is missing, the test fails and names it, so a renamed or converted
    file never turns into a silent skip.
    """
    root = corpus_dir()
    if not root.is_dir():
        pytest.skip(f"needs the local corpus {root}; see {CORPUS_PAGE}")
    if parts and not (root / parts[0]).exists():
        pytest.skip(f"the corpus {root} has no folder {parts[0]}; see {CORPUS_PAGE}")
    path = root.joinpath(*parts)
    if not path.exists():
        pytest.fail(f"the corpus {root} has no {Path(*parts)}; see {CORPUS_PAGE}", pytrace=False)
    return path.resolve()


def corpus_song(name: str, folder: str = "songs") -> Path:
    """Return the song ``name`` (file name without suffix) in a corpus folder, in any audio format.

    ``folder`` is ``songs`` (the current versions) or ``mp3`` (the earlier MP3 versions, for tests
    whose references were made from them). Skips and fails like ``corpus_path``: a missing folder
    skips, a missing song fails, and so do two formats of the same song, since it is unclear
    which one is meant.
    """
    found = sorted(
        path
        for path in corpus_path(folder).iterdir()
        if path.stem == name and path.suffix.lower() in AUDIO_SUFFIXES
    )
    if len(found) != 1:
        what = "no audio file" if not found else f"{len(found)} audio files"
        pytest.fail(
            f"the corpus folder {folder} has {what} named {name}; see {CORPUS_PAGE}", pytrace=False
        )
    return found[0]


def chosen_language(variable: str) -> str | None:
    """Return the language asked for in the environment variable ``variable``, or ``None``.

    ``make bench LANGUAGE=<code>`` and ``make demo-accept LANGUAGE=<code>`` pass the code this
    way. An unsupported code (a typo such as ``EN``) is an error, so it never turns into a run in
    which every language is skipped and the gate passes.

    Raises:
        pytest.UsageError: If the code is not a registered language.
    """
    code = os.environ.get(variable) or None
    if code is not None and code not in LANGUAGES:
        supported = ", ".join(LANGUAGES)
        raise pytest.UsageError(
            f"{variable}={code} is no supported language; supported: {supported}"
        )
    return code


def real_config(
    output: Path,
    *,
    use_lrc_times: bool,
    model: str | None = None,
    voice_source: str | None = None,
    hear_backing: bool | None = None,
) -> Config:
    """Return a configuration with the work folders in ``output`` and the models of the clone.

    ``model`` overrides ``separation.model`` and ``voice_source`` ``alignment.voice_source``;
    ``hear_backing`` sets ``alignment.hear_backing``; ``None`` keeps the default.
    """
    alignment: dict[str, object] = {"use_lrc_times": use_lrc_times}
    if voice_source is not None:
        alignment["voice_source"] = voice_source
    if hear_backing is not None:
        alignment["hear_backing"] = hear_backing
    separation: dict[str, str] = {} if model is None else {"model": model}
    return Config.model_validate(
        {
            "output": {"folder": str(output.resolve())},
            "models": {"folder": str(MODELS.folder)},
            "alignment": alignment,
            "separation": separation,
        }
    )


def tempo_ratio(first: float, second: float) -> float:
    """Return how far two tempos are from each other, ignoring doubling and halving.

    The tempos are brought to the same octave first: 100 and 201 BPM are 1 % apart.

    Returns:
        The relative difference, 0 for the same tempo.
    """
    octaves = round(math.log2(first / second))
    return abs(first / (second * 2**octaves) - 1)


def lyrics_of(song: Song) -> LyricsFile:
    """Read the ``lyrics.json`` of a song's work folder."""
    return LyricsFile.model_validate_json((song.work_dir / "lyrics.json").read_text("utf-8"))


def align(song: Song, config: Config) -> AlignmentFile:
    """Run the alignment stage on the song's stems with real engines; the model runs in a child."""
    engines = real_engines()
    stage = AlignmentStage()
    context = StageContext(song, engines, lambda message: None, MODELS.folder)
    fingerprint = make_fingerprint({}, stage.declared_settings(context, config), stage.version)
    file = stage.execute(context, config, fingerprint)
    assert isinstance(file, AlignmentFile)
    return file


@dataclass(frozen=True)
class LineStarts:
    """Where the lines of a song start, found and by the human reference."""

    found: list[float | None]
    reference: list[float | None]


def line_starts(song: Song) -> LineStarts:
    """Read ``alignment.json`` and ``lyrics.json`` of a finished song: numbers only."""
    aligned = AlignmentFile.model_validate_json(
        (song.work_dir / "alignment.json").read_text("utf-8")
    )
    lyrics = lyrics_of(song)
    return LineStarts([line.start for line in aligned.lines], [line.time for line in lyrics.lines])
