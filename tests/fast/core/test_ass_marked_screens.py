"""Stage 1: the end and break screens with the mark as ASS events, read back (ADR-0057)."""

import pytest
from pydantic import JsonValue
from syrupy.assertion import SnapshotAssertion

from fakes.measure import FixedMeasurer
from fakes.phrases import line
from fakes.scenes import builtin_profile
from vocatron.core.ass.parse import Event, parse_ass
from vocatron.core.ass.tags import fade, move
from vocatron.core.ass.timing import cs_of
from vocatron.core.ass.write import write_ass
from vocatron.core.colour import ass_colour
from vocatron.core.layout.build import SongText, layout
from vocatron.core.scene import CardElement, Scene
from vocatron.core.wordmark import (
    AMBER,
    BAND_COLOURS,
    EDGE_COLOUR,
    EDGE_LIGHT,
    FIELD_COLOUR,
    FRAME_FILL,
)

WORDMARK: JsonValue = {"form": "wordmark"}


def scene_of(name: str = "two-line-turns", **overrides: JsonValue) -> Scene:
    look = builtin_profile(name, **{"title": WORDMARK, **overrides})
    song = SongText("Titel", "Künstler", 80.0, {})
    lines = [line(8.0, 10.0, "la la"), line(40.0, 42.0, "li li")]
    return layout(lines, song, look, (960, 720), FixedMeasurer())


def card(scene: Scene, kind: str) -> CardElement:
    (found,) = [e for e in scene.elements if isinstance(e, CardElement) and e.kind == kind]
    return found


def events_of(scene: Scene, kind: str) -> list[Event]:
    """The events of the end or break card: those that start inside its life."""
    shown = card(scene, kind)
    first, last = cs_of(shown.start), cs_of(shown.end)
    found = [e for e in parse_ass(write_ass(scene)).events if first <= e.start < last]
    assert found
    return found


def coloured(events: list[Event], colour: str) -> list[Event]:
    return [e for e in events if e.drawing and f"\\1c{ass_colour(colour)}" in e.tags]


def source(scene: Scene, kind: str) -> list[str]:
    """The Dialogue lines of a card, as the writer wrote them."""
    shown = card(scene, kind)
    first, last = cs_of(shown.start), cs_of(shown.end)
    rows = [r for r in write_ass(scene).splitlines() if r.startswith("Dialogue:")]
    return [r for r in rows if first <= parse_ass_start(r) < last]


def parse_ass_start(row: str) -> int:
    h, m, s = row.split(",")[1].split(":")
    return round((int(h) * 3600 + int(m) * 60 + float(s)) * 100)


# ------------------------------------------------------------------ the end screen


def test_the_events_of_the_end_screen_are_golden(snapshot: SnapshotAssertion) -> None:
    assert "\n".join(source(scene_of(), "end")) == snapshot


def test_the_end_screen_stands_complete_from_its_first_frame_without_a_build_up() -> None:
    scene = scene_of()
    shown = card(scene, "end")
    events = events_of(scene, "end")
    assert {e.start for e in events} == {cs_of(shown.start)}
    assert {e.end for e in events} == {cs_of(shown.end)}
    assert not any("\\t(" in e.tags for e in events)
    assert all(e.fade_in_ms == 0 for e in events)


def test_the_field_the_letters_the_frame_the_rule_and_the_texts_all_fade_out() -> None:
    scene = scene_of()
    shown = card(scene, "end")
    fade = round(shown.fade_out * 1000)
    events = events_of(scene, "end")
    assert fade > 0
    assert all(e.fade_out_ms == fade for e in events)
    assert len(coloured(events, FIELD_COLOUR)) == 1
    assert len(coloured(events, FRAME_FILL)) == 1
    assert coloured(events, AMBER)  # the rule, and the amber band
    assert coloured(events, EDGE_COLOUR) and coloured(events, EDGE_LIGHT)
    assert {e.text for e in events if not e.drawing} == {"TITEL", "KÜNSTLER"}


def test_the_end_screen_has_the_seven_bands_in_its_letters() -> None:
    events = events_of(scene_of(), "end")
    for colour in BAND_COLOURS:
        assert coloured(events, colour), colour
    assert all("\\clip(" in e.tags for c in BAND_COLOURS if c != AMBER for e in coloured(events, c))


def test_the_end_screen_of_a_look_without_a_fade_has_no_fad() -> None:
    scene = scene_of(ending={"fade": 0.0})
    assert card(scene, "end").fade_out == 0.0
    assert not any("\\fad" in r for r in source(scene, "end"))


def test_plain_writes_no_drawing_for_the_end_screen_or_the_break_screen() -> None:
    scene = scene_of(title={"form": "plain"})
    assert not any(e.drawing for e in events_of(scene, "end"))
    assert not any(e.drawing for e in events_of(scene, "break"))


