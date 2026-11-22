"""The ``alignment`` stage: when is every word sung (ADR-0002, ADR-0005, ADR-0008).

It aligns the lyrics on the lead vocals (and the backing vocals where the lead is silent,
ADR-0014) with the language module's model. The acoustic model is
an engine (a child process on the GPU); everything that decides is in ``vocatron.core.alignment``.
The line times of an ``.lrc`` are checked against the singing and used as guide rails only if
they fit. The quality report feeds the song status.
"""

from typing import Literal, override

from pydantic import BaseModel

from vocatron.core import quality
from vocatron.core.alignment import chunks, estimate, hold, rails, unheard, voice, voices
from vocatron.core.alignment.estimate import LETTER_SECONDS, MIN_CONFIDENCE
from vocatron.core.alignment.file import (
    AlignedLine,
    AlignedWord,
    AlignmentFile,
    BackingUsed,
    DroppedHint,
    RailsUsed,
    VoiceUsed,
)
from vocatron.core.alignment.job import OVERLAP_SECONDS, PIECE_SECONDS, AcousticSetup
from vocatron.core.alignment.solve import Solution, Switches, line_starts, solve
from vocatron.core.errors import StageError
from vocatron.core.languages import DEFAULT_LANGUAGE, LANGUAGES
from vocatron.core.languages.base import LanguageModule
from vocatron.core.lyrics.document import FIRST_VOICE, SECOND_VOICE, format_time
from vocatron.core.lyrics.file import LyricsFile
from vocatron.core.models import ModelPin, find_model
from vocatron.core.separation.file import stem_path
from vocatron.core.stage_file import Fingerprint, StageFile
from vocatron.engines.protocols import AcousticRequest, Heard
from vocatron.stages.config import AlignmentSettings, Config
from vocatron.stages.lyrics import LYRICS_FILE, load_lyrics
from vocatron.stages.models import ModelFolder
from vocatron.stages.report import read_model
from vocatron.stages.stage import LOG_FILE, Engines, Song, StageContext, TypedStage

ALIGNMENT_STAGE = "alignment"
ALIGNMENT_FILE = "alignment.json"
MAX_LISTED = 20  # line numbers the log names for the second voice
LEAD_STEM = stem_path("lead")
BACKING_STEM = stem_path("backing")


class RailParameters(BaseModel):
    """The numbers of the rails check, as the fingerprint sees them."""

    max_spread: float = rails.MAX_SPREAD
    near: float = rails.NEAR
    min_near_share: float = rails.MIN_NEAR_SHARE
    margin: float = rails.MARGIN
    min_lines: int = rails.MIN_LINES


class SplitParameters(BaseModel):
    """The numbers that name a line whose time looks early, as the fingerprint sees them (ADR-0053).

    They are named constants in ``vocatron.core.quality``.
    """

    gap: float = quality.SPLIT_GAP
    confidence: float = quality.SPLIT_CONFIDENCE
    silent: float = quality.SPLIT_SILENT


class VoiceParameters(BaseModel):
    """The numbers of the voice activity and the placement on it, as the fingerprint sees them.

    They are named constants in ``vocatron.core.alignment.voice`` and ``estimate``, and the loudness
    of digital silence in ``chunks`` (ADR-0012, ADR-0021); the maximum hold is in ``hold``
    (ADR-0013) and the placement of unheard lines in ``unheard`` (ADR-0027).
    """

    silence_db: float = chunks.SILENCE_DB
    voice_percentile: float = voice.VOICE_PERCENTILE
    voice_margin_db: float = voice.VOICE_MARGIN_DB
    floor_percentile: float = voice.FLOOR_PERCENTILE
    floor_margin_db: float = voice.FLOOR_MARGIN_DB
    min_contrast_db: float = voice.MIN_CONTRAST_DB
    min_voiced_share: float = voice.MIN_VOICED_SHARE
    max_voiced_share: float = voice.MAX_VOICED_SHARE
    min_confident_seconds: float = voice.MIN_CONFIDENT_SECONDS
    confident_word: float = voice.CONFIDENT_WORD
    close_hole_seconds: float = voice.CLOSE_HOLE_SECONDS
    min_voiced_seconds: float = voice.MIN_VOICED_SECONDS
    min_letter_seconds: float = estimate.MIN_LETTER_SECONDS
    max_letter_seconds: float = estimate.MAX_LETTER_SECONDS
    edge_reach_seconds: float = estimate.EDGE_REACH_SECONDS
    held_tail_seconds: float = estimate.HELD_TAIL_SECONDS
    min_fill_share: float = estimate.MIN_FILL_SHARE
    keep_voiced_share: float = estimate.KEEP_VOICED_SHARE
    keep_next_seconds: float = estimate.KEEP_NEXT_SECONDS
    keep_direct_seconds: float = estimate.KEEP_DIRECT_SECONDS
    silent_confidence: float = estimate.SILENT_CONFIDENCE
    silent_share: float = estimate.SILENT_SHARE
    min_judged_seconds: float = estimate.MIN_JUDGED_SECONDS
    max_hold_seconds: float = hold.MAX_HOLD_SECONDS
    snap_seconds: float = unheard.SNAP_SECONDS
    after_previous_seconds: float = unheard.AFTER_PREVIOUS_SECONDS
    open_end_seconds: float = unheard.OPEN_END_SECONDS
    late_seconds: float = unheard.LATE_SECONDS


