"""Stage 1: ``make`` with the separation options, and a failing song in a folder, on fakes."""

from pathlib import Path

import pytest

from fakes.songs import FakeWorld
from fakes.streams import Streams
from vocatron.cli import app as app_module
from vocatron.cli.app import app
from vocatron.cli.commands import run_make
from vocatron.cli.config_file import Overrides
from vocatron.core.errors import StageError

MUSIC = Path("/music")


def test_no_backing_and_device_options_reach_the_separator(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    streams = Streams(world)
    overrides = Overrides(keep_backing=False, device="cpu")
    code = run_make(MUSIC, output=None, config_file=None, overrides=overrides, edges=streams.edges)
    assert code == 0
    (request,) = world.separator.requests
    assert (request.plan.keep_backing, request.device) == (False, "cpu")


def test_a_wrong_device_option_is_a_usage_error(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    streams = Streams(world)
    code = run_make(
        MUSIC, output=None, config_file=None, overrides=Overrides(device="tpu"), edges=streams.edges
    )
    assert code == 2
    assert "--device" in streams.err.getvalue()


def test_the_separation_section_of_the_file_is_read(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    world.store.add(
        Path("/work/vocatron.yaml"), b"separation:\n  keep_backing: false\n  device: cpu\n"
    )
    streams = Streams(world)
    assert run_make(MUSIC, output=None, config_file=None, edges=streams.edges) == 0
    (request,) = world.separator.requests
    assert (request.plan.keep_backing, request.device) == (False, "cpu")


def test_an_unknown_vocals_model_in_the_file_is_an_error_at_that_key(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    world.store.add(Path("/work/vocatron.yaml"), b"separation:\n  model: wav2vec2-de\n")
    streams = Streams(world)
    assert run_make(MUSIC, output=None, config_file=None, edges=streams.edges) == 2
    assert "vocatron.yaml:2:3: separation.model" in streams.err.getvalue()
    assert "is not a vocals model" in streams.err.getvalue()


def test_a_song_that_runs_out_of_memory_fails_alone_and_the_next_is_made(world: FakeWorld) -> None:
    world.add_song(MUSIC / "a.mp3")
    world.add_song(MUSIC / "b.mp3")
    world.separator.fail_for[MUSIC / "a.mp3"] = StageError("out-of-memory", "the GPU ran out")
    streams = Streams(world)
    assert run_make(MUSIC, output=None, config_file=None, edges=streams.edges) == 1
    out = streams.out.getvalue()
    assert "separation: the GPU ran out" in out
    assert "2 songs: 1 ok, 0 review, 1 failed" in out
    assert len(world.separator.requests) == 2


def test_the_command_line_has_no_backing_and_device_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Overrides] = []

    def fake_run_make(path: Path, **kwargs: object) -> int:
        overrides = kwargs["overrides"]
        assert isinstance(overrides, Overrides)
        seen.append(overrides)
        return 0

    monkeypatch.setattr(app_module, "run_make", fake_run_make)
    for argv in (["make", "x.mp3", "--no-backing", "--device", "cuda"], ["make", "x.mp3"]):
        with pytest.raises(SystemExit) as stop:
            app(argv)
        assert stop.value.code == 0
    assert seen == [Overrides(keep_backing=False, device="cuda"), Overrides()]
