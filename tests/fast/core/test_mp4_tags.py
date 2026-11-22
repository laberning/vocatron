"""Stage 1: the tags of the MP4 are built from fixed bytes, and the moov rebuild moves the index."""

import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fakes.mp4 import OLD_UDTA, co64, moov, stco, trak
from vocatron.core.mp4_tags import (
    Mp4Box,
    Mp4Error,
    box,
    locate_moov,
    read_header,
    read_tags,
    retag_moov,
    udta_box,
)

TAGS = (
    ("title", "Mädchen"),
    ("artist", "Über"),
    ("genre", "Karaoke"),
    ("comment", "Hi"),
    ("tag", "Duet"),
)


def test_the_udta_of_a_title_and_the_ensemble_word_is_these_exact_bytes() -> None:
    flags = b"\x00\x00\x00\x01\x00\x00\x00\x00"  # UTF-8 text, no locale
    ilst = (
        b"\x00\x00\x00\x68ilst"
        + b"\x00\x00\x00\x19\xa9nam" + b"\x00\x00\x00\x11data" + flags + b"T"
        + b"\x00\x00\x00\x47----"
        + b"\x00\x00\x00\x1cmean" + bytes(4) + b"com.apple.iTunes"
        + b"\x00\x00\x00\x0fname" + bytes(4) + b"TAG"
        + b"\x00\x00\x00\x14data" + flags + b"Duet"
    )  # fmt: skip
    hdlr = b"\x00\x00\x00\x21hdlr" + bytes(8) + b"mdirappl" + bytes(9)
    meta = b"\x00\x00\x00\x95meta" + bytes(4) + hdlr + ilst
    assert udta_box((("title", "T"), ("tag", "Duet"))) == b"\x00\x00\x00\x9dudta" + meta


def test_no_tags_give_no_udta() -> None:
    assert udta_box(()) == b""


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(Mp4Error, match="album"):
        udta_box((("album", "x"),))


def test_the_tags_read_back_in_order() -> None:
    assert read_tags(moov(udta_box(TAGS))) == TAGS
    assert read_tags(moov()) == ()


@given(
    values=st.lists(st.text(max_size=80), min_size=5, max_size=5),
    drop=st.sets(st.integers(0, 4)),
)
def test_any_text_reads_back(values: list[str], drop: set[int]) -> None:
    keys = ["title", "artist", "genre", "comment", "tag"]
    tags = tuple(
        (key, value)
        for i, (key, value) in enumerate(zip(keys, values, strict=True))
        if i not in drop
    )
    assert read_tags(moov(udta_box(tags))) == tags


def test_the_header_of_a_box_is_read_in_all_three_forms() -> None:
    assert read_header(box(b"free", b"abc"), 11) == (b"free", 8, 11)
    large = struct.pack(">I4sQ", 1, b"mdat", 20) + b"abcd"
    assert read_header(large, 20) == (b"mdat", 16, 20)
    assert read_header(struct.pack(">I4s", 0, b"mdat") + b"abc", 11) == (b"mdat", 8, 11)


@pytest.mark.parametrize(
    "head", [b"\x00\x00\x00", struct.pack(">I4s", 1, b"mdat"), box(b"free", b"abc")[:8] + b""]
)
def test_a_header_that_does_not_fit_is_refused(head: bytes) -> None:
    with pytest.raises(Mp4Error):
        read_header(head, 9)  # shorter than the size it states, or cut off


def test_a_size_below_the_header_is_refused() -> None:
    with pytest.raises(Mp4Error, match="does not fit"):
        read_header(struct.pack(">I4s", 4, b"free"), 100)


def test_moov_must_come_before_the_media() -> None:
    boxes = [Mp4Box(b"ftyp", 0, 20), Mp4Box(b"moov", 20, 100), Mp4Box(b"mdat", 120, 50)]
    assert locate_moov(boxes) == boxes[1]
    with pytest.raises(Mp4Error, match="not fast start"):
        locate_moov([boxes[0], boxes[2], Mp4Box(b"moov", 170, 100)])
    with pytest.raises(Mp4Error, match="no moov"):
        locate_moov([boxes[0]])


def offsets_of(data: bytes, kind: bytes) -> list[list[int]]:
    """Return the chunk offsets of every ``stco`` or ``co64`` table in ``data``."""
    found: list[list[int]] = []
    start = data.find(kind)
    while start != -1:
        count = struct.unpack(">I", data[start + 8 : start + 12])[0]
        code = f">{count}{'Q' if kind == b'co64' else 'I'}"
        width = 8 if kind == b"co64" else 4
        found.append(list(struct.unpack(code, data[start + 12 : start + 12 + count * width])))
        start = data.find(kind, start + 4)
    return found


