"""Stage 1: song discovery, identity and naming on fakes."""

from pathlib import Path

import pytest

from fakes.songs import FakeWorld
from vocatron.core.errors import UsageError
from vocatron.core.song import Tags
from vocatron.stages.config import Config, OutputSettings
from vocatron.stages.songs import discover

MUSIC = Path("/music")


def test_a_folder_yields_its_audio_files_only(world: FakeWorld) -> None:
    world.add_song(MUSIC / "b.mp3")
    world.add_song(MUSIC / "a.flac")
    world.store.add(MUSIC / "notes.txt")
    world.store.add(MUSIC / "karaoke" / "Old.wav")  # the output folder is never scanned
    world.store.add(MUSIC / "sub" / "deep.mp3")
    songs = discover(MUSIC, Config(), world.engines)
    assert [s.source.name for s in songs] == ["a.flac", "b.mp3"]
    assert songs[0].output_dir == MUSIC / "karaoke"
    assert songs[0].work_dir == MUSIC / "karaoke" / "Artist - Title"


def test_names_are_unique_and_the_same_for_a_single_file(world: FakeWorld) -> None:
    for name in ("a.mp3", "b.mp3", "c.mp3"):
        world.add_song(MUSIC / name)
    everyone = discover(MUSIC, Config(), world.engines)
    assert [s.name for s in everyone] == [
        "Artist - Title",
        "Artist - Title (2)",
        "Artist - Title (3)",
    ]
    alone = discover(MUSIC / "b.mp3", Config(), world.engines)
    assert [s.name for s in alone] == ["Artist - Title (2)"]


def test_unreadable_tags_fall_back_to_the_file_name(world: FakeWorld) -> None:
    world.add_song(MUSIC / "Queen - Radio Ga Ga.mp3", tags=None)
    (song,) = discover(MUSIC, Config(), world.engines)
    assert song.name == "Queen - Radio Ga Ga"
    assert song.tags is None
    assert song.tag_error is not None
    assert "Radio Ga Ga" in song.tag_error


def test_the_output_folder_can_be_relative_or_absolute(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3", tags=Tags("A", "T", 5))
    relative = Config(output=OutputSettings(folder="out/tracks"))
    assert discover(MUSIC, relative, world.engines)[0].output_dir == MUSIC / "out" / "tracks"
    absolute = Config(output=OutputSettings(folder="/elsewhere"))
    assert discover(MUSIC, absolute, world.engines)[0].work_dir == Path("/elsewhere/A - T")


@pytest.mark.parametrize(
    ("target", "message"),
    [
        (MUSIC / "missing.mp3", "does not exist"),
        (MUSIC / "notes.txt", "not an audio file"),
        (Path("/empty"), "no audio files"),
    ],
)
def test_usage_errors(world: FakeWorld, target: Path, message: str) -> None:
    world.store.add(MUSIC / "notes.txt")
    world.store.make_folder(Path("/empty"))
    with pytest.raises(UsageError, match=message):
        discover(target, Config(), world.engines)


def test_a_file_the_store_does_not_list_is_an_error(
    world: FakeWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    world.add_song(MUSIC / "a.mp3")
    world.add_song(MUSIC / "b.mp3")

    def only_a(folder: Path) -> list[Path]:
        return [MUSIC / "a.mp3"]

    monkeypatch.setattr(world.store, "list_audio", only_a)
    with pytest.raises(UsageError, match="was not found"):
        discover(MUSIC / "b.mp3", Config(), world.engines)
