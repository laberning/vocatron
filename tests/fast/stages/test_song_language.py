"""Stage 1: the language of a song picks its alignment model and its fingerprint (ADR-0016)."""

from pathlib import Path

import pytest

from fakes.lyrics import ENGLISH, ENTCHEN, HAENSCHEN, TWINKLE
from fakes.songs import FakeWorld
from vocatron.core.alignment.file import AlignmentFile
from vocatron.core.models import find_model
from vocatron.core.song import Tags
from vocatron.core.stage_file import settings_hash
from vocatron.core.status import SongStatus
from vocatron.stages.alignment import AlignmentStage
from vocatron.stages.batch import Options, run_batch, run_song
from vocatron.stages.config import Config, LyricsSettings
from vocatron.stages.songs import discover

MUSIC = Path("/music")
GERMAN_SONG = MUSIC / "Artist - German.mp3"
ENGLISH_SONG = MUSIC / "Artist - English.mp3"

# The settings hash of the German alignment fingerprint for the default configuration, first
# recorded before the alignment learned to follow the language of the song: following the
# language must not change it, so stored German results stay current. A new number in the
# fingerprint changes it on purpose; it was re-recorded for the constants of ADR-0021 and again
# for those of ADR-0027, for those of the second voice (ADR-0052) and for those of ADR-0053.
GERMAN_ALIGNMENT_SETTINGS = "8616b4dcbd9c28f05c013814cc059c304ec80b148b30f47a4ad91d47efa98f08"


@pytest.fixture
def mixed(world: FakeWorld) -> FakeWorld:
    """A folder with one German and one English song; the detector tells them apart."""
    world.add_song(GERMAN_SONG, Tags("Artist", "German", 180.0), lyrics=ENTCHEN)
    world.add_song(ENGLISH_SONG, Tags("Artist", "English", 180.0), lyrics=TWINKLE)
    world.language.by_keyword = {"Twinkle": ENGLISH}
    return world


def models_requested(world: FakeWorld) -> set[str]:
    return {destination.parent.name for _, destination in world.downloader.calls}


def alignment_of(world: FakeWorld, audio: Path) -> AlignmentFile:
    text = world.store.read_text(world.song(audio).work_dir / "alignment.json")
    assert text is not None
    return AlignmentFile.model_validate_json(text)


def run_one(world: FakeWorld, path: Path, config: Config | None = None) -> SongStatus:
    return world.run(path, config)


def test_the_german_alignment_keeps_the_fingerprint_it_had_before(world: FakeWorld) -> None:
    world.add_song(GERMAN_SONG, Tags("Artist", "German", 180.0), lyrics=ENTCHEN)
    stage = AlignmentStage()
    before_lyrics = stage.declared_settings(world.context(GERMAN_SONG), Config())
    assert settings_hash(before_lyrics) == GERMAN_ALIGNMENT_SETTINGS
    assert run_one(world, GERMAN_SONG).state == "ok"
    stored = alignment_of(world, GERMAN_SONG)
    assert stored.fingerprint.settings == GERMAN_ALIGNMENT_SETTINGS
    after = stage.declared_settings(world.context(GERMAN_SONG), Config())
    assert settings_hash(after) == GERMAN_ALIGNMENT_SETTINGS
    german = Config(lyrics=LyricsSettings(language="de"))
    assert settings_hash(stage.declared_settings(world.context(GERMAN_SONG), german)) == (
        GERMAN_ALIGNMENT_SETTINGS
    )


def test_an_english_song_is_aligned_with_the_english_model_and_the_file_says_so(
    mixed: FakeWorld,
) -> None:
    assert run_one(mixed, ENGLISH_SONG).state == "ok"
    (request,) = mixed.acoustic.requests
    assert request.model.name == "wav2vec2-en"
    assert request.model.folder.endswith(".cache/models/wav2vec2-en")
    english = find_model("wav2vec2-en")
    file = alignment_of(mixed, ENGLISH_SONG)
    assert (file.language, file.model, file.revision) == ("en", "wav2vec2-en", english.revision)
    assert file.fingerprint.settings != GERMAN_ALIGNMENT_SETTINGS
    pinned = AlignmentStage().declared_settings(mixed.context(ENGLISH_SONG), Config())
    assert settings_hash(pinned) == file.fingerprint.settings
    assert pinned.model_dump()["model"]["name"] == "wav2vec2-en"
    assert "wav2vec2-en" in models_requested(mixed)
    assert "wav2vec2-de" not in models_requested(mixed)
    assert [w.text for w in file.words][:3] == ["Twinkle,", "twinkle,", "little"]


