"""Measuring a finished song again with the stems apart (the diagnosis of the word voices).

Reads ``alignment.json`` and the lead and backing stems of a work folder with ffmpeg and hands
the loudness to ``vocatron.lab.alignment.word_voice``. Used by ``tools/word_voice.py`` and by the
stage 2 test of the corpus; no ``vocatron`` command runs it.
"""

from pathlib import Path

import numpy as np

from vocatron.core.alignment.chunks import SAMPLE_RATE, SILENCE_DB, frame_loudness, sum_waves
from vocatron.core.alignment.file import AlignmentFile
from vocatron.core.alignment.voice import VoiceActivity, find_voice
from vocatron.engines.audio import decode
from vocatron.lab.alignment.word_voice import (
    StemVoices,
    WordRow,
    WordTime,
    confident_words,
    stem_voices,
    word_rows,
)

ALIGNMENT_FILE = "alignment.json"
LEAD_STEM = Path("stems/lead.flac")
BACKING_STEM = Path("stems/backing.flac")


def analyse_work_folder(folder: Path) -> tuple[list[WordRow], StemVoices] | None:
    """Measure the voice under every word of the song in a work folder.

    Args:
        folder: The work folder (``alignment.json`` and ``stems/``).

    Returns:
        The rows and the voices by stem, or ``None`` if the alignment or a stem is missing or
        invalid, or the lead's voice is not plausible.
    """
    try:
        alignment = AlignmentFile.model_validate_json((folder / ALIGNMENT_FILE).read_text())
    except OSError, ValueError:
        return None
    if not (folder / LEAD_STEM).exists() or not (folder / BACKING_STEM).exists():
        return None
    lead = decode(str(folder / LEAD_STEM), SAMPLE_RATE, 1)[0]
    backing = decode(str(folder / BACKING_STEM), SAMPLE_RATE, 1)[0]
    lead_loudness = frame_loudness(lead)
    backing_loudness = frame_loudness(backing)[: len(lead_loudness)]
    short = len(lead_loudness) - len(backing_loudness)
    if short > 0:
        quiet = np.full(short, SILENCE_DB, dtype=np.float32)
        backing_loudness = np.concatenate((backing_loudness, quiet))
    words = [
        WordTime(
            w.line,
            w.start,
            w.end,
            w.heard_end,
            w.confidence,
            w.estimated,
            alignment.lines[w.line].voice,
        )
        for w in alignment.words
    ]
    confident = confident_words(words)
    spf = alignment.seconds_per_frame
    voices = stem_voices(lead_loudness, backing_loudness, spf, confident)
    if voices is None:
        return None
    mixed: VoiceActivity | None = find_voice(
        frame_loudness(sum_waves(lead, backing)), spf, confident
    ).activity
    return word_rows(words, voices, mixed), voices
