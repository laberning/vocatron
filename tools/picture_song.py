"""Write the timing file of the picture song from the work folder of the English demo run.

``make picture-song`` runs this (ADR-0045). The work folder of an accepted
``make demo-accept LANGUAGE=en`` holds ``lyrics.json``, ``syllables.json``, ``tempo.json`` and
``song.json``; the lines, syllable times, singers, tempo and length of them go into
``tests/data/demo/<name>.timing.json``, which feeds the pictures of the looks and the animation
without the GPU and without the audio. The song is under CC BY 4.0 and its lyrics are already part
of the repository. Run it again after an accepted demo run and run
``make profile-pictures readme-gif`` after it.
"""

import functools
import sys
from collections.abc import Sequence
from pathlib import Path

from vocatron.core.lyrics.file import LyricsFile
from vocatron.core.profiles.picture import (
    PictureSong,
    parse_picture_song,
    picture_song_of,
    render_picture_song,
)
from vocatron.core.song import SongInfo
from vocatron.core.syllables import SyllablesFile
from vocatron.core.tempo import TempoFile

CLONE = Path(__file__).resolve().parent.parent
DEMO_NAME = "Josh Woodward - My Favorite Regret"
WORK_FOLDER = CLONE / ".corpus" / "demo" / "make-en" / "karaoke" / DEMO_NAME
SONG_FILE = CLONE / "tests" / "data" / "demo" / f"{DEMO_NAME}.timing.json"
"""The committed timing of the picture song."""


@functools.cache
def committed_song() -> PictureSong:
    """Read the committed timing of the picture song, once per process."""
    return parse_picture_song(SONG_FILE.read_text(encoding="utf-8"))


def read_song(work: Path) -> PictureSong:
    """Read the stage files of the work folder ``work`` and collect the picture song.

    Raises:
        FileNotFoundError: If a stage file is missing.
        ValueError: If a stage file does not validate.
    """
    return picture_song_of(
        LyricsFile.model_validate_json((work / "lyrics.json").read_text(encoding="utf-8")),
        SyllablesFile.model_validate_json((work / "syllables.json").read_text(encoding="utf-8")),
        TempoFile.model_validate_json((work / "tempo.json").read_text(encoding="utf-8")),
        SongInfo.model_validate_json((work / "song.json").read_text(encoding="utf-8")),
    )


def export(work: Path, target: Path) -> PictureSong:
    """Write the picture song of the work folder ``work`` to ``target``; return it."""
    song = read_song(work)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_picture_song(song), encoding="utf-8")
    return song


def main(argv: Sequence[str]) -> int:
    """Write the timing file from the work folder in ``argv`` (default: the demo run)."""
    work = Path(argv[0]) if argv else WORK_FOLDER
    try:
        song = export(work, SONG_FILE)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"wrote {SONG_FILE.relative_to(CLONE)}: {len(song.lines)} lines, {len(song.words)} words")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
