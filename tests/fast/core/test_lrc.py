"""Stage 1: the enhanced LRC of a song (ADR-0008, ADR-0009)."""

import re

import pytest
from syrupy.assertion import SnapshotAssertion

from fakes.timed import timed_song
from vocatron.core.lrc import Heading, enhanced_lrc
from vocatron.core.lyrics.document import (
    Mark,
    Resolved,
    SingerInfo,
    parse,
    parse_length,
    resolve_singers,
)
from vocatron.core.lyrics.file import LyricLine
from vocatron.core.syllables import Syllable, SyllableWord

SONG = timed_song("Alle meine Entchen\nschwimmen auf dem See\nKöpfchen in das Wasser", start=12.3)


def test_the_lrc_of_a_folk_song_is_golden(snapshot: SnapshotAssertion) -> None:
    text = enhanced_lrc(
        SONG.words, SONG.lines, Heading("Alle meine Entchen", "Volkslied", 75.4), {}
    )
    assert text == snapshot


def test_every_line_has_its_time_and_a_tag_for_every_word_and_one_for_its_end() -> None:
    text = enhanced_lrc(SONG.words, SONG.lines, Heading("T", None, None), {})
    row = next(line for line in text.splitlines() if "Alle" in line)
    assert row.startswith("[00:12.30] <00:12.30>Alle <")
    assert row.count("<") == 4  # three words and the end of the line
    assert row.endswith(">")


def test_the_file_is_read_back_by_the_adr_8_parser_with_its_line_times() -> None:
    text = enhanced_lrc(SONG.words, SONG.lines, Heading("Titel", "Künstler", 75.4), {})
    document = parse(text, "lrc")
    assert document.kind == "lrc"
    assert dict(document.tags) == {"ti": "Titel", "ar": "Künstler", "length": "1:15"}
    assert parse_length(dict(document.tags)["length"]) == 75
    assert [line.time for line in document.lines] == [
        pytest.approx(word.start, abs=0.01)
        for word in (SONG.words[0], SONG.words[3], SONG.words[7])
    ]
    assert document.lines[0].text == "Alle meine Entchen"  # the word tags are ignored


def test_a_mark_is_written_when_the_singer_changes() -> None:
    song = timed_song(
        "eins zwei\ndrei vier\nfünf sechs\nsieben acht", singers=["1", "1", "2", "all"]
    )
    names = {1: SingerInfo(name="Anna", colour="#e0b000"), 2: SingerInfo(name="Ben")}
    text = enhanced_lrc(song.words, song.lines, Heading("T", None, None), names)
    document = parse(text, "lrc")
    assert [[(m.word, m.singers) for m in line.marks] for line in document.lines] == [
        [],
        [],
        [(0, "2")],
        [(0, "all")],
    ]
    assert document.singers == names


def test_a_mark_stands_where_the_singers_change_inside_a_line() -> None:
    song = timed_song(
        "eins zwei drei vier\nfünf sechs sieben\nacht neun",
        singers=["1", "2", "1"],
        turns={0: [(2, "2")], 1: [(1, "all"), (2, "2")]},
    )
    text = enhanced_lrc(song.words, song.lines, Heading("T", None, None), {})
    rows = [re.sub(r"<[^>]*>", "", row.split("] ", 1)[1]).strip() for row in text.splitlines()[1:]]
    assert rows == [
        "eins zwei {2} drei vier",  # singer 2 from the third word on, and on the next line
        "fünf {all} sechs {2} sieben",
        "{1} acht neun",
    ]


def test_the_enhanced_lrc_reads_back_with_the_same_singers_for_every_word() -> None:
    song = timed_song(
        "eins zwei drei vier\nfünf sechs sieben\nacht neun",
        singers=["1", "2", "1"],
        turns={0: [(2, "2")], 1: [(1, "all"), (2, "2")]},
    )
    document = parse(enhanced_lrc(song.words, song.lines, Heading("T", None, None), {}), "lrc")
    assert [line.text for line in document.lines] == [line.text for line in song.lines]
    assert resolve_singers(document.lines) == [
        Resolved(line.singers, tuple(line.turns)) for line in song.lines
    ]


