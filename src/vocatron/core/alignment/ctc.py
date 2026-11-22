"""The Viterbi search over the CTC trellis (ADR-0002).

Given the model's log-probabilities per frame and the tokens to find, it returns the most
probable frame-by-frame path through the trellis: blanks between tokens, a token held for one
or more frames, and the same token twice in a row only with a blank between. Each token may be
confined to a window of frames. For the tokens of one transcript the result equals torchaudio's
``forced_align`` frame for frame; a test keeps it so.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

LogProbs = NDArray[np.float32]
"""Log-probabilities shaped (frames, vocabulary)."""
NEG_INF = np.float32(-np.inf)


@dataclass(frozen=True)
class CtcPath:
    """The best path through the trellis.

    Attributes:
        states: The trellis state of every frame; odd ``2k + 1`` is target ``k``, even is blank.
        scores: The log-probability the model gave to the path's label at every frame.
        total: The sum of ``scores``.
    """

    states: NDArray[np.int32]
    scores: NDArray[np.float32]
    total: float


@dataclass(frozen=True)
class Spans:
    """The frames of every target token.

    Attributes:
        first: The first frame of each target.
        last: The last frame of each target (inclusive).
    """

    first: NDArray[np.int64]
    last: NDArray[np.int64]


def _state_windows(
    windows: Sequence[tuple[int, int]] | None, count: int, frames: int
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Return the first and last frame each trellis state may occupy.

    Only the tokens are confined. A blank needs no window of its own: it lies between the
    tokens around it, so their windows already bound it, and a window for it would change no
    path.
    """
    first = np.zeros(2 * count + 1, dtype=np.int64)
    last = np.full(2 * count + 1, frames - 1, dtype=np.int64)
    if windows is None:
        return first, last
    if len(windows) != count:
        raise ValueError(f"{len(windows)} windows for {count} tokens")
    first[1::2] = [w[0] for w in windows]
    last[1::2] = [w[1] for w in windows]
    return first, last


def viterbi(
    log_probs: LogProbs,
    targets: Sequence[int],
    blank: int,
    windows: Sequence[tuple[int, int]] | None = None,
) -> CtcPath:
    """Find the most probable alignment of ``targets`` on the frames.

    Args:
        log_probs: The log-probabilities, shaped (frames, vocabulary).
        targets: The token ids to find, in order; at least one.
        blank: The id of the CTC blank.
        windows: For each target the first and last frame (inclusive) it may occupy.

    Returns:
        The path with the label scores.

    Raises:
        ValueError: If there are no targets, a shape does not fit, or no path exists (too few
            frames, or windows that leave no way through).
    """
    frames, vocabulary = log_probs.shape
    if not targets:
        raise ValueError("nothing to align: no targets")
    if not all(0 <= t < vocabulary for t in (blank, *targets)):
        raise ValueError("a token id lies outside the vocabulary")
    labels = np.full(2 * len(targets) + 1, blank, dtype=np.int64)
    labels[1::2] = targets
    size = labels.size
    can_skip = np.zeros(size, dtype=bool)
    can_skip[2:] = (labels[2:] != blank) & (labels[2:] != labels[:-2])
    low, high = _state_windows(windows, len(targets), frames)
    alpha = np.full(size, NEG_INF, dtype=np.float32)
    back = np.zeros((frames, size), dtype=np.int8)
    for t in range(frames):
        emit = np.where((low <= t) & (t <= high), log_probs[t, labels], NEG_INF)
        if t == 0:
            alpha[:2] = emit[:2]
            continue
        stay, one, two = alpha, np.full(size, NEG_INF), np.full(size, NEG_INF)
        one[1:] = alpha[:-1]
        two[2:] = np.where(can_skip[2:], alpha[:-2], NEG_INF)
        choices = np.stack([stay, one, two])
        step = choices.argmax(axis=0)
        alpha = np.take_along_axis(choices, step[None, :], axis=0)[0] + emit
        back[t] = step
    end = size - 1 if alpha[size - 1] >= alpha[size - 2] else size - 2
    if not np.isfinite(alpha[end]):
        raise ValueError(f"no alignment path: {len(targets)} tokens do not fit {frames} frames")
    states = np.empty(frames, dtype=np.int32)
    state = end
    for t in range(frames - 1, -1, -1):
        states[t] = state
        state -= int(back[t, state])
    scores = log_probs[np.arange(frames), labels[states]].astype(np.float32)
    return CtcPath(states, scores, float(scores.sum()))


def token_spans(path: CtcPath, count: int) -> Spans:
    """Return the first and last frame of each of the ``count`` target tokens on ``path``.

    Every token is covered: a path ends only after it has passed all of them.
    """
    frames = np.flatnonzero(path.states % 2 == 1)
    owners = (path.states[frames] - 1) // 2
    wanted = np.arange(count)
    first = frames[np.searchsorted(owners, wanted, side="left")]
    last = frames[np.searchsorted(owners, wanted, side="right") - 1]
    return Spans(first.astype(np.int64), last.astype(np.int64))
