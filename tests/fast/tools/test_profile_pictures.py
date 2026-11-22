"""Stage 1 tests for ``tools/profile_pictures.py``: the pictures of the looks are not stale."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import profile_pictures
from fakes.picture_song import made_up_song
from vocatron.core.cdg.picture import CdgPicture, cdg_picture, cdg_picture_digest
from vocatron.core.profiles.model import (
    BUILTIN_PROFILES,
    CLASSIC_PROFILES,
    VIDEO_ONLY_PROFILES,
    digest_json,
    parse_profile,
)
from vocatron.core.schemas import parse_manifest, render_manifest
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser
from vocatron.engines.resources import PackageResources

RESOURCES = PackageResources()
MEASURER = PillowMeasurer(RESOURCES.font_file())
RASTERISER = PillowRasteriser(RESOURCES.font_file())
FOLDER = profile_pictures.PICTURE_DIR
CDG_INPUTS = profile_pictures.cdg_inputs
_WRITTEN: dict[tuple[str, str, str, str], tuple[CdgPicture, str]] = {}
"""The picture song written in each look and the digest of its inputs, per test process."""


def written_once(
    name: str, resources: PackageResources, measurer: PillowMeasurer, rasteriser: PillowRasteriser
) -> tuple[CdgPicture, str]:
    """Write the picture song of a look once per process; the tests only read the result.

    The tools are told apart by their class: all of them here draw with the bundled font, and
    ``profile_pictures.stale`` makes a new rasteriser on every call, so an ``id`` would miss the
    shared result (or match a dead object's).
    """
    key = (
        name,
        type(resources).__qualname__,
        type(measurer).__qualname__,
        type(rasteriser).__qualname__,
    )
    if key not in _WRITTEN:
        _WRITTEN[key] = CDG_INPUTS(name, resources, measurer, rasteriser)
    return _WRITTEN[key]


@pytest.fixture(autouse=True)
def one_picture_song_per_look(monkeypatch: pytest.MonkeyPatch) -> None:
    """Share the CD+G picture song of a look between these tests; they check what is made of it.

    Writing the song of a look for the CD+G screen takes seconds. The picture song itself is
    tested in ``core/cdg/test_picture.py``.
    """
    monkeypatch.setattr(profile_pictures, "cdg_inputs", written_once)


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_every_built_in_look_has_a_current_picture(name: str) -> None:
    problems = profile_pictures.stale([name], FOLDER, RESOURCES, MEASURER)
    assert problems == [], f"{problems}: run `make profile-pictures`"


def test_the_overview_is_current() -> None:
    problems = profile_pictures.overview_stale(FOLDER, RESOURCES, MEASURER)
    assert problems == [], f"{problems}: run `make profile-pictures`"


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_a_committed_picture_is_a_3x2_sheet_of_480_pixel_frames(name: str) -> None:
    with Image.open(FOLDER / f"{name}.png") as picture:
        assert picture.size == (1440, 720)


@pytest.mark.parametrize("name", CLASSIC_PROFILES)
def test_a_committed_cdg_picture_is_a_3x2_sheet_of_screens_shown_at_twice_the_size(
    name: str,
) -> None:
    with Image.open(FOLDER / f"{name}{profile_pictures.CDG_SUFFIX}.png") as picture:
        assert picture.size == (3 * 2 * 300, 2 * 2 * 216)


def test_the_committed_overview_has_two_rows_of_five_tiles_with_a_name_under_each() -> None:
    tile = profile_pictures.OVERVIEW_TILE
    cell = tile * 3 // 4 + profile_pictures.LABEL_HEIGHT
    with Image.open(FOLDER / profile_pictures.OVERVIEW) as picture:
        assert picture.size == (5 * tile, 2 * cell)
    assert len(BUILTIN_PROFILES) == 10


@pytest.mark.parametrize("name", VIDEO_ONLY_PROFILES)
def test_a_video_only_look_has_a_video_picture_and_no_cdg_picture(name: str) -> None:
    assert not profile_pictures.has_cdg_picture(name, RESOURCES)
    assert (FOLDER / f"{name}.png").is_file()
    assert not (FOLDER / f"{name}{profile_pictures.CDG_SUFFIX}.png").exists()
    assert profile_pictures.stale([name], FOLDER, RESOURCES, MEASURER) == []


def test_a_classic_look_has_a_cdg_picture() -> None:
    assert profile_pictures.has_cdg_picture("blue-page", RESOURCES)


def test_six_frames_make_a_3x2_sheet_with_each_frame_in_its_place() -> None:
    colours = ["#ff0000", "#00ff00", "#0000ff", "#ffff00", "#00ffff", "#ff00ff"]
    sheet = profile_pictures.compose([Image.new("RGB", (960, 720), c) for c in colours])
    assert sheet.size == (1440, 720)
    corners = [(10, 10), (700, 10), (1430, 10), (10, 710), (700, 710), (1430, 710)]
    assert [sheet.getpixel(p) for p in corners] == [
        (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255),
    ]  # fmt: skip
    grey = profile_pictures.DIVIDER
    dividers = [(479, 10), (480, 710), (959, 10), (960, 710), (10, 359), (1430, 360)]
    assert [sheet.getpixel(p) for p in dividers] == [grey] * 6
    beside = [(477, 10), (482, 710), (957, 10), (962, 710), (10, 357), (1430, 362)]
    assert [sheet.getpixel(p) for p in beside] == [
        (255, 0, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 0, 0), (255, 0, 255),
    ]  # fmt: skip


def test_the_overview_puts_each_look_in_a_tile_with_a_name_strip_under_it() -> None:
    tile = profile_pictures.OVERVIEW_TILE
    colours = ["#ff0000", "#00ff00", "#0000ff", "#ffff00", "#00ffff", "#ff00ff", "#ffffff"]
    tiles = [(f"look-{i}", Image.new("RGB", (960, 720), c)) for i, c in enumerate(colours)]
    sheet = profile_pictures.overview(tiles, RESOURCES)
    height = tile * 3 // 4
    cell = height + profile_pictures.LABEL_HEIGHT
    assert sheet.size == (5 * tile, 2 * cell)
    assert sheet.getpixel((tile // 2, height // 2)) == (255, 0, 0)
    assert sheet.getpixel((tile + tile // 2, height // 2)) == (0, 255, 0)
    assert sheet.getpixel((tile // 2, cell + height // 2)) == (255, 0, 255)  # the sixth: row two
    strip = sheet.crop((3, height + 3, tile - 3, cell - 3))  # the name is the only ink in it
    inked = [p for p in strip.get_flattened_data() if p != profile_pictures.LABEL_BACKGROUND]
    assert len(inked) > 20


def stale_in(folder: Path, names: list[str]) -> list[str]:
    return profile_pictures.stale(names, folder, RESOURCES, MEASURER)


def test_a_missing_picture_a_missing_line_and_an_old_digest_are_each_reported(
    tmp_path: Path,
) -> None:
    assert stale_in(tmp_path, ["blue-page"]) == [
        "blue-page.png is missing",
        "blue-page-cdg.png is missing",
    ]
    Image.new("RGB", (1, 1)).save(tmp_path / "blue-page.png")
    Image.new("RGB", (1, 1)).save(tmp_path / "blue-page-cdg.png")
    assert stale_in(tmp_path, ["blue-page"]) == [
        f"blue-page.png is not in {profile_pictures.MANIFEST}",
        f"blue-page-cdg.png is not in {profile_pictures.MANIFEST}",
    ]
    manifest = tmp_path / profile_pictures.MANIFEST
    manifest.write_text(
        render_manifest({"blue-page.png": "0" * 64, "blue-page-cdg.png": "0" * 64}),
        encoding="utf-8",
    )
    assert stale_in(tmp_path, ["blue-page"]) == [
        "blue-page.png was made from an older profile or layout",
        "blue-page-cdg.png was made from an older profile or layout",
    ]
    digest = profile_pictures.picture_inputs("blue-page", RESOURCES, MEASURER).digest
    cdg_digest = profile_pictures.cdg_inputs("blue-page", RESOURCES, MEASURER, RASTERISER)[1]
    manifest.write_text(
        render_manifest({"blue-page.png": digest, "blue-page-cdg.png": cdg_digest}),
        encoding="utf-8",
    )
    assert stale_in(tmp_path, ["blue-page"]) == []


def test_the_overview_is_missing_not_listed_or_out_of_date_unless_it_is_current(
    tmp_path: Path,
) -> None:
    def problems() -> list[str]:
        return profile_pictures.overview_stale(tmp_path, RESOURCES, MEASURER)

    name = profile_pictures.OVERVIEW
    assert problems() == [f"{name} is missing"]
    Image.new("RGB", (1, 1)).save(tmp_path / name)
    assert problems() == [f"{name} is not in {profile_pictures.MANIFEST}"]
    manifest = tmp_path / profile_pictures.MANIFEST
    manifest.write_text(render_manifest({name: "0" * 64}), encoding="utf-8")
    assert problems() == [f"{name} was made from an older profile or layout"]
    current = profile_pictures.overview_digest(list(BUILTIN_PROFILES), RESOURCES, MEASURER)
    manifest.write_text(render_manifest({name: current}), encoding="utf-8")
    assert problems() == []


def test_the_overview_digest_follows_the_looks_it_shows() -> None:
    names = list(BUILTIN_PROFILES)
    full = profile_pictures.overview_digest(names, RESOURCES, MEASURER)
    assert full == profile_pictures.overview_digest(names, RESOURCES, MEASURER)
    assert full != profile_pictures.overview_digest(names[:-1], RESOURCES, MEASURER)


def test_a_change_of_the_cdg_section_changes_the_cdg_digest_and_not_the_video_digest() -> None:
    text = RESOURCES.builtin_profile("blue-page") or ""
    plain = parse_profile("blue-page", text)
    coarse = parse_profile("blue-page", text, {"cdg": {"wipe_columns": 6}})
    assert plain.model_dump_json(exclude={"cdg"}) == coarse.model_dump_json(exclude={"cdg"})
    digests = [
        cdg_picture_digest(
            tool_version=1,
            picture=cdg_picture(made_up_song(), look, MEASURER, RASTERISER),
            font_sha256="f" * 64,
        )
        for look in (plain, coarse)
    ]
    assert digests[0] != digests[1]


def test_a_look_with_an_effect_changes_the_digest_and_one_without_keeps_it() -> None:
    text = RESOURCES.builtin_profile("two-line-turns") or ""
    plain = parse_profile("two-line-turns", text)
    glowing = parse_profile("two-line-turns", text, {"cdg": None, "glow": {"sung": 0.5}})
    assert "glow" not in digest_json(plain)
    assert digest_json(plain) != digest_json(glowing)
    assert '"glow":{"sung":0.5' in digest_json(glowing)


def test_the_digest_differs_between_the_looks() -> None:
    digests = {
        profile_pictures.picture_inputs(name, RESOURCES, MEASURER).digest
        for name in BUILTIN_PROFILES
    }
    assert len(digests) == len(BUILTIN_PROFILES)


def test_the_committed_cdg_digests_differ_between_the_looks() -> None:
    """Each look's digest is checked against its sheet above; here they are told apart."""
    pinned = parse_manifest((FOLDER / profile_pictures.MANIFEST).read_text(encoding="utf-8"))
    digests = {pinned[f"{name}{profile_pictures.CDG_SUFFIX}.png"] for name in CLASSIC_PROFILES}
    assert len(digests) == len(CLASSIC_PROFILES)


def test_a_cdg_pixel_is_shown_as_a_square_of_whole_pixels_in_exactly_its_colour(
    tmp_path: Path,
) -> None:
    target = tmp_path / "look.png"
    digest = profile_pictures.make_cdg_picture(
        "two-line-turns", RESOURCES, MEASURER, RASTERISER, target
    )
    assert (
        digest == profile_pictures.cdg_inputs("two-line-turns", RESOURCES, MEASURER, RASTERISER)[1]
    )
    sheet = np.asarray(Image.open(target).convert("RGB"))
    colours = {tuple(int(v) for v in p) for p in sheet.reshape(-1, 3)}
    assert len(colours) <= 16 + 1  # the 16 palette entries and the grey divider
    zoom = profile_pictures.CDG_ZOOM
    assert (sheet[0:zoom, 0:zoom] == sheet[0, 0]).all()  # a block of four pixels


def test_an_unknown_look_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert profile_pictures.main(["no-such-look"]) == 2
    assert "no-such-look" in capsys.readouterr().err
