"""Stage 2: the marked duets of ``.corpus/duets`` through lyrics and layout (ADR-0018).

Every marked duet is read by Vocatron's own code: the lyrics stage (on fakes, no AI), words timed
evenly from the line times of the ``.lrc``, then the layout in two profiles. The singers of every
word must be the same in the lyrics file and in the scene, each in the colours of its singers, and
the scene rules hold. The lyrics are copyrighted (AGENTS.md): the tests report counts and
verdicts only, so no message here holds a word of a song.
"""

import re
from pathlib import Path

import pytest

from conformance.scene_rules import check_scene
from conftest import corpus_dir
from fakes.measure import FixedMeasurer
from fakes.scenes import builtin_profile
from fakes.songs import FakeWorld
from fakes.timed import timed_from_line_times
from realworld import CORPUS_PAGE, corpus_path
from vocatron.core.layout.build import SongText, layout, line_colours
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.lyrics.document import Mark, has_singer_marks, parse, resolve_singers, write
from vocatron.core.lyrics.file import LyricLine, LyricsFile
from vocatron.core.presets import PRESETS
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import LineElement, Scene
from vocatron.core.syllables import SyllableWord
from vocatron.stages.batch import run_song
from vocatron.stages.config import Config, LyricsSettings
from vocatron.stages.lyrics import load_lyrics

OLD_PREFIX = re.compile(r"((?i:all)|[MFD]|[1-5](?:\s*,\s*[1-5])*)\s*:\s*\S")
LOOKS = ("two-line-turns", "full-page")
SONG = Path("/music/duet.mp3")
MIN_WORDS_FOR_TURN = 4

pytestmark = pytest.mark.timeout(600)


def duets() -> list[object]:
    """Return the names of the ``.lrc`` files in ``.corpus/duets``, or one skipped case."""
    folder = corpus_dir() / "duets"
    if not folder.is_dir():
        reason = f"needs the folder {folder}; see {CORPUS_PAGE}"
        return [pytest.param("", marks=pytest.mark.skip(reason=reason))]
    return [*sorted(path.name for path in folder.glob("*.lrc"))]


def lyrics_of(text: str) -> LyricsFile:
    """Run the lyrics stage on fakes with the text as the ``.lrc`` next to the song."""
    world = FakeWorld()
    world.add_song(SONG, lyrics=None)
    world.store.add(SONG.with_suffix(".lrc"), text.encode("utf-8"))
    config = Config(lyrics=LyricsSettings(language="en"))  # the fake detector is not asked
    status = run_song(
        world.song(SONG, config), config, world.engines, force=False, only=("probe", "lyrics")
    )
    assert status.error is None, "the lyrics stage failed"
    found = load_lyrics(world.song(SONG, config), world.engines)
    assert found is not None
    return found


def singers_of_words(line: LyricLine) -> list[str]:
    """Return who sings each word of a lyrics line."""
    turns = {turn.word: turn.singers for turn in line.turns}
    current = line.singers
    found: list[str] = []
    for index in range(len(line.text.split())):
        current = turns.get(index, current)
        found.append(current)
    return found


def singers_of_spans(line: LineElement) -> list[str]:
    """Return who sings each syllable of a scene line (one per word here)."""
    turns = {turn.span: turn.singers for turn in line.turns}
    current = line.singers
    found: list[str] = []
    for index in range(len(line.spans)):
        current = turns.get(index, current)
        found.append(current)
    return found


def laid_out(lyrics: LyricsFile, words: list[SyllableWord], look: Profile) -> Scene:
    preset = PRESETS["4x3-720"]
    song = SongText("Duet", None, words[-1].end + 10.0, lyrics.singers)
    phrases = phrases_from(words, lyrics.lines, look.font.case)
    return layout(phrases, song, look, (preset.width, preset.height), FixedMeasurer())


def with_turns(text: str) -> str:
    """Add a change of singers at the third word of every fifth line (as the files may get)."""
    document = parse(text, "lrc")
    who = resolve_singers(document.lines)
    lines = list(document.lines)
    for index in range(0, len(lines), 5):
        if len(lines[index].text.split()) >= MIN_WORDS_FOR_TURN:
            other = "2" if who[index].singers == "all" else "all"
            marks = (*lines[index].marks, Mark(word=2, singers=other))
            lines[index] = lines[index].model_copy(update={"marks": marks})
    return write(document.model_copy(update={"lines": tuple(lines)}))


def check_duet(name: str, *, turns: bool) -> None:
    """Check one duet (a failure shows no value of the run: ``safe_failure`` in ``conftest``)."""
    text = (corpus_path("duets") / name).read_text(encoding="utf-8")
    if not has_singer_marks(parse(text, "lrc").lines):
        pytest.skip("this duet has no singer marks yet")
    document = parse(with_turns(text) if turns else text, "lrc")
    text = write(document)
    lyrics = lyrics_of(text)
    assert not [line for line in lyrics.lines if OLD_PREFIX.match(line.text)], (
        "lines still start with an old prefix"
    )
    assert parse(write(document), "lrc") == document, "the file does not survive writing"
    marks = sum(len(line.marks) for line in document.lines)
    assert marks > 0, "no marks were read"
    # the marks never reach the text of the lyrics
    assert not [line for line in lyrics.lines if "{" in line.text or "}" in line.text], (
        "a mark reached the text"
    )
    expected = [singer for line in lyrics.lines for singer in singers_of_words(line)]
    in_line_turns = sum(len(line.turns) for line in lyrics.lines)
    inside = sum(1 for line in document.lines for mark in line.marks if mark.word > 0)
    # a file may change singers inside a line itself; a mark naming who sings already is no turn
    assert in_line_turns <= inside, f"{in_line_turns} turns from {inside} marks inside lines"
    assert in_line_turns > 0 or not turns, "the marks added inside lines made no turn"
    words = timed_from_line_times(lyrics.lines)
    assert len(expected) == len(words)
    for look_name in LOOKS:
        look = builtin_profile(look_name)
        scene = laid_out(lyrics, words, look)
        check_scene(scene, look)
        lines = scene.lines()
        found = [singer for line in lines for singer in singers_of_spans(line)]
        differ = sum(a != b for a, b in zip(expected, found, strict=False))
        assert (len(found), differ) == (len(expected), 0), (
            f"{look_name}: {differ} of {len(expected)} words change singers on the way "
            f"({len(found)} in the scene)"
        )
        wrong = 0
        for line in lines:
            at = {t.span: t.colours for t in line.turns}
            colours = line.colours
            for index, singers in enumerate(singers_of_spans(line)):
                colours = at.get(index, colours)
                wrong += colours != line_colours(singers, look, lyrics.singers)
        assert wrong == 0, f"{look_name}: {wrong} syllables are in the wrong colours"
        # a split of a long line moves a turn to the start of the second half, so only count
        # what is left as a turn in the scene
        scene_turns = sum(len(line.turns) for line in lines)
        assert scene_turns <= in_line_turns, f"{look_name}: more turns than the lyrics have"


@pytest.mark.parametrize("name", duets())
def test_a_marked_duet_keeps_its_singers_from_the_file_to_the_scene(name: str) -> None:
    check_duet(name, turns=False)


@pytest.mark.parametrize("name", duets())
def test_a_duet_with_changes_inside_lines_keeps_them_too(name: str) -> None:
    check_duet(name, turns=True)
