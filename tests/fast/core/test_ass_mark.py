"""Stage 1: the start screen with the wordmark as ASS events, read back (ADR-0055)."""

import re

import pytest
from syrupy.assertion import SnapshotAssertion

from fakes.measure import FixedMeasurer
from fakes.scenes import builtin_profile
from vocatron.core.ass.parse import Event, parse_ass
from vocatron.core.ass.write import write_ass
from vocatron.core.colour import ass_colour
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.mark import FILL_STEPS, WIPE_IN
from vocatron.core.scene import CardElement, Scene
from vocatron.core.wordmark import AMBER, BAND_COLOURS, EDGE_COLOUR, FIELD_COLOUR


def scene_of(seconds: float) -> Scene:
    """A song without lines: its start screen stands for the whole ``seconds``."""
    look = builtin_profile("two-line-turns", title={"form": "wordmark"})
    song = SongText("Titel", "Künstler", seconds, {})
    return layout([], song, look, (960, 720), FixedMeasurer())


def drawings(events: tuple[Event, ...], colour: str) -> list[Event]:
    return [e for e in events if e.drawing and f"\\1c{ass_colour(colour)}" in e.tags]


def test_the_events_of_a_start_screen_with_a_build_up_are_golden(
    snapshot: SnapshotAssertion,
) -> None:
    assert write_ass(scene_of(6.0)) == snapshot


def test_the_events_of_a_start_screen_without_a_build_up_are_golden(
    snapshot: SnapshotAssertion,
) -> None:
    assert write_ass(scene_of(3.0)) == snapshot


def test_the_field_covers_the_whole_picture_for_the_life_of_the_screen() -> None:
    scene = scene_of(6.0)
    script = parse_ass(write_ass(scene))
    (field,) = drawings(script.events, FIELD_COLOUR)
    assert (field.start, field.end) == (0, 600)
    assert field.position == (0, 0)
    assert field.layer == 0
    assert f"{scene.width} 0 {scene.width} {scene.height}" in write_ass(scene)


def test_each_band_is_filled_in_three_steps_with_a_clip_that_opens_to_the_right() -> None:
    text = write_ass(scene_of(6.0))
    script = parse_ass(text)
    for colour in (c for c in BAND_COLOURS if c != AMBER):  # the amber band is the rule's colour
        found = drawings(script.events, colour)
        assert [e.start for e in found] == [round(start * 100) for start, _ in FILL_STEPS]
        assert all(e.end == 600 for e in found)
        assert all("\\clip(" in e.tags and "\\t(0," in e.tags for e in found)


def test_the_clip_of_a_step_starts_empty_and_ends_at_the_right_edge_of_its_letters() -> None:
    script = parse_ass(write_ass(scene_of(6.0)))
    band = drawings(script.events, BAND_COLOURS[0])[0]
    first, last = re.findall(r"\\clip\(([-\d.]+),([-\d.]+),([-\d.]+),([-\d.]+)\)", band.tags)
    assert first[0] == first[2]  # no width before the sweep
    assert float(last[2]) > float(last[0])
    assert first[1] == last[1]
    assert first[3] == last[3]


def test_the_frame_the_rule_and_the_texts_wipe_in_together() -> None:
    scene = scene_of(6.0)
    script = parse_ass(write_ass(scene))
    start = round(WIPE_IN[0] * 100)
    (title,) = [e for e in scene.elements if isinstance(e, CardElement)]
    assert title.mark is not None
    assert title.mark.rule is not None
    (rule,) = [
        e
        for e in drawings(script.events, AMBER)
        if e.position == pytest.approx((title.mark.rule.x, title.mark.rule.y), abs=0.01)
    ]
    assert rule.start == start
    texts = [e for e in script.events if not e.drawing and e.text]
    assert [e.text for e in texts] == ["TITEL", "KÜNSTLER"]
    assert all(e.start == start and "\\clip(" in e.tags for e in texts)
    assert all(e.layer > rule.layer - 1 for e in texts)


def test_the_edge_fades_in() -> None:
    script = parse_ass(write_ass(scene_of(6.0)))
    edges = drawings(script.events, EDGE_COLOUR)
    assert edges
    assert any(e.fade_in_ms == 400 for e in edges)


def test_without_a_build_up_everything_stands_from_the_first_frame_and_nothing_moves() -> None:
    script = parse_ass(write_ass(scene_of(3.0)))
    assert {e.start for e in script.events} == {0}
    assert not any("\\t(" in e.tags for e in script.events)
    assert all(e.fade_in_ms == 0 for e in script.events)


def test_a_card_without_a_mark_writes_no_mark_events() -> None:
    look = builtin_profile("two-line-turns", title={"form": "plain"})
    scene = layout([], SongText("Titel", "Künstler", 6.0, {}), look, (960, 720), FixedMeasurer())
    script = parse_ass(write_ass(scene))
    assert not any(e.drawing for e in script.events)
    (card,) = [e for e in scene.elements if isinstance(e, CardElement)]
    assert card.mark is None
