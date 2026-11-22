"""The silent intro before the song: how much silence the start of a song needs (ADR-0020)."""

from vocatron.core.profiles.model import Profile
from vocatron.core.scene import rounded


def intro_minimum(ensemble: bool, profile: Profile) -> float:
    """Return the least seconds from the start of the video to the first sung word.

    Args:
        ensemble: Whether the song has more than one singer or lines sung together.
        profile: The style profile.
    """
    return profile.intro.group if ensemble else profile.intro.solo


def intro_lead(first_start: float, ensemble: bool, profile: Profile) -> float:
    """Return the silence to add before the song, in seconds rounded to a thousandth.

    Only as much as is missing: ``0`` when the first word comes late enough, or when the profile
    turns the intro off.

    Args:
        first_start: When the first sung word starts in the song.
        ensemble: Whether the song has more than one singer or lines sung together.
        profile: The style profile.
    """
    return rounded(max(0.0, intro_minimum(ensemble, profile) - first_start))
