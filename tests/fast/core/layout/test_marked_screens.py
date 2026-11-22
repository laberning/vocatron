"""Stage 1: the end and break screens with the mark, on the scene (ADR-0057)."""

import pytest
from pydantic import JsonValue

from conformance.scene_rules import check_scene
from fakes.measure import FixedMeasurer
from fakes.phrases import line
from fakes.rule_breaks import hits, line_far_away, messages, mutate, word_outside
from fakes.scenes import builtin_profile, entchen_with
from vocatron.core.cdg.canvas import cdg_scene
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.cards import LINE_PITCH
from vocatron.core.layout.mark import SYMBOL_GAP, SYMBOL_ROWS
from vocatron.core.lyrics.document import SingerInfo
from vocatron.core.profiles.model import BUILTIN_PROFILES, Profile
from vocatron.core.scene import CardElement, ProgressElement, Scene, TimerElement
from vocatron.core.wordmark import AMBER, FIELD_COLOUR, LETTER_HEIGHT, TEXT_COLOUR, symbol

WORDMARK: JsonValue = {"form": "wordmark"}
FRAMES = {"4:3": (960, 720), "16:9": (1280, 720)}
LONG_TITLE = "Der Mond ist aufgegangen, die goldnen Sternlein prangen am Himmel hell und klar"
NOTICE_SCALE = 0.9


def look(name: str = "two-line-turns", **overrides: JsonValue) -> Profile:
    return builtin_profile(name, **{"title": WORDMARK, **overrides})


def scene_of(
    chosen: Profile,
    frame: tuple[int, int] = (960, 720),
    *,
    title: str = "Titel",
    artist: str | None = "Künstler",
    singers: dict[int, SingerInfo] | None = None,
) -> Scene:
    """A song with a break of thirty seconds and an end screen."""
    song = SongText(title, artist, 80.0, singers or {})
    lines = [line(8.0, 10.0, "la la"), line(40.0, 42.0, "li li")]
    return layout(lines, song, chosen, frame, FixedMeasurer())


def cards(scene: Scene, kind: str) -> list[CardElement]:
    return [e for e in scene.elements if isinstance(e, CardElement) and e.kind == kind]


def end_of(scene: Scene) -> CardElement:
    (found,) = cards(scene, "end")
    return found


def title_of(scene: Scene) -> CardElement:
    (found,) = cards(scene, "title")
    return found


def break_of(scene: Scene) -> CardElement:
    (found,) = cards(scene, "break")
    return found


def notice_cell_top(card: CardElement) -> float:
    """The top of the row cell of the notice, the first line of the card."""
    first = card.lines[0]
    return first.box.y + first.box.h / 2 - first.size * LINE_PITCH / 2


# ------------------------------------------------------------------ the end screen


@pytest.mark.parametrize("frame", FRAMES.values(), ids=FRAMES.keys())
def test_the_end_screen_is_the_wordmark_screen_of_the_start_without_the_build_up(
    frame: tuple[int, int],
) -> None:
    chosen = look()
    scene = scene_of(chosen, frame)
    check_scene(scene, chosen)
    end, title = end_of(scene), title_of(scene)
    assert end.mark is not None and title.mark is not None
    assert end.mark.build is None and not end.mark.pixel
    assert title.mark.build is not None
    assert end.mark == title.mark.model_copy(update={"build": None})
    assert [(x.text, x.colour) for x in end.lines] == [(x.text, x.colour) for x in title.lines]
    assert end.box == title.box and end.box.inside(scene.safe)
    assert all(x.box.inside(end.mark.frame) for x in end.lines)
    assert [x.text for x in end.lines][:2] == ["TITEL", "KÜNSTLER"]
    assert end.lines[0].colour == TEXT_COLOUR and end.lines[1].colour == AMBER
    assert end.mark.field == FIELD_COLOUR


def test_the_end_screen_starts_ends_and_fades_out_as_before() -> None:
    chosen = look()
    plain = builtin_profile("two-line-turns")
    marked, before = end_of(scene_of(chosen)), end_of(scene_of(plain))
    assert (marked.start, marked.end, marked.fade_out) == (
        before.start,
        before.end,
        before.fade_out,
    )
    assert marked.fade_out == chosen.ending.fade > 0


