"""Reading the ``model`` section of a Roformer model's YAML configuration."""

from pydantic import BaseModel, ConfigDict
from ruamel.yaml import YAML
from ruamel.yaml.constructor import SafeConstructor
from ruamel.yaml.nodes import SequenceNode

IGNORED: dict[str, str] = {
    "attn_dropout": "dropout only matters in training",
    "ff_dropout": "dropout only matters in training",
    "flash_attn": "inference always uses PyTorch's fastest attention",
    "dim_freqs_in": "not used by the model",
    "multi_stft_resolution_loss_weight": "training loss",
    "multi_stft_resolutions_window_sizes": "training loss",
    "multi_stft_hop_size": "training loss",
    "multi_stft_normalized": "training loss",
    "use_torch_checkpoint": "training memory saver",
    "linear_transformer_depth": "must be 0: the trimmed model has no linear attention",
}
"""Keys of the configuration the trimmed model does not need, with the reason."""


DEFAULT_FREQS_PER_BANDS = (2,) * 24 + (4,) * 12 + (12,) * 8 + (24,) * 8 + (48,) * 8 + (128, 129)
"""The band widths of the upstream BS-Roformer, for a configuration that leaves them out."""


class RoformerConfig(BaseModel):
    """The keys both Roformer configurations share.

    A key a configuration leaves out has the default of the upstream model.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dim: int
    depth: int
    stereo: bool = False
    num_stems: int = 1
    time_transformer_depth: int = 2
    freq_transformer_depth: int = 2
    dim_head: int = 64
    heads: int = 8
    stft_n_fft: int = 2048
    stft_hop_length: int = 512
    stft_win_length: int = 2048
    stft_normalized: bool = False
    mlp_expansion_factor: int = 4
    skip_connection: bool = False


class ModelConfig(RoformerConfig):
    """The ``model`` section of a BS-Roformer configuration, as far as the trimmed model uses it.

    ``mask_estimator_depth`` counts the linear layers of a mask network, as upstream.
    """

    freqs_per_bands: tuple[int, ...] = DEFAULT_FREQS_PER_BANDS
    mask_estimator_depth: int = 2


class MelModelConfig(RoformerConfig):
    """The ``model`` section of a Mel-Band Roformer configuration (it has ``num_bands``).

    ``mask_estimator_depth`` counts the hidden layers of a mask network, as upstream.
    """

    num_bands: int = 60
    sample_rate: int = 44100
    mask_estimator_depth: int = 1


def _tuple_constructor(loader: SafeConstructor, node: SequenceNode) -> tuple[object, ...]:
    """Read a ``!!python/tuple`` as a tuple (the configurations write band widths that way)."""
    return tuple(loader.construct_sequence(node))


def parse_config(text: str) -> ModelConfig | MelModelConfig:
    """Read the ``model`` section of the YAML ``text``.

    A section with ``num_bands`` describes a Mel-Band Roformer, any other a BS-Roformer.

    Raises:
        ValueError: If the section is missing, a key is unknown, or the model would need linear
            attention.
    """
    yaml = YAML(typ="safe")
    yaml.constructor.add_constructor("tag:yaml.org,2002:python/tuple", _tuple_constructor)
    data: object = yaml.load(text)
    section = data.get("model") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        raise ValueError("the configuration has no 'model' section")
    section = {str(key): value for key, value in section.items()}
    if section.get("linear_transformer_depth", 0) != 0:
        raise ValueError(
            f"unsupported: linear_transformer_depth ({IGNORED['linear_transformer_depth']})"
        )
    for key in IGNORED:
        section.pop(key, None)
    if "num_bands" in section:
        return MelModelConfig.model_validate(section)
    return ModelConfig.model_validate(section)
