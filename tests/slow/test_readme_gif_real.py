"""Stage 2: the tool of the README animation draws a real GIF with ffmpeg (ADR-0045, ADR-0050).

On the CPU: the clip has the frames, the size and the weight the docs expect, there is text in it
(not only the background), and the digest of its inputs is the one the committed manifest pins.
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import readme_gif
from vocatron.core.schemas import parse_manifest
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.resources import PackageResources

RESOURCES = PackageResources()
MIN_INK_PIXELS = 100  # a frame with text has more pixels than this far from the background

pytestmark = pytest.mark.timeout(600)


def test_the_gif_is_drawn_with_text_in_its_frames_and_the_pinned_digest(tmp_path: Path) -> None:
    target = tmp_path / "clip.gif"
    inputs = readme_gif.make_gif(RESOURCES, PillowMeasurer(RESOURCES.font_file()), target)
    assert target.stat().st_size <= readme_gif.MAX_BYTES
    background = np.array([int(inputs.background[i : i + 2], 16) for i in (1, 3, 5)])
    with Image.open(target) as gif:
        assert gif.size == readme_gif.SIZE
        frames = getattr(gif, "n_frames", 1)  # Pillow's GIF reader has it; its base class not
        assert frames == round(sum(length for _, length in inputs.windows) * readme_gif.FPS)
        # at 2 s the title is built up
        for index in (round(2 * readme_gif.FPS), frames // 2, frames - 1):
            gif.seek(index)
            frame = np.asarray(gif.convert("RGB")).astype(int)
            assert (np.abs(frame - background) > 60).any(axis=2).sum() > MIN_INK_PIXELS, (
                f"nothing is drawn in frame {index}"
            )
    manifest = parse_manifest((readme_gif.ASSETS / readme_gif.MANIFEST).read_text(encoding="utf-8"))
    assert manifest[readme_gif.TARGET] == inputs.digest
