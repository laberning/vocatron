"""The alignment of a song's lyrics: two passes when the lyrics have line times (ADR-0008).

The first pass searches the whole song without hints. If lines carry times of an ``.lrc``, they
are checked against what the first pass found; when they fit up to one offset, the second pass
searches again with every line confined to a window around its corrected time. Hints that break
the order of the lines are dropped first. The second pass is kept only if a path exists. Lines the
model did not hear are then placed at their line times (ADR-0027).

A second voice (ADR-0052) is a second path: the lines of the second voice, from the lyrics file
and found in the audio (``vocatron.core.alignment.voices``), are searched in their own pass on
the backing's output, with windows of their own, so lines of the two voices may overlap in time.
Without a second-voice line there is one path, as before.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import ceil, floor

from vocatron.core.alignment import mix
from vocatron.core.alignment.chunks import Emissions
from vocatron.core.alignment.ctc import CtcPath, LogProbs, Spans, token_spans, viterbi
from vocatron.core.alignment.estimate import (
    MIN_CONFIDENCE,
    Timed,
    confident_spans,
    measure,
    settle,
)
from vocatron.core.alignment.hold import hold_ends
from vocatron.core.alignment.rails import (
    RailCheck,
    check_rails,
    crowded_lines,
    in_order,
    line_windows,
    voice_windows,
)
from vocatron.core.alignment.tokens import Transcript, blank_id, build_transcript, line_of_target
from vocatron.core.alignment.unheard import UnheardLine, forget_late, place_unheard
from vocatron.core.alignment.voice import NO_LOUDNESS, SWITCHED_OFF, Detection, find_voice
from vocatron.core.alignment.voices import Timing, choose, hear
from vocatron.core.languages.base import LanguageModule
from vocatron.core.lyrics.document import FIRST_VOICE, SECOND_VOICE, Voice


@dataclass(frozen=True)
class VoiceReport:
    """What became of the voice activity (ADR-0012, ADR-0013, ADR-0021).

    Attributes:
        detection: What the detection found for the song.
        placed: How many estimated words were placed on the voice.
        re_estimated: How many measured words in silence were estimated instead.
        kept: How many unsure words kept the model's position (ADR-0021).
        held: How many measured words ended later, where the voice stops (ADR-0013).
        held_median: The median move of those ends in seconds (0 without moves).
        unheard: How many lines the model did not hear were placed at their line time (ADR-0027).
    """

    detection: Detection
    placed: int = 0
    re_estimated: int = 0
    kept: int = 0
    held: int = 0
    held_median: float = 0.0
    unheard: int = 0


@dataclass(frozen=True)
class Switches:
    """What the alignment may do beyond the plain search; everything on is the default.

    Attributes:
        voice_activity: Place estimated words where the voice sounds and end measured words
            where it stops, if the emissions carry the loudness and the song's voice is
            plausible (ADR-0012, ADR-0013).
        hear_backing: Where the lead is silent and the backing sounds, align on the backing's
            output instead, if the emissions carry it (ADR-0014). Switched off, without a
            backing part, with a lead voice that is not plausible and without a frame to swap,
            the words are those of the lead alone.
    """

    voice_activity: bool = True
    hear_backing: bool = True


@dataclass(frozen=True)
class Solution:
    """The timed words of a song.

    Attributes:
        transcript: The words.
        words: The time of every word.
        rails: What the check of the line times found.
        frames: The number of frames aligned.
        voice: What became of the voice activity in the pass that gave ``words``.
        backing: What became of the backing vocals in the model's ear (ADR-0014).
        unheard: The lines placed at their line time because the model did not hear them
            (ADR-0027).
        voices: The voice of every line, ``1`` or ``2``; all ``1`` without a second voice.
        found: The indices of the lines the audio put on the second voice (the others of voice 2
            come from the file).
    """

    transcript: Transcript
    words: list[Timed]
    rails: RailCheck
    frames: int
    voice: VoiceReport
    backing: mix.BackingReport
    unheard: tuple[UnheardLine, ...] = ()
    voices: tuple[Voice, ...] = ()
    found: tuple[int, ...] = ()


def line_starts(transcript: Transcript, words: Sequence[Timed]) -> list[float | None]:
    """Return where each line starts: its first word's start (``None`` for a line with no word)."""
    starts: list[float | None] = [None] * transcript.lines
    for word, timed in zip(transcript.words, words, strict=True):
        if starts[word.line] is None:
            starts[word.line] = timed.start
    return starts


