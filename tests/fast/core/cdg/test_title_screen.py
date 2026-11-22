"""Stage 1: the start screen with the wordmark on CD+G: its own palette, its draw and the swap.

The pixel letters and the title palette are checked on the scene, the stream through our decoder
(ADR-0056): the screen is drawn in its own colours within three seconds (also in the real font,
with long texts and five singers, in every CD+G look), one memory preset and the song's colour
table replace them when it ends, and the song is drawn only after that. A look with
``title.form: plain`` writes the stream of before, byte for byte.
"""

import hashlib

import numpy as np
import pytest
from pydantic import JsonValue

from fakes.raster import FakeRasteriser
from fakes.resources import FakeResources
from fakes.scenes import builtin_profile, cdg_duet, cdg_entchen, cdg_scene_of
from vocatron.core.cdg import PACKETS_PER_SECOND, CdgOp, decode
from vocatron.core.cdg.fit import Fit, write_step
from vocatron.core.cdg.look import fit_steps
from vocatron.core.cdg.palette import (
    PALETTE_SIZE,
    TITLE_COLOURS,
    build_palette,
    build_title_palette,
    colour4,
    pixel_title,
)
from vocatron.core.cdg.raster import (
    CLEAR,
    INK,
    INK_ONLY_MIN,
    NONE,
    SHADE_MIN,
    TICKS_PER_SECOND,
    TargetFrames,
    TextSpec,
    ink_only,
    outline,
    text_sprite,
)
from vocatron.core.cdg.stream import CdgStream, build_stream
from vocatron.core.errors import StageError
from vocatron.core.layout import sample
from vocatron.core.layout.cards import ROW_PITCH
from vocatron.core.layout.mark import PIXEL_FLOOR_PX, PIXEL_NAME_PX
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.lyrics.document import SingerInfo
from vocatron.core.profiles.model import CLASSIC_PROFILES, Profile
from vocatron.core.scene import CardElement, Colours, Scene
from vocatron.core.wordmark import (
    AMBER,
    BAND_COLOURS,
    EDGE_COLOUR,
    FIELD_COLOUR,
    TEXT_COLOUR,
    pixel_band,
    pixel_word_cells,
)
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser

SETTLED_WITHIN = 3.0
"""The whole start screen is drawn this many seconds after the start, well before it ends
(ADR-0056)."""
OLD_INTRO: dict[str, JsonValue] = {"solo": 6.0, "group": 7.0}
OLD_STREAMS = {
    "entchen": "bb95052717cd2f1de5a11877a830ff39cf749989e3fe6ea23d126099e17b9142",
    "duet": "ad512b3edcd418dd70af7316fdb43b4b639767f7a2efdd8f29295b77ad79a37b",
}
"""The digests of the streams of the two folk songs that the code before the start screen with
pixel letters wrote (plain start screen, the times of that time); only a deliberate change of
the stream may change them."""
FIVE = {
    1: SingerInfo(name="Anna", colour="#22aa55"),
    2: SingerInfo(name="Ben", colour="#dd4466"),
    3: SingerInfo(name="Cleo", colour="#4488ff"),
    4: SingerInfo(name="Dora", colour="#ffaa00"),
    5: SingerInfo(name="Emil", colour="#aa66ff"),
}


def wordmark(title: dict[str, JsonValue] | None = None, **overrides: JsonValue) -> Profile:
    """The classic look with the wordmark start screen (``title`` adds to its ``title`` section)."""
    return builtin_profile(
        "two-line-turns", title={"form": "wordmark", **(title or {})}, **overrides
    )


def everyone_scene() -> Scene:
    """The folk songs sung by all five singers and the group, named, with the wordmark."""
    text = sample.ENTCHEN + sample.HAENSCHEN
    song = sample.timed_song(text, start=9.0, singers=["1", "2", "3", "4", "5", "all"] * 4)
    names = {**FIVE, 3: SingerInfo(name="Cleo", colour="#4488ff")}
    return cdg_scene_of(song, sample.song_text("Lieder", "Volk", 120.0, names), wordmark())


def title_card(scene: Scene) -> CardElement:
    found = pixel_title(scene)
    assert found is not None
    return found


def written(scene: Scene, clear_first: bool = False) -> CdgStream:
    return build_stream(scene, FakeRasteriser(), 3, clear_first)


# ------------------------------------------------------------------ the title palette