def test_the_end_screen_names_the_singers_as_the_start_does() -> None:
    singers = {1: SingerInfo(name="Anna", colour="#112233"), 2: SingerInfo(name="Ben")}
    scene = scene_of(look(), singers=singers)
    texts = [x.text for x in end_of(scene).lines]
    assert texts == [x.text for x in title_of(scene).lines]
    assert "Anna" in texts and "Ben" in texts


def test_without_an_artist_the_end_screen_has_no_rule() -> None:
    end = end_of(scene_of(look(), artist=None))
    assert end.mark is not None and end.mark.rule is None
    assert [x.text for x in end.lines] == ["TITEL"]


def test_a_long_title_wraps_on_the_end_screen_inside_the_frame() -> None:
    chosen = look()
    scene = scene_of(chosen, title=LONG_TITLE)
    check_scene(scene, chosen)
    end = end_of(scene)
    assert end.mark is not None
    assert len(end.lines) > 2
    assert all(x.box.inside(end.mark.frame) for x in end.lines)


def test_without_title_fields_the_end_screen_is_the_card_of_title_and_artist() -> None:
    chosen = look(title={"form": "wordmark", "fields": []})
    scene = scene_of(chosen)
    check_scene(scene, chosen)
    end = end_of(scene)
    assert end.mark is None
    assert [x.text for x in end.lines] == ["TITEL", "KÜNSTLER"]


def test_plain_gives_the_end_screen_of_before() -> None:
    chosen = builtin_profile("two-line-turns", title={"form": "plain"})
    end = end_of(scene_of(chosen))
    assert end.mark is None and end.symbol is None
    assert [x.text for x in end.lines] == ["Titel", "Künstler"]
    assert all(x.colour == chosen.colours.group.unsung for x in end.lines)


# ------------------------------------------------------------------ the break screen


@pytest.mark.parametrize("frame", FRAMES.values(), ids=FRAMES.keys())
def test_the_break_screen_has_the_symbol_above_the_notice_inside_the_safe_area(
    frame: tuple[int, int],
) -> None:
    chosen = look()
    scene = scene_of(chosen, frame)
    check_scene(scene, chosen)
    card = break_of(scene)
    assert card.symbol is not None and card.mark is None
    symbol_box = card.symbol
    assert symbol_box.inside(scene.safe) and symbol_box.inside(card.box)
    assert card.box.inside(scene.safe)
    assert all(symbol_box.bottom <= x.box.y for x in card.lines)
    assert [x.text for x in card.lines] == [chosen.breaks.notice]
    assert card.lines[0].colour == chosen.colours.group.unsung  # the notice keeps its colours


def test_the_symbol_is_one_and_a_half_rows_high_half_a_row_above_the_notice_and_centred() -> None:
    scene = scene_of(look())
    card = break_of(scene)
    assert card.symbol is not None
    row = card.lines[0].size * LINE_PITCH
    assert card.symbol.h == pytest.approx(SYMBOL_ROWS * row, abs=0.05)
    assert notice_cell_top(card) - card.symbol.bottom == pytest.approx(SYMBOL_GAP * row, abs=0.05)
    assert card.symbol.x + card.symbol.w / 2 == pytest.approx(
        scene.safe.x + scene.safe.w / 2, abs=0.05
    )
    assert card.symbol.w == pytest.approx(symbol().width / LETTER_HEIGHT * card.symbol.h, abs=0.05)
    assert card.lines[0].size == pytest.approx(NOTICE_SCALE * scene.safe.h * look().font.size)


def test_the_block_of_symbol_and_notice_is_centred_in_the_safe_area() -> None:
    scene = scene_of(look())
    card = break_of(scene)
    assert card.symbol is not None
    row = card.lines[0].size * LINE_PITCH
    top = card.symbol.y
    bottom = notice_cell_top(card) + row
    assert (top + bottom) / 2 == pytest.approx(scene.safe.y + scene.safe.h / 2, abs=0.05)


