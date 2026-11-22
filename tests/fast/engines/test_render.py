"""Stage 1: the real renderer with the programs replaced by canned runs (ADR-0009).

The real ffmpeg and fdkaac run in stage 2; here every subprocess call is recorded and answered.
"""

import io
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from fakes.mp4 import FTYP, mp4_file, stco, trak
from vocatron.core.errors import StageError
from vocatron.core.font_check import BUNDLED_FACE
from vocatron.core.id3 import id3_tag
from vocatron.core.mp4_tags import read_tags
from vocatron.core.presets import PRESETS, AudioSettings
from vocatron.engines import child as child_module
from vocatron.engines import render as render_module
from vocatron.engines.protocols import Mp3Request, RenderRequest, Watch
from vocatron.engines.render import FfmpegRenderer
from vocatron.engines.resources import PackageResources

GOOD_LOG = f"fontselect: (Noto Sans, 700, 0) -> {BUNDLED_FACE}, 0, {BUNDLED_FACE}\n"
BAD_LOG = "fontselect: (Noto Sans, 700, 0) -> /x/DejaVuSans-Bold.ttf, 0, DejaVuSans-Bold\n"
ASS = "PlayResX: 960\nPlayResY: 720\nDialogue: 0,0:00:00.00,0:00:05.00,s,,0,0,0,,{\\an7}Titel\n"


