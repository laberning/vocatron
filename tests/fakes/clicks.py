"""Synthetic songs with a known tempo: click tracks and drum patterns."""

import numpy as np

from vocatron.core.tempo import SAMPLE_RATE, Samples

BURST = 2000  # samples of one drum hit


def drum_pattern(
    bpm: float,
    seconds: float = 30.0,
    swing: float = 0.0,
    jitter: float = 0.0,
    seed: int = 0,
) -> Samples:
    """Return a kick on every beat and a hi-hat between the beats, at ``bpm``.

    Args:
        bpm: The tempo.
        seconds: The length.
        swing: How far the hi-hat is pushed later, in beats (0.2 is a heavy swing).
        jitter: The standard deviation of the timing error of every hit, in seconds.
        seed: Seeds the hi-hat noise and the jitter.
    """
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)
    age = np.arange(BURST) / SAMPLE_RATE
    decay = np.exp(-age * 60)
    kick = decay * np.sin(2 * np.pi * 80 * age * (1 + 3 * np.exp(-age * 40)))
    beat = 60.0 / bpm
    for number in range(int(seconds / beat)):
        for offset, hit in ((0.0, kick), (0.5 + swing / 2, 0.25 * decay * rng.normal(size=BURST))):
            start = int((number * beat + offset * beat + rng.normal(0, jitter)) * SAMPLE_RATE)
            if start >= 0 and start + BURST <= out.shape[0]:
                out[start : start + BURST] += hit.astype(np.float32)
    return out


def clicks(bpm: float, seconds: float = 30.0) -> Samples:
    """Return a bare click on every beat at ``bpm``."""
    out = np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)
    age = np.arange(BURST) / SAMPLE_RATE
    click = (np.exp(-age * 200) * np.sin(2 * np.pi * 1000 * age)).astype(np.float32)
    for start in (np.arange(0, seconds, 60.0 / bpm) * SAMPLE_RATE).astype(int):
        stop = min(start + BURST, out.shape[0])
        out[start:stop] += click[: stop - start]
    return out


def noise(seconds: float = 30.0, seed: int = 0) -> Samples:
    """Return white noise at a low level."""
    rng = np.random.default_rng(seed)
    return (0.1 * rng.normal(size=int(seconds * SAMPLE_RATE))).astype(np.float32)
