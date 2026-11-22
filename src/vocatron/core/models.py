"""The model registry and the rules that judge a model folder (ADR-0002).

Every model Vocatron uses is listed here with its source, revision, files (URL, size, SHA-256),
licence and inference settings. Nothing else is ever downloaded. ``THIRD_PARTY.md`` lists the same
models; a test keeps the two in step. The state of a model on disk is judged by pure rules from
what was observed about its files.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from vocatron.core.languages import LANGUAGES

State = Literal["present", "missing", "partial", "mismatch"]
"""``present``: complete and correct; ``missing``: nothing there; ``partial``: some files, or an
interrupted download; ``mismatch``: a file has the wrong size or checksum."""

KIB = 1024
HF = "https://huggingface.co"
UVR_RELEASE = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models"
UVR_CONFIGS = (
    "https://raw.githubusercontent.com/TRvlvr/application_data/"
    "22b79fc01ada8f3b9e3526ad0ed645af414a7cde/mdx_model_data/mdx_c_configs"
)


class ModelFile(BaseModel):
    """One file of a model.

    Attributes:
        url: Where it is downloaded from; the revision is part of the URL.
        path: Where it lies relative to the model's folder.
        size: Its size in bytes.
        sha256: Its SHA-256 as lower-case hex.
    """

    model_config = ConfigDict(frozen=True)

    url: str
    path: str
    size: int
    sha256: str


class ModelPin(BaseModel):
    """A model as the fingerprint of a stage sees it: name, revision and inference settings."""

    name: str
    revision: str
    inference: dict[str, str | int]


class ModelSpec(BaseModel):
    """A model as pinned by Vocatron.

    Attributes:
        name: Short name used on the command line and in stage declarations; also its folder.
        source_name: The model's name as its publisher calls it (as in ``THIRD_PARTY.md``).
        purpose: What Vocatron uses it for.
        source: Where it comes from.
        revision: The pinned revision (a commit, or a release tag).
        licence: The licence as stated by the publisher.
        licence_url: Where the licence is stated, if anywhere.
        inference: Inference settings; part of the pin.
        files: The files to download.
        non_commercial: Whether the licence forbids commercial use; a stage that runs such a
            model warns about it (``licence_warning``), so it is never used unknowingly.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    source_name: str
    purpose: str
    source: str
    revision: str
    licence: str
    licence_url: str | None
    inference: dict[str, str | int]
    files: tuple[ModelFile, ...]
    non_commercial: bool = False

    @property
    def size(self) -> int:
        """The total size of all files in bytes."""
        return sum(f.size for f in self.files)

    def pin(self) -> ModelPin:
        """Return what a stage's fingerprint records of this model."""
        return ModelPin(name=self.name, revision=self.revision, inference=self.inference)

    def notice(self) -> str:
        """Return the one-line licence notice printed on download and by ``vocatron models``."""
        return f"{self.source_name}: licence {self.licence}"

    def licence_warning(self) -> str | None:
        """Return the warning a run with this model gives, or ``None`` when its licence allows it.

        A non-commercial licence is fine for a private karaoke evening, but the fan has to know.
        """
        if not self.non_commercial:
            return None
        return (
            f"model {self.name} is licensed {self.licence} (non-commercial use only); "
            "do not use its output commercially"
        )


def hf_files(
    repo: str, revision: str, files: Iterable[tuple[str, int, str]]
) -> tuple[ModelFile, ...]:
    """Build the files of a Hugging Face repository at ``revision`` from (path, size, sha256)."""
    return tuple(
        ModelFile(url=f"{HF}/{repo}/resolve/{revision}/{path}", path=path, size=size, sha256=sha)
        for path, size, sha in files
    )


