"""The small pieces of ASS text the writers share: numbers, styles, drawings, dialogue lines."""

from vocatron.core.ass.timing import ass_time, cs_of
from vocatron.core.scene import Colours

CIRCLE = 0.5522847498  # the Bezier handle length of a quarter circle, in radii
PATH_EPS = 1e-6  # pixels or seconds below which two points of a path are the same


def number(value: float) -> str:
    """Format a coordinate or size with at most two decimals."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def style_name(colours: Colours) -> str:
    """Return the name of the style of a colour set."""
    return f"{colours.unsung[1:]}-{colours.sung[1:]}-{colours.edge[1:]}".lower()


def dialogue(start: float, end: float, style: str, text: str, layer: int = 0) -> str:
    """Write one ``Dialogue:`` line."""
    return (
        f"Dialogue: {layer},{ass_time(cs_of(start))},{ass_time(cs_of(end))},{style},,0,0,0,,{text}"
    )


def solid(colour: str) -> Colours:
    """Return the colours of a drawing: one colour for fill and edge."""
    return Colours(unsung=colour, sung=colour, edge=colour)


def rectangle(width: float, height: float) -> str:
    """Write a rectangle of the given size, from the origin, as ASS drawing commands."""
    n = number
    return f"m 0 0 l {n(width)} 0 {n(width)} {n(height)} 0 {n(height)}"


def move(x: float, y: float, to_y: float, seconds: float) -> str:
    r"""Write a ``\move`` of something at ``x`` from ``y`` to ``to_y`` in ``seconds``."""
    return f"\\move({number(x)},{number(y)},{number(x)},{number(to_y)},0,{round(seconds * 1000)})"


def fade(fade_in: float, fade_out: float) -> str:
    r"""Write a ``\fad`` of the given seconds, empty when there is neither."""
    if not (fade_in or fade_out):
        return ""
    return f"\\fad({round(fade_in * 1000)},{round(fade_out * 1000)})"
