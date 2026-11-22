"""Stage 1: what the layout builds besides the lines' times: colours, places, cards, shortfalls."""

import math

import pytest
from pydantic import JsonValue

from conformance.scene_rules import check_scene
from fakes.measure import FixedMeasurer
from fakes.phrases import line
from fakes.scenes import profile
from vocatron.core.layout.build import SongText, countdown_window, layout, line_colours
from vocatron.core.layout.cards import (
    COUNTDOWN_HEIGHT,
    DOT_SPACING,
    ROW_GAP,
    Canvas,
    CardText,
    CountdownWindow,
    card,
    row_rects,
    slot_rects,
    split_timer,
    timer_text,
    title_window,
)
from vocatron.core.layout.phrases import Phrase, Turn
from vocatron.core.lyrics.document import SingerInfo
from vocatron.core.profiles.model import Countdown, Profile
from vocatron.core.scene import (
    CardElement,
    CountdownElement,
    PreviewElement,
    ProgressElement,
    Rect,
    Scene,
    TimerElement,
)

NO_INTRO: dict[str, JsonValue] = {"solo": 0.0, "group": 0.0}  # songs that start early stay so
FRAME = (960, 720)  # safe area 864 x 648 from (48, 36); font size 0.12 of 648


def scene_of(
    phrases: list[Phrase],
    chosen: Profile | None = None,
    duration: float | None = 60.0,
    singers: dict[int, SingerInfo] | None = None,
    title: str = "Titel",
    *,
    rules: bool = True,
) -> Scene:
    look = chosen or profile()
    built = layout(
        phrases, SongText(title, "Künstler", duration, singers or {}), look, FRAME, FixedMeasurer()
    )
    if rules:
        check_scene(built, look)
    return built


def cards(scene: Scene, kind: str) -> list[CardElement]:
    return [e for e in scene.elements if isinstance(e, CardElement) and e.kind == kind]


def countdowns(scene: Scene) -> list[CountdownElement]:
    return [e for e in scene.elements if isinstance(e, CountdownElement)]


@pytest.mark.parametrize("singers", ["1", "2", "3", "4", "5"])
def test_every_singer_sings_in_the_colours_of_the_profile(singers: str) -> None:
    look = profile()
    assert line_colours(singers, look, {}).model_dump() == look.singer_colours(singers).model_dump()


@pytest.mark.parametrize("singers", ["all", "1,3", "2,5"])
def test_several_singers_sing_in_the_group_colours(singers: str) -> None:
    look = profile()
    assert line_colours(singers, look, {}).model_dump() == look.colours.group.model_dump()


def test_a_colour_from_the_lyrics_file_replaces_only_the_sung_colour_of_its_singer() -> None:
    look = profile()
    infos = {3: SingerInfo(name="Cleo", colour="#112233")}
    colours = line_colours("3", look, infos)
    assert colours.sung == "#112233"
    assert colours.unsung == look.colours.singer3.unsung
    assert line_colours("4", look, infos).sung == look.colours.singer4.sung


def test_a_group_line_is_one_line_in_the_group_colours_and_lines_are_never_merged() -> None:
    scene = scene_of([line(10, 12, "la la", "all"), line(12, 14, "li li", "1,3"), line(14, 16)])
    first, second, third = scene.lines()
    group = profile().colours.group
    assert (first.text, second.text, third.text) == ("la la", "li li", "la la")
    assert first.colours.sung == second.colours.sung == group.sung


def test_each_word_of_a_line_is_in_the_colours_of_its_singers() -> None:
    infos = {2: SingerInfo(name="Ben", colour="#445566")}
    phrase = Phrase("1", line(10, 16, "la li lo lu").pieces, (Turn(1, "2"), Turn(3, "all")))
    (only,) = scene_of([phrase], singers=infos).lines()
    look = profile()
    assert only.colours.sung == look.colours.singer1.sung
    first, second = only.turns
    assert (first.span, first.singers, second.span, second.singers) == (1, "2", 3, "all")
    assert first.colours.sung == "#445566"  # a colour of the lyrics file colours a turn too
    assert first.colours.unsung == look.colours.singer2.unsung
    assert second.colours.model_dump() == look.colours.group.model_dump()


def test_a_line_without_turns_has_none_and_a_turn_survives_the_fit() -> None:
    plain = scene_of([line(10, 12, "la la")]).lines()[0]
    assert plain.turns == []
    long = Phrase("1", line(10, 20, " ".join(["wortwort"] * 20)).pieces, (Turn(19, "2"),))
    halves = scene_of([long], rules=False).lines()
    assert len(halves) > 1
    last = halves[-1]
    assert halves[0].singers == "1"
    assert (last.turns[-1].singers if last.turns else last.singers) == "2"  # the end stays singer 2


def test_a_word_too_wide_even_at_the_smallest_size_is_reported_and_kept() -> None:
    scene = scene_of([line(10, 12, "x" * 60)], rules=False)  # it leaves the safe area: reported
    (only,) = scene.lines()
    assert only.text == "x" * 60
    assert only.size == pytest.approx(0.08 * 648)
    assert [(s.kind, s.line) for s in scene.shortfalls] == [("too-wide", 0)]
    assert "smallest size" in scene.shortfalls[0].message


def test_slots_that_do_not_fit_the_safe_area_are_reported() -> None:
    look = profile(slots=4, font={"size": 0.3, "min_size": 0.3})
    scene = layout([line(10, 12)], SongText("T", None, 30.0, {}), look, FRAME, FixedMeasurer())
    assert [(s.kind, s.line) for s in scene.shortfalls] == [("block", None)]
    assert "safe area" in scene.shortfalls[0].message


def test_a_line_on_the_right_ends_at_the_right_of_the_safe_area() -> None:
    scene = scene_of([line(10, 12)], profile(align="right"))
    assert scene.lines()[0].box.right == pytest.approx(scene.safe.right, abs=0.002)


@pytest.mark.parametrize(
    ("position", "centre"), [("top", 0.22), ("middle", 0.5), ("lower-third", 0.75)]
)
def test_the_block_of_slots_sits_where_the_profile_says(position: str, centre: float) -> None:
    scene = scene_of([line(10, 12)], profile(position=position))
    top, bottom = scene.slots[0].y, scene.slots[-1].bottom
    assert (top + bottom) / 2 == pytest.approx(scene.safe.y + centre * scene.safe.h, abs=0.01)


