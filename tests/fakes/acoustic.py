"""An acoustic model that "sings" the lyrics of the song: canned log-probabilities.

It reads ``lyrics.json`` from the work folder, builds the targets with the real tokenisation and
lays them out as clear spikes (three frames apart) between blanks, so that the alignment of the
lyrics on them is known exactly: the first letter of a word is found at the frame of its spike.
"""

from dataclasses import replace

import numpy as np

from fakes.files import InMemoryFileStore
from vocatron.core.alignment.chunks import BackingPart, Emissions
from vocatron.core.alignment.job import AcousticResult
from vocatron.core.alignment.tokens import Transcript, build_transcript
from vocatron.core.errors import StageError
from vocatron.core.languages import LANGUAGES
from vocatron.core.languages.base import LanguageModule
from vocatron.core.languages.de import GERMAN
from vocatron.core.lyrics.file import LyricsFile
from vocatron.engines.protocols import AcousticRequest, Heard

SECONDS_PER_FRAME = 0.02
VOCABULARY = (
    "<pad>", "<s>", "</s>", "<unk>", "|", "'", "-",
    *"abcdefghijklmnopqrstuvwxyz", "ä", "í", "ó", "ö", "ü",
)  # fmt: skip  # the 38 tokens of the German wav2vec2 model
BLANK = 0
STEP = 3  # frames between two sung letters
LEAD_IN = 50  # frames before the first letter
LINE_GAP = 25  # frames of silence after a line
TAIL = 50
SPIKE = 0.9
LOUD_DB = -20.0  # the lead vocals over a sung word
QUIET_DB = -70.0  # and between the words


def loudness_of(
    transcript: Transcript,
    spikes: dict[int, int],
    frames: int,
    silent_words: frozenset[int] = frozenset(),
) -> np.ndarray:
    """Return loudness per frame: loud over every sung word (first to last letter), else quiet.

    The words (by index) in ``silent_words`` stay quiet.
    """
    loud = np.full(frames, QUIET_DB, dtype=np.float32)
    for index, slot in enumerate(transcript.slots):
        if slot is not None and index not in silent_words:
            loud[spikes[slot[0]] : spikes[slot[1]] + 1] = LOUD_DB
    return loud


def loudness_only(
    transcript: Transcript, spikes: dict[int, int], frames: int, words: frozenset[int]
) -> np.ndarray:
    """Return loudness per frame that is loud over the given words only and quiet elsewhere."""
    sung = frozenset(i for i, slot in enumerate(transcript.slots) if slot is not None)
    return loudness_of(transcript, spikes, frames, sung - words)


def spike_matrix(frames: int, spikes: dict[int, int]) -> np.ndarray:
    """Return log-probabilities that are blank except at ``spikes`` (frame to token id)."""
    probs = np.full((frames, len(VOCABULARY)), 0.001, dtype=np.float64)
    probs[:, BLANK] = 0.9
    for frame, token in spikes.items():
        probs[frame, :] = 0.001
        probs[frame, token] = SPIKE
        probs[frame, BLANK] = 0.05
    probs /= probs.sum(axis=1, keepdims=True)
    return np.log(probs).astype(np.float32)


class FakeAcousticModel:
    """Sings the lyrics of the song; records what it was asked."""

    def __init__(self, store: InMemoryFileStore) -> None:
        self.store = store
        self.requests: list[AcousticRequest] = []
        self.fail_with: StageError | None = None
        self.shift: float | None = 0.0  # sing each timed line at its line time plus this
        self.jitter: dict[int, float] = {}  # extra seconds per line index, to break the times
        self.last: dict[int, int] = {}  # the spike frame of every target of the last song
        self.transcript: Transcript | None = None
        self.loudness = True  # give the loudness of the vocals (else none)
        # words that sound in the backing stem but are quiet in the lead (the model still
        # recognises them in the lead's output)
        self.backing_words: frozenset[int] = frozenset()
        # words that only the backing stem sings: blank in the lead's output, spikes in the
        # backing's, quiet in the lead's loudness and loud in the backing's
        self.backing_only: frozenset[int] = frozenset()

    def silent_words(self, request: AcousticRequest) -> frozenset[int]:
        """Return the words that are quiet in what the request measures.

        The words of the backing stem are quiet unless the request adds the backing stem to
        the lead (``voice_source: vocals``); the backing stem must then exist.
        """
        if request.backing is not None:
            assert self.store.sha256(request.backing) is not None, "the backing stem is missing"
        if request.backing is not None and request.sum_backing:
            return frozenset()
        return self.backing_words | self.backing_only

    def log_probs(self, request: AcousticRequest) -> Heard:
        self.requests.append(request)
        request.watch.progress(1.0)
        if self.fail_with is not None:
            raise self.fail_with
        text = self.store.read_text(request.work_dir / "lyrics.json")
        assert text is not None, "the fake acoustic model needs lyrics.json"
        lyrics = LyricsFile.model_validate_json(text)
        transcript = build_transcript(
            [line.text for line in lyrics.lines], LANGUAGES[lyrics.language], VOCABULARY
        )
        starts = {
            index: round((line.time + self.shift + self.jitter.get(index, 0.0)) / SECONDS_PER_FRAME)
            for index, line in enumerate(lyrics.lines)
            if self.shift is not None and line.time is not None
        }
        spikes = layout(transcript, starts)
        self.last, self.transcript = spikes, transcript
        emissions = build(
            transcript,
            spikes,
            silent=self.silent_words(request),
            backing_only=self.backing_only,
            backing_words=self.backing_words,
            hear=request.hear_backing,
        )
        if not self.loudness:
            emissions = replace(emissions, loudness=None)
        frames = len(emissions.log_probs)
        result = AcousticResult(
            frames=frames,
            seconds_per_frame=SECONDS_PER_FRAME,
            vocabulary=list(VOCABULARY),
            device="cpu",
            seconds=0.1,
        )
        return Heard(emissions, result)


