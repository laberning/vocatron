"""Stage 2: the tempo of the corpus instrumentals (ADR-0022). CPU only, no GPU.

The corpus has no tempo ground truth, so the test checks what can be checked: every song gets a
tempo or "unclear" within the time limit, and for the songs with a clear tempo the estimates on the
first and the second half agree after doubling or halving. It reports numbers and file names only.
"""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from conftest import corpus_dir
from realworld import CLONE, CORPUS_PAGE, tempo_ratio
from vocatron.core.tempo import SAMPLE_RATE, Tempo, estimate_tempo
from vocatron.engines.audio import FfmpegAudioReader
from vocatron.engines.files import FileLog

WORK_FOLDERS = ("bench/work", "songs-en-work")  # the work folders of earlier runs hold the stems
MAX_SECONDS = 2.0  # for a 4-minute song on the CPU
AGREEMENT = 0.03
MIN_AGREEING = 0.75  # of the songs with a clear tempo
LONG_SONG = 240.0  # seconds: the limit is for a song of this length


@pytest.fixture(scope="module")
def log() -> Iterator[FileLog]:
    folder = CLONE / ".cache" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    sink = FileLog(folder / "stage2-tempo.log")
    yield sink
    sink.close()


def stems() -> list[Path]:
    root = corpus_dir()
    if not root.is_dir():
        pytest.skip(f"needs the local corpus {root}; see {CORPUS_PAGE}")
    found = sorted(
        stem
        for folder in WORK_FOLDERS
        if (root / folder).is_dir()
        for stem in (root / folder).glob("*/stems/instrumental.flac")
    )
    if not found:
        pytest.skip(
            f"no instrumental stems in {', '.join(WORK_FOLDERS)} of {root}; see {CORPUS_PAGE}"
        )
    return found


def test_every_song_gets_a_tempo_or_unclear_in_time_and_the_halves_agree(log: FileLog) -> None:
    reader = FfmpegAudioReader()
    clear: list[tuple[str, Tempo]] = []
    agreeing: list[str] = []
    slowest = 0.0
    for stem in stems():
        name = stem.parent.parent.name
        samples = reader.read(stem, SAMPLE_RATE, 1)[0]
        started = time.monotonic()
        whole = estimate_tempo(samples)
        seconds = time.monotonic() - started
        length = samples.shape[0] / SAMPLE_RATE
        slowest = max(slowest, seconds * LONG_SONG / length)
        log.write(f"{name}: {whole.bpm} BPM, clarity {whole.clarity:.2f}, {seconds:.2f} s")
        assert seconds * LONG_SONG / length < MAX_SECONDS, (
            f"{name}: {seconds:.2f} s for {length:.0f} s"
        )
        if whole.bpm is None:
            continue
        clear.append((name, whole))
        half = samples.shape[0] // 2
        first, second = estimate_tempo(samples[:half]), estimate_tempo(samples[half:])
        if first.bpm is not None and second.bpm is not None:
            difference = tempo_ratio(first.bpm, second.bpm)
            log.write(f"{name}: halves {first.bpm} / {second.bpm} BPM, {difference:.1%} apart")
            if difference <= AGREEMENT:
                agreeing.append(name)
    log.write(f"{len(clear)} of {len(stems())} songs have a clear tempo; {len(agreeing)} agree")
    log.write(f"slowest estimate scaled to {LONG_SONG:.0f} s: {slowest:.2f} s")
    assert clear, "no song of the corpus has a clear tempo"
    assert len(agreeing) / len(clear) >= MIN_AGREEING, (
        f"only {len(agreeing)} of {len(clear)} songs agree between their halves"
    )
