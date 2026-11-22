# BS-Roformer model, trimmed to inference for Vocatron.
#
# Copied from ZFTurbo's Music-Source-Separation-Training, file models/bs_roformer/bs_roformer.py at
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
# Changes by Vocatron: only the inference path is kept (no dropout, no loss, no
# checkpointing, no linear attention, no PoPE, no beartype); the network takes its parsed
# configuration; the parts the Mel-Band Roformer shares (axial transformers, STFT in, inverse
# STFT out) live in AxialRoformer; type hints and docstrings added.
# The layer structure and the names of all weights are unchanged, so the checkpoints load strictly.
"""The BS-Roformer network: band split, axial time and frequency transformers, mask estimators."""

from typing import cast, override

import torch
import torch.nn.functional as F
from einops import pack, rearrange, unpack
from rotary_embedding_torch import RotaryEmbedding
from torch import Tensor, nn
from torch.nn import Module, ModuleList

from vocatron.engines.separation.roformer.attend import Attend
from vocatron.engines.separation.roformer.config import ModelConfig, RoformerConfig


class RMSNorm(Module):
    """Root-mean-square normalisation with a learned gain."""

    def __init__(self, dim: int) -> None:
        """Create the norm for vectors of size ``dim``."""
        super().__init__()
        self.scale = dim**0.5
        self.gamma = nn.Parameter(torch.ones(dim))

    @override
    def forward(self, x: Tensor) -> Tensor:
        """Normalise the last dimension."""
        return F.normalize(x, dim=-1) * self.scale * self.gamma


class FeedForward(Module):
    """Two linear layers with GELU between them."""

    def __init__(self, dim: int, mult: int = 4) -> None:
        """Create the block; ``Identity`` stands where upstream has dropout (weights keep names)."""
        super().__init__()
        dim_inner = int(dim * mult)
        self.net = nn.Sequential(
            RMSNorm(dim),
            nn.Linear(dim, dim_inner),
            nn.GELU(),
            nn.Identity(),
            nn.Linear(dim_inner, dim),
            nn.Identity(),
        )

    @override
    def forward(self, x: Tensor) -> Tensor:
        """Apply the block."""
        return self.net(x)


class Attention(Module):
    """Gated multi-head self-attention with rotary position embedding."""

    def __init__(self, dim: int, heads: int, dim_head: int, rotary_embed: RotaryEmbedding) -> None:
        """Create the attention of ``heads`` heads of size ``dim_head``."""
        super().__init__()
        self.heads = heads
        dim_inner = heads * dim_head
        self.rotary_embed = rotary_embed
        self.attend = Attend()
        self.norm = RMSNorm(dim)
        self.to_qkv = nn.Linear(dim, dim_inner * 3, bias=False)
        self.to_gates = nn.Linear(dim, heads)
        self.to_out = nn.Sequential(nn.Linear(dim_inner, dim, bias=False), nn.Identity())

    @override
    def forward(self, x: Tensor) -> Tensor:
        """Apply the attention to a (batch, length, dim) tensor."""
        x = self.norm(x)
        q, k, v = rearrange(self.to_qkv(x), "b n (qkv h d) -> qkv b h n d", qkv=3, h=self.heads)
        q = self.rotary_embed.rotate_queries_or_keys(q)
        k = self.rotary_embed.rotate_queries_or_keys(k)
        out = self.attend(q, k, v)
        gates = self.to_gates(x)
        out = out * rearrange(gates, "b n h -> b h n 1").sigmoid()
        out = rearrange(out, "b h n d -> b n (h d)")
        return self.to_out(out)


class Transformer(Module):
    """A stack of attention and feed-forward blocks with residual connections."""

    def __init__(
        self,
        *,
        dim: int,
        depth: int,
        dim_head: int,
        heads: int,
        rotary_embed: RotaryEmbedding,
        norm_output: bool = False,
    ) -> None:
        """Create ``depth`` blocks, with a norm after the last one if ``norm_output``.

        The BS-Roformer has no output norm in its transformers (``Identity``); the Mel-Band
        Roformer has one.
        """
        super().__init__()
        self.layers = ModuleList(
            [
                ModuleList(
                    [Attention(dim, heads, dim_head, rotary_embed), FeedForward(dim, mult=4)]
                )
                for _ in range(depth)
            ]
        )
        self.norm: Module = RMSNorm(dim) if norm_output else nn.Identity()

    @override
    def forward(self, x: Tensor) -> Tensor:
        """Apply all blocks."""
        for block in self.layers:
            attn, ff = cast("ModuleList", block)  # each block is the pair (attention, feed-forward)
            x = attn(x) + x
            x = ff(x) + x
        return self.norm(x)