def test_a_block_at_the_bottom_is_moved_up_into_the_safe_area() -> None:
    scene = scene_of([line(10, 12)], profile(position="bottom"))
    assert scene.slots[-1].bottom == pytest.approx(scene.safe.bottom, abs=0.01)


def test_a_block_at_the_top_leaves_room_for_the_countdown_above_it() -> None:
    scene = scene_of([line(10, 12)], profile(position="top", slots=4))
    (countdown,) = countdowns(scene)
    assert countdown.box.y == pytest.approx(scene.safe.y, abs=0.01)
    assert countdown.box.bottom < scene.slots[0].y


def test_the_countdown_bar_is_six_band_heights_wide_and_dots_have_their_spacing() -> None:
    band = COUNTDOWN_HEIGHT * 0.12 * 648
    (bar,) = countdowns(scene_of([line(10, 12)]))
    assert bar.box.w == pytest.approx(6 * band, abs=0.01)
    (dots,) = countdowns(scene_of([line(10, 12)], profile(countdown={"form": "dots", "count": 3})))
    assert dots.box.w == pytest.approx(3 * DOT_SPACING * band, abs=0.01)
    assert (dots.form, dots.count) == ("dots", 3)


def test_the_countdown_of_a_line_on_the_right_stays_inside_the_safe_area() -> None:
    scene = scene_of([line(10, 12, "a")], profile(align="right"))
    (countdown,) = countdowns(scene)
    assert countdown.box.right == pytest.approx(scene.safe.right, abs=0.01)


def test_a_gap_of_exactly_the_countdown_gap_gets_a_countdown() -> None:
    scene = scene_of([line(10, 12), line(17, 19)])  # 5.0 s after the end of the first line
    assert [c.end for c in countdowns(scene)] == [10.0, 17.0]


def test_a_gap_just_under_the_countdown_gap_gets_none() -> None:
    scene = scene_of([line(10, 12), line(16.9, 19)])
    assert [c.end for c in countdowns(scene)] == [10.0]


def test_a_gap_that_rounds_to_the_clear_gap_clears_the_screen_and_gets_a_countdown() -> None:
    scene = scene_of([line(10, 12.0004), line(17, 19)])  # 4.9996 s, 5.000 s in the scene
    assert scene.lines()[0].end == pytest.approx(12.0 + profile().clear.hold)  # 12.000 in the scene
    assert [c.end for c in countdowns(scene)] == [10.0, 17.0]


def test_the_countdown_after_a_break_screen_starts_when_the_break_screen_ends() -> None:
    scene = scene_of([line(10, 12), line(40, 42)])
    (pause,) = cards(scene, "break")
    late = countdowns(scene)[1]
    assert late.start >= pause.end
    assert late.end == 40.0


def test_a_gap_of_exactly_the_notice_gap_gets_a_break_screen() -> None:
    scene = scene_of([line(10, 12), line(27, 29)])  # 15.0 s
    (pause,) = cards(scene, "break")
    assert pause.start == pytest.approx(12 + profile().clear.hold)  # after the hold
    assert [x.text for x in pause.lines] == ["Instrumental"]


def test_a_break_screen_can_show_title_and_artist_smaller_below_the_notice() -> None:
    scene = scene_of([line(10, 12), line(40, 42)], profile(breaks={"show_title": True}))
    (pause,) = cards(scene, "break")
    assert [x.text for x in pause.lines] == ["Instrumental", "Titel", "Künstler"]
    base = 0.12 * 648
    assert [x.size for x in pause.lines] == pytest.approx([0.9 * base, 0.5 * base, 0.35 * base])


def test_a_card_line_too_wide_for_the_safe_area_is_shrunk_to_fit() -> None:
    scene = scene_of([line(20, 22)], title="T" * 40)
    (title,) = cards(scene, "title")
    first = title.lines[0]
    assert first.box.w <= scene.safe.w
    assert first.box.w == pytest.approx(scene.safe.w, rel=0.02)  # shrunk just enough
    assert first.size < 0.12 * 648
    assert title.lines[1].size == pytest.approx(0.7 * 0.12 * 648)  # the artist was not shrunk


def test_a_card_line_whose_text_fits_but_whose_edge_does_not_is_shrunk_too() -> None:
    scene = scene_of([line(20, 22)], title="T" * 22)  # 855 px of text, 874 px with the edge
    (title,) = cards(scene, "title")
    assert title.lines[0].size < 0.12 * 648
    assert title.lines[0].box.w <= scene.safe.w


def test_a_card_line_whose_text_and_edge_just_fit_keeps_its_size() -> None:
    look = profile(edge={"width": 0.25}, shadow={"offset": 0.0})  # 19.4 px of edge on each side
    scene = scene_of([line(20, 22)], look, title="T" * 21)  # 816 px of text, 855 px with the edge
    (title,) = cards(scene, "title")
    assert title.lines[0].size == pytest.approx(0.12 * 648)
    assert title.lines[0].box.w == pytest.approx(855.4, abs=0.1)


def test_a_card_that_fills_the_safe_area_exactly_keeps_its_size() -> None:
    look = profile(edge={"width": 0.125}, shadow={"offset": 0.0})  # 10 px of edge at 80 px
    safe = Rect(x=0, y=0, w=60, h=100)  # "T" is 40 px wide plus the edge; 1.25 x 80 px high
    canvas = Canvas(FixedMeasurer(), look, safe, 80)
    built = card("title", [CardText("T", 1.0, "#ffffff")], canvas, start=0, end=5)
    assert built.lines[0].size == 80
    assert built.box == safe


def test_a_title_naming_many_singers_is_shrunk_as_a_whole_to_fit_the_safe_area() -> None:
    names = {n: SingerInfo(name=f"S{n}") for n in range(1, 6)}
    look = profile(font={"size": 0.2, "min_size": 0.1})
    scene = scene_of([line(20, 22)], look, singers=names)  # the scene rules hold: rule 1 too
    (title,) = cards(scene, "title")
    sizes = [x.size for x in title.lines]
    base = 0.2 * 648
    wanted = [1.0, 0.7, 0.6, 0.6, 0.6, 0.6, 0.6]  # title, artist, five singers
    factor = sizes[0] / base
    assert factor < 1  # 1.25 x 4.7 font sizes would be taller than the safe area
    assert sizes == pytest.approx([base * scale * factor for scale in wanted], abs=0.01)
    assert title.box.y >= scene.safe.y and title.box.bottom <= scene.safe.bottom
    assert title.box.h == pytest.approx(scene.safe.h, rel=0.02)  # shrunk just enough


