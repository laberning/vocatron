"""A second voice in the audio: a line sung over the one before that the backing hears (ADR-0052).

In some songs a second voice sings a different line while the first is still singing, or starts
before it has finished. The separation then often puts the second voice into the backing vocals.
With line times (shifted rails, ADR-0008) every line is heard on its own, in the window of its
line time, on the lead's output and on the backing's output (the same CTC search and confidence
as the alignment): ``hear``. ``choose`` goes through the lines in order and puts a line on the
second voice when all of these hold:

- the backing hears it clearly better than the lead (``BACKING_MARGIN``);
- the lead does not sing it: the lead stem is silent while the line is due (``LEAD_SILENT_SHARE``)
  or the lead hears nothing of it (``LEAD_DEAF``), so the lead is silent or busy with the line
  before;
- it is crowded: its letters come faster than the lines of the song usually do
  (``CROWDED``), which two voices singing at once make them;
- the second voice is free: its last line started long enough ago (``FREE_SHARE``).

The file's second-voice lines (``{&}``, the same time) are kept. Pure NumPy, no randomness.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median
from typing import NamedTuple

import numpy as np

from vocatron.core.alignment.chunks import Emissions
from vocatron.core.alignment.ctc import LogProbs, token_spans, viterbi
from vocatron.core.alignment.tokens import DELIMITER, Transcript, blank_id
from vocatron.core.alignment.voice import VoiceActivity
from vocatron.core.lyrics.document import FIRST_VOICE, SECOND_VOICE, Voice

BACKING_MARGIN = 0.2
"""The backing's confidence must beat the lead's by this much (confidences run from 0 to 1) for a
line to go to the second voice: the backing hears the line clearly better."""
LEAD_SILENT_SHARE = 0.25
"""The lead stem is silent while a line is due when at most this share of the time until the next
line is voiced on it."""
LEAD_DEAF = 0.15
"""The lead hears nothing of a line when its confidence on the lead's output is at most this."""
CROWDED = 1.5
"""A line is crowded when its letters per second of the time until the next line are at least
this many times the song's median."""
FREE_SHARE = 0.65
"""The second voice is free for a line when the line before on it started at least this share of
the song's median line spacing earlier."""
SLOT_SECONDS = 3.0
"""The time a line without a later line gets for its slot."""


@dataclass(frozen=True)
class Hearing:
    """One line heard on the two outputs, inside the window of its line time.

    Attributes:
        due: Where the line is due: its line time, corrected by the offset of the rails.
        lead: The confidence on the lead's output, 0 to 1.
        backing: The confidence on the backing's output, 0 to 1.
        lead_voiced: The share of the line's slot (from ``due`` to the next line's) the lead stem
            is voiced in; ``None`` when the lead's voice is not known.
        letters: How many letters the line has.
        slot: The seconds from ``due`` to the due time of the next line that is later; 0 if no
            line is due later.
    """

    due: float
    lead: float
    backing: float
    lead_voiced: float | None
    letters: int
    slot: float


def confidence(
    matrix: LogProbs,
    targets: Sequence[int],
    blank: int,
    window: tuple[float, float],
    seconds_per_frame: float,
) -> float | None:
    """Search one line's tokens in a window and return how sure the model is of them.

    The confidence is the mean over the tokens of the highest probability the best path gives
    them (0 to 1), as the alignment judges a word.

    Args:
        matrix: The log-probabilities, shaped (frames, vocabulary).
        targets: The tokens of the line (letters and word delimiters, ``build_transcript``).
        blank: The id of the CTC blank.
        window: The first and last second the line may occupy.
        seconds_per_frame: The length of a frame.

    Returns:
        The confidence, or ``None`` if the window is too short for the line.
    """
    first = max(int(window[0] / seconds_per_frame), 0)
    last = min(int(window[1] / seconds_per_frame) + 1, len(matrix))
    try:
        path = viterbi(matrix[first:last], targets, blank)
    except ValueError:
        return None
    spans = token_spans(path, len(targets))
    posterior = np.exp(path.scores)
    peaks = [
        float(posterior[a : b + 1].max()) for a, b in zip(spans.first, spans.last, strict=True)
    ]
    return float(np.mean(peaks))


def letter_targets(transcript: Transcript, delimiter: int, line: int) -> list[int]:
    """Return the tokens of one line's letters, with the delimiters between its words."""
    owners = [word.line for word in transcript.words]
    out: list[int] = []
    for owner, slot in zip(owners, transcript.slots, strict=True):
        if owner != line or slot is None:
            continue
        if out:
            out.append(delimiter)
        out.extend(transcript.targets[slot[0] : slot[1] + 1])
    return out


