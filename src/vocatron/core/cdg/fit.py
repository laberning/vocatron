"""Fit a song to the CD+G timing, falling back in fixed steps (ADR-0029).

A song is *in time* when every line is fully drawn before its first syllable and the wipe is at
most ``MAX_WIPE_LAG`` behind. ``fit_stream`` lays the song out and writes the stream as the look
declares it; when that is not in time it tries the fallback steps of ``vocatron.core.cdg.look``
(for a page look its pages turning line by line, ADR-0041; the lead-in minimum raised to the look's
target and then to its maximum, then the wipe at 6 pixels) and returns the first step that is in
time, or the last one with ``in_time`` false. The ``cdg`` stage and the CD+G check of
``vocatron profiles check`` both call it, so they cannot disagree.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from vocatron.core.cdg.canvas import cdg_scene
from vocatron.core.cdg.look import FitStep, cdg_profile, fit_steps
from vocatron.core.cdg.stream import CdgStream, build_stream
from vocatron.core.layout.build import SongText
from vocatron.core.layout.phrases import Phrase
from vocatron.core.measure import TextMeasurer, TextRasteriser
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import Scene

MAX_WIPE_LAG = 0.05
"""The longest the wipe may be behind the singing, in seconds."""


@dataclass(frozen=True)
class Fit:
    """A song written for CD+G and how well it keeps the timing.

    Attributes:
        step: The fallback step the stream was written with.
        profile: The CD+G profile of that step.
        scene: The scene laid out with it.
        written: The stream.
        steps: How many steps the look has.
    """

    step: FitStep
    profile: Profile
    scene: Scene
    written: CdgStream
    steps: int

    @property
    def late_lines(self) -> int:
        """How many lines were not fully drawn when their first syllable started."""
        return len(self.written.scheduled.missed)

    @property
    def wipe_lag(self) -> float:
        """The longest the wipe was behind, in seconds."""
        return self.written.scheduled.wipe_lag

    @property
    def in_time(self) -> bool:
        """Tell whether every line is drawn in time and the wipe keeps up."""
        return self.late_lines == 0 and self.wipe_lag <= MAX_WIPE_LAG


def write_step(
    phrases: Sequence[Phrase],
    song: SongText,
    profile: Profile,
    step: FitStep,
    measurer: TextMeasurer,
    rasteriser: TextRasteriser,
) -> Fit:
    """Lay the song out and write its stream at one fallback step.

    Raises:
        StageError: ``cdg-palette`` if the look needs more than 16 colours.
    """
    chosen = cdg_profile(profile, step)
    scene = cdg_scene(phrases, song, chosen, measurer)
    written = build_stream(scene, rasteriser, step.wipe_columns, chosen.mode == "page")
    return Fit(step, chosen, scene, written, len(fit_steps(profile)))


def fit_stream(
    phrases: Sequence[Phrase],
    song: SongText,
    profile: Profile,
    measurer: TextMeasurer,
    rasteriser: TextRasteriser,
) -> Fit:
    """Write the song for CD+G at the first fallback step that is in time.

    Args:
        phrases: The lines with their syllable times.
        song: Title, artist, length, singers and tempo.
        profile: A profile with a ``cdg`` section.
        measurer: Measures text in the bundled font.
        rasteriser: Draws the letters.

    Returns:
        The first step in time, or the last step when none is.

    Raises:
        StageError: ``cdg-palette`` if the look needs more than 16 colours.
    """
    first, *later = fit_steps(profile)
    fit = write_step(phrases, song, profile, first, measurer, rasteriser)
    for step in later:
        if fit.in_time:
            break
        fit = write_step(phrases, song, profile, step, measurer, rasteriser)
    return fit
