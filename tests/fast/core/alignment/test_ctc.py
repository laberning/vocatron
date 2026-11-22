"""Stage 1: the CTC Viterbi: properties, a brute-force reference, windows, padding."""

import itertools

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from numpy.typing import NDArray

from vocatron.core.alignment.ctc import CtcPath, token_spans, viterbi

BLANK = 0
VOCABULARY = 5


@st.composite
def problems(
    draw: st.DrawFn, max_frames: int = 14, max_tokens: int = 5
) -> tuple[NDArray[np.float32], list[int]]:
    """Random log-probabilities and targets that fit (frames cover the tokens and repeats)."""
    targets = draw(st.lists(st.integers(1, VOCABULARY - 1), min_size=1, max_size=max_tokens))
    needed = len(targets) + sum(a == b for a, b in itertools.pairwise(targets))
    frames = draw(st.integers(needed, max(needed, max_frames)))
    seed = draw(st.integers(0, 2**32 - 1))
    raw = np.random.default_rng(seed).dirichlet(np.ones(VOCABULARY) * 0.5, size=frames)
    return np.log(np.maximum(raw, 1e-9)).astype(np.float32), targets


def collapse(labels: list[int]) -> list[int]:
    """The CTC rule: merge repeats, then drop blanks."""
    merged = [a for a, _ in itertools.groupby(labels)]
    return [a for a in merged if a != BLANK]


def labels_of(path: CtcPath, targets: list[int]) -> list[int]:
    extended = [BLANK] * (2 * len(targets) + 1)
    extended[1::2] = targets
    return [extended[s] for s in path.states]


def brute_force(log_probs: NDArray[np.float32], targets: list[int]) -> float:
    """The best score of any frame labelling that collapses to the targets."""
    best = -np.inf
    for labels in itertools.product(range(VOCABULARY), repeat=len(log_probs)):
        if collapse(list(labels)) == targets:
            best = max(best, float(sum(log_probs[t, label] for t, label in enumerate(labels))))
    return best


@given(problems())
def test_the_path_collapses_to_the_targets_and_covers_every_token(
    problem: tuple[NDArray[np.float32], list[int]],
) -> None:
    log_probs, targets = problem
    path = viterbi(log_probs, targets, BLANK)
    assert collapse(labels_of(path, targets)) == targets
    assert len(path.states) == len(log_probs)
    spans = token_spans(path, len(targets))
    assert (spans.first <= spans.last).all()  # every token has a frame
    assert (spans.first[1:] > spans.last[:-1]).all()  # in order, no overlap
    covered = sum(int(b - a + 1) for a, b in zip(spans.first, spans.last, strict=True))
    assert covered <= len(log_probs)


@given(problems())
def test_states_never_go_back_and_move_at_most_two_at_a_time(
    problem: tuple[NDArray[np.float32], list[int]],
) -> None:
    log_probs, targets = problem
    steps = np.diff(viterbi(log_probs, targets, BLANK).states)
    assert ((steps >= 0) & (steps <= 2)).all()


@given(problems())
def test_the_scores_are_the_log_probabilities_along_the_path(
    problem: tuple[NDArray[np.float32], list[int]],
) -> None:
    log_probs, targets = problem
    path = viterbi(log_probs, targets, BLANK)
    expected = [log_probs[t, label] for t, label in enumerate(labels_of(path, targets))]
    assert np.allclose(path.scores, expected)
    assert path.total == pytest.approx(float(np.sum(expected)), rel=1e-5)


@given(problems(max_frames=7, max_tokens=3))
def test_the_path_is_as_good_as_the_best_of_all_alignments(
    problem: tuple[NDArray[np.float32], list[int]],
) -> None:
    log_probs, targets = problem
    assert viterbi(log_probs, targets, BLANK).total == pytest.approx(
        brute_force(log_probs, targets), rel=1e-4, abs=1e-4
    )


@given(problems(), st.integers(0, 6), st.integers(0, 6))
def test_blank_padding_around_the_audio_only_shifts_the_spans(
    problem: tuple[NDArray[np.float32], list[int]], before: int, after: int
) -> None:
    log_probs, targets = problem
    silence = np.full(VOCABULARY, -50.0, dtype=np.float32)
    silence[BLANK] = 0.0
    padded = np.concatenate(
        [np.tile(silence, (before, 1)), log_probs, np.tile(silence, (after, 1))]
    )
    plain = token_spans(viterbi(log_probs, targets, BLANK), len(targets))
    shifted = token_spans(viterbi(padded, targets, BLANK), len(targets))
    assert (shifted.first == plain.first + before).all()
    assert (shifted.last == plain.last + before).all()


