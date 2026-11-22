"""Stage 1: module names are one word, or words joined by ``_`` (ADR-0042).

Every part of the name of every module and package under ``src/vocatron`` (split at ``_``) must
be in ``WORDS``. A name that runs two words together (``stagefile``) is not in the list, so it
fails here; write it in ``snake_case`` or, for a new word, add it to the list.
"""

from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "src" / "vocatron"

# Vendored names (bs, roformer, band) keep the spelling of the model they come from.
WORDS = frozenset(
    (
        "alignment",
        "analysis",
        "app",
        "ass",
        "attend",
        "audio",
        "band",
        "base",
        "batch",
        "bench",
        "bs",
        "build",
        "canvas",
        "cards",
        "cdg",
        "check",
        "child",
        "chunks",
        "clean",
        "cli",
        "clock",
        "cmd",
        "colour",
        "commands",
        "config",
        "console",
        "copy",
        "core",
        "ctc",
        "de",
        "decode",
        "doctor",
        "document",
        "downloader",
        "en",
        "encode",
        "engines",
        "errors",
        "estimate",
        "eval",
        "evaluation",
        "events",
        "ffmpeg",
        "file",
        "files",
        "fit",
        "font",
        "glyphs",
        "gpu",
        "hold",
        "id3",
        "inference",
        "interrupt",
        "intro",
        "job",
        "lab",
        "language",
        "languages",
        "layout",
        "logo",
        "listening",
        "look",
        "lrc",
        "lrclib",
        "lyrics",
        "map",
        "mark",
        "match",
        "measure",
        "mel",
        "metrics",
        "mix",
        "model",
        "models",
        "mp4",
        "names",
        "origin",
        "output",
        "pack",
        "packet",
        "page",
        "pages",
        "palette",
        "parse",
        "phrases",
        "picture",
        "place",
        "pos",
        "presets",
        "probe",
        "process",
        "profiles",
        "progress",
        "protocols",
        "quality",
        "rails",
        "raster",
        "registry",
        "render",
        "report",
        "resources",
        "roformer",
        "rules",
        "sample",
        "scene",
        "schedule",
        "schemas",
        "screen",
        "scroll",
        "separation",
        "showing",
        "singers",
        "slots",
        "solve",
        "song",
        "songs",
        "stage",
        "stages",
        "start",
        "status",
        "stream",
        "syllables",
        "system",
        "tags",
        "tempo",
        "text",
        "tile",
        "timing",
        "tokens",
        "tracking",
        "unheard",
        "verdict",
        "versions",
        "voice",
        "voices",
        "word",
        "wordmark",
        "worker",
        "write",
        "yaml",
    )
)


def module_names(source: Path = SOURCE) -> list[Path]:
    """Return every module file and package folder under ``source`` (``__init__`` excluded)."""
    files = [p for p in source.rglob("*.py") if not p.stem.startswith("__")]
    folders = [p.parent for p in source.rglob("__init__.py") if p.parent != source]
    return sorted({*files, *folders})


def unknown_parts(name: str) -> list[str]:
    """Return the parts of a module name (split at ``_``) that are not in ``WORDS``."""
    return [part for part in name.split("_") if part not in WORDS]


def test_every_module_name_is_made_of_known_words() -> None:
    bad = {
        path.relative_to(SOURCE).as_posix(): unknown_parts(path.stem)
        for path in module_names()
        if unknown_parts(path.stem)
    }
    assert not bad, f"write the name in snake_case or add the word to WORDS in this file: {bad}"


@pytest.mark.parametrize(
    "name", ["stagefile", "profilecheck", "configerrors", "evalworker", "tilemap"]
)
def test_a_name_that_runs_words_together_is_refused(name: str) -> None:
    assert unknown_parts(name) == [name]


@pytest.mark.parametrize(
    "name", ["stage_file", "config_errors", "eval_worker", "mel_band_roformer"]
)
def test_snake_case_names_pass(name: str) -> None:
    assert unknown_parts(name) == []
