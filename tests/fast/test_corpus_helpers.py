"""Stage 1 tests of the corpus helpers of the stage 2 tests (``tests/realworld.py``).

Without a corpus, or without the corpus folder a test reads, the test is skipped with a message
that names ``docs/dev/corpus.md``; when the folder is there, a missing file or song fails the test,
never skips it.
"""

from pathlib import Path

import pytest

from realworld import chosen_language, corpus_path, corpus_song, tempo_ratio


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty corpus with a ``songs`` and an ``mp3`` folder."""
    root = tmp_path / "corpus"
    (root / "songs").mkdir(parents=True)
    (root / "mp3").mkdir()
    monkeypatch.setenv("VOCATRON_CORPUS", str(root))
    return root


def test_without_a_corpus_the_test_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOCATRON_CORPUS", str(tmp_path / "none"))
    with pytest.raises(pytest.skip.Exception, match=r"local corpus .*docs/dev/corpus\.md"):
        corpus_path("reference", "a.wav")
    with pytest.raises(pytest.skip.Exception):
        corpus_song("Artist - Title")


def test_a_present_part_is_returned_as_an_absolute_path(corpus: Path) -> None:
    (corpus / "reference").mkdir()
    (corpus / "reference" / "a.wav").write_bytes(b"")
    found = corpus_path("reference", "a.wav")
    assert found.is_absolute()
    assert found == (corpus / "reference" / "a.wav").resolve()


def test_a_missing_folder_of_a_present_corpus_skips_and_names_it_and_the_page(
    corpus: Path,
) -> None:
    del corpus
    with pytest.raises(
        pytest.skip.Exception, match=r"has no folder reference; see docs/dev/corpus\.md"
    ):
        corpus_path("reference", "a.wav")


@pytest.mark.parametrize("parts", [("songs", "a.lrc"), ("songs", "work", "a.wav")])
def test_a_missing_part_of_a_present_folder_fails_and_names_it(
    corpus: Path, parts: tuple[str, ...]
) -> None:
    del corpus
    with pytest.raises(pytest.fail.Exception, match=rf"has no {'/'.join(parts)}\b"):
        corpus_path(*parts)


@pytest.mark.parametrize("suffix", [".ogg", ".mp3", ".FLAC", ".m4a"])
def test_a_song_is_found_by_name_in_any_audio_format(corpus: Path, suffix: str) -> None:
    (corpus / "songs" / f"Artist - Title{suffix}").write_bytes(b"")
    (corpus / "songs" / "Artist - Title.lrc").write_bytes(b"")
    (corpus / "songs" / "Artist - Other.ogg").write_bytes(b"")
    assert corpus_song("Artist - Title").name == f"Artist - Title{suffix}"


def test_a_song_is_looked_for_in_the_named_folder(corpus: Path) -> None:
    (corpus / "songs" / "Artist - Title.ogg").write_bytes(b"")
    (corpus / "mp3" / "Artist - Title.mp3").write_bytes(b"")
    assert corpus_song("Artist - Title", "mp3") == (corpus / "mp3" / "Artist - Title.mp3").resolve()


def test_a_missing_song_fails_even_if_its_lyrics_are_there(corpus: Path) -> None:
    (corpus / "songs" / "Artist - Title.lrc").write_bytes(b"")
    with pytest.raises(pytest.fail.Exception, match="no audio file named Artist - Title"):
        corpus_song("Artist - Title")


def test_two_formats_of_one_song_fail_since_it_is_unclear_which_is_meant(corpus: Path) -> None:
    (corpus / "songs" / "Artist - Title.ogg").write_bytes(b"")
    (corpus / "songs" / "Artist - Title.mp3").write_bytes(b"")
    with pytest.raises(pytest.fail.Exception, match="2 audio files"):
        corpus_song("Artist - Title")


def test_a_missing_folder_is_skipped(corpus: Path) -> None:
    with pytest.raises(pytest.skip.Exception, match=r"has no folder flac; see docs/dev/corpus\.md"):
        corpus_song("Artist - Title", "flac")
    assert corpus.is_dir()


def test_the_chosen_language_is_read_from_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOCATRON_X_LANGUAGE", raising=False)
    assert chosen_language("VOCATRON_X_LANGUAGE") is None
    monkeypatch.setenv("VOCATRON_X_LANGUAGE", "")
    assert chosen_language("VOCATRON_X_LANGUAGE") is None
    monkeypatch.setenv("VOCATRON_X_LANGUAGE", "en")
    assert chosen_language("VOCATRON_X_LANGUAGE") == "en"


@pytest.mark.parametrize("code", ["EN", "fr", "english"])
def test_an_unsupported_chosen_language_is_an_error_not_a_run_that_skips_everything(
    code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOCATRON_X_LANGUAGE", code)
    with pytest.raises(pytest.UsageError, match=f"VOCATRON_X_LANGUAGE={code} is no supported"):
        chosen_language("VOCATRON_X_LANGUAGE")


@pytest.mark.parametrize(
    ("first", "second", "difference"),
    [(100.0, 100.0, 0.0), (100.0, 102.0, 0.0196), (100.0, 201.0, 0.005), (200.0, 99.0, 0.0101),
     (60.0, 125.0, 0.04), (90.0, 140.0, 0.2857)],
)  # fmt: skip
def test_two_tempos_differ_by_their_distance_after_doubling_or_halving(
    first: float, second: float, difference: float
) -> None:
    assert tempo_ratio(first, second) == pytest.approx(difference, abs=1e-3)
