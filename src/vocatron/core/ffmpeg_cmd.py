"""The command lines of ffmpeg and fdkaac as pure functions (ADR-0002, ADR-0009).

Nothing here runs a program; the renderer (``vocatron.engines.render``) does. Keeping the
arguments in pure functions lets golden tests pin them: the same song and settings give the same
files on every machine, so a change of an argument is a deliberate act.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath

from vocatron.core.presets import AudioSettings, Preset, audio_bitrate
from vocatron.core.scene import BackgroundMotion

type Command = tuple[str, ...]

KBIT = 1000  # bits per second in a kbit/s
MILLI = 1000  # milliseconds in a second
COLOUR_FILTER = (
    "scale=in_color_matrix=bt601:in_range=tv:out_color_matrix=bt709:out_range=tv,"
    "format=yuv420p,"
    "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
)
"""Turns the frames, which libass has drawn on the untagged background in BT.601 (what ffmpeg
assumes for an untagged source), into BT.709 with limited range, and marks them so."""
COLOUR_TAGS = (
    "-colorspace", "bt709", "-color_primaries", "bt709",
    "-color_trc", "bt709", "-color_range", "tv",
)  # fmt: skip
"""What the encoder writes into the video, so every player shows the colours alike."""


@dataclass(frozen=True)
class AudioJob:
    """How the karaoke audio is encoded: one program, or a decoder piped into ``fdkaac``.

    Attributes:
        commands: One command (``ffmpeg-aac``) or two (``ffmpeg`` decoding to WAV on its standard
            output, ``fdkaac`` reading it from its standard input).
    """

    commands: tuple[Command, ...]


def _escape_option(value: str) -> str:
    """Escape backslash, quote and colon for the option level of an ffmpeg filter."""
    return re.sub(r"([\\':])", r"\\\1", value)


def _escape_graph(value: str) -> str:
    """Escape the special characters of the filtergraph level."""
    return re.sub(r"([\\',;\[\]])", r"\\\1", value)


def filter_value(path: PurePath | str) -> str:
    """Return ``path`` escaped as the value of a filter option (two levels, as ffmpeg asks)."""
    return _escape_graph(_escape_option(str(path)))


def subtitles_filter(ass: PurePath, fonts: PurePath) -> str:
    """Return the ``subtitles`` filter that draws ``ass`` with the fonts of ``fonts`` only."""
    return f"subtitles=filename={filter_value(ass)}:fontsdir={filter_value(fonts)}"


GRADIENT_SEED = 1
"""The seed of the moving background, so the same song gives the same video (ADR-0032)."""
GRADIENT_SHRINK = 2
"""The moving background is drawn at this fraction of the frame's width and height and scaled up:
a smooth gradient loses nothing, and drawing it at full size costs half of the render time."""
GRADIENT_RATE = 10
"""Frames per second the moving background is drawn at; it turns slowly, and ffmpeg repeats the
frames up to the frame rate of the video."""


def background_source(
    preset: Preset, background: str, motion: BackgroundMotion | None = None
) -> Command:
    """Return the input arguments of the background of the preset's size and frame rate.

    A plain colour, or, with ``motion``, ffmpeg's ``gradients`` source: a slowly turning gradient
    of the motion's colours, from corner to corner, drawn small and at a low frame rate and then
    scaled up to the frame and repeated up to its rate (ADR-0032).
    """
    if motion is None:
        colour = "0x" + background.removeprefix("#")
        return (
            "-f",
            "lavfi",
            "-i",
            f"color=c={colour}:s={preset.width}x{preset.height}:r={preset.fps}",
        )
    width, height = preset.width // GRADIENT_SHRINK, preset.height // GRADIENT_SHRINK
    colours = ":".join(
        f"c{index}=0x{colour.removeprefix('#')}" for index, colour in enumerate(motion.colours)
    )
    source = (
        f"gradients=s={width}x{height}:r={GRADIENT_RATE}:{colours}:nb_colors={len(motion.colours)}"
        f":speed={motion.speed:g}:x0=0:y0=0:x1={width}:y1={height}:seed={GRADIENT_SEED}"
        f",scale={preset.width}:{preset.height},fps={preset.fps}"
    )
    return ("-f", "lavfi", "-i", source)


def video_encoder_args(preset: Preset) -> Command:
    """Return the arguments of the preset's video encoder, with the colour tags."""
    quality = str(preset.quality)
    if preset.codec == "h264_nvenc":
        return (
            "-c:v", "h264_nvenc", "-preset", preset.speed, "-rc", "vbr", "-cq", quality,
            "-b:v", "0", "-pix_fmt", "yuv420p", *COLOUR_TAGS,
        )  # fmt: skip
    return (
        "-c:v", preset.codec, "-preset", preset.speed, "-crf", quality, "-pix_fmt", "yuv420p",
        *COLOUR_TAGS,
    )  # fmt: skip


