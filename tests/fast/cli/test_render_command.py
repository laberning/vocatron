"""Stage 1: ``vocatron render`` re-renders from the work folder without the AI stages (ADR-0009)."""

from pathlib import Path

import pytest

from fakes.songs import FakeWorld
from fakes.streams import Streams
from vocatron.cli import app as app_module
from vocatron.cli.app import app
from vocatron.cli.commands import run_make, run_render
from vocatron.cli.config_file import ConfigError, Overrides, load_config

MUSIC = Path("/music")
OUT = MUSIC / "karaoke"


def make(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    streams = Streams(world)
    assert run_make(MUSIC, output=None, config_file=None, edges=streams.edges) == 0


def test_render_makes_the_files_again_and_runs_no_ai_stage(world: FakeWorld) -> None:
    make(world)
    world.store.delete(OUT / "Artist - Title.mp4")
    streams = Streams(world)
    code = run_render(MUSIC, output=None, config_file=None, force=False, edges=streams.edges)
    assert code == 0
    assert world.store.size(OUT / "Artist - Title.mp4") is not None
    assert len(world.separator.requests) == len(world.acoustic.requests) == 1
    assert len(world.renderer.requests) == 2
    assert "1 songs: 1 ok" in streams.out.getvalue() or "1 song: 1 ok" in streams.out.getvalue()


def test_render_makes_the_tempo_of_a_song_made_before_the_tempo_stage_existed(
    world: FakeWorld,
) -> None:
    make(world)
    world.store.delete(OUT / "Artist - Title" / "tempo.json")
    world.store.delete(OUT / "Artist - Title.mp4")
    streams = Streams(world)
    code = run_render(MUSIC, output=None, config_file=None, force=False, edges=streams.edges)
    assert code == 0
    assert world.store.size(OUT / "Artist - Title" / "tempo.json") is not None
    assert len(world.separator.requests) == 1


def test_a_new_profile_by_option_runs_the_layout_and_the_render(world: FakeWorld) -> None:
    make(world)
    world.store.add(
        Path("/work/dark.yaml"),
        (world.resources.builtin_profile("two-line-turns") or "")
        .replace("slots: 2", "slots: 3")
        .encode(),
    )
    streams = Streams(world)
    overrides = Overrides(profile="dark.yaml")
    code = run_render(
        MUSIC, output=None, config_file=None, force=False, overrides=overrides, edges=streams.edges
    )
    assert code == 0
    assert len(world.renderer.requests) == 2
    assert len(world.acoustic.requests) == 1


def test_a_new_preset_by_option_renders_in_that_size(world: FakeWorld) -> None:
    make(world)
    streams = Streams(world)
    code = run_render(
        MUSIC,
        output=None,
        config_file=None,
        force=False,
        overrides=Overrides(preset="16x9-1080"),
        edges=streams.edges,
    )
    assert code == 0
    assert world.renderer.requests[-1].preset.name == "16x9-1080"


def test_an_unknown_preset_is_a_usage_error_that_names_the_option(world: FakeWorld) -> None:
    make(world)
    streams = Streams(world)
    code = run_render(
        MUSIC,
        output=None,
        config_file=None,
        force=False,
        overrides=Overrides(preset="8k"),
        edges=streams.edges,
    )
    assert code == 2
    assert "--preset" in streams.err.getvalue()
    assert "4x3-720" in streams.err.getvalue()


def test_render_of_a_song_that_was_never_made_says_what_to_do(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    streams = Streams(world)
    code = run_render(MUSIC, output=None, config_file=None, force=False, edges=streams.edges)
    assert code == 1
    assert "vocatron make" in streams.out.getvalue()
    assert world.renderer.requests == []


def test_force_renders_again_even_when_nothing_changed(world: FakeWorld) -> None:
    make(world)
    streams = Streams(world)
    assert run_render(MUSIC, output=None, config_file=None, force=True, edges=streams.edges) == 0
    assert len(world.renderer.requests) == 2
    assert len(world.acoustic.requests) == 1  # force reaches only the stages render runs


def test_the_command_line_has_the_profile_and_preset_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[bool, Overrides]] = []

    def fake_run_render(path: Path, **kwargs: object) -> int:
        overrides = kwargs["overrides"]
        assert isinstance(overrides, Overrides)
        seen.append((bool(kwargs["force"]), overrides))
        return 0

    monkeypatch.setattr(app_module, "run_render", fake_run_render)
    for argv in (
        ["render", "x.mp3", "--profile", "mine.yaml", "--preset", "16x9-720", "--force"],
        ["render", "x.mp3"],
    ):
        with pytest.raises(SystemExit) as stop:
            app(argv)
        assert stop.value.code == 0
    assert seen == [(True, Overrides(profile="mine.yaml", preset="16x9-720")), (False, Overrides())]


def test_the_video_settings_of_the_file_are_read(world: FakeWorld) -> None:
    world.store.add(
        Path("/work/vocatron.yaml"),
        b"profile: two-line-turns\nprofile_overrides:\n  font: {size: 0.1}\npreset: 16x9-720\n"
        b"audio:\n  encoder: ffmpeg-aac\n  bitrate: 128\n  export: none\n",
    )
    config = load_config(world.store, None, Path("/work"))
    assert config.profile == "two-line-turns"
    assert config.profile_overrides == {"font": {"size": 0.1}}
    assert (config.preset, config.audio.encoder, config.audio.bitrate) == (
        "16x9-720",
        "ffmpeg-aac",
        128,
    )


def test_a_wrong_preset_in_the_file_is_an_error_at_that_key(world: FakeWorld) -> None:
    world.store.add(Path("/work/vocatron.yaml"), b"preset: 8k\n")
    with pytest.raises(ConfigError) as error:
        load_config(world.store, None, Path("/work"))
    assert "vocatron.yaml:1:1: preset" in error.value.messages[0]


def test_a_profile_file_is_relative_to_the_file_that_names_it_and_a_built_in_name_stays(
    world: FakeWorld,
) -> None:
    world.store.add(Path("/conf/vocatron.yaml"), b"profile: looks/mine.yaml\n")
    config = load_config(world.store, Path("/conf/vocatron.yaml"), Path("/"))
    assert config.profile == "/conf/looks/mine.yaml"
    world.store.add(Path("/conf/builtin.yaml"), b"profile: two-line-turns\n")
    assert (
        load_config(world.store, Path("/conf/builtin.yaml"), Path("/")).profile == "two-line-turns"
    )


def test_a_profile_option_is_relative_to_the_current_folder(world: FakeWorld) -> None:
    config = load_config(world.store, None, Path("/work"), overrides=Overrides(profile="mine.yaml"))
    assert config.profile == "/work/mine.yaml"
    named = load_config(
        world.store, None, Path("/work"), overrides=Overrides(profile="two-line-turns")
    )
    assert named.profile == "two-line-turns"