@given(problems(), st.integers(0, 3))
def test_windows_are_respected_when_a_path_exists(
    problem: tuple[NDArray[np.float32], list[int]], slack: int
) -> None:
    log_probs, targets = problem
    free = token_spans(viterbi(log_probs, targets, BLANK), len(targets))
    last_frame = len(log_probs) - 1
    windows = [
        (max(int(a) - slack, 0), min(int(b) + slack, last_frame))
        for a, b in zip(free.first, free.last, strict=True)
    ]
    held = token_spans(viterbi(log_probs, targets, BLANK, windows), len(targets))
    for (low, high), a, b in zip(windows, held.first, held.last, strict=True):
        assert low <= a <= b <= high


def brute_force_windowed(
    log_probs: NDArray[np.float32], targets: list[int], windows: list[tuple[int, int]]
) -> float:
    """The best score of any labelling that collapses to the targets inside their windows."""
    best = -np.inf
    for labels in itertools.product(range(VOCABULARY), repeat=len(log_probs)):
        if collapse(list(labels)) != targets:
            continue
        runs: list[tuple[int, int]] = []
        frame = 0
        for label, group in itertools.groupby(labels):
            length = len(list(group))
            if label != BLANK:
                runs.append((frame, frame + length - 1))
            frame += length
        if all(low <= a and b <= high for (a, b), (low, high) in zip(runs, windows, strict=True)):
            best = max(best, float(sum(log_probs[t, label] for t, label in enumerate(labels))))
    return best


@given(problems(max_frames=6, max_tokens=3), st.data())
def test_windowed_path_is_the_best_of_all_alignments_inside_the_windows(
    problem: tuple[NDArray[np.float32], list[int]], data: st.DataObject
) -> None:
    # Only the tokens carry windows; this pins that blanks need none of their own.
    log_probs, targets = problem
    last_frame = len(log_probs) - 1
    windows: list[tuple[int, int]] = []
    for _ in targets:
        low = data.draw(st.integers(0, last_frame))
        windows.append((low, data.draw(st.integers(low, last_frame))))
    best = brute_force_windowed(log_probs, targets, windows)
    if best == -np.inf:
        with pytest.raises(ValueError, match="no alignment path"):
            viterbi(log_probs, targets, BLANK, windows)
        return
    path = viterbi(log_probs, targets, BLANK, windows)
    assert path.total == pytest.approx(best, rel=1e-4, abs=1e-4)


def test_a_window_that_leaves_no_path_is_an_error() -> None:
    log_probs = np.log(np.full((6, VOCABULARY), 0.2, dtype=np.float32))
    with pytest.raises(ValueError, match="no alignment path"):
        viterbi(log_probs, [1, 2], BLANK, [(4, 5), (0, 1)])


def test_too_few_frames_for_the_tokens_is_an_error() -> None:
    log_probs = np.log(np.full((3, VOCABULARY), 0.2, dtype=np.float32))
    with pytest.raises(ValueError, match="no alignment path"):
        viterbi(log_probs, [1, 1, 1], BLANK)  # repeats need a blank between them


@pytest.mark.parametrize(
    ("targets", "windows", "message"),
    [
        ([], None, "no targets"),
        ([9], None, "outside the vocabulary"),
        ([VOCABULARY], None, "outside the vocabulary"),  # the first id past the end
        ([1], [(0, 1), (0, 1)], "windows"),
    ],
)
def test_bad_arguments_are_errors(
    targets: list[int], windows: list[tuple[int, int]] | None, message: str
) -> None:
    log_probs = np.log(np.full((4, VOCABULARY), 0.2, dtype=np.float32))
    with pytest.raises(ValueError, match=message):
        viterbi(log_probs, targets, BLANK, windows)


def test_a_clear_signal_is_found_where_it_is() -> None:
    log_probs = np.log(np.full((10, VOCABULARY), 0.01, dtype=np.float32))
    log_probs[:, BLANK] = np.log(0.96)
    log_probs[3] = np.log(0.01)
    log_probs[3, 2] = np.log(0.96)
    log_probs[7] = np.log(0.01)
    log_probs[7, 4] = np.log(0.96)
    spans = token_spans(viterbi(log_probs, [2, 4], BLANK), 2)
    assert list(spans.first) == [3, 7]
    assert list(spans.last) == [3, 7]
