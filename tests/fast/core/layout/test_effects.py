"""Stage 1: the effects in the scene: pop room, transitions, the moving background (ADR-0032)."""

import pytest
from pydantic import JsonValue

from conformance.scene_rules import check_scene
from fakes.measure import FixedMeasurer
from fakes.phrases import line
from fakes.scenes import entchen_with, profile
from vocatron.core.layout.build import (
    MIN_TRANSITION,
    Context,
    SongText,
    layout,
    safe_area,
    transition_times,
)
from vocatron.core.layout.fit import NO_POP, Fitted, fit, pop_room, popped_width
from vocatron.core.layout.phrases import Phrase, Piece
from vocatron.core.layout.place import Placement
from vocatron.core.layout.rules import scene_findings
from vocatron.core.profiles.model import Pop, Profile
from vocatron.core.scene import LineElement, Scene

MEASURER = FixedMeasurer()  # a character is half the font size wide
FRAME = (960, 720)  # safe area 864 x 648; font size 0.12 of it is 77.76 px, a character 38.88 px
FADE: dict[str, JsonValue] = {"form": "fade", "time": 0.3}
SLIDE: dict[str, JsonValue] = {"form": "slide", "time": 0.3}
NO_INTRO: dict[str, JsonValue] = {"solo": 0.0, "group": 0.0}


def modern(**overrides: JsonValue) -> Profile:
    """The default look without its CD+G section, with effects."""
    return profile(cdg=None, intro=NO_INTRO, **overrides)


def scene_of(phrases: list[Phrase], chosen: Profile) -> Scene:
    built = layout(phrases, SongText("Titel", "Künstler", 60.0, {}), chosen, FRAME, MEASURER)
    check_scene(built, chosen)
    return built


def lines_of(scene: Scene) -> list[LineElement]:
    return scene.lines()


# --------------------------------------------------------------------------- defaults


def test_a_look_without_effects_has_no_effect_in_its_scene() -> None:
    scene = entchen_with(profile())
    look = scene.look
    assert (look.glow, look.glow_colour, look.pop_scale, look.upcoming_dim) == (0.0, None, 1.0, 0.0)
    assert look.transition == "none"
    assert scene.background_motion is None
    assert all((x.enter, x.exit) == (0.0, 0.0) for x in scene.lines())


def test_the_effects_of_a_look_are_in_the_scene() -> None:
    chosen = modern(
        glow={"sung": 0.7, "colour": "#ffffff"},
        pop={"scale": 1.1, "time": 0.2},
        upcoming={"dim": 0.4},
        transition=FADE,
        background_motion={"colours": ["#000011", "#110022"], "speed": 0.02},
    )
    scene = entchen_with(chosen)
    look = scene.look
    assert (look.glow, look.glow_colour) == (0.7, "#ffffff")
    assert (look.pop_scale, look.pop_time, look.upcoming_dim) == (1.1, 0.2, 0.4)
    assert look.transition == "fade"
    assert scene.background_motion is not None
    assert (scene.background_motion.colours, scene.background_motion.speed) == (
        ["#000011", "#110022"],
        0.02,
    )
    assert scene.background == chosen.background  # the plain colour stays for the cards' sake


def test_a_song_without_lines_keeps_the_moving_background() -> None:
    chosen = modern(background_motion={"colours": ["#000011", "#110022"]})
    scene = layout([], SongText("Titel", None, 30.0, {}), chosen, FRAME, MEASURER)
    assert scene.background_motion is not None


# --------------------------------------------------------------------------- transitions


def test_a_fade_takes_the_time_where_there_is_room_and_ends_before_the_singing() -> None:
    scene = entchen_with(modern(transition=FADE))
    for found in lines_of(scene):
        assert 0 < found.enter <= 0.3
        assert 0 < found.exit <= 0.3
        assert found.start + found.enter <= found.sing_start
        assert found.end - found.exit >= found.sing_end
    assert scene_findings(scene, modern(transition=FADE)) == []


def test_a_transition_never_goes_into_the_singing_and_is_left_out_where_there_is_no_room() -> None:
    # one slot and lines back to back: a line is replaced the moment it has been sung
    chosen = modern(slots=1, transition=SLIDE)
    phrases = [line(10.0, 11.0), line(11.0, 12.0), line(12.05, 13.0)]
    scene = scene_of(phrases, chosen)
    first, second, third = lines_of(scene)
    assert first.exit == 0 and second.exit == 0  # replaced when they end
    assert third.exit > 0
    for found in (first, second, third):
        assert found.start + found.enter <= found.sing_start
        assert found.end - found.exit >= found.sing_end


def test_a_transition_shorter_than_the_minimum_is_left_out() -> None:
    chosen = modern(slots=1, transition=FADE)
    phrases = [line(10.0, 11.0), line(11.0 + MIN_TRANSITION / 2, 12.0)]
    scene = scene_of(phrases, chosen)
    assert lines_of(scene)[0].exit == 0


