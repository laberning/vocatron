"""Helpers of the CD+G tests with the real font: a real stream of a public-domain song, decoders.

The golden pictures (stage 1) and the stage 2 tests use them.

The song is ``ENTCHEN`` with invented times, laid out and drawn with the real font. Three
decoders read its packets: ours, ffmpeg's ``cdgraphics`` and, when Node is there, the JavaScript
library of ADR-0025. They are compared on RGB frames at packet boundaries.
"""

import shutil
import subprocess
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from fakes.scenes import builtin_profile
from vocatron.core.cdg import PACKETS_PER_SECOND, parse_packets
from vocatron.core.cdg.fit import fit_stream
from vocatron.core.cdg.picture import rgb_frames
from vocatron.core.cdg.stream import CdgStream
from vocatron.core.layout import sample
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.scene import Scene
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser
from vocatron.engines.resources import PackageResources

CLONE = Path(__file__).resolve().parents[1]
CDGRAPHICS_JS = CLONE / ".tools" / "cdgraphics-7.0.0" / "dist" / "cdgraphics.js"
FRAME_SCRIPT = Path(__file__).resolve().parent / "slow" / "cdg_frames.mjs"
WIDTH, HEIGHT = 300, 216
MIN_NODE = 20
TOOL_LIMIT = 120  # seconds a decoder may take

type Rgb = NDArray[np.uint8]


def entchen_stream(
    start: float = 9.0, length: float = 40.0, look: str = "two-line-turns"
) -> tuple[Scene, CdgStream]:
    """Lay the folk song out for the CD+G screen with the real font and write its stream.

    Args:
        start: When the first word is sung, in seconds.
        length: The length of the song in seconds.
        look: The built-in look; its ``cdg`` section decides sizes, colours and the wipe step.
    """
    song = sample.timed_song(sample.ENTCHEN, start=start, gaps={2: 6.0, 4: 22.0})
    text = sample.song_text("Alle meine Entchen", "Volkslied", length, {})
    return piece_stream((song, text), look)


def piece_stream(piece: sample.Piece, look: str) -> tuple[Scene, CdgStream]:
    """Lay a timed sample song out for the CD+G screen with the real font and write its stream.

    The look has the start screen with the wordmark, so the decoders also read its own palette
    and the swap to the song's (ADR-0056).

    Args:
        piece: The song and the text around it (``vocatron.core.layout.sample``).
        look: The built-in look; its ``cdg`` section decides sizes, colours and the wipe step.
    """
    resources = PackageResources()
    chosen = builtin_profile(look, title={"form": "wordmark"})
    song, text = piece
    phrases = phrases_from(song.words, song.lines, chosen.font.case)
    fit = fit_stream(
        phrases,
        text,
        chosen,
        PillowMeasurer(resources.font_file()),
        PillowRasteriser(resources.font_file()),
    )
    return fit.scene, fit.written


def sample_packets(scene: Scene, stream: bytes, every: float = 0.5) -> list[int]:
    """Return the packets to compare at: every ``every`` seconds and inside every wipe.

    ffmpeg's decoder makes no frame after the last packet that draws, so none lies beyond it.
    """
    last = list(parse_packets(stream))[-1].index
    times = {k * every for k in range(1, int(scene.duration / every))}
    for line in scene.lines():
        times.update(np.linspace(line.sing_start, line.sing_end, 7).tolist())
    return sorted({n for t in times if (n := int(t * PACKETS_PER_SECOND)) < last})


def our_frames(stream: bytes, packets: list[int]) -> list[Rgb]:
    """Return our decoder's RGB frames after each of the packets."""
    return rgb_frames(stream, [(n + 0.5) / PACKETS_PER_SECOND for n in packets])


def ffmpeg_frames(file: Path, packets: list[int]) -> list[Rgb]:
    """Return ffmpeg's ``cdgraphics`` frames after each of the packets (as RGB).

    The demuxer leaves out the packets that do not draw, so ``fps`` puts one frame on every
    packet slot again before the frames are picked.
    """
    chosen = "+".join(f"eq(n\\,{n})" for n in packets)
    command = [
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(file),
        "-vf", f"fps={PACKETS_PER_SECOND},select='{chosen}'",
        "-fps_mode", "passthrough", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ]  # fmt: skip
    done = subprocess.run(command, capture_output=True, timeout=TOOL_LIMIT, check=True)
    return list(np.frombuffer(done.stdout, dtype=np.uint8).reshape(-1, HEIGHT, WIDTH, 3))


def node_problem() -> str | None:
    """Return why the JavaScript decoder cannot run here, or ``None`` when it can."""
    node = shutil.which("node")
    if node is None:
        return "node is not installed (an optional tool, ADR-0025)"
    if not CDGRAPHICS_JS.is_file():
        return f"{CDGRAPHICS_JS.parent.name} is missing: run `make cdg-js` (ADR-0025)"
    shown = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout
    if int(shown.strip().removeprefix("v").split(".")[0]) < MIN_NODE:
        return f"node {shown.strip()} is older than {MIN_NODE}"
    return None


def js_frames(file: Path, packets: list[int]) -> list[Rgb]:
    """Return the frames of the JavaScript decoder after each of the packets (as RGB)."""
    times = [str((n + 0.5) / PACKETS_PER_SECOND) for n in packets]
    command = ["node", str(FRAME_SCRIPT), str(CDGRAPHICS_JS), str(file), *times]
    done = subprocess.run(command, capture_output=True, timeout=TOOL_LIMIT, check=True)
    rgba = np.frombuffer(done.stdout, dtype=np.uint8).reshape(-1, HEIGHT, WIDTH, 4)
    return [np.asarray(frame[:, :, :3], dtype=np.uint8) for frame in rgba]


def differing(packets: list[int], ours: list[Rgb], theirs: list[Rgb]) -> list[tuple[int, int]]:
    """Return the packet and the number of pixels that differ, for each frame that differs."""
    assert len(theirs) == len(ours) == len(packets)
    return [
        (n, int((a != b).any(axis=2).sum()))
        for n, a, b in zip(packets, ours, theirs, strict=True)
        if not np.array_equal(a, b)
    ]
