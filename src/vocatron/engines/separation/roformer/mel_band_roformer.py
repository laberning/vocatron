# Mel-Band Roformer model, trimmed to inference for Vocatron.
#
# Copied from ZFTurbo's Music-Source-Separation-Training, file
# models/bs_roformer/mel_band_roformer.py at
# commit 6fdad13686bb7e84d029ec66f9dbe76e65c93ebf
# (https://github.com/ZFTurbo/Music-Source-Separation-Training), which is itself based on Phil
# Wang's BS-RoFormer (https://github.com/lucidrains/BS-RoFormer). Both are MIT-licensed:
#
#   Copyright (c) 2024 Roman Solovyev (ZFTurbo)
#   Copyright (c) 2023 Phil Wang
#
#   Permission is hereby granted, free of charge, to any person obtaining a copy of this software
#   and associated documentation files (the "Software"), to deal in the Software without
#   restriction, including without limitation the rights to use, copy, modify, merge, publish,
#   distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
#   Software is furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in all copies or
#   substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
#   INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
#   PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
#   FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
#   OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#   DEALINGS IN THE SOFTWARE.
#
# Changes by Vocatron: only the inference path is kept (no dropout, no loss, no checkpointing, no
# linear attention, no PoPE, no beartype); the network takes its parsed configuration; the building
# blocks shared with the BS-Roformer (including the axial transformers and both STFTs, in
# AxialRoformer) are imported from bs_roformer.py; the mel filter bank comes from
# vocatron.core.mel instead of librosa; the output always has the stem dimension; the inverse STFT
# is told the input length. Type hints and docstrings added. The layer structure and the names of
# all weights are unchanged, so the checkpoints load strictly.
"""The Mel-Band Roformer network: overlapping mel bands, axial transformers, mask estimators."""

from typing import override

import torch
from einops import rearrange, repeat
from torch import Tensor
from torch.nn import ModuleList

from vocatron.core.mel import mel_filter_bank
from vocatron.engines.separation.roformer.bs_roformer import AxialRoformer, BandSplit, MaskEstimator
from vocatron.engines.separation.roformer.config import MelModelConfig


class MelBandRoformer(AxialRoformer):
    """Mel-band Roformer: audio in, the separated stems out (inference only)."""

    def __init__(self, config: MelModelConfig) -> None:
        """Create the network that the ``model`` section of a configuration describes.

        Raises:
            ValueError: If a frequency lies in no mel band.
        """
        super().__init__(config, norm_output=True)
        num_bands = config.num_bands
        freqs = config.stft_n_fft // 2 + 1
        bank = torch.from_numpy(mel_filter_bank(config.sample_rate, config.stft_n_fft, num_bands))
        bank[0][0] = 1.0  # the first bin is not covered otherwise, as upstream
        bank[-1, -1] = 1.0  # tiny or zero depending on the platform, as upstream
        freqs_per_band = bank > 0
        if not bool(freqs_per_band.any(dim=0).all()):
            raise ValueError("every frequency must lie in at least one mel band")
        freq_indices = repeat(torch.arange(freqs), "f -> b f", b=num_bands)[freqs_per_band]
        if config.stereo:
            freq_indices = repeat(freq_indices, "f -> f s", s=2) * 2 + torch.arange(2)
            freq_indices = rearrange(freq_indices, "f s -> (f s)")
        num_freqs_per_band = freqs_per_band.sum(dim=1)
        # derived from the config, not stored in the checkpoints (upstream: persistent=False)
        self.register_buffer("freq_indices", freq_indices, persistent=False)
        self.register_buffer("num_bands_per_freq", freqs_per_band.sum(dim=0), persistent=False)
        band_widths = tuple(2 * f * self.audio_channels for f in num_freqs_per_band.tolist())
        self.band_split = BandSplit(dim=config.dim, dim_inputs=band_widths)
        self.mask_estimators = ModuleList(
            [
                MaskEstimator(
                    config.dim,
                    band_widths,
                    config.mask_estimator_depth,
                    config.mlp_expansion_factor,
                )
                for _ in range(config.num_stems)
            ]
        )

    @override
    def forward(self, raw_audio: Tensor) -> Tensor:
        """Separate a (batch, channels, samples) tensor.

        Returns:
            The stems, shaped (batch, stems, channels, samples); also for a single stem.
        """
        batch, channels = raw_audio.shape[0], raw_audio.shape[1]
        spectrum, window = self._spectrum(raw_audio)
        picked = spectrum[
            torch.arange(batch, device=raw_audio.device)[..., None], self.freq_indices
        ]
        x = self.band_split(rearrange(picked, "b f t c -> b t (f c)"))
        x = self._transform(x)
        masks = torch.stack([estimator(x) for estimator in self.mask_estimators], dim=1)
        stems = masks.shape[1]
        masks = torch.view_as_complex(rearrange(masks, "b n t (f c) -> b n f t c", c=2))
        complex_spectrum = torch.view_as_complex(rearrange(spectrum, "b f t c -> b 1 f t c"))
        masks = masks.type(complex_spectrum.dtype)
        scatter = repeat(
            self.freq_indices, "f -> b n f t", b=batch, n=stems, t=complex_spectrum.shape[-1]
        )
        summed = torch.zeros_like(repeat(complex_spectrum, "b 1 ... -> b n ...", n=stems))
        summed = summed.scatter_add_(2, scatter, masks)
        denominator = repeat(self.num_bands_per_freq, "f -> (f r) 1", r=channels)
        masked = complex_spectrum * (summed / denominator.clamp(min=1e-8))
        return self._waveform(masked, window, raw_audio.shape[-1])
