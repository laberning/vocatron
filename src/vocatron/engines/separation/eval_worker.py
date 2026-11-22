"""The evaluation worker: one model over many files, for ``tools/separation_eval.py``.

``python -m vocatron.engines.separation.eval_worker <job.json>`` loads the model once, separates
every file of the job whose output is not there yet, writes the estimated instrumental as float
WAV (so that nothing is clipped or rounded) and appends one JSON line per file to the timings
file, synced to disk. Exit codes and the log are those of every GPU worker; a crash leaves what
was finished, and the next job skips it.
"""

import os
import sys
import time
from pathlib import Path

import soundfile as sf
import torch

from vocatron.core.separation.rules import SAMPLE_RATE, Audio, combine_estimates
from vocatron.engines.audio import decode
from vocatron.engines.gpu_worker import Logger, cap_memory, peak_vram_gib, run_worker
from vocatron.engines.separation.inference import Network, load_model, separate_target
from vocatron.lab.separation.evaluation import EvalJob, EvalPair, EvalResult, Timing


def write_wav(path: Path, audio: Audio) -> None:
    """Write (channels, samples) audio as float WAV; the file appears complete or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    sf.write(partial, audio.T, SAMPLE_RATE, format="WAV", subtype="FLOAT")
    partial.replace(path)


def append_line(path: Path, text: str) -> None:
    """Append a line to ``path`` and sync it to disk."""
    with path.open("a", encoding="utf-8") as file:
        file.write(text + "\n")
        file.flush()
        os.fsync(file.fileno())


def separate_pair(job: EvalJob, model: Network, pair: EvalPair, log: Logger) -> Timing:
    """Separate one file and write its instrumental; return what it cost."""
    log(f"decoding {pair.audio}")
    mix = decode(pair.audio)
    if job.device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    started = time.monotonic()
    estimate = separate_target(model, mix, job.model, job.device, log)
    seconds = time.monotonic() - started
    _, instrumental = combine_estimates(mix, [(estimate, job.model.target)])
    write_wav(Path(pair.output), instrumental)
    return Timing(
        name=pair.name,
        audio_seconds=mix.shape[1] / SAMPLE_RATE,
        seconds=seconds,
        peak_vram_gib=peak_vram_gib(job.device),
    )


def separate(job: EvalJob, log: Logger) -> EvalResult:
    """Do the whole job: load the model, separate each file that is not done, log the timings."""
    started = time.monotonic()
    cap_memory(job, log)
    todo = [pair for pair in job.pairs if not Path(pair.output).is_file()]
    log(f"{len(todo)} of {len(job.pairs)} files to separate with {job.model.name}")
    if not todo:
        return EvalResult(seconds=0.0, peak_vram_gib=None, done=0)
    log(f"loading {job.model.name} on {job.device}")
    model = load_model(job.model, job.device)
    for number, pair in enumerate(todo, start=1):
        timing = separate_pair(job, model, pair, log)
        append_line(Path(job.timings_path), timing.model_dump_json())
        log(f"{pair.name}: {timing.seconds:.1f} s for {timing.audio_seconds:.1f} s of audio")
        log.progress(number, len(todo))
    return EvalResult(
        seconds=time.monotonic() - started, peak_vram_gib=peak_vram_gib(job.device), done=len(todo)
    )


def main(argv: list[str]) -> int:
    """Run the worker; ``argv`` is ``["--probe"]`` or the path of the job file."""
    return run_worker(argv, "evaluation", EvalJob, separate)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
