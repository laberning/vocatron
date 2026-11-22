"""A stand-in for the separation and alignment worker processes, to test the parent without a model.

Usage: ``fake_worker.py <mode> <free_vram> <job.json | --probe>``. ``free_vram`` is a number of
bytes or ``none``. Modes: ``ok``, ``fail`` (exit 1 after logging), ``oom`` (exit 3), ``killed``
(dies of SIGKILL), ``hang`` (sleeps), ``noresult`` (exit 0 without a result), ``garbage`` (exit 0
with an invalid result), ``badprobe`` (prints no JSON), ``badframes`` (an alignment result whose
frame file has the wrong shape), ``badloudness`` (its loudness file has the wrong
shape), ``noloudness`` (it leaves no loudness file), ``badbacking`` (the frames of the
backing have the wrong shape), ``nobacking`` (it leaves no file of the backing's frames). A job
with an ``emissions_path`` is an alignment job. Every mode that gets as far as working prints a
line of noise and progress lines on its standard output first, like a real worker.
"""

import json
import os
import signal
import sys
import time
from pathlib import Path

import numpy as np

from vocatron.core.separation.rules import EXIT_FAILED, EXIT_OUT_OF_MEMORY

HANG_SECONDS = 30


def write_result(job: dict[str, object], result: Path, mode: str) -> None:
    """Write the valid result of a separation or (with ``emissions_path``) an alignment job."""
    if "emissions_path" in job:
        frames = 7 if mode != "badframes" else 6
        np.save(str(job["emissions_path"]), np.zeros((frames, 4), dtype=np.float32))
        if mode != "noloudness":
            loud = 7 if mode != "badloudness" else 8
            np.save(str(job["loudness_path"]), np.full(loud, -30.0, dtype=np.float32))
        if job.get("hear_backing"):
            rows = 7 if mode != "badbacking" else 5
            if mode != "nobacking":
                np.save(str(job["backing_emissions_path"]), np.zeros((rows, 4), dtype=np.float32))
            np.save(str(job["lead_loudness_path"]), np.full(7, -30.0, dtype=np.float32))
            np.save(str(job["backing_loudness_path"]), np.full(7, -40.0, dtype=np.float32))
        answer: dict[str, object] = {
            "frames": 7,
            "seconds_per_frame": 0.02,
            "vocabulary": ["<pad>", "|", "a", "b"],
            "device": job["device"],
            "seconds": 1.5,
        }
    else:
        answer = {"samples": 88200, "gains": {}, "device": job["device"], "seconds": 1.5}
    result.write_text(json.dumps(answer), encoding="utf-8")


def main(mode: str, free: str, target: str) -> int:
    if target == "--probe":
        if "FAKE_PROBE_LOG" in os.environ:
            with Path(os.environ["FAKE_PROBE_LOG"]).open("a", encoding="utf-8") as probes:
                probes.write(f"probe own_session={os.getsid(0) == os.getpid()}\n")
        print(
            "not json"
            if mode == "badprobe"
            else json.dumps({"free_vram": None if free == "none" else int(free)})
        )
        return 0
    job = json.loads(Path(target).read_text(encoding="utf-8"))
    with Path(job["log_path"]).open("a", encoding="utf-8") as log:
        log.write(
            f"fake worker: {mode} on {job['device']}, keep_backing={job.get('keep_backing')}, "
            f"own_session={os.getsid(0) == os.getpid()}\n"
        )
    result = Path(job["result_path"])
    print("a line the libraries print for their own reasons", flush=True)
    for done in (1, 2, 4):
        print(f"progress {done} 4", flush=True)  # what a real worker tells its parent
    if mode == "fail":
        return EXIT_FAILED
    if mode == "oom":
        return EXIT_OUT_OF_MEMORY
    if mode == "killed":
        os.kill(os.getpid(), signal.SIGKILL)
    if mode == "hang":
        time.sleep(HANG_SECONDS)
    if mode == "garbage":
        result.write_text("{not json", encoding="utf-8")
    elif mode != "noresult":
        write_result(job, result, mode)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
