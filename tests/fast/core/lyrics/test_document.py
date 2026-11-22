"""Stage 1: the lyrics file format of ADR-0008: parser, writer and the round trip."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from syrupy.assertion import SnapshotAssertion

from fakes.lyrics import ENTCHEN, HAENSCHEN
from vocatron.core.lyrics.document import (
    SECOND_VOICE,
    Document,
    FormatError,
    Kind,
    Line,
    Mark,
    Resolved,
    SingerInfo,
    Voice,
    canonical_singers,
    format_time,
    has_singer_marks,
    is_single_singer,
    offset_of,
    parse,
    parse_length,
    parse_numbered,
    resolve_singers,
    write,
)

WORDS = st.text(alphabet="abcdefghijklmnopqrstuvwxyzäöüß ,.!?'", min_size=1, max_size=30).map(
    str.strip
)
TEXT = WORDS.filter(bool)
SINGING = st.sampled_from(["1", "2", "5", "1,3", "2,4,5", "all"])
NAMES = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S"), exclude_characters="\\\"'"),
    min_size=1,
    max_size=12,
).filter(lambda name: "," not in name and "[" not in name and "]" not in name)
COLOURS = st.from_regex(r"#[0-9a-f]{6}", fullmatch=True)
SINGERS = st.dictionaries(
    st.integers(1, 5),
    st.builds(SingerInfo, name=st.none() | NAMES, colour=st.none() | COLOURS),
    max_size=5,
)


def centis(count: int) -> float:
    """The time of a line in seconds, computed as the parser computes it."""
    minutes, rest = divmod(count, 6000)
    seconds, hundredths = divmod(rest, 100)
    return minutes * 60 + seconds + hundredths / 100


@st.composite
def marked_lines(draw: st.DrawFn, kind: Kind, blank: bool) -> Line:
    """A line with no marks, or with marks at any word and at the end (one space between words)."""
    text = draw(TEXT)
    marks: tuple[Mark, ...] = ()
    if draw(st.booleans()):
        text = " ".join(text.split())
        positions = sorted(draw(st.lists(st.integers(0, len(text.split())), max_size=4)))
        marks = tuple(Mark(word=word, singers=draw(SINGING)) for word in positions)
    voice: Voice = draw(st.sampled_from([1, 1, 2]))
    if voice == SECOND_VOICE:
        text = " ".join(text.split())  # a line with a voice mark has its words one space apart
    time = centis(draw(st.integers(0, 60_000))) if kind == "lrc" else None
    return Line(text=text, marks=marks, voice=voice, time=time, blank_before=blank)


@st.composite
def documents(draw: st.DrawFn, kind: Kind) -> Document:
    count = draw(st.integers(0, 8))
    lines = tuple(
        draw(marked_lines(kind, index > 0 and draw(st.booleans()))) for index in range(count)
    )
    tags = (
        tuple(draw(st.lists(st.tuples(st.sampled_from(["ar", "ti", "al"]), WORDS), max_size=3)))
        if kind == "lrc"
        else ()
    )
    singers = {
        n: SingerInfo(name=info.name, colour=info.colour) for n, info in draw(SINGERS).items()
    }
    written_by = draw(st.none() | NAMES) if kind == "txt" else None
    return Document(kind=kind, tags=tags, singers=singers, lines=lines, written_by=written_by)


@given(documents("txt"))
def test_a_txt_document_survives_write_and_parse(document: Document) -> None:
    assert parse(write(document), "txt") == document


@given(documents("lrc"))
def test_an_lrc_document_survives_write_and_parse(document: Document) -> None:
    assert parse(write(document), "lrc") == document


@given(documents("txt") | documents("lrc"))
def test_writing_a_parsed_canonical_file_gives_the_same_text(document: Document) -> None:
    text = write(document)
    assert write(parse(text, document.kind)) == text


def singers_of(text: str, kind: Kind = "txt") -> list[Resolved]:
    return resolve_singers(parse(text, kind).lines)


def test_plain_lines_blocks_and_marks_are_read() -> None:
    document = parse(
        "{1} Hänschen klein\n{2} ging allein\n\nin die weite Welt\n{all} hinein\n", "txt"
    )
    assert [(line.marks, line.text, line.blank_before) for line in document.lines] == [
        ((Mark(word=0, singers="1"),), "Hänschen klein", False),
        ((Mark(word=0, singers="2"),), "ging allein", False),
        ((), "in die weite Welt", True),
        ((Mark(word=0, singers="all"),), "hinein", False),
    ]
    assert [who.singers for who in resolve_singers(document.lines)] == ["1", "2", "2", "all"]
    assert has_singer_marks(document.lines)


def test_a_mark_inside_a_line_is_a_turn_and_holds_on_the_next_line() -> None:
    document = parse("{1} walk with me {2} hold me\nstay {1,3} near\n", "txt")
    assert [line.text for line in document.lines] == ["walk with me hold me", "stay near"]
    assert document.lines[0].marks == (
        Mark(word=0, singers="1"),
        Mark(word=3, singers="2"),
    )
    assert resolve_singers(document.lines) == [
        Resolved("1", (Mark(word=3, singers="2"),)),
        Resolved("2", (Mark(word=1, singers="1,3"),)),
    ]


def test_a_mark_glued_to_the_word_after_it_counts_but_not_the_word_before() -> None:
    document = parse("{2}Then Ben{3}\nBen{2} sings {all}{1}me\n", "txt")
    assert [line.text for line in document.lines] == ["Then Ben{3}", "Ben{2} sings me"]
    assert document.lines[0].marks == (Mark(word=0, singers="2"),)
    assert document.lines[1].marks == (Mark(word=2, singers="all"), Mark(word=2, singers="1"))
    assert resolve_singers(document.lines)[1] == Resolved("2", (Mark(word=2, singers="1"),))


def test_marks_before_the_first_word_and_a_mark_at_the_end_of_a_line() -> None:
    assert singers_of("{2}\nhello there {3}\nfriend\n") == [  # the first line has no words
        Resolved("1"),
        Resolved("2"),
        Resolved("3"),
    ]
    document = parse("hello {2}\n", "txt")
    assert document.lines[0].marks == (Mark(word=1, singers="2"),)


def test_a_mark_that_names_the_singers_already_singing_makes_no_turn() -> None:
    assert singers_of("a {1} b {2} c {2} d\n") == [Resolved("1", (Mark(word=2, singers="2"),))]


def test_a_line_without_marks_keeps_its_spacing_and_a_line_with_marks_has_single_spaces() -> None:
    assert parse("a  b   c\n", "txt").lines[0].text == "a  b   c"
    assert parse("{2} a  b   c\n", "txt").lines[0].text == "a b c"


def test_words_before_the_first_mark_belong_to_singer_one() -> None:
    assert singers_of("one two {2} three\n") == [Resolved("1", (Mark(word=2, singers="2"),))]


def test_groups_are_canonical_and_the_last_mark_at_a_position_counts() -> None:
    document = parse("{3,1} eins\n", "txt")
    assert document.lines[0].marks == (Mark(word=0, singers="1,3"),)
    assert write(document) == "{1,3} eins\n"
    assert canonical_singers("3,1,3") == "1,3"
    assert singers_of("{1}{2} eins\n") == [Resolved("2")]


@pytest.mark.parametrize(
    "text",
    ["1: Hänschen klein", "all: hinein", "M: eins", "F: zwei", "D: drei", "1,3: vier",
     "{ALL} laut", "{ 2 } leise", "{1, 3} laut", "{6} nein", "{0} nein", "{x} nein", "{} leer",
     "{1 3} laut"],
)  # fmt: skip
def test_old_prefixes_and_other_braces_are_lyrics(text: str) -> None:
    (line,) = parse(text + "\n", "txt").lines
    assert (line.text, line.marks) == (text, ())


def test_walaoke_style_aliases_are_not_read_any_more() -> None:
    assert singers_of("M: eins\nF: zwei\nD: drei\n") == [Resolved("1")] * 3


def test_the_voice_mark_puts_a_line_on_the_second_voice_and_only_at_its_start() -> None:
    document = parse("{&} {2} ging allein\n{&}Hänschen klein\nHänschen {&} klein\nHänschen", "txt")
    first, glued, middle, plain = document.lines
    assert (first.voice, first.text, first.marks) == (
        2,
        "ging allein",
        (Mark(word=0, singers="2"),),
    )
    assert (glued.voice, glued.text, glued.marks) == (2, "Hänschen klein", ())
    assert (middle.voice, middle.text) == (1, "Hänschen {&} klein")  # not at the start: lyrics
    assert plain.voice == 1


def test_the_voice_mark_comes_after_the_time_tag_and_is_written_first() -> None:
    text = "[00:05.00] {&} {2} ging allein\n"
    document = parse(text, "lrc")
    assert document.lines[0].voice == 2
    assert write(document) == text
    assert parse("[00:05.00] {2} {&} ging allein", "lrc").lines[0].voice == 2


def test_a_line_without_marks_belongs_to_singer_one() -> None:
    document = parse(ENTCHEN, "txt")
    assert not has_singer_marks(document.lines)
    assert {who.singers for who in resolve_singers(document.lines)} == {"1"}


def test_marks_in_an_lrc_come_after_the_time_tag_and_between_word_tags() -> None:
    text = (
        "[00:05.00] {2} <00:05.00>Then <00:05.50>Ben <00:06.00>{1}sings <00:06.50>\n"
        "[00:07.00] <00:07.00>{all}hello <00:07.50>there <00:08.00>\n"
    )
    document = parse(text, "lrc")
    assert [line.text for line in document.lines] == ["Then Ben sings", "hello there"]
    assert document.lines[0].marks == (Mark(word=0, singers="2"), Mark(word=2, singers="1"))
    assert document.lines[1].marks == (Mark(word=0, singers="all"),)
    assert write(parse(write(document), "lrc")) == write(document)
    assert write(document).splitlines()[0] == "[00:05.00] {2} Then Ben {1} sings"


def test_the_singer_header_of_a_txt_file_gives_names_and_colours() -> None:
    text = (
        '---\nsingers:\n  1: {name: Anna, colour: "#e0b000"}\n  2: Ben\n---\n'
        "{1} Hänschen klein\n{2} ging allein\n"
    )
    document = parse(text, "txt")
    assert document.singers == {
        1: SingerInfo(name="Anna", colour="#e0b000"),
        2: SingerInfo(name="Ben"),
    }
    assert [line.text for line in document.lines] == ["Hänschen klein", "ging allein"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("---\nsingers:\n  1: Anna\n{1} Hänschen\n", "^the singer header is not closed"),
        ("---\nsingers: [\n---\nx\n", "invalid"),
        ("---\nsingers:\n  6: Anna\n---\nx\n", "numbered 1 to 5"),
        ("---\nsingers:\n  1: {colour: red}\n---\nx\n", "invalid"),
        ("---\nsinger: x\n---\nx\n", "invalid"),
    ],
)
def test_an_invalid_header_is_a_format_error(text: str, message: str) -> None:
    with pytest.raises(FormatError, match=message):
        parse(text, "txt")


def test_an_lrc_file_with_tags_times_and_singers_is_read() -> None:
    text = (
        "[ar: Volkslied]\n[ti: Hänschen klein]\n[length: 1:00]\n"
        "[singer1: Anna, #e0b000]\n[singer2: Ben]\n[singer3:]\n"
        "[00:05.00] {1} Hänschen klein\n"
        "[00:09.5] {2} ging allein\n"
        "[00:13:25] in die <00:14.00>weite <00:14.50>Welt\n"
    )
    document = parse(text, "lrc")
    assert document.tags == (("ar", "Volkslied"), ("ti", "Hänschen klein"), ("length", "1:00"))
    assert document.singers == {
        1: SingerInfo(name="Anna", colour="#e0b000"),
        2: SingerInfo(name="Ben"),
        3: SingerInfo(),
    }
    assert [(line.time, [m.singers for m in line.marks], line.text) for line in document.lines] == [
        (5.0, ["1"], "Hänschen klein"),
        (9.5, ["2"], "ging allein"),
        (13.25, [], "in die weite Welt"),
    ]
    assert parse_length("1:00") == 60
    assert parse_length("nonsense") is None


def test_a_row_with_several_time_tags_becomes_several_lines_in_time_order() -> None:
    document = parse("[00:30.00] Refrain\n[00:10.00][00:50.00] Hänschen klein\n", "lrc")
    assert [(line.time, line.text) for line in document.lines] == [
        (10.0, "Hänschen klein"),
        (30.0, "Refrain"),
        (50.0, "Hänschen klein"),
    ]


def test_one_row_with_several_time_tags_puts_the_whole_file_in_time_order() -> None:
    document = parse("[00:10.00][00:30.00] Hänschen klein\n[00:20.00] ging allein\n", "lrc")
    assert [line.time for line in document.lines] == [10.0, 20.0, 30.0]


def test_a_byte_order_mark_and_untimed_lrc_rows_are_accepted() -> None:
    document = parse("﻿Hänschen klein\n[00:01.00] ging allein\n", "lrc")
    assert [(line.time, line.text) for line in document.lines] == [
        (None, "Hänschen klein"),
        (1.0, "ging allein"),
    ]


def test_names_that_yaml_would_misread_are_quoted_when_written() -> None:
    document = Document(
        kind="txt",
        singers={1: SingerInfo(name="yes"), 2: SingerInfo(name="Anna: the first")},
        lines=(Line(text="Hänschen klein"),),
    )
    assert parse(write(document), "txt") == document


def test_format_time_rounds_to_centiseconds() -> None:
    assert format_time(75.004) == "01:15.00"
    assert format_time(0.5) == "00:00.50"


def test_an_empty_document_is_an_empty_file() -> None:
    assert write(Document(kind="txt")) == ""


def test_the_canonical_form_is_golden(snapshot: SnapshotAssertion) -> None:
    txt = parse(
        "{1} Hänschen klein\n{2} ging allein\n\n{all} in die weite {1,2} Welt hinein\n", "txt"
    )
    lrc = parse(
        "[ti: Hänschen klein]\n[singer1: Anna, #e0b000]\n"
        "[00:01.2] {1} Stock und {2} Hut\n[00:03] steht ihm gut\n",
        "lrc",
    )
    assert write(txt) == snapshot
    assert write(lrc) == snapshot
    assert write(parse(HAENSCHEN, "txt")) == HAENSCHEN


def test_an_empty_header_names_no_singers() -> None:
    document = parse("---\n---\nHänschen klein\n", "txt")
    assert document.singers == {}
    assert [line.text for line in document.lines] == ["Hänschen klein"]


def test_without_header_a_fence_row_is_a_line_of_text() -> None:
    document = parse("---\nHänschen klein\n", "txt", header=False)
    assert [line.text for line in document.lines] == ["---", "Hänschen klein"]


def test_the_rows_of_the_lines_are_those_of_the_file() -> None:
    txt = parse_numbered("---\nsingers:\n  1: Anna\n---\n\nHänschen klein\n\nging allein\n", "txt")
    assert txt.rows == (6, 8)
    assert [line.blank_before for line in txt.document.lines] == [False, True]
    lrc = parse_numbered("[ti: x]\n\n[00:02.00][00:00.50] Stock und Hut\nsteht ihm gut\n", "lrc")
    assert [(line.time, line.text) for line in lrc.document.lines] == [
        (None, "steht ihm gut"),
        (0.5, "Stock und Hut"),
        (2.0, "Stock und Hut"),
    ]
    assert lrc.rows == (4, 3, 3)
    assert not lrc.document.lines[1].blank_before  # a blank row before the first line counts not


def test_the_canonical_form_spells_names_colours_and_empty_values_exactly() -> None:
    txt = Document(
        kind="txt",
        singers={
            1: SingerInfo(name="Anna", colour="#e0b000"),
            2: SingerInfo(name="Ben"),
            3: SingerInfo(colour="#00ff00"),
            4: SingerInfo(),
            5: SingerInfo(name="Jörg: der Zweite"),
        },
        lines=(Line(text="Hänschen klein", marks=(Mark(word=0, singers="1"),)),),
    )
    assert write(txt) == (
        "---\nsingers:\n"
        '  1: {name: Anna, colour: "#e0b000"}\n'
        "  2: Ben\n"
        '  3: {colour: "#00ff00"}\n'
        "  4: {}\n"
        '  5: "Jörg: der Zweite"\n'
        "---\n{1} Hänschen klein\n"
    )
    assert parse(write(txt), "txt") == txt
    lrc = Document(
        kind="lrc",
        tags=(("ti", ""), ("ar", "Volkslied")),
        singers={1: SingerInfo(), 2: SingerInfo(name="Ben")},
        lines=(
            Line(text="", time=1.0),
            Line(text="ging allein", marks=(Mark(word=0, singers="2"),), time=2.0),
        ),
    )
    assert write(lrc) == (
        "[ti:]\n[ar: Volkslied]\n[singer1:]\n[singer2: Ben]\n"
        "[00:01.00]\n[00:02.00] {2} ging allein\n"
    )


@pytest.mark.parametrize(
    ("offset", "expected"),
    [("+500", 4.5), ("500", 4.5), ("-250", 5.25), ("0", 5.0), ("soon", 5.0)],
)
def test_the_offset_tag_moves_every_line_time(offset: str, expected: float) -> None:
    """A positive offset (milliseconds) shows the lyrics earlier: it is subtracted."""
    text = f"[ti: Hänschen klein]\n[offset: {offset}]\n[00:05.00] Hänschen klein\nging allein\n"
    document = parse(text, "lrc")
    assert [line.time for line in document.lines] == [expected, None]
    assert ("offset", offset) in document.tags
    assert write(document) == text  # the tag stays, the time tags are as in the file


def test_the_last_offset_tag_counts() -> None:
    assert offset_of([("offset", "100"), ("OFFSET", "-300"), ("ti", "x")]) == -0.3
    assert offset_of([("ti", "100")]) == 0.0


@given(
    st.lists(st.integers(0, 60_000), min_size=1, max_size=5),
    st.integers(-5_000, 5_000),
)
def test_a_file_with_an_offset_is_written_back_unchanged(centis_list: list[int], ms: int) -> None:
    rows = [f"[offset: {ms:+d}]"] + [
        f"[{format_time(c / 100)}] Hänschen klein" for c in centis_list
    ]
    text = "\n".join(rows) + "\n"
    assert write(parse(text, "lrc")) == text


def test_one_singer_is_a_number_and_groups_and_all_are_not() -> None:
    assert is_single_singer("2")
    assert not is_single_singer("1,3")
    assert not is_single_singer("all")