class SecondVoiceParameters(BaseModel):
    """The numbers of the second voice, as the fingerprint sees them (ADR-0052).

    They are named constants in ``vocatron.core.alignment.voices`` and ``rails``.
    """

    backing_margin: float = voices.BACKING_MARGIN
    lead_silent_share: float = voices.LEAD_SILENT_SHARE
    lead_deaf: float = voices.LEAD_DEAF
    crowded: float = voices.CROWDED
    free_share: float = voices.FREE_SHARE
    slot_seconds: float = voices.SLOT_SECONDS
    reach: float = rails.REACH
    slot_reach: float = rails.SLOT_REACH


class Pinned(BaseModel):
    """The settings the alignment depends on.

    Attributes:
        model: The acoustic model with its pin.
        piece_seconds: The length of the pieces the model sees.
        overlap_seconds: How much consecutive pieces share.
        min_confidence: The confidence below which a word is estimated.
        letter_seconds: The length assumed for a letter at the edges of a song.
        rails: The numbers of the rails check.
        voice: The numbers of the voice activity.
        second_voice: The numbers of the second voice.
        split: The numbers of the lines whose time looks early.
        use_lrc_times: Whether line times of an ``.lrc`` are used.
        voice_activity: Whether estimated words are placed where the voice sounds.
        voice_source: Whether the loudness is measured on the lead vocals or on lead and backing.
        hear_backing: Whether the model also hears the backing where the lead is silent.
    """

    model: ModelPin
    piece_seconds: float = PIECE_SECONDS
    overlap_seconds: float = OVERLAP_SECONDS
    min_confidence: float = MIN_CONFIDENCE
    letter_seconds: float = LETTER_SECONDS
    rails: RailParameters = RailParameters()
    voice: VoiceParameters = VoiceParameters()
    second_voice: SecondVoiceParameters = SecondVoiceParameters()
    split: SplitParameters = SplitParameters()
    use_lrc_times: bool
    voice_activity: bool
    voice_source: Literal["lead", "vocals"]
    hear_backing: bool


def module_of(language: str) -> LanguageModule:
    """Return the language module for ``language``.

    Raises:
        StageError: ``unsupported-language`` if Vocatron has no module for it.
    """
    try:
        return LANGUAGES[language]
    except KeyError:
        raise StageError("unsupported-language", f"no language module for {language!r}") from None


def _module_of_song(ctx: StageContext, config: Config) -> LanguageModule:
    """Return the module of the language of the song's lyrics.

    The language is the one in the song's ``lyrics.json``; where there is none yet (or it is
    invalid) it is the configured language, else the default. This never raises for a missing
    file: the batch plans a song before its lyrics stage has run, and the missing input already
    makes the alignment not current then.
    """
    lyrics = load_lyrics(ctx.song, ctx.engines)
    return module_of(lyrics.language if lyrics else config.lyrics.language or DEFAULT_LANGUAGE)