def test_a_title_that_fits_keeps_its_sizes() -> None:
    names = {n: SingerInfo(name=f"S{n}") for n in range(1, 3)}
    (title,) = cards(scene_of([line(20, 22)], singers=names), "title")
    base = 0.12 * 648
    assert [x.size for x in title.lines] == pytest.approx(
        [base, 0.7 * base, 0.6 * base, 0.6 * base]
    )


def test_without_a_title_the_first_line_has_its_target_lead_in() -> None:
    look = profile(title={"fields": []})
    scene = scene_of([line(10, 12)], look)
    assert cards(scene, "title") == []
    first = 10.0 - look.lead_in.target
    assert scene.lines()[0].start == pytest.approx(first)
    assert title_window(10.0, look) == (0.0, first, [])
    assert title_window(1.0, look) == (0.0, 0.0, [])


def test_a_title_of_exactly_its_shortest_length_is_no_shortfall() -> None:
    look = profile(title={"min_short": 2.0})
    assert title_window(4.5, look) == (2.0, 2.0, [])  # min_short 2.0 + target 2.5
    ends, shows, short = title_window(2.0, look)
    assert (ends, shows) == (1.0, 1.0)
    assert [s.kind for s in short] == ["title"]


def test_the_end_screen_needs_half_a_second_and_the_profile_s_consent() -> None:
    assert len(cards(scene_of([line(10, 12)], duration=14.5), "end")) == 1  # 12 + 2 + 0.5
    assert cards(scene_of([line(10, 12)], duration=14.4), "end") == []
    no_end = profile(ending={"end_screen": False})
    assert cards(scene_of([line(10, 12)], no_end, duration=60.0), "end") == []


def test_a_title_shortfall_and_a_lead_in_shortfall_are_both_reported() -> None:
    scene = scene_of([line(2.0, 4.0), line(4.0, 4.5), line(4.6, 6.0)], profile(intro=NO_INTRO))
    kinds = sorted(s.kind for s in scene.shortfalls)
    assert kinds == ["lead-in", "title"]
    (lead,) = [s for s in scene.shortfalls if s.kind == "lead-in"]
    assert "0.60 s before it starts" in lead.message


def test_a_song_without_sung_lines_shows_its_title_for_the_whole_song() -> None:
    look = profile(slots=4, font={"size": 0.3, "min_size": 0.3})
    scene = layout([], SongText("T", None, 30.0, {}), look, FRAME, FixedMeasurer())
    (title,) = cards(scene, "title")
    assert (title.start, title.end) == (0.0, 30.0)
    assert (scene.width, scene.height, scene.duration) == (960, 720, 30.0)
    assert [s.kind for s in scene.shortfalls] == ["block"]


def test_the_first_countdown_waits_for_a_shortened_title_to_leave() -> None:
    scene = scene_of(
        [line(3.5, 5.0)],
        profile(countdown={"min_gap": 3.0}, intro=NO_INTRO, title={"min_short": 2.0}),
    )
    (title,) = cards(scene, "title")
    (countdown,) = countdowns(scene)
    assert title.end == pytest.approx(2.0)  # shortened to min_short: 3.5 - 2.5 is too short
    assert countdown.start == pytest.approx(2.0)  # not 1.5, which is 2 s before the line
    assert countdown.end == pytest.approx(3.5)


def previewing(show: bool = True) -> Profile:
    return profile(slots=1, cdg={"slots": 1}, preview={"show": show, "scale": 0.7})


def previews(scene: Scene) -> list[PreviewElement]:
    return [e for e in scene.elements if isinstance(e, PreviewElement)]


def bars(scene: Scene) -> list[ProgressElement]:
    return [e for e in scene.elements if isinstance(e, ProgressElement)]


def test_the_next_line_is_previewed_smaller_below_until_it_moves_up() -> None:
    scene = scene_of([line(10, 12, "la la"), line(12.5, 14, "li li li")], previewing())
    first, second = scene.lines()
    (preview,) = previews(scene)
    assert (preview.of_line, preview.line.text) == (1, "li li li")
    assert preview.end == second.start == pytest.approx(12.0)  # it moves up as the first is sung
    assert preview.line.size == pytest.approx(0.7 * second.size)
    assert preview.line.colour == second.colours.unsung
    assert scene.preview_row is not None
    assert scene.preview_row.y >= scene.slots[0].bottom
    assert preview.box.inside(scene.preview_row)
    assert first.end == second.start  # the preview row and the slot are never both the line's
    assert len(scene.slots) == 1


def test_a_preview_is_centred_like_the_lines() -> None:
    scene = scene_of([line(10, 12), line(12.5, 14)], previewing())
    (preview,) = previews(scene)
    assert preview.box.x + preview.box.w / 2 == pytest.approx(scene.safe.x + scene.safe.w / 2)


def test_no_preview_crosses_a_long_gap() -> None:
    scene = scene_of([line(10, 12), line(20, 22), line(22.5, 24)], previewing())
    assert [p.of_line for p in previews(scene)] == [2]


def test_a_preview_appears_at_most_lead_in_max_ahead() -> None:
    scene = scene_of([line(10, 30), line(31, 32)], previewing())
    (preview,) = previews(scene)
    assert 31.0 - preview.start == pytest.approx(profile().lead_in.max)  # not with the first line
    assert preview.start > scene.lines()[0].start


def test_preview_off_gives_a_bare_single_line() -> None:
    bare = previewing(show=False)
    scene = scene_of([line(10, 12), line(12.5, 14)], bare)
    assert previews(scene) == []
    assert scene.preview_row is None
    assert len(scene.slots) == 1