def layout(transcript: Transcript, starts: dict[int, int]) -> dict[int, int]:
    """Place the targets of ``transcript``: the frame of every target index.

    A line in ``starts`` begins at that frame (or later, if the one before runs on).
    """
    cursor = LEAD_IN
    spikes: dict[int, int] = {}
    for line in range(transcript.lines):
        members = [
            slot
            for word, slot in zip(transcript.words, transcript.slots, strict=True)
            if word.line == line and slot is not None
        ]
        # the delimiter before a line's first word comes just before the line time
        lead = STEP if members and members[0][0] > 0 else 0
        cursor = max(cursor, starts.get(line, cursor) - lead)
        for first, last in members:
            for index in range(max(first - 1, 0), last + 1):
                spikes[index] = cursor
                cursor += STEP
        cursor += LINE_GAP
    return spikes


def backing_targets(transcript: Transcript, words: frozenset[int]) -> frozenset[int]:
    """Return the targets of the words (by index) that only the backing stem sings."""
    out: set[int] = set()
    for index in words:
        slot = transcript.slots[index]
        assert slot is not None, "a word without sound has no place in the backing"
        out.update(range(slot[0], slot[1] + 1))
    return frozenset(out)


def build(
    transcript: Transcript,
    spikes: dict[int, int],
    *,
    silent: frozenset[int] = frozenset(),
    backing_only: frozenset[int] = frozenset(),
    backing_words: frozenset[int] = frozenset(),
    hear: bool = False,
) -> Emissions:
    """Return the emissions of the song as laid out.

    ``silent`` words are quiet in the loudness, ``backing_only`` words are blank in the lead's
    output (and with ``hear`` sung in the backing's), ``backing_words`` are quiet in the lead
    and loud in the backing.
    """
    frames = max(spikes.values(), default=0) + TAIL
    mine = backing_targets(transcript, backing_only)
    lead = {frame: transcript.targets[i] for i, frame in spikes.items() if i not in mine}
    backing = None
    if hear:
        heard = {frame: transcript.targets[i] for i, frame in spikes.items() if i in mine}
        elsewhere = backing_words | backing_only
        backing = BackingPart(
            spike_matrix(frames, heard),
            loudness_of(transcript, spikes, frames, elsewhere),
            loudness_only(transcript, spikes, frames, elsewhere),
        )
    return Emissions(
        spike_matrix(frames, lead),
        SECONDS_PER_FRAME,
        VOCABULARY,
        loudness_of(transcript, spikes, frames, silent),
        backing,
    )


def sung(
    lines: list[str],
    starts: dict[int, int] | None = None,
    *,
    loudness: bool = True,
    backing_only: frozenset[int] = frozenset(),
    hear: bool = False,
    module: LanguageModule = GERMAN,
) -> tuple[Emissions, Transcript, dict[int, int]]:
    """Return the emissions of ``lines`` sung as laid out, with the transcript and the spikes.

    ``module`` is the language of the song; the vocabulary is the German model's (lower case).

    The emissions carry the loudness (loud over the words, quiet between) unless ``loudness`` is
    false. ``backing_only`` words (by index) are sung only in the backing stem; with ``hear`` the
    emissions carry the backing's part.
    """
    transcript = build_transcript(lines, module, VOCABULARY)
    spikes = layout(transcript, starts or {})
    emissions = build(transcript, spikes, silent=backing_only, backing_only=backing_only, hear=hear)
    if not loudness:
        emissions = replace(emissions, loudness=None)
    return emissions, transcript, spikes
