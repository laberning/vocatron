"""The separation worker: a child process that does the GPU work (ADR-0002, ADR-0007).

``python -m vocatron.engines.separation.worker <job.json>`` separates one song and writes the
stems and a result file. ``--probe`` prints the free GPU memory instead. Exit codes: 0 done,
1 failed, 3 out of memory. Every step is logged to the song log and synced to disk, so a crash
leaves evidence.
"""

import sys
import time
from pathlib import Path

import numpy as np
import torch

from vocatron.core.separation.job import ModelSetup, SeparationJob, SeparationResult
from vocatron.core.separation.rules import Audio, Device, combine_estimates, normalise_peak
from vocatron.engines.audio import decode
from vocatron.engines.gpu_worker import Logger, cap_memory, peak_vram_gib, run_worker
from vocatron.engines.separation.inference import load_model, separate_target
from vocatron.engines.separation.output import write_stems


def run_model(  # every argument is a different thing the model needs
    setup: ModelSetup, audio: Audio, device: Device, log: Logger, progress: tuple[int, int]
) -> Audio:
    """Load a model, separate ``audio`` with it, and release it.

    ``progress`` is ``(number, models)``: this is model ``number`` (from 0) of ``models`` in the
    job, which the progress the parent sees is spread over.
    """
    number, models = progress
    log(f"loading {setup.name} on {device}")
    model = load_model(setup, device)
    started = time.monotonic()

    def report(done: int, total: int) -> None:
        log.progress(number * total + done, models * total)

    target = separate_target(model, audio, setup, device, log, report)
    log(f"{setup.name} done in {time.monotonic() - started:.1f} s")
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    return target


def separate(job: SeparationJob, log: Logger) -> SeparationResult:
    """Do the whole job: decode, vocals, instrumental, lead and backing, write the stems.

    Several vocals models are averaged (``combine_estimates``). The karaoke model gets the vocals
    or, with ``karaoke_input`` ``mix``, the full mix; either way scaled to the peak it was
    trained with and scaled back.
    """
    started = time.monotonic()
    cap_memory(job, log)
    log(f"decoding {job.audio}")
    mix = decode(job.audio)
    log(f"decoded {mix.shape[1]} samples")
    models = len(job.vocals_models) + 1
    estimates = [
        (run_model(setup, mix, job.device, log, (number, models)), setup.target)
        for number, setup in enumerate(job.vocals_models)
    ]
    vocals, instrumental = combine_estimates(mix, estimates)
    scaled, factor = normalise_peak(vocals if job.karaoke_input == "vocals" else mix)
    lead_and_backing = run_model(job.karaoke_model, scaled, job.device, log, (models - 1, models))
    lead = np.multiply(lead_and_backing, np.float32(1 / factor), dtype=np.float32)
    backing = vocals - lead
    log("writing stems")
    gains = write_stems(
        Path(job.out_folder), lead, backing, instrumental, keep_backing=job.keep_backing
    )
    return SeparationResult(
        samples=mix.shape[1],
        gains=gains,
        device=job.device,
        seconds=time.monotonic() - started,
        peak_vram_gib=peak_vram_gib(job.device),
    )


def main(argv: list[str]) -> int:
    """Run the worker; ``argv`` is ``["--probe"]`` or the path of the job file."""
    return run_worker(argv, "separation", SeparationJob, separate)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