_WAV2VEC2_LICENCE_URL = "https://www.apache.org/licenses/LICENSE-2.0"
_WAV2VEC2_INFERENCE: dict[str, str | int] = {"precision": "fp16"}
_DE_REVISION = "4b8a02957378d0f2da2ef74091156b032c485a89"
_EN_REVISION = "54074b1c16f4de6a5ad59affb4caa8f2ea03a119"
_WHISPER_REVISION = "41f01f3fe87f28c78e2fbf8b568835947dd65ed9"
_KARAOKE_REVISION = "0d4423d42e12cf2ba39ae09171028507b8a2a7be"
_EP317 = "model_bs_roformer_ep_317_sdr_12.9755"
_LEAP_REVISION = "4e47d6662ae82eaa8b4ac4329fe66099a843b48e"
_DEUX_REVISION = "402dd9a19baaed8c6f1b54458ce6ae2ae19f354e"
_GABOX_REVISION = "7860d31d8cc1c73b46c1cbdc2b497210c97478ae"
_FRAZER_REVISION = "0d66103c6b79c0dd0e9efd38ca70db7042f6f695"

MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        name="bs-roformer-ep317",
        source_name=_EP317,
        purpose="vocals / instrumental separation",
        source="GitHub release TRvlvr/model_repo (all_public_uvr_models); "
        "config from TRvlvr/application_data",
        revision="all_public_uvr_models",
        licence="no licence stated",
        licence_url=None,
        inference={"chunk_size": 352800, "num_overlap": 4, "precision": "fp16"},
        files=(
            ModelFile(
                url=f"{UVR_RELEASE}/{_EP317}.ckpt",
                path=f"{_EP317}.ckpt",
                size=639331213,
                sha256="5b84f37e8d444c8cb30c79d77f613a41c05868ff9c9ac6c7049c00aefae115aa",
            ),
            ModelFile(
                url=f"{UVR_CONFIGS}/{_EP317}.yaml",
                path=f"{_EP317}.yaml",
                size=2273,
                sha256="2bfdd16c656bd9519aba757cc4f8834b7ede675eb1e00ec4772d74ae1c41af7f",
            ),
        ),
    ),
    ModelSpec(
        name="bs-roformer-leap",
        source_name="bs_roformer_leap_voc",
        purpose="vocals / instrumental separation",
        source="Hugging Face pcunwa/BS-Roformer-Leap",
        revision=_LEAP_REVISION,
        licence="no licence stated",
        licence_url=None,
        inference={"chunk_size": 881559, "num_overlap": 2, "precision": "fp16"},
        files=hf_files(
            "pcunwa/BS-Roformer-Leap",
            _LEAP_REVISION,
            [
                (
                    "bs_roformer_leap_voc.ckpt",
                    238220459,
                    "8c0e4bfff6be150a12582a7c236379aa42102b7f43831900df5b2addf924da7c",
                ),
                (
                    "bs_leap_voc_conf.yaml",
                    1961,
                    "fb4238cd1e0cd6e6620b3f4e70bbea0dc5b1f1bdcf51f96b5091d2ee6794b8c8",
                ),
            ],
        ),
    ),
    ModelSpec(
        name="bs-roformer-karaoke",
        source_name="karaoke_bs_roformer_anvuew",
        purpose="lead / backing vocals separation",
        source="Hugging Face anvuew/karaoke_bs_roformer",
        revision=_KARAOKE_REVISION,
        licence="GPL-3.0",
        licence_url="https://www.gnu.org/licenses/gpl-3.0.html",
        inference={"chunk_size": 640000, "num_overlap": 4, "precision": "fp16"},
        files=hf_files(
            "anvuew/karaoke_bs_roformer",
            _KARAOKE_REVISION,
            [
                (
                    "karaoke_bs_roformer_anvuew.ckpt",
                    204486925,
                    "206d04757cb5f75ca3b55f8a0a48f5c26aa2351d4ff3c7adbfc9affa30ea3ae4",
                ),
                (
                    "karaoke_bs_roformer_anvuew.yaml",
                    1973,
                    "5cb3f127ecbc6a8e37f31ea7e05f60f360a44da43e857bde805b7b68558f6338",
                ),
            ],
        ),
    ),
    ModelSpec(
        name="bs-roformer-leap-inst",
        source_name="bs_leap_xe_inst",
        purpose="vocals / instrumental (candidate, instrumental output)",
        source="Hugging Face pcunwa/BS-Roformer-Leap, folder Xe",
        revision=_LEAP_REVISION,
        licence="no licence stated",
        licence_url=None,
        inference={
            "chunk_size": 881559,
            "num_overlap": 2,
            "precision": "fp16",
            "target": "instrumental",
        },
        files=hf_files(
            "pcunwa/BS-Roformer-Leap",
            _LEAP_REVISION,
            [
                (
                    "Xe/bs_leap_xe_inst.ckpt",
                    267798769,
                    "33ee9415f491d257fa7a79f6e92a80d647bc71ed622bfef9a137b6e4250307d3",
                ),
                (
                    "Xe/leap_xe_config_inst.yaml",
                    2189,
                    "bc188276085e07840757e5117285ead7ec5631f94329c1c6f5f0aff385adea4d",
                ),
            ],
        ),
    ),
    ModelSpec(
        name="mel-band-deux",
        source_name="becruily_deux",
        purpose="vocals / instrumental (candidate, Mel-Band Roformer)",
        source="Hugging Face becruily/mel-band-roformer-deux",
        revision=_DEUX_REVISION,
        licence="CC BY-NC 4.0",
        licence_url="https://creativecommons.org/licenses/by-nc/4.0/",
        non_commercial=True,
        inference={"chunk_size": 573300, "num_overlap": 2, "precision": "fp16"},
        files=hf_files(
            "becruily/mel-band-roformer-deux",
            _DEUX_REVISION,
            [
                (
                    "becruily_deux.ckpt",
                    435006815,
                    "10255c02295bf3e3865d4ee50ff752d7b19b124ed5fd93b147babc4333eda3aa",
                ),
                (
                    "config_deux_becruily.yaml",
                    1175,
                    "bb3ea9bce37ca96d63568490d5a92d7e41df3d7726788b6970c10d89eb62d902",
                ),
            ],
        ),
    ),
    ModelSpec(
        name="mel-band-flowersv10",
        source_name="inst_gaboxFlowersV10",
        purpose="vocals / instrumental (candidate, Mel-Band Roformer, instrumental output)",
        source="Hugging Face GaboxR67/MelBandRoformers, folder melbandroformers/instrumental",
        revision=_GABOX_REVISION,
        licence="no licence stated",
        licence_url=None,
        inference={
            "chunk_size": 352800,
            "num_overlap": 2,
            "precision": "fp16",
            "target": "instrumental",
        },
        files=hf_files(
            "GaboxR67/MelBandRoformers",
            _GABOX_REVISION,
            [
                (
                    "melbandroformers/instrumental/inst_gaboxFlowersV10.ckpt",
                    489571079,
                    "fe3aa51927beb60ff345b8b672c11760fb8bdaa6039d8c61631416a5b4f7a047",
                ),
                (
                    "melbandroformers/instrumental/v10.yaml",
                    1813,
                    "e4a8d2ebb57986ce154ce066bca5674b6a3aeda3ed9d623fb49af450335efe1e",
                ),
            ],
        ),
    ),
    ModelSpec(
        name="bs-roformer-karaoke-frazer",
        source_name="bs_roformer_karaoke_frazer_becruily",
        purpose="lead / backing vocals separation (candidate)",
        source="Hugging Face becruily/bs-roformer-karaoke",
        revision=_FRAZER_REVISION,
        licence="no licence stated",
        licence_url=None,
        inference={"chunk_size": 882000, "num_overlap": 4, "precision": "fp16"},
        files=hf_files(
            "becruily/bs-roformer-karaoke",
            _FRAZER_REVISION,
            [
                (
                    "bs_roformer_karaoke_frazer_becruily.ckpt",
                    204436907,
                    "eb90ee24c1154d83fbcfd27e96182f19e061557cc6e4746953125e08c29389f9",
                ),
                (
                    "config.yaml",
                    1903,
                    "1d3b58b473025183d0d3c91e7a444cb5f1418d9f34e8f46b8d2fb10d2cc8ab34",
                ),
            ],
        ),
    ),
    ModelSpec(
        name="wav2vec2-de",
        source_name="jonatasgrosman/wav2vec2-large-xlsr-53-german",
        purpose="alignment, German",
        source="Hugging Face jonatasgrosman/wav2vec2-large-xlsr-53-german",
        revision=_DE_REVISION,
        licence="Apache-2.0",
        licence_url=_WAV2VEC2_LICENCE_URL,
        inference=_WAV2VEC2_INFERENCE,
        files=hf_files(
            "jonatasgrosman/wav2vec2-large-xlsr-53-german",
            _DE_REVISION,
            [
                (
                    "pytorch_model.bin",
                    1262089623,
                    "bff6d75ab89d8ca9cd103df9beb9c10f547501cf5a34aeabea1c8d736c1b81cb",
                ),
                (
                    "config.json",
                    1782,
                    "42175a918795a7343c58dbcad995603912a0d85c729cc4d7b8eb089a7a569183",
                ),
                (
                    "preprocessor_config.json",
                    262,
                    "ca5999a45e98bb76ea87a461ba28a23ad32a5bb9f733b8e0f6546ff38b6c612d",
                ),
                (
                    "special_tokens_map.json",
                    85,
                    "bb7068de1150661a10b55f9e4b12a0e77af8bf91f5e45e1b58afaf1d0e17f675",
                ),
                (
                    "vocab.json",
                    350,
                    "31d0914432f4492a24ce83abfd767421844afe5cef20346a48c6c877dee28378",
                ),
            ],
        ),
    ),
    ModelSpec(
        name="wav2vec2-en",
        source_name="facebook/wav2vec2-large-960h-lv60-self",
        purpose="alignment, English",
        source="Hugging Face facebook/wav2vec2-large-960h-lv60-self",
        revision=_EN_REVISION,
        licence="Apache-2.0",
        licence_url=_WAV2VEC2_LICENCE_URL,
        inference=_WAV2VEC2_INFERENCE,
        files=hf_files(
            "facebook/wav2vec2-large-960h-lv60-self",
            _EN_REVISION,
            [
                (
                    "pytorch_model.bin",
                    1262055246,
                    "00b604cf4d28e86559e8adaeb3a186daa89dc37f5ab216771a0a15a26db0de9f",
                ),
                (
                    "config.json",
                    1606,
                    "bcb82b508db66c6772b34a978bcc6a411f9ea99c33cd9dee337119b5f6ddb797",
                ),
                (
                    "preprocessor_config.json",
                    158,
                    "c403ce09975b90dff0dd8302c42d422e9de1f166cd7772df23490069893cb0cf",
                ),
                (
                    "special_tokens_map.json",
                    85,
                    "bb7068de1150661a10b55f9e4b12a0e77af8bf91f5e45e1b58afaf1d0e17f675",
                ),
                (
                    "vocab.json",
                    291,
                    "19727f8944fe6459fc3f240ae2c198395b740f6a029bd23e06656266b83bcf64",
                ),
            ],
        ),
    ),
    ModelSpec(
        name="whisper-turbo",
        source_name="openai/whisper-large-v3-turbo",
        purpose="transcription (fallback)",
        source="Hugging Face openai/whisper-large-v3-turbo",
        revision=_WHISPER_REVISION,
        licence="MIT",
        licence_url="https://opensource.org/license/mit",
        inference={"precision": "fp16"},
        files=hf_files(
            "openai/whisper-large-v3-turbo",
            _WHISPER_REVISION,
            [
                (
                    "model.safetensors",
                    1617824864,
                    "542566a422ae4f3fd23f1ba11add198fca01bbf82e66e6a2857b3f608b1eb9d1",
                ),
                (
                    "added_tokens.json",
                    34648,
                    "3c51f66c4c21f9e126970078f11ae77a78c74aee8df606ee9daba86e467108e0",
                ),
                (
                    "config.json",
                    1256,
                    "c5b526b3e3cd64cd8940dabb45e8ba726629e22d8ed389c29b552f9140daf04a",
                ),
                (
                    "generation_config.json",
                    3772,
                    "cce11bfe3aaa6ae9e072ea2637caaec8795e68d9b67e655a5af16ee509681a4c",
                ),
                (
                    "merges.txt",
                    493869,
                    "2df2990a395e35e8dfbc7511e08c12d56018d8d04691e0133e5d63b21e154dc6",
                ),
                (
                    "normalizer.json",
                    52666,
                    "bf1c507dc8724ca9cf9903640dacfb69dae2f00edee4f21ceba106a7392f26dd",
                ),
                (
                    "preprocessor_config.json",
                    340,
                    "7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711",
                ),
                (
                    "special_tokens_map.json",
                    2186,
                    "baea4ea09372eb4fca86b4e4346139fd73cb807d5087e9de0948e971739c3e74",
                ),
                (
                    "tokenizer.json",
                    2710337,
                    "297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd",
                ),
                (
                    "tokenizer_config.json",
                    282843,
                    "844b642c73a91359722f47b35705f7174686df33d252695d8572cf9ac03a6389",
                ),
                (
                    "vocab.json",
                    1036558,
                    "e2aa043ef015641d363d8288e7c241c85e36a5c761fb303598e0710233344387",
                ),
            ],
        ),
    ),
)

