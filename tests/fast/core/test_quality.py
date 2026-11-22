"""Stage 1: the quality report of an alignment and the rules that make a song review."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.alignment.file import AlignedWord, QualityReport
from vocatron.core.alignment.unheard import UnheardLine
from vocatron.core.alignment.voice import VoiceActivity
from vocatron.core.quality import (
    MAX_ESTIMATED_SHARE,
    SPLIT_CONFIDENCE,
    SPLIT_GAP,
    SPLIT_SILENT,
    listed,
    reasons,
    report,
    split_reasons,
    unheard_reasons,
)


def word(start: float, end: float, *, line: int = 0, estimated: bool = False) -> AlignedWord:
    return AlignedWord(
        line=line, text="w", spoken="w", start=start, end=end, confidence=0.9, estimated=estimated
    )


def clean(words: int = 20) -> list[AlignedWord]:
    return [word(i * 0.5, i * 0.5 + 0.4, line=i // 5) for i in range(words)]


def test_a_clean_alignment_needs_no_review() -> None:
    quality = report(clean())
    assert (quality.words, quality.estimated, quality.too_short, quality.too_long) == (20, 0, 0, 0)
    assert reasons(quality) == []


def test_the_estimated_share_is_counted_and_over_ten_percent_needs_review() -> None:
    words = clean()
    for index in (1, 2, 3):
        words[index] = word(words[index].start, words[index].end, estimated=True)
    quality = report(words)
    assert (quality.estimated, quality.estimated_share) == (3, 0.15)
    assert reasons(quality) == ["15% of words estimated (max 10%)"]


def test_exactly_ten_percent_is_still_fine() -> None:
    words = clean()
    words[0] = word(0.0, 0.4, estimated=True)
    words[1] = word(0.5, 0.9, estimated=True)
    assert report(words).estimated_share == MAX_ESTIMATED_SHARE
    assert reasons(report(words)) == []


def test_a_gap_inside_a_line_over_three_seconds_needs_review_and_names_the_line() -> None:
    words = [word(0.0, 0.5), word(4.0, 4.5), word(5.0, 5.5, line=1)]
    quality = report(words)
    assert (quality.longest_gap, quality.gap_line) == (3.5, 0)
    assert reasons(quality) == ["3.5 s gap in line 1 (max 3 s)"]


def test_a_pause_between_two_lines_is_no_gap() -> None:
    quality = report([word(0.0, 0.5), word(30.0, 30.5, line=1)])
    assert (quality.longest_gap, quality.gap_line) == (0.0, None)
    assert reasons(quality) == []


@pytest.mark.parametrize(("odd", "review"), [(5, False), (6, True)])
def test_more_than_five_words_shorter_than_60_ms_or_longer_than_3_s_need_review(
    odd: int, review: bool
) -> None:
    words = [word(i * 5.0, i * 5.0 + (0.03 if i % 2 else 3.2), line=i) for i in range(odd)]
    quality = report(words)
    assert quality.too_short + quality.too_long == odd
    assert bool(reasons(quality)) is review


def test_estimated_words_never_count_as_too_short_or_too_long() -> None:
    quality = report([word(0.0, 0.0, estimated=True), word(1.0, 9.0, estimated=True)])
    assert (quality.too_short, quality.too_long) == (0, 0)


def test_no_word_is_an_empty_report() -> None:
    assert report([]) == QualityReport(
        words=0,
        estimated=0,
        estimated_share=0.0,
        longest_gap=0.0,
        gap_line=None,
        too_short=0,
        too_long=0,
    )


@given(st.lists(st.tuples(st.floats(0, 5), st.floats(0, 5), st.booleans()), max_size=20))
def test_the_counts_are_consistent(items: list[tuple[float, float, bool]]) -> None:
    cursor = 0.0
    words: list[AlignedWord] = []
    for gap, length, estimated in items:
        words.append(word(cursor + gap, cursor + gap + length, estimated=estimated))
        cursor += gap + length
    quality = report(words)
    assert quality.words == len(words)
    assert quality.estimated == sum(e for _, _, e in items)
    assert quality.too_short + quality.too_long <= len(words) - quality.estimated
    assert 0.0 <= quality.estimated_share <= 1.0


def test_the_limits_of_gap_and_word_length_are_inclusive() -> None:
    quality = report([word(0.0, 0.06), word(1.0, 4.0, line=1), word(7.0, 7.5, line=1)])
    assert (quality.longest_gap, quality.too_short, quality.too_long) == (3.0, 0, 0)
    assert reasons(quality) == []


def test_of_two_equal_gaps_the_first_names_the_line() -> None:
    words = [word(0.0, 0.5, line=0), word(4.0, 4.5, line=0)]
    words += [word(10.0, 10.5, line=2), word(14.0, 14.5, line=2)]
    quality = report(words)
    assert (quality.longest_gap, quality.gap_line) == (3.5, 0)
    later = report(words[2:])
    assert reasons(later) == ["3.5 s gap in line 3 (max 3 s)"]


def test_the_reason_for_odd_words_names_the_limits() -> None:
    words = [word(i * 1.0, i * 1.0 + 0.01) for i in range(6)]
    assert reasons(report(words)) == ["6 words of odd length (max 5)"]


def held(start: float, heard: float, end: float) -> AlignedWord:
    """A measured word whose last letter ends at ``heard`` and whose end is held to ``end``."""
    return AlignedWord(
        line=0, text="w", spoken="w", start=start, end=end, confidence=0.9, estimated=False,
        letters=[(start, heard)],
    )  # fmt: skip


def test_a_five_second_held_note_is_not_too_long() -> None:
    assert report([held(1.0, 1.4, 6.0)]).too_long == 0


def test_a_short_word_held_to_the_end_of_the_voice_is_not_too_short() -> None:
    assert report([held(1.0, 1.02, 1.3)]).too_short == 0


def test_a_short_word_not_held_is_too_short() -> None:
    assert report([held(1.0, 1.02, 1.02)]).too_short == 1


def test_a_word_heard_for_over_three_seconds_is_too_long_even_when_held() -> None:
    assert report([held(1.0, 4.5, 6.0)]).too_long == 1


def test_a_held_note_is_not_a_gap() -> None:
    words = [held(0.0, 0.5, 4.0), word(4.0, 4.5)]
    assert report(words).longest_gap == 0.0
    assert report([held(0.0, 0.5, 0.5), word(4.0, 4.5)]).longest_gap == 3.5


def test_an_unheard_line_with_less_than_half_voice_in_its_window_needs_review() -> None:
    lines = [UnheardLine(11, 10.0, 12.0), UnheardLine(13, 20.0, 22.0)]
    voice = VoiceActivity(((10.9, 12.0), (20.0, 22.0)))  # 55 % voiced, then fully
    assert unheard_reasons(lines, voice) == []
    quiet = VoiceActivity(((11.1, 12.0), (20.0, 22.0)))  # 45 % voiced
    assert unheard_reasons(lines, quiet) == ["little voice where line 12 was placed at its time"]


def test_unheard_lines_are_named_up_to_five_then_counted() -> None:
    lines = [UnheardLine(i, 10.0 * i, 10.0 * i + 1.0) for i in range(8)]
    found = unheard_reasons(lines, VoiceActivity(()))
    assert found == ["little voice where lines 1, 2, 3, 4, 5 and 3 more were placed at their time"]


def test_unheard_lines_need_no_review_without_a_voice_or_without_lines() -> None:
    assert unheard_reasons([UnheardLine(0, 0.0, 1.0)], None) == []
    assert unheard_reasons([], VoiceActivity(())) == []


def test_exactly_half_voice_is_enough_and_exactly_five_lines_are_listed_without_a_count() -> None:
    assert unheard_reasons([UnheardLine(0, 0.0, 2.0)], VoiceActivity(((0.0, 1.0),))) == []
    lines = [UnheardLine(i, 10.0 * i, 10.0 * i + 1.0) for i in range(5)]
    assert unheard_reasons(lines, VoiceActivity(())) == [
        "little voice where lines 1, 2, 3, 4, 5 were placed at their time"
    ]


def test_one_line_beyond_the_named_ones_is_counted() -> None:
    lines = [UnheardLine(i, 10.0 * i, 10.0 * i + 1.0) for i in range(6)]
    assert unheard_reasons(lines, VoiceActivity(())) == [
        "little voice where lines 1, 2, 3, 4, 5 and 1 more were placed at their time"
    ]


def test_listed_names_the_numbers_up_to_the_limit_and_then_counts_the_rest() -> None:
    assert listed([3, 7], 2) == "3, 7"
    assert listed([3, 7, 9, 12], 2) == "3, 7 and 2 more"
    assert listed([], 2) == ""


# ---------------------------------------------------------------- lines split by a gap (ADR-0053)


def spoken(start: float, end: float, confidence: float, line: int = 0) -> AlignedWord:
    return AlignedWord(
        line=line,
        text="w",
        spoken="w",
        start=start,
        end=end,
        confidence=confidence,
        estimated=False,
    )


def split_line(line: int = 0, *, confidence: float = 0.1, gap: float = 2.7) -> list[AlignedWord]:
    """Two weak words, a silent gap, then three sure words."""
    base = 10.0 * line
    start = base + 0.7 + gap
    return [
        spoken(base, base + 0.3, confidence, line),
        spoken(base + 0.4, base + 0.7, confidence, line),
        spoken(start, start + 0.3, 0.9, line),
        spoken(start + 0.4, start + 0.7, 0.9, line),
        spoken(start + 0.8, start + 1.1, 0.9, line),
    ]


QUIET = VoiceActivity(((20.0, 24.0),))  # voice only elsewhere


def test_weak_first_words_before_a_silent_gap_say_the_line_time_looks_early() -> None:
    assert split_reasons(split_line(33), QUIET) == ["line 34: its time looks early"]


def test_several_split_lines_are_named_together() -> None:
    words = split_line(1) + split_line(3)
    assert split_reasons(words, QUIET) == ["lines 2, 4: their times look early"]


def test_a_gap_with_voice_in_it_is_a_sung_gap_and_says_nothing() -> None:
    sung_gap = VoiceActivity(((10.7, 13.4),))
    assert split_reasons(split_line(1), sung_gap) == []


def test_sure_first_words_say_nothing_even_before_a_gap() -> None:
    assert split_reasons(split_line(1, confidence=0.8), QUIET) == []


def test_a_short_gap_or_a_held_note_is_not_a_split() -> None:
    assert split_reasons(split_line(1, gap=1.4), QUIET) == []
    held_note = split_line(1)
    held_note[1] = held_note[1].model_copy(update={"end": held_note[2].start - 0.1})
    assert split_reasons(held_note, QUIET) == []


def test_estimated_first_words_before_the_gap_are_no_weak_measurement() -> None:
    line = split_line(1)
    line[0] = line[0].model_copy(update={"estimated": True})
    assert split_reasons(line, QUIET) == []


def test_split_lines_need_a_voice_and_a_line_with_two_words() -> None:
    assert split_reasons(split_line(1), None) == []
    assert split_reasons([spoken(0.0, 0.3, 0.0)], QUIET) == []
    assert split_reasons([], QUIET) == []


def test_the_split_limits_are_exact() -> None:
    """A gap of exactly ``SPLIT_GAP`` counts, a voice in exactly ``SPLIT_SILENT`` of it does not,
    nor does a mean confidence of exactly ``SPLIT_CONFIDENCE``; the mean is over the words."""
    edge = [spoken(0.0, 1.0, 0.3), spoken(1.0 + SPLIT_GAP, 3.0, 0.9)]
    assert split_reasons(edge, QUIET) == ["line 1: its time looks early"]
    gap = [spoken(0.0, 1.0, 0.1), spoken(3.0, 3.5, 0.9)]
    assert split_reasons(gap, VoiceActivity(((1.0, 1.0 + 2.0 * SPLIT_SILENT),))) == []
    sure = [spoken(0.0, 0.5, SPLIT_CONFIDENCE), spoken(0.5, 1.0, SPLIT_CONFIDENCE)]
    assert split_reasons([*sure, spoken(3.0, 3.5, 0.9)], QUIET) == []
    fair = [spoken(0.0, 0.5, 0.3), spoken(0.5, 1.0, 0.3), spoken(3.0, 3.5, 0.9)]
    assert split_reasons(fair, QUIET) == ["line 1: its time looks early"]
