"""Running a Roformer model over a whole song (needs PyTorch; imported by the worker only)."""

from collections.abc import Callable
from pathlib import Path

import numpy as np
import torch

from vocatron.core.separation.job import ModelSetup
from vocatron.core.separation.rules import Audio, Device, overlap_add, plan_chunks
from vocatron.engines.separation.roformer.bs_roformer import BSRoformer
from vocatron.engines.separation.roformer.config import MelModelConfig, ModelConfig, parse_config
from vocatron.engines.separation.roformer.mel_band_roformer import MelBandRoformer

Log = Callable[[str], None]
FP16 = "fp16"
LOG_EVERY = 10  # chunks


type Network = BSRoformer | MelBandRoformer


def build_model(config: ModelConfig | MelModelConfig) -> Network:
    """Create the network described by ``config``, with random weights."""
    if isinstance(config, MelModelConfig):
        return MelBandRoformer(config)
    return BSRoformer(config)


def load_model(setup: ModelSetup, device: Device) -> Network:
    """Load a model with its weights, strictly: a missing or extra weight is an error.

    Raises:
        ValueError: If the configuration is invalid.
        RuntimeError: If the weights do not fit the network.
    """
    config = parse_config(Path(setup.config).read_text(encoding="utf-8"))
    model = build_model(config)
    weights = torch.load(setup.checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(weights.get("state_dict", weights), strict=True)
    return model.eval().to(device)


def separate_target(  # every argument is a different thing the model needs
    model: Network,
    audio: Audio,
    setup: ModelSetup,
    device: Device,
    log: Log,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
) -> Audio:
    """Return the model's first stem of ``audio`` (``setup.target`` says which), shaped like it.

    Uses half precision on the GPU when the model's pin says so, full precision on the CPU.
    ``on_progress`` hears how many chunks are done of how many, after each chunk.
    """
    plan = plan_chunks(audio.shape[1], setup.chunk_size, setup.num_overlap)
    half = device == "cuda" and setup.precision == FP16

    def process(chunk: Audio) -> Audio:
        piece = torch.from_numpy(np.ascontiguousarray(chunk)).unsqueeze(0).to(device)
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16, enabled=half):
            estimate = model(piece)
        return estimate[0, 0].float().cpu().numpy()

    def progress(done: int, total: int) -> None:
        on_progress(done, total)
        if done % LOG_EVERY == 1 or done == total:
            peak = (
                f", peak {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB"
                if device == "cuda"
                else ""
            )
            log(f"{setup.name}: chunk {done}/{total}{peak}")

    return overlap_add(audio, plan, process, progress)
