"""From lyric lines to the targets of the CTC search, and back to words (ADR-0005).

Every whitespace-separated piece of a line is a word shown as written. Its spoken form (numbers
spelled out, only letters the model knows) gives the model tokens. The targets are the tokens of
all words with the word delimiter between words; word ``i`` owns the targets ``slots[i]`` (first
and last, inclusive) and every letter of the word is exactly one target.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from vocatron.core.languages.base import LanguageModule

DELIMITER = "|"
BLANK = "<pad>"
"""The model's word delimiter and its CTC blank, by the names wav2vec2 vocabularies use."""


@dataclass(frozen=True)
class Word:
    """One word of the lyrics.

    Attributes:
        line: The index of its line.
        text: The word as written (what the screen shows).
        spoken: The letters the model hears; empty when the word has no sound (a dash).
    """

    line: int
    text: str
    spoken: str


@dataclass(frozen=True)
class Transcript:
    """The lyrics as words and as CTC targets.

    Attributes:
        words: All words in order.
        targets: The token ids to align, words separated by the delimiter.
        slots: For each word the index of its first and last target, or ``None`` if it has no
            sound.
        lines: The number of lines (also those without words).
    """

    words: tuple[Word, ...]
    targets: tuple[int, ...]
    slots: tuple[tuple[int, int] | None, ...]
    lines: int


def lower_case_vocabulary(tokens: Sequence[str]) -> list[str]:
    """Return the model's tokens in the form the aligner compares: letters in lower case.

    Special tokens (``<pad>``, ``[UNK]``) and the word delimiter stay as they are. An English
    model has an upper-case vocabulary, a German one a lower-case vocabulary, so this changes
    nothing there.

    Raises:
        ValueError: If two tokens become the same.
    """
    out = [token if token[:1] in "<[" and token[-1:] in ">]" else token.lower() for token in tokens]
    seen: dict[str, str] = {}
    for token, lowered in zip(tokens, out, strict=True):
        if (other := seen.setdefault(lowered, token)) != token:
            raise ValueError(f"the tokens {other!r} and {token!r} are the same in lower case")
    return out


def spoken_form(text: str, module: LanguageModule) -> str:
    """Return the letters the model hears for the written word ``text``."""
    return module.normalise(module.spell_numbers(text))


def build_transcript(
    lines: Sequence[str], module: LanguageModule, vocabulary: Sequence[str]
) -> Transcript:
    """Split ``lines`` into words and build the targets for the model's ``vocabulary``.

    Args:
        lines: The lyric lines as written.
        module: The language of the song.
        vocabulary: The model's tokens by id.

    Returns:
        The transcript.

    Raises:
        ValueError: If the vocabulary lacks the word delimiter or a letter the module returns.
    """
    ids = {token: index for index, token in enumerate(vocabulary)}
    if DELIMITER not in ids:
        raise ValueError(f"the model vocabulary has no word delimiter {DELIMITER!r}")
    words: list[Word] = []
    targets: list[int] = []
    slots: list[tuple[int, int] | None] = []
    for line, text in enumerate(lines):
        for piece in text.split():
            word = Word(line, piece, spoken_form(piece, module))
            words.append(word)
            if not word.spoken:
                slots.append(None)
                continue
            missing = sorted({c for c in word.spoken if c not in ids})
            if missing:
                raise ValueError(f"the model vocabulary lacks the letters {missing}")
            if targets:
                targets.append(ids[DELIMITER])
            slots.append((len(targets), len(targets) + len(word.spoken) - 1))
            targets.extend(ids[c] for c in word.spoken)
    return Transcript(tuple(words), tuple(targets), tuple(slots), len(lines))


def blank_id(vocabulary: Sequence[str]) -> int:
    """Return the id of the CTC blank in ``vocabulary``.

    Raises:
        ValueError: If the vocabulary has no blank token.
    """
    if BLANK not in vocabulary:
        raise ValueError(f"the model vocabulary has no blank token {BLANK!r}")
    return list(vocabulary).index(BLANK)


def line_of_target(transcript: Transcript) -> list[int]:
    """Return the line of every target; a delimiter belongs to the line of the word after it."""
    owners = [0] * len(transcript.targets)
    previous_end = 0
    for word, slot in zip(transcript.words, transcript.slots, strict=True):
        if slot is None:
            continue
        for index in range(previous_end, slot[1] + 1):
            owners[index] = word.line
        previous_end = slot[1] + 1
    return owners
