"""Stage 1 tests for the command line entry point."""

import inspect
import runpy
from importlib.metadata import version
from pathlib import Path

import pytest

from fakes.songs import FakeWorld
from fakes.streams import Streams
from vocatron.cli import app as app_module
from vocatron.cli.app import app, main, overview
from vocatron.cli.commands import run_make, run_render
from vocatron.cli.config_file import Overrides


def run(argv: list[str]) -> int:
    """Run the app on ``argv`` and return its exit code."""
    with pytest.raises(SystemExit) as exit_info:
        app(argv)
    code = exit_info.value.code
    assert isinstance(code, int)
    return code


def test_version_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(["--version"]) == 0
    assert capsys.readouterr().out.strip() == version("vocatron")


def test_help_comes_from_the_docstring(capsys: pytest.CaptureFixture[str]) -> None:
    docstring = inspect.getdoc(overview)
    assert docstring is not None
    assert run(["--help"]) == 0
    out = capsys.readouterr().out
    assert docstring.splitlines()[0] in out


def test_without_a_command_the_help_is_shown(capsys: pytest.CaptureFixture[str]) -> None:
    app([], result_action="return_value")
    assert "Usage: vocatron" in capsys.readouterr().out


def test_main_passes_the_process_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["vocatron", "--version"])
    with pytest.raises(SystemExit):
        main()
    assert capsys.readouterr().out.strip() == version("vocatron")


def test_module_entry_point_runs_the_app(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["vocatron", "--version"])
    with pytest.raises(SystemExit):
        runpy.run_module("vocatron", run_name="__main__")
    assert capsys.readouterr().out.strip() == version("vocatron")


def test_make_and_render_share_the_profile_and_preset_options(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in ("profile", "preset"):
        shared = getattr(app_module, name.capitalize())
        for command in (app_module.make, app_module.render):
            assert inspect.signature(command).parameters[name].annotation is shared
    for command in ("make", "render"):
        assert run([command, "--help"]) == 0
        out = " ".join(capsys.readouterr().out.replace("│", " ").split())
        assert "Style profile: a built-in name or a YAML file" in out
        assert "Output preset, for example 4x3-720" in out


def test_make_passes_look_preset_and_cdg_on_as_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[Overrides] = []

    def fake_run_make(*_: object, overrides: Overrides, **__: object) -> int:
        seen.append(overrides)
        return 0

    monkeypatch.setattr(app_module, "run_make", fake_run_make)
    song = str(tmp_path / "a.mp3")
    assert run(["make", song, "--profile", "two-line-turns", "--preset", "16x9-720", "--cdg"]) == 0
    assert (seen[0].profile, seen[0].preset, seen[0].cdg) == ("two-line-turns", "16x9-720", True)
    assert run(["make", song]) == 0
    assert (seen[1].profile, seen[1].preset, seen[1].cdg) == (None, None, False)


def test_make_rejects_an_unknown_preset_like_render(world: FakeWorld) -> None:
    world.add_song(Path("/music/a.mp3"))
    for kind in ("make", "render"):
        streams = Streams(world)
        overrides = Overrides(preset="nope")
        if kind == "make":
            code = run_make(
                Path("/music"),
                output=None,
                config_file=None,
                overrides=overrides,
                edges=streams.edges,
            )
        else:
            code = run_render(
                Path("/music"),
                output=None,
                config_file=None,
                force=False,
                overrides=overrides,
                edges=streams.edges,
            )
        assert code != 0
        assert "--preset" in streams.err.getvalue()
