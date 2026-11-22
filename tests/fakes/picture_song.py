"""A made-up duet for the tests of the picture moments: invented lines, no real song."""

from vocatron.core.layout.sample import timed_song
from vocatron.core.lyrics.document import SingerInfo
from vocatron.core.lyrics.file import LyricLine
from vocatron.core.profiles.picture import PictureSong

LINES = (
    "Wir singen ein Lied\nvom Mond und vom Meer\nvom Wind in den Bäumen\nund einem Boot im Wind\n"
    "Der Morgen ist still\nder Nebel steigt auf\nein Vogel erwacht\nund fliegt über den See\n"
    "Wir singen gemeinsam\nein Lied für die Nacht\nfür Sterne und Wolken\nund ein Hauch von Glück\n"
)
SINGERS = ["1", "1", "1", "1", "2", "2", "2", "all", "1,2", "1,2", "all", "all"]
GAPS = {4: 22.0, 8: 6.0}  # a long break after four lines, a short one before the group sings
START = 20.0
LONG_SINGERS = {1: SingerInfo(name="Anna"), 2: SingerInfo(name="Ben")}


def made_up_song(
    singers: list[str] | None = None, gaps: dict[int, float] | None = None, count: int = 12
) -> PictureSong:
    """Return a picture song of twelve invented lines in German: two singers, then both together.

    A long break and a short pause, a twenty-second intro, and a length that leaves time after the
    last line. ``singers`` and ``gaps`` replace the singers of the lines and the pauses; ``count``
    keeps only the first lines.
    """
    text = "".join(line + "\n" for line in LINES.splitlines()[:count])
    timed = timed_song(
        text, start=START, gaps=GAPS if gaps is None else gaps, singers=singers or SINGERS[:count]
    )
    last = max(word.end for word in timed.words)
    return PictureSong(
        title="Ein Titel",
        artist="Eine Künstlerin",
        duration=last + 20.0,
        language="de",
        bpm=100.0,
        singers=LONG_SINGERS,
        lines=[LyricLine(text=x.text, singers=x.singers, turns=x.turns) for x in timed.lines],
        words=timed.words,
    )
