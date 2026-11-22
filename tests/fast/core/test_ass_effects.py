"""Stage 1: the effects in the ASS file: glow, pop, dim, fade and slide (ADR-0032).

The tags are read back from the file and compared with the scene: where the words are, when a
line comes and goes. A look without effects writes none of them.
"""

import re

import pytest
from pydantic import JsonValue

from fakes.measure import FixedMeasurer
from fakes.phrases import line
from fakes.scenes import profile
from vocatron.core.ass.parse import Event, parse_ass
from vocatron.core.ass.write import DIM_RAMP, GLOW_LAYER, SLIDE_REACH, karaoke_text, write_ass
from vocatron.core.colour import ass_colour
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.sample import (
    DUET_TURNS,
    ENTCHEN,
    HAENSCHEN,
    TimedSong,
    scene_of,
    song_text,
    timed_song,
)
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import LineElement, Scene

FRAME = (960, 720)
FADE: dict[str, JsonValue] = {"form": "fade", "time": 0.3}
SLIDE: dict[str, JsonValue] = {"form": "slide", "time": 0.3}
NO_INTRO: dict[str, JsonValue] = {"solo": 0.0, "group": 0.0}
EFFECT_TAGS = (r"\fscx", r"\t(", r"\fad", r"\move", r"\blur", r"\4a", r"\1a")
HALF_CENTI = 0.005 + 1e-9


def modern(**overrides: JsonValue) -> Profile:
    return profile(cdg=None, **overrides)


def events_of(scene: Scene) -> list[Event]:
    return list(parse_ass(write_ass(scene)).events)


def lyric_events(scene: Scene) -> list[Event]:
    """The events that draw a lyric line (not a card, whose text differs), glow events included."""
    texts = {found.text for found in scene.lines()}
    return [e for e in events_of(scene) if e.text in texts]


def scene_with(chosen: Profile) -> Scene:
    """A folk song, with a title and an artist that are not lines of the song."""
    song = timed_song(ENTCHEN, start=9.0, gaps={2: 6.0, 4: 22.0})
    return scene_of(
        song, song_text("Ein Lied", "Jemand", 60.0, {}), chosen, "4x3-720", FixedMeasurer()
    )


def duet_turn_song() -> tuple[TimedSong, SongText]:
    """Hänschen klein as a duet in which the singers change inside two lines."""
    song = timed_song(HAENSCHEN, start=4.0, singers=["1", "2", "all", "1", "2"], turns=DUET_TURNS)
    return song, song_text("Ein Lied", "Jemand", 40.0, {})


# --------------------------------------------------------------------------- off by default


def test_a_look_without_effects_writes_none_of_the_effect_tags_in_its_lines() -> None:
    events = lyric_events(scene_with(profile()))
    assert len(events) == len(scene_with(profile()).lines())
    for event in events:
        for tag in EFFECT_TAGS:
            assert tag not in event.tags, tag
        assert event.layer == 0


# --------------------------------------------------------------------------- glow


def test_a_glow_is_a_second_event_under_each_line_that_shows_the_sung_syllables() -> None:
    scene = scene_with(modern(glow={"sung": 0.6}))
    events = lyric_events(scene)
    assert len(events) == 2 * len(scene.lines())
    for glow, found in zip(events[0::2], events[1::2], strict=True):
        assert (glow.layer, found.layer) == (GLOW_LAYER, GLOW_LAYER + 1)
        assert (glow.start, glow.end, glow.text) == (found.start, found.end, found.text)
        assert (glow.position, glow.style) == (found.position, found.style)
        assert r"\2a&HFF&" in glow.tags  # unsung, the glow is not seen
        assert r"\bord0" in glow.tags  # a blurred copy of the text, not an outline
        assert re.search(r"\\blur[\d.]+", glow.tags)
        assert r"\shad0" in glow.tags
        assert r"\ko" not in glow.tags


