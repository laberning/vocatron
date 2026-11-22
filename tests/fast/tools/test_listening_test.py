"""Stage 1 tests for ``tools/listening_test.py`` with made-up stems (no real songs, no GPU)."""

import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import listening_test
from fakes.audio import decode_file
from vocatron.core.bench import SongResult, run_of
from vocatron.core.separation.file import STEM_NAMES, SeparationFile, stem_path
from vocatron.core.separation.rules import SAMPLE_RATE
from vocatron.core.stage_file import Fingerprint
from vocatron.lab.separation.listening import ListeningKey

SYSTEMS = ("sys-ref", "sys-mix", "sys-pair")
SONGS = ("Song One", "Song Two")
SECONDS = 16
USED_STEMS = ("lead", "karaoke")


def write_stems(out: Path, system: str, song: str) -> None:
    """Write made-up stems and a separation.json for one system and song.

    Only the stems the tool reads are written (the reference's lead and every karaoke mix), to
    keep the fixture fast.
    """
    folder = listening_test.work_dir(out, system, song)
    (folder / "stems").mkdir(parents=True)
    rng = np.random.default_rng(len(system) + len(song))
    samples = SECONDS * SAMPLE_RATE
    for name in USED_STEMS:
        audio = rng.uniform(-0.3, 0.3, (samples, 2)).astype(np.float32)
        sf.write(folder / stem_path(name), audio, SAMPLE_RATE, subtype="PCM_24")
    file = SeparationFile(
        fingerprint=Fingerprint(inputs={}, settings="x", stage_version=1),
        keep_backing=True,
        models=[],
        stems=[stem_path(name) for name in STEM_NAMES],
        samples=samples,
        sample_rate=SAMPLE_RATE,
        gains={},
        device="cuda",
        seconds=samples / SAMPLE_RATE / (2 if system == SYSTEMS[0] else 4),
        peak_vram_gib=2.0 if system == SYSTEMS[0] else 3.0,
        warnings=[],
    )
    (folder / "separation.json").write_text(file.model_dump_json(), encoding="utf-8")


def fake_prepare(systems: Mapping[str, str], songs: Path, out: Path) -> list[str]:
    for system in systems:
        for song in SONGS:
            write_stems(out, system, song)
    return list(SONGS)


def fake_locate(songs: Path) -> dict[str, Path]:
    found = {}
    for index, song in enumerate(SONGS):
        path = songs / f"{song}.wav"
        sf.write(
            path,
            np.random.default_rng(index)
            .uniform(-0.3, 0.3, (SECONDS * SAMPLE_RATE, 2))
            .astype(np.float32),
            SAMPLE_RATE,
        )
        found[song] = path
    return found


def write_bench(path: Path, median_ms: float) -> None:
    run = run_of({"a": SongResult(status="ok", lines=1, compared=1, errors_ms=[median_ms])})
    path.write_text(run.model_dump_json(), encoding="utf-8")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The built test, shared by the tests of this module: they only read it.

    soundfile decodes the made-up originals instead of ffmpeg (no subprocess in stage 1; the real
    decoder is tested in the engines).
    """
    patch = pytest.MonkeyPatch()
    patch.setattr(listening_test, "decode", decode_file)
    try:
        return build_test(tmp_path_factory)
    finally:
        patch.undo()


def build_test(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Prepare and build the listening test from made-up stems into a fresh folder."""
    tmp_path = tmp_path_factory.mktemp("listening")
    out, songs = tmp_path / "listening", tmp_path / "songs"
    songs.mkdir()
    prepare = [
        "prepare",
        "--systems",
        "sys-ref=model=bs-roformer-ep317",
        "sys-mix=karaoke_input=mix",
    ]
    prepare += ["sys-pair=model=bs-roformer-ep317+bs-roformer-leap"]
    prepare += ["--songs", str(songs), "--out", str(out)]
    assert listening_test.main(prepare, prepare=fake_prepare, locate=fake_locate) == 0
    args = ["build", "--systems", *SYSTEMS, "--songs", str(songs), "--out", str(out)]
    args += ["--seconds", "4", "--passages", "2", "--seed", "5"]
    assert listening_test.main(args, prepare=fake_prepare, locate=fake_locate) == 0
    return out


def key_of(built: Path) -> ListeningKey:
    return ListeningKey.model_validate_json((built / "key.json").read_text("utf-8"))


def test_a_system_is_a_name_and_settings_of_the_separation_stage() -> None:
    assert listening_test.parse_system("a=model=x") == ("a", {"model": "x"})
    assert listening_test.parse_system("b=model=x+y;karaoke_input=mix;karaoke_model=k") == (
        "b",
        {"model": ["x", "y"], "karaoke_input": "mix", "karaoke_model": "k"},
    )
    for bad in ("nosettings", "a=", "a=mood=happy", "=model=x", "a=model="):
        with pytest.raises(ValueError, match="system|setting"):
            listening_test.parse_system(bad)


def test_build_writes_the_page_the_key_and_lossless_clips(built: Path) -> None:
    key = key_of(built)
    assert [p.song for p in key.passages].count("Song One") == 2
    assert len(key.passages) == 4
    clips = sorted(path.name for path in (built / "clips").iterdir())
    assert clips == sorted(f"{clip.id}.flac" for clip in key.clips)
    page = (built / "index.html").read_text("utf-8")
    for secret in (*SYSTEMS, "Song One", "Song Two"):
        assert secret not in page
    assert key.systems == SYSTEMS
    assert len(key.trials) == 2 * (4 * 2 + 4)  # two candidates: 4 passages x 2 orders + 4 identical