def test_the_title_palette_starts_with_the_field_the_edge_the_bands_and_white() -> None:
    palette = build_title_palette(cdg_entchen(wordmark()))
    assert palette is not None
    wanted = [colour4(c) for c in (FIELD_COLOUR, EDGE_COLOUR, *BAND_COLOURS, TEXT_COLOUR)]
    assert list(palette.entries[:10]) == wanted == [colour4(c) for c in TITLE_COLOURS]
    assert palette.background == 0 and palette.entries[0] == colour4(FIELD_COLOUR)
    assert len(palette.entries) == PALETTE_SIZE
    assert not palette.shaded


def test_amber_is_the_second_band_and_takes_no_entry_of_its_own() -> None:
    palette = build_title_palette(cdg_entchen(wordmark()))
    assert palette is not None
    assert colour4(AMBER) == colour4(BAND_COLOURS[1])
    assert palette.ink(AMBER) == palette.ink(BAND_COLOURS[1]) == (3, 3)
    assert palette.flat(BAND_COLOURS[1]) == 3
    assert palette.ink(TEXT_COLOUR) == (9, 9)  # no shade: the ink's entry twice


def test_five_singers_and_a_group_fit_each_name_colour_in_one_entry() -> None:
    scene = everyone_scene()
    palette = build_title_palette(scene)
    assert palette is not None
    names = {line.colour for line in title_card(scene).lines[2:]}
    assert len(names) >= 5
    indices = {palette.ink(colour)[0] for colour in names}
    assert len(indices) == len(names) and min(indices) >= 10  # after the fixed colours
    assert len(set(palette.entries)) <= PALETTE_SIZE


def test_a_name_in_a_colour_that_is_there_already_shares_its_entry() -> None:
    names = {
        1: SingerInfo(name="Anna", colour=TEXT_COLOUR),
        2: SingerInfo(name="Ben", colour=AMBER),
    }
    song = sample.timed_song(sample.ENTCHEN, start=9.0, singers=["1", "2", "1", "2", "1"])
    scene = cdg_scene_of(song, sample.song_text("T", "A", 60.0, names), wordmark())
    palette = build_title_palette(scene)
    assert palette is not None
    sung = [line.colour for line in title_card(scene).lines[2:4]]
    assert [palette.ink(c)[0] for c in sung] == [9, 3]
    assert palette.entries[10] == palette.entries[0]  # nothing was added: the rest is the field


def test_more_than_sixteen_colours_are_refused_naming_them() -> None:
    scene = cdg_entchen(wordmark())
    title = title_card(scene)
    seven = [
        line.model_copy(update={"colour": f"#{n * 34 + 17:02x}0000"})
        for n, line in enumerate([title.lines[0]] * 7)
    ]
    crowded = scene.model_copy(
        update={
            "elements": [
                e.model_copy(update={"lines": seven}) if e is title else e for e in scene.elements
            ]
        }
    )
    with pytest.raises(StageError, match="start screen needs 17 colours") as raised:
        build_title_palette(crowded)
    assert raised.value.kind == "cdg-palette"
    assert "#110000, #330000" in str(raised.value)  # every colour named, comma separated


def test_a_scene_without_the_pixel_wordmark_has_no_title_palette() -> None:
    assert build_title_palette(cdg_entchen()) is None  # a plain start screen
    plain_form = builtin_profile("two-line-turns", title={"form": "plain"})
    assert build_title_palette(cdg_entchen(plain_form)) is None


def test_the_songs_palette_does_not_count_the_colours_of_the_start_screen() -> None:
    scene = everyone_scene()
    without = scene.model_copy(
        update={"elements": [e for e in scene.elements if e is not title_card(scene)]}
    )
    assert build_palette(scene) == build_palette(without)
    entries = set(build_palette(scene).entries)
    assert (
        not {colour4(c) for c in BAND_COLOURS[:1]} & entries
    )  # the first band is not a song colour


# ------------------------------------------------------------------ text in ink only


def test_text_without_shades_is_ink_where_the_coverage_reaches_the_limit() -> None:
    coverage = np.array([[0, INK_ONLY_MIN - 1, INK_ONLY_MIN, 255]], dtype=np.uint8)
    assert ink_only(coverage).tolist() == [[NONE, NONE, INK, INK]]


class ConstantRasteriser:
    """Draws every text as one row of the given coverage values."""

    def __init__(self, values: list[int]) -> None:
        self.values = values

    def coverage(self, text: str, size: float) -> np.ndarray:
        return np.array([self.values], dtype=np.uint8)


