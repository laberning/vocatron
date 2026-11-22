"""Measure how classic CD+G discs present their lyrics (numbers only).

    uv run --no-sync python tools/cdg_analyse.py [FOLDER] [--report FILE] [--break-seconds N]
    uv run --no-sync python tools/cdg_analyse.py [FOLDER] --tilemap NAME (--at T,T,... |
        --timeline START,END,STEP)

``FOLDER`` (default ``.corpus/cdg``) holds one subfolder per vendor with the ``.cdg`` files of its
songs; a file with the same name and an audio suffix next to a ``.cdg`` is used for the length of
the song (else the length of the stream). The tool decodes every file, measures the title phase,
the lines and their rows, the alignment, lead-in, wipe, hold, gaps, breaks, countdowns, palette and
singer colours (``vocatron.lab.cdg.analysis``), prints the table per song and per vendor and
writes the same text to ``FOLDER/report.txt``.

``--tilemap NAME`` prints instead a *tile map* of the first ``.cdg`` file whose path contains
``NAME``: the screen at tile resolution (50 by 18 cells, one character per tile: ``.`` background,
a letter ``a`` to ``p`` for the palette index of a flat tile, upper case for the ink of a tile
with ink; see ``vocatron.lab.cdg.tile_map``) at the times of ``--at`` or every STEP seconds of
``--timeline``. It shows where and when lines stand, never what they say.

The tool prints numbers and file names only. It never writes a frame as an image and never reads
a lyric: a tile is a position, a pixel count and two colours. Everything stays in ``.corpus/``
(never in git).
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from vocatron.core.cdg import decode
from vocatron.engines.protocols import AUDIO_SUFFIXES, TagReadError
from vocatron.engines.tags import TinyTagReader
from vocatron.lab.cdg.analysis import BREAK_SECONDS, Analysis, analyse
from vocatron.lab.cdg.report import song_block, vendor_block
from vocatron.lab.cdg.tile_map import render_maps, tile_map

DEFAULT_FOLDER = Path(".corpus/cdg")


def vendor_files(folder: Path) -> dict[str, list[Path]]:
    """Return the ``.cdg`` files of each vendor subfolder of ``folder``, sorted by path."""
    vendors: dict[str, list[Path]] = {}
    for sub in sorted(path for path in folder.iterdir() if path.is_dir()):
        files = sorted(p for p in sub.rglob("*") if p.suffix.lower() == ".cdg")
        if files:
            vendors[sub.name] = files
    return vendors


def audio_length(cdg: Path) -> float | None:
    """Return the length of the audio file next to ``cdg`` in seconds, or ``None``."""
    for candidate in sorted(cdg.parent.iterdir()):
        if candidate.stem == cdg.stem and candidate.suffix.lower() in AUDIO_SUFFIXES:
            try:
                return TinyTagReader().read(candidate).duration
            except TagReadError:
                return None
    return None


def analyse_file(cdg: Path, break_seconds: float = BREAK_SECONDS) -> Analysis:
    """Decode one ``.cdg`` file and measure it."""
    decoding = decode(cdg.read_bytes())
    duration = max(audio_length(cdg) or 0.0, decoding.duration)
    return analyse(decoding.events, duration, break_seconds)


def build_report(folder: Path, break_seconds: float = BREAK_SECONDS) -> str:
    """Analyse every vendor folder and return the whole report as text."""
    blocks: list[str] = []
    for vendor, files in vendor_files(folder).items():
        done: list[tuple[str, Analysis]] = []
        for path in files:
            name = str(path.relative_to(folder / vendor))
            try:
                analysis = analyse_file(path, break_seconds)
            except (OSError, ValueError) as error:
                blocks.append(f"song {name}: failed ({type(error).__name__})")
                continue
            done.append((name, analysis))
            blocks.append(song_block(name, analysis))
        if done:
            blocks.append(vendor_block(vendor, done))
    return "\n\n".join(blocks) if blocks else f"no .cdg files in the vendor folders of {folder}"


def tile_map_text(cdg: Path, times: Sequence[float]) -> str:
    """Return the tile maps of ``cdg`` at ``times`` (no pixel of any tile is kept)."""
    frames = decode(cdg.read_bytes(), times).frames
    return render_maps([(time, tile_map(frame)) for time, frame in zip(times, frames, strict=True)])


def timeline(spec: str) -> list[float]:
    """Parse ``START,END,STEP`` into the times START, START+STEP, ... up to END."""
    start, end, step = (float(part) for part in spec.split(","))
    count = int((end - start) / step + 1e-9) + 1
    return [start + index * step for index in range(count)]


def main(argv: Sequence[str]) -> int:
    """Run the analysis, print the report and write it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("folder", nargs="?", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--break-seconds", type=float, default=BREAK_SECONDS)
    parser.add_argument("--tilemap", metavar="NAME", default=None)
    parser.add_argument("--at", default="")
    parser.add_argument("--timeline", default="")
    args = parser.parse_args(argv)
    if not args.folder.is_dir():
        print(f"{args.folder}: no such folder")
        return 1
    if args.tilemap is not None:
        return print_tile_maps(args)
    report = build_report(args.folder, args.break_seconds)
    target = args.report or args.folder / "report.txt"
    target.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\nwritten to {target}")
    return 0


def print_tile_maps(args: argparse.Namespace) -> int:
    """Print the tile maps asked for by ``--tilemap`` with ``--at`` or ``--timeline``."""
    found = [
        p for files in vendor_files(args.folder).values() for p in files if args.tilemap in str(p)
    ]
    times = [float(t) for t in args.at.split(",") if t] + (
        timeline(args.timeline) if args.timeline else []
    )
    if not found or not times:
        print("tilemap needs a name that matches a .cdg file and --at or --timeline")
        return 1
    print(f"{found[0].name}")
    print(tile_map_text(found[0], times))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
