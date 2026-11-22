"""The tags of the MP4, written by Vocatron itself (ADR-0047).

ffmpeg cannot write the freeform ``TAG`` field and moves standard fields away when asked to write
unknown keys, so the MP4 gets no tag from ffmpeg. This module builds the iTunes-style tag atoms
(``udta/meta/ilst``) from the song's media tags (``core.song.media_tags``, ADR-0031) and puts them
into the ``moov`` box, in place of whatever ffmpeg wrote there.

A fast-start MP4 has its ``moov`` box in front of the media (``mdat``), so a ``moov`` that gets
longer or shorter moves the media, and every chunk offset (``stco``, ``co64``) shifts by exactly
that change. Everything here is bytes in, bytes out; the engine reads the file.
"""

import struct
from collections.abc import Sequence
from typing import NamedTuple

from vocatron.core.song import MediaTags

HEADER = 8
"""A box starts with its size (4 bytes) and its type (4 bytes)."""
LARGE_HEADER = 16
"""A box with the size ``1`` has the real size in 8 more bytes."""
FULL_BOX = b"\x00\x00\x00\x00"
"""The version and flags of a "full" box: all zero."""
UTF8_DATA = b"\x00\x00\x00\x01\x00\x00\x00\x00"
"""The flags of a ``data`` atom for UTF-8 text (type indicator 1) and the empty locale."""
TABLE_HEADER = 8
"""A chunk offset table starts with its version and flags (4 bytes) and its count (4 bytes)."""
MAX_SIZE = 0xFFFFFFFF
"""The largest size and the largest 32-bit chunk offset."""

ITEMS = {"title": b"\xa9nam", "artist": b"\xa9ART", "genre": b"\xa9gen", "comment": b"\xa9cmt"}
"""The media tag keys written as standard iTunes atoms, and their atom types."""
FREEFORM_KEY = "tag"
"""The media tag key written as the freeform atom ``----:com.apple.iTunes:TAG``."""
FREEFORM_MEAN = b"com.apple.iTunes"
FREEFORM_NAME = b"TAG"

CONTAINERS = (b"trak", b"mdia", b"minf", b"stbl")
"""The boxes on the way from ``moov`` to the chunk offsets."""


class Mp4Error(ValueError):
    """The MP4 is not built the way fast start makes it, or a tag does not fit."""


class Mp4Box(NamedTuple):
    """Where a top-level box sits in the file.

    Attributes:
        kind: The four-character type.
        start: Its byte offset.
        size: Its size in bytes, header included.
    """

    kind: bytes
    start: int
    size: int


def box(kind: bytes, payload: bytes) -> bytes:
    """Return a box: size, type, payload.

    Raises:
        Mp4Error: If the box would need the 64-bit size.
    """
    size = HEADER + len(payload)
    if size > MAX_SIZE:
        raise Mp4Error(f"the {kind!r} box is too large for a 32-bit size")
    return struct.pack(">I4s", size, kind) + payload


def read_header(head: bytes, remaining: int) -> tuple[bytes, int, int]:
    """Read a box header and return ``(type, header length, size)``.

    Args:
        head: The first bytes of the box (at least 16 when there are so many).
        remaining: The bytes left in the file from the start of the box; a size of ``0`` means
            "to the end".

    Raises:
        Mp4Error: If the header is cut off or the size is impossible.
    """
    if len(head) < HEADER:
        raise Mp4Error("the file ends inside a box header")
    size, kind = struct.unpack(">I4s", head[:HEADER])
    length = HEADER
    if size == 1:
        if len(head) < LARGE_HEADER:
            raise Mp4Error("the file ends inside a box header")
        (size,) = struct.unpack(">Q", head[HEADER:LARGE_HEADER])
        length = LARGE_HEADER
    elif size == 0:
        size = remaining
    if size < length or size > remaining:
        raise Mp4Error(f"the {kind!r} box has the size {size}, which does not fit")
    return kind, length, size


def locate_moov(boxes: Sequence[Mp4Box]) -> Mp4Box:
    """Return the ``moov`` box of a fast-start file.

    Raises:
        Mp4Error: If there is no ``moov``, or it comes after the media (``mdat``): the chunk
            offsets would not move with it, which is not what this module can handle.
    """
    for found in boxes:
        if found.kind == b"mdat":
            raise Mp4Error("the moov box is not in front of the media; the file is not fast start")
        if found.kind == b"moov":
            return found
    raise Mp4Error("the file has no moov box")


def _data(text: str) -> bytes:
    """Return a ``data`` atom holding UTF-8 text."""
    return box(b"data", UTF8_DATA + text.encode())


def _item(key: str, value: str) -> bytes:
    """Return the ``ilst`` item of one media tag.

    Raises:
        Mp4Error: For a key that has no atom.
    """
    if key in ITEMS:
        return box(ITEMS[key], _data(value))
    if key == FREEFORM_KEY:
        return box(
            b"----",
            box(b"mean", FULL_BOX + FREEFORM_MEAN)
            + box(b"name", FULL_BOX + FREEFORM_NAME)
            + _data(value),
        )
    raise Mp4Error(f"no MP4 atom for the tag {key!r}")


