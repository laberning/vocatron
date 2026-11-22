"""Helpers of the stage 2 video tests: real libass frames of a scene, compared by pixels."""

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from fakes.scenes import builtin_profile, profile
from vocatron.core.ass.write import write_ass
from vocatron.core.ffmpeg_cmd import frame_command
from vocatron.core.font_check import font_problems
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.layout.sample import DUET_TURNS, ENTCHEN, HAENSCHEN, timed_song
from vocatron.core.presets import PRESETS, Preset
from vocatron.core.scene import LineElement, Rect, Scene
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.resources import PackageResources

RESOURCES = PackageResources()
MEASURER = PillowMeasurer(RESOURCES.font_file())
INK = 40  # a pixel with a channel above this is not background
BOX_TOLERANCE = 3.0  # pixels: libass rounds glyph positions and the outline has a soft edge
COLOUR_TOLERANCE = 70.0  # distance of a pixel from the colour it should be
FRAME_LIMIT = 60  # seconds ffmpeg may take for one frame
SAME = 0.002  # the share of pixels that may differ from a golden image


def entchen_scene(preset: Preset | None = None) -> Scene:
    """The public-domain test song laid out with the real font."""
    chosen = preset or PRESETS["4x3-720"]
    song = timed_song(ENTCHEN, start=9.0, gaps={2: 6.0, 4: 22.0})
    look = profile()
    return layout(
        phrases_from(song.words, song.lines, look.font.case),
        SongText("Alle meine Entchen", "Volkslied", 60.0, {}),
        look,
        (chosen.width, chosen.height),
        MEASURER,
    )


def turn_scene() -> Scene:
    """Hänschen klein as a duet with the changes of singers inside lines, laid out with the real
    font."""
    song = timed_song(HAENSCHEN, start=4.0, singers=["1", "2", "all", "1", "2"], turns=DUET_TURNS)
    look = profile()
    preset = PRESETS["4x3-720"]
    return layout(
        phrases_from(song.words, song.lines, look.font.case),
        SongText("Hänschen klein", None, 40.0, {}),
        look,
        (preset.width, preset.height),
        MEASURER,
    )


def look_scene(name: str) -> Scene:
    """The test song in the built-in look ``name`` with only one long gap (22 s before the last
    line), so that the first four lines make one page or a full stack."""
    song = timed_song(ENTCHEN, start=9.0, gaps={4: 22.0})
    look = builtin_profile(name)
    preset = PRESETS["4x3-720"]
    return layout(
        phrases_from(song.words, song.lines, look.font.case),
        SongText("Alle meine Entchen", "Volkslied", 60.0, {}),
        look,
        (preset.width, preset.height),
        MEASURER,
    )


ROWS_SONG = (
    "Alle meine Entchen schwimmen auf dem See\n"
    "Köpfchen in das Wasser\n"
    "Schwänzchen in die Höh\n"
)  # the first line is too wide for one row at the size of one-line-preview


def rows_scene(name: str = "one-line-preview") -> Scene:
    """The folk song with a long first line in the look ``name`` (one that wraps lines onto two
    rows): that line has two rows."""
    song = timed_song(ROWS_SONG, start=9.0)
    look = builtin_profile(name)
    preset = PRESETS["4x3-720"]
    return layout(
        phrases_from(song.words, song.lines, look.font.case),
        SongText("Alle meine Entchen", "Volkslied", 40.0, {}),
        look,
        (preset.width, preset.height),
        MEASURER,
    )


def render_frame(
    scene: Scene, seconds: float, work: Path, preset: Preset | None = None
) -> np.ndarray:
    """Draw the frame at ``seconds`` with real ffmpeg and libass; return it as height x width x RGB.

    Fails if libass drew with a font other than the bundled one.
    """
    chosen = preset or PRESETS["4x3-720"]
    work.mkdir(parents=True, exist_ok=True)
    ass, image = work / "lyrics.ass", work / "frame.png"
    ass.write_text(write_ass(scene), encoding="utf-8")
    command = frame_command(
        chosen,
        scene.background,
        ass,
        RESOURCES.fonts_dir(),
        seconds,
        image,
        motion=scene.background_motion,
    )
    done = subprocess.run(command, capture_output=True, check=False, timeout=FRAME_LIMIT)
    log = done.stderr.decode(errors="replace")
    assert done.returncode == 0, log[-400:]
    assert font_problems(log) == [], font_problems(log)
    return np.asarray(Image.open(image).convert("RGB"))


def ink(frame: np.ndarray, region: Rect) -> tuple[int, int, int, int] | None:
    """Return left, top, right and bottom of the pixels in ``region`` that are not background."""
    top, left = max(int(region.y), 0), max(int(region.x), 0)
    part = frame[top : int(region.bottom) + 1, left : int(region.right) + 1]
    rows, columns = np.nonzero((part > INK).any(axis=2))
    if rows.size == 0:
        return None
    return (
        left + int(columns.min()),
        top + int(rows.min()),
        left + int(columns.max()),
        top + int(rows.max()),
    )


def colour_columns(frame: np.ndarray, region: Rect, colour: str) -> np.ndarray:
    """Return the columns (frame coordinates) of ``region`` that hold pixels of ``colour``."""
    target = np.array([int(colour[i : i + 2], 16) for i in (1, 3, 5)], dtype=float)
    top, left = max(int(region.y), 0), max(int(region.x), 0)
    part = frame[top : int(region.bottom) + 1, left : int(region.right) + 1].astype(float)
    close = np.linalg.norm(part - target, axis=2) < COLOUR_TOLERANCE
    return left + np.nonzero(close.any(axis=0))[0]


def visible_lines(scene: Scene, seconds: float) -> list[LineElement]:
    """Return the lyric lines on screen at ``seconds``."""
    return [e for e in scene.visible_at(seconds) if isinstance(e, LineElement)]


def difference(frame: np.ndarray, golden: np.ndarray) -> float:
    """Return the share of pixels that differ visibly from the golden image."""
    if frame.shape != golden.shape:
        return 1.0
    return float((np.abs(frame.astype(int) - golden.astype(int)).max(axis=2) > 24).mean())


SHEET_COLUMNS = 4
SHEET_WIDTH = 480  # pixels per frame on the contact sheet


def frame_at(
    ass: Path, scene: Scene, seconds: float, target: Path, preset: Preset | None = None
) -> np.ndarray:
    """Draw the frame at ``seconds`` of an existing ``lyrics.ass`` with real ffmpeg and libass."""
    chosen = preset or PRESETS["4x3-720"]
    command = frame_command(
        chosen,
        scene.background,
        ass,
        RESOURCES.fonts_dir(),
        seconds,
        target,
        motion=scene.background_motion,
    )
    done = subprocess.run(command, capture_output=True, check=False, timeout=FRAME_LIMIT * 2)
    assert done.returncode == 0, "ffmpeg failed to draw a frame"
    return np.asarray(Image.open(target).convert("RGB"))


def contact_sheet(frames: list[Image.Image]) -> Image.Image:
    """Put the frames side by side in a grid for the human review (not a gate)."""
    height = round(frames[0].height * SHEET_WIDTH / frames[0].width)
    rows = -(-len(frames) // SHEET_COLUMNS)
    sheet = Image.new("RGB", (SHEET_COLUMNS * SHEET_WIDTH, rows * height), (40, 40, 40))
    for index, frame in enumerate(frames):
        small = frame.resize((SHEET_WIDTH, height))
        sheet.paste(
            small, ((index % SHEET_COLUMNS) * SHEET_WIDTH, (index // SHEET_COLUMNS) * height)
        )
    return sheet
