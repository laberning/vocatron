"""Draw the picture of every built-in look for the user docs (ADR-0019, ADR-0045).

Run with ``make profile-pictures``. Each look has a picture, a 3x2 PNG sheet of six moments of the
English demo song, a duet ("My Favorite Regret" by Josh Woodward feat. Katie Pederson, CC BY 4.0;
its timing is ``tests/data/demo/<name>.timing.json``, written by ``make picture-song``): the video,
laid out in the look and drawn with ffmpeg and libass on the CPU (``<name>.png``). A look made for
CD+G has a second one: the CD+G screen, written as CD+G and read back with our own decoder, each
pixel of the 300 by 216 screen shown as 2 by 2 (``<name>-cdg.png``, ADR-0029); a video-only look
(ADR-0032) has none. One more picture, ``overview.png``, shows every look at the moment "a line
sung together", with the name of the look under it.
The pictures go to ``docs/assets/profiles/``;
``docs/assets/profiles/SHA256SUMS`` pins the digest of the inputs of each (``picture_digest`` of
``vocatron.core.profiles.picture`` and ``cdg_picture_digest`` of ``vocatron.core.cdg.picture``), so
a fast test can tell that a profile changed without a new picture. The pixels themselves are not
pinned: ffmpeg builds and FreeType versions differ.

``stale`` and ``picture_inputs`` are also used by the tests.
"""

import functools
import hashlib
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from picture_song import committed_song
from vocatron.core.ass.write import write_ass
from vocatron.core.cdg.picture import CdgPicture, cdg_picture, cdg_picture_digest
from vocatron.core.ffmpeg_cmd import frame_command
from vocatron.core.font_check import font_problems
from vocatron.core.presets import PRESETS
from vocatron.core.profiles.model import BUILTIN_PROFILES, digest_json, made_for_cdg, parse_profile
from vocatron.core.profiles.picture import (
    FRAME_WIDTH,
    MOMENT_NAMES,
    PICTURE_PRESET,
    Moment,
    digest_of,
    picture_digest,
    picture_moments,
    picture_scene,
)
from vocatron.core.scene import Scene
from vocatron.core.schemas import parse_manifest, render_manifest
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser
from vocatron.engines.resources import PackageResources

TOOL_VERSION = 4
CDG_TOOL_VERSION = 3
OVERVIEW_TOOL_VERSION = 2
"""Bump when the way the sheet is drawn or put together changes, so every picture is stale."""
CDG_SUFFIX = "-cdg"
"""The ending of a look's name in the file name of its CD+G sheet."""
CDG_ZOOM = 2
"""A CD+G pixel is drawn as this many pixels square: whole numbers keep the pixel art sharp."""
PICTURE_DIR = Path(__file__).resolve().parent.parent / "docs" / "assets" / "profiles"
MANIFEST = "SHA256SUMS"
FRAME_LIMIT = 60  # seconds ffmpeg may take for one frame
COLUMNS = 3
OVERVIEW = "overview.png"
OVERVIEW_MOMENT = "a line sung together"
OVERVIEW_COLUMNS = 5
OVERVIEW_TILE = 384  # pixels wide, the frames of the overview
LABEL_HEIGHT = 40
LABEL_SIZE = 22
LABEL_BACKGROUND = (24, 24, 24)
LABEL_COLOUR = (240, 240, 240)
DIVIDER = (128, 128, 128)  # a grey line between the moments, seen on dark and light looks
DIVIDER_WIDTH = 2


@dataclass(frozen=True)
class PictureInputs:
    """Everything one picture is drawn from.

    Attributes:
        name: The look.
        scene: The song laid out in the look.
        background: The background colour of the frames.
        moments: The six moments.
        ass: The subtitle text of the scene.
        digest: The digest of all of it, see ``picture_digest``.
    """

    name: str
    scene: Scene
    background: str
    moments: list[Moment]
    ass: str
    digest: str


