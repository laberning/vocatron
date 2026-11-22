"""The CD+G check of a style profile (ADR-0029), part of ``vocatron profiles check``.

The look is laid out for the CD+G screen on the sample songs, one dense invented song and one
whose lines never pause, so that pages follow each other at once (``vocatron.core.layout.sample``),
and written with ``fit_stream``, the function the ``cdg`` stage uses. Each problem is located at
the key of the ``cdg`` section that fixes it:

- the palette needs more than 16 entries: ``cdg.colours``;
- the contrast rules fail on the 12-bit colours: ``cdg.colours.<singer>.<part>``;
- a line is too wide at ``min_font_px``: ``cdg.min_font_px``; the slots do not fit: ``cdg.slots``;
- after the last fallback step a line is still drawn late: ``cdg.font_px``; the wipe is still too
  far behind: ``cdg.wipe_columns``. A line counts as late when it is not fully drawn in the frame
  it is shown in by the time its first syllable starts (ADR-0041).

A broken layout rule is a bug of the layout and is reported without a key.
"""

from dataclasses import dataclass, field

from vocatron.core.cdg.fit import MAX_WIPE_LAG, Fit, fit_stream
from vocatron.core.cdg.look import cdg_profile
from vocatron.core.config_errors import Issue, Location
from vocatron.core.errors import StageError
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.sample import Piece, back_to_back_piece, dense_piece, sample_pieces
from vocatron.core.measure import TextMeasurer, TextRasteriser
from vocatron.core.profiles.model import Profile, profile_issues
from vocatron.core.scene import Shortfall

CDG_FIT_KEYS: dict[str, Location] = {
    "too-wide": ("cdg", "min_font_px"),
    "block": ("cdg", "slots"),
}
"""The key to change when a shortfall of that kind is reported on CD+G."""


@dataclass
class CdgCheck:
    """What the CD+G check found.

    Attributes:
        issues: Problems located at a key of the ``cdg`` section.
        bugs: Broken layout rules, ready to print after the file name.
    """

    issues: list[Issue] = field(default_factory=list)
    bugs: list[str] = field(default_factory=list)


def _contrast_issues(profile: Profile, chosen: Profile) -> list[Issue]:
    """Return the contrast problems that rounding to 12 bits (or an override) causes."""
    before = {issue.loc for issue in profile_issues(profile)}
    return [
        Issue(("cdg", *issue.loc), f"{issue.message} on CD+G")
        for issue in profile_issues(chosen)
        if issue.loc not in before
    ]


def _timing_issues(title: str, fit: Fit) -> list[Issue]:
    """Return how a song misses the timing after the last fallback step."""
    found: list[Issue] = []
    if fit.late_lines:
        found.append(
            Issue(
                ("cdg", "font_px"),
                f"{title}: lines not fully drawn before they are sung: {fit.late_lines}, "
                f"even with {fit.step.name}",
            )
        )
    if fit.wipe_lag > MAX_WIPE_LAG:
        found.append(
            Issue(
                ("cdg", "wipe_columns"),
                f"{title}: the wipe is {fit.wipe_lag * 1000:.0f} ms behind "
                f"(at most {MAX_WIPE_LAG * 1000:.0f} ms), even with {fit.step.name}",
            )
        )
    return found


def _check_piece(
    title: str,
    piece: Piece,
    profile: Profile,
    found: CdgCheck,
    tools: tuple[TextMeasurer, TextRasteriser],
) -> None:
    """Write one sample song for CD+G and add what is wrong with it to ``found``."""
    song, text = piece
    measurer, rasteriser = tools
    phrases = phrases_from(song.words, song.lines, profile.font.case)
    try:
        fit = fit_stream(phrases, text, profile, measurer, rasteriser)
    except StageError as error:
        found.issues.append(Issue(("cdg", "colours"), f"{title}: {error}"))
        return
    for shortfall in _fit_shortfalls(fit):
        found.issues.append(
            Issue(CDG_FIT_KEYS[shortfall.kind], f"{title}: {shortfall.message} (CD+G)")
        )
    found.bugs += [f"CD+G, {title}: {rule}" for rule in scene_findings(fit.scene, fit.profile)]
    found.issues += _timing_issues(title, fit)


def _fit_shortfalls(fit: Fit) -> list[Shortfall]:
    """Return the shortfalls of the laid-out scene that a key of the section can fix."""
    return [s for s in fit.scene.shortfalls if s.kind in CDG_FIT_KEYS]


def check_cdg(profile: Profile, measurer: TextMeasurer, rasteriser: TextRasteriser) -> CdgCheck:
    """Check a look with the marker on the sample songs, the dense song and the one without pauses.

    Args:
        profile: A profile with a ``cdg`` section.
        measurer: Measures text; the real font gives the real answer.
        rasteriser: Draws the letters.
    """
    found = CdgCheck()
    found.issues += _contrast_issues(profile, cdg_profile(profile))
    songs = [
        *sample_pieces(),
        ("dense song", dense_piece()),
        ("pages back to back", back_to_back_piece()),
    ]
    for title, piece in songs:
        _check_piece(title, piece, profile, found, (measurer, rasteriser))
    found.issues = list(dict.fromkeys(found.issues))
    found.bugs = list(dict.fromkeys(found.bugs))
    return found