def sweep(tags: str) -> list[tuple[str, str]]:
    """The karaoke tags of an event with their centiseconds, in order."""
    return re.findall(r"\\(k[f]?)(\d+)", tags)


@pytest.mark.parametrize(("granularity", "tag"), [("smooth", "kf"), ("syllable", "k")])
def test_the_glow_sweeps_with_the_tag_and_the_timings_of_the_text(
    granularity: str, tag: str
) -> None:
    scene = scene_with(modern(glow={"sung": 0.6}, wipe={"granularity": granularity}))
    events = lyric_events(scene)
    for glow, found in zip(events[0::2], events[1::2], strict=True):
        assert sweep(glow.tags) == sweep(found.tags)
        assert {name for name, _ in sweep(glow.tags) if name != "k"} <= {tag}
        assert tag in {name for name, _ in sweep(glow.tags)}


def test_a_fade_fades_the_glow_with_the_text() -> None:
    scene = scene_with(modern(glow={"sung": 0.6}, transition=FADE))
    events = lyric_events(scene)
    for glow, found in zip(events[0::2], events[1::2], strict=True):
        assert (glow.fade_in_ms, glow.fade_out_ms) == (found.fade_in_ms, found.fade_out_ms)
        assert glow.fade_in_ms > 0


def test_a_pop_pops_the_glow_with_the_word() -> None:
    scene = scene_with(modern(glow={"sung": 0.6}, pop={"scale": 1.1, "time": 0.25}))
    events = lyric_events(scene)
    pop = r"\\fscx\d+\\fscy\d+\\t\(\d+,\d+,[^)]*\)"
    for glow, found in zip(events[0::2], events[1::2], strict=True):
        assert re.findall(pop, glow.tags) == re.findall(pop, found.tags) != []


def test_a_line_sung_to_its_end_has_a_plain_glow_in_the_sung_colour() -> None:
    scene = scene_with(modern(transition=SLIDE, glow={"sung": 0.5}))
    last = [e for e in lyric_events(scene) if e.layer == GLOW_LAYER][2]  # going out, first line
    assert sweep(last.tags) == []
    assert f"\\1c{ass_colour(scene.lines()[0].colours.sung)}" in last.tags


def test_the_glow_has_the_syllable_times_of_the_line() -> None:
    scene = scene_with(modern(glow={"sung": 0.6}))
    glow = lyric_events(scene)[0]
    first = scene.lines()[0]
    centis = sum(int(n) for _, n in sweep(glow.tags))
    assert centis == pytest.approx((first.sing_end - first.start) * 100, abs=len(first.spans))


def test_the_glow_takes_the_sung_colour_unless_the_look_names_one() -> None:
    sung = lyric_events(scene_with(modern(glow={"sung": 0.6})))[0]
    assert f"\\1c{ass_colour(scene_with(modern()).lines()[0].colours.sung)}" in sung.tags
    named = lyric_events(scene_with(modern(glow={"sung": 0.6, "colour": "#00ff00"})))[0]
    assert f"\\1c{ass_colour('#00ff00')}" in named.tags


def test_a_turn_of_singers_switches_the_colour_of_the_glow() -> None:
    chosen = modern(glow={"sung": 0.6})
    scene = scene_of(*duet_turn_song(), chosen, "4x3-720", FixedMeasurer())
    turned = next(found for found in scene.lines() if found.turns)
    colour = ass_colour(turned.turns[0].colours.sung)
    glow = next(e for e in lyric_events(scene) if e.layer == GLOW_LAYER and e.text == turned.text)
    assert f"\\1c{colour}\\kf" in glow.tags


def test_a_stronger_glow_is_wider_and_more_opaque() -> None:
    def glow_tags(strength: float) -> str:
        return lyric_events(scene_with(modern(glow={"sung": strength})))[0].tags

    weak, strong = glow_tags(0.2), glow_tags(1.0)

    def number(tags: str, name: str) -> float:
        found = re.search(rf"\\{name}([\d.]+)", tags)
        assert found
        return float(found.group(1))

    assert number(strong, "blur") > number(weak, "blur")
    assert r"\1a&H00&" in strong  # fully opaque at the top
    assert r"\1a&H00&" not in weak


