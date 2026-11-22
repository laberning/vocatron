"""Stage 1: the model registry and the rules that judge a model folder."""

import re
from pathlib import Path
from random import Random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.languages import LANGUAGES
from vocatron.core.models import (
    DEFAULT_SET,
    DEFAULT_VOCALS_MODEL,
    KARAOKE_MODEL,
    MODELS,
    VOCALS_MODELS,
    ModelFile,
    Observed,
    State,
    UnknownModelError,
    file_state,
    find_model,
    hf_files,
    human_size,
    language_models,
    model_state,
    part_path,
)

FILE = ModelFile(url="https://example.org/a", path="a", size=10, sha256="ab" * 32)
STATES: list[State] = ["present", "missing", "partial", "mismatch"]


def test_names_are_unique_and_the_default_set_is_in_the_registry() -> None:
    names = [spec.name for spec in MODELS]
    assert len(names) == len(set(names))
    assert set(DEFAULT_SET) <= set(names)


def test_leap_is_the_default_vocals_model_and_ep317_stays_selectable() -> None:
    assert DEFAULT_VOCALS_MODEL == "bs-roformer-leap"  # ADR-0011
    assert DEFAULT_VOCALS_MODEL in DEFAULT_SET
    assert "bs-roformer-ep317" not in DEFAULT_SET
    assert {DEFAULT_VOCALS_MODEL, "bs-roformer-ep317"} <= set(VOCALS_MODELS)


def test_every_file_is_pinned_by_a_full_checksum_and_a_revision_in_its_url() -> None:
    for spec in MODELS:
        assert spec.files
        for file in spec.files:
            assert re.fullmatch(r"[0-9a-f]{64}", file.sha256), file.url
            assert file.size > 0
            assert file.url.startswith("https://")
            assert not file.path.startswith(("/", ".."))
        if "huggingface.co" in spec.files[0].url:
            assert re.fullmatch(r"[0-9a-f]{40}", spec.revision)
            assert all(f"/resolve/{spec.revision}/" in f.url for f in spec.files)


def test_no_two_files_of_a_model_share_a_path() -> None:
    for spec in MODELS:
        paths = [f.path for f in spec.files]
        assert len(paths) == len(set(paths)), spec.name


def test_the_size_is_the_sum_of_the_files() -> None:
    spec = find_model("wav2vec2-de")
    assert spec.size == sum(f.size for f in spec.files) > 1_000_000_000


def test_the_notice_names_the_model_and_its_licence() -> None:
    assert (
        find_model("bs-roformer-karaoke").notice() == "karaoke_bs_roformer_anvuew: licence GPL-3.0"
    )


def test_an_unknown_model_lists_the_known_ones() -> None:
    with pytest.raises(UnknownModelError) as caught:
        find_model("nope")
    known = ", ".join(spec.name for spec in MODELS)
    assert caught.value.args[0] == f"unknown model 'nope'; known models: {known}"


def test_hugging_face_files_are_resolved_at_the_revision() -> None:
    (file,) = hf_files("acme/model", "abc123", [("sub/w.bin", 7, "ff" * 32)])
    assert file == ModelFile(
        url="https://huggingface.co/acme/model/resolve/abc123/sub/w.bin",
        path="sub/w.bin",
        size=7,
        sha256="ff" * 32,
    )


@pytest.mark.parametrize(
    ("found", "expected"),
    [
        (Observed(None, None, has_part=False), "missing"),
        (Observed(None, None, has_part=True), "partial"),
        (Observed(10, None, has_part=False), "present"),
        (Observed(10, "ab" * 32, has_part=False), "present"),
        (Observed(10, "ab" * 32, has_part=True), "present"),
        (Observed(9, None, has_part=False), "mismatch"),
        (Observed(10, "cd" * 32, has_part=False), "mismatch"),
        (Observed(11, "ab" * 32, has_part=True), "mismatch"),
    ],
)
def test_file_state_table(found: Observed, expected: State) -> None:
    assert file_state(FILE, found) == expected


@given(st.lists(st.sampled_from(STATES), min_size=1))
def test_model_state_follows_the_rule(states: list[State]) -> None:
    result = model_state(states)
    if "mismatch" in states:
        assert result == "mismatch"
    elif set(states) == {"present"}:
        assert result == "present"
    elif set(states) == {"missing"}:
        assert result == "missing"
    else:
        assert result == "partial"


@given(st.lists(st.sampled_from(STATES), min_size=1), st.randoms())
def test_model_state_does_not_depend_on_the_order(states: list[State], rnd: Random) -> None:
    shuffled = list(states)
    rnd.shuffle(shuffled)
    assert model_state(shuffled) == model_state(states)


def test_the_part_file_lies_next_to_the_file() -> None:
    assert part_path(Path("/m/x/model.bin")) == Path("/m/x/model.bin.part")


@pytest.mark.parametrize(
    ("size", "text"),
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (2273, "2.2 KB"),
        (639331213, "609.7 MB"),
        (1617824864, "1.5 GB"),
    ],
)
def test_human_size(size: int, text: str) -> None:
    assert human_size(size) == text


def test_only_a_non_commercial_model_gives_a_licence_warning() -> None:
    warned = {spec.name: spec.licence_warning() for spec in MODELS}
    assert [name for name, note in warned.items() if note is not None] == ["mel-band-deux"]
    assert warned["mel-band-deux"] == (
        "model mel-band-deux is licensed CC BY-NC 4.0 (non-commercial use only); "
        "do not use its output commercially"
    )


def test_a_song_needs_the_default_separation_models_and_the_alignment_model_of_its_language() -> (
    None
):
    assert language_models("de") == (DEFAULT_VOCALS_MODEL, KARAOKE_MODEL, "wav2vec2-de")
    assert language_models("en") == (DEFAULT_VOCALS_MODEL, KARAOKE_MODEL, "wav2vec2-en")
    assert language_models("en") == DEFAULT_SET
    with pytest.raises(KeyError):
        language_models("fr")


def test_every_language_module_names_a_registered_alignment_model() -> None:
    for module in LANGUAGES.values():
        assert find_model(module.model).purpose.startswith("alignment")


def test_the_english_model_is_pinned_and_licensed() -> None:
    spec = find_model("wav2vec2-en")
    assert spec.source_name == "facebook/wav2vec2-large-960h-lv60-self"  # ADR-0016
    assert spec.revision == "54074b1c16f4de6a5ad59affb4caa8f2ea03a119"
    assert (spec.licence, spec.inference) == ("Apache-2.0", {"precision": "fp16"})
    assert all(spec.revision in file.url for file in spec.files)
    assert {file.path for file in spec.files} == {f.path for f in find_model("wav2vec2-de").files}
