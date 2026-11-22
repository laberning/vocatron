"""Stage 1: confidence per word and the estimation of what could not be measured."""

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.alignment import estimate
from vocatron.core.alignment.ctc import CtcPath, Spans
from vocatron.core.alignment.estimate import MIN_CONFIDENCE, Timed, measure
from vocatron.core.alignment.tokens import Transcript, Word
from vocatron.core.alignment.voice import VoiceActivity


def settle(measured: list[Timed | None], weights: list[int], duration: float) -> list[Timed]:
    """Settle without the voice: the earlier placement."""
    return estimate.settle(measured, weights, duration).words


def timed(start: float, end: float, confidence: float = 0.9) -> Timed:
    return Timed(start, end, confidence, False, ((start, end),))


def run_of(
    items: list[tuple[float, int, float]],
) -> tuple[list[Timed | None], list[int], float]:
    """Lay out words of the given confidence, letters and length, 0.1 s apart.

    Returns:
        The measured words, their letter weights and the end of the last word.
    """
    cursor = 0.0
    measured: list[Timed | None] = []
    weights: list[int] = []
    for confidence, letters, length in items:
        measured.append(timed(cursor + 0.1, cursor + 0.1 + length, confidence))
        weights.append(letters)
        cursor += 0.1 + length
    return measured, weights, cursor


def test_a_confident_word_is_kept_as_measured() -> None:
    (word,) = settle([timed(1.0, 2.0)], [4], 10.0)
    assert (word.start, word.end, word.estimated) == (1.0, 2.0, False)
    assert word.letters == ((1.0, 2.0),)


def test_an_unsure_word_takes_the_gap_between_its_neighbours() -> None:
    words = settle([timed(0.0, 1.0), timed(1.2, 1.4, 0.01), timed(3.0, 4.0)], [3, 3, 3], 10.0)
    assert [w.estimated for w in words] == [False, True, False]
    assert (words[1].start, words[1].end) == (1.0, 3.0)
    assert words[1].confidence == 0.01
    assert words[1].letters == ()


def test_a_run_of_estimated_words_shares_the_gap_in_proportion_to_their_letters() -> None:
    words = settle([timed(0.0, 1.0), None, None, timed(5.0, 6.0)], [3, 1, 3, 3], 10.0)
    assert [(w.start, w.end) for w in words[1:3]] == [(1.0, 2.0), (2.0, 5.0)]
    assert all(w.estimated and w.confidence == 0.0 for w in words[1:3])


def test_estimated_words_at_the_edges_get_a_plausible_length() -> None:
    words = settle([None, timed(2.0, 3.0), None], [5, 3, 5], 3.2)
    assert words[0].end == 2.0
    assert words[0].start == pytest.approx(2.0 - 5 * 0.08)
    assert words[2].start == 3.0
    assert words[2].end == pytest.approx(3.2)  # cut off at the end of the audio


def test_a_song_without_a_single_measured_word_is_spread_over_the_audio() -> None:
    words = settle([None, None], [1, 1], 8.0)
    assert [(w.start, w.end) for w in words] == [(0.0, 4.0), (4.0, 8.0)]


@given(
    st.lists(
        st.tuples(st.floats(0.0, 1.0), st.integers(1, 8), st.floats(0.01, 1.0)),
        min_size=1,
        max_size=15,
    )
)
def test_words_stay_in_order_and_never_overlap(
    items: list[tuple[float, int, float]],
) -> None:
    measured, weights, cursor = run_of(items)
    words = settle(measured, weights, cursor + 1.0)
    assert len(words) == len(items)
    for before, after in zip(words, words[1:], strict=False):
        assert before.start <= before.end <= after.start + 1e-9
    kept = [w for w in words if not w.estimated]
    assert all(w.confidence >= MIN_CONFIDENCE for w in kept)
    assert [w.estimated for w in words] == [
        m is not None and m.confidence < MIN_CONFIDENCE for m in measured
    ]


def test_the_confidence_of_a_word_is_the_mean_of_the_best_posterior_of_its_letters() -> None:
    transcript = Transcript(
        words=(Word(0, "ab", "ab"), Word(0, "—", "")),
        targets=(1, 2),
        slots=((0, 1), None),
        lines=1,
    )
    scores = np.log(np.array([0.2, 0.8, 0.6, 0.6], dtype=np.float32))
    states = np.array([1, 1, 3, 3], dtype=np.int32)
    path = CtcPath(states, scores, float(scores.sum()))
    spans = Spans(np.array([0, 2]), np.array([1, 3]))
    first, silent = measure(transcript, path, spans, 0.5)
    assert silent is None
    assert first is not None
    assert first.confidence == pytest.approx((0.8 + 0.6) / 2, rel=1e-5)
    assert (first.start, first.end) == (0.0, 2.0)
    assert first.letters == ((0.0, 1.0), (1.0, 2.0))


def test_the_confidence_looks_only_at_the_frames_and_letters_of_the_word() -> None:
    """A loud next letter (the delimiter) and a loud frame after the word do not count."""
    transcript = Transcript(
        words=(Word(0, "a", "a"), Word(0, "b", "b")),
        targets=(1, 3, 2),  # a | b
        slots=((0, 0), (2, 2)),
        lines=1,
    )
    scores = np.log(np.array([0.4, 0.99, 0.99, 0.5], dtype=np.float32))
    states = np.array([1, 2, 3, 5], dtype=np.int32)  # a, blank, delimiter, b
    path = CtcPath(states, scores, float(scores.sum()))
    spans = Spans(np.array([0, 2, 3]), np.array([0, 2, 3]))
    first, second = measure(transcript, path, spans, 0.5)
    assert first is not None and second is not None
    assert first.confidence == pytest.approx(0.4, rel=1e-5)
    assert second.confidence == pytest.approx(0.5, rel=1e-5)