def _pass(
    emissions: Emissions,
    transcript: Transcript,
    windows: Sequence[tuple[int, int]] | None,
) -> tuple[CtcPath, Spans]:
    """Run the search once and return the path with the frames of every target."""
    blank = blank_id(emissions.vocabulary)
    path = viterbi(emissions.log_probs, transcript.targets, blank, windows)
    return path, token_spans(path, len(transcript.targets))


def _timed(
    emissions: Emissions,
    transcript: Transcript,
    path: CtcPath,
    spans: Spans,
    settings: tuple[float, bool, Detection | None],
) -> tuple[list[Timed], VoiceReport]:
    """Measure the words on a path, estimate the unreliable ones and end the rest on the voice.

    ``settings`` are the confidence threshold, whether the voice activity is on, and the detection
    of another voice of the song (``None`` to find it): the loudness is the song's, so a second
    voice does not find it again from its few words.
    """
    threshold, voice_activity, known = settings
    measured = measure(transcript, path, spans, emissions.seconds_per_frame)
    weights = [len(word.spoken) for word in transcript.words]
    duration = len(emissions.log_probs) * emissions.seconds_per_frame
    if known is not None:
        detection = known
    elif not voice_activity:
        detection = Detection(None, SWITCHED_OFF)
    elif emissions.loudness is None:
        detection = Detection(None, NO_LOUDNESS)
    else:
        detection = find_voice(
            emissions.loudness, emissions.seconds_per_frame, confident_spans(measured)
        )
    lines = [word.line for word in transcript.words]
    settled = settle(measured, weights, duration, threshold, detection.activity, lines)
    report = VoiceReport(detection, settled.placed, settled.re_estimated, settled.kept)
    if detection.activity is None:
        return settled.words, report
    held = hold_ends(settled.words, detection.activity, emissions.seconds_per_frame)
    return held.words, replace(report, held=held.held, held_median=held.median_move)


def _frame_windows(
    transcript: Transcript, seconds: Sequence[tuple[float, float]], emissions: Emissions
) -> list[tuple[int, int]]:
    """Turn the window of each line into the window of each target, in frames."""
    last = len(emissions.log_probs) - 1
    spf = emissions.seconds_per_frame
    frames = [(max(floor(a / spf), 0), min(ceil(b / spf), last)) for a, b in seconds]
    return [frames[line] for line in line_of_target(transcript)]


@dataclass(frozen=True)
class _Search:
    """What every pass of the second search shares.

    Attributes:
        emissions: The emissions, the lead's matrix already mixed with the backing (ADR-0014).
        transcript: The words of all lines.
        lines: The lyric lines as written.
        module: The language of the song.
        threshold: The confidence below which a word is estimated.
        voice_on: Whether the voice activity is on.
        kept: The hint of every line that stays after the order check.
        offset: The offset of the rails.
    """

    emissions: Emissions
    transcript: Transcript
    lines: Sequence[str]
    module: LanguageModule
    threshold: float
    voice_on: bool
    kept: Sequence[float | None]
    offset: float

    @property
    def duration(self) -> float:
        """The length of the audio in seconds."""
        return len(self.emissions.log_probs) * self.emissions.seconds_per_frame


@dataclass(frozen=True)
class _Second:
    """What the second pass found, all voices together.

    Attributes:
        words: One ``Timed`` per word of the whole transcript, in order.
        voice: What became of the voice activity (the counts of all voices added).
        unheard: The lines placed at their line time.
    """

    words: list[Timed]
    voice: VoiceReport
    unheard: tuple[UnheardLine, ...]


def _add(first: VoiceReport, second: VoiceReport) -> VoiceReport:
    """Add what became of the voice activity in two voices' passes (the first one's detection).

    The median move of the held ends is the average of the two medians, weighted by their counts.
    """
    held = first.held + second.held
    median = (
        (first.held_median * first.held + second.held_median * second.held) / held if held else 0.0
    )
    return replace(
        first,
        placed=first.placed + second.placed,
        re_estimated=first.re_estimated + second.re_estimated,
        kept=first.kept + second.kept,
        held=held,
        held_median=median,
        unheard=first.unheard + second.unheard,
    )


