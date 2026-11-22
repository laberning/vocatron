"""The picture of a built-in look: what it shows and when it goes stale (ADR-0019, ADR-0045).

Every look has one picture in the user docs: six moments of the English demo song, a duet, laid
out in the look and put together as a 3x2 sheet. This module holds the timing of the song
(``PictureSong``, a JSON file committed next to its lyrics) and decides the six moments;
``tools/profile_pictures.py`` draws the frames. A digest over everything the frames depend on lets
a fast test see that a picture is stale without drawing anything.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from vocatron.core.languages import LANGUAGES
from vocatron.core.layout.build import SongText
from vocatron.core.layout.rules_base import gaps, is_later_row
from vocatron.core.layout.sample import DEFAULT_PRESET, TimedSong, scene_of
from vocatron.core.lyrics.document import SingerInfo, is_single_singer
from vocatron.core.lyrics.file import LyricLine, LyricsFile
from vocatron.core.measure import TextMeasurer
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import LineElement, Scene
from vocatron.core.song import SongInfo
from vocatron.core.syllables import SyllablesFile, SyllableWord
from vocatron.core.tempo import TempoFile

PICTURE_PRESET = DEFAULT_PRESET
FRAME_WIDTH = 480  # pixels of one moment in the sheet; the sheet is three frames wide
START_SCREEN_AT = 5.0  # seconds: inside the title screen of every look
END_SCREEN_AFTER = 6.0  # seconds after the last line ends
COUNTDOWN_BEFORE = 1.0  # seconds before the first line after the longest gap
CHANGE_DELAY = 0.25  # seconds after a line or page appears that the "change" moment looks
SETTLE = 0.01  # seconds before a line appears: what it replaces is still there
MOMENT_NAMES = (
    "start screen",
    "a line sung together",
    "a line or page change",
    "the break screen",
    "the countdown",
    "the end screen",
)


class PictureSong(BaseModel):
    """The timing of the song of the pictures: what the layout needs, no audio.

    It is the lines, the singers, the syllable times, the tempo and the length of an accepted demo
    run, written by ``tools/picture_song.py`` and committed (the text is the song's own, under its
    licence).

    Attributes:
        schema_version: The version of this file.
        title: The title.
        artist: The artist, or ``None``.
        duration: The length of the song in seconds, or ``None``.
        language: ISO 639-1 code of the lyrics; it gives the words for singing together.
        bpm: The tempo in beats per minute, or ``None``.
        singers: Names and colours by singer number.
        lines: The cleaned lines with their singers.
        words: Every word with its syllable times.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    title: str
    artist: str | None
    duration: float | None
    language: str
    bpm: float | None
    singers: dict[int, SingerInfo]
    lines: list[LyricLine]
    words: list[SyllableWord]


def picture_song_of(
    lyrics: LyricsFile, syllables: SyllablesFile, tempo: TempoFile, info: SongInfo
) -> PictureSong:
    """Collect the timing of a song from the stage files of its work folder."""
    return PictureSong(
        title=info.title,
        artist=info.artist,
        duration=info.duration,
        language=syllables.language,
        bpm=tempo.bpm,
        singers=lyrics.singers,
        lines=[LyricLine(text=x.text, singers=x.singers, turns=x.turns) for x in lyrics.lines],
        words=syllables.words,
    )


def parse_picture_song(text: str) -> PictureSong:
    """Parse the JSON text of a picture song.

    Raises:
        ValueError: If the text is not a valid picture song.
    """
    return PictureSong.model_validate_json(text)


def render_picture_song(song: PictureSong) -> str:
    """Return the JSON text of ``song``: indented, sorted as the model is, ending in a newline."""
    return json.dumps(song.model_dump(mode="json"), indent=1, ensure_ascii=False) + "\n"


def picture_text(song: PictureSong) -> SongText:
    """Return what surrounds the lines: title, artist, length, singers, tempo, the joint words."""
    words = LANGUAGES[song.language]
    return SongText(
        song.title,
        song.artist,
        song.duration,
        song.singers,
        words.together_two,
        words.together_all,
        song.bpm,
    )


def picture_scene(song: PictureSong, profile: Profile, measurer: TextMeasurer) -> Scene:
    """Lay out the picture song in ``profile``, with its singers' names and its tempo."""
    timed = TimedSong(song.words, song.lines)
    return scene_of(timed, picture_text(song), profile, PICTURE_PRESET, measurer)


@dataclass(frozen=True)
class Moment:
    """One frame of the picture.

    Attributes:
        name: What it shows, one of ``MOMENT_NAMES``.
        seconds: When in the song.
    """

    name: str
    seconds: float


def _second(seconds: float) -> float:
    """Round to a thousandth, as the scene does."""
    return round(seconds, 3)


def _middle(line: LineElement) -> float:
    """Return the middle of the singing of ``line``, rounded as the scene is."""
    return _second((line.sing_start + line.sing_end) / 2)


def _sung_lines(scene: Scene) -> list[LineElement]:
    """Return the lines in the order they are sung; the rows after the first of a line left out."""
    lines = scene.lines()
    return [x for i, x in enumerate(lines) if not is_later_row(lines, i)]