# ---------------------------------------------------------------- on the voice (ADR-0012)

PER_LETTER = 0.05


def word(start: float, letters: int, confidence: float = 0.9) -> Timed:
    """A measured word of ``letters`` letters of ``PER_LETTER`` seconds each."""
    end = start + letters * PER_LETTER
    steps = tuple((start + i * PER_LETTER, start + (i + 1) * PER_LETTER) for i in range(letters))
    return Timed(start, end, confidence, False, steps)


def voice_of(*spans: tuple[float, float]) -> VoiceActivity:
    return VoiceActivity(tuple(spans))


def disjoint_spans(voice_parts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Voice spans from (begin, length) parts, dropping parts that start inside an earlier one."""
    spans: list[tuple[float, float]] = []
    for begin, length in sorted(voice_parts):
        if not spans or begin > spans[-1][1]:
            spans.append((begin, begin + length))
    return spans


def assert_ordered(words: list[Timed], count: int) -> None:
    """There are ``count`` words, in order, without overlaps, none before the song starts."""
    assert len(words) == count
    for before, after in zip(words, words[1:], strict=False):
        assert before.start <= before.end <= after.start + 1e-9
    assert words[0].start >= -1e-9


def estimated_times(settled: estimate.Settled) -> list[float]:
    """Start and end of every estimated word, flat (``pytest.approx`` has no nested lists)."""
    return [t for w in settled.words if w.estimated for t in (w.start, w.end)]


def test_a_word_after_a_pause_starts_where_the_voice_starts_again() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, word(6.0, 4)]  # 1.0 to 1.2 and 6.0 to 6.2
    voice = voice_of((0.9, 1.3), (5.0, 6.3))  # a held note, a pause, the voice again
    settled = estimate.settle(measured, [4, 3, 4], 10.0, voice=voice)
    assert estimated_times(settled) == pytest.approx([5.0, 5.15])  # 3 letters of 0.05 s
    assert settled.placed == 1
    assert settled.words[1].confidence == 0.0
    assert settled.words[1].letters == ()


def test_without_the_voice_the_same_word_fills_the_whole_gap() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, word(6.0, 4)]
    settled = estimate.settle(measured, [4, 3, 4], 10.0)
    assert estimated_times(settled) == pytest.approx([1.2, 6.0])
    assert (settled.placed, settled.re_estimated) == (0, 0)


def test_a_voice_that_goes_on_from_the_previous_word_gives_it_the_start_of_the_gap() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, word(6.0, 4)]
    settled = estimate.settle(measured, [4, 3, 4], 10.0, voice=voice_of((0.9, 6.3)))
    assert estimated_times(settled) == pytest.approx([1.2, 1.35])


def test_a_long_held_note_is_not_taken_for_the_tail_of_the_previous_word() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, word(6.0, 4)]
    voice = voice_of((0.9, 2.5), (5.0, 6.3))  # sounds 1.3 s after the previous word
    assert estimated_times(estimate.settle(measured, [4, 3, 4], 10.0, voice=voice)) == (
        pytest.approx([1.2, 1.35])
    )


def test_the_words_of_a_run_follow_the_voice_over_its_pauses() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, None, word(9.0, 4)]
    voice = voice_of((0.9, 1.3), (4.0, 4.2), (6.0, 7.0))  # the first word fits the first stretch
    settled = estimate.settle(measured, [4, 4, 4, 4], 12.0, voice=voice)
    assert estimated_times(settled) == pytest.approx([4.0, 4.2, 6.0, 6.2])
    assert settled.placed == 2


def test_a_run_that_is_longer_than_its_gap_is_compressed_into_it() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, None, word(1.6, 4)]  # a gap of 0.4 s
    settled = estimate.settle(measured, [4, 5, 5, 4], 10.0, voice=voice_of((0.9, 2.0)))
    assert estimated_times(settled) == pytest.approx([1.2, 1.4, 1.4, 1.6])  # 0.5 s into 0.4 s
    assert settled.placed == 2


def test_without_a_voice_start_in_the_gap_the_time_is_shared_as_before() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, word(6.0, 4)]
    silent = voice_of((0.0, 0.5), (7.0, 8.0))  # nothing sounds between the words
    shared = estimate.settle(measured, [4, 3, 4], 10.0, voice=silent)
    assert estimated_times(shared) == pytest.approx([1.2, 6.0])
    assert shared.placed == 0


def test_far_too_little_voiced_time_for_the_run_falls_back() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, word(6.0, 4)]
    short = voice_of((5.9, 6.3))  # 0.1 s voiced before the next word; the run needs 0.6 s
    settled = estimate.settle(measured, [4, 12, 4], 10.0, voice=short)
    assert estimated_times(settled) == pytest.approx([1.2, 6.0])
    assert settled.placed == 0


def test_the_first_word_of_a_song_ignores_a_sound_far_in_the_intro() -> None:
    measured: list[Timed | None] = [None, word(8.0, 4)]
    voice = voice_of((0.5, 1.0), (7.0, 8.5))  # a sound in the intro, then the voice
    settled = estimate.settle(measured, [3, 4], 12.0, voice=voice)
    assert estimated_times(settled) == pytest.approx([7.0, 7.15])


def test_the_first_word_without_a_voice_start_near_it_is_placed_as_before() -> None:
    measured: list[Timed | None] = [None, word(8.0, 4)]
    voice = voice_of((0.5, 9.0))  # sounds all along: no start within reach
    settled = estimate.settle(measured, [5, 4], 12.0, voice=voice)
    assert estimated_times(settled) == pytest.approx([8.0 - 5 * estimate.LETTER_SECONDS, 8.0])
    assert settled.placed == 0


def test_the_last_word_of_a_song_starts_at_the_voice_after_the_last_measured_word() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None]
    voice = voice_of((0.9, 1.3), (3.0, 3.6), (9.0, 10.0))  # the outro sound lies out of reach
    settled = estimate.settle(measured, [4, 4], 12.0, voice=voice)
    assert estimated_times(settled) == pytest.approx([3.0, 3.2])
    again = estimate.settle(measured, [4, 4], 12.0, voice=voice_of((0.5, 1.1), (9.0, 10.0)))
    assert estimated_times(again) == pytest.approx([1.2, 1.2 + 4 * estimate.LETTER_SECONDS])


def test_a_song_without_any_measured_word_is_spread_over_the_audio_even_with_a_voice() -> None:
    settled = estimate.settle([None, None], [1, 1], 8.0, voice=voice_of((1.0, 7.0)))
    assert [(w.start, w.end) for w in settled.words] == [(0.0, 4.0), (4.0, 8.0)]


def test_the_length_per_letter_is_the_median_of_the_confident_words_and_clamped() -> None:
    slow = [word(i, 2) for i in range(3)]
    assert estimate.letter_seconds(slow) == pytest.approx(PER_LETTER)
    assert estimate.letter_seconds([word(0, 1), Timed(0.0, 9.0, 0.9, False, ((0.0, 9.0),))]) == (
        estimate.MAX_LETTER_SECONDS
    )
    assert estimate.letter_seconds([Timed(0.0, 0.001, 0.9, False, ((0.0, 0.001),))]) == (
        estimate.MIN_LETTER_SECONDS
    )
    assert estimate.letter_seconds([word(0, 3, 0.2), None]) == estimate.LETTER_SECONDS


def test_a_word_of_moderate_confidence_in_silence_is_estimated_and_placed_by_the_voice() -> None:
    measured: list[Timed | None] = [word(1.0, 4), word(3.0, 4, 0.3), word(6.0, 4)]
    voice = voice_of((0.9, 1.3), (5.0, 6.3))
    settled = estimate.settle(measured, [4, 4, 4], 10.0, voice=voice)
    assert settled.re_estimated == 1
    assert settled.words[1].estimated
    assert settled.words[1].confidence == 0.3  # the confidence is kept
    assert settled.words[1].letters == ()
    assert (settled.words[1].start, settled.words[1].end) == pytest.approx((5.0, 5.2))
    assert settled.placed == 1


@pytest.mark.parametrize(
    ("moved", "why"),
    [
        (word(3.0, 4, 0.7), "confident enough"),  # 0.7 is not moderate
        (word(3.0, 1, 0.3), "too short to be judged"),  # 0.05 s
        (word(5.1, 4, 0.3), "mostly voiced"),
    ],
)
def test_other_measured_words_are_left_alone(moved: Timed, why: str) -> None:
    measured: list[Timed | None] = [word(1.0, 4), moved, word(6.0, 4)]
    voice = voice_of((0.9, 1.3), (5.0, 6.3))
    settled = estimate.settle(measured, [4, 4, 4], 10.0, voice=voice)
    assert settled.re_estimated == 0, why
    assert not settled.words[1].estimated, why
    assert settled.words[1] == moved


@given(
    st.lists(
        st.tuples(st.floats(0.0, 1.0), st.integers(1, 8), st.floats(0.01, 1.0)),
        min_size=1,
        max_size=15,
    ),
    st.lists(st.tuples(st.floats(0.0, 30.0), st.floats(0.1, 5.0)), max_size=8),
)
def test_with_a_voice_words_stay_in_order_inside_their_gaps_and_never_overlap(
    items: list[tuple[float, int, float]], voice_parts: list[tuple[float, float]]
) -> None:
    measured, weights, cursor = run_of(items)
    settled = estimate.settle(
        measured, weights, cursor + 1.0, voice=voice_of(*disjoint_spans(voice_parts))
    )
    words = settled.words
    assert_ordered(words, len(items))
    assert settled.placed <= sum(w.estimated for w in words)
    for was, now in zip(measured, words, strict=True):
        assert was is not None
        if was.confidence >= estimate.SILENT_CONFIDENCE:
            assert now == was  # a confidently measured word never moves
        elif not now.estimated:
            assert now == was
    assert settled.re_estimated == sum(
        w.estimated and m is not None and m.confidence >= MIN_CONFIDENCE
        for m, w in zip(measured, words, strict=True)
    )
    assert settled.re_estimated <= settled.placed


def test_a_word_in_silence_that_the_voice_cannot_place_keeps_its_measured_time() -> None:
    misplaced = word(3.0, 4, 0.3)  # in silence, and the gap has no voice start
    measured: list[Timed | None] = [word(1.0, 4), misplaced, word(6.0, 4)]
    settled = estimate.settle(measured, [4, 4, 4], 10.0, voice=voice_of((0.9, 1.3), (5.95, 6.3)))
    assert settled.words[1] == misplaced
    assert (settled.placed, settled.re_estimated) == (0, 0)


def test_an_unplaced_word_in_silence_splits_the_run_and_the_rest_is_placed() -> None:
    misplaced = word(1.5, 4, 0.3)  # in silence, right after the first word
    measured: list[Timed | None] = [word(1.0, 4), misplaced, None, word(9.0, 4)]
    voice = voice_of((0.9, 1.3), (8.5, 8.62))  # too little voice for both, enough for one
    settled = estimate.settle(measured, [4, 4, 3, 4], 12.0, voice=voice)
    assert settled.words[1] == misplaced
    assert (settled.placed, settled.re_estimated) == (1, 0)
    assert estimated_times(settled) == pytest.approx([8.5, 8.65])


def test_a_word_estimated_anyway_is_not_counted_as_re_estimated() -> None:
    measured: list[Timed | None] = [word(1.0, 4), word(3.0, 4, 0.05), word(6.0, 4)]
    voice = voice_of((0.9, 1.3), (5.0, 6.3))
    settled = estimate.settle(measured, [4, 4, 4], 10.0, voice=voice)
    assert (settled.placed, settled.re_estimated) == (1, 0)
    assert settled.words[1].confidence == 0.05


def test_a_word_after_the_last_stretch_of_voice_goes_on_from_the_word_before() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, None, word(9.0, 4)]
    settled = estimate.settle(measured, [4, 4, 4, 4], 12.0, voice=voice_of((0.9, 1.3), (4.0, 4.2)))
    assert estimated_times(settled) == pytest.approx([4.0, 4.2, 4.2, 4.4])


def test_a_word_of_exactly_the_confident_limit_tells_the_song_its_speed() -> None:
    edge = word(0.0, 2, estimate.CONFIDENT_WORD)
    assert estimate.letter_seconds([edge]) == pytest.approx(PER_LETTER)
    assert estimate.confident_spans([edge, None, word(1.0, 2, 0.49)]) == [(edge.start, edge.end)]


@pytest.mark.parametrize(
    ("confidence", "judged"),
    [(MIN_CONFIDENCE, True), (estimate.SILENT_CONFIDENCE, False)],
)
def test_the_confidence_limits_of_a_word_in_silence_are_inclusive_below(
    confidence: float, judged: bool
) -> None:
    measured: list[Timed | None] = [word(1.0, 4), word(3.0, 4, confidence), word(6.0, 4)]
    settled = estimate.settle(measured, [4, 4, 4], 10.0, voice=voice_of((0.9, 1.3), (5.0, 6.3)))
    assert settled.re_estimated == int(judged)
    assert settled.words[1].estimated == judged


def test_a_word_exactly_as_long_as_the_judged_minimum_is_judged() -> None:
    measured: list[Timed | None] = [
        word(1.0, 4),
        Timed(3.0, 3.0 + estimate.MIN_JUDGED_SECONDS, 0.3, False, ((3.0, 3.1),)),
        word(6.0, 4),
    ]
    settled = estimate.settle(measured, [4, 1, 4], 10.0, voice=voice_of((0.9, 1.3), (5.0, 6.3)))
    assert settled.re_estimated == 1


def test_a_word_of_exactly_the_threshold_is_kept() -> None:
    kept = word(3.0, 4, MIN_CONFIDENCE)
    settled = estimate.settle([word(1.0, 4), kept, word(6.0, 4)], [4, 4, 4], 10.0)
    assert settled.words[1] == kept


def test_every_run_placed_on_the_voice_is_counted() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, word(4.0, 4), None, word(8.0, 4)]
    voice = voice_of((0.9, 1.3), (3.0, 4.3), (7.0, 8.3))
    settled = estimate.settle(measured, [4, 2, 4, 2, 4], 10.0, voice=voice)
    assert settled.placed == 2
    assert estimated_times(settled) == pytest.approx([3.0, 3.1, 7.0, 7.1])


def test_the_first_word_near_the_start_of_the_song_finds_an_early_voice() -> None:
    measured: list[Timed | None] = [None, word(2.0, 4)]
    settled = estimate.settle(measured, [2, 4], 6.0, voice=voice_of((0.5, 0.8), (2.0, 2.3)))
    assert estimated_times(settled) == pytest.approx([0.5, 0.6])


def test_a_voice_start_too_close_before_the_first_measured_word_is_not_used() -> None:
    measured: list[Timed | None] = [None, word(5.0, 4)]
    voice = voice_of((4.95, 5.3))  # 0.05 s before the word; the run needs 0.25 s
    settled = estimate.settle(measured, [5, 4], 8.0, voice=voice)
    assert settled.placed == 0
    assert estimated_times(settled) == pytest.approx([5.0 - 5 * estimate.LETTER_SECONDS, 5.0])


def test_a_word_in_silence_placed_by_the_voice_stays_re_estimated_when_a_later_run_is_not() -> None:
    measured: list[Timed | None] = [
        word(1.0, 4),
        word(3.0, 4, 0.3),  # in silence, the voice starts at 5.0
        word(6.0, 4),
        None,  # no voice start before the last word
        word(9.0, 4),
    ]
    voice = voice_of((0.9, 1.3), (5.0, 6.3), (8.95, 9.3))
    settled = estimate.settle(measured, [4, 4, 4, 4, 4], 12.0, voice=voice)
    assert (settled.placed, settled.re_estimated) == (1, 1)
    assert (settled.words[1].start, settled.words[1].end) == pytest.approx((5.0, 5.2))


def test_the_last_word_takes_the_first_voice_start_after_the_last_measured_word() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None]
    voice = voice_of((0.9, 1.3), (2.0, 2.4), (3.0, 3.6))
    settled = estimate.settle(measured, [4, 4], 12.0, voice=voice)
    assert estimated_times(settled) == pytest.approx([2.0, 2.2])


@given(
    st.lists(
        st.tuples(st.floats(0.0, 1.0), st.integers(1, 8), st.floats(0.01, 1.0), st.booleans()),
        min_size=1,
        max_size=15,
    )
)
def test_a_voice_that_never_sounds_gives_exactly_the_placement_without_the_voice(
    items: list[tuple[float, int, float, bool]],
) -> None:
    # every word of moderate confidence lies in silence and is demoted first; none can be placed,
    # so the re-settling must give every one back and end with the earlier placement
    cursor = 0.0
    measured: list[Timed | None] = []
    weights: list[int] = []
    for confidence, letters, length, sounded in items:
        measured.append(timed(cursor + 0.1, cursor + 0.1 + length, confidence) if sounded else None)
        weights.append(letters)
        cursor += 0.1 + length
    without = estimate.settle(measured, weights, cursor + 1.0)
    silent = estimate.settle(measured, weights, cursor + 1.0, voice=voice_of())
    assert silent == without
    assert (silent.placed, silent.re_estimated) == (0, 0)


def test_the_first_word_takes_the_latest_voice_start_that_leaves_it_room() -> None:
    measured: list[Timed | None] = [None, word(5.0, 4)]
    voice = voice_of((2.5, 3.0), (4.9, 5.3))  # the later start leaves 0.1 s; the run needs 0.25 s
    settled = estimate.settle(measured, [5, 4], 8.0, voice=voice)
    assert settled.placed == 1
    assert estimated_times(settled) == pytest.approx([2.5, 2.75])


# ------------------------------------- the model's position and runs in their line (ADR-0021)


def unsure(start: float, letters: int = 2, confidence: float = 0.02) -> Timed:
    """A word the model placed but is unsure of (below ``MIN_CONFIDENCE``)."""
    return word(start, letters, confidence)


def settle_in_lines(
    measured: list[Timed | None],
    lines: list[int],
    voice: VoiceActivity | None,
    weights: list[int] | None = None,
    duration: float = 30.0,
) -> estimate.Settled:
    sizes = weights or [max(len(m.letters), 1) if m else 2 for m in measured]
    return estimate.settle(measured, sizes, duration, voice=voice, lines=lines)


def test_an_unsure_word_that_is_mostly_voiced_keeps_the_model_position() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(2.0, 4), word(5.0, 4)]
    settled = settle_in_lines(measured, [0, 0, 0], voice_of((1.9, 2.3)))
    kept = settled.words[1]
    assert (kept.start, kept.estimated, kept.confidence) == (2.0, True, 0.02)
    assert kept.letters == ()
    assert (settled.kept, settled.placed) == (1, 0)


def test_an_unsure_word_right_before_the_next_word_of_its_line_is_kept_without_voice() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(4.7), word(5.0, 4)]  # ends 0.2 s before
    settled = settle_in_lines(measured, [0, 0, 0], voice_of((0.9, 1.3), (5.0, 5.4)))
    assert settled.words[1].start == pytest.approx(4.7)
    assert settled.kept == 1


def test_an_unsure_word_that_is_unvoiced_and_far_from_the_next_word_is_not_kept() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(3.0), word(5.0, 4)]
    settled = settle_in_lines(measured, [0, 0, 0], voice_of((0.9, 1.3), (4.0, 5.3)))
    assert settled.words[1].start == pytest.approx(4.0)  # the voice start, as in ADR-0012
    assert (settled.kept, settled.placed) == (0, 1)


def test_the_next_word_must_be_of_the_same_line() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(4.7), word(5.0, 4)]
    settled = settle_in_lines(measured, [0, 0, 1], voice_of((0.9, 1.3), (5.0, 5.4)))
    assert settled.kept == 0


def test_a_line_first_word_in_the_held_note_of_the_line_before_is_not_kept() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(2.5), word(6.0, 4)]
    held = voice_of((0.9, 3.4), (4.5, 6.3))  # the note began before the previous word ended
    settled = settle_in_lines(measured, [0, 1, 1], held)
    assert settled.kept == 0
    assert settled.words[1].start == pytest.approx(4.5)  # the last voice start that leaves room


def test_a_line_first_word_whose_voice_began_after_the_previous_word_is_kept() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(2.5), word(6.0, 4)]
    fresh = voice_of((0.9, 1.3), (2.4, 3.0), (5.0, 6.3))
    settled = settle_in_lines(measured, [0, 1, 1], fresh)
    assert settled.words[1].start == 2.5
    assert settled.kept == 1


def test_a_line_first_word_that_follows_the_previous_word_directly_is_kept() -> None:
    """A sung vocalise right after the line before: the voice that goes on is its own note."""
    measured: list[Timed | None] = [word(1.0, 4), unsure(1.25, 4), word(6.0, 4)]
    settled = settle_in_lines(measured, [0, 1, 1], voice_of((0.9, 3.4), (5.9, 6.3)))
    assert settled.words[1].start == 1.25  # 0.05 s after the previous word's end of 1.2
    assert settled.kept == 1


@pytest.mark.parametrize(
    ("start", "kept"),
    [(1.25, True), (1.3125, True), (1.375, False)],  # 0, 0.0625 and 0.125 s after 1.25
)
def test_only_a_line_first_word_within_the_direct_distance_of_the_previous_end_is_kept(
    start: float, kept: bool
) -> None:
    measured: list[Timed | None] = [word(1.0, 5), unsure(start, 4), word(6.0, 4)]
    settled = settle_in_lines(measured, [0, 1, 1], voice_of((0.9, 3.4), (5.9, 6.3)))
    assert (settled.words[1].start == start) is kept
    assert settled.kept == int(kept)


def test_a_line_first_word_exactly_the_direct_distance_after_the_previous_end_is_kept() -> None:
    # 0.225 - 0.125 is exactly 0.1 in floating point, so this is the boundary itself.
    measured: list[Timed | None] = [word(0.025, 2), unsure(0.225, 4), word(6.0, 4)]
    settled = settle_in_lines(measured, [0, 1, 1], voice_of((0.0, 3.4), (5.9, 6.3)))
    assert (settled.words[1].start, settled.kept) == (0.225, 1)


def test_a_voice_that_begins_exactly_at_the_previous_end_backs_the_line_first_word() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(2.5), word(6.0, 4)]  # first ends at 1.2
    settled = settle_in_lines(measured, [0, 1, 1], voice_of((1.2, 3.0), (5.9, 6.3)))
    assert (settled.words[1].start, settled.kept) == (2.5, 1)


def test_a_line_first_word_in_a_held_note_but_right_before_its_next_word_is_kept() -> None:
    """The regression: the model hears the short word right, the voice is still the held note."""
    measured: list[Timed | None] = [word(1.0, 4), unsure(2.8, 2), word(3.0, 4)]
    settled = settle_in_lines(measured, [0, 1, 1], voice_of((0.9, 3.4)))
    assert settled.words[1].start == 2.8
    assert settled.kept == 1


def test_a_measured_word_in_silence_is_re_estimated_and_never_kept() -> None:
    silent = word(2.0, 4, 0.3)  # ends 0.2 s before the next word, but lies in silence
    measured: list[Timed | None] = [word(1.0, 4), silent, word(2.4, 4)]
    settled = settle_in_lines(measured, [0, 0, 0], voice_of((1.3, 1.9), (2.4, 2.8)))
    assert settled.re_estimated == 1
    assert settled.kept == 0
    assert settled.words[1].start == pytest.approx(1.3)  # placed on the voice instead


def test_keeping_does_not_chain() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(4.2), unsure(4.7), word(5.0, 4)]
    settled = settle_in_lines(measured, [0, 0, 0, 0], voice_of((0.9, 1.3)))
    assert settled.kept == 1  # the second ends right before the last; the first has no anchor
    assert settled.words[2].start == pytest.approx(4.7)
    assert settled.words[1].start < 4.2  # shared in the gap before the kept word, not at 4.2


def test_a_kept_word_ends_at_its_letters_but_never_after_the_next_word() -> None:
    long_gap: list[Timed | None] = [word(1.0, 4), unsure(2.0, 2), word(5.0, 4)]
    roomy = settle_in_lines(long_gap, [0, 0, 0], voice_of((1.9, 2.3)), weights=[4, 10, 4])
    assert roomy.words[1].end == pytest.approx(2.0 + 10 * PER_LETTER)
    tight: list[Timed | None] = [word(1.0, 4), unsure(2.0, 2), word(2.2, 4)]
    capped = settle_in_lines(tight, [0, 0, 0], voice_of((1.9, 2.3)), weights=[4, 10, 4])
    assert capped.words[1].end == pytest.approx(2.2)
    short = settle_in_lines(long_gap, [0, 0, 0], voice_of((1.9, 2.3)), weights=[4, 1, 4])
    assert short.words[1].end == pytest.approx(2.1)  # the model's own end stays


def test_without_lines_nothing_is_kept_and_runs_cross_line_breaks_as_before() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(2.0, 4), word(5.0, 4)]
    voice = voice_of((1.9, 2.3), (3.5, 4.5))
    settled = estimate.settle(measured, [4, 4, 4], 30.0, voice=voice)
    assert settled.kept == 0
    assert settled.words[1].start == pytest.approx(1.9)  # placed on the voice, as in ADR-0012
    assert settled.placed == 1


def test_with_the_voice_off_lines_change_nothing() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, None, word(8.0, 4)]
    plain = estimate.settle(measured, [4, 3, 3, 4], 30.0)
    lined = estimate.settle(measured, [4, 3, 3, 4], 30.0, lines=[0, 0, 1, 1])
    assert lined == plain


def test_a_run_across_a_line_break_becomes_two_runs() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, None, word(8.0, 4)]
    voice = voice_of((0.9, 1.3), (2.0, 2.6), (6.0, 7.5))
    settled = settle_in_lines(measured, [0, 0, 1, 1], voice, weights=[4, 3, 3, 4])
    last, first = settled.words[1], settled.words[2]
    assert last.start == pytest.approx(
        2.0
    )  # the line's last word goes forward from the word before
    assert first.start == pytest.approx(6.0)  # the next line's first word, from its last onset
    assert last.end <= first.start


def test_a_line_last_run_does_not_reach_further_than_the_edge_reach() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, word(20.0, 4)]
    voice = voice_of((0.5, 1.1), (9.0, 9.6))  # nothing sounds within the reach
    settled = settle_in_lines(measured, [0, 0, 1], voice, weights=[4, 3, 4])
    assert settled.words[1].end <= 1.2 + estimate.EDGE_REACH_SECONDS + 1e-9
    assert settled.words[1].end == pytest.approx(1.2 + 3 * estimate.LETTER_SECONDS)


def test_a_line_first_run_with_the_voice_through_the_gap_sits_right_before_the_next_word() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, word(5.0, 4)]
    settled = settle_in_lines(measured, [0, 1, 1], voice_of((0.9, 6.0)), weights=[4, 3, 4])
    assert (settled.words[1].start, settled.words[1].end) == pytest.approx(
        (5.0 - 3 * estimate.LETTER_SECONDS, 5.0)
    )
    assert settled.placed == 0


def test_a_fully_estimated_line_is_placed_against_the_first_word_of_the_next_line() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None, None, word(9.0, 4)]
    voice = voice_of((0.9, 1.3), (2.0, 3.0), (7.0, 8.5))
    settled = settle_in_lines(measured, [0, 1, 1, 2], voice, weights=[4, 3, 3, 4])
    assert settled.words[1].start == pytest.approx(7.0)  # not at the first voice start, 2.0


def test_a_fully_estimated_last_line_goes_forward_from_its_previous_word() -> None:
    measured: list[Timed | None] = [word(1.0, 4), None]
    settled = settle_in_lines(measured, [0, 1], voice_of((0.9, 1.3), (2.0, 3.0)), weights=[4, 3])
    assert settled.words[1].start == pytest.approx(2.0)


@given(
    st.lists(
        st.tuples(
            st.floats(0.0, 1.0),
            st.integers(1, 6),
            st.floats(0.02, 0.6),
            st.booleans(),
            st.booleans(),
        ),
        min_size=1,
        max_size=14,
    ),
    st.lists(st.tuples(st.floats(0.0, 20.0), st.floats(0.1, 4.0)), max_size=8),
)
def test_with_lines_words_keep_order_the_model_position_and_the_voice_rules(
    items: list[tuple[float, int, float, bool, bool]], voice_parts: list[tuple[float, float]]
) -> None:
    measured: list[Timed | None] = []
    weights: list[int] = []
    lines: list[int] = []
    cursor, line = 0.0, 0
    for confidence, letters, length, new_line, silent in items:
        measured.append(
            None
            if silent
            else Timed(
                cursor + 0.1,
                cursor + 0.1 + length,
                confidence,
                False,
                ((cursor + 0.1, cursor + 0.1 + length),),
            )
        )
        weights.append(letters)
        line += new_line
        lines.append(line)
        cursor += 0.1 + length
    spans = disjoint_spans(voice_parts)
    voice = voice_of(*spans)
    settled = estimate.settle(measured, weights, cursor + 1.0, voice=voice, lines=lines)
    words = settled.words
    assert_ordered(words, len(items))
    assert words[-1].end <= cursor + 1.0 + 1e-9
    assert settled.kept <= sum(w.estimated for w in words)
    for index, (found, now) in enumerate(zip(measured, words, strict=True)):
        if found is None or not now.estimated:
            continue
        first_of_line = index == 0 or lines[index - 1] != lines[index]
        earlier = [m.end for m in measured[:index] if m is not None]
        previous_end = earlier[-1] if earlier else 0.0
        held = any(a < previous_end - 1e-6 and a <= found.start < b for a, b in spans)
        if (
            found.confidence < MIN_CONFIDENCE
            and found.end > found.start
            and voice.voiced_fraction(found.start, found.end) >= estimate.KEEP_VOICED_SHARE
            and not (first_of_line and held)
        ):
            assert now.start == found.start  # a voiced word keeps the model's start


def exact(start: float, end: float, confidence: float = 0.9) -> Timed:
    """A word with one letter from ``start`` to ``end`` (binary fractions keep the edges exact)."""
    return Timed(start, end, confidence, False, ((start, end),))


def test_a_word_exactly_half_voiced_is_kept() -> None:
    measured: list[Timed | None] = [exact(1.0, 2.0), exact(3.0, 3.5, 0.02), exact(8.0, 9.0)]
    settled = settle_in_lines(measured, [0, 0, 0], voice_of((3.0, 3.25)))
    assert (settled.words[1].start, settled.kept) == (3.0, 1)
    less = settle_in_lines(measured, [0, 0, 0], voice_of((3.0, 3.2)))
    assert less.kept == 0


def test_a_word_ending_exactly_at_the_next_word_is_kept_and_one_far_before_it_is_not() -> None:
    touching: list[Timed | None] = [exact(1.0, 2.0), exact(3.0, 3.5, 0.02), exact(3.5, 4.0)]
    assert settle_in_lines(touching, [0, 0, 0], voice_of((0.5, 1.5))).kept == 1
    apart: list[Timed | None] = [exact(1.0, 2.0), exact(3.0, 3.5, 0.02), exact(3.85, 4.5)]
    assert settle_in_lines(apart, [0, 0, 0], voice_of((0.5, 1.5))).kept == 0


def test_a_kept_word_of_one_letter_ends_at_the_model_end() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(2.0, 1), word(5.0, 4)]
    settled = settle_in_lines(measured, [0, 0, 0], voice_of((1.9, 2.3)), weights=[4, 1, 4])
    assert settled.words[1].end == pytest.approx(2.0 + PER_LETTER)


def test_a_run_inside_a_line_is_placed_between_its_neighbours_even_far_from_them() -> None:
    measured: list[Timed | None]
    lines = [0, 1, 1, 1]
    measured = [exact(0.5, 0.75), exact(1.0, 2.0), None, exact(20.0, 21.0)]
    settled = settle_in_lines(measured, lines, voice_of((0.5, 1.5), (9.0, 10.0)), [1] * 4)
    assert settled.words[2].start == 9.0  # beyond EDGE_REACH_SECONDS, as for a run in a line


def test_a_line_last_run_takes_the_first_voice_start_after_the_word_before() -> None:
    measured: list[Timed | None] = [exact(1.0, 2.0), None, exact(20.0, 21.0)]
    voice = voice_of((0.5, 1.5), (2.5, 2.75), (3.0, 3.5))
    settled = settle_in_lines(measured, [0, 0, 1], voice, weights=[1, 1, 1])
    assert settled.words[1].start == 2.5


@given(
    st.lists(
        st.tuples(st.floats(0.0, 1.0), st.integers(0, 6), st.floats(0.0, 0.6), st.booleans()),
        min_size=1,
        max_size=14,
    )
)
def test_without_the_voice_the_lines_never_change_the_placement(
    items: list[tuple[float, int, float, bool]],
) -> None:
    measured: list[Timed | None] = []
    lines: list[int] = []
    cursor, line = 0.0, 0
    for confidence, letters, length, new_line in items:
        measured.append(None if letters == 0 else word(cursor + 0.1, letters, confidence))
        line += new_line
        lines.append(line)
        cursor += 0.1 + max(length, letters * PER_LETTER)
    weights = [max(len(m.letters), 1) if m else 2 for m in measured]
    plain = estimate.settle(measured, weights, cursor + 1.0)
    assert estimate.settle(measured, weights, cursor + 1.0, lines=lines) == plain


def test_inside_a_line_a_voice_that_goes_on_from_the_word_before_backs_every_unsure_word() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(1.4), unsure(1.6), word(5.0, 4)]
    settled = settle_in_lines(measured, [0, 0, 0, 0], voice_of((0.9, 1.8)))
    assert [w.start for w in settled.words[1:3]] == [1.4, 1.6]
    assert settled.kept == 2


def test_a_held_note_that_ends_where_the_line_first_word_starts_does_not_hold_it_back() -> None:
    measured: list[Timed | None] = [exact(1.0, 2.0), exact(2.5, 2.625, 0.02), exact(6.0, 7.0)]
    voice = voice_of((0.5, 2.5), (2.53125, 3.0))  # the held note ends exactly at the word's start
    settled = settle_in_lines(measured, [0, 1, 1], voice)
    assert (settled.words[1].start, settled.kept) == (2.5, 1)


def test_a_word_ending_exactly_the_next_word_distance_before_the_next_word_is_kept() -> None:
    measured: list[Timed | None] = [exact(0.0, 0.01, 0.02), exact(0.31, 0.5)]
    assert measured[1] is not None and measured[0] is not None
    assert measured[1].start - measured[0].end == estimate.KEEP_NEXT_SECONDS  # exactly
    assert settle_in_lines(measured, [0, 0], voice_of((0.31, 0.5))).kept == 1


def test_a_kept_word_ends_before_the_model_start_of_an_unsure_word_after_it() -> None:
    measured: list[Timed | None] = [word(1.0, 4), unsure(2.0, 2), unsure(2.3, 2), word(5.0, 4)]
    voice = voice_of((1.9, 2.15))  # the first unsure word is voiced, the second is not
    settled = settle_in_lines(measured, [0, 0, 0, 0], voice, weights=[4, 10, 2, 4])
    assert settled.kept == 1
    assert settled.words[1].end == pytest.approx(2.3)  # not 2.0 + 10 letters, past the next word


# ------------------------------------- an undone re-estimate


def test_an_undone_re_estimate_keeps_the_model_start_with_voice_at_the_end_of_its_gap() -> None:
    # The kept word after it (first of its line) shrinks the gap to 1.2 to 5.0 s; the voice there
    # is 0.08 s, too little for the voice placement, so the re-estimate is undone. The voice
    # detection can miss quiet singing, so the model's start is trusted over the late voice.
    measured: list[Timed | None] = [word(1.0, 4), word(3.0, 4, 0.3), unsure(5.0, 4)]
    settled = settle_in_lines(measured, [0, 0, 1], voice_of((0.9, 1.2), (4.92, 5.5)))
    assert settled.words[2].start == 5.0 and settled.kept == 1
    assert settled.words[1] == measured[1]
    assert (settled.re_estimated, settled.placed) == (0, 0)