def _voice_pass(
    search: _Search,
    members: Sequence[int],
    rows: LogProbs,
    windows: Sequence[tuple[float, float]],
    known: Detection | None,
    *,
    crowded: frozenset[int],
) -> tuple[list[Timed], VoiceReport, list[UnheardLine]]:
    """Search the lines of one voice on its matrix, confined to their windows, and settle them.

    Args:
        search: What the passes share.
        members: The indices of this voice's lines, ascending.
        rows: The matrix this voice is searched on.
        windows: The window of every line of the song in seconds (``voice_windows``).
        known: The detection of the voice activity of the first voice, or ``None`` to find it.
        crowded: The lines of the song (``crowded_lines``) whose window overlaps one of the other
            voice: of these, those that start long after their line time have taken the other
            voice's words and are placed at their line time instead (``forget_late``).

    Returns:
        The words of this voice's lines in order, what became of the voice activity and the lines
        placed at their line time (numbered as in the whole song).

    Raises:
        ValueError: If there is no path for these lines inside their windows.
    """
    emissions = replace(search.emissions, log_probs=rows)
    transcript = search.transcript
    if len(members) < len(search.lines):
        texts = [search.lines[i] for i in members]
        transcript = build_transcript(texts, search.module, emissions.vocabulary)
    frames = _frame_windows(transcript, [windows[i] for i in members], emissions)
    path, spans = _pass(emissions, transcript, frames)
    words, report = _timed(
        emissions, transcript, path, spans, (search.threshold, search.voice_on, known)
    )
    line_of_word = [word.line for word in transcript.words]
    hints = [search.kept[i] for i in members]
    judged = {k for k, line in enumerate(members) if line in crowded}
    if judged:
        words = forget_late(words, line_of_word, hints, search.offset, judged)
    placed = place_unheard(
        words,
        line_of_word,
        [len(word.spoken) for word in transcript.words],
        hints,
        search.offset,
        report.detection.activity,
    )
    unheard = [replace(line, line=members[line.line]) for line in placed.lines]
    return placed.words, replace(report, unheard=len(unheard)), unheard


def _second_pass(
    search: _Search, voices: Sequence[Voice], rows: Mapping[Voice, LogProbs]
) -> _Second:
    """Run the second pass, one search per voice, and put the words back in the song's order.

    Args:
        search: What the passes share.
        voices: The voice of every line.
        rows: The matrix of every voice.

    Returns:
        The words of the whole transcript.

    Raises:
        ValueError: If a voice has no path inside its windows.
    """
    windows = voice_windows(search.kept, voices, search.offset, search.duration)
    crowded = crowded_lines(windows, voices)
    words: list[Timed | None] = [None] * len(search.transcript.words)
    report: VoiceReport | None = None
    unheard: list[UnheardLine] = []
    for voice in sorted(set(voices)):
        members = [i for i, owner in enumerate(voices) if owner == voice]
        known = None if report is None else report.detection
        found, part, lost = _voice_pass(
            search, members, rows[voice], windows, known, crowded=crowded
        )
        slots = iter(found)
        for index, word in enumerate(search.transcript.words):
            if voices[word.line] == voice:
                words[index] = next(slots)
        report = part if report is None else _add(report, part)
        unheard += lost
    assert report is not None  # a song has lines
    ordered = tuple(sorted(unheard, key=lambda line: line.line))
    return _Second([word for word in words if word is not None], report, ordered)


def _with_audio_voices(
    search: _Search,
    lead: LogProbs,
    confident: Sequence[tuple[float, float]],
    voices: Sequence[Voice],
) -> tuple[list[Voice], tuple[int, ...]]:
    """Add the second-voice lines the audio finds to those of the file (ADR-0052).

    Args:
        search: What the passes share; its emissions carry the backing part.
        lead: The lead's matrix alone, without the backing mixed in.
        confident: The confidently measured words of the first pass, in seconds.
        voices: The voice of every line from the file.

    Returns:
        The voice of every line and the indices of the lines the audio added.
    """
    emissions = search.emissions
    part = emissions.backing
    assert part is not None  # the caller checked
    windows = line_windows(search.kept, search.offset, search.duration)
    timings = [
        None if hint is None else Timing(hint + search.offset, window)
        for hint, window in zip(search.kept, windows, strict=True)
    ]
    voice = find_voice(part.lead_loudness, emissions.seconds_per_frame, confident)
    heard = hear(lead, emissions, search.transcript, timings, voice.activity)
    chosen = choose(heard, voices)
    return chosen, tuple(i for i, (a, b) in enumerate(zip(voices, chosen, strict=True)) if a != b)


@dataclass(frozen=True)
class _Voices:
    """What the second pass made of the song with its voices.

    Attributes:
        second: The words and reports.
        voices: The voice of every line.
        found: The lines the audio put on the second voice.
    """

    second: _Second
    voices: list[Voice]
    found: tuple[int, ...]


