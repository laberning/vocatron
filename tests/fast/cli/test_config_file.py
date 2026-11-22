"""Stage 1: configuration loading, precedence and error positions."""

from pathlib import Path

import pytest

from fakes.songs import FakeWorld
from vocatron.cli.config_file import ConfigError, Overrides, load_config
from vocatron.stages.config import Config, ProbeSettings

CWD = Path("/work")
FILE = CWD / "vocatron.yaml"


def errors_of(world: FakeWorld, yaml: str) -> list[str]:
    world.store.add(FILE, yaml.encode())
    with pytest.raises(ConfigError) as error:
        load_config(world.store, None, CWD)
    return error.value.messages


def test_without_a_file_the_defaults_apply(world: FakeWorld) -> None:
    assert load_config(world.store, None, CWD) == Config()


def test_the_file_overrides_the_defaults(world: FakeWorld) -> None:
    world.store.add(FILE, b"output:\n  folder: tracks\nprobe:\n  min_duration: 5\n")
    config = load_config(world.store, None, CWD)
    assert config.output.folder == "/work/tracks"  # relative to the folder of the file
    assert config.probe == ProbeSettings(min_duration=5)


def test_an_option_overrides_the_file(world: FakeWorld) -> None:
    world.store.add(FILE, b"output:\n  folder: tracks\n")
    assert load_config(world.store, None, CWD, output="cli").output.folder == "/work/cli"


def test_an_explicit_file_is_read_instead_of_the_default(world: FakeWorld) -> None:
    world.store.add(FILE, b"output:\n  folder: tracks\n")
    world.store.add(Path("/other.yaml"), b"output:\n  folder: other\n")
    assert load_config(world.store, Path("/other.yaml"), CWD).output.folder == "/other"


def test_an_explicit_file_must_exist(world: FakeWorld) -> None:
    with pytest.raises(ConfigError) as error:
        load_config(world.store, Path("/nope.yaml"), CWD)
    assert error.value.messages == ["/nope.yaml: file not found"]


def test_an_empty_file_means_defaults(world: FakeWorld) -> None:
    world.store.add(FILE, b"# only a comment\n")
    assert load_config(world.store, None, CWD) == Config()


def test_a_wrong_type_names_file_line_and_column(world: FakeWorld) -> None:
    messages = errors_of(world, "output:\n  folder: x\nprobe:\n  min_duration: soon\n")
    assert len(messages) == 1
    assert messages[0].startswith("/work/vocatron.yaml:4:3: probe.min_duration: ")


def test_an_unknown_key_is_an_error_at_that_key(world: FakeWorld) -> None:
    messages = errors_of(world, "probe:\n  min_duraton: 3\nextra: [1, 2]\n")
    assert [m.split(": ")[0] for m in messages] == [
        "/work/vocatron.yaml:2:3",
        "/work/vocatron.yaml:3:1",
    ]
    assert "probe.min_duraton" in messages[0]


def test_a_value_that_is_not_a_mapping_is_an_error(world: FakeWorld) -> None:
    messages = errors_of(world, "- a\n- b\n")
    assert messages[0].startswith("/work/vocatron.yaml:1:1: ")


def test_invalid_yaml_names_the_position_of_the_problem(world: FakeWorld) -> None:
    messages = errors_of(world, "output:\n  folder: [unclosed\n")
    assert messages[0].startswith("/work/vocatron.yaml:")
    assert len(messages) == 1


def test_an_invalid_option_is_a_config_error(world: FakeWorld) -> None:
    with pytest.raises(ConfigError) as error:
        load_config(world.store, None, CWD, output="")
    assert error.value.messages[0].startswith("--output: ")


def test_a_file_that_is_not_text_is_a_config_error(world: FakeWorld) -> None:
    world.store.add(FILE, b"\xff\xfe")
    with pytest.raises(ConfigError) as error:
        load_config(world.store, None, CWD)
    assert error.value.messages[0].startswith("/work/vocatron.yaml: cannot read: ")


def test_relative_output_folders_are_anchored_where_they_were_written(world: FakeWorld) -> None:
    world.store.add(Path("/etc/vk/settings.yaml"), b"output:\n  folder: tracks\n")
    world.store.add(Path("/work/sub/v.yaml"), b"output:\n  folder: /abs\n")
    world.store.add(Path("/work/sub/w.yaml"), b"probe:\n  min_duration: 2\n")
    from_file = load_config(world.store, Path("/etc/vk/settings.yaml"), CWD)
    assert from_file.output.folder == "/etc/vk/tracks"
    assert load_config(world.store, Path("sub/v.yaml"), CWD).output.folder == "/abs"
    assert load_config(world.store, Path("sub/w.yaml"), CWD).output.folder == "karaoke"  # default
    assert load_config(world.store, None, CWD, output="../out").output.folder == "/work/../out"
    assert load_config(world.store, None, CWD, output="/abs").output.folder == "/abs"
    assert load_config(world.store, None, CWD).output.folder == "karaoke"  # relative to the songs


