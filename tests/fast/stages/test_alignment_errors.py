"""Stage 1: what the alignment and syllables stages do with inputs that are not right."""

from pathlib import Path

import pytest

from fakes.songs import FakeWorld
from vocatron.core.alignment.file import AlignmentFile
from vocatron.core.errors import StageError
from vocatron.core.lyrics.file import LyricLine, LyricsFile
from vocatron.core.separation.file import stem_path
from vocatron.core.stage_file import Fingerprint
from vocatron.core.status import SongStatus
from vocatron.stages.alignment import AlignmentStage, module_of
from vocatron.stages.batch import run_song
from vocatron.stages.config import Config
from vocatron.stages.stage import StageContext
from vocatron.stages.syllables import SyllablesStage

MUSIC = Path("/music")
AUDIO = MUSIC / "Artist - Title.mp3"
WORK = MUSIC / "karaoke" / "Artist - Title"
NOTHING = Fingerprint(inputs={}, settings="", stage_version=1)


@pytest.fixture
def done(world: FakeWorld) -> FakeWorld:
    world.add_song(AUDIO)
    run_song(world.song(AUDIO), Config(), world.engines, force=False)
    return world


def context(world: FakeWorld) -> StageContext:
    return world.context(AUDIO)


def test_a_language_without_a_module_is_a_typed_error() -> None:
    with pytest.raises(StageError) as error:
        module_of("xx")
    assert error.value.kind == "unsupported-language"


def test_the_alignment_needs_a_valid_lyrics_file(done: FakeWorld) -> None:
    done.store.add(WORK / "lyrics.json", b"{broken")
    with pytest.raises(StageError, match="lyrics.json is missing or invalid") as error:
        AlignmentStage().execute(context(done), Config(), NOTHING)
    assert error.value.kind == "missing-input"


def test_a_line_without_any_word_cannot_be_placed(done: FakeWorld) -> None:
    text = done.store.read_text(WORK / "lyrics.json")
    assert text is not None
    lyrics = LyricsFile.model_validate_json(text)
    lines = [*lyrics.lines, LyricLine(text="   ", singers="all")]
    done.store.add(
        WORK / "lyrics.json", lyrics.model_copy(update={"lines": lines}).model_dump_json().encode()
    )
    with pytest.raises(StageError, match="line 6 has no word") as error:
        AlignmentStage().execute(context(done), Config(), NOTHING)
    assert error.value.kind == "alignment-failed"


@pytest.mark.parametrize("content", [None, b"{broken"])
def test_the_syllables_need_a_valid_alignment_file(done: FakeWorld, content: bytes | None) -> None:
    if content is None:
        done.store.delete(WORK / "alignment.json")
    else:
        done.store.add(WORK / "alignment.json", content)
    with pytest.raises(StageError, match="alignment.json is missing or invalid") as error:
        SyllablesStage().execute(context(done), Config(), NOTHING)
    assert error.value.kind == "missing-input"


def test_the_syllables_of_a_language_without_a_module_are_a_typed_error(done: FakeWorld) -> None:
    text = done.store.read_text(WORK / "alignment.json")
    assert text is not None
    other = AlignmentFile.model_validate_json(text).model_copy(update={"language": "xx"})
    done.store.add(WORK / "alignment.json", other.model_dump_json().encode())
    with pytest.raises(StageError) as error:
        SyllablesStage().execute(context(done), Config(), NOTHING)
    assert error.value.kind == "unsupported-language"


def test_a_partial_run_cannot_judge_a_stage_whose_input_is_gone(done: FakeWorld) -> None:
    done.store.delete(WORK / stem_path("lead"))
    status = run_song(done.song(AUDIO), Config(), done.engines, force=False, until="lyrics")
    assert isinstance(status, SongStatus)
    assert [(o.stage, o.action) for o in status.stages][-7:] == [
        ("separation", "outdated"),
        ("tempo", "outdated"),
        ("alignment", "outdated"),
        ("syllables", "outdated"),
        ("layout", "outdated"),
        ("render", "outdated"),
        ("cdg", "outdated"),
    ]


def test_a_partial_run_cannot_judge_a_stage_whose_own_input_file_is_missing(
    done: FakeWorld,
) -> None:
    # The audio vanished after a full run: the stages that read it cannot be fingerprinted.
    song = done.song(AUDIO)
    done.store.delete(AUDIO)
    status = run_song(song, Config(), done.engines, force=False, until="lyrics")
    later = {o.stage: o.action for o in status.stages if o.stage in {"separation", "alignment"}}
    assert later == {"separation": "outdated", "alignment": "outdated"}