def test_the_start_screens_text_is_drawn_in_ink_only_without_the_shade_level() -> None:
    palette = build_title_palette(cdg_entchen(wordmark()))
    assert palette is not None
    white = Colours(unsung=TEXT_COLOUR, sung=TEXT_COLOUR, edge=FIELD_COLOUR)
    coverage = [SHADE_MIN, INK_ONLY_MIN - 1, INK_ONLY_MIN, 255]
    sprite = text_sprite(
        ConstantRasteriser(coverage), palette, TextSpec("ab", 1.0, 1.0, 100.0, 100.0), [], [white]
    )
    ink = palette.ink(TEXT_COLOUR)[0]
    middle = sprite.unsung[1, 1:-1].tolist()  # inside the one-pixel edge, which is the field
    assert middle == [CLEAR, CLEAR, ink, ink]  # a shade pixel of the song's palette is left out


def test_the_frame_is_a_closed_one_pixel_outline_with_rounded_corners() -> None:
    drawn = outline(10, 12, 4)
    assert ["".join("#" if x else "." for x in row) for row in drawn.tolist()] == [
        "..########..",
        ".#........#.",
        "#..........#",
        "#..........#",
        "#..........#",
        "#..........#",
        "#..........#",
        "#..........#",
        ".#........#.",
        "..########..",
    ]
    wide = outline(12, 16, 6)
    assert ["".join("#" if x else "." for x in row) for row in wide[:4].tolist()] == [
        "....########....",
        "..##........##..",
        ".#............#.",
        ".#............#.",
    ]
    assert outline(4, 5, 0).sum() == 2 * 5 + 2 * 2  # square corners: the whole border


# ------------------------------------------------------------------ the stream


@pytest.fixture(scope="module")
def stream() -> tuple[Scene, CdgStream]:
    scene = cdg_entchen(wordmark())
    return scene, written(scene)


def test_the_screen_is_drawn_in_time_and_stays_until_it_ends(
    stream: tuple[Scene, CdgStream],
) -> None:
    scene, result = stream
    title = title_card(scene)
    settled = result.scheduled.settled
    assert settled[0] < SETTLED_WITHIN * TICKS_PER_SECOND
    assert result.targets.swap_tick == round(title.end * TICKS_PER_SECOND) > 400  # four seconds
    drawn = decode(result.stream, [SETTLED_WITHIN, title.end - 0.01])
    assert np.array_equal(
        drawn.frames[0], result.targets.frame(round(SETTLED_WITHIN * TICKS_PER_SECOND) - 1)
    )
    assert np.array_equal(drawn.frames[0], drawn.frames[1])  # nothing changes until it ends