def test_plain_gives_the_break_screen_of_before() -> None:
    chosen = builtin_profile("two-line-turns", title={"form": "plain"})
    card = break_of(scene_of(chosen))
    assert card.symbol is None
    before = break_of(scene_of(look()))
    assert before.box.h > card.box.h  # the symbol makes the card's box grow
    assert card.box.inside(before.box)


@pytest.mark.parametrize("form", ["notice", "progress", "timer"])
def test_progress_bar_and_timer_stay_below_the_text(form: str) -> None:
    chosen = look(breaks={"form": form})
    scene = scene_of(chosen)
    check_scene(scene, chosen)
    card = break_of(scene)
    assert card.symbol is not None
    parts = [e for e in scene.elements if isinstance(e, (ProgressElement, TimerElement))]
    assert len(parts) == (form != "notice")
    for part in parts:
        assert part.box.y >= card.box.bottom - 0.01
        assert not part.box.overlaps(card.symbol)
        assert part.box.inside(scene.safe)


def test_the_break_screen_with_titles_keeps_them_under_the_notice() -> None:
    chosen = look(breaks={"show_title": True})
    scene = scene_of(chosen)
    check_scene(scene, chosen)
    card = break_of(scene)
    assert card.symbol is not None
    assert [x.text for x in card.lines][1:] == ["TITEL", "KÜNSTLER"]


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
@pytest.mark.parametrize("frame", FRAMES.values(), ids=FRAMES.keys())
def test_in_every_built_in_look_nothing_new_overlaps_and_everything_is_inside_the_safe_area(
    name: str, frame: tuple[int, int]
) -> None:
    chosen = look(name)
    scene = scene_of(chosen, frame)
    check_scene(scene, chosen)
    for card in (*cards(scene, "break"), *cards(scene, "end")):
        assert card.box.inside(scene.safe)
    for card in cards(scene, "break"):
        assert card.symbol is not None
        assert card.symbol.inside(scene.safe)
        if scene.scroll is None:  # nothing of the lyric lines or a countdown is there with it
            others = [
                e
                for e in scene.elements
                if e is not card and e.start < card.end and e.end > card.start
            ]
            assert not [e for e in others if e.box.overlaps(card.box)]


def test_in_scroll_mode_the_symbol_stands_still_in_the_middle_of_the_break_screen() -> None:
    chosen = look("lyric-scroll")
    scene = scene_of(chosen)
    check_scene(scene, chosen)
    card = break_of(scene)
    assert card.symbol is not None
    assert card.symbol.inside(card.box)
    middle = (card.symbol.y + notice_cell_top(card) + card.lines[0].size * LINE_PITCH) / 2
    assert middle == pytest.approx(scene.safe.y + scene.safe.h / 2, abs=0.05)  # centred as always


def test_the_symbol_never_makes_the_break_leave_the_safe_area_of_a_small_picture() -> None:
    chosen = look("lyric-scroll", breaks={"form": "timer"})
    scene = scene_of(chosen, (640, 480))
    check_scene(scene, chosen)
    assert break_of(scene).box.inside(scene.safe)


# ------------------------------------------------------------------ CD+G


def test_cdg_has_neither_symbol_nor_mark_on_its_break_and_end_screens() -> None:
    chosen = look()
    song = SongText("Titel", "Künstler", 80.0, {})
    lines = [line(8.0, 10.0, "la"), line(40.0, 42.0, "li")]
    scene = cdg_scene(lines, song, chosen, FixedMeasurer())
    plain = cdg_scene(lines, song, builtin_profile("two-line-turns"), FixedMeasurer())
    for kind in ("break", "end"):
        (card,) = cards(scene, kind)
        (before,) = cards(plain, kind)
        assert card.symbol is None and card.mark is None
        assert card.box == before.box
        assert [x.text for x in card.lines] == [x.text for x in before.lines]


# ------------------------------------------------------------------ the rules