def delay_args(lead: float) -> Command:
    """Return the audio filter that puts ``lead`` seconds of silence before the audio.

    Nothing for ``0``, so a song without an intro keeps the commands it always had (ADR-0020).
    """
    if lead <= 0:
        return ()
    return ("-af", f"adelay={round(lead * MILLI)}:all=1")


def flac_export_command(source: PurePath, target: PurePath, lead: float) -> Command:
    """Return the command that writes the FLAC export with ``lead`` seconds of silence before it.

    Args:
        source: The lossless karaoke audio.
        target: The FLAC file to write.
        lead: The silence to add in seconds.
    """
    return (
        "ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(source), "-vn",
        *delay_args(lead), "-c:a", "flac", str(target),
    )  # fmt: skip


MP3_BITRATE = 192
"""The bitrate of the MP3 of a CD+G pair in kbit/s (ADR-0024)."""
MP3_RATE = 44100
"""Its sample rate in Hz."""


def mp3_command(source: PurePath, target: PurePath, lead: float) -> Command:
    """Return the command that writes the MP3 of a CD+G pair with ``lead`` seconds of silence.

    LAME at 192 kbit/s, 44.1 kHz, stereo (ADR-0024), without any tag: Vocatron writes the ID3 tag
    itself (``core.id3``, ADR-0035), because ffmpeg cannot write the standard comment frame.

    Args:
        source: The lossless karaoke audio.
        target: The MP3 file to write.
        lead: The silence to add in seconds.
    """
    return (
        "ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(source), "-vn",
        *delay_args(lead), "-c:a", "libmp3lame", "-b:a", f"{MP3_BITRATE}k",
        "-ar", str(MP3_RATE), "-ac", "2",
        "-map_metadata", "-1", "-id3v2_version", "0", str(target),
    )  # fmt: skip


def audio_job(
    audio: AudioSettings, preset: Preset, source: PurePath, target: PurePath, lead: float = 0.0
) -> AudioJob:
    """Return the commands that encode ``source`` (the karaoke FLAC) once to ``target`` (M4A).

    Args:
        audio: The encoder and bitrate settings.
        preset: The output preset (it may ask for a bitrate).
        source: The lossless karaoke audio.
        target: The M4A file to write.
        lead: The silence to put before the audio in seconds (the silent intro, ADR-0020).
    """
    kbit = audio_bitrate(audio, preset)
    delay = delay_args(lead)
    if audio.encoder == "ffmpeg-aac":
        return AudioJob(
            (
                (
                    "ffmpeg",
                    "-nostdin",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(source),
                    "-vn",
                    *delay,
                    "-c:a",
                    "aac",
                    "-b:a",
                    f"{kbit}k",
                    "-movflags",
                    "+faststart",
                    str(target),
                ),
            )  # fmt: skip
        )
    decode = (
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-vn", *delay, "-f", "wav", "-",
    )  # fmt: skip
    encode = (
        "fdkaac",
        "-S",
        "-I",
        "-b",
        str(kbit * KBIT),
        "--moov-before-mdat",
        "-o",
        str(target),
        "-",
    )
    return AudioJob((decode, encode))


