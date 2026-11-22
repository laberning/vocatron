"""Stage 1: the whole frame end to end through the command line, on the real engines."""

from pathlib import Path

import pytest

from fakes.lyrics import FakeLanguageDetector, FakeLyricsSource
from fakes.songs import write_wav
from fakes.summary import summary_line
from fakes.system import FakeSystemProbe
from vocatron.cli import app as app_module
from vocatron.cli import commands as commands_module
from vocatron.cli.app import app
from vocatron.stages import batch
from vocatron.stages.lyrics import LyricsStage
from vocatron.stages.probe import ProbeStage


@pytest.fixture(autouse=True)
def fake_lyrics_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lyrics lookup and the language detector never run for real in the fast stage."""
    monkeypatch.setattr(app_module, "LrclibSource", FakeLyricsSource)
    monkeypatch.setattr(app_module, "LinguaDetector", FakeLanguageDetector)


@pytest.fixture(autouse=True)
def private_timings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The speeds learnt from tiny test songs must not end up in the clone's ``.cache``."""
    monkeypatch.setattr(commands_module, "TIMINGS_FILE", str(tmp_path / "learnt" / "timings.json"))


@pytest.fixture(autouse=True)
def without_separation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The separation needs the big models and a GPU; its tests use fakes (see test_separation)."""
    monkeypatch.setattr(batch, "STAGES", (ProbeStage(), LyricsStage()))


def run(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as exit_info:
        app(argv)
    code = exit_info.value.code
    assert isinstance(code, int)
    return code


def test_make_status_and_a_second_make_on_generated_wav_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    songs = tmp_path / "songs"
    songs.mkdir()
    write_wav(songs / "Artist - Title.wav")
    write_wav(songs / "Artist - Title .wav", seconds=2)  # same identity: a name collision
    (songs / "notes.txt").write_text("not a song")
    monkeypatch.chdir(tmp_path)
    before = sorted(p.name for p in songs.iterdir())

    assert run(["make", str(songs)]) == 0
    first = capsys.readouterr().out
    assert "2 songs: 2 ok" in first
    output = songs / "karaoke"
    assert sorted(p.name for p in output.iterdir()) == [
        "Artist - Title",
        "Artist - Title (2)",
        "vocatron-report.txt",
    ]
    work = output / "Artist - Title"
    assert sorted(p.name for p in work.iterdir()) == [
        "log.txt",
        "lyrics.json",
        "report.json",
        "song.json",
        "status.json",
    ]
    assert sorted(p.name for p in songs.iterdir()) == sorted([*before, "karaoke"])  # only karaoke/

    assert run(["status", str(songs)]) == 0
    shown = capsys.readouterr().out.splitlines()
    assert sum(1 for line in shown if summary_line(line, "ok", "Artist - Title")) == 2

    song_json = (work / "song.json").stat().st_mtime_ns
    assert run(["make", str(songs)]) == 0
    capsys.readouterr()
    assert (work / "song.json").stat().st_mtime_ns == song_json  # skipped, not rewritten
    assert '"skipped"' in (work / "status.json").read_text()
    assert "probe: skipped" in (work / "log.txt").read_text()

    assert run(["make", str(songs), "--force"]) == 0
    assert (work / "song.json").stat().st_mtime_ns != song_json


def test_a_broken_song_gives_exit_code_one_and_a_missing_path_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "good.wav")
    write_wav(tmp_path / "short.wav", seconds=0.1)
    assert run(["make", str(tmp_path), "--output", "out"]) == 1
    assert summary_line(capsys.readouterr().out, "failed", "short")
    assert (tmp_path / "out" / "good" / "status.json").is_file()
    assert run(["make", str(tmp_path / "missing")]) == 2
    assert "does not exist" in capsys.readouterr().err
    assert run(["make", str(tmp_path), "--output", ""]) == 2
    assert "--output: " in capsys.readouterr().err
    assert run(["make", str(tmp_path), "--config", str(tmp_path)]) == 2  # a folder, not a file
    assert "cannot read" in capsys.readouterr().err
    (tmp_path / "vocatron.yaml").write_text("output:\n  folder: 3\n  nope: 1\n")
    assert run(["status", str(tmp_path)]) == 2
    assert "vocatron.yaml:3:3" in capsys.readouterr().err


def test_a_config_file_given_with_the_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    write_wav(tmp_path / "x.wav")
    (tmp_path / "other.yaml").write_text("output:\n  folder: from-config\n")
    assert run(["make", str(tmp_path / "x.wav"), "--config", "other.yaml"]) == 0
    assert (tmp_path / "from-config" / "x" / "song.json").is_file()


def test_relative_output_folders_on_the_real_engines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    songs, settings, cwd = tmp_path / "songs", tmp_path / "settings", tmp_path / "cwd"
    for folder in (songs, settings, cwd):
        folder.mkdir()
    write_wav(songs / "x.wav")
    (settings / "v.yaml").write_text("output:\n  folder: from-file\n")
    monkeypatch.chdir(cwd)
    assert run(["make", str(songs)]) == 0
    assert (songs / "karaoke" / "x" / "song.json").is_file()  # the default: next to the songs
    assert run(["make", str(songs), "--output", "out"]) == 0
    assert (cwd / "out" / "x" / "song.json").is_file()  # the option: the current folder
    assert run(["make", str(songs), "--config", str(settings / "v.yaml")]) == 0
    assert (settings / "from-file" / "x" / "song.json").is_file()  # the file: its own folder


def test_an_output_folder_that_cannot_be_created_exits_with_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    song = write_wav(tmp_path / "song.wav")
    assert run(["make", str(song), "--output", "song.wav/out"]) == 2  # below a file
    assert "cannot create the output folder" in capsys.readouterr().err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["song.txt", "song.wav"]


def test_models_doctor_and_offline_through_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vocatron.yaml").write_text("models:\n  folder: models\n")
    monkeypatch.setattr(app_module, "LocalSystemProbe", FakeSystemProbe)
    monkeypatch.setenv("COLUMNS", "400")  # long paths must not wrap

    assert run(["models"]) == 0
    listing = capsys.readouterr().out
    assert "bs-roformer-ep317" in listing
    assert f"Model folder: {tmp_path / 'models'}" in listing

    assert run(["models", "download", "nope"]) == 2
    assert "unknown model 'nope'" in capsys.readouterr().err

    assert run(["doctor", "--output", str(tmp_path / "out")]) == 1  # no models downloaded
    report = capsys.readouterr().out
    assert "✗ models" in report
    assert "✓ GPU" in report

    write_wav(tmp_path / "song.wav")
    assert run(["make", str(tmp_path / "song.wav"), "--offline"]) == 0  # probe needs no model


def test_the_clone_folder_is_the_folder_with_pyproject() -> None:
    assert (app_module.clone_folder() / "pyproject.toml").is_file()


def test_the_language_option_of_make_and_lyrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    song = write_wav(tmp_path / "song.wav")
    assert run(["lyrics", str(song), "--language", "fr"]) == 2
    assert "--language: " in capsys.readouterr().err
    assert run(["make", str(song), "--language", "xx"]) == 2
    assert not (tmp_path / "karaoke").exists()
    assert run(["lyrics", str(song), "--language", "de"]) == 0
    assert run(["make", str(song), "--language", "de"]) == 0
    lyrics = (tmp_path / "karaoke" / "song" / "lyrics.json").read_text()
    assert '"language": "de"' in lyrics
