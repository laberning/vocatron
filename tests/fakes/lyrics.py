"""A lyrics source and a language detector with canned answers."""

from vocatron.core.languages import Detected
from vocatron.core.lyrics.versions import Candidate
from vocatron.engines.protocols import LyricsLookupError

GERMAN = Detected("de", "German")
ENGLISH = Detected("en", "English")


class FakeLyricsSource:
    """Answers every lookup with ``records``; fails with ``error`` when that is set."""

    def __init__(self) -> None:
        self.records: list[Candidate] = []
        self.error: str | None = None
        self.calls: list[tuple[str | None, str, float | None]] = []

    def find(self, artist: str | None, title: str, duration: float | None) -> list[Candidate]:
        self.calls.append((artist, title, duration))
        if self.error is not None:
            raise LyricsLookupError(self.error)
        return list(self.records)


class FakeLanguageDetector:
    """Detects ``language`` for every text, unless a keyword of ``by_keyword`` occurs in it."""

    def __init__(self) -> None:
        self.language: Detected | None = GERMAN
        self.by_keyword: dict[str, Detected | None] = {}
        self.texts: list[str] = []

    def detect(self, text: str) -> Detected | None:
        self.texts.append(text)
        for keyword, language in self.by_keyword.items():
            if keyword in text:
                return language
        return self.language


# Public-domain German folk songs. No other lyrics belong in this repository.
ENTCHEN = (
    "Alle meine Entchen\n"
    "schwimmen auf dem See\n"
    "schwimmen auf dem See\n"
    "Köpfchen in das Wasser\n"
    "Schwänzchen in die Höh\n"
)
HAENSCHEN = (
    "Hänschen klein\n"
    "ging allein\n"
    "in die weite Welt hinein\n"
    "Stock und Hut\n"
    "steht ihm gut\n"
    "ist gar wohlgemut\n"
)
VOGEL = (
    "Kommt ein Vogel geflogen\n"
    "setzt sich nieder auf mein Fuß\n"
    "hat ein Zettel im Schnabel\n"
    "von der Mutter einen Gruß\n"
)
# Public-domain English nursery rhymes.
TWINKLE = (
    "Twinkle, twinkle, little star\n"
    "How I wonder what you are\n"
    "Up above the world so high\n"
    "Like a diamond in the sky\n"
)
MARY = (
    "Mary had a little lamb\n"
    "Its fleece was white as snow\n"
    "And everywhere that Mary went\n"
    "The lamb was sure to go\n"
)
# The same song as scraped online lyrics tend to look: headings, repeat markers, credits.
ENTCHEN_MESSY = (
    "[Strophe 1]\n"
    "Alle meine Entchen\n"
    "schwimmen auf dem See (2x)\n"
    "\n"
    "Refrain:\n"
    "Köpfchen in das Wasser\n"
    "Schwänzchen in die Höh x2\n"
    "\n"
    "Text: Volksgut\n"
)
# More public-domain songs dressed up as messy online lyrics (the junk is invented).
HAENSCHEN_MESSY = (
    "[Intro]\n"
    "\n"
    "[Strophe 1]\n"
    "Hänschen klein\n"
    "ging allein\n"
    "in die weite Welt hinein (x2)\n"
    "[Refrain]\n"
    "Stock und Hut\n"
    "steht ihm gut\n"
    "ist gar wohlgemut\n"
    "(Refrain 2x)\n"
    "\n"
    "Songwriter: Volksgut\n"
    "Lyrics powered by Nobody\n"
    "3 Embed\n"
)
VOGEL_MESSY = (
    "Kommt ein Vogel geflogen,\n"
    "setzt sich nieder auf mein Fuß,\n"
    "[Chorus: Anna]\n"
    "hat ein Zettel im Schnabel\n"
    "von der Mutter einen Gruß. 2x\n"
    "Text & Musik: Volksweise\n"
    "© Niemand\n"
    "You might also like\n"
)
MESSY = {"entchen": ENTCHEN_MESSY, "haenschen": HAENSCHEN_MESSY, "vogel": VOGEL_MESSY}
ENTCHEN_CLEANED = [
    "Alle meine Entchen",
    "schwimmen auf dem See",
    "Köpfchen in das Wasser",
    "Schwänzchen in die Höh",
]


def lrclib_record(
    *, record_id: int, artist: str, title: str, duration: float, **more: object
) -> dict[str, object]:
    """Write a record in the JSON format of LRCLIB (by hand, around public-domain texts).

    ``more`` sets ``plainLyrics``, ``syncedLyrics``, ``albumName`` or ``instrumental``.
    """
    return {
        "id": record_id,
        "name": title,
        "trackName": title,
        "artistName": artist,
        "albumName": "Volkslieder",
        "duration": duration,
        "instrumental": False,
        "plainLyrics": None,
        "syncedLyrics": None,
        **more,
    }


def synced_of(text: str, start: float = 5.0, step: float = 4.0) -> str:
    """Turn the lines of ``text`` into LRC lines, ``step`` seconds apart."""
    rows = []
    for index, line in enumerate(text.splitlines()):
        seconds = start + index * step
        rows.append(f"[{int(seconds // 60):02d}:{seconds % 60:05.2f}] {line}")
    return "\n".join(rows) + "\n"