def picture_inputs(
    name: str, resources: PackageResources, measurer: PillowMeasurer
) -> PictureInputs:
    """Lay out the picture song in the built-in look ``name`` and digest its inputs."""
    profile = parse_profile(name, resources.builtin_profile(name) or "")
    scene = picture_scene(committed_song(), profile, measurer)
    moments = picture_moments(scene, profile)
    ass = write_ass(scene)
    digest = picture_digest(
        tool_version=TOOL_VERSION,
        profile_text=digest_json(profile, without=frozenset({"cdg"})),
        preset=PICTURE_PRESET,
        moments=moments,
        ass=ass,
        font_sha256=hashlib.sha256(resources.font_file().read_bytes()).hexdigest(),
    )
    return PictureInputs(name, scene, profile.background, moments, ass, digest)


def has_cdg_picture(name: str, resources: PackageResources) -> bool:
    """Tell whether the look ``name`` has a CD+G picture: only a look made for CD+G does."""
    return made_for_cdg(parse_profile(name, resources.builtin_profile(name) or ""))


def compose(frames: Sequence[Image.Image], frame_width: int = FRAME_WIDTH) -> Image.Image:
    """Shrink the frames to ``frame_width`` and paste them into a sheet, three in a row.

    A thin grey line divides the moments, so that frames of the same background do not run into
    one picture.
    """
    shrunk = [
        frame.resize((frame_width, round(frame.height * frame_width / frame.width)))
        for frame in frames
    ]
    width, height = shrunk[0].size
    rows = -(-len(shrunk) // COLUMNS)
    sheet = Image.new("RGB", (width * COLUMNS, height * rows))
    for index, frame in enumerate(shrunk):
        sheet.paste(frame, (width * (index % COLUMNS), height * (index // COLUMNS)))
    draw = ImageDraw.Draw(sheet)
    half = DIVIDER_WIDTH // 2
    for column in range(1, COLUMNS):
        x = width * column
        draw.rectangle((x - half, 0, x + half - 1, sheet.height - 1), fill=DIVIDER)
    for row in range(1, rows):
        y = height * row
        draw.rectangle((0, y - half, sheet.width - 1, y + half - 1), fill=DIVIDER)
    return sheet


def draw_frames(
    inputs: PictureInputs, resources: PackageResources, work: Path
) -> list[Image.Image]:
    """Draw the frame of every moment with ffmpeg and libass; fail if libass lacks the font."""
    preset = PRESETS[PICTURE_PRESET]
    ass = work / "lyrics.ass"
    ass.write_text(inputs.ass, encoding="utf-8")
    frames: list[Image.Image] = []
    for index, moment in enumerate(inputs.moments):
        target = work / f"frame{index}.png"
        command = frame_command(
            preset,
            inputs.background,
            ass,
            resources.fonts_dir(),
            moment.seconds,
            target,
            motion=inputs.scene.background_motion,
        )
        done = subprocess.run(command, capture_output=True, check=False, timeout=FRAME_LIMIT)
        log = done.stderr.decode(errors="replace")
        if done.returncode != 0 or font_problems(log):
            raise RuntimeError(f"{inputs.name}: ffmpeg could not draw {moment.name}: {log[-400:]}")
        frames.append(Image.open(target).convert("RGB"))
    return frames


def make_picture(
    name: str, resources: PackageResources, measurer: PillowMeasurer, target: Path
) -> tuple[PictureInputs, list[Image.Image]]:
    """Draw the picture of the look ``name`` into ``target`` (PNG); return its inputs and frames."""
    inputs = picture_inputs(name, resources, measurer)
    with tempfile.TemporaryDirectory() as work:
        frames = draw_frames(inputs, resources, Path(work))
    compose(frames).save(target, optimize=True)
    return inputs, frames


def overview(tiles: Sequence[tuple[str, Image.Image]], resources: PackageResources) -> Image.Image:
    """Put the frames of the looks into one picture, five in a row, each with its name under it.

    Args:
        tiles: The look's name and its frame, in the order of the picture.
        resources: Gives the bundled font of the names.
    """
    font = ImageFont.truetype(str(resources.font_file()), LABEL_SIZE)
    width = OVERVIEW_TILE
    height = round(tiles[0][1].height * width / tiles[0][1].width)
    rows = -(-len(tiles) // OVERVIEW_COLUMNS)
    cell = height + LABEL_HEIGHT
    sheet = Image.new("RGB", (width * OVERVIEW_COLUMNS, cell * rows), LABEL_BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    for index, (name, frame) in enumerate(tiles):
        x, y = width * (index % OVERVIEW_COLUMNS), cell * (index // OVERVIEW_COLUMNS)
        sheet.paste(frame.resize((width, height)), (x, y))
        draw.text(
            (x + width / 2, y + height + LABEL_HEIGHT / 2),
            name,
            fill=LABEL_COLOUR,
            font=font,
            anchor="mm",
        )
        draw.rectangle((x, y, x + width - 1, y + cell - 1), outline=DIVIDER, width=1)
    return sheet


def overview_digest(
    names: Sequence[str], resources: PackageResources, measurer: PillowMeasurer
) -> str:
    """Return the digest of everything the overview is drawn from: the inputs of every look."""
    return digest_of(
        {
            "tool": OVERVIEW_TOOL_VERSION,
            "moment": OVERVIEW_MOMENT,
            "looks": [(n, picture_inputs(n, resources, measurer).digest) for n in names],
            "font": hashlib.sha256(resources.font_file().read_bytes()).hexdigest(),
        }
    )


def cdg_inputs(
    name: str, resources: PackageResources, measurer: PillowMeasurer, rasteriser: PillowRasteriser
) -> tuple[CdgPicture, str]:
    """Write the picture song in the CD+G look ``name``; return it and the digest of its inputs."""
    profile = parse_profile(name, resources.builtin_profile(name) or "")
    picture = cdg_picture(committed_song(), profile, measurer, rasteriser)
    font = hashlib.sha256(resources.font_file().read_bytes()).hexdigest()
    digest = cdg_picture_digest(tool_version=CDG_TOOL_VERSION, picture=picture, font_sha256=font)
    return picture, digest


def make_cdg_picture(
    name: str,
    resources: PackageResources,
    measurer: PillowMeasurer,
    rasteriser: PillowRasteriser,
    target: Path,
) -> str:
    """Draw the CD+G picture of the look ``name`` into ``target`` (a PNG); return its digest."""
    picture, digest = cdg_inputs(name, resources, measurer, rasteriser)
    frames = [
        Image.fromarray(frame).resize(
            (frame.shape[1] * CDG_ZOOM, frame.shape[0] * CDG_ZOOM), Image.Resampling.NEAREST
        )
        for frame in picture.frames
    ]
    compose(frames, frames[0].width).save(target, optimize=True)
    return digest


def current_digest(
    picture: str,
    resources: PackageResources,
    measurer: PillowMeasurer,
    rasteriser: PillowRasteriser,
) -> str:
    """Return the digest of the inputs of the sheet ``picture`` (``<name>.png`` or its CD+G one)."""
    name = picture.removesuffix(".png")
    if name.endswith(CDG_SUFFIX):
        return cdg_inputs(name.removesuffix(CDG_SUFFIX), resources, measurer, rasteriser)[1]
    return picture_inputs(name, resources, measurer).digest


def read_pinned(folder: Path) -> dict[str, str]:
    """Return the digests the manifest in ``folder`` pins, by file name; none without a manifest."""
    manifest_file = folder / MANIFEST
    if not manifest_file.is_file():
        return {}
    return parse_manifest(manifest_file.read_text(encoding="utf-8"))


def pinned_problem(
    folder: Path, pinned: dict[str, str], picture: str, current: Callable[[], str], older: str
) -> str | None:
    """Return what is wrong with ``picture`` in ``folder``, or ``None`` if it is current.

    Args:
        folder: Where the picture and its manifest are.
        pinned: The digests of the manifest (``read_pinned``).
        picture: The file name of the picture.
        current: Computes the digest of the picture's inputs now; called only when needed.
        older: What changed, for the message of an out-of-date picture.
    """
    if not (folder / picture).is_file():
        return f"{picture} is missing"
    if pinned.get(picture) is None:
        return f"{picture} is not in {MANIFEST}"
    if pinned[picture] != current():
        return f"{picture} was made from an older {older}"
    return None


def stale(
    names: Sequence[str], folder: Path, resources: PackageResources, measurer: PillowMeasurer
) -> list[str]:
    """Return what is wrong with the pictures in ``folder``: missing, not listed or out of date.

    Every look has a video sheet, and a look made for CD+G a CD+G sheet too.
    """
    pinned = read_pinned(folder)
    rasteriser = PillowRasteriser(resources.font_file())
    problems: list[str] = []
    for name in names:
        wanted = [f"{name}.png", *([f"{name}{CDG_SUFFIX}.png"] * has_cdg_picture(name, resources))]
        for picture in wanted:
            problem = pinned_problem(
                folder,
                pinned,
                picture,
                functools.partial(current_digest, picture, resources, measurer, rasteriser),
                "profile or layout",
            )
            problems.extend([problem] if problem else [])
    return problems


def overview_stale(
    folder: Path, resources: PackageResources, measurer: PillowMeasurer
) -> list[str]:
    """Return what is wrong with the overview in ``folder``: missing, not listed or out of date."""
    names = list(BUILTIN_PROFILES)
    problem = pinned_problem(
        folder,
        read_pinned(folder),
        OVERVIEW,
        functools.partial(overview_digest, names, resources, measurer),
        "profile or layout",
    )
    return [problem] if problem else []


def main(argv: Sequence[str]) -> int:
    """Draw the pictures of the looks named in ``argv`` (default: all); return the exit code."""
    names = list(argv) or list(BUILTIN_PROFILES)
    unknown = [name for name in names if name not in BUILTIN_PROFILES]
    if unknown:
        print(f"error: not a built-in profile: {', '.join(unknown)}", file=sys.stderr)
        return 2
    resources = PackageResources()
    measurer = PillowMeasurer(resources.font_file())
    rasteriser = PillowRasteriser(resources.font_file())
    PICTURE_DIR.mkdir(parents=True, exist_ok=True)
    pinned = read_pinned(PICTURE_DIR)
    tiles: list[tuple[str, Image.Image]] = []
    for name in names:
        inputs, frames = make_picture(name, resources, measurer, PICTURE_DIR / f"{name}.png")
        tiles.append((name, frames[MOMENT_NAMES.index(OVERVIEW_MOMENT)]))
        pinned[f"{name}.png"] = inputs.digest
        print(f"wrote docs/assets/profiles/{name}.png")
        if has_cdg_picture(name, resources):
            cdg_name = f"{name}{CDG_SUFFIX}.png"
            pinned[cdg_name] = make_cdg_picture(
                name, resources, measurer, rasteriser, PICTURE_DIR / cdg_name
            )
            print(f"wrote docs/assets/profiles/{cdg_name}")
    if names == list(BUILTIN_PROFILES):
        overview(tiles, resources).save(PICTURE_DIR / OVERVIEW, optimize=True)
        pinned[OVERVIEW] = overview_digest(names, resources, measurer)
        print(f"wrote docs/assets/profiles/{OVERVIEW}")
    (PICTURE_DIR / MANIFEST).write_text(render_manifest(pinned), encoding="utf-8")
    print(f"wrote docs/assets/profiles/{MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