def video_command(  # noqa: PLR0913  # every part of the command is a different input
    preset: Preset,
    background: str,
    ass: PurePath,
    fonts: PurePath,
    audio: PurePath,
    target: PurePath,
    *,
    motion: BackgroundMotion | None = None,
) -> Command:
    """Return the ffmpeg command that burns the lyrics onto the background and adds the audio.

    The audio is copied, not encoded again. The video ends with the audio. The picture is
    converted to BT.709 with limited range and tagged so (``COLOUR_FILTER``, ``COLOUR_TAGS``).
    Nothing is copied from the inputs and ffmpeg writes no tags: Vocatron adds them afterwards
    (ADR-0047).

    Args:
        preset: The output preset.
        background: The plain background colour as ``#rrggbb``.
        ass: The subtitle file.
        fonts: The folder with the bundled font; libass looks nowhere else.
        audio: The encoded audio (M4A).
        target: The MP4 to write.
        motion: A moving gradient instead of the plain background, ``None`` for the colour.
    """
    return (
        "ffmpeg", "-nostdin", "-y", "-v", "info",
        *background_source(preset, background, motion),
        "-i", str(audio),
        "-vf", f"{subtitles_filter(ass, fonts)},{COLOUR_FILTER}",
        "-map", "0:v", "-map", "1:a",
        *video_encoder_args(preset),
        "-c:a", "copy", "-shortest", "-movflags", "+faststart", "-map_metadata", "-1", str(target),
    )  # fmt: skip


def frame_command(  # noqa: PLR0913  # every part of the command is a different input
    preset: Preset,
    background: str,
    ass: PurePath,
    fonts: PurePath,
    seconds: float,
    target: PurePath,
    *,
    motion: BackgroundMotion | None = None,
) -> Command:
    """Return the ffmpeg command that writes the one frame at ``seconds`` as an image.

    Used to check, with real libass, what the layout predicted. With ``motion`` the background is
    the moving gradient as it is ``seconds`` into the video.
    """
    return (
        "ffmpeg", "-nostdin", "-y", "-v", "info",
        *background_source(preset, background, motion),
        "-vf", subtitles_filter(ass, fonts),
        "-ss", f"{seconds:.3f}", "-frames:v", "1", str(target),
    )  # fmt: skip


def gif_command(  # noqa: PLR0913  # every part of the command is a different input
    preset: Preset,
    background: str,
    ass: PurePath,
    fonts: PurePath,
    windows: Sequence[tuple[float, float]],
    target: PurePath,
    *,
    fps: int,
    size: tuple[int, int],
    motion: BackgroundMotion | None = None,
) -> Command:
    """Return the ffmpeg command that writes the parts ``windows`` (start, length) as a GIF.

    The frames are thinned to ``fps`` and each window is cut out before the subtitles are drawn,
    so only the frames of the clip cost anything; the windows must not overlap and are joined by
    hard cuts, in the order given, and the clip starts at zero. It is scaled to ``size`` and gets
    one palette of its own (``palettegen`` and ``paletteuse`` without dithering: flat text on a
    flat background stays crisp and small). The GIF loops for ever.

    Raises:
        ValueError: If there is no window.
    """
    if not windows:
        raise ValueError("a GIF needs at least one window")
    count = len(windows)
    split = f"fps={fps},split={count}" + "".join(f"[s{i}]" for i in range(count))
    parts = [
        f"[s{i}]trim=start={start:.3f}:duration={length:.3f},{subtitles_filter(ass, fonts)},"
        f"setpts=PTS-STARTPTS[c{i}]"
        for i, (start, length) in enumerate(windows)
    ]
    joined = "".join(f"[c{i}]" for i in range(count)) + f"concat=n={count}:v=1:a=0"
    scale = f"scale={size[0]}:{size[1]}:flags=lanczos"
    graph = (
        f"{split};{';'.join(parts)};{joined},{scale},split[a][b];"
        "[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle"
    )
    total = sum(length for _, length in windows)
    return (
        "ffmpeg", "-nostdin", "-y", "-v", "info",
        *background_source(preset, background, motion),
        "-filter_complex", graph,
        "-t", f"{total:.3f}", "-loop", "0", str(target),
    )  # fmt: skip


def with_progress(command: Command) -> Command:
    """Return ``command`` with ffmpeg's machine-readable progress on its standard output."""
    return (command[0], "-progress", "pipe:1", "-nostats", *command[1:])


_OUT_TIME = re.compile(r"out_time_us=(?P<micro>\d+)")


def parse_progress(line: str, seconds: float) -> float | None:
    """Return how far ffmpeg is (0 to 1) from one line of its progress output.

    Args:
        line: One line of ``-progress`` output.
        seconds: The length of the output; the fraction is the written time over it.

    Returns:
        The fraction, or ``None`` for any line that does not say how much was written (ffmpeg
        prints ``out_time_us=N/A`` before the first frame).
    """
    match = _OUT_TIME.fullmatch(line.strip())
    if match is None or seconds <= 0:
        return None
    return min(int(match["micro"]) / 1e6 / seconds, 1.0)
