"""Stage 1 tests for ``tools/bench_accept.py``."""

import os
import subprocess
from pathlib import Path

import pytest

import bench_accept


def corpus_with(tmp_path: Path) -> Path:
    (tmp_path / "bench").mkdir()
    return tmp_path


def test_german_copies_last_json_to_baseline_json(tmp_path: Path) -> None:
    corpus = corpus_with(tmp_path)
    (corpus / "bench" / "last.json").write_text("german")
    (corpus / "bench" / "last-en.json").write_text("english")
    ok, message = bench_accept.accept(corpus, "de")
    assert ok
    assert message == f"accepted {corpus / 'bench' / 'last.json'} as the baseline"
    assert (corpus / "bench" / "baseline.json").read_text() == "german"
    assert not (corpus / "bench" / "baseline-en.json").exists()


def test_english_has_its_own_files_and_leaves_the_german_baseline_alone(tmp_path: Path) -> None:
    corpus = corpus_with(tmp_path)
    (corpus / "bench" / "last-en.json").write_text("english")
    (corpus / "bench" / "baseline.json").write_text("old german")
    assert bench_accept.accept(corpus, "en")[0]
    assert (corpus / "bench" / "baseline-en.json").read_text() == "english"
    assert (corpus / "bench" / "baseline.json").read_text() == "old german"


def test_a_missing_last_run_names_the_command_to_run(tmp_path: Path) -> None:
    corpus = corpus_with(tmp_path)
    assert bench_accept.accept(corpus, "de") == (
        False,
        f"no {corpus / 'bench' / 'last.json'}: run 'make bench' first",
    )
    ok, message = bench_accept.accept(corpus, "en")
    assert not ok
    assert message.endswith("run 'make bench LANGUAGE=en' first")


def test_an_unsupported_language_is_refused(tmp_path: Path) -> None:
    ok, message = bench_accept.accept(corpus_with(tmp_path), "fr")
    assert not ok
    assert message == "unsupported language 'fr'; supported: de, en"


def test_main_prints_and_returns_the_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    corpus = corpus_with(tmp_path)
    assert bench_accept.main(["--corpus", str(corpus)]) == 1
    assert "make bench' first" in capsys.readouterr().out
    (corpus / "bench" / "last.json").write_text("x")
    assert bench_accept.main(["de", "--corpus", str(corpus)]) == 0


ROOT = Path(__file__).resolve().parents[3]


def dry_run(target: str, *args: str, env_language: str | None = None) -> str:
    """Return the commands ``make`` would run for ``target`` (nothing runs)."""
    env = {k: v for k, v in os.environ.items() if k not in {"LANGUAGE", "MAKEFLAGS", "MFLAGS"}}
    if env_language is not None:
        env["LANGUAGE"] = env_language
    done = subprocess.run(
        ["make", "-n", "-C", str(ROOT), target, *args],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return done.stdout


@pytest.mark.parametrize(
    ("target", "variable", "reader"),
    [
        ("bench", "VOCATRON_BENCH_LANGUAGE", "tests/bench/test_sync.py"),
        ("demo-accept", "VOCATRON_DEMO_LANGUAGE", "tests/slow/test_demo_real.py"),
    ],
)
def test_the_language_of_the_command_line_reaches_the_test_under_the_name_it_reads(
    target: str, variable: str, reader: str
) -> None:
    assert f'"{variable}"' in (ROOT / reader).read_text(encoding="utf-8")
    # A code that is no default of any target, so only the command line can have put it there.
    assert f"{variable}=xx " in dry_run(target, "LANGUAGE=xx")
    # The LANGUAGE of the environment is a locale setting, never a choice of the benchmark.
    assert f"{variable}=xx " not in dry_run(target, env_language="xx")


def test_bench_accept_takes_the_language_of_the_command_line_only() -> None:
    assert "bench_accept.py en " in dry_run("bench-accept", "LANGUAGE=en")
    assert "bench_accept.py de " in dry_run("bench-accept", env_language="en")
