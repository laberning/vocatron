"""The real renderer: fdkaac or ffmpeg for the audio, ffmpeg with libass for the video (ADR-0009).

The karaoke audio is encoded once to M4A, the lyrics are burnt onto a plain background, and the
audio is copied into the MP4 unchanged. ffmpeg writes no tags; Vocatron puts them into the MP4
afterwards (ADR-0047). The M4A is kept as the audio export. After the video is
made the log of libass is read: every font it chose must be the bundled one, else the run fails
(libass replaces a font it cannot find without a word).
"""

import shutil
import subprocess
import time
from pathlib import Path

from vocatron.core.ass.parse import parse_ass
from vocatron.core.errors import StageError
from vocatron.core.ffmpeg_cmd import (
    Command,
    audio_job,
    flac_export_command,
    mp3_command,
    parse_progress,
    video_command,
    with_progress,
)
from vocatron.core.font_check import font_characters, font_problems, fonts_used
from vocatron.core.id3 import id3_tag
from vocatron.core.mp4_tags import (
    LARGE_HEADER,
    Mp4Box,
    Mp4Error,
    locate_moov,
    read_header,
    retag_moov,
)
from vocatron.core.song import MediaTags
from vocatron.core.worker import effective_limit
from vocatron.engines.child import kill, run_child
from vocatron.engines.protocols import Mp3Request, RenderRequest, RenderResult, Watch
from vocatron.engines.resources import FONT_FILE

BASE_TIMEOUT = 120.0  # seconds added to every limit
AUDIO_FACTOR = 2.0  # the audio may take this many song lengths
VIDEO_FACTOR = 4.0  # the video may take this many song lengths (it should be about real time)
DEFAULT_DURATION = 600.0  # seconds, when the length is not known
TAIL = 600  # characters of a program's error output shown in a message


def _missing(program: str) -> StageError:
    """Return the error for a program that is not installed."""
    return StageError(
        "missing-tool", f"{program} is not installed or not on PATH; run 'vocatron doctor'"
    )


def _failed(program: str, output: bytes | str) -> StageError:
    """Return the error for a program that failed, with the end of what it said."""
    text = output if isinstance(output, str) else output.decode(errors="replace")
    return StageError("render-failed", f"{program} failed: {text.strip()[-TAIL:]}")


def _timed_out(what: str, limit: float, by_song: bool) -> StageError:
    """Return the error for work that ran out of time: the song's limit, or the step's own."""
    if by_song:
        return StageError(
            "time-limit",
            f"the time limit of this song ran out while {what} was running; it was stopped",
        )
    return StageError("render-timeout", f"{what} took longer than {limit:.0f} s")


def _run(command: Command, timeout: float, watch: Watch | None = None, seconds: float = 0.0) -> str:
    """Run one command and return its error output (ffmpeg logs there).

    The command runs in a session of its own, so only the first Ctrl-C of the terminal stops
    the batch politely; a second one kills it here.

    Args:
        command: The program and its arguments.
        timeout: How long it may run.
        watch: Gets the progress ffmpeg reports (with ``seconds`` as the length of the output)
            and says how long the song may still take.
        seconds: The length of the output, to turn ffmpeg's time into a fraction.

    Raises:
        StageError: If the program is missing, fails or runs out of time.
    """
    watch = watch or Watch()
    reported = with_progress(command) if seconds > 0 else command

    def progress(line: str) -> None:
        if (fraction := parse_progress(line, seconds)) is not None:
            watch.progress(fraction)

    bound, by_song = effective_limit(timeout, watch.time_left())
    try:
        ended = run_child(reported, bound, progress)
    except FileNotFoundError as error:
        raise _missing(command[0]) from error
    except subprocess.TimeoutExpired:
        raise _timed_out(command[0], bound, by_song) from None
    if ended.code != 0:
        raise _failed(command[0], ended.errors)
    return ended.errors