def test_the_start_screen_is_drawn_in_the_title_palette_letters_banded_field_around(
    stream: tuple[Scene, CdgStream],
) -> None:
    scene, result = stream
    title_palette = build_title_palette(scene)
    assert title_palette is not None
    mark = title_card(scene).mark
    assert mark is not None
    frame = decode(result.stream, [SETTLED_WITHIN])
    assert frame.palettes[0] == title_palette.entries
    shown = frame.frames[0]
    left, top, cell = round(mark.word.x), round(mark.word.y), round(mark.scale)
    cells = pixel_word_cells()
    rows = len(cells) * cell
    bands = [title_palette.flat(c) for c in BAND_COLOURS]
    seen: set[int] = set()
    for row, cells_row in enumerate(cells):
        for column, on in enumerate(cells_row):
            index = int(shown[top + row * cell + 1, left + column * cell + 1])
            if on:
                seen.add(index)
                assert index in bands, (row, column)
            else:
                assert index not in bands
    assert seen == set(bands)  # every band shows in the letters
    cyan = title_palette.flat(EDGE_COLOUR)
    assert shown[top + rows // 2, left - 10] == 0  # the field is outside a letter
    middle = round(mark.frame.y + mark.frame.h / 2)
    assert shown[middle, round(mark.frame.x)] == cyan  # the side of the frame
    assert shown[round(mark.frame.y), round(mark.frame.x + mark.frame.w / 2)] == cyan  # its top
    assert shown[middle, round(mark.frame.x) + 1] == 0  # inside the frame: the field


def test_every_pixel_of_the_word_has_its_band_the_edge_or_the_field(
    stream: tuple[Scene, CdgStream],
) -> None:
    scene, result = stream
    mark = title_card(scene).mark
    palette = build_title_palette(scene)
    assert mark is not None and palette is not None
    shown = decode(result.stream, [SETTLED_WITHIN]).frames[0]
    top, left, cell = round(mark.word.y), round(mark.word.x), round(mark.scale)
    cells = pixel_word_cells()
    height = len(cells) * cell
    background = {0, palette.flat(EDGE_COLOUR)}
    for y in range(height):
        band = palette.flat(BAND_COLOURS[pixel_band(y, height)])
        for x in range(len(cells[0]) * cell):
            index = int(shown[top + y, left + x])
            if cells[y // cell][x // cell]:
                assert index == band, (y, x)
            else:
                assert index in background, (y, x)


def test_the_rule_is_amber(stream: tuple[Scene, CdgStream]) -> None:
    scene, result = stream
    mark = title_card(scene).mark
    palette = build_title_palette(scene)
    assert mark is not None and mark.rule is not None and palette is not None
    shown = decode(result.stream, [SETTLED_WITHIN]).frames[0]
    rule = shown[
        round(mark.rule.y) : round(mark.rule.y + mark.rule.h),
        round(mark.rule.x) : round(mark.rule.x + mark.rule.w),
    ]
    assert rule.size > 0 and (rule == palette.ink(AMBER)[0]).all()


def test_the_edge_of_the_letters_is_one_pixel_of_cyan(stream: tuple[Scene, CdgStream]) -> None:
    scene, result = stream
    mark = title_card(scene).mark
    palette = build_title_palette(scene)
    assert mark is not None and palette is not None
    shown = decode(result.stream, [SETTLED_WITHIN]).frames[0]
    cyan, first_band = palette.flat(EDGE_COLOUR), palette.flat(BAND_COLOURS[0])
    top, left = round(mark.word.y), round(mark.word.x)
    # the first letter, V, has its stem in the first column: field, edge, letter
    assert [int(x) for x in shown[top + 1, left - 2 : left + 1]] == [0, cyan, first_band]
    assert [int(x) for x in shown[top - 2 : top + 1, left + 1]] == [0, cyan, first_band]


def test_the_header_loads_the_title_palette_and_clears_to_the_field(
    stream: tuple[Scene, CdgStream],
) -> None:
    scene, result = stream
    title_palette = build_title_palette(scene)
    assert title_palette is not None
    events = decode(result.stream).events
    first = [e for e in events if e.op is CdgOp.PALETTE][:2]
    assert first[0].colours + first[1].colours == title_palette.entries
    presets = [e for e in events if e.op in (CdgOp.MEMORY_PRESET, CdgOp.BORDER_PRESET)][:2]
    assert [e.colour0 for e in presets] == [0, 0]  # the field: entry 0 of the title palette


def test_when_the_screen_ends_one_memory_preset_and_the_songs_palette_replace_it(
    stream: tuple[Scene, CdgStream],
) -> None:
    scene, result = stream
    swap = result.targets.swap_tick
    assert swap is not None
    slot = swap * PACKETS_PER_SECOND // TICKS_PER_SECOND
    events = [e for e in decode(result.stream).events if e.packet >= slot - 4]
    assert [e.op for e in events[:3]] == [CdgOp.MEMORY_PRESET, CdgOp.PALETTE, CdgOp.PALETTE]
    preset, low, high = events[:3]
    assert preset.packet == slot and preset.colour0 == 0
    assert (low.first_colour, high.first_colour) == (0, 8)
    assert low.colours + high.colours == result.palette.entries
    after = decode(result.stream, [(slot + 2.5) / PACKETS_PER_SECOND])  # the three packets, no tile
    assert after.palettes[0] == result.palette.entries
    assert (after.frames[0] == 0).all()  # cleared: the look's background and nothing else yet


def test_the_song_is_drawn_only_after_the_swap_and_the_first_line_in_time(
    stream: tuple[Scene, CdgStream],
) -> None:
    scene, result = stream
    swap = result.targets.swap_tick
    assert swap is not None
    slot = swap * PACKETS_PER_SECOND // TICKS_PER_SECOND
    tiles = [e for e in decode(result.stream).events if e.op in (CdgOp.TILE, CdgOp.TILE_XOR)]
    in_between = [e for e in tiles if SETTLED_WITHIN * PACKETS_PER_SECOND < e.packet < slot]
    assert in_between == []  # nothing of the song, nothing of the start screen
    assert result.scheduled.missed == ()
    (first, *_) = scene.lines()
    shown = decode(result.stream, [first.sing_start - 1 / PACKETS_PER_SECOND])
    assert shown.palettes[0] == result.palette.entries


def test_a_pause_in_the_screens_packets_does_not_count_into_the_songs_lag(
    stream: tuple[Scene, CdgStream],
) -> None:
    _, result = stream
    assert 0 < result.scheduled.draw_lag < 1.0  # the start screen took longer (about 1.8 s)


TEXTS = {
    "solo, short title": ("Lanterns Over Marrow Bay", "The Quiet Tuesdays", 0),
    "solo, 45 characters": (
        "A Long Way Home Through the Rain and the Night",
        "The Quiet Tuesdays",
        0,
    ),
    "duet": ("Paper Boats on a Summer River", "Anna Field & Ben Stone", 2),
    "three singers": ("Lanterns Over Marrow Bay", "The Quiet Tuesdays", 3),
    "five singers and a group": ("Lanterns Over Marrow Bay", "The Quiet Tuesdays", 5),
    "80 characters": (
        "Everything We Ever Said Under the Old Bridge When the Lights Went Out at Midnight",
        "The Quiet Tuesdays and the Very Long Orchestra",
        0,
    ),
}
"""Invented texts that keep the wordmark screen in every CD+G look, the worst for the draw: a title
and an artist on two rows each, three names side by side, five names and a group on two rows."""
NAMES = ["Anna", "Ben", "Cleo", "Dora", "Emil"]
TOO_LONG: dict[str, tuple[str, str, list[str]]] = {
    "five long names": ("Lanterns", "Quiet", ["Maximilian Wolfgang", "Konstantina Elisabeth"] * 3),
    "a title of 120 characters": ("Everything We Said " * 7, "Quiet", []),
}
"""Texts whose smallest text would be under the floor: the plain card in every look."""


def singers_of(count: int) -> dict[int, SingerInfo]:
    return {n: SingerInfo(name=NAMES[n - 1]) for n in range(1, count + 1)}


def real_fit(look: str, title: str, artist: str, singers: dict[int, SingerInfo]) -> Fit:
    """The first fit of ``look`` in the real font, with the wordmark start screen asked for."""
    chosen = builtin_profile(look, title={"form": "wordmark"})
    order = [*(str(n) for n in singers), *(["all"] if singers else [])] or ["1"]
    song = sample.timed_song(sample.ENTCHEN + sample.HAENSCHEN, start=0.0, singers=order * 40)
    font = FakeResources().font_file()
    fit = write_step(
        phrases_from(song.words, song.lines, chosen.font.case),
        sample.song_text(title, artist, 90.0, singers),
        chosen,
        fit_steps(chosen)[0],
        PillowMeasurer(font),
        PillowRasteriser(font),
    )
    return fit


def real_title(look: str, title: str, artist: str, singers: dict[int, SingerInfo]) -> CardElement:
    """The start screen of ``look`` in the real font."""
    fit = real_fit(look, title, artist, singers)
    return next(e for e in fit.scene.elements if isinstance(e, CardElement) and e.kind == "title")


@pytest.mark.parametrize("look", CLASSIC_PROFILES)
@pytest.mark.parametrize("texts", TEXTS, ids=str)
def test_long_texts_in_the_real_font_are_drawn_in_time_and_keep_the_wordmark(
    look: str, texts: str
) -> None:
    title, artist, count = TEXTS[texts]
    fit = real_fit(look, title, artist, singers_of(count))
    card = title_card(fit.scene)  # the wordmark screen, in every look
    assert fit.written.targets.swap_tick == round(card.end * TICKS_PER_SECOND) >= 400
    assert fit.written.scheduled.settled[0] < SETTLED_WITHIN * TICKS_PER_SECOND


@pytest.mark.parametrize("look", CLASSIC_PROFILES)
@pytest.mark.parametrize("texts", TEXTS, ids=str)
def test_the_texts_have_the_same_sizes_in_every_look_and_none_is_below_the_floor(
    look: str, texts: str
) -> None:
    title, artist, count = TEXTS[texts]
    card = real_title(look, title, artist, singers_of(count))
    assert card.mark is not None
    sizes = [line.size for line in card.lines]
    assert min(sizes) >= PIXEL_FLOOR_PX - 1e-3
    assert all(line.box.inside(card.mark.frame) for line in card.lines)
    other = real_title("two-line-turns", title, artist, singers_of(count))
    assert [line.text for line in card.lines] == [line.text for line in other.lines]
    assert [round(size, 1) for size in sizes] == [round(line.size, 1) for line in other.lines]


@pytest.mark.parametrize("look", CLASSIC_PROFILES)
def test_a_title_wrapped_onto_two_rows_has_one_size_for_both(look: str) -> None:
    title, artist, _ = TEXTS["80 characters"]
    card = real_title(look, title, artist, {})
    rows = [line for line in card.lines if line.colour == TEXT_COLOUR]
    assert len(rows) == 2 and rows[0].size == rows[1].size
    assert rows[1].box.y - rows[0].box.y == pytest.approx(ROW_PITCH * rows[0].size, abs=0.01)


@pytest.mark.parametrize("look", CLASSIC_PROFILES)
def test_five_singers_and_a_group_stand_side_by_side_in_two_rows(look: str) -> None:
    title, artist, count = TEXTS["five singers and a group"]
    card = real_title(look, title, artist, singers_of(count))
    names = card.lines[2:]
    assert len(names) == 6 and {line.size for line in names} == {PIXEL_NAME_PX}
    assert len({line.box.y for line in names}) <= 2  # as few rows as fit
    assert len({line.colour for line in names}) == 6  # each in its own colour


@pytest.mark.parametrize("look", CLASSIC_PROFILES)
def test_names_a_little_too_wide_for_two_to_a_row_stay_two_to_a_row_rather_than_the_plain_card(
    look: str,
) -> None:
    singers = {n: SingerInfo(name="Wim Wouwermans-Molnar") for n in range(1, 4)}  # and "Alle"
    card = real_title(look, "Lanterns", "Quiet", singers)
    assert card.mark is not None  # one to a row is wide enough, but four rows are too many
    names = card.lines[2:]
    assert len({line.box.y for line in names}) == 2  # two and two, a little smaller
    assert PIXEL_FLOOR_PX <= min(line.size for line in names) < PIXEL_NAME_PX


@pytest.mark.parametrize("look", CLASSIC_PROFILES)
@pytest.mark.parametrize("texts", TOO_LONG, ids=str)
def test_texts_that_would_be_below_the_floor_give_the_plain_card_in_every_look(
    look: str, texts: str
) -> None:
    title, artist, names = TOO_LONG[texts]
    singers = {n: SingerInfo(name=name) for n, name in enumerate(names, 1)}
    card = real_title(look, title, artist, singers)
    assert card.mark is None  # the plain card, the texts as written
    assert [line.text for line in card.lines][:2] == [title, artist]


def test_a_duet_with_names_has_the_same_swap() -> None:
    scene = cdg_duet(wordmark())
    result = written(scene)
    assert result.targets.swap_tick is not None
    assert result.scheduled.settled[0] < SETTLED_WITHIN * TICKS_PER_SECOND


def test_a_start_screen_shorter_than_four_seconds_writes_the_plain_card_and_no_swap() -> None:
    short = wordmark(title={"form": "wordmark", "min": 2.0, "min_short": 2.0}, intro=OLD_INTRO)
    song = sample.timed_song(sample.ENTCHEN, start=5.0)
    scene = cdg_scene_of(
        song,
        sample.song_text("T", "A", 60.0, {}),
        short.model_copy(
            update={"intro": short.intro.model_copy(update={"solo": 0.0, "group": 0.0})}
        ),
    )
    title = next(e for e in scene.elements if isinstance(e, CardElement) and e.kind == "title")
    assert title.end == pytest.approx(2.0) and title.mark is None
    result = written(scene)
    assert result.targets.swap_tick is None
    palettes = [e for e in decode(result.stream).events if e.op is CdgOp.PALETTE]
    assert len(palettes) == 2  # the header's two halves, the song's palette; no second load
    assert palettes[0].colours + palettes[1].colours == result.palette.entries


# ------------------------------------------------------------------ title.form: plain


@pytest.mark.parametrize("name", ["entchen", "duet"])
def test_the_plain_form_writes_the_stream_of_before_byte_for_byte(name: str) -> None:
    plain = builtin_profile("two-line-turns", intro=OLD_INTRO, title={"min_short": 2.0})
    scene = cdg_entchen(plain) if name == "entchen" else cdg_duet(plain)
    result = written(scene, clear_first=True)
    assert hashlib.sha256(result.stream).hexdigest() == OLD_STREAMS[name]


def test_the_pixel_start_screen_cannot_be_drawn_without_its_palette() -> None:
    scene = cdg_entchen(wordmark())
    with pytest.raises(ValueError, match="needs its palette"):
        TargetFrames(scene, build_palette(scene), FakeRasteriser())
