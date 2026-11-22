"""The pure rules of vocal separation: chunks, overlap-add, mixing, headroom, device, timeout.

The network itself lives in the separation engine; everything that decides is here and testable
with NumPy alone (ADR-0002, ADR-0007). Audio is a float32 array shaped (channels, samples).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from vocatron.core.errors import StageError

Audio = NDArray[np.float32]
"""Audio shaped (channels, samples), values in -1..1 unless a stem exceeds full scale."""

SAMPLE_RATE = 44100
CHANNELS = 2
MIN_OVERLAP = 2
"""Fewer chunks per sample would lose the first sample: the chunk ends fade to zero."""
FADE_DIVISOR = 10
"""Each end of a chunk fades linearly over a tenth of its length."""
CEILING_DB = -0.1
"""A stem whose peak exceeds full scale is scaled down to this level (ADR-0002)."""
GIB = 1 << 30
MIN_FREE_VRAM = 2 * GIB
"""The free GPU memory ``auto`` needs before it chooses the GPU."""
TIMEOUT_BASE = 120.0
"""Seconds added to the song-length part of the timeout: loading the models and writing stems."""
CPU_SLOWDOWN = 20
KARAOKE_INPUT_PEAK = 0.9
"""The lead and backing model gets the vocals scaled to this peak and its output scaled back.

