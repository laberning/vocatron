"""Stage 1: the ID3v2.4 tag of the MP3 is built from fixed bytes and read back (ADR-0035)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.id3 import id3_tag, synchsafe
from vocatron.core.song import KARAOKE_COMMENT, KARAOKE_GENRE


def parse(tag: bytes) -> list[tuple[bytes, bytes]]:
    """Read a tag the way a player does: header, then frames of id, synchsafe size, flags, body."""
    assert tag[:3] == b"ID3" and tag[3:6] == b"\x04\x00\x00"
    assert all(byte < 0x80 for byte in tag[6:10])
    assert len(tag) == 10 + ((tag[6] << 21) | (tag[7] << 14) | (tag[8] << 7) | tag[9])
    frames: list[tuple[bytes, bytes]] = []
    rest = tag[10:]
    while rest:
        frame_size = (rest[4] << 21) | (rest[5] << 14) | (rest[6] << 7) | rest[7]
        assert rest[8:10] == b"\x00\x00"
        frames.append((rest[:4], rest[10 : 10 + frame_size]))
        rest = rest[10 + frame_size :]
    return frames


def test_a_tag_with_umlauts_is_these_exact_bytes() -> None:
    tag = id3_tag((("title", "Mädchen"), ("artist", "Über"), ("genre", "Karaoke")))
    title = "Mädchen".encode()
    artist = "Über".encode()
    expected_frames = (
        b"TIT2" + bytes([0, 0, 0, len(title) + 1]) + b"\x00\x00\x03" + title
        + b"TPE1" + bytes([0, 0, 0, len(artist) + 1]) + b"\x00\x00\x03" + artist
        + b"TCON" + bytes([0, 0, 0, 8]) + b"\x00\x00\x03Karaoke"
    )  # fmt: skip
    assert tag == b"ID3\x04\x00\x00" + synchsafe(len(expected_frames)) + expected_frames


def test_the_comment_is_english_with_an_empty_description() -> None:
    tag = id3_tag((("comment", "Hi"),))
    header = b"ID3\x04\x00\x00\x00\x00\x00\x11"  # 17 bytes of frame
    frame = b"COMM\x00\x00\x00\x07\x00\x00" + b"\x03eng\x00Hi"
    assert tag == header + frame


def test_the_ensemble_word_is_a_user_text_frame_with_the_description_tag() -> None:
    tag = id3_tag((("tag", "Duet"),))
    frame = b"TXXX\x00\x00\x00\x09\x00\x00" + b"\x03TAG\x00Duet"
    assert tag == b"ID3\x04\x00\x00\x00\x00\x00\x13" + frame  # 19 bytes of frame


def test_a_tag_with_and_without_the_ensemble_word_differs_by_that_frame_only() -> None:
    base = (("title", "T"), ("genre", KARAOKE_GENRE), ("comment", KARAOKE_COMMENT))
    without, with_word = parse(id3_tag(base)), parse(id3_tag((*base, ("tag", "Trio"))))
    assert with_word[:-1] == without
    assert with_word[-1] == (b"TXXX", b"\x03TAG\x00Trio")


def test_without_an_artist_there_is_no_artist_frame() -> None:
    tag = id3_tag((("title", "T"), ("genre", KARAOKE_GENRE), ("comment", KARAOKE_COMMENT)))
    assert [frame for frame, _ in parse(tag)] == [b"TIT2", b"TCON", b"COMM"]
    assert b"TPE1" not in tag and b"TXXX" not in tag


def test_a_size_above_127_bytes_is_synchsafe() -> None:
    tag = id3_tag((("title", "x" * 200),))
    assert tag[6:10] == b"\x00\x00\x01\x53"  # the frame is 10 + 201 = 211 = 1 * 128 + 83 bytes
    assert len(tag) == 10 + 211


def test_synchsafe_sizes() -> None:
    assert synchsafe(0) == b"\x00\x00\x00\x00"
    assert synchsafe(127) == b"\x00\x00\x00\x7f"
    assert synchsafe(128) == b"\x00\x00\x01\x00"
    assert synchsafe(1 << 14) == b"\x00\x01\x00\x00"
    assert synchsafe(1 << 21) == b"\x01\x00\x00\x00"
    assert synchsafe(0x1234567) == bytes([0x09, 0x0D, 0x0A, 0x67])
    assert synchsafe((1 << 28) - 1) == b"\x7f\x7f\x7f\x7f"
    for bad in (-1, 1 << 28):
        with pytest.raises(ValueError, match="does not fit"):
            synchsafe(bad)


def test_no_tags_give_no_bytes() -> None:
    assert id3_tag(()) == b""


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValueError, match="album"):
        id3_tag((("album", "x"),))


@given(
    title=st.text(max_size=300),
    artist=st.one_of(st.none(), st.text(max_size=300)),
    comment=st.text(max_size=300),
)
def test_the_frames_read_back(title: str, artist: str | None, comment: str) -> None:
    pairs = [("title", title)] + ([("artist", artist)] if artist is not None else [])
    tag = id3_tag((*pairs, ("genre", "Karaoke"), ("comment", comment)))
    frames = parse(tag)
    assert [fid for fid, _ in frames] == [
        b"TIT2", *([b"TPE1"] if artist is not None else []), b"TCON", b"COMM",
    ]  # fmt: skip
    bodies = dict(frames)
    assert bodies[b"TIT2"] == b"\x03" + title.encode()
    assert bodies[b"COMM"] == b"\x03eng\x00" + comment.encode()