def test_rule_15_a_mark_on_a_plain_end_screen() -> None:
    chosen = builtin_profile("two-line-turns", title={"form": "plain"})
    marked = end_of(scene_of(look())).mark
    scene = mutate(
        scene_of(chosen), "end", 0, lambda card: card.model_copy(update={"mark": marked})
    )
    assert messages(scene, chosen, 15) == ["rule 15: a mark on a plain end screen"]


def test_rule_15_an_end_screen_that_builds_up() -> None:
    chosen = look()
    scene = scene_of(chosen)
    assert hits(scene, chosen) == set()
    built = title_of(scene).mark
    swapped = mutate(scene, "end", 0, lambda card: card.model_copy(update={"mark": built}))
    assert messages(swapped, chosen, 15) == ["rule 15: the end screen's mark builds up"]


def test_rule_15_a_line_that_leaves_the_frame_of_the_end_screen() -> None:
    chosen = look()

    scene = mutate(scene_of(chosen), "end", 0, line_far_away)
    assert "rule 15: a line leaves the frame of the end screen" in messages(scene, chosen, 15)


def test_rule_15_the_wordmark_that_overlaps_the_frame_of_the_end_screen() -> None:
    chosen = look()

    def low(card: CardElement) -> CardElement:
        assert card.mark is not None
        word = card.mark.word.model_copy(update={"y": card.mark.frame.y})
        return card.model_copy(update={"mark": card.mark.model_copy(update={"word": word})})

    scene = mutate(scene_of(chosen), "end", 0, low)
    assert messages(scene, chosen, 15) == ["rule 15: the wordmark and the frame overlap"]


def test_rule_12_a_symbol_on_a_plain_break_screen() -> None:
    chosen = builtin_profile("two-line-turns", title={"form": "plain"})
    box = break_of(scene_of(look())).symbol
    scene = mutate(
        scene_of(chosen), "break", 0, lambda card: card.model_copy(update={"symbol": box})
    )
    assert "rule 12: a symbol on a plain break screen" in messages(scene, chosen, 12)


def test_rule_12_a_symbol_that_is_not_above_the_text() -> None:
    chosen = look()

    def low(card: CardElement) -> CardElement:
        assert card.symbol is not None
        return card.model_copy(
            update={"symbol": card.symbol.model_copy(update={"y": card.box.y + 50})}
        )

    scene = mutate(scene_of(chosen), "break", 0, low)
    found = messages(scene, chosen, 12)
    assert "rule 12: the symbol is not above the text" in found


def test_rule_12_a_symbol_outside_the_card() -> None:
    chosen = look()

    def out(card: CardElement) -> CardElement:
        assert card.symbol is not None
        moved = card.symbol.model_copy(update={"x": card.box.x - 100})
        return card.model_copy(update={"symbol": moved})

    scene = mutate(scene_of(chosen), "break", 0, out)
    assert "rule 12: the symbol leaves the card" in messages(scene, chosen, 12)


def test_rule_1_a_symbol_outside_the_safe_area() -> None:
    chosen = look()

    def wide(card: CardElement) -> CardElement:
        assert card.symbol is not None
        return card.model_copy(update={"symbol": card.symbol.model_copy(update={"x": -5.0})})

    assert "1" in hits(mutate(scene_of(chosen), "break", 0, wide), chosen)


def test_rule_1_the_wordmark_of_the_end_screen_outside_the_safe_area() -> None:
    chosen = look()

    assert "1" in hits(mutate(scene_of(chosen), "end", 0, word_outside), chosen)


def test_the_look_of_a_song_without_a_break_has_no_break_screen_and_the_end_screen_still() -> None:
    chosen = look()
    scene = entchen_with(chosen)
    assert end_of(scene).mark is not None


def test_rule_12_a_symbol_that_just_touches_the_text_is_still_above_it() -> None:
    chosen = look()

    def touching(card: CardElement) -> CardElement:
        assert card.symbol is not None
        y = card.lines[0].box.y - card.symbol.h
        return card.model_copy(update={"symbol": card.symbol.model_copy(update={"y": y})})

    scene = mutate(scene_of(chosen), "break", 0, touching)
    assert "rule 12: the symbol is not above the text" not in messages(scene, chosen, 12)