def test_the_block_with_a_preview_is_centred_where_the_profile_says() -> None:
    plain = scene_of([line(10, 12)], previewing(show=False))
    scene = scene_of([line(10, 12)], previewing())
    assert scene.preview_row is not None
    middle = (scene.slots[0].y + scene.preview_row.bottom) / 2
    assert middle == pytest.approx(scene.safe.y + 0.75 * scene.safe.h, abs=0.01)
    assert scene.slots[0].y < plain.slots[0].y  # the preview row takes room from the block


def test_the_lead_in_counts_from_the_preview() -> None:
    sung = [line(10, 12), line(12.2, 14)]
    scene = scene_of(sung, previewing())
    (preview,) = previews(scene)
    assert scene.lines()[1].start == pytest.approx(12.0)  # on screen 0.2 s before it starts
    assert 12.2 - preview.start >= 1.0  # but its preview was there long before
    assert scene.shortfalls == []
    bare = scene_of(sung, previewing(show=False))
    assert [(s.kind, s.line) for s in bare.shortfalls] == [("lead-in", 1)]


def test_a_progress_bar_fills_the_break_screen_below_its_text() -> None:
    scene = scene_of([line(10, 12), line(40, 42)], profile(breaks={"form": "progress"}))
    (pause,) = cards(scene, "break")
    (bar,) = bars(scene)
    assert (bar.start, bar.end) == (pause.start, pause.end)
    assert bar.box.y >= pause.box.bottom
    assert bar.box.w == pytest.approx(0.6 * scene.safe.w, abs=0.01)
    assert bar.box.h == pytest.approx(0.15 * 0.12 * 648, abs=0.01)
    assert bar.box.x + bar.box.w / 2 == pytest.approx(scene.safe.x + scene.safe.w / 2, abs=0.01)
    colours = profile().colours.group
    assert (bar.fill, bar.frame) == (colours.sung, colours.unsung)
    assert bars(scene_of([line(10, 12), line(40, 42)])) == []  # the notice form has none


def test_blocks_have_the_width_of_dots() -> None:
    band = COUNTDOWN_HEIGHT * 0.12 * 648
    (blocks,) = countdowns(
        scene_of([line(10, 12)], profile(countdown={"form": "blocks", "count": 3}))
    )
    assert blocks.box.w == pytest.approx(3 * DOT_SPACING * band, abs=0.01)
    assert (blocks.form, blocks.count) == ("blocks", 3)


def test_the_preview_row_sits_a_gap_below_the_slot_and_fits_the_small_line() -> None:
    chosen = previewing()
    scene = scene_of([line(10, 12)], chosen)
    assert scene.preview_row is not None
    size = chosen.font.size * scene.safe.h
    small = chosen.preview.scale * size
    gap = 0.1 * size
    assert scene.preview_row.y == pytest.approx(scene.slots[0].bottom + gap, abs=0.01)
    assert scene.preview_row.h == pytest.approx(small + 2 * chosen.padding(small), abs=0.01)


def test_a_preview_is_drawn_like_a_small_line() -> None:
    chosen = previewing()
    scene = scene_of([line(10, 12, "la la"), line(12.5, 14, "li li li")], chosen)
    (preview,) = previews(scene)
    text, size = preview.line, preview.line.size
    assert text.edge == pytest.approx(chosen.edge.width * size, abs=0.01)
    assert text.shadow == pytest.approx(chosen.shadow.offset * size, abs=0.01)
    pad = chosen.padding(size)
    assert (text.text_x, text.text_y) == pytest.approx(
        (preview.box.x + pad, preview.box.y + pad), abs=0.01
    )


def test_a_line_shown_at_its_lead_in_maximum_needs_no_preview() -> None:
    chosen = previewing().model_copy(
        update={"lead_in": profile().lead_in.model_copy(update={"max": 3.0})}
    )
    scene = scene_of([line(10, 11), line(15, 16), line(16.5, 17.5)], chosen)
    assert scene.lines()[1].start == pytest.approx(12.0)  # free at 11.33, lead_in.max at 12
    assert [p.of_line for p in previews(scene)] == [2]  # the later line still gets one


def test_a_gap_of_exactly_clear_after_is_long_for_the_preview() -> None:
    scene = scene_of([line(10, 11), line(16, 17)], previewing())  # 5.0 s of silence
    assert previews(scene) == []


def test_a_preview_row_that_does_not_fit_is_a_block_shortfall() -> None:
    big = previewing().model_copy(
        update={"font": profile().font.model_copy(update={"size": 0.4, "min_size": 0.08})}
    )
    plain = big.model_copy(update={"preview": big.preview.model_copy(update={"show": False})})
    kinds = {
        s.kind
        for s in layout(
            [line(10, 12)], SongText("T", None, 30.0, {}), big, (960, 720), FixedMeasurer()
        ).shortfalls
    }
    plain_kinds = {
        s.kind
        for s in layout(
            [line(10, 12)], SongText("T", None, 30.0, {}), plain, (960, 720), FixedMeasurer()
        ).shortfalls
    }
    assert "block" in kinds
    assert "block" not in plain_kinds


def test_the_progress_bar_keeps_its_gap_below_the_text() -> None:
    scene = scene_of([line(10, 12), line(40, 42)], profile(breaks={"form": "progress"}))
    (pause,) = cards(scene, "break")
    (bar,) = bars(scene)
    assert bar.box.y == pytest.approx(pause.box.bottom + 0.4 * 0.12 * 648, abs=0.01)


def wrapping(rows: int = 2, **overrides: JsonValue) -> Profile:
    chosen: dict[str, JsonValue] = {"preview": {"show": True, "scale": 0.7}, **overrides}
    return profile(slots=1, cdg={"slots": 1}, line_rows=rows, **chosen)


LONG = " ".join(["lala"] * 6)  # 29 characters: too wide for one row (21 fit), fine for two
SHORT = "la la la"


def test_a_long_line_with_two_rows_is_one_block_shown_sung_and_gone_together() -> None:
    scene = scene_of([line(10, 16, LONG), line(17, 19, SHORT)], wrapping())
    top, bottom, after = scene.lines()
    assert top.text == "lala lala lala" and bottom.text == "lala lala lala"
    assert (top.slot, bottom.slot) == (0, 0)
    assert (top.start, top.end) == (bottom.start, bottom.end)
    assert bottom.box.y >= top.box.bottom  # one below the other
    assert top.sing_end <= bottom.sing_start + 1e-6  # sung one after the other, once each
    assert top.box.inside(scene.slots[0]) and bottom.box.inside(scene.slots[0])
    assert top.size == bottom.size == pytest.approx(0.12 * 648)  # each row fits as it is
    assert after.start >= bottom.end  # the next line takes over when the block goes


