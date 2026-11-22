"""The stage file of the alignment stage: ``alignment.json`` (ADR-0006)."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from vocatron.core.alignment.rails import Rails
from vocatron.core.lyrics.document import FIRST_VOICE, Voice
from vocatron.core.separation.rules import Device
from vocatron.core.stage_file import StageFile


class AlignedWord(BaseModel):
    """One word of the lyrics with its time.

    Attributes:
        line: The index of its line in ``lyrics.json``.
        text: The word as written.
        spoken: The letters the model heard (numbers spelled out); empty for a word with no sound.
        start: Seconds from the start of the song.
        end: Seconds from the start of the song.
        confidence: 0 to 1: how sure the model was of the word's letters; 0 for no sound.
        estimated: The time is interpolated from the neighbours, not measured.
        letters: Start and end of every letter of a measured word.
    """

    model_config = ConfigDict(extra="forbid")

    line: int
    text: str
    spoken: str
    start: float
    end: float
    confidence: float
    estimated: bool
    letters: list[tuple[float, float]] = Field(default_factory=list)

    @property
    def heard_end(self) -> float:
        """Where the model last heard a letter of the word; ``end`` without letters.

        ``end`` may be later: a measured word is held until the voice stops (ADR-0013).
        """
        return self.letters[-1][1] if self.letters else self.end


class AlignedLine(BaseModel):
    """One line of the lyrics with its time.

    Attributes:
        start: Where the first word starts.
        end: Where the last word ends.
        first_word: The index of its first word in ``words``.
        word_count: How many words it has.
        voice: ``2`` for a line the second voice sings (ADR-0052): marked in the lyrics file, with
            the time of the line before, or found in the audio; ``1`` otherwise. Lines of
            different voices may overlap in time; within a voice they do not.
    """

    model_config = ConfigDict(extra="forbid")

    start: float
    end: float
    first_word: int
    word_count: int
    voice: Voice = FIRST_VOICE


class DroppedHint(BaseModel):
    """A line time of an ``.lrc`` that broke the order of the lines and was left out.

    Attributes:
        line: The number of the line in the lyrics (from 1).
        time: The time tag as written, ``mm:ss.xx``.
    """

    model_config = ConfigDict(extra="forbid")

    line: int
    time: str


class RailsUsed(BaseModel):
    """What became of the line times of an ``.lrc``.

    Attributes:
        kind: ``none`` (not used), ``shifted`` (used after correcting an offset) or ``ignored``
            (they do not fit the singing).
        offset: Seconds the singing lies after the hints.
        compared: How many lines were compared.
        spread: The median absolute deviation from the offset.
        near: The share of lines within half a second of the offset.
        dropped: The hints left out because they broke the order of the lines.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Rails
    offset: float = 0.0
    compared: int = 0
    spread: float = 0.0
    near: float = 0.0
    dropped: list[DroppedHint] = []


class QualityReport(BaseModel):
    """How good an alignment looks (answer 5 of the story; ``vocatron.core.quality``).

    Attributes:
        words: The number of words.
        estimated: How many words are estimated.
        estimated_share: ``estimated / words``.
        longest_gap: The longest silence between two words of one line in seconds.
        gap_line: The line with that gap, or ``None`` without a gap.
        too_short: Measured words shorter than 60 ms.
        too_long: Measured words longer than 3 s.
    """

    model_config = ConfigDict(extra="forbid")

    words: int
    estimated: int
    estimated_share: float
    longest_gap: float
    gap_line: int | None
    too_short: int
    too_long: int


class VoiceUsed(BaseModel):
    """What became of the voice activity (ADR-0012); numbers and fixed phrases only.

    Attributes:
        used: Whether the voice placed estimated words and ended measured ones for this song.
        reason: ``used``, or why not (``switched off``, ``no loudness``, ``too little confident
            singing``, ``low contrast``, ``voiced share out of range``).
        threshold_db: The loudness above which a frame counts as voiced (0 if not found).
        voiced_share: The share of voiced frames (0 if not found).
        placed: How many estimated words were placed on the voice.
        re_estimated: How many measured words in silence were estimated instead.
        kept: How many unsure words kept the model's position because the voice supports it
            (ADR-0021).
        held: How many measured words end later, where the voice stops (ADR-0013).
        held_median: The median move of those ends in seconds (0 without moves).
        unheard: How many lines the model did not hear were placed at their line time
            (ADR-0027).
    """

    model_config = ConfigDict(extra="forbid")

    used: bool
    reason: str
    threshold_db: float
    voiced_share: float
    placed: int
    re_estimated: int
    kept: int
    held: int
    held_median: float
    unheard: int


class BackingUsed(BaseModel):
    """What became of the backing vocals in the model's ear (ADR-0014); numbers and phrases only.

    Attributes:
        used: Whether any frame took the backing's output.
        reason: ``used``, ``switched off``, ``lead voice not plausible`` or ``no backing frames``.
        frames: How many frames took the backing's output.
        words: How many measured words have most of their letters in those frames.
    """

    model_config = ConfigDict(extra="forbid")

    used: bool
    reason: str
    frames: int
    words: int


class AlignmentFile(StageFile):
    """``alignment.json``: when every word is sung.

    Attributes:
        language: The language module that was used.
        model: The acoustic model's registry name and revision.
        rails: What became of the line times of an ``.lrc``.
        words: Every word in the order of the lyrics (not of time when two voices sing at once).
        lines: Every line in order, with its voice.
        quality: The quality report.
        voice: What became of the voice activity.
        backing: What became of the backing vocals in the model's ear.
        frames: The number of frames aligned.
        seconds_per_frame: The length of a frame.
        device: The device the model ran on.
        seconds: How long the model took.
        peak_vram_gib: The most GPU memory used, or ``None`` on the CPU.
        warnings: What the fan should know, for example the fallback to the CPU.
    """

    SCHEMA_NAME: ClassVar[str] = "alignment"
    schema_version: Literal[7, 8] = 8  # a v7 file reads as v8: v8 only adds the line's voice
    language: str
    model: str
    revision: str
    rails: RailsUsed
    words: list[AlignedWord]
    lines: list[AlignedLine]
    quality: QualityReport
    voice: VoiceUsed
    backing: BackingUsed
    frames: int
    seconds_per_frame: float
    device: Device
    seconds: float
    peak_vram_gib: float | None = None
    warnings: list[str] = Field(default_factory=list)
