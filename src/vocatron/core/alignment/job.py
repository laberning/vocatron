"""The messages between the alignment stage and its acoustic worker process (ADR-0006).

The job is what the parent hands the acoustic worker process, the result what the worker hands
back; the log-probabilities travel in a NumPy file named by the job.
"""

from pydantic import Field, model_validator

from vocatron.core.separation.rules import Device
from vocatron.core.worker import Frozen, WorkerJob

PIECE_SECONDS = 30.0
"""The length of the pieces the acoustic model sees (ADR-0002)."""
OVERLAP_SECONDS = 2.0
"""How much consecutive pieces share."""


class AcousticSetup(Frozen):
    """The acoustic model as the worker loads it.

    Attributes:
        name: The registry name.
        revision: The pinned revision.
        folder: The model folder (``config.json``, weights, ``vocab.json``).
        precision: ``fp16`` or ``fp32``; the CPU always uses ``fp32``.
    """

    name: str
    revision: str
    folder: str
    precision: str


class AcousticJob(WorkerJob):
    """What the acoustic worker is asked to do.

    Attributes:
        audio: The audio file (the lead vocals).
        backing: The backing vocals, used when ``sum_backing`` or ``hear_backing`` is on.
        sum_backing: With ``backing`` given, add the backing vocals to the lead vocals before
            measuring the loudness (``alignment.voice_source: vocals``).
        hear_backing: Also run the model on the backing vocals (padded or trimmed to the lead's
            length, normalised on their own) and write the three extra files (ADR-0014).
        emissions_path: Where the worker writes the log-probabilities (a ``.npy`` file).
        loudness_path: Where the worker writes the loudness of the vocals per frame in dBFS
            (a ``.npy`` file with ``frames`` entries, ADR-0012): of the lead vocals, or of lead
            and backing added when ``sum_backing`` is on.
        backing_emissions_path: Where the log-probabilities of the backing vocals go.
        lead_loudness_path: Where the loudness of the lead vocals alone goes.
        backing_loudness_path: Where the loudness of the backing vocals alone goes.
        model: The acoustic model.
        piece_seconds: The length of the pieces.
        overlap_seconds: How much consecutive pieces share.
    """

    audio: str
    backing: str | None = None
    sum_backing: bool = True
    hear_backing: bool = False
    emissions_path: str
    loudness_path: str
    backing_emissions_path: str | None = None
    lead_loudness_path: str | None = None
    backing_loudness_path: str | None = None
    model: AcousticSetup
    piece_seconds: float
    overlap_seconds: float

    @model_validator(mode="after")
    def _complete(self) -> AcousticJob:
        """Check that what each switch needs is given."""
        if not self.hear_backing:
            return self
        paths = (self.backing_emissions_path, self.lead_loudness_path, self.backing_loudness_path)
        if self.backing is None or None in paths:
            raise ValueError("hearing the backing needs the backing vocals and three more paths")
        return self


class AcousticResult(Frozen):
    """What the acoustic worker produced.

    Attributes:
        frames: The number of frames written.
        seconds_per_frame: The length of a frame.
        vocabulary: The model's tokens by id.
        device: The device it ran on.
        seconds: How long it took.
        peak_vram_gib: The most GPU memory PyTorch used, or ``None`` on the CPU.
        warnings: What the fan should hear, for example the fallback to the CPU.
    """

    frames: int
    seconds_per_frame: float
    vocabulary: list[str]
    device: Device
    seconds: float
    peak_vram_gib: float | None = None
    warnings: list[str] = Field(default_factory=list)
