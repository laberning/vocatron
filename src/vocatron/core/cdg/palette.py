"""The 16-colour palette of a CD+G scene, built so that a wipe is one XOR (ADR-0023).

Colours are rounded to 12 bits. Text is drawn in two palette entries, its ink and, for smooth
edges, one shade between ink and background. The 16 entries are eight pairs, the ink at an even
index and the shade right after it. A sung colour is the pair of the singer's sung colour, so a
colour group's mask (the XOR of its unsung and sung pair numbers, shifted by one bit) turns ink
into sung ink and shade into sung shade at once. Flat colours (the background, an edge, a bar)
take the entries of the first pairs, two to a pair, and text colours the pairs after them, which
leaves room for one unsung colour and six sung ones next to a background: the five singers and the
group.

The start screen with the wordmark has a palette of its own (``build_title_palette``, ADR-0056):
the field, the edge, the seven bands, white and the colours of the singers' names, each one entry
and no shades. The stream loads it first and replaces it with the palette of the song when the
screen ends, so the song's palette does not count the colours of that screen.
"""

from dataclasses import dataclass

from vocatron.core.cdg.events import Colour4
from vocatron.core.cdg.screen import PALETTE_SIZE
from vocatron.core.colour import from_12bit, to_12bit
from vocatron.core.errors import StageError
from vocatron.core.scene import (
    CardElement,
    CountdownElement,
    LineElement,
    PreviewElement,
    ProgressElement,
    Scene,
    TimerElement,
)
from vocatron.core.wordmark import BAND_COLOURS, EDGE_COLOUR, FIELD_COLOUR, TEXT_COLOUR

PAIRS = PALETTE_SIZE // 2


def colour4(colour: str) -> Colour4:
    """Return ``#rrggbb`` rounded to 4 bits per channel (``vocatron.core.colour.to_12bit``)."""
    return to_12bit(colour)


def hex_of(colour: Colour4) -> str:
    """Return a 12-bit colour as ``#rrggbb``."""
    return from_12bit(colour)


