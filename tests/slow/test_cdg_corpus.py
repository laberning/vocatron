"""Stage 2: the CD+G decoder and analysis on the real discs in ``.corpus/cdg`` (robustness).

The discs are copyrighted: the tests report numbers and file names only and never write a
frame. They skip when the folder has no ``.cdg`` file yet. No GPU is used.
"""

from pathlib import Path

import pytest

import cdg_analyse
from realworld import corpus_path


def discs() -> list[tuple[str, Path]]:
    folder = corpus_path("cdg")
    found = [
        (vendor, path)
        for vendor, files in cdg_analyse.vendor_files(folder).items()
        for path in files
    ]
    if not found:
        pytest.skip(f"no .cdg files in the vendor folders of {folder}")
    return found


def test_every_disc_decodes_and_is_analysed_without_errors() -> None:
    for vendor, path in discs():
        label = f"{vendor}/{path.name}"
        analysis = cdg_analyse.analyse_file(path)
        assert analysis.duration > 0, label
        assert analysis.lines, f"{label}: no wiped line found"
        assert 0 < (analysis.lines_per_screen or 0) <= 8, f"{label}: lines per screen"
        assert analysis.wipe_speed is not None, f"{label}: no wipe speed"