# --------------------------------------------------------------------------- pop


def word_starts(found: LineElement) -> list[int]:
    return [i for i in range(len(found.spans)) if i == 0 or found.spans[i - 1].text.endswith(" ")]


def test_every_word_pops_when_its_first_syllable_starts_and_settles_within_the_time() -> None:
    scene = scene_with(modern(pop={"scale": 1.1, "time": 0.25}))
    for found, event in zip(scene.lines(), lyric_events(scene), strict=True):
        pops = re.findall(
            r"\\t\((\d+),(\d+),\\fscx110\\fscy110\)\\t\((\d+),(\d+),\\fscx100\\fscy100\)",
            event.tags,
        )
        words = word_starts(found)
        assert len(pops) == len(words)
        for (grow_from, grow_to, settle_from, settle_to), index in zip(pops, words, strict=True):
            begin = (found.spans[index].start - found.start) * 1000
            assert int(grow_from) == pytest.approx(begin, abs=10)
            assert int(grow_to) - int(grow_from) == 100  # 40 % of 250 ms
            assert int(settle_from) == int(grow_to)
            assert int(settle_to) - int(grow_from) == 250


def test_every_word_starts_from_its_own_size() -> None:
    scene = scene_with(modern(pop={"scale": 1.15, "time": 0.25}))
    event = lyric_events(scene)[0]
    assert event.tags.count(r"\fscx100\fscy100\t(") == len(word_starts(scene.lines()[0]))
    assert r"\fscx115\fscy115" in event.tags


def test_the_pop_tags_do_not_change_the_text_or_the_wipe() -> None:
    found = scene_with(modern(pop={"scale": 1.1})).lines()[0]
    plain = karaoke_text(found, "smooth", 0.0)
    popped = karaoke_text(found, "smooth", 0.0, pop=(1.1, 0.25))
    assert re.sub(r"\\fscx100\\fscy100\\t\([^)]*\)\\t\([^)]*\)", "", popped) == plain


# --------------------------------------------------------------------------- upcoming


def test_a_dimmed_line_starts_dim_and_is_full_at_its_first_syllable() -> None:
    scene = scene_with(modern(upcoming={"dim": 0.5}))
    for found, event in zip(scene.lines(), lyric_events(scene), strict=True):
        shown = found.sing_start - found.start
        match = re.search(r"\\1a&H([0-9A-F]{2})&.*\\t\((\d+),(\d+),\\1a&H00&", event.tags)
        assert match, event.tags
        if shown >= DIM_RAMP:
            assert match.group(1) == "80"  # half of 255, rounded
            assert int(match.group(2)) == pytest.approx((shown - DIM_RAMP) * 1000, abs=10)
        assert int(match.group(3)) == pytest.approx(shown * 1000, abs=10)  # full at the syllable


@pytest.mark.parametrize(("offset", "earlier"), [(-0.2, 0.2), (0.2, 0.0)])
def test_a_dimmed_line_is_full_when_its_wipe_starts_if_that_is_shifted_earlier(
    offset: float, earlier: float
) -> None:
    scene = scene_with(modern(upcoming={"dim": 0.5}, wipe={"offset": offset}))
    for found, event in zip(scene.lines(), lyric_events(scene), strict=True):
        shown = found.sing_start - earlier - found.start
        match = re.search(r"\\t\((\d+),(\d+),\\1a&H00&", event.tags)
        assert match, event.tags
        assert int(match.group(2)) == pytest.approx(shown * 1000, abs=10)