def _pipe(decode: Command, encode: Command, timeout: float, watch: Watch | None = None) -> None:
    """Run ``decode`` and feed its output to ``encode``.

    Raises:
        StageError: If either program is missing, fails or runs out of time.
    """
    bound, by_song = effective_limit(timeout, (watch or Watch()).time_left())
    try:
        with (
            subprocess.Popen(
                decode, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
            ) as reader,
            subprocess.Popen(
                encode,
                stdin=reader.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            ) as writer,
        ):
            if reader.stdout is not None:
                reader.stdout.close()  # so the reader gets SIGPIPE if the writer dies
            try:
                _, encode_error = writer.communicate(timeout=bound)
                _, decode_error = reader.communicate(timeout=bound)
            except BaseException:  # a timeout or a second Ctrl-C: leave no process behind
                kill(writer)
                kill(reader)
                raise
    except FileNotFoundError as error:
        raise _missing(Path(str(error.filename)).name) from error
    except subprocess.TimeoutExpired as error:
        raise _timed_out("encoding", bound, by_song) from error
    if writer.returncode != 0:
        raise _failed(encode[0], encode_error)
    if reader.returncode != 0:
        raise _failed(decode[0], decode_error)


class FfmpegRenderer:
    """Renders with the programs on ``PATH``; the font folder is the bundled one."""

    def __init__(self, fonts_dir: Path) -> None:
        """Remember the folder with the bundled font."""
        self._fonts = fonts_dir

    def _font_message(self, log: str, text: str) -> str:
        """Return why libass did not draw with the bundled font, naming the characters it lacks."""
        try:
            drawable = font_characters((self._fonts / FONT_FILE).read_bytes())
        except OSError, ValueError:  # the message is still true without the characters
            drawable = None
        return font_problems(log, text_drawn=bool(text), text=text, drawable=drawable)[0]

    def _encode_audio(self, request: RenderRequest, limit: float) -> Path:
        """Encode the karaoke audio once into the work folder and return that M4A file."""
        target = request.work_dir / "audio.m4a"
        job = audio_job(request.audio_settings, request.preset, request.audio, target, request.lead)
        request.log(f"render: encoding the audio with {request.audio_settings.encoder}")
        if len(job.commands) == 1:
            _run(job.commands[0], limit, request.watch)
        else:
            _pipe(job.commands[0], job.commands[1], limit, request.watch)
        return target

    @staticmethod
    def _write_tags(video: Path, tags: MediaTags) -> None:
        """Replace the tags in the MP4 ``video`` with ``tags`` (ADR-0047).

        ffmpeg writes none. The file is copied unchanged except for ``moov``, which comes right
        after ``ftyp`` in a fast-start file and gets the tags and the shifted chunk offsets
        (``core.mp4_tags``).

        Raises:
            StageError: ``render-failed`` if the MP4 is not built as expected or a tag cannot be
                written.
        """
        tagged = video.with_name(f"{video.stem}.tagged.mp4")
        try:
            with video.open("rb") as source, tagged.open("wb") as out:
                size = video.stat().st_size
                boxes: list[Mp4Box] = []
                position = 0
                while position < size:
                    source.seek(position)
                    kind, _, length = read_header(source.read(LARGE_HEADER), size - position)
                    boxes.append(Mp4Box(kind, position, length))
                    position += length
                moov = locate_moov(boxes)
                source.seek(0)
                out.write(source.read(moov.start))
                source.seek(moov.start)
                out.write(retag_moov(source.read(moov.size), tags))
                shutil.copyfileobj(source, out)
            tagged.replace(video)
        except Mp4Error as error:
            raise StageError(
                "render-failed", f"the tags cannot be written into the MP4: {error}"
            ) from error
        finally:
            tagged.unlink(missing_ok=True)

    def render(self, request: RenderRequest) -> RenderResult:
        """Encode the audio, burn in the lyrics, copy the audio in and write the export.

        Raises:
            StageError: ``missing-tool``, ``render-failed``, ``render-timeout`` or ``wrong-font``.
        """
        started = time.monotonic()
        length = request.duration or DEFAULT_DURATION
        audio = self._encode_audio(request, BASE_TIMEOUT + AUDIO_FACTOR * length)
        video = request.output_dir / f"{request.name}.mp4"
        partial = video.with_name(f"{request.name}.part.mp4")
        command = video_command(
            request.preset,
            request.background,
            request.ass,
            self._fonts,
            audio,
            partial,
            motion=request.motion,
        )
        request.log(f"render: {request.preset.name} with {request.preset.codec}")
        try:
            log = _run(command, BASE_TIMEOUT + VIDEO_FACTOR * length, request.watch, length)
        except StageError:
            partial.unlink(missing_ok=True)
            raise
        text = "".join(event.text for event in parse_ass(request.ass.read_text("utf-8")).events)
        if font_problems(log, text_drawn=bool(text)):
            partial.unlink(missing_ok=True)
            raise StageError("wrong-font", self._font_message(log, text))
        try:
            self._write_tags(partial, request.tags)
        except StageError, ValueError, OSError:
            partial.unlink(missing_ok=True)
            raise
        partial.replace(video)
        files = [video.name, *self._export(request, audio, BASE_TIMEOUT + AUDIO_FACTOR * length)]
        return RenderResult(
            files=tuple(files),
            seconds=time.monotonic() - started,
            audio_encoder=request.audio_settings.encoder,
            fonts=tuple(dict.fromkeys(fonts_used(log))),
        )

    def encode_mp3(self, request: Mp3Request) -> None:
        """Encode the karaoke audio with LAME, with the silent intro in front (ADR-0024).

        ffmpeg writes the audio without a tag; the ID3 tag of ``request.tags`` is written in
        front of it here (ADR-0035).

        Raises:
            StageError: ``missing-tool`` (also for an ffmpeg without libmp3lame),
                ``render-failed`` or ``render-timeout``.
        """
        partial = request.target.with_name(f"{request.target.stem}.part.mp3")
        length = request.duration or DEFAULT_DURATION
        request.log("cdg: encoding the MP3 with libmp3lame")
        try:
            _run(
                mp3_command(request.source, partial, request.lead),
                BASE_TIMEOUT + AUDIO_FACTOR * length,
                request.watch,
                length,
            )
        except StageError as error:
            partial.unlink(missing_ok=True)
            if "libmp3lame" in str(error):
                raise StageError(
                    "missing-tool",
                    "this ffmpeg has no MP3 encoder (libmp3lame), which CD+G needs; "
                    "run 'vocatron doctor'",
                ) from error
            raise
        tagged = request.target.with_name(f"{request.target.stem}.tagged.mp3")
        try:
            with tagged.open("wb") as out, partial.open("rb") as audio:
                out.write(id3_tag(request.tags))
                shutil.copyfileobj(audio, out)
            tagged.replace(request.target)
        finally:
            partial.unlink(missing_ok=True)
            tagged.unlink(missing_ok=True)

    @staticmethod
    def _export(request: RenderRequest, audio: Path, limit: float) -> list[str]:
        """Write the audio export next to the video; return its name (none for ``none``).

        The M4A is the encoded audio, which already has the lead. The FLAC is the lossless
        karaoke audio: copied, or encoded again with the silence in front when there is a lead.
        """
        export = request.audio_settings.export
        if export == "none":
            return []
        suffix = ".m4a" if export == "m4a" else ".flac"
        target = request.output_dir / f"{request.name}{suffix}"
        if export == "m4a":
            shutil.copyfile(audio, target)
        elif request.lead > 0:
            _run(flac_export_command(request.audio, target, request.lead), limit, request.watch)
        else:
            shutil.copyfile(request.audio, target)
        return [target.name]
