"""Stage 1: the mark of a lyrics file Vocatron wrote: found when unchanged, gone after any edit."""

import hashlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fakes.lyrics import ENTCHEN, HAENSCHEN
from vocatron.core.lyrics.document import Document, Kind, Line, SingerInfo, parse, write
from vocatron.core.lyrics.origin import write_marked, written_by_vocatron


def document(kind: Kind, *, singers: bool = False) -> Document:
    """A document of public-domain lines, as the lyrics stage writes it after a lookup."""
    lines = tuple(
        Line(text=text, time=5.0 + 4 * i if kind == "lrc" else None)
        for i, text in enumerate(ENTCHEN.splitlines())
    )
    tags = (("ar", "Volksgut"), ("ti", "Alle meine Entchen")) if kind == "lrc" else ()
    who = {1: SingerInfo(name="Anna", colour="#e0b000")} if singers else {}
    return Document(kind=kind, tags=tags, singers=who, lines=lines)


KINDS: list[Kind] = ["txt", "lrc"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("singers", [False, True])
def test_a_file_vocatron_wrote_carries_its_mark(kind: Kind, singers: bool) -> None:
    text = write_marked(document(kind, singers=singers))
    assert written_by_vocatron(text, kind)
    assert parse(text, kind).lines == document(kind).lines  # the mark is no line of the lyrics


def test_the_mark_is_the_creator_tag_of_an_lrc_and_a_header_key_of_a_txt() -> None:
    lrc = write_marked(document("lrc")).splitlines()
    assert lrc[0].startswith("[re: Vocatron ") and lrc[1] == "[ar: Volksgut]"
    txt = write_marked(document("txt")).splitlines()
    assert txt[0] == "---" and txt[1].startswith('written_by: "Vocatron ') and txt[2] == "---"
    assert txt[3] == ENTCHEN.splitlines()[0]


@pytest.mark.parametrize("kind", KINDS)
def test_a_marked_file_reads_back_and_writes_back_unchanged(kind: Kind) -> None:
    text = write_marked(document(kind, singers=True))
    assert write(parse(text, kind)) == text


@given(kind=st.sampled_from(KINDS), at=st.integers(min_value=0), char=st.characters())
def test_any_edit_removes_the_mark(kind: Kind, at: int, char: str) -> None:
    text = write_marked(document(kind))
    position = at % len(text)
    edited = text[:position] + char + text[position + 1 :]
    if edited != text:
        assert not written_by_vocatron(edited, kind)
    assert not written_by_vocatron(text[:position] + char + text[position:], kind)  # an insert


@pytest.mark.parametrize("kind", KINDS)
def test_a_removed_or_moved_mark_or_another_kind_is_no_mark(kind: Kind) -> None:
    rows = write_marked(document(kind)).splitlines(keepends=True)
    mark = 0 if kind == "lrc" else 1
    assert not written_by_vocatron("".join(rows[:mark] + rows[mark + 1 :]), kind)
    assert not written_by_vocatron("".join(rows[mark + 1 :] + rows[mark : mark + 1]), kind)
    other: Kind = "txt" if kind == "lrc" else "lrc"
    assert not written_by_vocatron("".join(rows), other)
    assert not written_by_vocatron("".join(rows).replace("\n", "\r\n"), kind)


@pytest.mark.parametrize("text", ["", "---\n", HAENSCHEN, write(document("txt"))])
def test_a_fans_file_has_no_mark(text: str) -> None:
    assert not written_by_vocatron(text, "txt")
    assert not written_by_vocatron(text, "lrc")


def test_a_fans_written_by_with_a_wrong_check_is_no_mark() -> None:
    forged = '---\nwritten_by: "Vocatron 0123456789abcdef"\n---\n' + ENTCHEN
    assert not written_by_vocatron(forged, "txt")
    assert not written_by_vocatron("[re: Vocatron 0123456789abcdef]\n" + ENTCHEN, "lrc")


@pytest.mark.parametrize("kind", KINDS)
def test_the_check_is_the_sha256_of_the_file_without_the_mark(kind: Kind) -> None:
    rows = write_marked(document(kind)).splitlines(keepends=True)
    mark = 0 if kind == "lrc" else 1
    rest = "".join(rows[:mark] + rows[mark + 1 :])
    assert hashlib.sha256(rest.encode()).hexdigest()[:16] in rows[mark]


def test_a_txt_mark_outside_a_header_is_no_mark() -> None:
    rest = "Vorwort\n" + ENTCHEN
    check = hashlib.sha256(rest.encode()).hexdigest()[:16]
    text = f'Vorwort\nwritten_by: "Vocatron {check}"\n' + ENTCHEN
    assert not written_by_vocatron(text, "txt")


@pytest.mark.parametrize("kind", KINDS)
def test_the_mark_needs_the_bytes_of_the_file_when_their_hash_is_given(kind: Kind) -> None:
    text = write_marked(document(kind))
    assert written_by_vocatron(text, kind, hashlib.sha256(text.encode()).hexdigest())
    crlf = text.replace("\n", "\r\n").encode()  # a reader with universal newlines hides this
    assert not written_by_vocatron(text, kind, hashlib.sha256(crlf).hexdigest())
    bom = b"\xef\xbb\xbf" + text.encode()
    assert not written_by_vocatron(text, kind, hashlib.sha256(bom).hexdigest())