class AlignmentStage(TypedStage[AlignmentSettings]):
    """Finds when every word of the lyrics is sung."""

    name = ALIGNMENT_STAGE
    # 10: a second voice in a path of its own, `voice` of every line (ADR-0052, alignment.json v8);
    # first-voice lines far after their line time count as unheard while a second voice sings,
    # 11: only those whose window overlaps a second-voice line's
    # 12: a line whose first words sit before a silent gap is named as time looks early (ADR-0053)
    # 13: a second-voice line far after its line time counts as unheard as well (ADR-0054)
    version = 13
    inputs = (LYRICS_FILE, LEAD_STEM, BACKING_STEM)
    output = ALIGNMENT_FILE
    output_model = AlignmentFile

    def settings_from(self, config: Config) -> AlignmentSettings:
        """Return the ``alignment`` section."""
        return config.alignment

    @override
    def declared_settings(self, ctx: StageContext, config: Config) -> BaseModel:
        """Return the model pin, the numbers of the search and the switches.

        The model is that of the song's language. The switches are ``use_lrc_times``,
        ``voice_activity``, ``voice_source`` and ``hear_backing``.

        Device and timeouts do not change the result and are left out.

        Raises:
            StageError: ``unsupported-language`` if the language has no module.
        """
        model = find_model(_module_of_song(ctx, config).model).pin()
        return Pinned(
            model=model,
            use_lrc_times=config.alignment.use_lrc_times,
            voice_activity=config.alignment.voice_activity,
            voice_source=config.alignment.voice_source,
            hear_backing=config.alignment.hear_backing,
        )

    @override
    def required_models(self, ctx: StageContext, config: Config) -> tuple[str, ...]:
        """Return the model of the song's language (see ``_module_of_song``)."""
        return (_module_of_song(ctx, config).model,)

    def run(
        self, ctx: StageContext, settings: AlignmentSettings, fingerprint: Fingerprint
    ) -> StageFile:
        """Align the lyrics and write ``alignment.json``.

        Raises:
            StageError: If ``lyrics.json`` is missing, the language has no module, the acoustic
                model fails (``alignment-failed``, ``alignment-timeout``, ``out-of-memory``,
                ``no-gpu``, ``vram-too-small``), or the lyrics cannot be aligned.
        """
        lyrics = load_lyrics(ctx.song, ctx.engines)
        if lyrics is None:
            raise StageError("missing-input", f"{LYRICS_FILE} is missing or invalid")
        module = module_of(lyrics.language)
        heard = self._hear(ctx, settings, module)
        solution = _solve(lyrics, heard, settings, module)
        ctx.log(
            f"alignment: {len(solution.words)} words on {solution.frames} frames, rails "
            f"{solution.rails.rails}, {heard.result.seconds:.1f} s on {heard.result.device}"
        )
        ctx.log(_voice_line(solution, settings))
        ctx.log(_backing_line(solution))
        ctx.log(_voices_line(solution))
        for hint in _dropped(lyrics, solution):
            ctx.log(f"alignment: warning: {rails.skipped_note(hint.line, hint.time)}")
        return _file(fingerprint, lyrics, solution, heard, module)

    @staticmethod
    def _hear(ctx: StageContext, settings: AlignmentSettings, module: LanguageModule) -> Heard:
        """Run the acoustic model on the lead vocals."""
        spec = find_model(module.model)
        folder = ModelFolder(ctx.models_dir, ctx.engines.store)
        song = ctx.song
        request = AcousticRequest(
            audio=song.work_dir / LEAD_STEM,
            work_dir=song.work_dir,
            log_path=song.work_dir / LOG_FILE,
            log=ctx.log,
            duration=song.tags.duration if song.tags is not None else None,
            device=settings.device,
            timeout_factor_gpu=settings.timeout_factor_gpu,
            timeout_factor_cpu=settings.timeout_factor_cpu,
            model=AcousticSetup(
                name=spec.name,
                revision=spec.revision,
                folder=str(folder.path_of(spec)),
                precision=str(spec.inference["precision"]),
            ),
            backing=song.work_dir / BACKING_STEM
            if settings.voice_source == "vocals" or settings.hear_backing
            else None,
            sum_backing=settings.voice_source == "vocals",
            hear_backing=settings.hear_backing,
            piece_seconds=PIECE_SECONDS,
            overlap_seconds=OVERLAP_SECONDS,
            watch=ctx.watch,
        )
        return ctx.engines.acoustic.log_probs(request)


def _solve(
    lyrics: LyricsFile, heard: Heard, settings: AlignmentSettings, module: LanguageModule
) -> Solution:
    """Align the lyrics on the emissions; the line times are hints if the setting allows."""
    times = [line.time for line in lyrics.lines]
    hints = times if settings.use_lrc_times and any(t is not None for t in times) else None
    try:
        return solve(
            heard.emissions,
            [line.text for line in lyrics.lines],
            hints,
            module,
            switches=Switches(settings.voice_activity, settings.hear_backing),
            voices=[line.voice for line in lyrics.lines],
        )
    except ValueError as error:
        raise StageError("alignment-failed", f"the lyrics cannot be aligned: {error}") from error


def _voice_line(solution: Solution, settings: AlignmentSettings) -> str:
    """Return the log line about the voice activity; a fallback says why."""
    report = solution.voice
    if report.detection.activity is not None:
        return (
            f"alignment: voice activity used: {report.placed} estimated words placed on the "
            f"voice, {report.kept} unsure words kept at the model's position, "
            f"{report.re_estimated} measured words in silence estimated instead, "
            f"{report.unheard} unheard lines placed at their line time, "
            f"{report.held} word ends held to the end of the voice (median "
            f"{report.held_median:.2f} s)"
        )
    if not settings.voice_activity:
        return "alignment: voice activity is switched off"
    return (
        f"alignment: voice activity not used ({report.detection.reason}); estimated words share "
        "the time between their neighbours"
    )


