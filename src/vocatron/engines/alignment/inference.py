"""Running wav2vec2 on pieces of a song: log-probabilities per frame (ADR-0002, PyTorch).

Only the alignment worker imports this module. The model comes from a local folder, never from
the network. The song is normalised once as a whole so that every piece sees the same scale and
the pieces fit together.
"""

import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import torch
from numpy.typing import NDArray
from transformers import Wav2Vec2ForCTC

from vocatron.core.alignment.chunks import Piece, frame_count
from vocatron.core.alignment.job import AcousticSetup
from vocatron.core.alignment.tokens import lower_case_vocabulary
from vocatron.core.separation.rules import Device

VOCAB_FILE = "vocab.json"
EPSILON = 1e-7


def load_vocabulary(folder: Path) -> list[str]:
    """Return the tokens of the model in ``folder`` by id, letters in lower case.

    The aligner compares lower-case letters; an upper-case vocabulary (the English model)
    is lower-cased here.

    Raises:
        ValueError: If the ids are not 0 to n-1, or two tokens are the same in lower case.
    """
    table = json.loads((folder / VOCAB_FILE).read_text(encoding="utf-8"))
    tokens = sorted(table, key=table.__getitem__)
    if [table[t] for t in tokens] != list(range(len(tokens))):
        raise ValueError(f"{VOCAB_FILE} does not number its tokens 0 to {len(tokens) - 1}")
    return lower_case_vocabulary(tokens)


def load_model(setup: AcousticSetup, device: Device) -> Wav2Vec2ForCTC:
    """Load the model from its folder, in half precision on the GPU when the setup says fp16."""
    half = device == "cuda" and setup.precision == "fp16"
    model = Wav2Vec2ForCTC.from_pretrained(
        setup.folder,
        dtype=torch.float16 if half else torch.float32,
        attn_implementation="sdpa",
        local_files_only=True,
    )
    module: torch.nn.Module = model  # transformers wraps ``to`` in a way the type checker misreads
    module.eval().to(device)
    return model


def normalise(wave: NDArray[np.float32]) -> NDArray[np.float32]:
    """Scale the whole song to zero mean and unit variance, as the model's processor does."""
    return ((wave - wave.mean()) / (wave.std() + EPSILON)).astype(np.float32)


def piece_log_probs(
    model: Wav2Vec2ForCTC, wave: NDArray[np.float32], piece: Piece, device: Device
) -> NDArray[np.float32]:
    """Return the log-probabilities of one piece, shaped (frames, vocabulary)."""
    samples = torch.from_numpy(wave[piece.start : piece.stop]).view(1, -1).to(device)
    samples = samples.to(model.dtype)
    with torch.inference_mode():
        logits = model(samples).logits.float()
    out = torch.log_softmax(logits, dim=-1)[0].cpu().numpy()
    expected = frame_count(piece.stop - piece.start)
    if out.shape[0] != expected:
        raise ValueError(f"the model made {out.shape[0]} frames, expected {expected}")
    return out


def hear(
    model: Wav2Vec2ForCTC,
    wave: NDArray[np.float32],
    pieces: list[Piece],
    device: Device,
    log: Callable[[str], None],
    on_progress: Callable[[int, int], None] = lambda done, total: None,
) -> list[tuple[int, NDArray[np.float32]]]:
    """Run the model over the pieces and return each piece's first frame and frames.

    ``on_progress`` hears how many pieces are done of how many, after each piece.
    """
    parts: list[tuple[int, NDArray[np.float32]]] = []
    for number, piece in enumerate(pieces, start=1):
        parts.append((piece.first_frame, piece_log_probs(model, wave, piece, device)))
        log(f"piece {number} of {len(pieces)} done")
        on_progress(number, len(pieces))
    return parts