def _other_singer_line(lines: list[LineElement]) -> LineElement:
    """Return the first line one singer sings alone who is not the singer of the first line.

    Without one, the first line.
    """
    first = lines[0]
    return next(
        (x for x in lines if is_single_singer(x.singers) and x.singers != first.singers), first
    )


def _singing_line(lines: list[LineElement]) -> LineElement:
    """Return the line of the moment "a line sung together": the first sung by a group or by all.

    Before it the lines sung alone are still on the screen in the stacked and page looks, so the
    colour of the singer before it and the colour of the group show together. A song without such
    a line falls back to the first line of the second singer, and a song with one singer to its
    first line.
    """
    group = next((x for x in lines if not is_single_singer(x.singers)), None)
    return group if group is not None else _other_singer_line(lines)


def _glide_after(line: LineElement) -> float | None:
    """Return the middle of the first glide of the column after ``line`` has been sung."""
    glides = [
        (before.time + after.time) / 2
        for before, after in zip(line.path, line.path[1:], strict=False)
        if before.y > after.y and before.time >= line.sing_end
    ]
    return _second(glides[0]) if glides else None


def _replaced_at(scene: Scene, line: LineElement) -> bool:
    """Tell whether ``line`` appears while something else is on the screen (a change)."""
    before = line.start - SETTLE
    return any(isinstance(e, LineElement) and e is not line for e in scene.visible_at(before))


def _change_moment(
    scene: Scene, profile: Profile, lines: list[LineElement], singing: LineElement
) -> float:
    """Return the moment of the look's first change after ``singing`` is half sung.

    ``singing`` is the line of the moment "a line sung together"; the change comes after it, so
    the sheet reads in the order of the song. In line and page mode the moment is
    ``CHANGE_DELAY`` after the first line that appears after that moment where another is still
    on the screen; in scroll mode it is the middle of the first glide of the column after it
    (ADR-0033). Where nothing is replaced after it (a look that clears the screen before each
    page) the moment is just after the first line that appears after it, and where none does (a
    song too short), just after ``singing`` appears.
    """
    sung = _middle(singing)
    after = lines[lines.index(singing) :]
    if profile.mode == "scroll":
        glides = [g for x in after if (g := _glide_after(x)) is not None and g > sung]
        if glides:
            return glides[0]
    later = [x for x in after if x.start > sung] or [singing]
    appears = next((x for x in later if _replaced_at(scene, x)), later[0])
    return _second(appears.start + CHANGE_DELAY)


def _longest_gap(lines: list[LineElement]) -> tuple[float, float]:
    """Return the start and end of the longest silence between two lines, the intro left out.

    ``lines`` are all rows of the scene: a line wrapped onto rows is sung until its last row is.
    """
    silences = gaps(lines)
    index = max(range(1, len(lines)), key=lambda i: silences[i].before)
    return silences[index].ended, lines[index].sing_start


def picture_moments(scene: Scene, profile: Profile) -> list[Moment]:
    """Return the six moments of a picture, in the order of the sheet.

    The same song time in every look, except the change, which depends on the look's own turn:
    the start screen (``START_SCREEN_AT``), a line half sung by a group or by all
    (else the second singer's first line, else the first line), the first change after it
    (``CHANGE_DELAY`` after the line that appears), the middle of the longest
    gap (the break screen), ``COUNTDOWN_BEFORE`` seconds before the first line after it (the
    countdown) and ``END_SCREEN_AFTER`` seconds after the last line ends (the end screen).

    Raises:
        ValueError: If the scene has fewer than two rows: a song of one line has no gap.
    """
    lines = _sung_lines(scene)
    gap_start, gap_end = _longest_gap(scene.lines())
    singing = _singing_line(lines)
    seconds = (
        START_SCREEN_AT,
        _middle(singing),
        _change_moment(scene, profile, lines, singing),
        _second((gap_start + gap_end) / 2),
        _second(gap_end - COUNTDOWN_BEFORE),
        _second(max(x.sing_end for x in scene.lines()) + END_SCREEN_AFTER),
    )
    return [Moment(name, at) for name, at in zip(MOMENT_NAMES, seconds, strict=True)]


def digest_of(parts: dict[str, object]) -> str:
    """Return the SHA-256 of the canonical JSON of ``parts``, the inputs of a picture."""
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def picture_digest(  # every part is a different input of the frames
    *,
    tool_version: int,
    profile_text: str,
    preset: str,
    moments: list[Moment],
    ass: str,
    font_sha256: str,
) -> str:
    """Return the digest of everything a picture is drawn from.

    It covers the inputs and not the pixels, since ffmpeg and libass builds differ between
    machines: a new ffmpeg does not make a picture stale, a changed profile does. ``profile_text``
    is the profile as the video uses it: the ``cdg`` section is left out, since it does not
    change the video.
    """
    return digest_of(
        {
            "tool": tool_version,
            "profile": profile_text,
            "preset": preset,
            "moments": [(m.name, m.seconds) for m in moments],
            "ass": ass,
            "font": font_sha256,
        }
    )
