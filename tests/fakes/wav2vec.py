"""A tiny wav2vec2 model with random weights, for tests of the real acoustic worker."""

import json
from pathlib import Path

from transformers import Wav2Vec2Config, Wav2Vec2ForCTC

from fakes.acoustic import VOCABULARY


def write_tiny_model(folder: Path) -> Path:
    """Save a small random wav2vec2 CTC model and the vocabulary of the German one to ``folder``."""
    config = Wav2Vec2Config(
        vocab_size=len(VOCABULARY),
        hidden_size=16,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=32,
        conv_dim=(8, 8, 8, 8, 8, 8, 8),
        conv_stride=(5, 2, 2, 2, 2, 2, 2),
        conv_kernel=(10, 3, 3, 3, 3, 2, 2),
        num_conv_pos_embeddings=8,
        num_conv_pos_embedding_groups=2,
        do_stable_layer_norm=True,
        feat_extract_norm="layer",
        pad_token_id=0,
    )
    Wav2Vec2ForCTC(config).save_pretrained(folder)
    (folder / "vocab.json").write_text(
        json.dumps({token: index for index, token in enumerate(VOCABULARY)}), encoding="utf-8"
    )
    return folder
