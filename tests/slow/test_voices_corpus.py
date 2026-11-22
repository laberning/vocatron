"""Stage 2: two voices singing different lines at once, on two real songs (ADR-0052).

"Auf uns" (Andreas Bourani) has a part from its line 53 on in which two voices sing different
lines that overlap, and "Stumblin' In" (Suzi Quatro and Chris Norman) has two lines with the
same ``.lrc`` time. The stems of earlier runs (``.corpus/bench/work`` and ``.corpus/unheard/new``)
are reused, and the lyrics are those of each song's own ``.lrc``. Messages hold numbers only:
line numbers, seconds and counts, never a line of a song (AGENTS.md). The GPU tests follow the
GPU rules of AGENTS.md: a timeout, a capped share of the memory in the worker, half precision
and a log on disk.
"""

import re
import shutil
from pathlib import Path

import pytest
import torch

from fakes.songs import FakeWorld
from realworld import align, corpus_path, lyrics_of, real_config
from vocatron.cli.app import real_engines
from vocatron.core.alignment.file import AlignedLine, AlignmentFile
from vocatron.core.lyrics.document import SECOND_VOICE
from vocatron.core.lyrics.file import LyricsFile
from vocatron.engines.alignment.analysis import analyse_work_folder
from vocatron.stages.batch import run_song
from vocatron.stages.config import Config, LyricsSettings
from vocatron.stages.lyrics import load_lyrics
from vocatron.stages.songs import discover

AUF_UNS = "Andreas Bourani - Auf uns"
STUMBLIN = "Suzi Quatro & Chris Norman - Stumblin' In"
STUMBLIN_WORK = "Chris Norman, Suzi Quatro - Stumblin' In"
OVERLAPPING = range(52, 59)  # lines 53 to 59 of "Auf uns", counted from 0
MAX_ESTIMATED = 1  # of the words of those lines that the model heard (8 before the second voice)
FIRST_VOICE_LINES = (53, 55, 57)  # the first voice's refrain line, from 0 (54, 56, 58 in messages)
HEAD_PLACEMENT = (216.10, 220.06, 224.08)  # seconds where the code before ADR-0052 started them
MAX_NEAR_HEAD = 0.45  # seconds a first-voice line may start from there or from its line time
RUN_AFTER = 0.5  # seconds a run of voice may outlast the lines that overlap it
MAX_LATE = 0.3  # seconds a line may start after its line time plus the offset of the rails
FAR_FROM_PAIR = (7, 26, 35)  # first-voice lines of "Stumblin' In" far from the pair, from 0
TIMEOUT = 900


def aligned(source: Path, stems: Path, output: Path) -> tuple[Path, AlignmentFile, LyricsFile]:
    """Align a song of the corpus with its ``.lrc`` times as hints, on its earlier stems.

    The lyrics stage runs for real; the lead and backing stems are copied from the earlier run.
    Returns the work folder, ``alignment.json`` and ``lyrics.json``.
    """
    config = real_config(output, use_lrc_times=True)
    engines = real_engines()
    (found,) = discover(source, config, engines)
    status = run_song(found, config, engines, force=False, until="lyrics")
    assert status.state in {"ok", "review"}, status.error
    (found.work_dir / "stems").mkdir(parents=True, exist_ok=True)
    for stem in ("lead.flac", "backing.flac"):
        shutil.copy(stems / stem, found.work_dir / "stems" / stem)
    return found.work_dir, align(found, config), lyrics_of(found)


def voices_of(lines: list[AlignedLine]) -> list[int]:
    return [line.voice for line in lines]


def numbers(indices: list[int]) -> str:
    """Line numbers (from 1) for a message."""
    return ", ".join(str(i + 1) for i in indices)


