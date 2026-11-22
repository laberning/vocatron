"""Stage 1: cleaning of section headings, repeat markers and credits."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from syrupy.assertion import SnapshotAssertion

from fakes.lyrics import ENTCHEN_CLEANED, ENTCHEN_MESSY, HAENSCHEN, MESSY, VOGEL
from vocatron.core.glyphs import UndrawableLetter
from vocatron.core.lyrics.clean import Removal, classify, clean, strip_repeat
from vocatron.core.lyrics.document import Line, Mark, parse, parse_numbered, resolve_singers

SUNG = [line for text in (HAENSCHEN, VOGEL) for line in text.splitlines()]
SECTIONS = ["[Chorus]", "[Verse 2]", "Refrain:", "(Bridge)", "Strophe 2", "[Intro]", "[Refrain x2]"]
CREDITS = [
    "Written by Volksgut",
    "Text: Volksgut",
    "Text & Musik: Volksweise",
    "Melodie: Volksweise",
    "Musik von Nobody",
    "© Niemand",
    "Source: Nowhere",
]
MARKERS = ["(2x)", "x2", "[3x]", "2x", "(Refrain 2x)", "(bis)"]


def texts(rows: list[str]) -> tuple[Line, ...]:
    return tuple(Line(text=row) for row in rows)


@pytest.mark.parametrize("text", SECTIONS)
def test_section_headings_are_recognised(text: str) -> None:
    assert classify(text) == "section"


@pytest.mark.parametrize("text", CREDITS)
def test_credit_lines_are_recognised(text: str) -> None:
    assert classify(text) == "credit"


@pytest.mark.parametrize("text", SUNG)
def test_sung_lines_are_not_junk(text: str) -> None:
    assert classify(text) is None
    assert strip_repeat(text).text == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hänschen klein (2x)", "Hänschen klein"),
        ("Hänschen klein x2", "Hänschen klein"),
        ("(2x) Hänschen klein", "Hänschen klein"),
        ("Hänschen klein (3x) [2x]", "Hänschen klein"),
        ("Hänschen klein", "Hänschen klein"),
    ],
)
def test_repeat_markers_are_stripped(text: str, expected: str) -> None:
    assert strip_repeat(text).text == expected


def test_the_messy_song_is_cleaned_and_everything_removed_is_reported() -> None:
    result = clean(parse(ENTCHEN_MESSY, "txt").lines)
    assert [line.text for line in result.lines] == ENTCHEN_CLEANED
    assert [(r.line, r.kind) for r in result.removals] == [
        (1, "section"),
        (3, "repeat"),
        (4, "section"),
        (6, "repeat"),
        (7, "credit"),
    ]
    assert result.removals[1].text == "schwimmen auf dem See (2x)"  # the original is kept


def test_a_block_break_moves_to_the_next_line_that_stays() -> None:
    lines = parse("Hänschen klein\n\n[Chorus]\nging allein\n", "txt").lines
    kept = clean(lines).lines
    assert [(line.text, line.blank_before) for line in kept] == [
        ("Hänschen klein", False),
        ("ging allein", True),
    ]


def test_empty_lines_are_dropped_without_a_report() -> None:
    result = clean(texts(["", "  ", "---", "* * *", "♪", "Hänschen klein"]))
    assert [line.text for line in result.lines] == ["Hänschen klein"]
    assert result.removals == ()


@pytest.mark.parametrize("name", sorted(MESSY))
def test_the_cleaned_messy_songs_are_golden(name: str, snapshot: SnapshotAssertion) -> None:
    document, rows = parse_numbered(MESSY[name], "txt")
    result = clean(document.lines, rows)
    assert result.model_dump() == snapshot


def test_removals_name_the_rows_of_the_file() -> None:
    document, rows = parse_numbered(ENTCHEN_MESSY, "txt")
    assert [r.line for r in clean(document.lines, rows).removals] == [1, 3, 5, 7, 9]


@pytest.mark.parametrize("text", ["[Refrain x2]", "Refrain (2x)", "(Strophe 2) x3"])
def test_a_heading_with_a_repeat_marker_is_a_heading(text: str) -> None:
    (removal,) = clean(texts([text, "Hänschen klein"])).removals
    assert removal.kind == "section"


@given(
    st.lists(
        st.tuples(
            st.sampled_from(SUNG),
            st.sampled_from(["", *MARKERS]),
            st.lists(st.sampled_from([*SECTIONS, *CREDITS]), max_size=2),
        ),
        min_size=1,
        max_size=10,
    )
)
def test_junk_added_to_a_song_never_survives_cleaning(
    rows: list[tuple[str, str, list[str]]],
) -> None:
    messy: list[str] = []
    for sung, marker, junk in rows:
        messy += junk
        messy.append(f"{sung} {marker}".strip())
    result = clean(texts(messy))
    assert [line.text for line in result.lines] == [sung for sung, _, _ in rows]
    assert len(result.removals) == sum(len(junk) + bool(marker) for _, marker, junk in rows)


@given(
    st.lists(
        st.sampled_from([*SUNG, *SECTIONS, *CREDITS, *MARKERS, "", "---", "Hänschen klein (2x)"])
    )
)
def test_cleaning_twice_changes_nothing(rows: list[str]) -> None:
    once = clean(texts(rows))
    assert clean(once.lines).lines == once.lines
    assert clean(once.lines).removals == ()


def at(word: int, singers: str) -> Mark:
    return Mark(word=word, singers=singers)


def per_word(lines: tuple[Line, ...] | list[Line]) -> list[list[str]]:
    """Who sings each word of every line, from the resolved singers."""
    found: list[list[str]] = []
    for line, who in zip(lines, resolve_singers(lines), strict=True):
        turns = {turn.word: turn.singers for turn in who.turns}
        current = who.singers
        words: list[str] = []
        for index in range(len(line.text.split())):
            current = turns.get(index, current)
            words.append(current)
        found.append(words)
    return found


def test_the_marks_of_a_removed_line_move_to_the_next_line_that_stays() -> None:
    lines = (
        Line(text="Hänschen klein", marks=(at(0, "1"),)),
        Line(text="[Chorus]", marks=(at(0, "2"),)),
        Line(text="Written by Volksgut", marks=(at(0, "3"),)),
        Line(text="ging allein", marks=(at(1, "1,3"),)),
        Line(text="---", marks=(at(0, "all"),)),
    )
    result = clean(lines)
    assert [line.text for line in result.lines] == ["Hänschen klein", "ging allein"]
    assert result.lines[1].marks == (at(0, "2"), at(0, "3"), at(1, "1,3"))  # the last one counts
    assert [who.singers for who in resolve_singers(result.lines)] == ["1", "3"]


def test_marks_shift_with_the_words_a_line_loses() -> None:
    line = Line(text="(2x) Hänschen klein ging (3x)", marks=(at(0, "2"), at(2, "3"), at(5, "1")))
    (kept,) = clean([line]).lines
    assert kept.text == "Hänschen klein ging"
    assert kept.marks == (at(0, "2"), at(1, "3"), at(3, "1"))  # the last one is at the end


def test_a_mark_on_a_removed_word_moves_to_the_next_word_that_stays() -> None:
    (kept,) = clean([Line(text="(2x) Hänschen klein", marks=(at(1, "2"),))]).lines
    assert kept.text == "Hänschen klein"
    assert kept.marks == (at(0, "2"),)


@given(
    st.lists(
        st.tuples(
            st.sampled_from(SUNG),
            st.sampled_from(["", *MARKERS]),
            st.booleans(),
            st.lists(
                st.tuples(st.sampled_from([*SECTIONS, *CREDITS]), st.integers(1, 5)), max_size=2
            ),
            st.lists(st.tuples(st.integers(0, 12), st.integers(1, 5)), max_size=3),
        ),
        min_size=1,
        max_size=8,
    )
)
def test_cleaning_keeps_the_singers_of_every_word_that_stays(
    rows: list[tuple[str, str, bool, list[tuple[str, int]], list[tuple[int, int]]]],
) -> None:
    messy: list[Line] = []
    sung: list[tuple[int, int]] = []  # the line and the number of leading words to skip
    for text, marker, leading, junk, marks in rows:
        messy += [Line(text=word, marks=(at(0, str(who)),)) for word, who in junk]
        full = f"{marker} {text}" if marker and leading else f"{text} {marker}".strip()
        count = len(full.split())
        places = sorted((min(word, count), str(who)) for word, who in marks)
        sung.append((len(messy), len(marker.split()) if marker and leading else 0))
        messy.append(Line(text=full, marks=tuple(at(word, who) for word, who in places)))
    expected = [
        per_word(messy)[index][skip : skip + len(text.split())]
        for (index, skip), (text, *_) in zip(sung, rows, strict=True)
    ]
    result = clean(messy)
    assert [line.text for line in result.lines] == [text for text, *_ in rows]
    assert per_word(result.lines) == expected


def test_stripping_tells_how_many_characters_came_off_the_start() -> None:
    assert strip_repeat("(2x) Hänschen klein (3x)") == ("Hänschen klein", 5)
    assert strip_repeat("Hänschen klein x2") == ("Hänschen klein", 0)
    assert strip_repeat("x2 (bis) Hänschen") == ("Hänschen", 9)


SQRT = "\u221a"
NOTE = "\u266a"
HEART = "\u2665"
DRAWABLE = frozenset(ord(c) for c in "abcdefghijklmnopqrstuvwxyzäöüß0123456789 ,.'")


def test_a_symbol_the_font_lacks_is_dropped_and_reported_with_line_and_code_point() -> None:
    lines = texts(["ab cd", f"ef {SQRT} gh", "ij"])
    result = clean(lines, [10, 11, 12], DRAWABLE)
    assert [line.text for line in result.lines] == ["ab cd", "ef gh", "ij"]
    assert result.removals == (
        Removal(line=11, kind="glyph", text=f"ef {SQRT} gh", character=0x221A),
    )


def test_each_symbol_of_a_line_is_reported_once() -> None:
    result = clean(texts([f"{HEART}ab{SQRT}{HEART} cd"]), None, DRAWABLE)
    assert [line.text for line in result.lines] == ["ab cd"]
    assert [(r.line, r.character) for r in result.removals] == [(1, 0x2665), (1, 0x221A)]


def test_note_signs_around_sung_words_go_without_a_report() -> None:
    result = clean(texts([f"{NOTE} ab cd {NOTE}"]), None, DRAWABLE)
    assert [line.text for line in result.lines] == ["ab cd"]
    assert result.removals == ()


def test_a_line_that_is_only_symbols_is_dropped_without_a_report_as_before() -> None:
    result = clean(texts([f"{NOTE} {SQRT}", "ab"]), None, DRAWABLE)
    assert [line.text for line in result.lines] == ["ab"]
    assert result.removals == ()


def test_without_the_font_nothing_is_dropped() -> None:
    result = clean(texts([f"ab {SQRT} cd"]))
    assert [line.text for line in result.lines] == [f"ab {SQRT} cd"]


def test_singer_marks_follow_their_words_when_a_word_of_symbols_goes() -> None:
    line = Line(
        text=f"ab {SQRT} cd ef",
        marks=(Mark(word=0, singers="1"), Mark(word=1, singers="2"), Mark(word=3, singers="all")),
    )
    (kept,) = clean([line], None, DRAWABLE).lines
    assert kept.text == "ab cd ef"
    # the mark on the removed word moves to the next word that stays; word 3 (ef) becomes 2
    assert [(m.word, m.singers) for m in kept.marks] == [(0, "1"), (1, "2"), (2, "all")]


def test_a_mark_at_the_end_of_a_line_stays_at_the_end() -> None:
    line = Line(text=f"ab cd {SQRT}", marks=(Mark(word=3, singers="2"),))
    (kept,) = clean([line], None, DRAWABLE).lines
    assert (kept.text, [m.word for m in kept.marks]) == ("ab cd", [2])


def test_marks_still_shift_when_a_repeat_marker_and_a_symbol_come_together() -> None:
    line = Line(text=f"(2x) ab {SQRT} cd", marks=(Mark(word=3, singers="2"),))
    (kept,) = clean([line], None, DRAWABLE).lines
    assert (kept.text, [m.word for m in kept.marks]) == ("ab cd", [1])


def test_a_letter_the_font_lacks_stops_the_cleaning_with_the_row_of_its_line() -> None:
    with pytest.raises(UndrawableLetter) as caught:
        clean(texts(["ab", "cd \u0416"]), [3, 7], DRAWABLE)
    assert (caught.value.codepoint, caught.value.where) == (0x416, "line 7")


def test_a_letter_in_a_removed_line_does_not_matter() -> None:
    result = clean(texts(["[Chorus \u0416]", "ab"]), None, DRAWABLE)
    assert [line.text for line in result.lines] == ["ab"]


@given(
    st.lists(
        st.text(
            alphabet=st.sampled_from([*"abcdefg \t", SQRT, NOTE, "\u2665", "-", "!"]), max_size=30
        ),
        max_size=8,
    )
)
def test_cleaning_never_leaves_a_character_outside_the_font(rows: list[str]) -> None:
    font = frozenset(ord(c) for c in "abcdefg -!")  # no tab either
    result = clean(texts(rows), None, font)
    assert all(ord(char) in font for line in result.lines for char in line.text)
    assert clean(result.lines, None, font).removals == ()  # cleaning cleaned lines changes nothing


def test_a_tab_the_font_lacks_becomes_a_space_without_a_report() -> None:
    result = clean(texts(["ab\tcd"]), None, DRAWABLE)
    assert ([line.text for line in result.lines], result.removals) == (["ab cd"], ())


def test_a_line_whose_word_characters_all_go_is_dropped_with_its_reports() -> None:
    result = clean(texts(["_ √", "ab"]), None, DRAWABLE)  # this font has no underscore
    assert [line.text for line in result.lines] == ["ab"]
    assert [r.character for r in result.removals] == [ord("_"), 0x221A]


def test_a_mark_at_the_end_stays_at_the_end_when_a_word_in_the_middle_goes() -> None:
    line = Line(text=f"ab {SQRT} cd", marks=(Mark(word=3, singers="2"),))
    (kept,) = clean([line], None, DRAWABLE).lines
    assert (kept.text, [m.word for m in kept.marks]) == ("ab cd", [2])


def test_a_mark_past_the_last_word_stays_at_the_end() -> None:
    line = Line(text=f"ab {SQRT} cd", marks=(Mark(word=9, singers="2"),))
    (kept,) = clean([line], None, DRAWABLE).lines
    assert [m.word for m in kept.marks] == [2]