class Recorder:
    """Stands in for ``subprocess.Popen``: records commands, writes the outputs."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.commands: list[tuple[str, ...]] = []
        self.log = GOOD_LOG
        self.progress = b""  # what ffmpeg says on its standard output
        self.fail: str | None = None  # the program that fails, or "video" for the video only
        self.missing: str | None = None  # the program that is not installed
        self.timeout: str | None = None
        self.killed: list[str] = []
        self.video: bytes | None = None  # what ffmpeg writes as the video; a fast-start MP4


FAKE_PID = 999_999_999  # no real process: its group is never signalled (see ``recorder``)


class FakeProcess:
    """A program that has run: ``wait`` finishes a single command, ``communicate`` a piped one."""

    def __init__(self, recorder: Recorder, command: tuple[str, ...]) -> None:
        if command[0] == recorder.missing:
            raise FileNotFoundError(2, "no such file", command[0])
        self.recorder = recorder
        self.command = tuple(command)
        self.stdout = io.BytesIO(recorder.progress if "-progress" in command else b"wav")
        self.stderr = io.BytesIO(recorder.log.encode())
        self.returncode = 0
        self.pid = FAKE_PID
        recorder.commands.append(self.command)

    def __enter__(self) -> FakeProcess:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def kill(self) -> None:
        self.recorder.killed.append(self.command[0])
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode == -9:  # reaping a killed program: it makes nothing
            return self.returncode
        if self.command[0] == self.recorder.timeout and timeout is not None:
            raise subprocess.TimeoutExpired(self.command, timeout or 0)
        video = self.recorder.fail == "video" and "-vf" in self.command
        self.returncode = 1 if self.command[0] == self.recorder.fail or video else 0
        made = (
            self.recorder.video or mp4_file()
            if "-vf" in self.command
            else b"made by " + self.command[0].encode()
        )
        Path(self.command[-1]).write_bytes(made)  # a part
        return self.returncode

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        if self.command[0] == self.recorder.timeout:
            raise subprocess.TimeoutExpired(self.command, timeout or 0)
        self.returncode = 1 if self.command[0] == self.recorder.fail else 0
        if self.returncode == 0 and self.command[0] == "fdkaac":
            Path(self.command[self.command.index("-o") + 1]).write_bytes(b"made by fdkaac")
        return b"", self.recorder.log.encode()


@pytest.fixture
def recorder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Recorder:
    found = Recorder(tmp_path)

    def popen(command: tuple[str, ...], **_: object) -> FakeProcess:
        return FakeProcess(found, command)

    def killpg(pid: int, signal: int) -> None:
        assert pid == FAKE_PID  # never a real process group
        del signal

    monkeypatch.setattr(render_module.subprocess, "Popen", popen)
    monkeypatch.setattr(child_module.os, "killpg", killpg)
    return found


def request(
    tmp_path: Path,
    audio: AudioSettings | None = None,
    watch: Watch | None = None,
    lead: float = 0.0,
) -> RenderRequest:
    work, output = tmp_path / "work", tmp_path / "out"
    (work / "stems").mkdir(parents=True)
    output.mkdir()
    (work / "stems" / "karaoke.flac").write_bytes(b"flac")
    (work / "lyrics.ass").write_text(ASS, encoding="utf-8")
    return RenderRequest(
        ass=work / "lyrics.ass",
        audio=work / "stems" / "karaoke.flac",
        work_dir=work,
        output_dir=output,
        name="Artist - Title",
        preset=PRESETS["4x3-720"],
        audio_settings=audio or AudioSettings(encoder="ffmpeg-aac", export="m4a"),
        background="#000000",
        duration=60.0,
        log=lambda message: None,
        watch=watch or Watch(),
        lead=lead,
    )


def test_the_mp4_gets_the_tags_from_vocatron_and_the_media_moves_with_its_index(
    tmp_path: Path, recorder: Recorder
) -> None:
    asked = replace(request(tmp_path), tags=(("title", "T"), ("tag", "Duet")))
    FfmpegRenderer(tmp_path / "fonts").render(asked)
    command = recorder.commands[1]
    assert "-metadata" not in command
    data = (tmp_path / "out" / "Artist - Title.mp4").read_bytes()
    start = data.index(b"moov") - 4
    end = start + int.from_bytes(data[start : start + 4], "big")
    assert read_tags(data[start:end]) == asked.tags
    first = data.index(b"stco") + 12  # the first chunk offset: where the media starts
    assert int.from_bytes(data[first : first + 4], "big") == data.index(b"mdat") + 4
    assert data[:start] == FTYP and data.endswith(b"media")
    assert not list((tmp_path / "out").glob("*.tagged.mp4"))


def test_an_mp4_with_the_media_before_the_index_fails_and_leaves_no_video(
    tmp_path: Path, recorder: Recorder
) -> None:
    recorder.video = FTYP + b"\x00\x00\x00\x0cmdat1234" + trak(stco([1]))
    with pytest.raises(StageError, match="not fast start") as error:
        FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path))
    assert error.value.kind == "render-failed"
    assert list((tmp_path / "out").iterdir()) == []


def test_the_audio_is_encoded_once_then_copied_into_the_video(
    tmp_path: Path, recorder: Recorder
) -> None:
    result = FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path))
    assert [c[0] for c in recorder.commands] == ["ffmpeg", "ffmpeg"]
    assert "aac" in recorder.commands[0]
    assert recorder.commands[1][recorder.commands[1].index("-c:a") + 1] == "copy"
    assert result.files == ("Artist - Title.mp4", "Artist - Title.m4a")
    assert result.fonts == (BUNDLED_FACE,)
    assert (tmp_path / "out" / "Artist - Title.mp4").is_file()
    assert not (tmp_path / "out" / "Artist - Title.part.mp4").exists()  # renamed when finished


def test_the_m4a_export_is_the_encoded_audio_not_a_second_encode(
    tmp_path: Path, recorder: Recorder
) -> None:
    FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path))
    assert (tmp_path / "out" / "Artist - Title.m4a").read_bytes() == (
        tmp_path / "work" / "audio.m4a"
    ).read_bytes()
    assert len([c for c in recorder.commands if "aac" in c]) == 1


def test_the_flac_export_copies_the_lossless_karaoke_audio(
    tmp_path: Path, recorder: Recorder
) -> None:
    audio = AudioSettings(encoder="ffmpeg-aac", export="flac")
    result = FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path, audio))
    assert result.files == ("Artist - Title.mp4", "Artist - Title.flac")
    assert (tmp_path / "out" / "Artist - Title.flac").read_bytes() == b"flac"


def test_no_export_leaves_only_the_video(tmp_path: Path, recorder: Recorder) -> None:
    audio = AudioSettings(encoder="ffmpeg-aac", export="none")
    assert FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path, audio)).files == (
        "Artist - Title.mp4",
    )
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["Artist - Title.mp4"]


def test_a_font_other_than_the_bundled_one_fails_and_leaves_no_video(
    tmp_path: Path, recorder: Recorder
) -> None:
    recorder.log = BAD_LOG
    with pytest.raises(StageError, match="DejaVuSans-Bold") as error:
        FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path))
    assert error.value.kind == "wrong-font"
    assert list((tmp_path / "out").iterdir()) == []


@pytest.mark.parametrize("program", ["ffmpeg", "fdkaac"])
def test_a_program_that_is_not_installed_is_named(
    tmp_path: Path, recorder: Recorder, program: str
) -> None:
    recorder.missing = program
    audio = AudioSettings(encoder="ffmpeg-aac" if program == "ffmpeg" else "fdkaac")
    if program == "fdkaac":
        recorder.missing = "fdkaac"
    with pytest.raises(StageError, match=program) as error:
        FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path, audio))
    assert error.value.kind == "missing-tool"


def test_a_failing_program_gives_the_end_of_what_it_said(
    tmp_path: Path, recorder: Recorder
) -> None:
    recorder.fail = "ffmpeg"
    recorder.log = "x" * 5000 + "the real reason"
    with pytest.raises(StageError, match="the real reason") as error:
        FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path))
    assert error.value.kind == "render-failed"
    assert len(str(error.value)) < 1000


def test_a_program_that_takes_too_long_is_stopped(tmp_path: Path, recorder: Recorder) -> None:
    recorder.timeout = "ffmpeg"
    with pytest.raises(StageError, match="took longer") as error:
        FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path))
    assert error.value.kind == "render-timeout"


def test_fdkaac_encodes_what_ffmpeg_decodes_through_a_pipe(
    tmp_path: Path, recorder: Recorder
) -> None:
    result = FfmpegRenderer(tmp_path / "fonts").render(
        request(tmp_path, AudioSettings(export="m4a"))
    )
    assert [c[0] for c in recorder.commands] == ["ffmpeg", "fdkaac", "ffmpeg"]
    assert result.audio_encoder == "fdkaac"
    assert (tmp_path / "out" / "Artist - Title.m4a").read_bytes() == b"made by fdkaac"


def test_a_failing_fdkaac_is_named_and_stops_the_render(tmp_path: Path, recorder: Recorder) -> None:
    recorder.fail = "fdkaac"
    with pytest.raises(StageError, match="fdkaac failed"):
        FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path, AudioSettings()))
    assert [c[0] for c in recorder.commands] == ["ffmpeg", "fdkaac"]


def test_a_failing_decoder_in_the_pipe_is_named(tmp_path: Path, recorder: Recorder) -> None:
    recorder.fail = "ffmpeg"
    with pytest.raises(StageError, match="ffmpeg failed"):
        FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path, AudioSettings()))


def test_a_pipe_that_takes_too_long_is_stopped(tmp_path: Path, recorder: Recorder) -> None:
    recorder.timeout = "fdkaac"
    with pytest.raises(StageError, match="took longer"):
        FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path, AudioSettings()))
    assert sorted(recorder.killed) == ["fdkaac", "ffmpeg"]


def test_a_log_that_names_no_font_fails_when_text_was_drawn(
    tmp_path: Path, recorder: Recorder
) -> None:
    recorder.log = "libass said nothing about fonts\n"
    with pytest.raises(StageError, match="did not say") as error:
        FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path))
    assert error.value.kind == "wrong-font"
    assert list((tmp_path / "out").iterdir()) == []


def test_a_subtitle_file_without_text_needs_no_font(tmp_path: Path, recorder: Recorder) -> None:
    recorder.log = ""
    asked = request(tmp_path)
    asked.ass.write_text("PlayResX: 960\nPlayResY: 720\n", encoding="utf-8")
    assert FfmpegRenderer(tmp_path / "fonts").render(asked).fonts == ()


def test_a_failing_video_leaves_no_part_file(tmp_path: Path, recorder: Recorder) -> None:
    recorder.fail = "video"
    with pytest.raises(StageError, match="ffmpeg failed"):
        FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path))
    assert list((tmp_path / "out").iterdir()) == []


def test_a_hanging_pipe_is_killed_when_its_time_is_up() -> None:
    sleeper = (sys.executable, "-c", "import time; time.sleep(30)")
    started = time.monotonic()
    with pytest.raises(StageError, match="took longer") as error:
        render_module._pipe(sleeper, sleeper, 0.3)  # real processes: no recorder here
    assert error.value.kind == "render-timeout"
    assert time.monotonic() - started < 10


def test_the_video_reports_how_far_ffmpeg_is_and_the_audio_encode_asks_for_no_progress(
    tmp_path: Path, recorder: Recorder
) -> None:
    recorder.progress = b"frame=3\nout_time_us=N/A\nout_time_us=15000000\nout_time_us=60000000\n"
    heard: list[float] = []
    FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path, watch=Watch(progress=heard.append)))
    audio, video = recorder.commands
    assert "-progress" not in audio
    assert video[1:4] == ("-progress", "pipe:1", "-nostats")
    assert heard == [0.25, 1.0]


def test_the_time_left_of_the_song_ends_a_program_with_the_time_limit_error(
    tmp_path: Path, recorder: Recorder
) -> None:
    recorder.timeout = "ffmpeg"
    with pytest.raises(StageError, match="time limit of this song") as error:
        FfmpegRenderer(tmp_path / "fonts").render(
            request(tmp_path, watch=Watch(time_left=lambda: 5.0))
        )
    assert error.value.kind == "time-limit"
    assert recorder.killed == ["ffmpeg"]


def test_a_second_ctrl_c_kills_the_program_it_waits_for(
    tmp_path: Path, recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(self: FakeProcess, timeout: float | None = None) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(FakeProcess, "wait", interrupted)
    with pytest.raises(KeyboardInterrupt):
        FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path))
    assert recorder.killed == ["ffmpeg"]


def test_a_pipe_that_runs_into_the_time_limit_of_the_song_says_so(
    tmp_path: Path, recorder: Recorder
) -> None:
    recorder.timeout = "fdkaac"
    with pytest.raises(StageError, match="time limit of this song") as error:
        FfmpegRenderer(tmp_path / "fonts").render(
            request(tmp_path, AudioSettings(), Watch(time_left=lambda: 3.0))
        )
    assert error.value.kind == "time-limit"


def test_the_lead_delays_the_audio_once_and_the_video_copies_it(
    tmp_path: Path, recorder: Recorder
) -> None:
    FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path, lead=4.5))
    delayed = [c for c in recorder.commands if "adelay=4500:all=1" in c]
    assert len(delayed) == 1
    assert "aac" in delayed[0]
    assert recorder.commands[1][recorder.commands[1].index("-c:a") + 1] == "copy"


def test_without_a_lead_no_command_delays_anything(tmp_path: Path, recorder: Recorder) -> None:
    audio = AudioSettings(encoder="ffmpeg-aac", export="flac")
    FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path, audio))
    assert not [c for c in recorder.commands if any("adelay" in part for part in c)]


def test_the_flac_export_with_a_lead_is_encoded_with_the_silence_in_front(
    tmp_path: Path, recorder: Recorder
) -> None:
    audio = AudioSettings(encoder="ffmpeg-aac", export="flac")
    result = FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path, audio, lead=6.0))
    assert result.files == ("Artist - Title.mp4", "Artist - Title.flac")
    flac = recorder.commands[-1]
    assert flac[flac.index("-c:a") + 1] == "flac"
    assert flac[-1] == str(tmp_path / "out" / "Artist - Title.flac")
    assert "adelay=6000:all=1" in flac
    assert (tmp_path / "out" / "Artist - Title.flac").read_bytes() == b"made by ffmpeg"


def test_the_m4a_export_with_a_lead_is_still_the_one_encoded_audio(
    tmp_path: Path, recorder: Recorder
) -> None:
    FfmpegRenderer(tmp_path / "fonts").render(request(tmp_path, lead=6.0))
    assert len([c for c in recorder.commands if "aac" in c]) == 1
    assert (tmp_path / "out" / "Artist - Title.m4a").read_bytes() == (
        tmp_path / "work" / "audio.m4a"
    ).read_bytes()


TAGS = (("title", "Title"), ("artist", "Artist"), ("comment", "Hi"))


def mp3_request(tmp_path: Path, lead: float = 4.5) -> Mp3Request:
    work, output = tmp_path / "work", tmp_path / "out"
    (work / "stems").mkdir(parents=True)
    output.mkdir()
    (work / "stems" / "karaoke.flac").write_bytes(b"flac")
    return Mp3Request(
        source=work / "stems" / "karaoke.flac",
        target=output / "Artist - Title.mp3",
        lead=lead,
        duration=60.0,
        log=lambda message: None,
        tags=TAGS,
    )


def test_the_mp3_is_one_lame_run_into_a_part_file_that_is_renamed(
    tmp_path: Path, recorder: Recorder
) -> None:
    asked = mp3_request(tmp_path)
    FfmpegRenderer(tmp_path / "fonts").encode_mp3(asked)
    (command,) = recorder.commands
    assert command[command.index("-c:a") + 1] == "libmp3lame"
    assert command[command.index("-af") + 1] == "adelay=4500:all=1"
    assert command[-1].endswith("Artist - Title.part.mp3")
    assert "-metadata" not in command
    assert asked.target.read_bytes() == id3_tag(TAGS) + b"made by ffmpeg"
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["Artist - Title.mp3"]


def test_an_unwritable_tag_leaves_no_partial_file(tmp_path: Path, recorder: Recorder) -> None:
    asked = replace(mp3_request(tmp_path), tags=(("album", "x"),))
    with pytest.raises(ValueError, match="album"):
        FfmpegRenderer(tmp_path / "fonts").encode_mp3(asked)
    assert list((tmp_path / "out").iterdir()) == []


def test_a_failing_mp3_run_leaves_no_part_file(tmp_path: Path, recorder: Recorder) -> None:
    recorder.fail = "ffmpeg"
    recorder.log = "something broke"
    with pytest.raises(StageError, match="something broke") as error:
        FfmpegRenderer(tmp_path / "fonts").encode_mp3(mp3_request(tmp_path))
    assert error.value.kind == "render-failed"
    assert list((tmp_path / "out").iterdir()) == []


def test_an_ffmpeg_without_lame_says_so(tmp_path: Path, recorder: Recorder) -> None:
    recorder.fail = "ffmpeg"
    recorder.log = "Unknown encoder 'libmp3lame'"
    with pytest.raises(StageError, match="no MP3 encoder") as error:
        FfmpegRenderer(tmp_path / "fonts").encode_mp3(mp3_request(tmp_path))
    assert error.value.kind == "missing-tool"


def test_a_missing_ffmpeg_and_a_timeout_are_named_for_the_mp3_too(
    tmp_path: Path, recorder: Recorder
) -> None:
    recorder.missing = "ffmpeg"
    with pytest.raises(StageError, match="ffmpeg is not installed"):
        FfmpegRenderer(tmp_path / "fonts").encode_mp3(mp3_request(tmp_path))
    recorder.missing, recorder.timeout = None, "ffmpeg"
    with pytest.raises(StageError, match="took longer"):
        FfmpegRenderer(tmp_path / "fonts").encode_mp3(mp3_request(tmp_path / "again"))


def test_the_wrong_font_message_names_the_characters_the_bundled_font_lacks(
    tmp_path: Path, recorder: Recorder
) -> None:
    recorder.log = BAD_LOG
    asked = request(tmp_path)
    asked.ass.write_text(ASS.replace("Titel", "Titel √"), encoding="utf-8")
    with pytest.raises(StageError) as error:
        FfmpegRenderer(PackageResources().fonts_dir()).render(asked)
    assert error.value.kind == "wrong-font"
    assert "the font cannot draw U+221A SQUARE ROOT" in str(error.value)