def test_a_wipe_shifted_later_keeps_the_exit_out_of_the_wipe() -> None:
    chosen = modern(transition=FADE, wipe={"offset": 0.5})
    scene = entchen_with(chosen)
    for found in lines_of(scene):
        assert found.end - found.exit >= found.sing_end + 0.5 - 0.002


def test_a_wipe_shifted_earlier_keeps_the_entrance_out_of_the_wipe() -> None:
    chosen = modern(transition=FADE, wipe={"offset": -0.5})
    scene = entchen_with(chosen)
    for found in lines_of(scene):
        assert found.start + found.enter <= found.sing_start - 0.5 + 0.002


def test_the_rows_of_a_wrapped_line_come_and_go_together() -> None:
    chosen = modern(line_rows=2, transition=SLIDE)
    phrases = [line(10.0, 14.0, "eins zwei drei vier fünf sechs sieben acht"), line(15.0, 16.0)]
    rows = lines_of(scene_of(phrases, chosen))
    first_block = [x for x in rows if x.start == rows[0].start]
    assert len(first_block) == 2
    assert {(x.enter, x.exit) for x in first_block} == {(first_block[0].enter, first_block[0].exit)}
    assert first_block[0].enter > 0


def test_the_parts_of_a_split_line_take_neighbouring_slots_and_each_slides_in_its_own() -> None:
    chosen = modern(slots=3, transition=SLIDE)
    phrases = [
        line(10.0, 14.0, "eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf"),
        line(16.0, 17.0),
    ]
    scene = scene_of(phrases, chosen)
    parts = [x for x in lines_of(scene) if x.part in (0, 1)][:2]
    assert [x.part for x in parts] == [0, 1]
    assert parts[1].slot == parts[0].slot + 1  # top to bottom
    assert all(x.enter > 0 for x in parts)
    for found in parts:
        assert found.start + found.enter <= found.sing_start
        assert found.end - found.exit >= found.sing_end
    assert scene.look.transition == "slide"


def test_no_transition_gives_no_enter_or_exit_even_where_there_is_room() -> None:
    scene = entchen_with(modern(transition={"form": "none", "time": 0.5}))
    assert all((x.enter, x.exit) == (0.0, 0.0) for x in lines_of(scene))


# --------------------------------------------------------------------------- pop


def phrase_of(*words: tuple[str, float]) -> Phrase:
    """A line of one syllable per word, each starting at the given time and lasting 0.1 s."""
    return Phrase(
        "1",
        tuple(
            Piece(text + (" " if index < len(words) - 1 else ""), start, start + 0.1)
            for index, (text, start) in enumerate(words)
        ),
    )


def test_a_word_that_pops_needs_room_of_its_growth() -> None:
    sung = phrase_of(("aaaa", 0.0), ("bbbbbb", 1.0), ("cc", 2.0))  # a character is 5 px at size 10
    assert pop_room(sung, MEASURER, 10.0, Pop(scale=1.1)) == pytest.approx(0.1 * 6 * 5)
    assert popped_width(sung, MEASURER, 10.0, Pop(scale=1.1)) == pytest.approx(14 * 5 + 3.0)


def test_there_is_no_room_without_pop() -> None:
    sung = phrase_of(("aaaa", 0.0), ("bbbbbb", 1.0))
    assert pop_room(sung, MEASURER, 10.0, NO_POP) == 0.0
    assert popped_width(sung, MEASURER, 10.0, NO_POP) == MEASURER.width(sung.text, 10.0)


def test_words_that_start_within_the_pop_time_may_be_grown_together() -> None:
    quick = phrase_of(("aaaa", 0.0), ("bbbb", 0.1), ("cccc", 5.0))
    room = pop_room(quick, MEASURER, 10.0, Pop(scale=1.1, time=0.25))
    assert room == pytest.approx(0.1 * (4 + 4) * 5)  # the first two together, not the third


def test_a_line_that_would_just_fit_is_shrunk_when_its_words_pop() -> None:
    limit = 21.5 * 5  # 21 characters at size 10 are 105 px
    sung = phrase_of(("a" * 21, 0.0))  # one word: it cannot be split, so it is shrunk
    (plain,) = fit(sung, MEASURER, 10.0, 5.0, limit)
    (popping,) = fit(sung, MEASURER, 10.0, 5.0, limit, pop=Pop(scale=1.15))
    assert plain.size == 10.0
    assert popping.size < 10.0
    assert popped_width(sung, MEASURER, popping.size, Pop(scale=1.15)) <= limit


def test_a_line_that_would_just_fit_is_split_when_its_words_pop() -> None:
    sung = phrase_of(("aaaaaaaaaa", 0.0), ("bbbbbbbbbb", 1.0))  # 21 characters, 105 px
    assert len(fit(sung, MEASURER, 10.0, 5.0, 21.5 * 5)) == 1
    assert len(fit(sung, MEASURER, 10.0, 5.0, 21.5 * 5, pop=Pop(scale=1.15))) == 2