def test_the_shadow_of_a_dimmed_line_dims_with_it() -> None:
    scene = scene_with(modern(upcoming={"dim": 0.5}, shadow={"alpha": 0.6}))
    event = lyric_events(scene)[0]
    start = re.search(r"\\4a&H([0-9A-F]{2})&", event.tags)
    assert start
    assert start.group(1) == "B2"  # opacity 0.6 * 0.5 = 0.3: 255 * 0.7 = 178.5, rounded
    assert r"\4a&H66&" in event.tags  # back to 0.6 at the end


def test_a_line_that_is_on_screen_a_short_time_starts_part_way_up_the_ramp() -> None:
    chosen = modern(upcoming={"dim": 0.8}, slots=1, intro=NO_INTRO)
    built = layout(
        [line(10.0, 11.0), line(11.2, 12.2)],
        SongText("T", None, 30.0, {}),
        chosen,
        FRAME,
        FixedMeasurer(),
    )
    second = lyric_events(built)[1]
    shown = built.lines()[1].sing_start - built.lines()[1].start
    assert shown < DIM_RAMP
    found = re.search(r"\\1a&H([0-9A-F]{2})&", second.tags)
    assert found
    assert 0x00 < int(found.group(1), 16) < round(0.8 * 255)


def test_a_line_that_is_dimmed_has_no_dim_after_its_first_syllable() -> None:
    chosen = modern(upcoming={"dim": 0.5}, transition=SLIDE)
    scene = scene_with(chosen)
    going = lyric_events(scene)[2]
    assert r"\1a" not in going.tags
    assert r"\1a" in lyric_events(scene)[0].tags


# --------------------------------------------------------------------------- fade


def test_a_fade_is_one_event_with_fad() -> None:
    scene = scene_with(modern(transition=FADE))
    events = lyric_events(scene)
    assert len(events) == len(scene.lines())
    for found, event in zip(scene.lines(), events, strict=True):
        assert event.fade_in_ms == round(found.enter * 1000) > 0
        assert event.fade_out_ms == round(found.exit * 1000) > 0
        assert (event.start, event.end) == (round(found.start * 100), round(found.end * 100))
        assert r"\move" not in event.tags


# --------------------------------------------------------------------------- slide


def slide_scene(slots: int = 2) -> Scene:
    return scene_with(modern(slots=slots, transition=SLIDE))


def test_a_sliding_line_is_three_events_that_follow_each_other() -> None:
    scene = slide_scene()
    events = lyric_events(scene)
    assert len(events) == 3 * len(scene.lines())
    for index, found in enumerate(scene.lines()):
        coming, singing, going = events[3 * index : 3 * index + 3]
        assert coming.start == round(found.start * 100)
        assert coming.end == singing.start == round((found.start + found.enter) * 100)
        assert singing.end == going.start == round((found.end - found.exit) * 100)
        assert going.end == round(found.end * 100)


def test_a_sliding_line_comes_in_from_below_and_goes_out_upwards_by_part_of_its_slot() -> None:
    scene = slide_scene()
    found = scene.lines()[0]
    coming, singing, going = lyric_events(scene)[:3]
    reach = SLIDE_REACH * scene.slots[found.slot].h
    x, y = found.text_x, found.text_y
    pattern = r"\\move\(([\d.]+),([\d.]+),([\d.]+),([\d.]+),0,(\d+)\)"
    arrive, leave = re.search(pattern, coming.tags), re.search(pattern, going.tags)
    assert arrive and leave
    assert [float(v) for v in arrive.groups()[:4]] == pytest.approx([x, y + reach, x, y], abs=0.01)
    assert [float(v) for v in leave.groups()[:4]] == pytest.approx([x, y, x, y - reach], abs=0.01)
    assert int(arrive.group(5)) == round(found.enter * 1000)
    assert int(leave.group(5)) == round(found.exit * 1000)
    assert (coming.fade_in_ms, coming.fade_out_ms) == (round(found.enter * 1000), 0)
    assert (going.fade_in_ms, going.fade_out_ms) == (0, round(found.exit * 1000))
    assert singing.position == pytest.approx((x, y), abs=0.01)
    assert r"\move" not in singing.tags and r"\fad" not in singing.tags


