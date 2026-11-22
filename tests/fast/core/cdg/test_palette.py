"""Stage 1: the CD+G palette: 12-bit colours, at most 16 entries, sung = unsung XOR a mask."""

import pytest

from fakes.scenes import builtin_profile, cdg_entchen, cdg_scene_of, profile
from vocatron.core.cdg.palette import PAIRS, build_palette, colour4, hex_of, shade_of
from vocatron.core.errors import StageError
from vocatron.core.layout import sample
from vocatron.core.scene import LineElement, Scene, TimerElement

EVERYONE = ["1", "2", "3", "4", "5", "all"]


def six_singers() -> Scene:
    """The folk songs with every singer and the group, so all six sung colours are on screen."""
    text = sample.ENTCHEN + sample.HAENSCHEN
    song = sample.timed_song(text, start=9.0, singers=[*EVERYONE, *EVERYONE])
    return cdg_scene_of(song, sample.song_text("Lieder", "Volk", 120.0, {}), profile())


def test_colours_are_rounded_to_12_bits() -> None:
    assert colour4("#3399ff") == (3, 9, 15)
    assert colour4("#000000") == (0, 0, 0)
    assert colour4("#ffffff") == (15, 15, 15)
    assert colour4("#080808") == (0, 0, 0)
    assert colour4("#0a0a0a") == (1, 1, 1)
    assert hex_of((3, 9, 15)) == "#3399ff"


def test_the_shade_lies_between_ink_and_background() -> None:
    assert shade_of((15, 15, 15), (0, 0, 0)) == (8, 8, 8)
    assert shade_of((3, 9, 15), (3, 9, 15)) == (3, 9, 15)


def test_the_palette_has_16_entries_of_12_bit_colours() -> None:
    palette = build_palette(cdg_entchen())
    assert len(palette.entries) == 16
    assert all(0 <= value <= 15 for entry in palette.entries for value in entry)
    assert palette.background == 0
    assert palette.entries[0] == colour4(cdg_entchen().background)


def test_every_sung_colour_is_its_unsung_index_xor_one_mask_for_ink_and_shade() -> None:
    scene = six_singers()
    palette = build_palette(scene)
    groups = {(line.colours.unsung, line.colours.sung) for line in scene.lines()}
    assert len(groups) == 6  # five singers and the group
    masks = set()
    for unsung, sung in groups:
        ink_u, shade_u = palette.ink(unsung)
        ink_s, shade_s = palette.ink(sung)
        mask = palette.mask(unsung, sung)
        assert ink_s == ink_u ^ mask
        assert shade_s == shade_u ^ mask
        assert mask > 0 and mask % 2 == 0  # ink and shade stay a pair of neighbours
        masks.add(mask)
    assert len(masks) == 6  # every group has its own mask
    assert len(palette.entries) == 16


def test_the_shade_follows_its_ink_and_is_half_way_to_the_background() -> None:
    scene = six_singers()
    palette = build_palette(scene)
    for line in scene.lines():
        for colour in (line.colours.unsung, line.colours.sung):
            ink, shade = palette.ink(colour)
            assert palette.entries[ink] == colour4(colour)
            assert palette.entries[shade] == shade_of(colour4(colour), palette.entries[0])


def test_a_colour_that_is_not_in_the_scene_is_an_error() -> None:
    palette = build_palette(cdg_entchen())
    with pytest.raises(KeyError):
        palette.ink("#123456")
    with pytest.raises(KeyError):
        palette.flat("#123456")


def test_an_edge_that_differs_from_the_background_takes_an_entry_of_its_own() -> None:
    plain = build_palette(cdg_entchen())
    edged = build_palette(cdg_entchen(profile(colours={"singer1": {"edge": "#ff0000"}})))
    red = edged.flat("#ff0000")
    assert edged.entries[red] == (15, 0, 0)
    assert len(set(edged.entries)) > len(set(plain.entries))
    assert plain.flat("#000000") == plain.background


def test_a_countdown_in_the_colour_of_the_text_shares_its_entry() -> None:
    scene = six_singers()
    palette = build_palette(scene)
    group = scene.lines()[5].colours.sung
    assert palette.flat(group) == palette.ink(group)[0]


def test_more_colours_than_the_palette_holds_fail_with_their_names() -> None:
    scene = six_singers()
    crowded = scene.model_copy(
        update={
            "elements": [
                e.model_copy(
                    update={
                        "colours": e.colours.model_copy(
                            update={"unsung": f"#{(n * 20 + 40) % 256:02x}4020"}
                        )
                    }
                )
                if isinstance(e, LineElement)
                else e
                for n, e in enumerate(scene.elements)
            ]
        }
    )
    with pytest.raises(StageError, match="more than the 16 entries") as caught:
        build_palette(crowded)
    assert caught.value.kind == "cdg-palette"
    assert "#" in str(caught.value)
    assert PAIRS == 8


def test_the_timer_is_text_in_its_colour_and_its_edge_is_a_flat_colour() -> None:
    scene = cdg_entchen(builtin_profile("three-line"))
    timer = next(e for e in scene.elements if isinstance(e, TimerElement))
    palette = build_palette(scene)
    ink, shade = palette.ink(timer.colour)  # a text colour with its shade
    assert palette.entries[ink] == colour4(timer.colour) and shade == ink + 1
    assert colour4(timer.edge_colour) in palette.flat_entries
    without = scene.model_copy(update={"elements": [e for e in scene.elements if e is not timer]})
    assert colour4(timer.colour) not in build_palette(without).text_entries  # only the timer
    assert build_palette(without).flat(timer.colour) is not None  # the countdown bar's colour


def test_a_timer_in_a_colour_of_its_own_takes_a_text_entry() -> None:
    scene = cdg_entchen(builtin_profile("three-line"))
    timer = next(e for e in scene.elements if isinstance(e, TimerElement))
    odd = timer.model_copy(update={"colour": "#00ff00"})
    changed = scene.model_copy(
        update={"elements": [odd if e is timer else e for e in scene.elements]}
    )
    after = build_palette(changed)
    assert colour4("#00ff00") in after.text_entries
    assert colour4(timer.colour) not in after.text_entries
