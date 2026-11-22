"""The CD+G canvas: the frame and safe area the scene is laid out for (ADR-0023).

The screen is 300 by 216 pixels; the visible part is the inner 288 by 192 pixels, one tile inside
the border. The layout of the video takes the safe area as a share of the frame, which 0.9 of
300 by 216 would not make the visible area, so the CD+G scene is laid out with this rectangle.
"""

from collections.abc import Sequence

from vocatron.core.cdg.screen import BORDER_X, BORDER_Y, HEIGHT, WIDTH
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.phrases import Phrase
from vocatron.core.measure import TextMeasurer
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import Rect, Scene

FRAME = (WIDTH, HEIGHT)
"""The size of the CD+G screen in pixels."""
SAFE = Rect(x=BORDER_X, y=BORDER_Y, w=WIDTH - 2 * BORDER_X, h=HEIGHT - 2 * BORDER_Y)
"""The visible area: everything is drawn inside it."""


def cdg_scene(
    phrases: Sequence[Phrase], song: SongText, profile: Profile, measurer: TextMeasurer
) -> Scene:
    """Lay the song out for the CD+G screen: the same layout as the video, on 300 by 216 pixels.

    The start screen follows the profile's ``title.form``: the wordmark with pixel letters on its
    own palette when it lasts at least four seconds, else the plain card (ADR-0056).

    Args:
        phrases: The lines with their syllable times.
        song: Title, artist, length, singers and tempo.
        profile: The style profile.
        measurer: Measures text in the bundled font.
    """
    return layout(phrases, song, profile, FRAME, measurer, safe=SAFE, pixel_mark=True)
