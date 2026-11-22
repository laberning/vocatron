"""Scenes of public-domain songs for the tests of the renderers: made with the fixed measurer."""

from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from fakes.measure import FixedMeasurer
from fakes.resources import FakeResources
from vocatron.core.cdg.canvas import cdg_scene
from vocatron.core.cdg.look import cdg_profile
from vocatron.core.layout import sample
from vocatron.core.layout.build import SongText
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.layout.sample import DUET_TURNS
from vocatron.core.lyrics.document import SingerInfo
from vocatron.core.measure import TextMeasurer
from vocatron.core.profiles.model import Profile, parse_profile
from vocatron.core.scene import Scene


def builtin_profile(name: str, **overrides: JsonValue) -> Profile:
    """Return the built-in profile ``name`` with ``overrides`` (nested keys as in the YAML).

    The start screen is the plain card unless ``title.form`` is overridden: most tests look at
    the card of text; the start screen with the wordmark has tests of its own.
    """
    text = FakeResources().builtin_profile(name) or ""
    title = overrides.get("title")
    plain: JsonValue = {"form": "plain", **(title if isinstance(title, dict) else {})}
    return parse_profile(name, text, {**overrides, "title": plain})


def profile(**overrides: JsonValue) -> Profile:
    """Return the default built-in profile with ``overrides`` (nested keys as in the YAML)."""
    return builtin_profile("two-line-turns", **overrides)


def entchen_with(
    chosen: Profile,
    duration: float = 60.0,
    preset: str = "4x3-720",
    measurer: TextMeasurer | None = None,
    bpm: float | None = sample.SAMPLE_BPM,
) -> Scene:
    """A short song with a title, a countdown, two long gaps and an ending, in a given profile.

    The countdowns count beats at ``bpm`` (100 by default); with ``None`` they run in seconds.
    """
    return sample.entchen_scene(chosen, measurer or FixedMeasurer(), preset, duration, bpm)


def duet_with(
    chosen: Profile,
    preset: str = "4x3-720",
    turns: Mapping[int, Sequence[tuple[int, str]]] | None = None,
) -> Scene:
    """Hänschen klein as a duet: singers by line and, if asked, changes of singers inside lines."""
    return sample.duet_scene(chosen, FixedMeasurer(), preset, turns)


def entchen_scene(
    duration: float = 60.0, bpm: float | None = sample.SAMPLE_BPM, **overrides: JsonValue
) -> Scene:
    """A short song with a title, a countdown, two long gaps and an ending."""
    return entchen_with(profile(**overrides), duration, bpm=bpm)


def duet_scene() -> Scene:
    """Hänschen klein as a duet: singers by line (the group sings one of them)."""
    return duet_with(profile())


def turn_scene() -> Scene:
    """The duet with two lines in which the singers change at a word (``DUET_TURNS``)."""
    return duet_with(profile(), turns=DUET_TURNS)


def cdg_scene_of(song: sample.TimedSong, text: SongText, chosen: Profile) -> Scene:
    """Lay a timed song out for the CD+G screen with the fixed measurer.

    A look with a ``cdg`` section is laid out as its CD+G profile (ADR-0029).
    """
    phrases = phrases_from(song.words, song.lines, chosen.font.case)
    look = cdg_profile(chosen) if chosen.cdg is not None else chosen
    return cdg_scene(phrases, text, look, FixedMeasurer())


def cdg_entchen(chosen: Profile | None = None, duration: float = 60.0) -> Scene:
    """The short folk song of ``entchen_scene`` laid out for the CD+G screen."""
    song = sample.timed_song(sample.ENTCHEN, start=9.0, gaps={2: 6.0, 4: 22.0})
    text = sample.song_text("Alle meine Entchen", "Volkslied", duration, {})
    return cdg_scene_of(song, text, chosen or profile())


def cdg_duet(chosen: Profile | None = None, *, turns: bool = True) -> Scene:
    """Hänschen klein as a duet for the CD+G screen, with changes of singers inside two lines."""
    song = sample.timed_song(
        sample.HAENSCHEN,
        start=4.0,
        singers=sample.DUET_SINGERS,
        turns=sample.DUET_TURNS if turns else None,
    )
    names = {1: SingerInfo(name="Anna", colour="#22aa55"), 2: SingerInfo(name="Ben")}
    return cdg_scene_of(
        song, sample.song_text("Hänschen klein", None, 40.0, names), chosen or profile()
    )
