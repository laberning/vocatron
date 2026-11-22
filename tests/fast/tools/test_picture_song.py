"""Stage 1: ``tools/picture_song.py`` writes the timing of the picture song from a work folder."""

from pathlib import Path

import pytest

import picture_song
from fakes.picture_song import made_up_song
from vocatron.core.lyrics.document import Mark
from vocatron.core.lyrics.file import LyricLine, LyricsFile
from vocatron.core.profiles.picture import PictureSong, parse_picture_song, picture_song_of
from vocatron.core.song import SongInfo
from vocatron.core.stage_file import Fingerprint
from vocatron.core.syllables import SyllablesFile
from vocatron.core.tempo import TempoFile

FINGERPRINT = Fingerprint(inputs={}, settings="s", stage_version=1)


def work_folder(folder: Path, song: PictureSong | None = None) -> Path:
    """Write the four stage files of a made-up song (or ``song``) into ``folder``."""
    song = song or made_up_song()
    lyrics = LyricsFile(
        fingerprint=FINGERPRINT, source="sidecar", sidecar="x.txt", sidecar_hash="h", original="",
        lines=[
            LyricLine(text=x.text, singers=x.singers, turns=x.turns, time=1.5) for x in song.lines
        ],
        singers=song.singers, duet=False, language="de", removed=[], findings=[], approved=False,
        status="ok",
    )  # fmt: skip
    syllables = SyllablesFile(fingerprint=FINGERPRINT, language="de", words=song.words)
    tempo = TempoFile(fingerprint=FINGERPRINT, bpm=song.bpm, clarity=0.5)
    info = SongInfo(
        fingerprint=FINGERPRINT, artist=song.artist, title=song.title, name="n",
        source_file="n.mp3", duration=song.duration,
    )  # fmt: skip
    folder.mkdir(parents=True, exist_ok=True)
    for name, model in (
        ("lyrics.json", lyrics), ("syllables.json", syllables), ("tempo.json", tempo),
        ("song.json", info),
    ):  # fmt: skip
        (folder / name).write_text(model.model_dump_json(), encoding="utf-8")
    return folder


def test_the_stage_files_of_a_work_folder_become_the_picture_song(tmp_path: Path) -> None:
    folder = work_folder(tmp_path / "work")
    assert picture_song.read_song(folder) == made_up_song()  # the line time hint is left out


def test_the_export_writes_a_file_the_pictures_can_read(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "song.timing.json"
    written = picture_song.export(work_folder(tmp_path / "work"), target)
    assert parse_picture_song(target.read_text(encoding="utf-8")) == written


def test_the_collecting_is_the_same_as_the_one_of_the_core(tmp_path: Path) -> None:
    folder = work_folder(tmp_path / "work")
    lyrics = LyricsFile.model_validate_json((folder / "lyrics.json").read_text(encoding="utf-8"))
    syllables = SyllablesFile.model_validate_json(
        (folder / "syllables.json").read_text(encoding="utf-8")
    )
    tempo = TempoFile.model_validate_json((folder / "tempo.json").read_text(encoding="utf-8"))
    info = SongInfo.model_validate_json((folder / "song.json").read_text(encoding="utf-8"))
    assert picture_song_of(lyrics, syllables, tempo, info) == picture_song.read_song(folder)


def test_a_missing_work_folder_is_an_error_not_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert picture_song.main([str(tmp_path / "nothing")]) == 1
    assert "error" in capsys.readouterr().err


def test_the_singer_turns_inside_a_line_are_kept(tmp_path: Path) -> None:
    song = made_up_song()
    turned = LyricLine(text=song.lines[0].text, singers="1", turns=[Mark(word=2, singers="2")])
    song = song.model_copy(update={"lines": [turned, *song.lines[1:]]})
    assert picture_song.read_song(work_folder(tmp_path / "work", song)).lines[0].turns == (
        turned.turns
    )
