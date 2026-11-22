"""Stage 1 tests of the helper that times lyrics from their line times (``fakes.timed``).

The duet corpus test (stage 2) times the words of a real ``.lrc`` with it; here the lines are
invented.
"""

import pytest

from fakes.measure import FixedMeasurer
from fakes.scenes import builtin_profile
from fakes.timed import LAST_LINE_SECONDS, LINE_TIME_GAP, timed_from_line_times
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.lyrics.document import Mark
from vocatron.core.lyrics.file import LyricLine
from vocatron.core.presets import PRESETS

LINES = [
    LyricLine(text="one two three four", time=10.0, singers="1"),
    # two lines with one time tag; the first is long enough to be split in the layout
    LyricLine(text="alpha beta gamma delta epsilon zeta eta theta", time=14.0, singers="2"),
    LyricLine(text="red orange yellow green blue indigo violet", time=14.0, singers="all"),
    LyricLine(text="sun moon star sky", time=20.0, singers="2", turns=[Mark(word=2, singers="1")]),
]


def test_two_lines_with_one_time_tag_are_sung_one_after_the_other() -> None:
    words = timed_from_line_times(LINES)
    assert [word.line for word in words] == sorted(word.line for word in words)
    assert all(b.start >= a.end for a, b in zip(words, words[1:], strict=False))
    assert words[0].start == LINES[0].time


def test_lines_with_one_time_tag_keep_the_singers_of_their_words_in_the_scene() -> None:
    words = timed_from_line_times(LINES)
    expected: list[str] = []
    for line in LINES:
        turns = {turn.word: turn.singers for turn in line.turns}
        current = line.singers
        for index in range(len(line.text.split())):
            current = turns.get(index, current)
            expected.append(current)
    preset = PRESETS["4x3-720"]
    for name in ("two-line-turns", "full-page"):
        look = builtin_profile(name)
        song = SongText("Duet", None, words[-1].end + 10.0, {})
        phrases = phrases_from(words, LINES, look.font.case)
        scene = layout(phrases, song, look, (preset.width, preset.height), FixedMeasurer())
        assert len(scene.lines()) > len(LINES), "no line was split"
        found: list[str] = []
        for line in scene.lines():
            at = {turn.span: turn.singers for turn in line.turns}
            current = line.singers
            for index in range(len(line.spans)):
                current = at.get(index, current)
                found.append(current)
        assert found == expected, name


UNTIMED = [
    LyricLine(text="morning bells ring", time=None, singers="1"),
    LyricLine(text="one two three four", time=10.0, singers="1"),
    LyricLine(text="five six", time=None, singers="2"),
    LyricLine(text="seven eight nine", time=20.0, singers="all"),
    LyricLine(text="ten eleven", time=None, singers="1"),
    LyricLine(text="twelve", time=None, singers="2"),
]


def test_lines_without_a_time_follow_the_line_before() -> None:
    words = timed_from_line_times(UNTIMED)
    assert len(words) == sum(len(line.text.split()) for line in UNTIMED)
    assert all(b.start >= a.end for a, b in zip(words, words[1:], strict=False))
    assert all(word.end > word.start for word in words)
    starts = {word.line: word.start for word in reversed(words)}
    ends = {word.line: word.end for word in words}
    assert starts[0] == 0.0
    assert (starts[1], starts[3]) == (10.0, 20.0)  # a known time is kept
    assert starts[2] == pytest.approx(ends[1] + LINE_TIME_GAP)
    assert ends[2] <= 20.0
    assert starts[4] == pytest.approx(ends[3] + LINE_TIME_GAP)
    assert starts[5] == pytest.approx(ends[4] + LINE_TIME_GAP)
    assert ends[3] - starts[3] == pytest.approx(LAST_LINE_SECONDS)