# ------------------------------------------------------------------ the break screen


def test_the_events_of_the_break_screen_are_golden(snapshot: SnapshotAssertion) -> None:
    assert "\n".join(source(scene_of(), "break")) == snapshot


def test_the_events_of_the_break_screen_in_a_scroll_look_are_golden(
    snapshot: SnapshotAssertion,
) -> None:
    assert "\n".join(source(scene_of("lyric-scroll"), "break")) == snapshot


def test_the_symbol_is_a_finished_letter_without_a_field_or_a_build_up() -> None:
    scene = scene_of()
    events = events_of(scene, "break")
    drawings = [e for e in events if e.drawing]
    assert len(drawings) == 3 + len(BAND_COLOURS)
    assert [len(coloured(drawings, c)) for c in (EDGE_COLOUR, EDGE_LIGHT)] == [2, 1]
    for colour in (FIELD_COLOUR, FRAME_FILL):
        assert not coloured(drawings, colour), colour
    glow, edge = coloured(drawings, EDGE_COLOUR)
    assert "\\blur" in glow.tags and "\\blur" not in edge.tags
    rings = [glow, edge, coloured(drawings, EDGE_LIGHT)[0]]
    assert all("\\1a&HFF&" in e.tags for e in rings)  # a ring: the fill is clear
    for colour in BAND_COLOURS:
        (band,) = coloured(drawings, colour)
        assert "\\bord0" in band.tags and "\\clip(" in band.tags and "\\t(" not in band.tags
        assert "\\1a&HFF&" not in band.tags
        assert glow.layer < edge.layer < band.layer < rings[2].layer
    assert [e.text for e in events if not e.drawing] == ["Instrumental"]


def test_the_symbol_stands_where_the_scene_says_and_for_the_life_of_the_card() -> None:
    scene = scene_of()
    shown = card(scene, "break")
    assert shown.symbol is not None
    drawings = [e for e in events_of(scene, "break") if e.drawing]
    assert {(e.start, e.end) for e in drawings} == {(cs_of(shown.start), cs_of(shown.end))}
    for event in drawings:
        assert event.position is not None
        x, y = event.position
        assert shown.symbol.x - 1 <= x <= shown.symbol.right
        assert shown.symbol.y - 1 <= y <= shown.symbol.bottom
        assert not event.move


def test_in_a_scroll_look_the_symbol_stands_still_for_the_life_of_the_card() -> None:
    scene = scene_of("lyric-scroll")
    shown = card(scene, "break")
    events = events_of(scene, "break")
    symbol = (EDGE_COLOUR, EDGE_LIGHT, *BAND_COLOURS)
    drawings = [e for c in dict.fromkeys(symbol) for e in coloured(events, c)]
    assert len(drawings) == 3 + len(BAND_COLOURS)
    assert {(e.start, e.end) for e in drawings} == {(cs_of(shown.start), cs_of(shown.end))}
    assert not any(e.move for e in drawings)  # nothing of the break screen moves (ADR-0040)
    assert not any("\\t(" in e.tags for e in drawings)  # and nothing dims it


@pytest.mark.parametrize("form", ["notice", "progress", "timer"])
def test_every_form_of_the_break_screen_has_the_symbol_once(form: str) -> None:
    events = events_of(scene_of(breaks={"form": form}), "break")
    assert len(coloured(events, EDGE_COLOUR)) == 2
    assert len(coloured(events, EDGE_LIGHT)) == 1
    assert all(len(coloured(events, colour)) == 1 for colour in BAND_COLOURS)


@pytest.mark.parametrize("name", ["two-line-turns", "lyric-scroll", "full-page"])
def test_the_styles_of_the_symbol_are_written(name: str) -> None:
    text = write_ass(scene_of(name))
    script = parse_ass(text)
    for event in script.events:
        assert event.style in script.styles


# ------------------------------------------------------------------ the shared tags


def test_fade_writes_milliseconds_and_nothing_without_a_fade() -> None:
    assert fade(2.0, 3.0) == "\\fad(2000,3000)"
    assert fade(0.0, 1.5) == "\\fad(0,1500)"
    assert fade(0.0, 0.0) == ""


def test_move_writes_a_vertical_glide_in_milliseconds() -> None:
    assert move(10.5, 20.0, 30.25, 2.0) == "\\move(10.5,20,10.5,30.25,0,2000)"


def test_a_still_break_screen_that_fades_out_fades_its_symbol_with_its_text() -> None:
    scene = scene_of()
    shown = card(scene, "break")
    faded = shown.model_copy(update={"fade_out": 0.5})
    scene = scene.model_copy(
        update={"elements": [faded if e is shown else e for e in scene.elements]}
    )
    events = events_of(scene, "break")
    assert len([e for e in events if e.drawing]) == 3 + len(BAND_COLOURS)
    assert {e.fade_out_ms for e in events} == {500}
