"""Stage 2: on a real song no sweep starts before its voice or crosses a silence (numbers only).

The song is the one whose highlight was reported to creep in pauses and to look odd in two-voice
parts ("Auf uns" of Andreas Bourani). The benchmark's work folder in ``.corpus/bench/work`` holds
its alignment and stems. The words are measured against the lead stem and the backing stem apart
(``vocatron.lab.alignment.word_voice``): no sweep starts more than 0.3 s before the voice that
sings it (lead or backing), and none crosses a silence of more than 0.5 s in both stems. The
assertion messages carry indices and numbers, never a word (AGENTS.md). No GPU.
"""

from realworld import corpus_path
from vocatron.engines.alignment.analysis import analyse_work_folder
from vocatron.lab.alignment.word_voice import CROSSES, EARLY, NO_VOICE

WORK = "Andreas Bourani - Auf uns"


def test_no_sweep_starts_early_or_crosses_a_silence_on_auf_uns() -> None:
    result = analyse_work_folder(corpus_path("bench", "work", WORK))
    assert result is not None, "the stored work folder has no usable alignment or stems"
    rows, _ = result
    for flag in (NO_VOICE, EARLY, CROSSES):
        indices = [row.index for row in rows if flag in row.flags]
        assert not indices, f"{len(indices)} words flagged {flag}: indices {indices[:20]}"
    silent_on_lead = [row for row in rows if row.lead_share == 0.0]
    assert silent_on_lead, "the song has words only the backing sings"
    assert all(row.backing_share > 0.0 for row in silent_on_lead)