def udta_box(tags: MediaTags) -> bytes:
    """Return ``udta/meta(hdlr mdir)/ilst`` for ``tags``, one item per pair; nothing for no tags.

    Text is UTF-8. ``title``, ``artist``, ``genre`` and ``comment`` are the standard atoms
    (``©nam``, ``©ART``, ``©gen``, ``©cmt``), ``tag`` is the freeform atom ``TAG`` of the
    ``com.apple.iTunes`` namespace that tag editors show as a field of its own.

    Raises:
        Mp4Error: For an unknown key, or a tag too large for a box.
    """
    if not tags:
        return b""
    ilst = box(b"ilst", b"".join(_item(key, value) for key, value in tags))
    handler = box(b"hdlr", FULL_BOX + bytes(4) + b"mdir" + b"appl" + bytes(9))
    return box(b"udta", box(b"meta", FULL_BOX + handler + ilst))


def _children(data: bytes) -> list[tuple[bytes, int, bytes]]:
    """Split the payload of a container into ``(type, header length, whole box)``."""
    found: list[tuple[bytes, int, bytes]] = []
    position = 0
    while position < len(data):
        head = data[position : position + LARGE_HEADER]
        kind, length, size = read_header(head, len(data) - position)
        found.append((kind, length, data[position : position + size]))
        position += size
    return found


def _shifted_offsets(whole: bytes, length: int, delta: int) -> bytes:
    """Return an ``stco`` or ``co64`` box with every chunk offset moved by ``delta``.

    Raises:
        Mp4Error: If the table is cut off, or an offset leaves its range.
    """
    wide = whole[4:8] == b"co64"
    width = 8 if wide else 4
    payload = whole[length:]
    if len(payload) < TABLE_HEADER:
        raise Mp4Error(f"the {whole[4:8]!r} table ends before its count")
    (count,) = struct.unpack(">I", payload[4:TABLE_HEADER])
    if len(payload) != TABLE_HEADER + count * width:
        raise Mp4Error(f"the {whole[4:8]!r} table does not hold {count} offsets")
    code = f">{count}{'Q' if wide else 'I'}"
    offsets = struct.unpack(code, payload[TABLE_HEADER:])
    moved = [offset + delta for offset in offsets]
    largest = (1 << 64) - 1 if wide else MAX_SIZE
    if any(not 0 <= offset <= largest for offset in moved):
        raise Mp4Error("a chunk offset does not fit its table after the move")
    return whole[:length] + payload[:TABLE_HEADER] + struct.pack(code, *moved)


def _shifted(payload: bytes, delta: int) -> bytes:
    """Return the payload of a container with the chunk offsets below it moved by ``delta``."""
    parts: list[bytes] = []
    for kind, length, whole in _children(payload):
        if kind in CONTAINERS:
            parts.append(whole[:length] + _shifted(whole[length:], delta))
        elif kind in (b"stco", b"co64"):
            parts.append(_shifted_offsets(whole, length, delta))
        else:
            parts.append(whole)
    return b"".join(parts)


def retag_moov(moov: bytes, tags: MediaTags) -> bytes:
    """Return ``moov`` with the tags of ``tags`` instead of its own ``udta``.

    The media sits behind ``moov``, so every chunk offset moves by the change in size of the box;
    every other box stays byte for byte as it was.

    Args:
        moov: The whole ``moov`` box, header included.
        tags: The ``(key, value)`` pairs of ``media_tags``.

    Raises:
        Mp4Error: If ``moov`` is not one box of that type, a tag is not writable, or a chunk
            offset does not fit after the move.
    """
    kind, length, size = read_header(moov[:LARGE_HEADER], len(moov))
    if kind != b"moov" or size != len(moov):
        raise Mp4Error("the bytes are not exactly one moov box")
    body = b"".join(whole for child, _, whole in _children(moov[length:]) if child != b"udta")
    udta = udta_box(tags)
    delta = HEADER + len(body) + len(udta) - len(moov)
    return box(b"moov", _shifted(body, delta) + udta)


def read_tags(moov: bytes) -> MediaTags:
    """Return the tags of a ``moov`` box in the order of its ``ilst``; none without ``udta``.

    The inverse of ``udta_box`` for the atoms it writes; other atoms are skipped.

    Raises:
        Mp4Error: If the boxes are malformed.
    """
    kind, length, _ = read_header(moov[:LARGE_HEADER], len(moov))
    if kind != b"moov":
        raise Mp4Error("the bytes are not a moov box")
    names = {atom: key for key, atom in ITEMS.items()}
    found: list[tuple[str, str]] = []
    for child, child_length, whole in _children(moov[length:]):
        if child != b"udta":
            continue
        for meta, meta_length, meta_whole in _children(whole[child_length:]):
            if meta != b"meta":
                continue
            for entry, entry_length, entry_whole in _children(meta_whole[meta_length + 4 :]):
                if entry != b"ilst":
                    continue
                for atom, atom_length, atom_whole in _children(entry_whole[entry_length:]):
                    key = names.get(atom, FREEFORM_KEY if atom == b"----" else None)
                    if key is not None:
                        found.append((key, _text(atom_whole[atom_length:])))
    return tuple(found)


def _text(item: bytes) -> str:
    """Return the text of the ``data`` atom inside an ``ilst`` item."""
    for kind, length, whole in _children(item):
        if kind == b"data":
            return whole[length + len(UTF8_DATA) :].decode()
    raise Mp4Error("an item has no data atom")