def test_a_moov_with_tags_has_the_old_udta_replaced_and_the_offsets_moved() -> None:
    old = moov(trak(stco([100, 200]), b"a"), trak(co64([5, 1 << 40]), b"b"), OLD_UDTA)
    new = retag_moov(old, TAGS)
    delta = len(new) - len(old)
    assert delta == len(udta_box(TAGS)) - len(OLD_UDTA)
    assert b"Lavf" not in new
    assert read_tags(new) == TAGS
    assert offsets_of(new, b"stco") == [[100 + delta, 200 + delta]]
    assert offsets_of(new, b"co64") == [[5 + delta, (1 << 40) + delta]]


def test_without_tags_the_udta_is_dropped_and_the_offsets_shrink() -> None:
    old = moov(trak(stco([100]), b"a"), OLD_UDTA)
    new = retag_moov(old, ())
    assert len(new) == len(old) - len(OLD_UDTA)
    assert offsets_of(new, b"stco") == [[100 - len(OLD_UDTA)]]
    assert read_tags(new) == ()


@given(
    narrow=st.lists(st.integers(1 << 12, 1 << 20), max_size=6),
    wide=st.lists(st.integers(1 << 12, 1 << 40), max_size=6),
    traks=st.integers(1, 3),
    filler=st.binary(max_size=30),
    tags=st.lists(st.sampled_from(TAGS), max_size=5, unique=True),
    with_old=st.booleans(),
)
def test_every_offset_moves_by_the_change_and_every_other_box_stays_as_it_was(
    narrow: list[int], wide: list[int], traks: int, filler: bytes, tags: list[tuple[str, str]],
    with_old: bool,
) -> None:  # fmt: skip
    old_udta = OLD_UDTA if with_old else b""
    pieces = [trak(stco(narrow), filler) if i % 2 == 0 else trak(co64(wide), filler)
              for i in range(traks)]  # fmt: skip
    old = moov(*pieces, old_udta)
    new = retag_moov(old, tuple(tags))
    delta = len(new) - len(old)
    assert delta == len(udta_box(tuple(tags))) - len(old_udta)
    expected_narrow = [[o + delta for o in narrow] for i in range(traks) if i % 2 == 0]
    expected_wide = [[o + delta for o in wide] for i in range(traks) if i % 2 == 1]
    assert offsets_of(new, b"stco") == expected_narrow
    assert offsets_of(new, b"co64") == expected_wide
    # shifting the offsets back and removing the new udta gives the old moov without its udta
    assert retag_moov(new, ()) == retag_moov(old, ())
    assert read_tags(new) == tuple(tags)


def test_an_offset_that_no_longer_fits_its_table_is_an_error() -> None:
    old = moov(trak(stco([0xFFFFFFF0]), b""))
    with pytest.raises(Mp4Error, match="does not fit"):
        retag_moov(old, TAGS)
    with pytest.raises(Mp4Error, match="does not fit"):
        retag_moov(moov(trak(stco([3]), b""), OLD_UDTA), ())  # moves below zero


def test_a_table_that_is_cut_off_is_an_error() -> None:
    table = box(b"stco", bytes(4) + struct.pack(">II", 3, 1))  # three offsets announced, one held
    with pytest.raises(Mp4Error, match="does not hold"):
        retag_moov(moov(trak(table)), TAGS)


def test_bytes_that_are_not_exactly_one_moov_are_refused() -> None:
    with pytest.raises(Mp4Error, match="not exactly one moov"):
        retag_moov(box(b"free", b"x"), TAGS)
    with pytest.raises(Mp4Error, match="not exactly one moov"):
        retag_moov(moov() + b"extra", TAGS)
    with pytest.raises(Mp4Error, match="not a moov"):
        read_tags(box(b"free", b"x"))


def test_a_box_too_large_for_its_size_field_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vocatron.core.mp4_tags.MAX_SIZE", 10)
    with pytest.raises(Mp4Error, match="too large"):
        box(b"free", b"x" * 3)
    assert box(b"free", b"xx") == b"\x00\x00\x00\x0afreexx"


def test_boxes_that_are_no_tags_are_skipped_when_reading() -> None:
    other = box(b"udta", box(b"free", b"x") + box(b"meta", bytes(4) + box(b"free", b"y")))
    assert read_tags(moov(other, udta_box((("title", "T"),)))) == (("title", "T"),)
    item = box(b"\xa9nam", box(b"free", b"x"))
    broken = box(b"udta", box(b"meta", bytes(4) + box(b"ilst", item)))
    with pytest.raises(Mp4Error, match="no data atom"):
        read_tags(moov(broken))


def message(call: object) -> str:
    """Return the message of the ``Mp4Error`` that ``call`` raises."""
    assert callable(call)
    with pytest.raises(Mp4Error) as error:
        call()
    return str(error.value)