def test_a_german_only_folder_never_asks_for_the_english_model(world: FakeWorld) -> None:
    world.add_song(GERMAN_SONG, Tags("Artist", "German", 180.0), lyrics=ENTCHEN)
    world.add_song(MUSIC / "Artist - Second.mp3", Tags("Artist", "Second", 180.0), lyrics=HAENSCHEN)
    songs = discover(MUSIC, Config(), world.engines)
    run_batch(songs, Config(), world.engines, Options())
    assert "wav2vec2-de" in models_requested(world)
    assert "wav2vec2-en" not in models_requested(world)
    assert {r.model.name for r in world.acoustic.requests} == {"wav2vec2-de"}


def test_a_folder_of_german_and_english_songs_runs_in_one_batch(mixed: FakeWorld) -> None:
    songs = discover(MUSIC, Config(), mixed.engines)
    results = run_batch(songs, Config(), mixed.engines, Options())
    assert [r.status.state for r in results] == ["ok", "ok"]
    models = {r.model.folder.rsplit("/", 1)[-1] for r in mixed.acoustic.requests}
    assert models == {"wav2vec2-de", "wav2vec2-en"}
    assert len(mixed.acoustic.requests) == 2
    assert alignment_of(mixed, GERMAN_SONG).language == "de"
    assert alignment_of(mixed, ENGLISH_SONG).language == "en"


def test_a_second_run_finds_the_english_song_current(mixed: FakeWorld) -> None:
    run_one(mixed, ENGLISH_SONG)
    again = run_one(mixed, ENGLISH_SONG)
    assert [o.action for o in again.stages] == ["skipped"] * 9
    assert len(mixed.acoustic.requests) == 1


def test_offline_an_english_song_without_its_model_fails_with_the_command_to_run(
    mixed: FakeWorld,
) -> None:
    config = Config()
    song = mixed.song(ENGLISH_SONG, config)
    first = run_song(song, config, mixed.engines, force=False, until="separation")
    assert first.state == "ok"
    status = run_song(song, config, mixed.engines, force=False, offline=True)
    assert status.state == "failed"
    assert status.error is not None
    assert (status.error.stage, status.error.kind) == ("alignment", "models-missing")
    assert "vocatron models download wav2vec2-en" in status.error.message
    assert mixed.acoustic.requests == []


def test_the_language_setting_overrides_the_detection_for_both_languages(
    mixed: FakeWorld,
) -> None:
    english = Config(lyrics=LyricsSettings(language="en"))
    assert run_one(mixed, GERMAN_SONG, english).state == "ok"  # forced, whatever the text is
    assert alignment_of(mixed, GERMAN_SONG).model == "wav2vec2-en"
    german = Config(lyrics=LyricsSettings(language="de"))
    assert run_one(mixed, ENGLISH_SONG, german).state == "ok"
    assert alignment_of(mixed, ENGLISH_SONG).model == "wav2vec2-de"
    assert [r.model.name for r in mixed.acoustic.requests] == ["wav2vec2-en", "wav2vec2-de"]
    # The detector was not asked for a song whose language is set.
    assert mixed.language.texts == []


def test_before_the_lyrics_exist_the_pin_follows_the_setting_and_never_fails(
    mixed: FakeWorld,
) -> None:
    stage = AlignmentStage()
    ctx = mixed.context(ENGLISH_SONG)
    assert stage.required_models(ctx, Config()) == ("wav2vec2-de",)
    english = Config(lyrics=LyricsSettings(language="en"))
    assert stage.required_models(ctx, english) == ("wav2vec2-en",)
    mixed.store.add(mixed.song(ENGLISH_SONG).work_dir / "lyrics.json", b"{broken")
    assert stage.required_models(ctx, Config()) == ("wav2vec2-de",)  # invalid: as if missing
    run_one(mixed, ENGLISH_SONG)
    assert stage.required_models(ctx, Config()) == ("wav2vec2-en",)  # the file wins
    assert stage.required_models(ctx, Config(lyrics=LyricsSettings(language="de"))) == (
        "wav2vec2-en",
    )  # the lyrics stage already applied the setting to the file