def test_the_clips_of_a_passage_have_its_length_and_one_loudness(built: Path) -> None:
    key = key_of(built)
    passage = key.passages[0]
    levels = []
    for clip in key.clips:
        if clip.passage != passage.id:
            continue
        data, rate = sf.read(built / "clips" / f"{clip.id}.flac", dtype="float64")
        assert rate == SAMPLE_RATE
        assert len(data) == round(passage.window.seconds * SAMPLE_RATE)
        levels.append(float(np.sqrt(np.mean(data**2))))
    assert max(levels) == pytest.approx(min(levels), rel=0.05)


def test_the_hidden_identical_clips_are_separate_files_with_the_same_audio(built: Path) -> None:
    key = key_of(built)
    trial = next(t for t in key.trials if t.identical)
    first, _ = sf.read(built / "clips" / f"{trial.a}.flac")
    second, _ = sf.read(built / "clips" / f"{trial.b}.flac")
    assert trial.a != trial.b
    assert np.array_equal(first, second)


def test_the_passages_of_a_song_are_chosen_from_the_reference_lead_stem(built: Path) -> None:
    passages = listening_test.passage_list(
        list(SONGS),
        "sys-ref",
        built,
        listening_test.PassageOptions(count=2, seconds=4, extra=["Song Two@12"]),
    )
    two = [p.window.start for p in passages if p.song == "Song Two"]
    assert 12.0 in two
    with pytest.raises(ValueError, match="no such song"):
        listening_test.passage_list(
            list(SONGS), "sys-ref", built, listening_test.PassageOptions(extra=["Nope@3"])
        )


def judged(built: Path, preferred: str, path: Path) -> Path:
    key = key_of(built)
    items: list[dict[str, object]] = []
    for trial in key.trials:
        if trial.identical or preferred == "tie":
            items.append({"trial": trial.id, "preference": "tie"})
            continue
        winner = trial.candidate if preferred == "cand" else key.reference
        side = "A" if key.system_of(trial.a) == winner else "B"
        items.append({"trial": trial.id, "preference": side, "criteria": {"lead": side}})
    path.write_text(json.dumps({"judgements": items}), encoding="utf-8")
    return path


def run_score(
    built: Path, results: list[Path], bench: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    code = listening_test.main(
        ["score", *map(str, results), "--out", str(built), "--bench", str(bench), "--gpu-gib", "8"]
    )
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_score_reveals_the_key_and_applies_the_rule(
    built: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bench = tmp_path / "bench"
    bench.mkdir()
    write_bench(bench / "baseline.json", 150.0)
    write_bench(bench / "last-sys-mix.json", 140.0)
    code, text = run_score(built, [judged(built, "cand", tmp_path / "r.json")], bench, capsys)
    assert code == 0
    assert "sys-mix against sys-ref:" in text
    assert "judged 8 times: preferred 8, reference preferred 0, cannot tell 0" in text
    assert "4 passages judged in both orders: candidate won both 4" in text
    assert "hidden identical pairs: 4 of 4 judged 'cannot tell'" in text
    assert "criterion lead: candidate better 8, reference better 0" in text
    assert "peak VRAM 3.00 GiB" in text
    assert "0.250 s per s of audio" in text
    assert (
        "[FAIL] preferred in at least 20 of 30 judgements" not in text
    )  # 8 of 8 passes in proportion
    assert "verdict: stays" in text  # the second candidate has no benchmark: its sync check fails
    assert "sys-mix against sys-ref:" in text
    assert text.count("verdict:") == 2


def test_a_reference_that_wins_keeps_the_current_system(
    built: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, text = run_score(built, [judged(built, "ref", tmp_path / "r.json")], tmp_path, capsys)
    assert code == 0
    assert "[FAIL] preferred in at least 20 of 30 judgements" in text
    assert "[FAIL] never clearly worse" in text
    assert "verdict: may become the default" not in text


def test_the_results_of_several_sessions_are_merged(
    built: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    whole = json.loads(judged(built, "tie", tmp_path / "all.json").read_text())["judgements"]
    first, second = tmp_path / "s1.json", tmp_path / "s2.json"
    first.write_text(json.dumps({"judgements": whole[:10]}))
    second.write_text(json.dumps({"judgements": whole[10:]}))
    code, text = run_score(built, [first, second], tmp_path, capsys)
    assert code == 0
    assert "cannot tell 8" in text


def test_incomplete_results_are_an_error_that_counts_what_is_missing(
    built: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    part = tmp_path / "part.json"
    part.write_text(json.dumps({"judgements": [{"trial": "t001", "preference": "A"}]}))
    code, text = run_score(built, [part], tmp_path, capsys)
    assert code == 1
    assert "trials are not judged" in text


def test_speed_and_memory_are_empty_without_separation_files(tmp_path: Path) -> None:
    assert listening_test.speed_and_memory(tmp_path, SYSTEMS[0], ["none"]) == (None, None)
    assert listening_test.read_bench(tmp_path, SYSTEMS[0], SYSTEMS[1]) is None


def test_score_reports_a_missing_or_broken_results_file_as_an_error(
    built: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, text = run_score(built, [tmp_path / "missing.json"], tmp_path, capsys)
    assert code == 1
    assert text.startswith("error:")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert run_score(built, [broken], tmp_path, capsys)[0] == 1
