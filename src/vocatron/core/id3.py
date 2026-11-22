"""The ID3v2.4 tag of the MP3, written by Vocatron itself (ADR-0035, ADR-0047).

ffmpeg cannot write the standard comment frame, so the MP3 gets no tag from ffmpeg and this
module builds the whole tag from the song's media tags (``core.song.media_tags``, ADR-0031).
"""

from vocatron.core.song import MediaTags

ID3_VERSION = b"\x04\x00"
"""ID3v2.4.0: major version 4, revision 0."""
UTF8 = b"\x03"
"""The text encoding byte of ID3v2.4 for UTF-8."""
COMMENT_LANGUAGE = b"eng"
"""The language of the comment frame."""
MAX_SYNCHSAFE = 1 << 28
"""Sizes are four bytes of seven bits; a tag or frame must be smaller than this."""

TEXT_FRAMES = {"title": b"TIT2", "artist": b"TPE1", "genre": b"TCON"}
"""The media tag keys written as plain text frames, and their frame ids."""
COMMENT_KEY = "comment"
"""The media tag key written as the comment frame ``COMM``."""
COMMENT_FRAME = b"COMM"
USER_TEXT_KEY = "tag"
"""The media tag key written as the user-defined text frame ``TXXX`` with the description
``TAG`` (ADR-0047)."""
USER_TEXT_FRAME = b"TXXX"
USER_TEXT_DESCRIPTION = b"TAG"


def synchsafe(size: int) -> bytes:
    """Return ``size`` as four bytes of seven bits each, most significant first.

    Raises:
        ValueError: If ``size`` is negative or does not fit in 28 bits.
    """
    if not 0 <= size < MAX_SYNCHSAFE:
        raise ValueError(f"size {size} does not fit an ID3 size field")
    return bytes((size >> shift) & 0x7F for shift in (21, 14, 7, 0))


def _frame(frame_id: bytes, body: bytes) -> bytes:
    """Return a frame: id, synchsafe size, two zero flag bytes, body."""
    return frame_id + synchsafe(len(body)) + b"\x00\x00" + body


def _frame_for(key: str, value: str) -> bytes:
    """Return the frame of one media tag.

    Raises:
        ValueError: For a key that has no frame.
    """
    text = value.encode()  # UTF-8
    if key in TEXT_FRAMES:
        return _frame(TEXT_FRAMES[key], UTF8 + text)
    if key == COMMENT_KEY:
        return _frame(COMMENT_FRAME, UTF8 + COMMENT_LANGUAGE + b"\x00" + text)  # empty description
    if key == USER_TEXT_KEY:
        return _frame(USER_TEXT_FRAME, UTF8 + USER_TEXT_DESCRIPTION + b"\x00" + text)
    raise ValueError(f"no ID3 frame for the tag {key!r}")


def id3_tag(tags: MediaTags) -> bytes:
    """Return the ID3v2.4 tag for ``tags``: header, then one frame per pair, no padding.

    Text is UTF-8. The ``tag`` is a ``TXXX`` frame with the description ``TAG``. The comment
    has the language ``eng`` and an empty description. No tags give no bytes at all, so the MP3
    then starts with the audio.

    Args:
        tags: The ``(key, value)`` pairs of ``media_tags``: ``title``, ``artist``, ``genre``,
            ``comment`` and ``tag``.

    Raises:
        ValueError: For an unknown key, or a tag too large for ID3.
    """
    frames = b"".join(_frame_for(key, value) for key, value in tags)
    if not frames:
        return b""
    return b"ID3" + ID3_VERSION + b"\x00" + synchsafe(len(frames)) + frames