def test_the_slot_holds_the_rows_and_the_preview_sits_below_the_last_row() -> None:
    scene = scene_of([line(10, 16, LONG), line(17, 19, SHORT)], wrapping())
    size = 0.12 * 648
    row = size + 2 * (0.08 + 0.04) * size
    assert scene.slots[0].h == pytest.approx(2 * row + 0.1 * size, abs=0.01)
    (preview,) = previews(scene)
    bottom = scene.lines()[1]
    assert preview.box.y >= bottom.box.bottom
    assert scene.preview_row is not None
    assert scene.preview_row.y >= scene.slots[0].bottom


def test_a_short_line_stays_one_row_in_the_middle_of_the_slot() -> None:
    scene = scene_of([line(10, 12, SHORT), line(13, 15, SHORT)], wrapping())
    first, second = scene.lines()
    slot = scene.slots[0]
    assert len(scene.lines()) == 2
    assert first.box.y + first.box.h / 2 == pytest.approx(slot.y + slot.h / 2, abs=0.01)
    assert second.box.y == first.box.y


def test_the_preview_of_a_line_with_two_rows_is_its_first_row() -> None:
    scene = scene_of([line(10, 12, SHORT), line(13, 19, LONG)], wrapping())
    (preview,) = previews(scene)
    assert preview.of_line == 1  # the first row of the long line
    assert preview.line.text == "lala lala lala"
    assert preview.end == scene.lines()[1].start


def test_the_rows_appear_with_the_preview_counted_from_the_first_row() -> None:
    scene = scene_of([line(10, 12, SHORT), line(13, 19, LONG), line(20, 22, SHORT)], wrapping())
    assert [p.of_line for p in previews(scene)] == [1, 3]
    assert [line.text for line in scene.lines()][3:] == [SHORT]


def test_a_shortfall_names_the_first_row_of_its_line() -> None:
    scene = scene_of(
        [line(10, 11, SHORT), line(11.2, 17, LONG), line(17.1, 18, SHORT)],
        wrapping(preview={"show": False}),
        rules=False,
    )
    lead = [s.line for s in scene.shortfalls if s.kind == "lead-in"]
    assert 1 in lead  # the first row of the long line
    assert 2 not in lead  # the second row of the long line is never a line of its own


def test_with_one_row_a_long_line_is_split_into_lines_as_before() -> None:
    scene = scene_of([line(10, 16, LONG)], profile(slots=1, line_rows=1), rules=False)
    assert [x.text for x in scene.lines()] == ["lala lala lala", "lala lala lala"]
    assert [x.start for x in scene.lines()] == sorted({x.start for x in scene.lines()})
    assert scene.lines()[0].start < scene.lines()[1].start  # one after the other, not together
    assert scene.slots[0].h == pytest.approx(0.12 * 648 * (1 + 2 * 0.12), abs=0.01)  # one row


def test_the_rows_are_shrunk_together_when_two_rows_still_do_not_fit() -> None:
    longer = " ".join(["lalala"] * 8)  # 55 characters, 27 or 28 in a row
    scene = scene_of([line(10, 20, longer)], wrapping())
    top, bottom = scene.lines()
    assert top.size == bottom.size < 0.12 * 648
    assert top.size >= 0.08 * 648


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (1, "the slots and the countdown do not fit the safe area"),
        (2, "the slots of 2 rows and the countdown do not fit the safe area"),
    ],
)
def test_a_block_shortfall_names_the_rows_of_a_slot(rows: int, message: str) -> None:
    tall = profile(
        slots=4, line_rows=rows, font={"size": 0.3 if rows == 1 else 0.15, "min_size": 0.08}
    )
    scene = layout([line(10, 12)], SongText("T", None, 30.0, {}), tall, (960, 720), FixedMeasurer())
    assert [s.message for s in scene.shortfalls if s.kind == "block"] == [message]


def test_the_rows_of_a_slot_share_its_height_with_a_gap_between_them() -> None:
    slot = Rect(x=10.0, y=100.0, w=300.0, h=210.0)
    size = 50.0  # the gap is ROW_GAP * size = 5 px
    top, bottom = row_rects(slot, 2, size)
    assert ROW_GAP * size == 5.0
    assert (top.x, top.w, bottom.x, bottom.w) == (10.0, 300.0, 10.0, 300.0)
    assert (top.y, top.h) == (100.0, 102.5)
    assert (bottom.y, bottom.h) == (207.5, 102.5)
    assert bottom.bottom == slot.bottom
    assert row_rects(slot, 1, size) == [slot]


# ----------------------------------------------------------------- countdown in beats (ADR-0022)


def scene_at(phrases: list[Phrase], bpm: float | None, chosen: Profile | None = None) -> Scene:
    """Lay out ``phrases`` for a song at the tempo ``bpm`` and check the rules on the scene."""
    look = chosen or profile()
    built = layout(
        phrases, SongText("Titel", "Künstler", 60.0, {}, bpm=bpm), look, FRAME, FixedMeasurer()
    )
    check_scene(built, look)
    return built


def test_a_song_without_sung_lines_keeps_its_tempo_too() -> None:
    assert scene_at([], 100.0).bpm == 100.0
    assert scene_at([], None).bpm is None


def test_without_a_tempo_a_countdown_runs_in_seconds() -> None:
    scene = scene_of([line(10, 12)], profile(countdown={"duration": 2.0}))
    (countdown,) = countdowns(scene)
    assert (countdown.start, countdown.end, countdown.beat) == (8.0, 10.0, None)


def test_with_a_tempo_a_countdown_lasts_count_beats_and_ends_one_beat_before_the_line() -> None:
    scene = scene_at([line(10, 12)], 100.0)
    assert scene.bpm == 100.0  # the scene carries the tempo, so rule 13 knows its beat
    (countdown,) = countdowns(scene)
    assert (countdown.count, countdown.beat) == (4, 0.6)
    assert countdown.end == pytest.approx(9.4)  # the singing starts on the next beat (ADR-0028)
    assert countdown.start == pytest.approx(9.4 - 4 * 0.6)


