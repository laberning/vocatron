"""Stage 1 tests for ``tools/cdg_analyse.py`` on a synthetic disc."""

from pathlib import Path

import pytest

import cdg_analyse
from fakes.cdg import classic_song


def make_folder(tmp_path: Path) -> Path:
    stream, _ = classic_song()
    vendor = tmp_path / "Vendor A" / "sub"
    vendor.mkdir(parents=True)
    (vendor / "one.cdg").write_bytes(stream)
    (vendor / "two.CDG").write_bytes(stream[: len(stream) // 2])
    (tmp_path / "Empty").mkdir()
    (tmp_path / "stray.cdg").write_bytes(stream)  # not in a vendor folder
    return tmp_path


def test_vendor_folders_with_cdg_files_are_found(tmp_path: Path) -> None:
    found = cdg_analyse.vendor_files(make_folder(tmp_path))
    assert list(found) == ["Vendor A"]
    assert [p.name for p in found["Vendor A"]] == ["one.cdg", "two.CDG"]


def test_the_report_has_a_block_per_song_and_per_vendor(tmp_path: Path) -> None:
    report = cdg_analyse.build_report(make_folder(tmp_path))
    assert "song sub/one.cdg: 50.0 s, 3 wiped lines" in report
    assert "vendor Vendor A: 2 songs" in report
    assert "alignment: centred" in report
    assert "countdown: 4 ticks every 1.00 s" in report
    assert "BREAK" in report


def test_a_folder_without_discs_says_so(tmp_path: Path) -> None:
    assert "no .cdg files" in cdg_analyse.build_report(tmp_path)


def test_main_prints_and_writes_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = make_folder(tmp_path)
    assert cdg_analyse.main([str(folder)]) == 0
    assert "vendor Vendor A" in capsys.readouterr().out
    assert "vendor Vendor A" in (folder / "report.txt").read_text()
    assert cdg_analyse.main([str(tmp_path / "missing")]) == 1


def test_tile_maps_are_printed_at_given_times_and_along_a_timeline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = make_folder(tmp_path)
    assert cdg_analyse.main([str(folder), "--tilemap", "one", "--at", "3,9"]) == 0
    out = capsys.readouterr().out
    assert "t=   3.00 s" in out and "t=   9.00 s" in out
    assert cdg_analyse.timeline("1,2,0.5") == [1.0, 1.5, 2.0]
    assert cdg_analyse.main([str(folder), "--tilemap", "one", "--timeline", "0,10,5"]) == 0
    assert cdg_analyse.main([str(folder), "--tilemap", "nope", "--at", "3"]) == 1
    assert cdg_analyse.main([str(folder), "--tilemap", "one"]) == 1