def test_the_middle_event_sweeps_from_the_same_syllable_times() -> None:
    scene = slide_scene()
    for index, found in enumerate(scene.lines()):
        singing = lyric_events(scene)[3 * index + 1]
        cursor = singing.start
        syllables = iter(found.spans)
        for sweep in singing.sweeps:
            if sweep.text:
                span = next(syllables)
                assert abs(cursor / 100 - span.start) <= HALF_CENTI
            cursor += sweep.centis
        assert next(syllables, None) is None


def test_the_event_that_goes_out_is_the_sung_line_without_a_sweep() -> None:
    scene = slide_scene()
    found = scene.lines()[0]
    going = lyric_events(scene)[2]
    assert going.sweeps == ()
    assert going.text == found.text
    assert r"\k" not in going.tags


def test_the_event_that_goes_out_keeps_the_colours_of_a_turn_of_singers() -> None:
    scene = scene_of(*duet_turn_song(), modern(transition=SLIDE), "4x3-720", FixedMeasurer())
    turned = next(found for found in scene.lines() if found.turns)
    colours = turned.turns[0].colours
    going = [e for e in lyric_events(scene) if e.text == turned.text][-1]
    recolour = f"\\1c{ass_colour(colours.sung)}\\2c{ass_colour(colours.unsung)}"
    assert recolour in going.tags


def test_the_parts_of_a_split_line_slide_each_in_its_own_slot_by_the_same_distance() -> None:
    chosen = modern(slots=3, transition=SLIDE, intro=NO_INTRO)
    built = layout(
        [line(10.0, 14.0, "eins zwei drei vier fünf sechs sieben acht neun zehn elf zwölf"),
         line(16.0, 17.0)],
        SongText("T", None, 30.0, {}),
        chosen,
        FRAME,
        FixedMeasurer(),
    )  # fmt: skip
    parts = [x for x in built.lines() if x.part in (0, 1)][:2]
    assert parts[1].slot == parts[0].slot + 1
    pattern = r"\\move\(([\d.]+),([\d.]+),([\d.]+),([\d.]+),0,\d+\)"
    distances = {
        round(float(found.group(2)) - float(found.group(4)), 2)
        for e in lyric_events(built)
        if (found := re.search(pattern, e.tags)) and float(found.group(2)) > float(found.group(4))
    }
    assert len(distances) == 1  # the slots are as high as each other
    assert distances.pop() == pytest.approx(SLIDE_REACH * built.slots[0].h, abs=0.01)
    firsts = [e for e in lyric_events(built) if e.sweeps][:2]
    assert firsts[0].start != firsts[1].start  # each part comes in when its own slot is free


def test_a_slide_with_a_glow_draws_the_glow_with_every_phase_that_moves() -> None:
    scene = scene_with(modern(transition=SLIDE, glow={"sung": 0.5}))
    moving = [e for e in lyric_events(scene) if r"\move" in e.tags]
    glows = [e for e in moving if e.layer == GLOW_LAYER]
    texts = [e for e in moving if e.layer == GLOW_LAYER + 1]
    assert len(glows) == len(texts) > 0
    for glow, text in zip(glows, texts, strict=True):
        assert (glow.start, glow.end) == (text.start, text.end)
        assert re.findall(r"\\move\([^)]*\)", glow.tags) == re.findall(
            r"\\move\([^)]*\)", text.tags
        )


# --------------------------------------------------------------------------- exact times