def test_the_count_of_the_look_is_the_number_of_beats() -> None:
    scene = scene_at([line(10, 12)], 100.0, profile(countdown={"form": "dots", "count": 3}))
    (dots,) = countdowns(scene)
    assert (dots.count, dots.beat) == (3, 0.6)
    assert dots.start == pytest.approx(9.4 - 3 * 0.6)  # 1.8 s, as fast as the song's beat
    assert dots.box.w == pytest.approx(3 * DOT_SPACING * COUNTDOWN_HEIGHT * 0.12 * 648, abs=0.01)


@pytest.mark.parametrize(("bpm", "beat"), [(50.0, 0.6), (200.0, 0.6), (100.0, 0.6), (75.0, 0.8)])
def test_the_beat_is_doubled_or_halved_to_fit_the_length(bpm: float, beat: float) -> None:
    (countdown,) = countdowns(scene_at([line(10, 12)], bpm))
    assert countdown.beat == pytest.approx(beat)
    assert 1.5 <= countdown.end - countdown.start <= 4.0


def test_a_title_screen_that_leaves_less_room_cuts_the_countdown_to_whole_beats() -> None:
    chosen = profile(
        countdown={"min_gap": 3.0, "form": "dots"}, intro=NO_INTRO, title={"min_short": 2.0}
    )
    scene = scene_at([line(3.5, 5.0)], 100.0, chosen)
    (title,) = cards(scene, "title")
    (countdown,) = countdowns(scene)
    room = 3.5 - 0.6 - title.end  # the countdown ends a beat before the line
    beats = int(room / 0.6)
    assert 1 <= beats < 4
    assert (countdown.count, countdown.beat) == (beats, 0.6)
    assert countdown.end == pytest.approx(2.9)
    assert title.end <= countdown.start < title.end + 0.6  # the first whole beat after the title
    full = countdowns(scene_at([line(3.5, 5.0)], 100.0, chosen))[0]
    assert full.box.w == pytest.approx(
        beats * DOT_SPACING * COUNTDOWN_HEIGHT * 0.12 * 648, abs=0.01
    )


def test_a_break_screen_cuts_the_countdown_the_same_way() -> None:
    scene = scene_at([line(10, 12), line(27, 29)], 100.0)
    (pause,) = cards(scene, "break")
    late = countdowns(scene)[1]
    assert late.start >= pause.end - 0.001
    assert late.end == pytest.approx(26.4)
    assert late.count == min(4, int((26.4 - pause.end) / 0.6 + 1e-6))


def test_a_countdown_never_starts_before_the_line_before_it_ends() -> None:
    # an own look with a short gap: 4 beats of 1 s do not fit into the 3.5 s after the line,
    # less the beat before the line
    chosen = profile(countdown={"min_gap": 3.0, "form": "dots"})
    scene = scene_at([line(10, 12), line(15.5, 17)], 60.0, chosen)
    after = countdowns(scene)[-1]
    assert after.end == pytest.approx(14.5 + scene.lead)
    assert (after.count, after.beat) == (2, 1.0)  # the first whole beat after the line
    assert after.start >= 12.0 + scene.lead - 0.001


def test_without_a_tempo_the_countdown_is_cut_where_the_line_before_ends() -> None:
    chosen = profile(countdown={"min_gap": 1.0, "duration": 2.0})
    scene = scene_at([line(10, 12), line(13.5, 15)], None, chosen)
    after = countdowns(scene)[-1]
    assert (after.start, after.end) == pytest.approx((12.0 + scene.lead, 13.5 + scene.lead))
    assert after.beat is None


def test_a_line_that_leaves_less_than_a_beat_gets_no_countdown() -> None:
    chosen = profile(countdown={"min_gap": 0.5, "count": 2})
    scene = scene_at([line(10, 12), line(13.8, 15)], 60.0, chosen)  # 2 beats of 1 s
    (first,) = countdowns(scene)  # 1.8 s after the line, less the beat before: none there
    assert first.end == pytest.approx(9.0 + scene.lead)


def test_no_countdown_when_not_even_one_beat_fits_after_the_title_screen() -> None:
    chosen = profile(countdown={"min_gap": 1.0, "count": 2}, intro=NO_INTRO)
    scene = scene_at([line(2.0, 4.0)], 30.0, chosen)  # 2 beats of 2 s
    (title,) = cards(scene, "title")
    assert 2.0 - title.end < 2.0
    assert countdowns(scene) == []


def test_the_countdown_after_the_silent_intro_counts_beats_too() -> None:
    scene = scene_at([line(2, 4)], 100.0)  # a song that starts early gets a silent intro
    assert scene.lead > 0
    (countdown,) = countdowns(scene)
    assert (countdown.count, countdown.beat) == (4, 0.6)
    assert countdown.end == pytest.approx(2.0 + scene.lead - 0.6)


def window(
    bpm: float | None, sing_start: float, floor: float = 0.0, **setting: float
) -> CountdownWindow | None:
    return countdown_window(Countdown.model_validate(setting), bpm, sing_start, floor)


def test_four_beats_before_the_line_when_there_is_room() -> None:
    found = window(100.0, 10.0)
    assert found is not None
    assert (found.end, found.count, found.beat) == (pytest.approx(9.4), 4, 0.6)
    assert found.start == pytest.approx(7.0)


def test_four_beats_of_a_second_end_one_beat_before_the_line() -> None:
    # 60 bpm: the dots go out at 12, 13, 14 and 15 s, the singing starts on the next beat
    assert window(60.0, 16.0) == CountdownWindow(11.0, 15.0, 4, 1.0)
    assert window(60.0, 16.0, floor=12.0) == CountdownWindow(12.0, 15.0, 3, 1.0)
    assert window(60.0, 16.0, floor=14.5) is None  # half a beat before the end: no countdown


def test_a_countdown_that_fits_the_room_exactly_keeps_all_its_beats() -> None:
    exact = window(100.0, 10.0, floor=7.0)
    assert exact is not None
    assert exact.count == 4
    rounding = window(100.0, 10.0, floor=7.0 + 1e-9)
    assert rounding is not None
    assert rounding.count == 4


def test_one_beat_less_room_means_one_beat_less() -> None:
    found = window(100.0, 10.0, floor=7.01)
    assert found is not None
    assert (found.count, found.start) == (3, pytest.approx(7.6))


