"""Stage 2: lines the model does not hear are placed at their line time on a real song (ADR-0027).

The outro of "Cold Heart (PNAU Remix)" (lines 40 to 42) is a sung vowel phrase that the model does
not hear. The stems come from an earlier run of the song in ``.corpus/unheard/new`` (the work
folder keeps them), the lyrics are those of the song's own ``.lrc``. The test reports numbers only,
never a line of the lyrics (AGENTS.md). GPU safety: a timeout, PyTorch capped at 75 % of the memory
inside the worker, half precision, and the log of the run in the work folder, synced after every
line.
"""

import shutil
from pathlib import Path

import pytest
import torch

from realworld import align, corpus_path, lyrics_of, real_config
from vocatron.cli.app import real_engines
from vocatron.core.alignment.file import AlignmentFile
from vocatron.core.lyrics.file import LyricsFile
from vocatron.stages.batch import run_song
from vocatron.stages.songs import discover

COLD_HEART = "Elton John & Dua Lipa - Cold Heart (PNAU Remix)"
WORK_NAME = "Elton John, Dua Lipa, PNAU - Cold Heart - PNAU Remix"
OUTRO_LINES = (40, 41, 42)  # numbered from 1
MAX_OFF = 0.7  # seconds from the .lrc time (the trial gives 0.37 at most)
TIMEOUT = 900

pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA GPU"),
    pytest.mark.timeout(TIMEOUT),
]


def aligned(output: Path, name: str, work_name: str) -> tuple[AlignmentFile, LyricsFile]:
    """Align a song of ``.corpus/unheard`` with its ``.lrc`` times as hints, on its old stems.

    The lyrics stage runs for real; the lead and backing stems are copied from the earlier run.
    """
    config = real_config(output, use_lrc_times=True)
    engines = real_engines()
    (found,) = discover(corpus_path("unheard", "in", f"{name}.ogg"), config, engines)
    status = run_song(found, config, engines, force=False, until="lyrics")
    assert status.state in {"ok", "review"}, status.error
    stems = corpus_path("unheard", "new", work_name, "stems")
    (found.work_dir / "stems").mkdir(parents=True, exist_ok=True)
    for stem in ("lead.flac", "backing.flac"):
        shutil.copy(stems / stem, found.work_dir / "stems" / stem)
    return align(found, config), lyrics_of(found)


def test_the_outro_of_cold_heart_starts_near_its_line_times(tmp_path: Path) -> None:
    file, lyrics = aligned(tmp_path, COLD_HEART, WORK_NAME)
    assert file.device == "cuda"
    assert file.rails.kind == "shifted"
    offsets = []
    for number in OUTRO_LINES:
        reference = lyrics.lines[number - 1].time
        assert reference is not None
        offsets.append(file.lines[number - 1].start - reference)
    print(
        f"Cold Heart: {file.voice.unheard} unheard lines placed, outro line starts "
        + ", ".join(f"{o:+.2f} s" for o in offsets)
        + f" from the .lrc times, estimated {file.quality.estimated_share * 100:.1f} %"
    )
    assert file.voice.unheard >= len(OUTRO_LINES)
    assert all(abs(o) <= MAX_OFF for o in offsets)
