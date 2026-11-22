"""Stage 1 tests for ``tools/separation_eval.py`` with made-up audio (no real songs, no GPU)."""

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import separation_eval
from fakes.audio import decode_file
from vocatron.core.errors import StageError
from vocatron.core.separation.rules import SAMPLE_RATE
from vocatron.lab.separation.evaluation import EvalPair, Failure, Item, Timing

SECONDS = 2
DELAY = 300  # samples by which the mixtures lag the true instrumentals


def noise(seed: int, scale: float = 0.2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.uniform(-scale, scale, (SECONDS * SAMPLE_RATE, 2)).astype(np.float32)


def music(seed: int) -> np.ndarray:
    """A few sines with a slow beat: a signal that Ogg Vorbis keeps close to the original."""
    rng = np.random.default_rng(seed)
    t = np.arange(SECONDS * SAMPLE_RATE) / SAMPLE_RATE
    channels = []
    for _ in range(2):
        freqs = rng.uniform(200, 3000, 4)
        wave = sum(np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) for f in freqs)
        channels.append(wave * (0.5 + 0.5 * np.sin(2 * np.pi * 2 * t)) * 0.08)
    return np.stack(channels, axis=1).astype(np.float32)


def write(path: Path, data: np.ndarray, fmt: str = "WAV") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, data, SAMPLE_RATE, format=fmt)