DEFAULT_VOCALS_MODEL = "bs-roformer-leap"
"""The default vocals/instrumental model (ADR-0011); ``bs-roformer-ep317`` stays selectable."""
VOCALS_MODELS: tuple[str, ...] = (
    DEFAULT_VOCALS_MODEL,
    "bs-roformer-ep317",
    "bs-roformer-leap-inst",
    "mel-band-deux",
    "mel-band-flowersv10",
)
"""The registered models that separate vocals from the instrumental (``separation.model``)."""
KARAOKE_MODEL = "bs-roformer-karaoke"
"""The default model that splits the vocals into lead and backing."""
KARAOKE_MODELS: tuple[str, ...] = (KARAOKE_MODEL, "bs-roformer-karaoke-frazer")
"""The registered models that split lead and backing vocals (``separation.karaoke_model``)."""


def language_models(code: str) -> tuple[str, ...]:
    """Return the registry names of the models a song in the language ``code`` needs.

    The default vocals and karaoke models and the alignment model of the language's module.

    Raises:
        KeyError: If Vocatron has no module for ``code``.
    """
    return (DEFAULT_VOCALS_MODEL, KARAOKE_MODEL, LANGUAGES[code].model)


DOWNLOAD_LANGUAGE = "en"
"""The language whose models ``vocatron models download`` fetches when none is given.

``vocatron doctor`` checks the models of the same language when ``lyrics.language`` is not set,
so the two agree after following the install guide.
"""

