"""Stage 2: the tool of the look pictures draws a real sheet with ffmpeg and libass (ADR-0019).

One look is drawn with the real engines on the CPU: the sheet has the size the docs expect, each
of its six frames holds text (not only the background and the dividing lines), and the digest
of the drawn inputs is the one the committed manifest pins.
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import profile_pictures
from vocatron.core.profiles.picture import MOMENT_NAMES
from vocatron.core.schemas import parse_manifest
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.resources import PackageResources

RESOURCES = PackageResources()
INK = 60  # a pixel with a channel this far from the background colour is ink

pytestmark = [
    pytest.mark.skipif(not RESOURCES.font_file().is_file(), reason="the bundled font is missing"),
    pytest.mark.timeout(300),
]


def test_a_look_is_drawn_as_a_sheet_with_ink_in_every_quarter(tmp_path: Path) -> None:
    measurer = PillowMeasurer(RESOURCES.font_file())
    target = tmp_path / "blue-page.png"
    inputs, _ = profile_pictures.make_picture("blue-page", RESOURCES, measurer, target)
    with Image.open(target) as picture:
        sheet = np.asarray(picture.convert("RGB")).astype(int)
    assert sheet.shape == (720, 1440, 3)
    background = np.array([int(inputs.background[i : i + 2], 16) for i in (1, 3, 5)])
    for index, name in enumerate(MOMENT_NAMES):
        row, column = divmod(index, 3)
        frame = sheet[364 * row : 364 * row + 356, 484 * column : 484 * column + 476]
        assert (np.abs(frame - background) > INK).any(axis=2).sum() > 100, (
            f"nothing is drawn in {name}"
        )
    manifest = parse_manifest(
        (profile_pictures.PICTURE_DIR / profile_pictures.MANIFEST).read_text(encoding="utf-8")
    )
    assert manifest["blue-page.png"] == inputs.digest