def test_a_pop_of_one_second_settles_exactly_one_second_after_the_word_starts() -> None:
    event = lyric_events(scene_with(modern(pop={"scale": 1.1, "time": 1.0})))[0]
    pops = re.findall(r"\\t\((\d+),(\d+),\\fscx110\\fscy110\)\\t\((\d+),(\d+),", event.tags)
    assert pops
    for grow_from, grow_to, _, settle_to in pops:
        assert (int(grow_to) - int(grow_from), int(settle_to) - int(grow_from)) == (400, 1000)


@pytest.mark.parametrize("form", ["fade", "slide"])
def test_a_transition_of_one_second_takes_exactly_one_second(form: str) -> None:
    scene = scene_with(modern(transition={"form": form, "time": 1.0}))
    full = [x for x in scene.lines() if x.enter == 1.0 and x.exit == 1.0]
    assert full
    events = [e for e in lyric_events(scene) if e.text == full[0].text]
    assert max(e.fade_in_ms for e in events) == 1000
    assert max(e.fade_out_ms for e in events) == 1000
    if form == "slide":
        moves = re.findall(r"\\move\([^)]*,0,(\d+)\)", "".join(e.tags for e in events))
        assert moves == ["1000", "1000"]


def test_a_line_that_only_fades_in_has_a_fade_in_and_no_fade_out() -> None:
    chosen = modern(transition=FADE, slots=1, intro=NO_INTRO)
    built = layout(
        [line(10.0, 11.0), line(11.0, 12.0)],
        SongText("T", None, 30.0, {}),
        chosen,
        FRAME,
        FixedMeasurer(),
    )
    first = built.lines()[0]
    assert first.enter > 0 and first.exit == 0  # replaced the moment it has been sung
    (event,) = [e for e in lyric_events(built) if e.start == round(first.start * 100)]
    assert (event.fade_in_ms, event.fade_out_ms) == (round(first.enter * 1000), 0)


def short_dim_scene(transition: dict[str, JsonValue] | None = None) -> Scene:
    """Two lines back to back in one slot: the second is shown 0.2 s before its first syllable."""
    chosen = modern(upcoming={"dim": 0.8}, slots=1, intro=NO_INTRO, transition=transition or {})
    return layout(
        [line(10.0, 11.0), line(11.2, 12.2)],
        SongText("T", None, 30.0, {}),
        chosen,
        FRAME,
        FixedMeasurer(),
    )


def test_a_line_shown_inside_the_ramp_starts_at_the_opacity_of_that_point_of_the_ramp() -> None:
    built = short_dim_scene()
    second = built.lines()[1]
    share = (second.start - (second.sing_start - DIM_RAMP)) / DIM_RAMP
    opacity = 0.2 + 0.8 * share
    event = next(e for e in lyric_events(built) if e.start == round(second.start * 100))
    found = re.search(r"\\1a&H([0-9A-F]{2})&", event.tags)
    assert found
    assert int(found.group(1), 16) == round((1 - opacity) * 255)


def test_a_line_that_slides_in_inside_the_ramp_brightens_while_it_comes_in() -> None:
    built = short_dim_scene(SLIDE)
    second = built.lines()[1]
    assert second.enter > 0
    coming = next(
        e
        for e in lyric_events(built)
        if r"\move" in e.tags and e.start == round(second.start * 100)
    )
    assert re.search(r"\\t\(\d+,\d+,\\1a&H00&", coming.tags)


def test_a_slide_with_a_glow_sweeps_the_glow_with_the_text_in_every_phase() -> None:
    scene = scene_with(modern(transition=SLIDE, glow={"sung": 0.5}))
    events = lyric_events(scene)
    glows = [e for e in events if e.layer == GLOW_LAYER]
    texts = [e for e in events if e.layer == GLOW_LAYER + 1]
    assert len(glows) == len(texts) > len(scene.lines())  # a line slides in up to three phases
    karaoke = r"\\k[f]?(\d+)"
    for glow, text in zip(glows, texts, strict=True):
        assert (glow.start, glow.end) == (text.start, text.end)
        assert re.findall(karaoke, glow.tags) == re.findall(karaoke, text.tags)