class BandSplit(Module):
    """Projects each frequency band of the spectrogram to one feature vector."""

    def __init__(self, dim: int, dim_inputs: tuple[int, ...]) -> None:
        """Create one RMS-normed projection per band; ``dim_inputs`` are the band widths."""
        super().__init__()
        self.dim_inputs = dim_inputs
        self.to_features = ModuleList(
            [nn.Sequential(RMSNorm(dim_in), nn.Linear(dim_in, dim)) for dim_in in dim_inputs]
        )

    @override
    def forward(self, x: Tensor) -> Tensor:
        """Split the last dimension into bands and project each; bands become dimension -2."""
        outs = [
            net(part)
            for part, net in zip(x.split(self.dim_inputs, dim=-1), self.to_features, strict=True)
        ]
        return torch.stack(outs, dim=-2)


def mlp(dim_in: int, dim_out: int, dim_hidden: int, hidden_layers: int) -> nn.Sequential:
    """Build the mask network: ``hidden_layers`` hidden layers, tanh between all linear layers."""
    dims = (dim_in, *((dim_hidden,) * hidden_layers), dim_out)
    layers: list[Module] = []
    pairs = list(zip(dims[:-1], dims[1:], strict=True))
    for index, (layer_in, layer_out) in enumerate(pairs):
        layers.append(nn.Linear(layer_in, layer_out))
        if index < len(pairs) - 1:
            layers.append(nn.Tanh())
    return nn.Sequential(*layers)


class MaskEstimator(Module):
    """Turns the band features back into a complex mask for every band."""

    def __init__(
        self, dim: int, dim_inputs: tuple[int, ...], hidden_layers: int, expansion: int
    ) -> None:
        """Create one gated mask network per band, each with ``hidden_layers`` hidden layers."""
        super().__init__()
        self.dim_inputs = dim_inputs
        self.to_freqs = ModuleList(
            [
                nn.Sequential(mlp(dim, dim_in * 2, dim * expansion, hidden_layers), nn.GLU(dim=-1))
                for dim_in in dim_inputs
            ]
        )

    @override
    def forward(self, x: Tensor) -> Tensor:
        """Return the mask, bands concatenated on the last dimension."""
        outs = [net(band) for band, net in zip(x.unbind(dim=-2), self.to_freqs, strict=True)]
        return torch.cat(outs, dim=-1)


