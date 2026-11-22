"""Stage 2: the start screen with the wordmark on CD+G, read by other decoders (ADR-0056).

The demo duet of the pictures (``tests/data/demo/<name>.timing.json``, CC BY 4.0) is laid out in
the real font for the CD+G screen and written with the wordmark start screen; ffmpeg's own
``cdgraphics`` decoder, and the JavaScript one of ADR-0025 where Node is there, must show the band
colours inside a letter and the field outside it while the start screen stands, the field in the
border, and the look's background in the border after the screen has ended (the palette swapped, the
screen cleared). No GPU, no corpus; the tests report colours and verdicts only.
"""

import shutil
from pathlib import Path

import pytest

from cdgreal import Rgb, ffmpeg_frames, js_frames, node_problem, our_frames
from fakes.scenes import builtin_profile
from picture_song import committed_song
from vocatron.core.cdg.fit import fit_stream
from vocatron.core.cdg.packet import PACKETS_PER_SECOND
from vocatron.core.cdg.palette import colour4
from vocatron.core.colour import round_12bit
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.profiles.picture import picture_text
from vocatron.core.scene import CardElement
from vocatron.core.wordmark import BAND_COLOURS, FIELD_COLOUR, pixel_word_cells
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser
from vocatron.engines.resources import PackageResources

pytestmark = [
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed"),
    pytest.mark.timeout(600),
]
LOOK = "two-line-turns"


def rgb_of(colour: str) -> tuple[int, int, int]:
    """Return ``#rrggbb`` as the 8-bit values a decoder shows for its 12-bit colour."""
    red, green, blue = colour4(colour)
    return 17 * red, 17 * green, 17 * blue


def pixel(frame: Rgb, row: int, column: int) -> tuple[int, int, int]:
    """Return the colour of a pixel of a decoded frame."""
    red, green, blue = (int(value) for value in frame[row, column])
    return red, green, blue


@pytest.fixture(scope="module")
def written(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, int, int, tuple[int, int, int, int]]:
    """Write the demo duet and return its file, the packet the start screen ends at, the packet
    after which it is settled and the word's box (top, left, cell, rows)."""
    resources = PackageResources()
    chosen = builtin_profile(LOOK, title={"form": "wordmark"})
    song = committed_song()
    fit = fit_stream(
        phrases_from(song.words, song.lines, chosen.font.case),
        picture_text(song),
        chosen,
        PillowMeasurer(resources.font_file()),
        PillowRasteriser(resources.font_file()),
    )
    (title,) = [e for e in fit.scene.elements if isinstance(e, CardElement) and e.kind == "title"]
    assert title.mark is not None and title.mark.pixel
    file = tmp_path_factory.mktemp("cdg") / "Song.cdg"
    file.write_bytes(fit.written.stream)
    settled = fit.written.scheduled.settled[0]
    box = (round(title.mark.word.y), round(title.mark.word.x), round(title.mark.scale), 11)
    return file, round(title.end * PACKETS_PER_SECOND), settled * 3 + 2, box


@pytest.mark.parametrize("name", ["ffmpeg", "cdgraphics-js", "ours"])
def test_the_decoder_shows_the_bands_in_a_letter_the_field_outside_and_the_background_after(
    written: tuple[Path, int, int, tuple[int, int, int, int]], name: str
) -> None:
    file, ends, settled, (top, left, cell, rows) = written
    if name == "cdgraphics-js" and node_problem() is not None:
        pytest.skip(node_problem() or "")
    packets = [settled + 3, ends - 3, ends + 12]
    if name == "ours":
        frames: list[Rgb] = our_frames(file.read_bytes(), packets)
    else:
        frames = (ffmpeg_frames if name == "ffmpeg" else js_frames)(file, packets)
    during, last, after = frames
    field = rgb_of(FIELD_COLOUR)
    bands = [rgb_of(c) for c in BAND_COLOURS]
    cells = pixel_word_cells()
    stem = next(c for c in range(len(cells[0])) if all(row[c] for row in cells))  # the T's stem
    x = left + stem * cell + 1
    for frame in (during, last):
        shown = [pixel(frame, top + row * cell + 1, x) for row in range(rows)]
        assert set(shown) == set(bands), name  # a stem: every band, top to bottom
        assert [bands.index(c) for c in shown] == sorted(bands.index(c) for c in shown), name
        assert pixel(frame, top + rows // 2, left - 12) == field, name
        assert pixel(frame, 0, 0) == field, name  # the border
    background = rgb_of(round_12bit(builtin_profile(LOOK).background))
    assert pixel(after, 0, 0) == background, name  # the look's, after the swap
    assert pixel(after, top + 1, left + 1) == background, name  # no letters