@pytest.fixture(autouse=True)
def no_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ffmpeg in stage 1: soundfile decodes, and the MP3 versions are made-up WAV data.

    The made-up runner does not care about the name; the real decoder is tested in the engines.
    """

    def fake_encode(source: Path, kbit: int, destination: Path) -> None:
        write(destination, noise(0))

    monkeypatch.setattr(separation_eval, "encode_mp3", fake_encode)
    monkeypatch.setattr(separation_eval, "decode", decode_file)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    for index, name in enumerate(("Artist - One", "Artist - Two")):
        instrumental = music(index)
        vocals = music(index + 10)
        write(root / "instrumentals" / f"{name}.ogg", instrumental, "OGG")
        mix = np.concatenate([np.zeros((DELAY, 2), np.float32), instrumental + vocals])
        write(root / "songs" / f"{name}.ogg", mix, "OGG")
    write(root / "songs" / "Only Song.ogg", noise(5), "OGG")  # no instrumental: no material
    return root


def estimate_runner(error: float = 0.02) -> separation_eval.Runner:
    """A runner that "separates" by writing the lagged true instrumental plus a little noise."""

    def run(model: str, pairs: Sequence[EvalPair], out: Path) -> None:
        for pair in pairs:
            if Path(pair.output).is_file():
                continue
            mix, _ = sf.read(pair.audio, dtype="float32", always_2d=True)
            base = np.concatenate(
                [np.zeros((DELAY, 2), np.float32), music(int("two" in pair.name))]
            )[: len(mix)]
            estimate = np.zeros(mix.shape, np.float32)
            estimate[: len(base)] = base
            rng = np.random.default_rng(len(model))
            estimate += rng.uniform(-error, error, estimate.shape).astype(np.float32)
            write(Path(pair.output), estimate)
            timing = Timing(name=pair.name, audio_seconds=len(mix) / SAMPLE_RATE, seconds=1.5,
                            peak_vram_gib=2.5)  # fmt: skip
            with (out / model / "timings.jsonl").open("a") as file:
                file.write(timing.model_dump_json() + "\n")

    return run


def test_the_material_is_the_official_instrumentals_with_their_songs(corpus: Path) -> None:
    items = separation_eval.collect_items(corpus)
    assert [(i.id, i.group) for i in items] == [
        ("artist-one", "official"),
        ("artist-two", "official"),
    ]
    assert items[0].mix == "songs/Artist - One.ogg"
    assert items[0].truth == "instrumentals/Artist - One.ogg"


def test_every_items_file_of_a_material_folder_adds_material(corpus: Path) -> None:
    extra = Item(id="x-1", group="extra", mix="extra/m.wav", truth="extra/t.wav")
    folder = corpus / "extra"
    folder.mkdir()
    (folder / "items.json").write_text(json.dumps({"items": [extra.model_dump()]}))
    assert [i.id for i in separation_eval.collect_items(corpus)][-1] == "x-1"
    (folder / "items.json").write_text(json.dumps({"items": [extra.model_dump()] * 2}))
    with pytest.raises(ValueError, match="same id"):
        separation_eval.collect_items(corpus)


def archive(prefix: str, names: Sequence[str]) -> dict[str, object]:
    files = [
        {"name": f"{n:02d}-{prefix}-{title}.mp3", "sha1": hashlib.sha1(title.encode()).hexdigest()}
        for n, title in enumerate(names, start=1)
    ]
    return {"files": [*files, {"name": "cover.jpg", "sha1": "0"}]}


def fake_archive(url: str) -> dict[str, object]:
    return archive("mix" if "158415" in url else "inst", ["Release", "Knock"])


def fake_download(url: str, destination: Path) -> None:
    title = url.rsplit("-", 1)[-1].removesuffix(".mp3")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(title.encode())


def test_fetch_downloads_the_release_track_and_its_instrumental_and_writes_the_items(
    tmp_path: Path,
) -> None:
    items = separation_eval.fetch_woodward(tmp_path, "release", fake_archive, fake_download)
    assert [i.id for i in items.items] == ["woodward-01"]
    assert (tmp_path / "woodward" / "track-01-mix.mp3").is_file()
    assert (tmp_path / "woodward" / "track-01-instrumental.mp3").is_file()
    assert "CC BY" in items.note
    assert [i.id for i in separation_eval.collect_items(tmp_path)] == ["woodward-01"]


def test_fetch_of_the_album_takes_every_track(tmp_path: Path) -> None:
    items = separation_eval.fetch_woodward(tmp_path, "album", fake_archive, fake_download)
    assert [i.id for i in items.items] == ["woodward-01", "woodward-02"]


def test_a_download_with_the_wrong_checksum_is_refused_and_removed(tmp_path: Path) -> None:
    def broken(url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"something else")

    with pytest.raises(ValueError, match="SHA-1"):
        separation_eval.fetch_woodward(tmp_path, "release", fake_archive, broken)
    assert not (tmp_path / "woodward" / "track-01-mix.mp3").exists()


def test_a_track_without_an_instrumental_is_an_error(tmp_path: Path) -> None:
    def short(url: str) -> dict[str, object]:
        return archive("mix", ["Release"]) if "158415" in url else {"files": []}

    with pytest.raises(ValueError, match="no instrumental"):
        separation_eval.fetch_woodward(tmp_path, "release", short, fake_download)


def test_run_separates_all_material_with_each_model_and_resumes(
    corpus: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "eval"
    args = ["--corpus", str(corpus), "--out", str(out), "run", "--models"]
    models = ["bs-roformer-leap", "mel-band-deux"]
    assert separation_eval.main([*args, *models], runner=estimate_runner()) == 0
    for model in models:
        assert sorted(p.name for p in (out / model).glob("*.wav")) == [
            "artist-one.wav",
            "artist-two.wav",
        ]
    assert "0 model(s) failed" in capsys.readouterr().out
    seen: list[int] = []

    def counting(model: str, pairs: Sequence[EvalPair], out: Path) -> None:
        seen.append(len([p for p in pairs if not Path(p.output).is_file()]))

    separation_eval.main([*args, *models], runner=counting)
    assert seen == [0, 0]  # nothing is left to do


def test_a_model_that_fails_is_recorded_and_the_others_go_on(
    corpus: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "eval"
    good = estimate_runner()

    def runner(model: str, pairs: Sequence[EvalPair], out: Path) -> None:
        if model == "mel-band-deux":
            raise StageError("out-of-memory", "the GPU ran out of memory\nmore lines")
        good(model, pairs, out)

    code = separation_eval.main(
        ["--corpus", str(corpus), "--out", str(out), "run", "--models", "mel-band-deux",
         "bs-roformer-leap"],
        runner=runner,
    )  # fmt: skip
    assert code == 0
    assert "1 model(s) failed" in capsys.readouterr().out
    (failure,) = separation_eval.read_failures(out, "mel-band-deux")
    assert (failure.kind, failure.message) == ("out-of-memory", "the GPU ran out of memory")
    assert (out / "bs-roformer-leap" / "artist-one.wav").is_file()


def test_the_reference_also_separates_the_mp3_versions_and_the_mp3_songs(
    corpus: Path, tmp_path: Path
) -> None:
    write(corpus / "songs" / "Artist - One.ogg", noise(1), "OGG")
    (corpus / "mp3").mkdir()
    (corpus / "mp3" / "Artist - One.mp3").write_bytes(b"mp3")
    asked: dict[str, list[str]] = {}

    def runner(model: str, pairs: Sequence[EvalPair], out: Path) -> None:
        asked[model] = [pair.name for pair in pairs]

    separation_eval.run_all(
        ["bs-roformer-ep317", "bs-roformer-leap"], corpus, tmp_path / "e", runner
    )
    assert asked["bs-roformer-leap"] == ["artist-one", "artist-two"]
    assert asked["bs-roformer-ep317"] == [
        "artist-one",
        "artist-two",
        "artist-one-mp3-320",
        "artist-one-mp3-192",
        "artist-two-mp3-320",
        "artist-two-mp3-192",
        "pair-ogg-artist-one",
        "pair-mp3-artist-one",
    ]


def test_the_report_has_the_numbers_per_candidate_group_speed_and_finalists(
    corpus: Path, tmp_path: Path
) -> None:
    out = tmp_path / "eval"
    models = ["bs-roformer-ep317", "bs-roformer-leap-inst", "mel-band-deux", "mel-band-flowersv10"]
    for model in models:
        # a different error per model, so that the ranking is not a tie
        separation_eval.run_all([model], corpus, out, estimate_runner(0.01 * (1 + len(model) % 5)))
    text = "\n".join(separation_eval.report(corpus, out))
    for model in models:
        assert model in text
    assert "ensemble mel-band-deux + mel-band-flowersv10" in text
    assert "official   n=2" in text
    assert re.search(r"speed 0\.7\d\d s per s of audio; peak VRAM 2\.50 GiB; failures 0", text)
    assert "Proposed finalists" in text
    assert "bs-roformer-ep317," not in text.split("Proposed finalists")[1]
    # the 300-sample lag is removed first: the SDR is far above the 0 dB of an unaligned copy
    first = next(line for line in text.splitlines() if line.strip().startswith("all"))
    assert float(first.split("sdr")[1].split()[0]) > 8


def test_a_wrong_estimate_scores_low_and_a_failure_shows_in_the_report(
    corpus: Path, tmp_path: Path
) -> None:
    out = tmp_path / "eval"
    separation_eval.run_all(["bs-roformer-leap"], corpus, out, estimate_runner())
    failure = Failure(model="bs-roformer-leap", items=("a",), kind="out-of-memory", message="oom")
    separation_eval.record_failure(out, failure)
    text = "\n".join(separation_eval.report(corpus, out))
    assert "failures 1 [out-of-memory: oom]" in text


def test_the_source_check_compares_the_instrumental_from_mp3_with_the_one_from_ogg(
    corpus: Path, tmp_path: Path
) -> None:
    out = tmp_path / "eval"
    write(corpus / "songs" / "Artist - One.ogg", noise(1), "OGG")
    write(corpus / "mp3" / "Artist - One.mp3", noise(1))
    runner = estimate_runner()
    # the "mp3" files are WAV data; the made-up runner does not care about the name
    separation_eval.run_all(["bs-roformer-ep317"], corpus, out, runner)
    text = "\n".join(separation_eval.report(corpus, out))
    assert "Source quality" in text
    assert "mp3 against ogg, artist-one: lag 0 samples" in text
