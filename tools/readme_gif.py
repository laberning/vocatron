"""Draw the animation of the default look for the README and the start page (ADR-0045, ADR-0050).

Run with ``make readme-gif``. It lays out the English demo song (its committed timing, see
``tools/picture_song.py``) in the default look and draws two cuts of it (``cuts``: the title
screen, then the first lines sung without a break, up to the first pause) with ffmpeg and libass on
the CPU as a looping GIF of ``docs/assets/readme.gif``: one hard cut, 12 frames a second, 640 by
480, one palette for the whole clip. ``docs/assets/SHA256SUMS`` pins the digest of its inputs
(``gif_inputs``), so a fast test can tell that the look, the layout, the song or the cuts
changed without a new GIF. The pixels themselves are not pinned.

``stale`` and ``gif_inputs`` are also used by the tests.
"""

import hashlib
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from picture_song import committed_song
from profile_pictures import MANIFEST, pinned_problem, read_pinned
from vocatron.core.ass.write import write_ass
from vocatron.core.ffmpeg_cmd import gif_command
from vocatron.core.font_check import font_problems
from vocatron.core.presets import PRESETS
from vocatron.core.profiles.model import DEFAULT_PROFILE, digest_json, parse_profile
from vocatron.core.profiles.picture import PICTURE_PRESET, PictureSong, digest_of, picture_scene
from vocatron.core.scene import BackgroundMotion
from vocatron.core.schemas import render_manifest
from vocatron.core.syllables import SyllableWord
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.resources import PackageResources

TOOL_VERSION = 3
"""Bump when the way the GIF is drawn changes, so the committed one is stale."""
TITLE_SECONDS = 3.0  # the first cut: the title screen, from the start: its build-up and a rest
LEAD_IN = 3.0  # the second cut starts this long before the first word is sung
MIN_SUNG = 10.0  # seconds of singing, from the first word, before the clip may stop
PAUSE = 3.0  # a gap between two lines at least this long is a place to stop
TAIL = 1.0  # the clip ends this long after the last word it shows
FPS = 12
SIZE = (640, 480)
ASSETS = Path(__file__).resolve().parent.parent / "docs" / "assets"
TARGET = "readme.gif"
RENDER_LIMIT = 600  # seconds ffmpeg may take
MAX_BYTES = 2_000_000  # the GIF should not weigh more: it loads with the front page


Window = tuple[float, float]
"""Start and length in seconds of a part of the song."""


def cuts(words: Sequence[SyllableWord], duration: float | None = None) -> list[Window]:
    """Return the two cuts of the GIF, in song order, from the timed words of the song.

    The title screen from the start for ``TITLE_SECONDS``; then one cut from ``LEAD_IN`` before the
    first word (not into the title cut) to ``TAIL`` after the end of the first line that is
    followed by a pause of at least ``PAUSE`` (or by nothing) once ``MIN_SUNG`` seconds have been
    sung, so the clip stops where the singing does. ``duration``, when known, caps the end.
    """
    lines: dict[int, tuple[float, float]] = {}
    for word in words:
        start, end = lines.get(word.line, (word.start, word.end))
        lines[word.line] = (min(start, word.start), max(end, word.end))
    spans = sorted(lines.values())
    first = spans[0][0]
    stop = max(end for _, end in spans)
    sung_to = first  # the end of the singing so far: lines of two voices may overlap
    for (_, end), following in zip(spans, [*spans[1:], None], strict=True):
        sung_to = max(sung_to, end)
        if sung_to - first >= MIN_SUNG and (following is None or following[0] - sung_to >= PAUSE):
            stop = sung_to
            break
    begin = max(TITLE_SECONDS, first - LEAD_IN)
    finish = stop + TAIL if duration is None else min(stop + TAIL, duration)
    return [(0.0, TITLE_SECONDS), (round(begin, 3), round(finish - begin, 3))]


@dataclass(frozen=True)
class GifInputs:
    """Everything the GIF is drawn from.

    Attributes:
        background: The background colour of the frames.
        motion: The moving background of the look, ``None`` for the plain colour.
        ass: The subtitle text of the song in the look.
        windows: The cuts of the song that make the clip.
        digest: The digest of all of it.
    """

    background: str
    motion: BackgroundMotion | None
    ass: str
    windows: list[Window]
    digest: str


def gif_inputs(
    resources: PackageResources, measurer: PillowMeasurer, song: PictureSong | None = None
) -> GifInputs:
    """Lay out the picture song (the committed one by default) in the default look; digest it."""
    song = song or committed_song()
    profile = parse_profile(DEFAULT_PROFILE, resources.builtin_profile(DEFAULT_PROFILE) or "")
    scene = picture_scene(song, profile, measurer)
    ass = write_ass(scene)
    windows = cuts(song.words, song.duration)
    digest = digest_of(
        {
            "tool": TOOL_VERSION,
            "profile": digest_json(profile, without=frozenset({"cdg"})),
            "preset": PICTURE_PRESET,
            "windows": windows,
            "fps": FPS,
            "size": SIZE,
            "ass": ass,
            "font": hashlib.sha256(resources.font_file().read_bytes()).hexdigest(),
        }
    )
    return GifInputs(profile.background, scene.background_motion, ass, windows, digest)


def make_gif(resources: PackageResources, measurer: PillowMeasurer, target: Path) -> GifInputs:
    """Draw the GIF into ``target`` with ffmpeg and libass; fail if libass lacks the font."""
    inputs = gif_inputs(resources, measurer)
    with tempfile.TemporaryDirectory() as work:
        ass = Path(work) / "lyrics.ass"
        ass.write_text(inputs.ass, encoding="utf-8")
        command = gif_command(
            PRESETS[PICTURE_PRESET], inputs.background, ass, resources.fonts_dir(), inputs.windows,
            target, fps=FPS, size=SIZE, motion=inputs.motion,
        )  # fmt: skip
        done = subprocess.run(command, capture_output=True, check=False, timeout=RENDER_LIMIT)
    log = done.stderr.decode(errors="replace")
    if done.returncode != 0 or font_problems(log):
        raise RuntimeError(f"ffmpeg could not draw the GIF: {log[-400:]}")
    return inputs


def stale(folder: Path, resources: PackageResources, measurer: PillowMeasurer) -> list[str]:
    """Return what is wrong with the GIF in ``folder``: missing, not listed or out of date."""
    problem = pinned_problem(
        folder,
        read_pinned(folder),
        TARGET,
        lambda: gif_inputs(resources, measurer).digest,
        "look, layout, song or cuts",
    )
    return [problem] if problem else []


def main(argv: Sequence[str]) -> int:
    """Draw the GIF into ``docs/assets/``; return the exit code."""
    if argv:
        print("error: readme_gif takes no arguments", file=sys.stderr)
        return 2
    resources = PackageResources()
    measurer = PillowMeasurer(resources.font_file())
    ASSETS.mkdir(parents=True, exist_ok=True)
    inputs = make_gif(resources, measurer, ASSETS / TARGET)
    pinned = read_pinned(ASSETS)
    pinned[TARGET] = inputs.digest
    (ASSETS / MANIFEST).write_text(render_manifest(pinned), encoding="utf-8")
    size = (ASSETS / TARGET).stat().st_size
    print(f"wrote docs/assets/{TARGET}: {size / 1e6:.2f} MB at {FPS} frames a second")
    if size > MAX_BYTES:
        print(f"warning: the GIF is larger than {MAX_BYTES / 1e6:.1f} MB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
