"""Sample songs for checking a style profile: invented lyrics and public-domain folk songs.

Nothing here is a real song of a user. The texts and their times are generated, so that the
layout rules (``vocatron.core.layout.rules``) can be checked on a profile without any audio:
the profile check (``vocatron.core.profiles.check``), the pictures of the looks and the tests use
the same samples.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from vocatron.core.alignment.file import AlignedWord
from vocatron.core.languages.de import GERMAN
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.lyrics.document import Mark, SingerInfo
from vocatron.core.lyrics.file import LyricLine
from vocatron.core.measure import TextMeasurer
from vocatron.core.presets import PRESETS
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import Scene
from vocatron.core.syllables import SyllableWord, split_word

WORD_SECONDS = 0.1  # the time of a word: this plus WORD_LETTER_SECONDS per letter
WORD_LETTER_SECONDS = 0.07
WORD_GAP = 0.08  # silence between two words of a line
LINE_GAP = 0.6  # silence between two lines, unless a test says otherwise
DEFAULT_PRESET = "4x3-720"
SAMPLE_BPM = 100.0  # the tempo of the sample songs: their countdowns count beats
DENSE_GAP = 0.5  # silence between two lines of the dense song

ENTCHEN = (
    "Alle meine Entchen\nschwimmen auf dem See\nschwimmen auf dem See\n"
    "Köpfchen in das Wasser\nSchwänzchen in die Höh\n"
)
HAENSCHEN = "Hänschen klein\nging allein\nin die weite Welt hinein\nStock und Hut\nsteht ihm gut\n"
DUET_TURNS = {2: [(4, "1")], 3: [(2, "2")]}  # the group line ends with singer 1, "Hut" is Ben's
DUET_SINGERS = ["1", "2", "all", "1", "2"]

SAMPLE = (
    "Alle meine Entchen schwimmen auf dem See\n"
    "Köpfchen in das Wasser\n"
    "Schwänzchen in die Höh\n"
    "Donaudampfschifffahrtsgesellschaftskapitänsmützen\n"
    "und noch eine Zeile mit sehr vielen kurzen Wörtern die nicht in eine Zeile passen wollen\n"
)
"""Five lines, the last two too long for one row: they test the fit at every size."""
SAMPLE_GAPS = {1: 0.4, 2: 7.0, 3: 20.0, 4: 1.0}
SAMPLE_SINGERS = ["1", "2", "all", "3,4", "5"]

DENSE = (
    "Der Mond steht hoch am Himmel\n"
    "Wir tanzen leise durch die Nacht\n"
    "Ein kleiner Vogel singt vom Morgen\n"
    "Ein warmer Wind weht durch die Stadt\n"
    "Komm mit mir ans Ende der Straße\n"
    "Ich zähle die Lichter am Fluss\n"
    "Alle zusammen im Kreis um das Feuer\n"
    "Und singen den Morgen herbei\n"
    "Heute Nacht gehört die Welt uns\n"
    "Lauter lauter bis die Fenster klirren\n"
    "Ein Lied für den Mond\n"
    "Ein Lied für den Fluss\n"
    "Wo der Weg sich teilt\n"
    "Bleiben wir zusammen\n"
    "Sterne Sterne Sterne über uns\n"
    "Zum Schluss singen wir es noch einmal\n"
)
"""Sixteen invented lines of a normal length, close together, sung by all five singers and the
group; the worst case for the CD+G timing check."""
DENSE_SINGERS = [
    "1", "2", "3", "4", "5", "all", "1,2", "3,4", "5", "2", "all", "4", "1", "3", "all", "5"
]  # fmt: skip
DENSE_TURNS = {3: [(3, "2")], 6: [(3, "5")], 10: [(2, "1")]}
DENSE_GAPS = {index: DENSE_GAP for index in range(1, 16)} | {5: 7.0, 11: 20.0}


def song_text(
    title: str,
    artist: str | None,
    duration: float | None,
    singers: dict[int, SingerInfo],
    bpm: float | None = SAMPLE_BPM,
) -> SongText:
    """Return the text of a German sample song: the German words for singing together.

    ``bpm`` is the tempo of the sample (100 BPM unless a test asks for none, ``None``).
    """
    return SongText(title, artist, duration, singers, GERMAN.together_two, GERMAN.together_all, bpm)


@dataclass(frozen=True)
class TimedSong:
    """The lines of a song with the time of every syllable.

    Attributes:
        words: Every word with its syllables, as ``syllables.json`` has them.
        lines: The lyrics lines the words belong to.
    """

    words: list[SyllableWord]
    lines: list[LyricLine]


@dataclass
class _Clock:
    """The time cursor of a song being timed."""

    now: float
    words: list[SyllableWord] = field(default_factory=list)
    lines: list[LyricLine] = field(default_factory=list)


def timed_song(
    text: str,
    start: float = 12.0,
    gaps: dict[int, float] | None = None,
    singers: Sequence[str] | None = None,
    turns: Mapping[int, Sequence[tuple[int, str]]] | None = None,
) -> TimedSong:
    """Give the words of ``text`` (one line per row) estimated times and split them into syllables.

    Args:
        text: The lyrics, one line per row.
        start: When the first word starts.
        gaps: Silence before a line, by line index, replacing ``LINE_GAP``.
        singers: The singer of each line (default ``1``).
        turns: Where the singers change inside a line, by line index: pairs of the word index
            and the singers from there on.
    """
    clock = _Clock(start)
    for index, row in enumerate(line for line in text.splitlines() if line.strip()):
        clock.now += (gaps or {}).get(index, LINE_GAP) if index else 0.0
        start_with = singers[index] if singers else "1"
        changes = [Mark(word=word, singers=who) for word, who in (turns or {}).get(index, ())]
        clock.lines.append(LyricLine(text=row, singers=start_with, turns=changes))
        for word in row.split():
            end = clock.now + WORD_SECONDS + WORD_LETTER_SECONDS * len(word)
            aligned = AlignedWord(
                line=index, text=word, spoken=GERMAN.normalise(word), start=clock.now, end=end,
                confidence=0.0, estimated=True,
            )  # fmt: skip
            clock.words.append(split_word(aligned, GERMAN))
            clock.now = end + WORD_GAP
    return TimedSong(clock.words, clock.lines)


type Piece = tuple[TimedSong, SongText]
"""A timed sample song with the text around it (title, artist, length, singers)."""


def sample_piece() -> Piece:
    """``SAMPLE``: five lines, five singers and three kinds of gap."""
    song = timed_song(SAMPLE, start=9.0, gaps=SAMPLE_GAPS, singers=SAMPLE_SINGERS)
    return song, song_text("Ein Titel", "Eine Künstlerin", 120.0, {})


def entchen_piece(duration: float = 60.0, bpm: float | None = SAMPLE_BPM) -> Piece:
    """A short song with a title, a countdown, two long gaps and an ending (tempo ``bpm``)."""
    song = timed_song(ENTCHEN, start=9.0, gaps={2: 6.0, 4: 22.0})
    return song, song_text("Alle meine Entchen", "Volkslied", duration, {}, bpm)


def duet_piece(turns: Mapping[int, Sequence[tuple[int, str]]] | None = None) -> Piece:
    """Hänschen klein as a duet: singers by line and, if asked, changes of singers inside lines."""
    song = timed_song(HAENSCHEN, start=4.0, singers=DUET_SINGERS, turns=turns)
    names = {1: SingerInfo(name="Anna", colour="#22aa55"), 2: SingerInfo(name="Ben")}
    return song, song_text("Hänschen klein", None, 40.0, names)


def dense_piece() -> Piece:
    """``DENSE`` as a song: lines half a second apart, all five singers and the group.

    Singers also change inside lines, and a countdown and a break come between lines. The five
    singers have names, so the title screen is as full as it gets. It is the worst case for the
    CD+G timing check.
    """
    song = timed_song(DENSE, start=8.0, gaps=DENSE_GAPS, singers=DENSE_SINGERS, turns=DENSE_TURNS)
    names = {number: SingerInfo(name=f"Sänger {number}") for number in range(1, 6)}
    return song, song_text("Viele Stimmen", "Volkslied", 120.0, names)


def back_to_back_piece() -> Piece:
    """``DENSE`` with no pause longer than half a second: every page follows the one before at once.

    A look in page mode turns its pages with no time between them (ADR-0041); it is the sample
    where a page that is drawn as a whole is too late, whatever the look's number of slots.
    """
    song = timed_song(DENSE, start=8.0, gaps=dict.fromkeys(range(1, 16), DENSE_GAP))
    return song, song_text("Seite an Seite", "Volkslied", 120.0, {})


def sample_pieces() -> list[tuple[str, Piece]]:
    """Return every sample song of a profile check, each with a name for messages."""
    return [
        ("sample lyrics", sample_piece()),
        ("Alle meine Entchen", entchen_piece()),
        ("Hänschen klein (duet)", duet_piece()),
        ("Hänschen klein (turns)", duet_piece(DUET_TURNS)),
    ]


def scene_of(
    song: TimedSong,
    text: SongText,
    profile: Profile,
    preset: str,
    measurer: TextMeasurer,
) -> Scene:
    """Lay out a timed song in ``profile`` for the frame of the output preset ``preset``."""
    size = PRESETS[preset]
    return layout(
        phrases_from(song.words, song.lines, profile.font.case),
        text,
        profile,
        (size.width, size.height),
        measurer,
    )


def sample_scene(profile: Profile, measurer: TextMeasurer, preset: str = DEFAULT_PRESET) -> Scene:
    """Lay out ``SAMPLE``: five lines, five singers and three kinds of gap."""
    return scene_of(*sample_piece(), profile, preset, measurer)


def entchen_scene(
    profile: Profile,
    measurer: TextMeasurer,
    preset: str = DEFAULT_PRESET,
    duration: float = 60.0,
    bpm: float | None = SAMPLE_BPM,
) -> Scene:
    """A short song with a title, a countdown, two long gaps and an ending (tempo ``bpm``)."""
    return scene_of(*entchen_piece(duration, bpm), profile, preset, measurer)


def duet_scene(
    profile: Profile,
    measurer: TextMeasurer,
    preset: str = DEFAULT_PRESET,
    turns: Mapping[int, Sequence[tuple[int, str]]] | None = None,
) -> Scene:
    """Hänschen klein as a duet: singers by line and, if asked, changes of singers inside lines."""
    return scene_of(*duet_piece(turns), profile, preset, measurer)


def sample_scenes(
    profile: Profile, measurer: TextMeasurer, preset: str = DEFAULT_PRESET
) -> list[tuple[str, Scene]]:
    """Return every sample scene of ``profile`` in one preset, each with a name for messages."""
    return [
        (title, scene_of(*piece, profile, preset, measurer)) for title, piece in sample_pieces()
    ]
