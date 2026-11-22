"""The alignment worker: a child process that runs the acoustic model (ADR-0002, ADR-0007).

``python -m vocatron.engines.alignment.worker <job.json>`` decodes the lead vocals to 16 kHz mono,
runs wav2vec2 over overlapping pieces, stitches the frames and writes them as a NumPy file next to
a result file. It also writes the loudness per frame (ADR-0012) as a second NumPy file: of the
lead vocals, or of lead and backing vocals added if the job says so. If the job asks to hear the
backing (ADR-0014), the model runs a second time over the same pieces on the backing vocals
(trimmed or padded to the lead's length, normalised on their own) and three more files are
written: its frames and the loudness of lead and backing alone. ``--probe``
prints the free GPU memory instead. Exit codes: 0 done, 1 failed, 3 out of memory.
"""

import sys
import time
from pathlib import Path

import numpy as np
import torch
from numpy.typing import NDArray
from transformers import Wav2Vec2ForCTC

from vocatron.core.alignment.chunks import (
    SAMPLE_RATE,
    STRIDE,
    Piece,
    fit_length,
    frame_count,
    frame_loudness,
    plan_pieces,
    stitch,
    sum_waves,
)
from vocatron.core.alignment.job import AcousticJob, AcousticResult
from vocatron.engines.alignment.inference import (
    hear,
    load_model,
    load_vocabulary,
    normalise,
)
from vocatron.engines.audio import decode
from vocatron.engines.gpu_worker import Logger, cap_memory, peak_vram_gib, run_worker


def align(job: AcousticJob, log: Logger) -> AcousticResult:
    """Do the whole job: decode, load the model, run the pieces, write frames and loudness."""
    started = time.monotonic()
    cap_memory(job, log, job.model.precision if job.device == "cuda" else "fp32")
    log(f"decoding {job.audio}")
    raw = decode(job.audio, SAMPLE_RATE, 1)[0]
    voices = raw
    backing = None
    if job.backing is not None:
        log(f"decoding {job.backing} for the loudness and the model")
        backing = decode(job.backing, SAMPLE_RATE, 1)[0]
        if job.sum_backing:
            voices = sum_waves(raw, backing)
    np.save(job.loudness_path, frame_loudness(voices))  # before normalising: levels mean something
    wave = normalise(raw)
    log(f"decoded {len(wave)} samples")
    vocabulary = load_vocabulary(Path(job.model.folder))
    log(f"loading {job.model.name} on {job.device}")
    model = load_model(job.model, job.device)
    pieces = plan_pieces(len(wave), job.piece_seconds, job.overlap_seconds)
    log(f"{len(pieces)} pieces of {job.piece_seconds:.0f} s, overlap {job.overlap_seconds:.0f} s")
    parts = hear(model, wave, pieces, job.device, log, log.progress)
    frames = stitch(parts, frame_count(len(wave)))
    np.save(job.emissions_path, frames)
    if job.hear_backing and backing is not None:
        _hear_backing(job, model, fit_length(backing, len(raw)), raw, pieces, log)
    del model
    if job.device == "cuda":
        torch.cuda.empty_cache()
    return AcousticResult(
        frames=len(frames),
        seconds_per_frame=STRIDE / SAMPLE_RATE,
        vocabulary=vocabulary,
        device=job.device,
        seconds=time.monotonic() - started,
        peak_vram_gib=peak_vram_gib(job.device),
    )


def _hear_backing(
    job: AcousticJob,
    model: Wav2Vec2ForCTC,
    backing: NDArray[np.float32],
    lead: NDArray[np.float32],
    pieces: list[Piece],
    log: Logger,
) -> None:
    """Run the model on the backing vocals and write its frames and both loudness files."""
    emissions, lead_path, backing_path = (
        job.backing_emissions_path,
        job.lead_loudness_path,
        job.backing_loudness_path,
    )
    if emissions is None or lead_path is None or backing_path is None:
        raise ValueError("the job names no files for the backing")
    log("hearing the backing vocals")
    parts = hear(model, normalise(backing), pieces, job.device, log)
    np.save(emissions, stitch(parts, frame_count(len(backing))))
    np.save(lead_path, frame_loudness(lead))
    np.save(backing_path, frame_loudness(backing))


def main(argv: list[str]) -> int:
    """Run the worker; ``argv`` is ``["--probe"]`` or the path of the job file."""
    return run_worker(argv, "alignment", AcousticJob, align)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