def _backing_line(solution: Solution) -> str:
    """Return the log line about the backing vocals; it says why not when none was used."""
    report = solution.backing
    if report.frames:
        return (
            f"alignment: backing vocals heard in {report.frames} frames where the lead is "
            f"silent, {report.words} measured words in them"
        )
    return f"alignment: backing vocals not heard ({report.reason})"


def _voices_line(solution: Solution) -> str:
    """Return the log line about the second voice (ADR-0052): how many lines and from where."""
    second = [i + 1 for i, voice in enumerate(solution.voices) if voice == SECOND_VOICE]
    if not second:
        return "alignment: one voice"
    heard = [i + 1 for i in solution.found]
    return (
        f"alignment: second voice sings {len(second)} lines "
        f"(numbers {quality.listed(second, MAX_LISTED)}), "
        f"{len(heard)} found in the audio (numbers {quality.listed(heard, MAX_LISTED)})"
    )


def load_alignment(song: Song, engines: Engines) -> AlignmentFile | None:
    """Return the ``alignment.json`` of a song, or ``None`` if it is missing or invalid."""
    try:
        return read_model(engines.store, song.work_dir / ALIGNMENT_FILE, AlignmentFile)
    except ValueError:
        return None


def _dropped(lyrics: LyricsFile, solution: Solution) -> list[DroppedHint]:
    """Return the hints that were dropped for breaking the order, with their time tags."""
    return [
        DroppedHint(line=index + 1, time=format_time(lyrics.lines[index].time or 0.0))
        for index in solution.rails.dropped
    ]


def _file(
    fingerprint: Fingerprint,
    lyrics: LyricsFile,
    solution: Solution,
    heard: Heard,
    module: LanguageModule,
) -> AlignmentFile:
    """Build ``alignment.json`` from the solution."""
    words = [
        AlignedWord(
            line=word.line,
            text=word.text,
            spoken=word.spoken,
            start=timed.start,
            end=timed.end,
            confidence=timed.confidence,
            estimated=timed.estimated,
            letters=list(timed.letters),
        )
        for word, timed in zip(solution.transcript.words, solution.words, strict=True)
    ]
    report = quality.report(words)
    check = solution.rails
    reasons = quality.reasons(report)
    reasons += quality.unheard_reasons(solution.unheard, solution.voice.detection.activity)
    reasons += quality.split_reasons(words, solution.voice.detection.activity)
    if check.rails == "ignored":
        reasons.insert(0, quality.NOT_FITTING)
    result = heard.result
    return AlignmentFile(
        fingerprint=fingerprint,
        reasons=reasons,
        language=lyrics.language,
        model=module.model,
        revision=find_model(module.model).revision,
        rails=RailsUsed(
            kind=check.rails,
            offset=check.offset,
            compared=check.compared,
            spread=check.spread,
            near=check.near,
            dropped=_dropped(lyrics, solution),
        ),
        words=words,
        lines=_lines(solution, words),
        quality=report,
        voice=VoiceUsed(
            used=solution.voice.detection.activity is not None,
            reason=solution.voice.detection.reason,
            threshold_db=solution.voice.detection.threshold_db,
            voiced_share=solution.voice.detection.voiced_share,
            placed=solution.voice.placed,
            re_estimated=solution.voice.re_estimated,
            kept=solution.voice.kept,
            unheard=solution.voice.unheard,
            held=solution.voice.held,
            held_median=solution.voice.held_median,
        ),
        backing=BackingUsed(
            used=solution.backing.frames > 0,
            reason=solution.backing.reason,
            frames=solution.backing.frames,
            words=solution.backing.words,
        ),
        frames=solution.frames,
        seconds_per_frame=heard.emissions.seconds_per_frame,
        device=result.device,
        seconds=result.seconds,
        peak_vram_gib=result.peak_vram_gib,
        warnings=result.warnings,
    )


def _lines(solution: Solution, words: list[AlignedWord]) -> list[AlignedLine]:
    """Return the span of every line: from its first word's start to its last word's end."""
    starts = line_starts(solution.transcript, solution.words)
    lines: list[AlignedLine] = []
    for index, start in enumerate(starts):
        members = [i for i, w in enumerate(words) if w.line == index]
        if start is None or not members:
            raise StageError("alignment-failed", f"line {index + 1} has no word")
        lines.append(
            AlignedLine(
                start=start,
                end=words[members[-1]].end,
                first_word=members[0],
                word_count=len(members),
                voice=solution.voices[index] if solution.voices else FIRST_VOICE,
            )
        )
    return lines