class AxialRoformer(Module):
    """What both Roformers share: axial transformers, the STFT in and the inverse STFT out.

    Subclasses add the band split and the mask estimators after calling this constructor, so the
    modules are created, and the weights named, in the order of the upstream networks.
    """

    def __init__(self, config: RoformerConfig, *, norm_output: bool) -> None:
        """Create the ``depth`` pairs of time and frequency transformers of ``config``.

        ``norm_output`` gives every transformer an output norm (the Mel-Band Roformer has one,
        the BS-Roformer has ``Identity``).
        """
        super().__init__()
        self.audio_channels = 2 if config.stereo else 1
        self.skip_connection = config.skip_connection
        time_rotary = RotaryEmbedding(dim=config.dim_head)
        freq_rotary = RotaryEmbedding(dim=config.dim_head)
        shared = {
            "dim": config.dim,
            "heads": config.heads,
            "dim_head": config.dim_head,
            "norm_output": norm_output,
        }
        self.layers = ModuleList(
            [
                ModuleList(
                    [
                        Transformer(
                            depth=config.time_transformer_depth, rotary_embed=time_rotary, **shared
                        ),
                        Transformer(
                            depth=config.freq_transformer_depth, rotary_embed=freq_rotary, **shared
                        ),
                    ]
                )
                for _ in range(config.depth)
            ]
        )
        self.stft_kwargs = {
            "n_fft": config.stft_n_fft,
            "hop_length": config.stft_hop_length,
            "win_length": config.stft_win_length,
            "normalized": config.stft_normalized,
        }
        self.stft_win_length = config.stft_win_length

    def _transform(self, x: Tensor) -> Tensor:
        """Run the axial transformers: time attention, then frequency attention, per layer."""
        store: list[Tensor] = []
        for index, block in enumerate(self.layers):
            time_transformer, freq_transformer = cast("ModuleList", block)  # (time, frequency)
            if self.skip_connection:
                for earlier in store[:index]:
                    x = x + earlier
            x = rearrange(x, "b t f d -> b f t d")
            x, ps = pack([x], "* t d")
            x = time_transformer(x)
            (x,) = unpack(x, ps, "* t d")
            x = rearrange(x, "b f t d -> b t f d")
            x, ps = pack([x], "* f d")
            x = freq_transformer(x)
            (x,) = unpack(x, ps, "* f d")
            store.append(x)
        return x

    def _spectrum(self, raw_audio: Tensor) -> tuple[Tensor, Tensor]:
        """Return the STFT of a (batch, channels, samples) tensor and the window it used.

        The spectrum is real, shaped (batch, frequencies × channels, frames, 2), the channels of a
        frequency next to each other.

        Raises:
            ValueError: If the audio has the wrong number of channels.
        """
        channels = raw_audio.shape[1]
        if channels != self.audio_channels:
            raise ValueError(f"the model takes {self.audio_channels} channels, got {channels}")
        packed, packed_shape = pack([raw_audio], "* t")
        window = torch.hann_window(self.stft_win_length, device=raw_audio.device)
        spectrum = torch.stft(packed, **self.stft_kwargs, window=window, return_complex=True)
        spectrum = unpack(torch.view_as_real(spectrum), packed_shape, "* f t c")[0]
        return rearrange(spectrum, "b s f t c -> b (f s) t c"), window

    def _waveform(self, masked: Tensor, window: Tensor, length: int) -> Tensor:
        """Turn masked complex spectra (batch, stems, frequencies × channels, frames) into audio.

        Returns:
            The stems, shaped (batch, stems, channels, ``length``).
        """
        batch, stems = masked.shape[0], masked.shape[1]
        masked = rearrange(masked, "b n (f s) t -> (b n s) f t", s=self.audio_channels)
        masked[:, 0] = 0.0  # drop the DC component, as upstream does
        audio = torch.istft(
            masked, **self.stft_kwargs, window=window, return_complex=False, length=length
        )
        return rearrange(audio, "(b n s) t -> b n s t", b=batch, s=self.audio_channels, n=stems)


class BSRoformer(AxialRoformer):
    """Band-split Roformer: audio in, the separated stems out (inference only)."""

    def __init__(self, config: ModelConfig) -> None:
        """Create the network that the ``model`` section of a configuration describes.

        Raises:
            ValueError: If the bands do not add up to the frequencies of the STFT.
        """
        super().__init__(config, norm_output=False)
        self.final_norm = RMSNorm(config.dim)
        freqs = config.stft_n_fft // 2 + 1
        freqs_per_bands = config.freqs_per_bands
        if len(freqs_per_bands) <= 1 or sum(freqs_per_bands) != freqs:
            raise ValueError(
                f"the bands must add up to {freqs} frequencies, got {sum(freqs_per_bands)}"
            )
        band_widths = tuple(2 * f * self.audio_channels for f in freqs_per_bands)
        self.band_split = BandSplit(dim=config.dim, dim_inputs=band_widths)
        self.mask_estimators = ModuleList(
            [
                MaskEstimator(
                    config.dim,
                    band_widths,
                    config.mask_estimator_depth - 1,
                    config.mlp_expansion_factor,
                )
                for _ in range(config.num_stems)
            ]
        )

    @override
    def forward(self, raw_audio: Tensor) -> Tensor:
        """Separate a (batch, channels, samples) tensor.

        Returns:
            The stems, shaped (batch, stems, channels, samples).
        """
        spectrum, window = self._spectrum(raw_audio)
        x = self.band_split(rearrange(spectrum, "b f t c -> b t (f c)"))
        x = self.final_norm(self._transform(x))
        mask = torch.stack([estimator(x) for estimator in self.mask_estimators], dim=1)
        mask = rearrange(mask, "b n t (f c) -> b n f t c", c=2)
        masked = torch.view_as_complex(rearrange(spectrum, "b f t c -> b 1 f t c")) * (
            torch.view_as_complex(mask)
        )
        return self._waveform(masked, window, raw_audio.shape[-1])