def test_words_past_the_lyrics_lines_keep_the_singers_before_and_turns_past_the_words_go() -> None:
    song = timed_song("eins zwei\ndrei vier", singers=["1", "2"])
    first = song.lines[0].model_copy(update={"turns": [Mark(word=2, singers="2")]})
    text = enhanced_lrc(
        song.words, [first], Heading("T", None, None), {}
    )  # line 2 is not in the lyrics
    rows = [re.sub(r"<[^>]*>", "", row.split("] ", 1)[1]).strip() for row in text.splitlines()[1:]]
    assert rows == ["eins zwei", "drei vier"]  # a turn after the last word is no mark


def test_an_offset_shifts_every_tag_and_the_length() -> None:
    plain = enhanced_lrc(SONG.words, SONG.lines, Heading("T", None, 75.4), {})
    moved = enhanced_lrc(SONG.words, SONG.lines, Heading("T", None, 75.4), {}, offset=6.0)
    document = parse(moved, "lrc")
    first = parse(plain, "lrc")
    times = [line.time for line in document.lines]
    assert all(time is not None for time in times)
    assert times == pytest.approx([(line.time or 0.0) + 6.0 for line in first.lines])
    tags = [float(t) for t in re.findall(r"<\d+:(\d+\.\d+)>", moved)]
    assert tags == pytest.approx([float(t) + 6.0 for t in re.findall(r"<\d+:(\d+\.\d+)>", plain)])
    assert "[length: 1:21]" in moved  # 75.4 + 6 = 81.4 s
    assert "[length: 1:15]" in plain
    assert moved != plain


def _words(spans: list[tuple[int, str, float, float]]) -> list[SyllableWord]:
    return [
        SyllableWord(
            line=line,
            text=text,
            start=start,
            end=end,
            estimated=False,
            syllables=[Syllable(text=text, start=start, end=end)],
        )
        for line, text, start, end in spans
    ]


def test_a_second_voice_line_is_written_with_its_mark_and_the_lines_stay_in_time_order() -> None:
    # lyrics order: line 1 (first voice), line 2 (second voice, starts earlier), line 3
    words = _words([(0, "eins", 12.0, 13.0), (1, "zwei", 11.5, 14.0), (2, "drei", 15.0, 16.0)])
    lines = [LyricLine(text=w.text, singers="1") for w in words]
    text = enhanced_lrc(words, lines, Heading("T", None, None), {}, voices=[1, 2, 1])
    rows = [re.sub(r"<[^>]*>", "", row.split("] ", 1)[1]).strip() for row in text.splitlines()[1:]]
    assert rows == ["{&} zwei", "eins", "drei"]
    document = parse(text, "lrc")
    assert [line.voice for line in document.lines] == [2, 1, 1]
    times = [line.time for line in document.lines]
    assert times == sorted(t for t in times if t is not None)


def test_the_voices_of_the_syllables_file_win_over_those_of_the_lyrics() -> None:
    words = _words([(0, "eins", 12.0, 13.0), (1, "zwei", 12.5, 14.0)])
    lines = [LyricLine(text="eins", singers="1"), LyricLine(text="zwei", singers="1", voice=1)]
    heading = Heading("T", None, None)
    found = enhanced_lrc(words, lines, heading, {}, voices=[1, 2])  # found in the audio
    assert "{&} <00:12.50>zwei" in found
    kept = enhanced_lrc(words, [lines[0], lines[1].model_copy(update={"voice": 2})], heading, {})
    assert "{&} <00:12.50>zwei" in kept  # without voices the lyrics file's own count
    assert "{&}" not in enhanced_lrc(words, lines, heading, {})


def test_a_second_voice_line_with_a_mark_of_its_own_keeps_both_marks() -> None:
    words = _words([(0, "eins", 12.0, 13.0), (1, "zwei", 12.5, 14.0)])
    lines = [LyricLine(text="eins", singers="1"), LyricLine(text="zwei", singers="3", voice=2)]
    text = enhanced_lrc(words, lines, Heading("T", None, None), {}, voices=[1, 2])
    document = parse(text, "lrc")
    assert [line.voice for line in document.lines] == [1, 2]
    assert resolve_singers(document.lines)[1].singers == "3"
