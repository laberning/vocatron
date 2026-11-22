"""A tiny BS-Roformer with random weights, saved like a real model: checkpoint plus YAML."""

from pathlib import Path
from typing import Literal

import torch

from vocatron.core.separation.job import ModelSetup
from vocatron.engines.separation.inference import build_model
from vocatron.engines.separation.roformer.config import parse_config

CHUNK = 2048

TINY_CONFIG = """
audio:
  chunk_size: 2048
  sample_rate: 44100
model:
  dim: 8
  depth: 1
  stereo: true
  num_stems: 1
  time_transformer_depth: 1
  freq_transformer_depth: 1
  linear_transformer_depth: 0
  freqs_per_bands: !!python/tuple
    - 11
    - 11
    - 11
  dim_head: 4
  heads: 2
  attn_dropout: 0.1
  ff_dropout: 0.1
  flash_attn: true
  dim_freqs_in: 33
  stft_n_fft: 64
  stft_hop_length: 16
  stft_win_length: 64
  stft_normalized: false
  mask_estimator_depth: 2
  multi_stft_resolution_loss_weight: 1.0
  multi_stft_resolutions_window_sizes: !!python/tuple
  - 64
  - 32
  multi_stft_hop_size: 8
  multi_stft_normalized: false
  mlp_expansion_factor: 2
  use_torch_checkpoint: true
  skip_connection: false
"""


TINY_MEL_CONFIG = """
audio:
  chunk_size: 2048
model:
  dim: 8
  depth: 1
  stereo: true
  num_stems: 2
  time_transformer_depth: 1
  freq_transformer_depth: 1
  num_bands: 4
  dim_head: 4
  heads: 2
  attn_dropout: 0
  ff_dropout: 0
  flash_attn: true
  dim_freqs_in: 33
  sample_rate: 44100
  stft_n_fft: 64
  stft_hop_length: 16
  stft_win_length: 64
  stft_normalized: true
  mask_estimator_depth: 2
  multi_stft_resolution_loss_weight: 1.0
  multi_stft_resolutions_window_sizes: !!python/tuple
  - 64
  multi_stft_hop_size: 8
  multi_stft_normalized: false
  use_torch_checkpoint: true
"""


def write_tiny_model(
    folder: Path,
    name: str,
    seed: int,
    *,
    mel: bool = False,
    target: Literal["vocals", "instrumental"] = "vocals",
) -> ModelSetup:
    """Write a randomly initialised tiny model into ``folder`` and describe how to load it.

    ``mel`` makes a Mel-Band Roformer with two stems instead of a BS-Roformer.
    """
    folder.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(seed)
    text = TINY_MEL_CONFIG if mel else TINY_CONFIG
    model = build_model(parse_config(text))
    checkpoint, config = folder / f"{name}.ckpt", folder / f"{name}.yaml"
    torch.save(model.state_dict(), checkpoint)
    config.write_text(text, encoding="utf-8")
    return ModelSetup(
        name=name,
        revision="test",
        checkpoint=str(checkpoint),
        config=str(config),
        chunk_size=CHUNK,
        num_overlap=2,
        precision="fp16",
        target=target,
    )