CLONE = Path("/clone")


def test_the_default_model_folder_lies_in_the_clone(world: FakeWorld) -> None:
    config = load_config(world.store, None, CWD, clone=CLONE)
    assert config.models.folder == "/clone/.cache/models"


def test_without_a_clone_the_default_model_folder_stays_relative(world: FakeWorld) -> None:
    assert load_config(world.store, None, CWD).models.folder == ".cache/models"


def test_a_model_folder_in_the_file_is_relative_to_the_file(world: FakeWorld) -> None:
    world.store.add(FILE, b"models:\n  folder: stuff\n")
    assert load_config(world.store, None, CWD, clone=CLONE).models.folder == "/work/stuff"
    world.store.add(FILE, b"models:\n  folder: /abs/models\n")
    assert load_config(world.store, None, CWD, clone=CLONE).models.folder == "/abs/models"


def test_the_language_option_overrides_the_file(world: FakeWorld) -> None:
    world.store.add(FILE, b"lyrics:\n  language: de\n  lookup: false\n")
    from_file = load_config(world.store, None, CWD)
    assert (from_file.lyrics.language, from_file.lyrics.lookup) == ("de", False)
    config = load_config(world.store, None, CWD, overrides=Overrides(language="de"))
    assert (config.lyrics.language, config.lyrics.lookup) == ("de", False)  # the rest stays
    assert load_config(world.store, None, CWD).lyrics.language == "de"


def test_an_unsupported_language_is_a_config_error(world: FakeWorld) -> None:
    (message,) = errors_of(world, "lyrics:\n  language: fr\n")
    assert message.startswith("/work/vocatron.yaml:2:")
    assert "language 'fr' is not supported" in message
    with pytest.raises(ConfigError) as error:
        load_config(FakeWorld().store, None, CWD, overrides=Overrides(language="fr"))
    assert error.value.messages[0].startswith("--language: ")
    assert "supported: de (German), en (English)" in error.value.messages[0]


def test_the_profiles_folder_is_anchored_at_the_folder_of_the_file(world: FakeWorld) -> None:
    world.store.add(FILE, b"profiles_folder: looks\n")
    assert load_config(world.store, None, CWD).profiles_folder == "/work/looks"
    assert load_config(world.store.__class__(), None, CWD).profiles_folder is None


def test_a_profile_name_stays_a_name_and_a_path_is_anchored(world: FakeWorld) -> None:
    world.store.add(FILE, b"profile: mine\n")
    assert load_config(world.store, None, CWD).profile == "mine"
    world.store.add(FILE, b"profile: looks/mine.yaml\n")
    assert load_config(world.store, None, CWD).profile == "/work/looks/mine.yaml"
    world.store.add(FILE, b"profile: ./mine\n")
    assert load_config(world.store, None, CWD).profile == "/work/mine"


def test_the_profile_option_is_anchored_at_the_current_folder(world: FakeWorld) -> None:
    named = load_config(world.store, None, CWD, overrides=Overrides(profile="mine"))
    assert named.profile == "mine"
    path = load_config(world.store, None, CWD, overrides=Overrides(profile="mine.yml"))
    assert path.profile == "/work/mine.yml"


def test_the_outputs_default_to_the_video_and_the_file_can_add_cdg(world: FakeWorld) -> None:
    assert Config().outputs == ["mp4"]
    world.store.add(FILE, b"outputs: [mp4, cdg]\n")
    assert load_config(world.store, None, CWD).outputs == ["mp4", "cdg"]


def test_an_unknown_output_name_is_an_error_at_that_item(world: FakeWorld) -> None:
    messages = errors_of(world, "profile: two-line-turns\noutputs:\n  - mp4\n  - wav\n")
    assert messages[0].startswith("/work/vocatron.yaml:4:5: outputs.1: ")
    assert "mp4" in messages[0] and "cdg" in messages[0]


def test_outputs_without_the_video_are_an_error(world: FakeWorld) -> None:
    messages = errors_of(world, "outputs: [cdg]\n")
    assert messages[0].startswith("/work/vocatron.yaml:1:")
    assert "outputs must contain mp4" in messages[0]


def test_the_cdg_option_adds_cdg_to_the_outputs_of_this_run(world: FakeWorld) -> None:
    assert load_config(world.store, None, CWD, overrides=Overrides(cdg=True)).outputs == [
        "mp4",
        "cdg",
    ]
    assert load_config(world.store, None, CWD, overrides=Overrides()).outputs == ["mp4"]
    world.store.add(FILE, b"outputs: [mp4, cdg]\n")
    both = load_config(world.store, None, CWD, overrides=Overrides(cdg=True))
    assert both.outputs == ["mp4", "cdg"]  # not added twice


def test_no_audio_export_is_the_default_and_the_file_can_ask_for_one(world: FakeWorld) -> None:
    assert load_config(world.store, None, CWD).audio.export == "none"
    world.store.add(FILE, b"audio:\n  export: flac\n")
    assert load_config(world.store, None, CWD).audio.export == "flac"