def test_a_single_beat_of_room_means_a_countdown_of_one_beat() -> None:
    found = window(100.0, 10.0, floor=8.8)
    assert found is not None
    assert (found.count, found.start, found.end) == (1, pytest.approx(8.8), pytest.approx(9.4))


def test_a_song_without_a_title_screen_counts_down_from_the_start_of_the_video() -> None:
    # sung at 1.9 s with no title and no intro: two beats of 0.6 s fit before the beat before the
    # line, the first at 0.1 s
    look = profile(title={"fields": []}, intro={"solo": 0, "group": 0}, countdown={"min_gap": 1.0})
    (countdown,) = countdowns(scene_at([line(1.9, 3)], 100.0, look))
    assert (countdown.count, countdown.start) == (2, pytest.approx(0.1))


def test_less_than_a_beat_of_room_means_no_countdown() -> None:
    assert window(100.0, 10.0, floor=8.81) is None
    assert window(100.0, 10.0, floor=9.4) is None
    assert window(100.0, 10.0, floor=10.0) is None
    assert window(100.0, 10.0, floor=11.0) is None


def test_without_a_tempo_the_window_is_the_duration_cut_at_the_floor() -> None:
    free = window(None, 10.0, duration=2.0)
    assert free == CountdownWindow(8.0, 10.0, 4)
    cut = window(None, 10.0, floor=9.0, duration=2.0)
    assert cut == CountdownWindow(9.0, 10.0, 4)  # the count of dots stays
    assert window(None, 10.0, floor=10.0, duration=2.0) is None


def test_the_count_of_the_look_caps_the_beats() -> None:
    found = window(100.0, 10.0, floor=0.0, count=2)
    assert found is not None
    assert (found.count, found.beat) == (
        2,
        1.2,
    )  # 2 beats of 0.6 s are 1.2 s: too short, so the beat is doubled


# ----------------------------------------------------------------- the timer of a break screen


def timers(scene: Scene) -> list[TimerElement]:
    return [e for e in scene.elements if isinstance(e, TimerElement)]


def with_timer(**breaks: JsonValue) -> Profile:
    return profile(breaks={"form": "timer", **breaks})


def test_the_timer_counts_whole_seconds_until_the_next_lines_appear() -> None:
    scene = scene_of([line(10, 12), line(40, 42)], with_timer())
    (pause,) = cards(scene, "break")
    (timer,) = timers(scene)
    assert (timer.start, timer.end) == (pause.start, pause.end)
    assert timer.end == scene.lines()[1].start  # it goes when the next lines appear
    left = timer.end - timer.start
    assert timer.total == math.ceil(left)
    assert timer.seconds_left(timer.start) == timer.total
    assert timer.seconds_left(timer.end - 0.001) == 1
    shown = [timer.seconds_left(timer.start + 0.5 * n) for n in range(int(left * 2))]
    assert shown == sorted(shown, reverse=True)  # never up
    assert {a - b for a, b in zip(shown, shown[1:], strict=False)} <= {0, 1}  # one at a time
    assert timer.changes()[0] == pytest.approx(timer.end - timer.total + 1)


def test_the_timer_sits_under_the_notice_in_the_middle() -> None:
    scene = scene_of([line(10, 12), line(40, 42)], with_timer())
    (pause,) = cards(scene, "break")
    (timer,) = timers(scene)
    (notice,) = pause.lines  # the screen keeps its text; the timer is its own element
    safe = scene.safe
    assert timer.box.x + timer.box.w / 2 == pytest.approx(safe.x + safe.w / 2, abs=0.01)
    assert timer.box.y >= pause.box.bottom  # under the text
    assert timer.size == pytest.approx(0.8 * notice.size, abs=0.01)  # 0.8 of the notice
    assert timer.colour == profile().colours.group.sung
    assert timer.edge_colour == profile().colours.group.edge
    block_middle = (pause.box.y + timer.box.bottom) / 2  # notice and timer are centred together
    assert block_middle == pytest.approx(safe.y + safe.h / 2, abs=0.1 * notice.size)
    assert timer.text_y == pytest.approx(timer.box.y + profile().padding(timer.size), abs=0.01)


def test_the_timer_box_is_as_wide_as_its_widest_number() -> None:
    scene = scene_of([line(10, 12), line(40, 42)], with_timer())
    (timer,) = timers(scene)
    pad = profile().padding(timer.size)
    digits = len(str(timer.total))  # the fixed measurer: every character is half the size wide
    assert timer.box.w == pytest.approx(digits * 0.5 * timer.size + 2 * pad, abs=0.01)
    assert timer_text(FixedMeasurer(), 9, 10.0) == "1"  # the first of equally wide numbers
    assert timer_text(FixedMeasurer(), 25, 10.0) == "10"
    assert timer_text(FixedMeasurer(), 1, 10.0) == "1"


def test_a_notice_without_the_timer_form_has_none_and_a_short_gap_has_no_break_screen() -> None:
    assert timers(scene_of([line(10, 12), line(40, 42)], profile())) == []
    assert (
        timers(scene_of([line(10, 12), line(40, 42)], profile(breaks={"form": "progress"}))) == []
    )
    assert timers(scene_of([line(10, 12), line(20, 22)], with_timer())) == []  # 8 s: no screen


def test_every_break_screen_has_a_timer_that_goes_with_it() -> None:
    scene = scene_of([line(10, 12), line(40, 42), line(80, 82)], with_timer())
    screens, counted = cards(scene, "break"), timers(scene)
    assert [(c.start, c.end) for c in screens] == [(t.start, t.end) for t in counted]
    assert len(screens) == 2


def test_the_timer_stays_inside_the_safe_area_with_the_title_on_the_break_screen() -> None:
    look = with_timer(show_title=True)
    scene = scene_of([line(10, 12), line(40, 42)], look, title="Ein langer Titel " * 3)
    (timer,) = timers(scene)
    (pause,) = cards(scene, "break")
    assert len(pause.lines) == 3  # the notice, the title and the artist
    assert timer.box.inside(scene.safe) and timer.box.y >= pause.box.bottom