def test_the_lyrics_stage_puts_the_later_line_of_one_time_on_the_second_voice() -> None:
    """On fakes, no GPU: the one pair of lines with the same time in "Stumblin' In"."""
    text = corpus_path("unheard", "in", f"{STUMBLIN}.lrc").read_text(encoding="utf-8")
    world = FakeWorld()
    song = Path("/music/duet.mp3")
    world.add_song(song, lyrics=None)
    world.store.add(song.with_suffix(".lrc"), text.encode("utf-8"))
    config = Config(lyrics=LyricsSettings(language="en"))
    status = run_song(
        world.song(song, config), config, world.engines, force=False, only=("probe", "lyrics")
    )
    assert status.error is None, "the lyrics stage failed"
    lyrics = load_lyrics(world.song(song, config), world.engines)
    assert lyrics is not None
    second = [i for i, line in enumerate(lyrics.lines) if line.voice == SECOND_VOICE]
    assert len(second) == 1, f"{len(second)} lines on the second voice: {numbers(second)}"
    (index,) = second
    assert lyrics.lines[index].time == lyrics.lines[index - 1].time, "not the line of one time"


@pytest.mark.gpu
@pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA GPU")
@pytest.mark.timeout(TIMEOUT)
def test_auf_uns_has_its_overlapping_lines_in_two_voices(tmp_path: Path) -> None:
    work, file, lyrics = aligned(
        corpus_path("listen352", "in", f"{AUF_UNS}.ogg"),
        corpus_path("bench", "work", AUF_UNS, "stems"),
        tmp_path,
    )
    assert file.device == "cuda"
    assert file.rails.kind == "shifted"
    voices = voices_of(file.lines)
    second = [i for i, voice in enumerate(voices) if voice == SECOND_VOICE]
    inside = [i for i in OVERLAPPING if voices[i] == SECOND_VOICE]
    estimated = sum(
        w.estimated
        for i in OVERLAPPING
        if not all(x.estimated for x in file.words if x.line == i)  # not placed at its line time
        for w in file.words
        if w.line == i
    )
    print(
        f"Auf uns: {len(second)} lines on the second voice ({numbers(second)}), "
        f"{len(inside)} of lines 53 to 59, {estimated} of their words estimated"
    )
    assert 3 <= len(inside) < len(OVERLAPPING), "lines 53 to 59 are not split into two voices"
    assert estimated <= MAX_ESTIMATED
    rails = file.rails.offset
    for index, head in zip(FIRST_VOICE_LINES, HEAD_PLACEMENT, strict=True):
        line_time = lyrics.lines[index].time
        assert line_time is not None
        start = file.lines[index].start
        print(
            f"Auf uns: line {index + 1} (first voice) starts at {start:.2f} s, "
            f"{sum(w.estimated for w in file.words if w.line == index)} words estimated, "
            f"{start - (line_time + rails):+.2f} s "
            f"from its line time and {start - head:+.2f} s from where it was placed before"
        )
        assert voices[index] == 1
        assert abs(start - (line_time + rails)) <= MAX_LATE, f"line {index + 1} starts late"
        assert abs(start - head) <= MAX_NEAR_HEAD, f"line {index + 1} is far from the old place"
    for voice in (1, 2):  # within one voice the lines never overlap
        lines = [line for line in file.lines if line.voice == voice]
        assert all(a.end <= b.start + 1e-6 for a, b in zip(lines, lines[1:], strict=False))
    assert len(lyrics.lines) == len(file.lines)
    # no run of voice on either stem lasts longer than the lines that overlap it
    (work / "alignment.json").write_text(file.model_dump_json(), encoding="utf-8")
    result = analyse_work_folder(work)
    assert result is not None, "no plausible voice on the stems"
    _, stems = result
    window = [file.lines[i] for i in OVERLAPPING]
    for begin, stop in stems.either.spans:
        hit = [line for line in window if line.start < stop and line.end > begin]
        if hit:
            late = stop - max(line.end for line in hit)
            assert late <= RUN_AFTER, f"voice sounds {late:.2f} s after the lines at {begin:.1f} s"