The model is not scale-invariant; the trial of ADR-0002 gave it its input at this peak. A change
changes the stems and needs a new version of the separation stage."""
DEFAULT_DURATION = 600.0
"""The length assumed for the timeout when the tags do not tell it."""
VRAM_FRACTION = 0.75
"""The share of GPU memory PyTorch may take, so that an overflow is an ordinary error (ADR-0002)."""
EXIT_FAILED = 1
"""The exit code of a worker that failed."""
EXIT_OUT_OF_MEMORY = 3
"""The exit code of a worker that ran out of GPU memory."""

Device = Literal["cuda", "cpu"]
DeviceRequest = Literal["auto", "cuda", "cpu"]

ChunkProcessor = Callable[[Audio], Audio]
"""Maps a chunk (channels, chunk) to the separated chunk of the same shape."""
Progress = Callable[[int, int], None]
"""Called with the number of the chunk just done (from 1) and the number of chunks."""


@dataclass(frozen=True)
class ChunkPlan:
    """Where the chunks of a song lie in the padded signal.

    Attributes:
        samples: The length of the song.
        chunk: The chunk length.
        step: The distance between two chunk starts.
        border: The zeros put before the song so that its first sample is covered fully.
        padded: The length of the padded signal.
        starts: The start of every chunk in the padded signal.
    """

    samples: int
    chunk: int
    step: int
    border: int
    padded: int
    starts: tuple[int, ...]


def plan_chunks(samples: int, chunk: int, num_overlap: int) -> ChunkPlan:
    """Plan the chunks of a song of ``samples`` samples.

    A chunk starts every ``chunk // num_overlap`` samples; the signal gets ``chunk - step``
    zeros before the song and ``chunk - step + chunk`` after it, so that every sample of the song
    lies in ``num_overlap`` chunks.

    Raises:
        ValueError: If ``samples`` is negative, or ``num_overlap`` is below 2 (the chunk ends fade
            to zero, so without overlap the song's first sample would be lost) or exceeds ``chunk``;
            a ``chunk`` below 2 is refused through that overlap rule.
    """
    if samples < 0 or not MIN_OVERLAP <= num_overlap <= chunk:
        raise ValueError(f"invalid chunk plan: {samples=}, {chunk=}, {num_overlap=}")
    step = chunk // num_overlap
    border = chunk - step
    padded = samples + 2 * border + chunk
    starts = tuple(range(0, padded - chunk + 1, step))
    return ChunkPlan(samples, chunk, step, border, padded, starts)


def fade_window(chunk: int) -> NDArray[np.float32]:
    """Return the weight of each sample of a chunk: 1 with linear fades at both ends."""
    fade = max(chunk // FADE_DIVISOR, 1)
    window = np.ones(chunk, dtype=np.float32)
    ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    window[:fade] = ramp
    window[-fade:] = ramp[::-1]
    return window


def overlap_add(
    audio: Audio, plan: ChunkPlan, process: ChunkProcessor, progress: Progress | None = None
) -> Audio:
    """Run ``process`` over the overlapping chunks and blend the results.

    The results are weighted with ``fade_window`` and divided by the summed weights, so a
    ``process`` that returns its input gives the song back.

    Args:
        audio: The song, shaped (channels, plan.samples).
        plan: The chunk plan of the song.
        process: Separates one chunk.
        progress: Told after every chunk.

    Returns:
        The blended result, shaped like ``audio``.

    Raises:
        ValueError: If ``audio`` does not have ``plan.samples`` samples, or ``process`` returns a
            chunk of the wrong shape.
    """
    channels, samples = audio.shape
    if samples != plan.samples:
        raise ValueError(f"the plan is for {plan.samples} samples, the audio has {samples}")
    padded = np.zeros((channels, plan.padded), dtype=np.float32)
    padded[:, plan.border : plan.border + samples] = audio
    out = np.zeros_like(padded)
    weight = np.zeros(plan.padded, dtype=np.float32)
    window = fade_window(plan.chunk)
    for index, start in enumerate(plan.starts, start=1):
        piece = process(padded[:, start : start + plan.chunk])
        if piece.shape != (channels, plan.chunk):
            raise ValueError(f"the chunk came back as {piece.shape}, not {(channels, plan.chunk)}")
        out[:, start : start + plan.chunk] += piece * window
        weight[start : start + plan.chunk] += window
        if progress is not None:
            progress(index, len(plan.starts))
    out /= np.maximum(weight, np.float32(1e-8))
    return out[:, plan.border : plan.border + samples]


def normalise_peak(audio: Audio, target: float = KARAOKE_INPUT_PEAK) -> tuple[Audio, float]:
    """Scale ``audio`` so that its peak is ``target``.

    Returns:
        The scaled audio and the factor applied (1.0 for silence, which is left alone).
    """
    top = peak(audio)
    if top == 0.0:
        return audio, 1.0
    factor = target / top
    return (audio * np.float32(factor)).astype(np.float32), factor


def mix_stems(first: Audio, second: Audio) -> Audio:
    """Return the sum of two stems of the same shape (instrumental plus backing vocals)."""
    if first.shape != second.shape:
        raise ValueError(f"cannot mix stems of shapes {first.shape} and {second.shape}")
    return first + second


def combine_estimates(
    mix: Audio, estimates: Sequence[tuple[Audio, Literal["vocals", "instrumental"]]]
) -> tuple[Audio, Audio]:
    """Return ``(vocals, instrumental)`` from the estimates of one or more models.

    Each estimate is a model's first output and says what it is. One model gives its own stem and
    the mix minus it as the other. Several models are averaged on the waveform: the instrumental
    is the mean of their instrumentals (an estimate of the vocals counts as the mix minus it) and
    the vocals are the mix minus that.

    Raises:
        ValueError: If there are no estimates or a shape differs from the mix.
    """
    if not estimates:
        raise ValueError("no estimates to combine")
    for audio, _ in estimates:
        if audio.shape != mix.shape:
            raise ValueError(f"an estimate has the shape {audio.shape}, the mix {mix.shape}")
    if len(estimates) == 1:
        audio, target = estimates[0]
        return (audio, mix - audio) if target == "vocals" else (mix - audio, audio)
    instrumentals = [mix - a if target == "vocals" else a for a, target in estimates]
    instrumental = np.mean(instrumentals, axis=0, dtype=np.float32)
    return mix - instrumental, instrumental


def peak(audio: Audio) -> float:
    """Return the largest absolute sample value (0 for no audio)."""
    return float(np.max(np.abs(audio))) if audio.size else 0.0


def apply_headroom(audio: Audio) -> tuple[Audio, float]:
    """Scale a stem down to -0.1 dBFS when its peak exceeds full scale (ADR-0002).

    Nothing else changes: no limiter, no loudness change.

    Returns:
        The stem and the gain applied (1.0 when the stem was left alone).
    """
    top = peak(audio)
    if top <= 1.0:
        return audio, 1.0
    gain = 10 ** (CEILING_DB / 20) / top
    return (audio * np.float32(gain)).astype(np.float32), gain


def timeout_seconds(
    duration: float,
    device: Device,
    factor_gpu: float,
    factor_cpu: float,
    base: float = TIMEOUT_BASE,
) -> float:
    """Return how long the worker may run: the song length times the factor, plus ``base``."""
    factor = factor_gpu if device == "cuda" else factor_cpu
    return factor * duration + base


@dataclass(frozen=True)
class DeviceChoice:
    """The device a separation runs on.

    Attributes:
        device: ``cuda`` or ``cpu``.
        warning: Something the fan should hear about (the fallback to the CPU), or ``None``.
    """

    device: Device
    warning: str | None = None


def choose_device(requested: DeviceRequest, free_vram: int | None) -> DeviceChoice:
    """Decide where to run.

    ``auto`` takes the GPU when at least 2 GiB are free and falls back to the CPU with a warning;
    ``cuda`` and ``cpu`` force the device.

    Args:
        requested: The setting.
        free_vram: Free GPU memory in bytes, or ``None`` when there is no usable GPU.

    Raises:
        StageError: ``no-gpu`` or ``vram-too-small`` when ``cuda`` is forced and cannot work.
    """
    if requested == "cpu":
        return DeviceChoice("cpu")
    if free_vram is not None and free_vram >= MIN_FREE_VRAM:
        return DeviceChoice("cuda")
    if requested == "cuda":
        if free_vram is None:
            raise StageError("no-gpu", "device cuda was asked for, but no usable GPU was found")
        raise StageError(
            "vram-too-small",
            f"only {free_vram / GIB:.1f} GiB of GPU memory are free; "
            f"{MIN_FREE_VRAM // GIB} GiB are needed (close other programs, or use --device cpu)",
        )
    reason = (
        "no usable GPU was found"
        if free_vram is None
        else f"only {free_vram / GIB:.1f} GiB of GPU memory are free"
    )
    return DeviceChoice(
        "cpu", f"{reason}; separating on the CPU, which is about {CPU_SLOWDOWN}x slower"
    )
