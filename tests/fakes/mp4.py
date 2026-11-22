"""Small synthetic MP4 files and ``moov`` boxes with chunk offsets (tests of the MP4 tags)."""

import struct
from collections.abc import Sequence

from vocatron.core.mp4_tags import box

FTYP = box(b"ftyp", b"isom" + bytes(4) + b"isom")
OLD_UDTA = box(b"udta", box(b"meta", bytes(4) + box(b"ilst", box(b"\xa9too", b"Lavf"))))
"""The kind of tag ffmpeg writes on its own, to be replaced."""


def stco(offsets: Sequence[int]) -> bytes:
    """Return an ``stco`` box with 32-bit chunk offsets."""
    return box(b"stco", bytes(4) + struct.pack(f">I{len(offsets)}I", len(offsets), *offsets))


def co64(offsets: Sequence[int]) -> bytes:
    """Return a ``co64`` box with 64-bit chunk offsets."""
    return box(b"co64", bytes(4) + struct.pack(f">I{len(offsets)}Q", len(offsets), *offsets))


def trak(table: bytes, filler: bytes = b"") -> bytes:
    """Return a ``trak`` holding ``table`` in ``mdia/minf/stbl``, next to a box with no offsets."""
    stbl = box(b"stbl", box(b"stts", filler) + table)
    return box(b"trak", box(b"tkhd", bytes(8)) + box(b"mdia", box(b"minf", stbl)))


def moov(*children: bytes) -> bytes:
    """Return a ``moov`` box with ``mvhd`` and ``children``."""
    return box(b"moov", box(b"mvhd", bytes(20)) + b"".join(children))


def mp4_file(media: bytes = b"media", udta: bytes = OLD_UDTA) -> bytes:
    """Return a fast-start MP4: ``ftyp``, a ``moov`` whose offsets are right, then ``mdat``."""
    size = len(FTYP) + len(moov(trak(stco([0, 0]), b"x"), udta)) + 8  # where the media starts
    return FTYP + moov(trak(stco([size, size + 3]), b"x"), udta) + box(b"mdat", media)