class Timing(NamedTuple):
    """When a line is due and where it may be.

    Attributes:
        due: The line time corrected by the offset of the rails, in seconds.
        window: The first and last second the line may occupy (``rails.line_windows``).
    """

    due: float
    window: tuple[float, float]


def hear(
    lead: LogProbs,
    emissions: Emissions,
    transcript: Transcript,
    timings: Sequence[Timing | None],
    lead_voice: VoiceActivity | None,
) -> list[Hearing | None]:
    """Hear every line with a line time on the lead and on the backing.

    Args:
        lead: The lead's log-probabilities (the lead stem alone).
        emissions: The emissions with the backing part (its output and the model's vocabulary).
        transcript: The words and targets of all lines.
        timings: The timing of every line, ``None`` for a line without a line time.
        lead_voice: Where the lead stem is voiced, or ``None`` if that is not known.

    Returns:
        One entry per line; ``None`` for a line without a line time, without sound or too long
        for its window.

    Raises:
        ValueError: If the emissions carry no backing part.
    """
    part = emissions.backing
    if part is None:
        raise ValueError("the emissions carry no backing part")
    vocabulary, seconds_per_frame = emissions.vocabulary, emissions.seconds_per_frame
    delimiter = list(vocabulary).index(DELIMITER)
    blank = blank_id(vocabulary)
    dues = [t.due for t in timings if t is not None]
    heard: list[Hearing | None] = []
    for line, timing in enumerate(timings):
        targets = letter_targets(transcript, delimiter, line)
        if timing is None or not targets:
            heard.append(None)
            continue
        scores = [
            confidence(matrix, targets, blank, timing.window, seconds_per_frame)
            for matrix in (lead, part.log_probs)
        ]
        later = [due for due in dues if due > timing.due]
        slot = min(later) - timing.due if later else 0.0
        voiced = (
            None
            if lead_voice is None
            else lead_voice.voiced_fraction(timing.due, timing.due + (slot or SLOT_SECONDS))
        )
        letters = sum(len(word.spoken) for word in transcript.words if word.line == line)
        lead_score, backing_score = scores
        heard.append(
            None
            if lead_score is None or backing_score is None
            else Hearing(timing.due, lead_score, backing_score, voiced, letters, slot)
        )
    return heard


def _usual(hearings: Sequence[Hearing | None]) -> tuple[float, float] | None:
    """Return the song's median letters per second of a slot and its median slot in seconds.

    ``None`` without lines that have a slot.
    """
    slotted = [h for h in hearings if h is not None and h.slot > 0]
    if not slotted:
        return None
    return median(h.letters / h.slot for h in slotted), median(h.slot for h in slotted)


def _wants_second(hearing: Hearing, usual: tuple[float, float]) -> bool:
    """Tell whether the audio says this line is sung by a second voice, free or not.

    The backing hears it clearly better than the lead, the lead does not sing it (silent while
    it is due, or deaf to it), and its slot is crowded.
    """
    density, _ = usual
    silent = hearing.lead_voiced is not None and hearing.lead_voiced <= LEAD_SILENT_SHARE
    sings_elsewhere = silent or hearing.lead <= LEAD_DEAF
    crowded = hearing.slot > 0 and hearing.letters / hearing.slot >= CROWDED * density
    return hearing.backing - hearing.lead >= BACKING_MARGIN and sings_elsewhere and crowded


def choose(hearings: Sequence[Hearing | None], file_voices: Sequence[Voice]) -> list[Voice]:
    """Give every line its voice: the file's second voice stays, the audio adds the rest.

    A line goes to the second voice when ``_wants_second`` and the second voice is free: its
    last line started at least ``FREE_SHARE`` of the song's median slot before. Otherwise it
    stays on the first voice. A line without a hearing stays where the file put it.

    Args:
        hearings: The lines heard, ``None`` for a line that could not be.
        file_voices: The voice of every line from the file (``1`` or ``2``).

    Returns:
        The voice of every line, ``1`` or ``2``.
    """
    voices = list(file_voices)
    usual = _usual(hearings)
    if usual is None:
        return voices
    last = float("-inf")  # when the last line of the second voice was due
    for index, hearing in enumerate(hearings):
        if hearing is None:
            continue
        free = hearing.due - last >= FREE_SHARE * usual[1]
        if voices[index] == FIRST_VOICE and free and _wants_second(hearing, usual):
            voices[index] = SECOND_VOICE
        if voices[index] == SECOND_VOICE:
            last = hearing.due
    return voices
