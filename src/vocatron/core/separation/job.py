"""The messages between the separation stage and its worker process (ADR-0006).

The job is what the parent hands the worker process, the result what the worker hands back.
"""

from typing import Literal

from pydantic import Field

from vocatron.core.separation.rules import Device
from vocatron.core.worker import Frozen, WorkerJob


class ModelSetup(Frozen):
    """One separation model as the worker loads it.

    Attributes:
        name: The registry name.
        revision: The pinned revision.
        checkpoint: The weights file.
        config: The model's configuration file.
        chunk_size: Samples per chunk (part of the model pin).
        num_overlap: How many chunks cover each sample (part of the model pin).
        precision: ``fp16`` or ``fp32``; the CPU always uses ``fp32`` (part of the model pin).
        target: What the model's first output is: ``vocals`` (the instrumental is the mix minus
            it) or ``instrumental`` (the vocals are the mix minus it); part of the model pin.
    """

    name: str
    revision: str
    checkpoint: str
    config: str
    chunk_size: int
    num_overlap: int
    precision: str
    target: Literal["vocals", "instrumental"] = "vocals"


class SeparationPlan(Frozen):
    """Which models separate a song and how their outputs are combined.

    The stage hands it to the separator, the separator to its worker (inside the job).

    Attributes:
        keep_backing: Whether the karaoke mix keeps the backing vocals.
        vocals_models: The vocals and instrumental model, or two whose instrumentals are
            averaged.
        karaoke_model: The lead and backing vocals model.
        karaoke_input: What the karaoke model gets: the ``vocals`` stem or the full ``mix``.
    """

    keep_backing: bool
    vocals_models: tuple[ModelSetup, ...]
    karaoke_model: ModelSetup
    karaoke_input: Literal["vocals", "mix"] = "vocals"


class SeparationJob(SeparationPlan, WorkerJob):
    """What the worker process is asked to do: the plan for one song.

    Attributes:
        audio: The song's audio file.
        out_folder: The work folder; stems go to ``stems/`` below it.
    """

    audio: str
    out_folder: str


class StemGains(Frozen):
    """The gain applied to each stem so that none clips (1.0 means untouched).

    Attributes:
        lead: Gain of the lead vocals.
        backing: Gain of the backing vocals.
        instrumental: Gain of the instrumental.
        karaoke: Gain of the karaoke mix, applied after mixing.
    """

    lead: float = 1.0
    backing: float = 1.0
    instrumental: float = 1.0
    karaoke: float = 1.0


class SeparationResult(Frozen):
    """What a separation produced.

    Attributes:
        samples: The length of every stem in samples (44.1 kHz).
        gains: The headroom gains.
        device: The device it ran on.
        seconds: How long the separation took.
        peak_vram_gib: The most GPU memory PyTorch used, or ``None`` on the CPU.
        warnings: What the fan should hear, for example the fallback to the CPU.
    """

    samples: int
    gains: StemGains
    device: Device
    seconds: float
    peak_vram_gib: float | None = None
    warnings: list[str] = Field(default_factory=list)