DEFAULT_SET: tuple[str, ...] = language_models(DOWNLOAD_LANGUAGE)
"""What an English song needs; ``vocatron models download`` without names fetches these."""


class UnknownModelError(KeyError):
    """A model name is not in the registry."""


def find_model(name: str) -> ModelSpec:
    """Return the model called ``name``.

    Raises:
        UnknownModelError: If the registry has no such model; the message lists the known names.
    """
    for spec in MODELS:
        if spec.name == name:
            return spec
    known = ", ".join(spec.name for spec in MODELS)
    raise UnknownModelError(f"unknown model '{name}'; known models: {known}")


@dataclass(frozen=True)
class Observed:
    """What was found on disk for one file.

    Attributes:
        size: The size in bytes of the finished file, or ``None`` when it does not exist.
        sha256: Its SHA-256, or ``None`` when it was not computed (only the size is judged).
        has_part: Whether an interrupted download (``<file>.part``) exists.
    """

    size: int | None
    sha256: str | None
    has_part: bool


def part_path(destination: Path) -> Path:
    """Return the path of the file that an interrupted download of ``destination`` leaves."""
    return destination.with_name(destination.name + ".part")


def file_state(file: ModelFile, found: Observed) -> State:
    """Judge one file.

    A wrong size or checksum is ``mismatch`` and beats everything; no file but a ``.part`` file
    is ``partial``.
    """
    if found.size is None:
        return "partial" if found.has_part else "missing"
    if found.size != file.size or (found.sha256 is not None and found.sha256 != file.sha256):
        return "mismatch"
    return "present"


def model_state(states: Sequence[State]) -> State:
    """Combine the states of a model's files.

    Any mismatch wins; otherwise all present or all missing; otherwise ``partial``.
    """
    if "mismatch" in states:
        return "mismatch"
    if all(s == "present" for s in states):
        return "present"
    if all(s == "missing" for s in states):
        return "missing"
    return "partial"


def human_size(size: int) -> str:
    """Format a byte count for people: ``2.2 KB``, ``609.7 MB``, ``1.5 GB`` (powers of 1024)."""
    value = float(size)
    for unit in ("B", "KB", "MB"):
        if value < KIB:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= KIB
    return f"{value:.1f} GB"
