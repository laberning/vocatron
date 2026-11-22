# BS-Roformer attention, trimmed to inference for Vocatron.
#
# Copied from ZFTurbo's Music-Source-Separation-Training, file models/bs_roformer/attend.py at
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
# Changes by Vocatron: only the inference path is kept (no dropout, no training branches, no
# printing); type hints and docstrings added. The attention is unchanged.
"""Scaled dot-product attention with the fastest backend the GPU offers."""

from typing import override

import torch.nn.functional as F
from torch import Tensor, nn
from torch.nn.attention import SDPBackend, sdpa_kernel

INFERENCE_SDPA_BACKENDS = [
    SDPBackend.CUDNN_ATTENTION,
    SDPBackend.FLASH_ATTENTION,
    SDPBackend.EFFICIENT_ATTENTION,
    SDPBackend.MATH,
]


class Attend(nn.Module):
    """Attention over queries, keys and values of shape (batch, heads, length, head size)."""

    @override
    def forward(self, q: Tensor, k: Tensor, v: Tensor) -> Tensor:
        """Return the attention output, using cuDNN, flash or memory-efficient kernels on a GPU."""
        if q.is_cuda:
            with sdpa_kernel(INFERENCE_SDPA_BACKENDS, set_priority=True):
                return F.scaled_dot_product_attention(q, k, v)
        return F.scaled_dot_product_attention(q, k, v)
