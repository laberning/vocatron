"""Stage 1: the start screen with the wordmark on the scene, never on a frame (ADR-0055)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from conformance.scene_rules import check_scene
from fakes.measure import FixedMeasurer
from fakes.phrases import line
from fakes.rule_breaks import hits, line_far_away, messages, mutate, word_outside
from fakes.scenes import builtin_profile, entchen_scene, entchen_with
from vocatron.core.cdg.canvas import cdg_scene
from vocatron.core.cdg.look import cdg_profile
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.cards import LINE_PITCH, ROW_PITCH, Canvas, CardText
from vocatron.core.layout.mark import (
    BUILD_MIN,
    EDGE_IN,
    FILL_STEPS,
    FRAME_HEIGHT,
    FRAME_INSET_X,
    FRAME_INSET_Y,
    FRAME_WIDTH,
    MARK_GAP,
    MARK_MAX_HEIGHT,
    PIXEL_ARTIST_PX,
    PIXEL_FLOOR_PX,
    PIXEL_FRAME_HEIGHT,
    PIXEL_FRAME_WIDTH,
    PIXEL_NAME_PX,
    PIXEL_RULE_HEIGHT,
    PIXEL_TITLE_PX,
    RULE_HEIGHT,
    RULE_SPACE,
    SIZE_SLACK,
    TEXT_EDGE,
    WIPE_IN,
    _best,
    _flowed,
    _lay,
    _wrapped,
    wordmark_card,
)
from vocatron.core.lyrics.document import SingerInfo
from vocatron.core.profiles.model import BUILTIN_PROFILES, CLASSIC_PROFILES, Profile
from vocatron.core.scene import CardElement, Rect, Scene
from vocatron.core.wordmark import (
    AMBER,
    FIELD_COLOUR,
    PIXEL_SCALE,
    SYLLABLES,
    TEXT_COLOUR,
    pixel_word_columns,
)

WORDMARK: JsonValue = {"form": "wordmark"}
LONG_TITLE = "Der Mond ist aufgegangen, die goldnen Sternlein prangen am Himmel hell und klar"
LONG_ARTIST = "Matthias Claudius und Johann Abraham Peter Schulz mit dem Chor"
FIVE_NAMES = {
    i + 1: SingerInfo(name=n) for i, n in enumerate(["Anna", "Ben", "Clara", "Dora", "Emil"])
}
FRAMES = {"4:3": (960, 720), "16:9": (1280, 720)}


def wordmark_profile(**overrides: JsonValue) -> Profile:
    merged: dict[str, JsonValue] = {"title": WORDMARK, **overrides}
    return builtin_profile("two-line-turns", **merged)


def title_of(scene: Scene) -> CardElement:
    (found,) = [e for e in scene.elements if isinstance(e, CardElement) and e.kind == "title"]
    return found


def scene_of(
    frame: tuple[int, int] = (960, 720),
    *,
    title: str = "Titel",
    artist: str | None = "Künstler",
    first: float = 8.0,
    singers: dict[int, SingerInfo] | None = None,
    chosen: Profile | None = None,
) -> Scene:
    look = chosen or wordmark_profile()
    song = SongText(title, artist, 60.0, singers or {})
    return layout([line(first, first + 2, "la la")], song, look, frame, FixedMeasurer())


@pytest.mark.parametrize("frame", FRAMES.values(), ids=FRAMES.keys())
def test_the_title_has_the_wordmark_a_frame_and_the_texts_inside_the_safe_area(
    frame: tuple[int, int],
) -> None:
    scene = scene_of(frame)
    check_scene(scene, wordmark_profile())
    title = title_of(scene)
    assert title.mark is not None
    mark = title.mark
    assert mark.word.inside(scene.safe)
    assert mark.frame.inside(scene.safe)
    assert not mark.word.overlaps(mark.frame)
    assert mark.word.bottom < mark.frame.y
    assert mark.field == FIELD_COLOUR
    assert all(text.box.inside(mark.frame) for text in title.lines)
    assert title.box.inside(scene.safe)
    assert mark.word.inside(title.box) and mark.frame.inside(title.box)
    assert all(text.edge_colour == TEXT_EDGE for text in title.lines)


def test_the_texts_are_capitals_the_title_white_the_artist_amber_with_a_rule_between() -> None:
    title = title_of(scene_of())
    assert [(x.text, x.colour) for x in title.lines] == [
        ("TITEL", TEXT_COLOUR),
        ("KÜNSTLER", AMBER),
    ]
    assert title.mark is not None
    rule = title.mark.rule
    assert rule is not None
    assert rule.inside(title.mark.frame)
    first, second = title.lines
    assert first.box.bottom <= rule.y + 1e-3
    assert rule.bottom <= second.box.y + second.size  # the rule stands between the two texts
    assert abs(rule.x + rule.w / 2 - (title.mark.frame.x + title.mark.frame.w / 2)) < 1e-2


def test_without_an_artist_there_is_no_rule() -> None:
    title = title_of(scene_of(artist=None))
    assert title.mark is not None
    assert title.mark.rule is None
    assert [x.text for x in title.lines] == ["TITEL"]


def test_the_singers_follow_the_artist_in_their_colours_inside_the_frame() -> None:
    singers = {1: SingerInfo(name="Anna", colour="#22aa55"), 2: SingerInfo(name="Ben")}
    title = title_of(scene_of(singers=singers))
    assert [x.text for x in title.lines][:2] == ["TITEL", "KÜNSTLER"]
    assert [x.text for x in title.lines][2:] == ["Anna", "Ben"]
    assert title.lines[2].colour == "#22aa55"
    assert title.mark is not None
    assert all(x.box.inside(title.mark.frame) for x in title.lines)


def test_the_build_up_has_the_edge_three_fills_and_the_wipe_in_order_inside_the_window() -> None:
    title = title_of(scene_of(first=9.0))
    assert title.end >= BUILD_MIN
    assert title.mark is not None
    build = title.mark.build
    assert build is not None
    assert (build.edge.start, build.edge.end) == EDGE_IN
    assert [(f.first, f.last) for f in build.fills] == list(SYLLABLES)
    assert [(f.when.start, f.when.end) for f in build.fills] == list(FILL_STEPS)
    assert (build.wipe.start, build.wipe.end) == WIPE_IN
    assert build.edge.end <= build.fills[0].when.start
    assert build.fills[-1].when.end <= build.wipe.start
    assert build.wipe.end <= 2.0 + 1e-9 < title.end


def test_a_title_of_less_than_four_seconds_has_no_build_up() -> None:
    chosen = wordmark_profile(
        title={"form": "wordmark", "min": 2.0, "min_short": 2.0}, intro={"solo": 0.0, "group": 0.0}
    )
    scene = scene_of(first=2.0 + chosen.lead_in.target, chosen=chosen)
    title = title_of(scene)
    assert title.end < BUILD_MIN
    assert title.mark is not None
    assert title.mark.build is None
    check_scene(scene, chosen)


def test_the_build_up_starts_at_exactly_four_seconds() -> None:
    chosen = wordmark_profile(
        title={"form": "wordmark", "min": 4.0, "min_short": 4.0}, intro={"solo": 0.0, "group": 0.0}
    )
    title = title_of(scene_of(first=4.0 + chosen.lead_in.target, chosen=chosen))
    assert title.end == pytest.approx(BUILD_MIN)
    assert title.mark is not None
    assert title.mark.build is not None


def test_plain_gives_the_start_screen_of_before_without_a_mark() -> None:
    chosen = builtin_profile("two-line-turns", title={"form": "plain"})
    title = title_of(scene_of(chosen=chosen))
    assert title.mark is None
    assert [x.text for x in title.lines] == ["Titel", "Künstler"]


def test_the_looks_all_have_the_same_wordmark_and_colours() -> None:
    marks = []
    for name in BUILTIN_PROFILES:
        chosen = builtin_profile(name, title=WORDMARK)
        scene = scene_of(chosen=chosen)
        check_scene(scene, chosen)
        title = title_of(scene)
        assert title.mark is not None
        marks.append((title.mark.field, title.mark.word, title.mark.scale))
        assert [x.colour for x in title.lines][:2] == [TEXT_COLOUR, AMBER]
        assert all(x.edge_colour == TEXT_EDGE for x in title.lines)
    assert len(set(marks)) == 1


def test_the_times_of_the_title_do_not_change_with_the_form() -> None:
    plain = title_of(scene_of(chosen=builtin_profile("two-line-turns", title={"form": "plain"})))
    marked = title_of(scene_of())
    assert (plain.start, plain.end) == (marked.start, marked.end)


def cdg_title(
    chosen: Profile | None = None,
    first: float = 8.0,
    singers: dict[int, SingerInfo] | None = None,
    artist: str | None = "Künstler",
) -> CardElement:
    song = SongText("Titel", artist, 60.0, singers or {})
    look = chosen or wordmark_profile()
    return title_of(cdg_scene([line(first, first + 2, "la la")], song, look, FixedMeasurer()))


def test_the_cdg_scene_has_the_wordmark_in_pixel_letters_without_a_build_up() -> None:
    chosen = wordmark_profile()
    scene = cdg_scene(
        [line(8.0, 10.0, "la la")], SongText("Titel", "Künstler", 60.0, {}), chosen, FixedMeasurer()
    )
    check_scene(scene, chosen)
    title = title_of(scene)
    assert title.mark is not None
    mark = title.mark
    assert (mark.pixel, mark.build, mark.scale) == (True, None, PIXEL_SCALE)
    assert (mark.word.w, mark.word.h) == (PIXEL_SCALE * pixel_word_columns(), 33.0)
    assert mark.word.inside(scene.safe) and mark.frame.inside(scene.safe)
    assert not mark.word.overlaps(mark.frame)
    assert mark.field == FIELD_COLOUR
    assert [(x.text, x.colour) for x in title.lines] == [
        ("TITEL", TEXT_COLOUR),
        ("KÜNSTLER", AMBER),
    ]
    assert all(x.edge_colour == FIELD_COLOUR for x in title.lines)  # no outline: nothing to colour
    assert mark.rule is not None and mark.rule.h == PIXEL_RULE_HEIGHT
    assert all(x.box.inside(mark.frame) for x in title.lines)


def test_the_pixel_wordmark_is_centred_in_the_safe_area() -> None:
    scene = cdg_scene(
        [line(8.0, 10.0, "la la")],
        SongText("T", None, 60.0, {}),
        wordmark_profile(),
        FixedMeasurer(),
    )
    mark = title_of(scene).mark
    assert mark is not None
    assert mark.word.x + mark.word.w / 2 == pytest.approx(scene.safe.x + scene.safe.w / 2)
    assert mark.frame.x + mark.frame.w / 2 == pytest.approx(scene.safe.x + scene.safe.w / 2)


def long_cdg_title(
    look: str,
    singers: dict[int, SingerInfo] | None = None,
    title: str = LONG_TITLE,
    artist: str = LONG_ARTIST,
) -> CardElement:
    chosen = cdg_profile(wordmark_profile_of(look))
    song = SongText(title, artist, 60.0, singers or {})
    return title_of(cdg_scene([line(9.0, 11.0, "la la")], song, chosen, FixedMeasurer()))


def wordmark_profile_of(look: str) -> Profile:
    return builtin_profile(look, title=WORDMARK)


@pytest.mark.parametrize("look", CLASSIC_PROFILES)
def test_the_cdg_start_screen_has_its_own_sizes_the_same_in_every_look(look: str) -> None:
    singers = {1: SingerInfo(name="Anna"), 2: SingerInfo(name="Ben")}
    title = long_cdg_title(look, singers, title="Kleine Nacht", artist="Der Chor")
    assert title.mark is not None
    assert [x.size for x in title.lines[:2]] == [PIXEL_TITLE_PX, PIXEL_ARTIST_PX]
    assert [x.size for x in title.lines[2:]] == [PIXEL_NAME_PX, PIXEL_NAME_PX]


@pytest.mark.parametrize("look", CLASSIC_PROFILES)
def test_a_title_too_wide_for_the_cdg_frame_wraps_and_keeps_its_size(look: str) -> None:
    title = long_cdg_title(look, title="Der Mond ist aufgegangen", artist="Matthias Claudius")
    assert title.mark is not None
    assert [x.text for x in title.lines] == ["DER MOND IST", "AUFGEGANGEN", "MATTHIAS CLAUDIUS"]
    assert [x.size for x in title.lines] == [PIXEL_TITLE_PX, PIXEL_TITLE_PX, PIXEL_ARTIST_PX]
    assert all(x.box.inside(title.mark.frame) for x in title.lines)


@pytest.mark.parametrize("look", CLASSIC_PROFILES)
@pytest.mark.parametrize("singers", [{}, FIVE_NAMES], ids=["no singers", "five singers"])
def test_a_very_long_title_or_five_singers_make_it_the_plain_card_on_cdg(
    look: str, singers: dict[int, SingerInfo]
) -> None:
    title = long_cdg_title(look, singers)
    assert title.mark is None  # the title cannot keep the smallest size, nor nine lines
    assert [x.text for x in title.lines][:2] == [LONG_TITLE, LONG_ARTIST]  # as written


@pytest.mark.parametrize("look", CLASSIC_PROFILES)
def test_a_text_below_the_floor_gives_the_plain_card_in_the_looks_colours(look: str) -> None:
    chosen = cdg_profile(wordmark_profile_of(look))
    song = SongText(LONG_TITLE, None, 60.0, {})
    plain = title_of(cdg_scene([line(9.0, 11.0, "la la")], song, chosen, FixedMeasurer()))
    assert plain.mark is None
    assert [x.text for x in plain.lines] == [LONG_TITLE]
    assert plain.lines[0].colour == chosen.colours.group.unsung
    assert plain.lines[0].size < PIXEL_FLOOR_PX  # what the wordmark screen would have had


def test_the_floor_is_the_same_whatever_the_looks_smallest_size_says() -> None:
    chosen = cdg_profile(wordmark_profile_of("three-line"))
    assert chosen.cdg is not None
    loose = chosen.model_copy(update={"cdg": chosen.cdg.model_copy(update={"min_font_px": 4})})
    song = SongText("Der Mond ist aufgegangen", "Matthias Claudius", 60.0, {})
    title = title_of(cdg_scene([line(9.0, 11.0, "la la")], song, loose, FixedMeasurer()))
    assert title.mark is not None and min(x.size for x in title.lines) >= PIXEL_FLOOR_PX


def test_the_floor_does_not_apply_to_the_video() -> None:
    title = title_of(scene_of(title=LONG_TITLE, artist=LONG_ARTIST, singers=FIVE_NAMES))
    assert title.mark is not None and not title.mark.pixel


def test_the_form_plain_gives_the_plain_start_screen_on_cdg() -> None:
    title = cdg_title(builtin_profile("two-line-turns", title={"form": "plain"}))
    assert title.mark is None
    assert [x.text for x in title.lines] == ["Titel", "Künstler"]


def test_a_start_screen_shorter_than_four_seconds_is_the_plain_card_on_cdg() -> None:
    short = wordmark_profile(
        title={"form": "wordmark", "min": 2.0, "min_short": 2.0}, intro={"solo": 0.0, "group": 0.0}
    )
    title = cdg_title(short, first=5.0)  # the title ends 3 s before the first line: 2 s
    assert title.end - title.start == pytest.approx(2.0)
    assert title.mark is None
    assert [x.text for x in title.lines] == ["Titel", "Künstler"]  # not in capitals
    video = title_of(
        layout(
            [line(5.0, 7.0, "la la")],
            SongText("Titel", "Künstler", 60.0, {}),
            short,
            (960, 720),
            FixedMeasurer(),
        )
    )
    assert video.mark is not None and video.mark.build is None  # a short screen in the video too


def test_the_break_and_end_screens_of_cdg_stay_plain_in_the_looks_colours() -> None:
    chosen = wordmark_profile(colours={"group": {"unsung": "#e0e0a0"}})
    scene = cdg_scene(
        [line(8.0, 10.0, "la"), line(30.0, 32.0, "li")],
        SongText("Titel", "Künstler", 60.0, {}),
        chosen,
        FixedMeasurer(),
    )
    others = [e for e in scene.elements if isinstance(e, CardElement) and e.kind != "title"]
    assert {e.kind for e in others} == {"break", "end"}
    for card in others:
        assert card.mark is None
        assert all(x.colour == chosen.colours.group.unsung for x in card.lines)
    end = next(e for e in others if e.kind == "end")
    assert [x.text for x in end.lines] == ["Titel", "Künstler"]


def test_the_pixel_frame_has_its_own_share_of_the_safe_area_and_the_video_rule_its_height() -> None:
    scene = cdg_scene(
        [line(8.0, 10.0, "la la")],
        SongText("Titel", "Künstler", 60.0, {}),
        wordmark_profile(),
        FixedMeasurer(),
    )
    mark = title_of(scene).mark
    assert mark is not None
    assert mark.frame.w == pytest.approx(PIXEL_FRAME_WIDTH * scene.safe.w, abs=0.01)
    assert mark.frame.h == pytest.approx(PIXEL_FRAME_HEIGHT * scene.safe.h, abs=0.01)
    video = title_of(scene_of()).mark
    assert video is not None and video.rule is not None
    video_safe = scene_of().safe
    assert video.frame.w == pytest.approx(FRAME_WIDTH * video_safe.w, abs=0.01)
    assert video.frame.h == pytest.approx(FRAME_HEIGHT * video_safe.h, abs=0.01)
    assert video.rule.h == pytest.approx(max(RULE_HEIGHT * video.frame.h, 1.0), abs=0.01)


def test_the_video_end_screen_with_the_wordmark_has_the_names_in_capitals() -> None:
    scene = layout(
        [line(8.0, 10.0, "la"), line(30.0, 32.0, "li")],
        SongText("Titel", "Künstler", 60.0, {}),
        wordmark_profile(),
        (960, 720),
        FixedMeasurer(),
    )
    (end,) = [e for e in scene.elements if isinstance(e, CardElement) and e.kind == "end"]
    assert [(x.text, x.colour) for x in end.lines] == [("TITEL", TEXT_COLOUR), ("KÜNSTLER", AMBER)]


def test_the_video_start_screen_is_not_a_pixel_mark() -> None:
    title = title_of(scene_of())
    assert title.mark is not None and not title.mark.pixel


def test_rule_14_a_pixel_mark_with_a_build_up_or_on_a_short_screen() -> None:
    chosen = wordmark_profile()
    scene = cdg_scene(
        [line(8.0, 10.0, "la la")], SongText("Titel", "Künstler", 60.0, {}), chosen, FixedMeasurer()
    )
    assert hits(scene, chosen) == set()
    video = title_of(entchen_with(chosen))
    assert video.mark is not None

    def with_build(card: CardElement) -> CardElement:
        assert card.mark is not None
        mark = card.mark.model_copy(update={"build": video.mark.build if video.mark else None})
        return card.model_copy(update={"mark": mark})

    assert (
        "pixel mark on a short screen"
        in messages(mutate(scene, "title", 0, with_build), chosen, 14)[0]
    )

    def shortened(card: CardElement) -> CardElement:
        return card.model_copy(update={"end": 2.0})

    assert (
        "pixel mark on a short screen"
        in messages(mutate(scene, "title", 0, shortened), chosen, 14)[0]
    )


def test_a_very_long_title_is_made_smaller_until_it_stays_in_the_frame() -> None:
    scene = scene_of(title="Ein sehr langer Titel " * 6, artist="Eine Künstlerin " * 5)
    title = title_of(scene)
    assert title.mark is not None
    assert all(x.box.inside(title.mark.frame) for x in title.lines)
    short = title_of(scene_of())
    assert title.lines[0].size < short.lines[0].size


@pytest.mark.parametrize("singer_count", [0, 12], ids=["a long title", "twelve singers"])
def test_the_texts_keep_the_inset_from_the_frame_when_they_fill_it(singer_count: int) -> None:
    singers = {i + 1: SingerInfo(name=f"Name {i}") for i in range(singer_count)}
    title = title_of(scene_of(title="Ein sehr langer Titel " * 6, singers=singers))
    assert title.mark is not None
    frame = title.mark.frame
    slack = 1.0  # pixels: ``card`` lets a small line's box reach a little past its area
    inner = Rect(
        x=frame.x + FRAME_INSET_X * frame.w - slack,
        y=frame.y + FRAME_INSET_Y * frame.h - slack,
        w=frame.w * (1 - 2 * FRAME_INSET_X) + 2 * slack,
        h=frame.h * (1 - 2 * FRAME_INSET_Y) + 2 * slack,
    )
    assert all(x.box.inside(inner) for x in title.lines)
    if singer_count:  # the names fill the height
        assert min(x.box.y for x in title.lines) < inner.y + 0.05 * frame.h
    else:  # the title fills the width
        assert min(x.box.x for x in title.lines) < inner.x + 0.05 * frame.w


def test_a_title_too_wide_for_the_frame_wraps_onto_two_lines_before_it_is_shrunk() -> None:
    title = title_of(scene_of(title="Ein langer Titel im Rahmen", artist=None))
    assert [x.text for x in title.lines] == ["EIN LANGER", "TITEL IM RAHMEN"]
    alone = title_of(scene_of(artist=None))
    assert {x.size for x in title.lines} == {alone.lines[0].size}  # not shrunk at all
    assert title.mark is not None and all(x.box.inside(title.mark.frame) for x in title.lines)


def test_an_artist_wraps_too_and_the_rule_stands_under_the_last_row_of_the_title() -> None:
    title = title_of(
        scene_of(title="Ein langer Titel im Rahmen", artist="Eine Künstlerin mit Gefolge")
    )
    assert [x.text for x in title.lines] == [
        "EIN LANGER",
        "TITEL IM RAHMEN",
        "EINE KÜNSTLERIN",
        "MIT GEFOLGE",
    ]
    assert title.mark is not None and title.mark.rule is not None
    rule = title.mark.rule
    assert title.lines[1].box.bottom <= rule.y + 1e-3 <= title.lines[2].box.y + 1e-3
    assert title.lines[0].colour == title.lines[1].colour == TEXT_COLOUR
    assert title.lines[2].colour == title.lines[3].colour == AMBER


def test_a_text_wraps_only_when_it_and_its_padding_are_wider_than_the_frames_inside() -> None:
    chosen = wordmark_profile()
    measurer, size = FixedMeasurer(), 40.0
    text = "Ein langer Titel"
    room = measurer.width(text, size) + 2 * chosen.padding(size)
    canvas = Canvas(measurer, chosen, Rect(x=0, y=0, w=room, h=300), size)
    lines = [CardText(text, 1.0, TEXT_COLOUR, wraps=True)]
    assert len(_wrapped(lines[0], canvas, room)) == 1  # it just fits
    assert len(_wrapped(lines[0], canvas, room - 0.01)) == 2
    unwrapping = CardText(text, 1.0, TEXT_COLOUR)
    assert len(_wrapped(unwrapping, canvas, room - 0.01)) == 1  # names never wrap


def test_with_singers_named_the_rule_stays_under_the_last_row_of_the_title() -> None:
    title = title_of(
        scene_of(
            title="Ein langer Titel im Rahmen",
            artist="Eine Künstlerin",
            singers={1: SingerInfo(name="Anna")},
        )
    )
    assert title.mark is not None and title.mark.rule is not None
    assert [x.text for x in title.lines][:3] == ["EIN LANGER", "TITEL IM RAHMEN", "EINE KÜNSTLERIN"]
    rule = title.mark.rule
    assert title.lines[1].box.bottom <= rule.y + 1e-3 <= title.lines[2].box.y + 1e-3


def test_a_text_exactly_at_the_smallest_size_keeps_the_pixel_wordmark() -> None:
    chosen = cdg_profile(wordmark_profile())
    scene = cdg_scene(
        [line(8.0, 10.0, "la la")], SongText("T", None, 60.0, {}), chosen, FixedMeasurer()
    )
    canvas = Canvas(FixedMeasurer(), chosen, scene.safe, 36.0)
    lines = [CardText("TITEL", 1.0, TEXT_COLOUR, wraps=True)]
    free = wordmark_card(lines, canvas, 10.0, None, pixel=True)
    assert free is not None
    size = free.lines[0].size
    assert wordmark_card(lines, canvas, 10.0, None, True, size + SIZE_SLACK / 2) is not None
    assert wordmark_card(lines, canvas, 10.0, None, True, size + 2 * SIZE_SLACK) is None


def test_a_text_that_fits_or_has_one_word_is_not_wrapped() -> None:
    assert [x.text for x in title_of(scene_of()).lines] == ["TITEL", "KÜNSTLER"]
    one = title_of(scene_of(title="Donaudampfschifffahrtsgesellschaftskapitän", artist=None))
    assert len(one.lines) == 1  # a single word is shrunk
    assert one.lines[0].size < title_of(scene_of(artist=None)).lines[0].size


def test_the_singers_names_are_not_wrapped() -> None:
    names = {1: SingerInfo(name="Anna Maria Lena Sophie Katharina Elisabeth Charlotte Wilhelmina")}
    assert len(title_of(scene_of(singers=names)).lines) == 3


def test_on_a_very_wide_picture_the_wordmark_is_held_to_its_height() -> None:
    scene = scene_of((2880, 720))
    title = title_of(scene)
    assert title.mark is not None
    assert title.mark.word.h == pytest.approx(MARK_MAX_HEIGHT * scene.safe.h, abs=0.01)
    assert title.mark.word.inside(scene.safe)


def test_wordmark_gap_and_frame_always_fit_the_safe_height() -> None:
    assert MARK_MAX_HEIGHT + MARK_GAP + FRAME_HEIGHT <= 1.0


def test_five_singers_are_made_smaller_to_stay_in_the_frame() -> None:
    names = ["Anna", "Ben", "Clara", "Dora", "Emil"]
    singers = {i + 1: SingerInfo(name=n) for i, n in enumerate(names)}
    title = title_of(scene_of(singers=singers))
    assert title.mark is not None
    assert len(title.lines) == 2 + 5
    assert all(x.box.inside(title.mark.frame) for x in title.lines)
    alone = title_of(scene_of())
    assert title.lines[0].size <= alone.lines[0].size


@given(
    st.text(alphabet="abcdefgh ÄÖÜ", min_size=1, max_size=120).filter(lambda t: t.strip() != ""),
    st.text(alphabet="abcdefgh ÄÖÜ", min_size=1, max_size=120).filter(lambda t: t.strip() != ""),
    st.integers(0, 6),
    st.sampled_from(list(FRAMES.values())),
)
def test_the_lines_never_leave_the_frame_and_the_mark_never_leaves_the_safe_area(
    title: str, artist: str, singer_count: int, frame: tuple[int, int]
) -> None:
    singers = {i + 1: SingerInfo(name=f"Name {i}") for i in range(singer_count)}
    scene = scene_of(frame, title=title.strip(), artist=artist.strip(), singers=singers)
    shown = title_of(scene)
    assert shown.mark is not None
    assert all(x.box.inside(shown.mark.frame) for x in shown.lines)
    assert shown.mark.word.inside(scene.safe)
    assert shown.mark.frame.inside(scene.safe)


def test_a_song_without_lines_shows_the_start_screen_for_the_whole_song() -> None:
    song = SongText("Titel", "Künstler", 30.0, {})
    scene = layout([], song, wordmark_profile(), (960, 720), FixedMeasurer())
    title = title_of(scene)
    assert title.mark is not None
    assert title.mark.build is not None
    assert title.end == 30.0


def test_the_scene_of_a_long_song_in_scroll_mode_has_the_mark_too() -> None:
    chosen = builtin_profile("lyric-scroll", title=WORDMARK)
    title = title_of(entchen_with(chosen))
    assert title.mark is not None


# ------------------------------------------------------------------ rule 14 on the mark


def test_rule_14_a_mark_on_a_plain_title_screen() -> None:
    chosen = builtin_profile("two-line-turns", title={"form": "plain"})
    marked = title_of(entchen_scene(title=WORDMARK))
    scene = mutate(
        entchen_scene(), "title", 0, lambda t: t.model_copy(update={"mark": marked.mark})
    )
    assert "a mark on a plain title screen" in messages(scene, chosen, 14)[0]


def test_rule_14_a_line_that_leaves_the_frame() -> None:
    chosen = wordmark_profile()
    scene = entchen_with(chosen)
    assert hits(scene, chosen) == set()

    assert "leaves the frame" in messages(mutate(scene, "title", 0, line_far_away), chosen, 14)[0]


def test_rule_14_a_build_up_that_does_not_belong_to_the_length_of_the_screen() -> None:
    chosen = wordmark_profile()
    scene = entchen_with(chosen)
    title = title_of(scene)
    assert title.mark is not None

    def without_build(card: CardElement) -> CardElement:
        assert card.mark is not None
        return card.model_copy(update={"mark": card.mark.model_copy(update={"build": None})})

    assert "build-up is wrong" in messages(mutate(scene, "title", 0, without_build), chosen, 14)[0]

    def late(card: CardElement) -> CardElement:
        assert card.mark is not None
        assert card.mark.build is not None
        wipe = card.mark.build.wipe.model_copy(update={"end": card.end + 1})
        build = card.mark.build.model_copy(update={"wipe": wipe})
        return card.model_copy(update={"mark": card.mark.model_copy(update={"build": build})})

    assert "leaves the title window" in messages(mutate(scene, "title", 0, late), chosen, 14)[0]


def test_rule_14_steps_of_the_build_up_that_overlap() -> None:
    chosen = wordmark_profile()
    scene = entchen_with(chosen)

    def overlap(card: CardElement) -> CardElement:
        assert card.mark is not None
        assert card.mark.build is not None
        first, *rest = card.mark.build.fills
        first = first.model_copy(
            update={"when": first.when.model_copy(update={"end": rest[0].when.end})}
        )
        build = card.mark.build.model_copy(update={"fills": [first, *rest]})
        return card.model_copy(update={"mark": card.mark.model_copy(update={"build": build})})

    assert "overlap" in messages(mutate(scene, "title", 0, overlap), chosen, 14)[0]


def test_rule_14_an_edge_that_still_fades_in_when_the_bands_fill() -> None:
    chosen = wordmark_profile()
    scene = entchen_with(chosen)

    def late_edge(card: CardElement) -> CardElement:
        assert card.mark is not None
        assert card.mark.build is not None
        build = card.mark.build
        edge = build.edge.model_copy(update={"end": build.fills[0].when.start + 0.1})
        later = build.model_copy(update={"edge": edge})
        return card.model_copy(update={"mark": card.mark.model_copy(update={"build": later})})

    assert "overlap" in messages(mutate(scene, "title", 0, late_edge), chosen, 14)[0]


def test_rule_14_a_rule_that_leaves_the_frame() -> None:
    chosen = wordmark_profile()
    scene = entchen_with(chosen)

    def low_rule(card: CardElement) -> CardElement:
        assert card.mark is not None
        assert card.mark.rule is not None
        rule = card.mark.rule.model_copy(update={"y": card.mark.frame.bottom})
        return card.model_copy(update={"mark": card.mark.model_copy(update={"rule": rule})})

    found = messages(mutate(scene, "title", 0, low_rule), chosen, 14)
    assert found == ["rule 14: the rule leaves the frame"]


def test_rule_14_a_wordmark_that_overlaps_the_frame() -> None:
    chosen = wordmark_profile()
    scene = entchen_with(chosen)

    def low_word(card: CardElement) -> CardElement:
        assert card.mark is not None
        word = card.mark.word.model_copy(update={"y": card.mark.frame.y})
        return card.model_copy(update={"mark": card.mark.model_copy(update={"word": word})})

    found = messages(mutate(scene, "title", 0, low_word), chosen, 14)
    assert found == ["rule 14: the wordmark and the frame overlap"]


def test_rule_14_a_build_up_that_ends_with_the_screen_is_accepted() -> None:
    chosen = wordmark_profile()
    scene = entchen_with(chosen)

    def to_the_end(card: CardElement) -> CardElement:
        assert card.mark is not None
        assert card.mark.build is not None
        wipe = card.mark.build.wipe.model_copy(update={"end": card.end})
        build = card.mark.build.model_copy(update={"wipe": wipe})
        return card.model_copy(update={"mark": card.mark.model_copy(update={"build": build})})

    assert messages(mutate(scene, "title", 0, to_the_end), chosen, 14) == []


def test_rule_1_the_wordmark_outside_the_safe_area() -> None:
    chosen = wordmark_profile()
    scene = entchen_with(chosen)

    assert "1" in hits(mutate(scene, "title", 0, word_outside), chosen)


# ------------------------------------------------------------------ the four seconds of every look


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
@pytest.mark.parametrize("duet", [False, True], ids=["solo", "duet"])
def test_in_every_built_in_look_a_song_sung_from_the_start_gets_a_start_screen_of_four_seconds(
    name: str, duet: bool
) -> None:
    chosen = builtin_profile(name, title=WORDMARK)
    singers = ("1", "2") if duet else ("1", "1")
    lines = [
        line(0.0, 2.0, "la la", singers=singers[0]),
        line(3.0, 5.0, "li li", singers=singers[1]),
    ]
    song = SongText("Titel", "Künstler", 60.0, {})
    scene = layout(lines, song, chosen, (960, 720), FixedMeasurer())
    check_scene(scene, chosen)
    title = title_of(scene)
    assert title.end - title.start >= BUILD_MIN
    assert title.mark is not None and title.mark.build is not None  # the build-up plays
    assert not [s for s in scene.shortfalls if s.kind == "title"]
    if chosen.cdg is not None:  # and on CD+G the pixel letters
        shown = cdg_scene(lines, song, cdg_profile(chosen), FixedMeasurer())
        pixels = title_of(shown)
        assert pixels.end - pixels.start >= BUILD_MIN
        assert pixels.mark is not None and pixels.mark.pixel


# ------------------------------------------------------------------ rows, names and their sizes


def bare_canvas(width: float = 200.0, size: float = 13.0, height: float = 300.0) -> Canvas:
    """A canvas of ``width`` for the fixed measurer, whose characters are half a size wide."""
    chosen = wordmark_profile()
    return Canvas(FixedMeasurer(), chosen, Rect(x=0, y=0, w=width, h=height), size)


def names_of(*texts: str) -> list[CardText]:
    return [CardText(text, 1.0, "#ffffff", flows=True) for text in texts]


def joins(texts: list[CardText]) -> list[bool]:
    return [text.join for text in texts if text.flows]


def best_of(names: list[CardText], canvas: Canvas) -> list[CardText]:
    """The names as the start screen arranges them under a title, without a rule."""
    return _best([CardText("T", 1.0, TEXT_COLOUR), *names], canvas, 10.0, None, TEXT_EDGE).texts


@pytest.mark.parametrize(
    ("count", "rows", "expected"),
    [
        (4, 2, [False, True, False, True]),
        (5, 2, [False, True, True, False, True]),
        (5, 3, [False, True, False, True, False]),
        (6, 1, [False] + [True] * 5),
        (3, 3, [False] * 3),
    ],
)
def test_names_are_spread_evenly_over_the_rows_the_first_rows_taking_the_extra_ones(
    count: int, rows: int, expected: list[bool]
) -> None:
    assert joins(_flowed(names_of(*["N"] * count), rows)) == expected


def test_four_long_names_stand_two_and_two_not_three_and_one() -> None:
    assert joins(best_of(names_of(*["N" * 10] * 4), bare_canvas())) == [False, True, False, True]


def test_five_names_that_do_not_fit_one_row_are_spread_three_and_two() -> None:
    laid = best_of(names_of(*["N" * 6] * 5), bare_canvas())
    assert joins(laid) == [False, True, True, False, True]


def test_names_that_fit_stand_in_one_row() -> None:
    laid = best_of(names_of("Anna", "Ben", "Cleo", "Dora", "Emil", "Alle"), bare_canvas(400.0))
    assert joins(laid) == [False, True, True, True, True, True]


def test_one_name_to_a_row_only_when_that_gives_larger_text() -> None:
    wide = names_of(*["N" * 20] * 4)  # two in a row would have to shrink, one fits at full size
    assert joins(best_of(wide, bare_canvas())) == [False] * 4
    assert joins(best_of(names_of("N" * 20), bare_canvas())) == [False]


def test_the_rows_are_chosen_by_the_laid_out_size_so_the_height_counts_too() -> None:
    canvas = bare_canvas(height=50.0)  # one name to a row is narrow enough but too many rows
    names = names_of(*["N" * 20] * 4)
    lines = [CardText("T", 1.0, TEXT_COLOUR), *names]
    chosen = _best(lines, canvas, 10.0, None, TEXT_EDGE)
    assert joins(chosen.texts) == [False, True, False, True]
    tall = _lay(lines, canvas, 10.0, None, TEXT_EDGE, 4)
    assert chosen.smallest()[0] > tall.smallest()[0]


def test_the_largest_names_win_before_the_largest_title() -> None:
    lines = [CardText("T" * 80, 1.0, TEXT_COLOUR), *names_of(*["N" * 10] * 4)]
    canvas = bare_canvas()  # the title is shrunk to the width whatever the names do
    chosen = _best(lines, canvas, 10.0, None, TEXT_EDGE)
    one_row = _lay(lines, canvas, 10.0, None, TEXT_EDGE, 1)
    assert chosen.smallest()[1] == one_row.smallest()[1]  # the title: the smallest text in both
    assert chosen.smallest()[0] > one_row.smallest()[0]


def test_the_names_keep_their_order_and_colours() -> None:
    names = [
        CardText(text, 1.0, colour, flows=True)
        for text, colour in [("A", "#111111"), ("B", "#222222")]
    ]
    laid = [x for x in best_of(names, bare_canvas()) if x.flows]
    assert [(x.text, x.colour) for x in laid] == [("A", "#111111"), ("B", "#222222")]


def pixel_card(texts: list[CardText]) -> CardElement | None:
    """The pixel start screen of ``texts`` with no floor at base size 36 (scales are px / 36)."""
    chosen = cdg_profile(wordmark_profile())
    scene = cdg_scene(
        [line(9.0, 11.0, "la la")], SongText("T", None, 60.0, {}), chosen, FixedMeasurer()
    )
    canvas = Canvas(FixedMeasurer(), chosen, scene.safe, 36.0)
    return wordmark_card(texts, canvas, 10.0, 0, pixel=True)


def test_the_rows_of_a_wrapped_text_share_one_size_and_stand_closer_together() -> None:
    title = "Ein ziemlich langer Titel und ein noch viel längerer zweiter Teil davon"
    shown = pixel_card(
        [
            CardText(title.upper(), PIXEL_TITLE_PX / 36.0, TEXT_COLOUR, wraps=True),
            CardText("ARTIST", PIXEL_ARTIST_PX / 36.0, AMBER, wraps=True),
        ]
    )
    assert shown is not None
    first, second, artist = shown.lines
    assert first.size == second.size < PIXEL_TITLE_PX  # shrunk together
    assert second.box.y - first.box.y == pytest.approx(ROW_PITCH * first.size, abs=0.01)
    assert ROW_PITCH < LINE_PITCH
    assert artist.box.y - second.box.y > LINE_PITCH * first.size  # the rule stands between
    assert artist.size == PIXEL_ARTIST_PX


def test_the_rules_space_is_a_share_of_the_titles_size_not_the_artists() -> None:
    title = cdg_title()
    assert title.mark is not None and title.mark.rule is not None
    head, artist = title.lines
    gap = (head.box.y + head.box.h / 2, artist.box.y + artist.box.h / 2)
    spacer = RULE_SPACE * PIXEL_TITLE_PX * LINE_PITCH
    middles = LINE_PITCH * (PIXEL_TITLE_PX + PIXEL_ARTIST_PX) / 2
    assert gap[1] - gap[0] == pytest.approx(middles + spacer, abs=0.01)


def test_the_floor_does_not_apply_to_a_small_video() -> None:
    title = title_of(scene_of((320, 240), title=LONG_TITLE, artist=LONG_ARTIST))
    assert title.mark is not None and not title.mark.pixel
    assert min(x.size for x in title.lines) < PIXEL_FLOOR_PX


def test_the_cdg_fallback_is_the_card_of_the_form_plain_names_and_group_included() -> None:
    singers = {1: SingerInfo(name="Anna"), 2: SingerInfo(name="Ben")}
    song = SongText(LONG_TITLE, "Künstler", 60.0, singers, together_two="Beide")
    lines = [line(9.0, 11.0, "la la", singers="1"), line(12.0, 14.0, "li li", singers="all")]

    def title_with(form: str) -> CardElement:
        chosen = builtin_profile("two-line-turns", title={"form": form})
        return title_of(cdg_scene(lines, song, chosen, FixedMeasurer()))

    fallback, plain = title_with("wordmark"), title_with("plain")
    assert fallback.mark is None
    assert fallback.lines == plain.lines
    assert [x.text for x in plain.lines][2:] == ["Anna", "Ben", "Beide"]
    group = builtin_profile("two-line-turns").colours.group.sung
    assert plain.lines[-1].colour == group and plain.lines[-1].size == plain.lines[2].size


def test_the_video_names_are_a_share_of_the_title_size_side_by_side() -> None:
    title = title_of(scene_of(singers={1: SingerInfo(name="Anna"), 2: SingerInfo(name="Ben")}))
    head, _, anna, ben = title.lines
    assert anna.size == ben.size == pytest.approx(0.6 * head.size, abs=0.01)
    assert anna.box.y == ben.box.y