@pytest.mark.gpu
@pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA GPU")
@pytest.mark.timeout(TIMEOUT)
def test_the_two_lines_of_one_time_in_stumblin_in_are_two_voices_and_the_next_is_on_time(
    tmp_path: Path,
) -> None:
    _, file, lyrics = aligned(
        corpus_path("unheard", "in", f"{STUMBLIN}.ogg"),
        corpus_path("unheard", "new", STUMBLIN_WORK, "stems"),
        tmp_path,
    )
    assert file.rails.kind == "shifted"
    times = [line.time for line in lyrics.lines]
    (pair,) = [i for i in range(1, len(times)) if times[i] is not None and times[i] == times[i - 1]]
    voices = voices_of(file.lines)
    after = pair + 1
    reference = lyrics.lines[after].time
    assert reference is not None
    late = file.lines[after].start - (reference + file.rails.offset)
    print(
        f"Stumblin' In: lines {pair} and {pair + 1} share a time, voices {voices[pair - 1]} and "
        f"{voices[pair]}; line {after + 1} starts {late:+.2f} s from its line time"
    )
    assert (voices[pair - 1], voices[pair]) == (1, 2)
    assert abs(late) <= MAX_LATE
    for index in (*FAR_FROM_PAIR, pair, after):  # numbers of the pair and the line after
        words = [w for w in file.words if w.line == index]
        start = file.lines[index].start
        print(
            f"Stumblin' In: line {index} (voice {voices[index]}) starts at {start:.2f} s, "
            f"{sum(w.estimated for w in words)} of {len(words)} words estimated"
        )
    for index in FAR_FROM_PAIR:  # a second voice far away does not make them unheard
        words = [w for w in file.words if w.line == index]
        assert voices[index] == 1
        assert not all(w.estimated for w in words), f"line {index} is placed at its line time"


EARLY_LINE = 27  # line 28 of the old ``.lrc`` of "Stumblin' In" (line 34 counting its tags), from 0
EARLY_START = 207.8  # seconds of song time where that line is sung (3:34.5 video time)
MAX_EARLY = 0.5  # seconds a line of the corrected file may start from there (it starts 0.3 s after)


@pytest.mark.gpu
@pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA GPU")
@pytest.mark.timeout(TIMEOUT)
def test_a_line_time_three_seconds_early_is_named_in_the_review_reasons(tmp_path: Path) -> None:
    """The old ``.lrc`` of "Stumblin' In" (``.corpus/early``): the first words of the line sit
    before a silent gap, as the model places them where the line time says."""
    _, file, _ = aligned(
        corpus_path("early", f"{STUMBLIN}.ogg"),
        corpus_path("unheard", "new", STUMBLIN_WORK, "stems"),
        tmp_path,
    )
    start = file.lines[EARLY_LINE].start
    print(
        f"Stumblin' In (early .lrc): line {EARLY_LINE + 1} starts {start - EARLY_START:+.2f} s "
        f"from {EARLY_START} s; {len(file.reasons)} reasons: {file.reasons}"
    )
    assert file.rails.kind == "shifted"
    assert f"line {EARLY_LINE + 1}: its time looks early" in file.reasons


@pytest.mark.gpu
@pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA GPU")
@pytest.mark.timeout(TIMEOUT)
def test_the_corrected_stumblin_in_lrc_does_not_name_the_line_it_corrected(tmp_path: Path) -> None:
    """Line 34 of the corrected ``.lrc`` is line 28 of the old one: sung where its time says."""
    _, file, _ = aligned(
        corpus_path("unheard", "in", f"{STUMBLIN}.ogg"),
        corpus_path("unheard", "new", STUMBLIN_WORK, "stems"),
        tmp_path,
    )
    line = 34  # in the corrected file
    start = file.lines[line - 1].start
    print(f"Stumblin' In: line {line} starts {start - EARLY_START:+.2f} s from {EARLY_START} s")
    assert file.rails.kind == "shifted"
    early = [r.split(":")[0] for r in file.reasons if r.endswith(("looks early", "look early"))]
    assert not [named for named in early if str(line) in re.findall(r"\d+", named)]
    assert abs(start - EARLY_START) <= MAX_EARLY