def shade_of(ink: Colour4, background: Colour4) -> Colour4:
    """Return the colour half way between ``ink`` and ``background`` (rounded up)."""
    red, green, blue = ((a + b + 1) // 2 for a, b in zip(ink, background, strict=True))
    return (red, green, blue)


@dataclass(frozen=True)
class Palette:
    """The palette of a scene and how its colours map to entries.

    Attributes:
        entries: The 16 entries as 4-bit red, green and blue.
        background: The index of the background colour (always 0).
        text_entries: The index of the ink of each text colour; its shade is the next index.
        flat_entries: The index of each flat colour.
        shaded: Text has a shade entry after its ink; ``False`` for the palette of the start
            screen, whose text is drawn in ink only.
    """

    entries: tuple[Colour4, ...]
    background: int
    text_entries: dict[Colour4, int]
    flat_entries: dict[Colour4, int]
    shaded: bool = True

    def ink(self, colour: str) -> tuple[int, int]:
        """Return the index of the ink of a text colour and of its shade.

        Without shades (``shaded`` false) the shade is the ink's index too.

        Raises:
            KeyError: If the colour is not text in the scene.
        """
        index = self.text_entries[colour4(colour)]
        return index, index + self.shaded

    def flat(self, colour: str) -> int:
        """Return the index of a flat colour (an edge, a bar, the background).

        Raises:
            KeyError: If the colour is not in the scene.
        """
        found = colour4(colour)
        return self.flat_entries[found] if found in self.flat_entries else self.text_entries[found]

    def mask(self, unsung: str, sung: str) -> int:
        """Return the value that turns the unsung ink and shade into the sung ones by XOR."""
        return self.text_entries[colour4(unsung)] ^ self.text_entries[colour4(sung)]


def is_pixel_title(element: object) -> bool:
    """Tell whether ``element`` is the start screen with pixel letters, drawn in its own palette."""
    return isinstance(element, CardElement) and element.mark is not None and element.mark.pixel


def pixel_title(scene: Scene) -> CardElement | None:
    """Return the start screen of ``scene`` if it has pixel letters (``TitleMark.pixel``)."""
    return next(
        (e for e in scene.elements if isinstance(e, CardElement) and is_pixel_title(e)), None
    )


def _text_colours(scene: Scene) -> list[Colour4]:
    """Return the text colours of the scene, each once, in the order they appear."""
    found: list[str] = []
    for element in scene.elements:
        if is_pixel_title(element):
            continue  # the start screen has its palette
        if isinstance(element, LineElement):
            found += [element.colours.unsung, element.colours.sung]
            for turn in element.turns:
                found += [turn.colours.unsung, turn.colours.sung]
        elif isinstance(element, CardElement):
            found += [line.colour for line in element.lines]
        elif isinstance(element, PreviewElement):
            found.append(element.line.colour)
        elif isinstance(element, TimerElement):
            found.append(element.colour)
    return list(dict.fromkeys(colour4(c) for c in found))


def _edge_colours(scene: Scene) -> list[str]:
    """Return the edge colours of all text in the scene."""
    found: list[str] = []
    for element in scene.elements:
        if is_pixel_title(element):
            continue
        if isinstance(element, LineElement):
            found += [element.colours.edge, *(t.colours.edge for t in element.turns)]
        elif isinstance(element, CardElement):
            found += [line.edge_colour for line in element.lines]
        elif isinstance(element, PreviewElement):
            found.append(element.line.edge_colour)
        elif isinstance(element, TimerElement):
            found.append(element.edge_colour)
    return found


def _bar_colours(scene: Scene) -> list[str]:
    """Return the colours of the countdowns and progress bars of the scene."""
    found: list[str] = []
    for element in scene.elements:
        if isinstance(element, CountdownElement):
            found.append(element.colour)
        elif isinstance(element, ProgressElement):
            found += [element.fill, element.frame]
    return found


def build_palette(scene: Scene) -> Palette:
    """Return the palette of ``scene``.

    Args:
        scene: A scene laid out for the CD+G screen.

    Raises:
        StageError: ``cdg-palette`` if the colours need more than the 16 entries, naming them.
    """
    background = colour4(scene.background)
    text = _text_colours(scene)
    flats = [background]
    for colour in (colour4(c) for c in [*_edge_colours(scene), *_bar_colours(scene)]):
        if colour not in flats and colour not in text:
            flats.append(colour)
    flat_pairs = (len(flats) + 1) // 2
    if flat_pairs + len(text) > PAIRS:
        names = ", ".join(hex_of(c) for c in [*flats, *text])
        raise StageError(
            "cdg-palette",
            f"the look needs {len(flats)} flat colours and {len(text)} text colours "
            f"(each with a shade), more than the {PALETTE_SIZE} entries of CD+G allow: {names}",
        )
    entries: list[Colour4] = [background] * PALETTE_SIZE
    flat_index: dict[Colour4, int] = {}
    for position, colour in enumerate(flats):
        entries[position] = colour
        flat_index[colour] = position
    text_index: dict[Colour4, int] = {}
    for number, colour in enumerate(text):
        first = 2 * (flat_pairs + number)
        entries[first] = colour
        entries[first + 1] = shade_of(colour, background)
        text_index[colour] = first
    return Palette(tuple(entries), 0, text_index, flat_index)


TITLE_COLOURS = (FIELD_COLOUR, EDGE_COLOUR, *BAND_COLOURS, TEXT_COLOUR)
"""The colours every start screen has, in the order of their entries: the field (entry 0), the edge,
the seven bands (the amber of the rule and the artist is the second) and white."""


def build_title_palette(scene: Scene) -> Palette | None:
    """Return the palette of the start screen with pixel letters, ``None`` if there is none.

    The fixed colours come first, then the colour of each name on the screen, each once; a colour
    that is there already shares its entry. A screen with five singers and a group fits.

    Raises:
        StageError: ``cdg-palette`` if the colours need more than the 16 entries.
    """
    title = pixel_title(scene)
    if title is None:
        return None
    colours = list(
        dict.fromkeys(colour4(c) for c in [*TITLE_COLOURS, *(line.colour for line in title.lines)])
    )
    if len(colours) > PALETTE_SIZE:
        names = ", ".join(hex_of(c) for c in colours)
        raise StageError(
            "cdg-palette",
            f"the start screen needs {len(colours)} colours, more than the {PALETTE_SIZE} entries "
            f"of CD+G allow: {names}",
        )
    index = {colour: number for number, colour in enumerate(colours)}
    entries = colours + [colours[0]] * (PALETTE_SIZE - len(colours))
    return Palette(tuple(entries), 0, index, index, shaded=False)