def _search_voices(
    search: _Search,
    lead: LogProbs,
    confident: Sequence[tuple[float, float]],
    voices: list[Voice],
    audio: bool,
) -> _Voices | None:
    """Find the voices of the lines and run the second pass on them (ADR-0052).

    The second-voice lines of the file and, with line times that fit (``audio``) and the backing
    heard, those the audio adds are searched in a pass of their own on the backing's output. No
    retry with one voice follows a failed search: with the kept hints in order, every window of two
    voices holds the window the line has with one voice, and each voice's path holds fewer lines,
    so one voice has no path either.

    Args:
        search: What the passes share.
        lead: The lead's matrix alone, without the backing mixed in.
        confident: The confidently measured words of the first pass, in seconds.
        voices: The voice of every line from the file.
        audio: Whether the audio may add second-voice lines.

    Returns:
        The second pass with the voices it ran on, or ``None`` if no path exists inside the
        windows.
    """
    emissions = search.emissions
    found: tuple[int, ...] = ()
    if audio and emissions.backing is not None:
        voices, found = _with_audio_voices(search, lead, confident, voices)
    rows: dict[Voice, LogProbs] = {FIRST_VOICE: emissions.log_probs}
    if SECOND_VOICE in voices:
        rows[SECOND_VOICE] = mix.second_voice_rows(emissions, emissions.log_probs, confident, audio)
    try:
        return _Voices(_second_pass(search, voices, rows), voices, found)
    except ValueError:
        return None


def solve(  # noqa: PLR0913  # the three lists of the lyrics and the settings of one alignment
    emissions: Emissions,
    lines: Sequence[str],
    hints: Sequence[float | None] | None,
    module: LanguageModule,
    threshold: float = MIN_CONFIDENCE,
    switches: Switches = Switches(),  # noqa: B008  # frozen, so sharing the default is safe
    *,
    voices: Sequence[Voice] | None = None,
) -> Solution:
    """Align the lyrics on the emissions.

    Args:
        emissions: What the acoustic model made of the song.
        lines: The lyric lines as written.
        hints: The line times of an ``.lrc`` to check and use; ``None`` to search without.
        module: The language of the song.
        threshold: The confidence below which a word is estimated.
        switches: Which of the voice activity and the hearing of the backing are on.
        voices: The voice of every line from the lyrics file, ``1`` or ``2`` (ADR-0052); ``None``
            for all lines on the first voice. They count only with line times that fit: the
            second voice is searched inside the windows of its line times. With the backing
            heard the audio adds second-voice lines.

    Returns:
        The words with their times and what became of the hints.

    Raises:
        ValueError: If the lyrics have no sound, or do not fit the audio even without hints.
    """
    transcript = build_transcript(lines, module, emissions.vocabulary)
    path, spans = _pass(emissions, transcript, None)
    backing = mix.BackingReport(mix.SWITCHED_OFF)
    swapped = None
    lead = emissions.log_probs
    confident: list[tuple[float, float]] = []
    if switches.hear_backing and emissions.backing is not None:
        confident = confident_spans(measure(transcript, path, spans, emissions.seconds_per_frame))
        mixed = mix.mix_backing(emissions, confident)
        backing = mix.BackingReport(mixed.reason)
        if mixed.frames:
            swapped = mixed.swapped
            emissions = replace(emissions, log_probs=mixed.log_probs)
            path, spans = _pass(emissions, transcript, None)
    elif emissions.backing is not None:
        emissions = replace(emissions, backing=None)  # not heard: no second voice on it either
    voice_on = switches.voice_activity
    words, voice = _timed(emissions, transcript, path, spans, (threshold, voice_on, None))
    rails = RailCheck("none")
    kept: list[float | None] = []
    unheard: tuple[UnheardLine, ...] = ()
    final: list[Voice] = [FIRST_VOICE] * len(lines)
    found: tuple[int, ...] = ()
    if hints is not None:
        starts = line_starts(transcript, words)
        order = in_order(hints, starts)
        kept = order.kept
        rails = replace(check_rails(starts, kept), dropped=order.dropped)
    shifted = rails.rails == "shifted"
    file_voices = list(voices or final)
    if shifted or SECOND_VOICE in file_voices:
        # Without fitting line times the lines of a second voice have no windows: the whole song.
        window = (kept, rails.offset) if shifted else ([None] * len(lines), 0.0)
        search = _Search(emissions, transcript, lines, module, threshold, voice_on, *window)
        result = _search_voices(search, lead, confident, file_voices, shifted)
        if result is not None:
            words, voice, unheard = result.second.words, result.second.voice, result.second.unheard
            final, found = result.voices, result.found
        elif shifted:
            rails = replace(rails, rails="ignored")
    if swapped is not None:
        backing = replace(
            backing,
            frames=int(swapped.sum()),
            words=mix.words_in(swapped, words, emissions.seconds_per_frame),
        )
    frames = len(emissions.log_probs)
    return Solution(transcript, words, rails, frames, voice, backing, unheard, tuple(final), found)
