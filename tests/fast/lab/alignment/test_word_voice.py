"""Stage 1: the diagnosis of what the voice does under every word (invented timings)."""

import numpy as np
import pytest

from vocatron.core.alignment.voice import VoiceActivity
from vocatron.lab.alignment.word_voice import (
    CROSSES,
    EARLY,
    NO_VOICE,
    StemVoices,
    WordTime,
    confident_words,
    longest_silence,
    merge,
    onset,
    row_line,
    stem_voices,
    summary,
    table_header,
    word_rows,
)

SPF = 0.02


def word(start: float, end: float, *, confidence: float = 0.9, estimated: bool = False) -> WordTime:
    """Return a word with its heard end at ``end``."""
    return WordTime(0, start, end, end, confidence, estimated)


def voices(lead: list[tuple[float, float]], backing: list[tuple[float, float]]) -> StemVoices:
    """Return stem voices from invented spans."""
    return StemVoices(VoiceActivity(tuple(lead)), VoiceActivity(tuple(backing)), -30.0)


def test_merge_joins_touching_and_overlapping_spans() -> None:
    assert merge([(3.0, 4.0), (0.0, 1.0), (1.0, 2.0), (1.5, 2.5)]) == ((0.0, 2.5), (3.0, 4.0))
    assert merge([]) == ()


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (0.0, 1.0, 0.0),
        (0.5, 1.5, 0.0),
        (-1.0, 0.5, 1.0),
        (3.5, 4.0, None),
        (1.2, 2.9, None),
        (2.0, 3.2, 1.0),
    ],
)
def test_onset_is_zero_where_voice_sounds_and_none_without(
    start: float, end: float, expected: float | None
) -> None:
    assert onset(VoiceActivity(((0.0, 1.0), (3.0, 3.4))), start, end) == expected


def test_onset_counts_from_the_start_of_the_word() -> None:
    assert onset(VoiceActivity(((2.0, 3.0),)), 1.0, 2.5) == pytest.approx(1.0)


def test_longest_silence_is_the_biggest_hole_inside_the_word() -> None:
    voice = VoiceActivity(((1.0, 2.0), (2.2, 3.0), (4.0, 4.5)))
    assert longest_silence(voice, 1.0, 3.0) == pytest.approx(0.2)
    assert longest_silence(voice, 0.0, 5.0) == pytest.approx(1.0)
    assert longest_silence(voice, 5.0, 6.0) == pytest.approx(1.0)
    assert longest_silence(VoiceActivity(()), 0.0, 2.0) == pytest.approx(2.0)


def test_a_word_only_the_backing_sings_is_voiced_there_and_not_flagged() -> None:
    rows = word_rows([word(10.0, 11.0)], voices([(0.0, 5.0)], [(9.9, 11.2)]))
    row = rows[0]
    assert row.lead_share == 0.0
    assert row.backing_share == pytest.approx(1.0)
    assert row.lead_onset is None
    assert row.backing_onset == pytest.approx(0.0)
    assert row.flags == ()


def test_a_word_in_silence_on_both_stems_is_flagged() -> None:
    rows = word_rows([word(10.0, 11.0)], voices([(0.0, 5.0)], [(20.0, 21.0)]))
    assert rows[0].flags == (NO_VOICE,)
    assert rows[0].either_onset is None


def test_a_sweep_that_starts_long_before_the_voice_is_flagged_early() -> None:
    rows = word_rows([word(10.0, 12.0), word(20.0, 21.0)], voices([(10.5, 12.0)], [(20.2, 21.0)]))
    assert rows[0].flags == (EARLY,)
    assert rows[0].either_onset == pytest.approx(0.5)
    assert rows[1].flags == ()


def test_a_word_stretched_over_a_breath_is_flagged_crossing() -> None:
    lead = [(10.0, 10.4), (11.4, 12.0)]
    row = word_rows([word(10.0, 12.0)], voices(lead, [(30.0, 31.0)]))[0]
    assert row.flags == (CROSSES,)
    assert row.longest_silence == pytest.approx(1.0)


def test_a_breath_covered_by_the_other_stem_does_not_count() -> None:
    row = word_rows([word(10.0, 12.0)], voices([(10.0, 10.4), (11.4, 12.0)], [(10.3, 11.5)]))[0]
    assert row.flags == ()


def test_the_mix_share_comes_from_the_alignments_own_voice() -> None:
    row = word_rows([word(0.0, 2.0)], voices([(0.0, 2.0)], []), VoiceActivity(((0.0, 1.0),)))[0]
    assert row.mix_share == pytest.approx(0.5)
    assert word_rows([word(0.0, 2.0)], voices([(0.0, 2.0)], []))[0].mix_share == 0.0


def test_confident_words_are_measured_ones_with_enough_confidence() -> None:
    words = [word(0, 1), word(1, 2, confidence=0.2), word(2, 3, estimated=True)]
    assert confident_words(words) == [(0, 1)]


def test_the_lines_and_the_summary_are_numbers_and_flags() -> None:
    rows = word_rows(
        [word(10.0, 11.0), word(12.0, 13.0, estimated=True)], voices([(10.0, 11.0)], [(12.0, 13.0)])
    )
    assert "lead" in table_header()
    assert row_line(rows[0]).split()[:3] == ["0", "L1", "10.00"]
    assert row_line(rows[1]).startswith("   1")
    assert summary(rows) == (
        "2 words: 0 no-voice, 0 early, 0 crosses; 1 silent on the lead, "
        "1 of them voiced on the backing"
    )


def _loudness(seconds: float, loud: list[tuple[float, float]], level: float) -> np.ndarray:
    values = np.full(round(seconds / SPF), -100.0, dtype=np.float32)
    for start, end in loud:
        values[round(start / SPF) : round(end / SPF)] = level
    return values


def test_stem_voices_measure_the_backing_with_the_leads_threshold() -> None:
    lead = _loudness(20.0, [(2.0, 6.0), (8.0, 12.0)], -20.0)
    backing = _loudness(20.0, [(14.0, 16.0)], -10.0)
    found = stem_voices(lead, backing, SPF, [(2.0, 6.0), (8.0, 12.0)])
    assert found is not None
    assert found.lead.spans[0][0] == pytest.approx(2.0, abs=0.05)
    assert len(found.backing.spans) == 1
    assert found.backing.spans[0] == pytest.approx((14.0, 16.0), abs=0.05)
    assert found.either.spans[-1] == pytest.approx((14.0, 16.0), abs=0.05)


def test_stem_voices_are_none_when_the_lead_is_not_plausible() -> None:
    quiet = _loudness(20.0, [], -20.0)
    assert stem_voices(quiet, quiet, SPF, []) is None


def test_the_summary_adds_the_words_of_a_second_voice_only_when_there_are_some() -> None:
    active = voices([(0.0, 10.0)], [])
    one = word_rows([word(0.0, 1.0), word(2.0, 3.0)], active)
    assert "second voice" not in summary(one)
    second = WordTime(1, 4.0, 5.0, 5.0, 0.9, False, 2)
    silent = WordTime(1, 20.0, 21.0, 21.0, 0.9, False, 2)  # no voice on either stem
    text = summary(word_rows([word(0.0, 1.0), second, silent], active))
    assert text.endswith("second voice 2 words: 1 no-voice, 0 early, 0 crosses")