def test_the_messages_say_what_is_wrong() -> None:
    assert message(lambda: retag_moov(box(b"free", b"x"), ())) == (
        "the bytes are not exactly one moov box"
    )
    assert message(lambda: locate_moov([Mp4Box(b"mdat", 0, 9)])) == (
        "the moov box is not in front of the media; the file is not fast start"
    )
    assert message(lambda: locate_moov([])) == "the file has no moov box"
    assert message(lambda: read_header(b"abc", 3)) == "the file ends inside a box header"
    cut = struct.pack(">I4s", 1, b"mdat")
    assert message(lambda: read_header(cut, 99)) == "the file ends inside a box header"
    assert message(lambda: read_tags(box(b"free", b"x"))) == "the bytes are not a moov box"


def test_a_header_of_exactly_sixteen_bytes_is_a_whole_large_header() -> None:
    assert read_header(struct.pack(">I4sQ", 1, b"mdat", 16), 16) == (b"mdat", 16, 16)


def test_sizes_are_unsigned() -> None:
    assert message(lambda: read_header(struct.pack(">I4s", 1 << 31, b"free"), 100)) == (
        "the b'free' box has the size 2147483648, which does not fit"
    )
    large = struct.pack(">I4sQ", 1, b"mdat", 1 << 63)
    assert message(lambda: read_header(large, 100)) == (
        f"the b'mdat' box has the size {1 << 63}, which does not fit"
    )


def test_a_table_that_is_cut_off_names_its_kind_and_count() -> None:
    table = box(b"co64", bytes(4) + struct.pack(">II", 0xFFFFFFFF, 1))
    assert message(lambda: retag_moov(moov(trak(table)), ())) == (
        f"the {b'co64'!r} table does not hold 4294967295 offsets"
    )


def test_offsets_may_reach_the_limits_of_their_table_but_not_pass_them() -> None:
    delta = len(udta_box(TAGS)) - len(OLD_UDTA)
    for make, top in ((stco, (1 << 32) - 1), (co64, (1 << 64) - 1)):
        fits = retag_moov(moov(trak(make([top - delta]), b""), OLD_UDTA), TAGS)
        assert offsets_of(fits, b"stco" if make is stco else b"co64") == [[top]]
        message(
            lambda make=make, top=top: retag_moov(
                moov(trak(make([top - delta + 1]), b""), OLD_UDTA), TAGS
            )
        )
    zero = retag_moov(moov(trak(stco([len(OLD_UDTA)]), b""), OLD_UDTA), ())
    assert offsets_of(zero, b"stco") == [[0]]
    big = (1 << 63) + 5
    assert offsets_of(retag_moov(moov(trak(co64([big]), b"")), TAGS), b"co64") == [
        [big + len(udta_box(TAGS))]
    ]


def test_the_offset_error_says_so() -> None:
    old = moov(trak(stco([0xFFFFFFF0]), b""))
    assert message(lambda: retag_moov(old, TAGS)) == (
        "a chunk offset does not fit its table after the move"
    )


def test_unknown_boxes_and_atoms_are_skipped_before_and_between_tags() -> None:
    free = box(b"free", b"x")
    album = box(b"\xa9alb", box(b"data", bytes(8) + b"A"))
    ilst = box(b"ilst", album + _item_title())
    udta = box(b"udta", free + box(b"meta", bytes(4) + free + ilst))
    assert read_tags(moov(trak(stco([1])), udta)) == (("title", "T"),)


def _item_title() -> bytes:
    return udta_box((("title", "T"),))[8 + 8 + 4 + 33 + 8 :]


@pytest.mark.parametrize("kind", [b"stco", b"co64"])
def test_a_table_that_ends_before_its_count_is_an_error(kind: bytes) -> None:
    table = box(kind, bytes(7))  # version, flags and three of the four bytes of the count
    assert message(lambda: retag_moov(moov(trak(table)), TAGS)) == (
        f"the {kind!r} table ends before its count"
    )
    assert retag_moov(moov(trak(box(kind, bytes(8)))), ())  # an empty table is fine


def test_a_box_inside_moov_that_claims_more_than_moov_holds_is_refused() -> None:
    inner = struct.pack(">I4s", 40, b"trak") + bytes(8)  # 40 bytes stated, 16 there
    with pytest.raises(Mp4Error, match="does not fit"):
        retag_moov(box(b"moov", box(b"mvhd", bytes(4)) + inner), TAGS)


def test_an_item_without_data_says_so() -> None:
    item = box(b"\xa9nam", box(b"free", b"x"))
    broken = box(b"udta", box(b"meta", bytes(4) + box(b"ilst", item)))
    assert message(lambda: read_tags(moov(broken))) == "an item has no data atom"