def test_a_two_row_line_is_fitted_with_the_room_of_its_popping_words() -> None:
    limit = 11.4 * 5.0
    sung = phrase_of(("aaaaa", 0.0), ("bbbbb", 1.0), ("ccccc", 2.0), ("ddddd", 3.0))
    plain = fit(sung, MEASURER, 10.0, 5.0, limit, 2)[0]
    popping = fit(sung, MEASURER, 10.0, 5.0, limit, 2, pop=Pop(scale=1.15))[0]
    assert len(plain.parts) == len(popping.parts) == 2
    assert plain.size == 10.0  # "aaaaa bbbbb" is 11 characters, 55 px of 60
    assert popping.size < plain.size  # the room of a word of five characters does not fit


@pytest.mark.parametrize("align", ["center", "left", "right"])
def test_a_popping_line_has_its_room_to_pop_on_the_right_inside_the_safe_area(align: str) -> None:
    # the text is drawn from its left edge (an7): a growing word pushes only the text after it to
    # the right, so the whole room lies right of the text and the grown line still ends in the box
    wide = line(10.0, 12.0, "a" * 21)  # one word of 816 px, of 851 at size 77.76
    plain = lines_of(scene_of([wide], modern(align=align)))[0]
    chosen = modern(align=align, pop={"scale": 1.15, "time": 0.25})
    popping = lines_of(scene_of([wide], chosen))[0]
    assert plain.size == pytest.approx(77.76)
    assert popping.size < plain.size
    pad = popping.edge + popping.shadow
    assert popping.text_x == pytest.approx(popping.box.x + pad, abs=0.002)
    grown = popping.text_x + MEASURER.width(popping.text, popping.size) * 1.15
    assert grown <= popping.box.right - pad + 0.002
    assert popping.box.right <= 48.0 + 864.0 + 0.002  # the right edge of the safe area


def test_a_look_without_pop_places_its_text_as_before() -> None:
    found = lines_of(scene_of([line(10.0, 12.0, "la la")], modern()))[0]
    assert found.text_x == pytest.approx(found.box.x + found.edge + found.shadow, abs=0.002)


def times_for(
    show: float, hide: float, sung: tuple[float, float], offset: float = 0.0
) -> tuple[float, float]:
    chosen = modern(transition=FADE, wipe={"offset": offset})
    safe = safe_area(chosen, FRAME)
    ctx = Context(chosen, MEASURER, SongText("T", None, 30.0, {}), safe, 77.76)
    item = Fitted(line(*sung), 77.76)
    return transition_times(ctx, item, Placement(0, show, hide))


def test_a_transition_of_exactly_the_minimum_is_kept_and_a_shorter_one_is_left_out() -> None:
    assert times_for(10.45, 12.0, (10.5, 11.0)) == (MIN_TRANSITION, 0.3)
    assert times_for(10.48, 11.02, (10.5, 11.0))[0] == 0.0
    assert times_for(10.0, 11.05, (10.5, 11.0)) == (0.3, MIN_TRANSITION)
    assert times_for(10.0, 11.02, (10.5, 11.0))[1] == 0.0


def test_the_syllables_of_a_word_pop_as_one_word_that_starts_with_its_first_syllable() -> None:
    sung = Phrase(
        "1",
        (
            Piece("al", 0.0, 0.1),
            Piece("le ", 0.1, 0.2),
            Piece("xy", 5.0, 5.1),
            Piece("z", 5.1, 5.2),
        ),
    )
    # the words "alle" and "xyz": 4 and 3 characters of 5 px at size 10, far apart
    assert pop_room(sung, MEASURER, 10.0, Pop(scale=1.1, time=0.25)) == pytest.approx(0.1 * 4 * 5)


def test_a_word_starting_exactly_the_pop_time_later_does_not_pop_together_with_the_first() -> None:
    sung = phrase_of(("aaaa", 0.0), ("bbbb", 0.25))
    assert pop_room(sung, MEASURER, 10.0, Pop(scale=1.1, time=0.25)) == pytest.approx(0.1 * 4 * 5)


def test_a_word_is_dated_by_its_first_syllable() -> None:
    sung = Phrase(
        "1",
        (Piece("xy", 5.0, 5.1), Piece("z ", 5.1, 5.2), Piece("w", 5.3, 5.4)),
    )
    # "xyz" starts at 5.0, so "w" at 5.3 is more than the pop time (0.25 s) later: not together
    assert pop_room(sung, MEASURER, 10.0, Pop(scale=1.1, time=0.25)) == pytest.approx(0.1 * 3 * 5)


def test_only_a_wipe_shifted_earlier_shortens_the_entrance() -> None:
    assert times_for(10.0, 12.0, (10.25, 11.0), offset=-0.2) == (MIN_TRANSITION, 0.3)
    assert times_for(10.0, 12.0, (10.25, 11.0), offset=0.2) == (0.25, 0.3)