def test_split_timer_takes_the_last_line_out_of_the_screen() -> None:
    canvas = Canvas(FixedMeasurer(), profile(), Rect(x=0.0, y=0.0, w=800.0, h=600.0), 50.0)
    lines = [CardText("Pause", 0.9, "#ffffff"), CardText("12", 0.72, "#ff0000")]
    screen = card("break", lines, canvas, 5.0, 17.0)
    text, timer = split_timer(screen)
    assert [x.text for x in text.lines] == ["Pause"]
    assert text.box == screen.lines[0].box and timer.box == screen.lines[1].box
    assert (timer.start, timer.end, timer.colour) == (5.0, 17.0, "#ff0000")
    assert timer.total == 12


def test_with_slot_per_row_a_slot_is_one_row_high() -> None:
    rows = profile(
        mode="page", slots=4, line_rows=2, page={"slot_per_row": True}, cdg={"slots": 4},
        font={"size": 0.1, "min_size": 0.07},
    )  # fmt: skip
    two = rows.model_copy(update={"page": rows.page.model_copy(update={"slot_per_row": False})})
    safe = Rect(x=48.0, y=36.0, w=864.0, h=648.0)
    size = 0.1 * 648
    one_row, _, _ = slot_rects(rows, safe, size, rows.padding(size))
    shared, _, _ = slot_rects(two, safe, size, two.padding(size))
    assert len(one_row) == 4
    assert one_row[0].h == pytest.approx(size + 2 * rows.padding(size), abs=0.01)
    assert shared[0].h == pytest.approx(2 * one_row[0].h + ROW_GAP * size, abs=0.01)


def test_the_block_shortfall_of_slots_over_rows_names_one_row() -> None:
    tall = profile(
        mode="page", slots=6, line_rows=2, page={"slot_per_row": True}, cdg={"slots": 6},
        font={"size": 0.3, "min_size": 0.08},
    )  # fmt: skip
    scene = layout([line(10, 12)], SongText("T", None, 30.0, {}), tall, (960, 720), FixedMeasurer())
    assert [s.message for s in scene.shortfalls if s.kind == "block"] == [
        "the slots and the countdown do not fit the safe area"
    ]


def box(rect: Rect) -> tuple[float, float, float, float]:
    return rect.x, rect.y, rect.w, rect.h


SLOT_SAFE = Rect(x=10.0, y=20.0, w=200.0, h=100.0)  # bottom 120
SLOT_SIZE, SLOT_PAD = 10.0, 1.0  # a slot is 12 high, the gaps 1; the band 3 high, 1 above the slots


@pytest.mark.parametrize(
    ("position", "top"),
    [("top", 29.5), ("middle", 57.5), ("lower-third", 82.5), ("bottom", 95.0)],
)
def test_the_block_of_slots_sits_where_the_position_says_and_stays_above_the_bottom(
    position: str, top: float
) -> None:
    look = profile(slots=2, line_rows=1, position=position, cdg={"slots": 2})
    slots, band, row = slot_rects(look, SLOT_SAFE, SLOT_SIZE, SLOT_PAD)
    # the block is 2 * 12 + 1 = 25 high; "bottom" would end at 120.5 and is moved up to 120
    assert [box(s) for s in slots] == [
        pytest.approx((10.0, top, 200.0, 12.0)),
        pytest.approx((10.0, top + 13.0, 200.0, 12.0)),
    ]
    assert box(band) == pytest.approx((10.0, top - 4.0, 200.0, 3.0))
    assert row is None


def test_the_countdown_band_is_kept_inside_the_safe_area_at_the_top() -> None:
    short = Rect(x=10.0, y=20.0, w=200.0, h=30.0)  # bottom 50; the block is 25 high
    top = profile(slots=2, line_rows=1, position="top", cdg={"slots": 2})
    bottom = profile(slots=2, line_rows=1, position="bottom", cdg={"slots": 2})
    slots, band, _ = slot_rects(top, short, SLOT_SIZE, SLOT_PAD)
    assert slots[0].y == pytest.approx(24.0) and band.y == pytest.approx(20.0)  # not 14.1
    slots, band, _ = slot_rects(bottom, short, SLOT_SIZE, SLOT_PAD)
    assert slots[0].y == pytest.approx(25.0) and slots[-1].bottom == pytest.approx(50.0)


def test_three_slots_of_two_rows_are_spaced_by_their_height_and_the_gap() -> None:
    look = profile(
        slots=3, line_rows=2, position="middle", page={"slot_per_row": False}, cdg={"slots": 3}
    )
    slots, band, _ = slot_rects(look, SLOT_SAFE, SLOT_SIZE, SLOT_PAD)
    # a slot is 2 * 12 + 1 = 25 high; the block 3 * 25 + 2 * 1 = 77; it starts at 70 - 38.5
    assert [box(s) for s in slots] == [
        pytest.approx((10.0, 31.5, 200.0, 25.0)),
        pytest.approx((10.0, 57.5, 200.0, 25.0)),
        pytest.approx((10.0, 83.5, 200.0, 25.0)),
    ]
    assert box(band) == pytest.approx((10.0, 27.5, 200.0, 3.0))


def test_the_preview_row_sits_one_gap_below_the_only_slot() -> None:
    look = previewing()
    slots, band, row = slot_rects(look, SLOT_SAFE, SLOT_SIZE, SLOT_PAD)
    small = 0.7 * SLOT_SIZE
    row_h = small + 2 * look.padding(small)
    top = 20.0 + 0.75 * 100.0 - (12.0 + 1.0 + row_h) / 2
    assert row is not None
    assert box(slots[0]) == pytest.approx((10.0, top, 200.0, 12.0))
    assert box(row) == pytest.approx((10.0, top + 13.0, 200.0, row_h))
    assert box(band) == pytest.approx((10.0, top - 4.0, 200.0, 3.0))


def test_the_bottom_position_centres_the_block_at_88_percent_of_a_tall_safe_area() -> None:
    tall = Rect(x=10.0, y=20.0, w=200.0, h=300.0)  # the block (25) is far from the bottom edge
    look = profile(slots=2, line_rows=1, position="bottom", cdg={"slots": 2})
    slots, _, _ = slot_rects(look, tall, SLOT_SIZE, SLOT_PAD)
    assert slots[0].y == pytest.approx(20.0 + 0.88 * 300.0 - 12.5)
