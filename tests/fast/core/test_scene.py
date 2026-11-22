"""Stage 1: the scene model and the layout of public-domain songs, as golden files."""

import pytest
from pydantic import ValidationError
from syrupy.assertion import SnapshotAssertion

from conformance.scene_rules import check_scene
from fakes.scenes import duet_scene, entchen_scene, profile, turn_scene
from vocatron.core.layout.sample import DUET_TURNS
from vocatron.core.scene import (
    CardElement,
    CardLine,
    CountdownElement,
    Keyframe,
    LineElement,
    PreviewElement,
    ProgressElement,
    Rect,
    Scene,
    TimerElement,
)


def summary(scene: Scene) -> list[str]:
    """One row per element: kind, times, text, slot and box."""
    rows = []
    for element in scene.elements:
        text = ""
        if isinstance(element, LineElement):
            text = f"{element.text!r} slot {element.slot} singers {element.singers}"
            if element.turns:
                text += f" turns {[(t.span, t.singers) for t in element.turns]}"
        elif isinstance(element, CardElement):
            text = " / ".join(line.text for line in element.lines)
        elif isinstance(element, CountdownElement):
            text = f"{element.form} x{element.count}"
        elif isinstance(element, PreviewElement):
            text = f"{element.line.text!r} of line {element.of_line}"
        elif isinstance(element, ProgressElement):
            text = "progress"
        box = element.box
        rows.append(
            f"{element.kind:9} {element.start:7.3f} {element.end:7.3f} "
            f"{box.x:7.2f} {box.y:7.2f} {box.w:7.2f} {box.h:6.2f}  {text}"
        )
    return rows


def test_the_layout_of_a_folk_song_is_golden(snapshot: SnapshotAssertion) -> None:
    assert summary(entchen_scene()) == snapshot


def test_the_scene_of_a_folk_song_is_golden_as_json(snapshot: SnapshotAssertion) -> None:
    assert entchen_scene().model_dump_json(indent=1) == snapshot


def test_the_layout_of_a_duet_is_golden(snapshot: SnapshotAssertion) -> None:
    assert summary(duet_scene()) == snapshot


def test_the_layout_of_a_duet_with_turns_is_golden(snapshot: SnapshotAssertion) -> None:
    scene = turn_scene()
    assert summary(scene) == snapshot
    assert [(i, t.span, t.singers) for i, line in enumerate(scene.lines()) for t in line.turns] == [
        (3, 1, "1"),  # the long group line is split in two: "Welt hinein", turning at "hinein"
        (4, 2, "2"),
    ]


def test_the_folk_songs_keep_to_the_rules() -> None:
    check_scene(entchen_scene(), profile())
    check_scene(duet_scene(), profile())
    check_scene(turn_scene(), profile())


def test_the_turns_of_a_scene_survive_json() -> None:
    scene = turn_scene()
    assert Scene.model_validate_json(scene.model_dump_json()) == scene
    assert len(DUET_TURNS) == sum(bool(line.turns) for line in scene.lines())


def test_each_word_of_a_turn_line_is_in_the_colours_of_its_singers() -> None:
    scene = turn_scene()
    group_line, mixed = scene.lines()[3], scene.lines()[4]
    group = profile().colours.group
    assert group_line.colours.sung == group.sung  # "Welt" is sung together
    (turn,) = group_line.turns
    assert turn.colours.unsung == profile().colours.singer1.unsung  # "hinein": singer 1
    assert turn.colours.sung == "#22aa55"  # and the colour of the lyrics file counts for a turn
    (switch,) = mixed.turns
    assert (mixed.singers, switch.singers) == ("1", "2")
    assert switch.colours.sung == "#ff3399"  # a colour of the profile, not of the lyrics file
    assert mixed.colours.sung == "#22aa55"  # singer 1 has a colour in the lyrics file


def test_what_is_visible_at_a_time_is_asked_of_the_model() -> None:
    scene = entchen_scene()
    assert [e.kind for e in scene.visible_at(1.0)] == ["title"]
    first = scene.lines()[0]
    at_start = scene.visible_at(first.sing_start + 0.01)
    assert first in at_start
    assert any(isinstance(e, CountdownElement) for e in scene.visible_at(first.sing_start - 1.0))
    assert scene.visible_at(scene.duration + 1.0) == []


def test_the_screens_of_a_kind_are_asked_of_the_model() -> None:
    scene = entchen_scene()
    cards = [e for e in scene.elements if isinstance(e, CardElement)]
    for kind in ("title", "break", "end"):
        assert scene.cards(kind) == [card for card in cards if card.kind == kind]
    assert scene.cards("title") and scene.cards("break")


def test_the_wipe_front_moves_through_the_syllables() -> None:
    scene = entchen_scene()
    line = scene.lines()[0]
    first, second = line.spans[0], line.spans[1]
    assert line.wipe_front(first.start - 0.1, scene.look) == 0.0
    middle = line.wipe_front((first.start + first.end) / 2, scene.look)
    assert first.x0 < middle < first.x1
    assert line.wipe_front(second.start, scene.look) == first.x1 or second.start > first.end
    assert line.wipe_front(line.sing_end + 1.0, scene.look) == line.spans[-1].x1


def test_a_syllable_wipe_switches_at_the_start() -> None:
    scene = entchen_scene(wipe={"granularity": "syllable"})
    line = scene.lines()[0]
    span = line.spans[0]
    assert line.wipe_front(span.start + 0.001, scene.look) == span.x1


def test_the_wipe_offset_shifts_every_wipe() -> None:
    scene = entchen_scene(wipe={"offset": 0.2})
    line = scene.lines()[0]
    span = line.spans[0]
    assert line.wipe_front(span.start + 0.1, scene.look) == 0.0
    assert line.wipe_front(span.end + 0.25, scene.look) >= span.x1


def test_the_title_shows_the_singers_names_in_their_colours() -> None:
    scene = duet_scene()
    title = next(e for e in scene.elements if isinstance(e, CardElement) and e.kind == "title")
    names = {line.text: line.colour for line in title.lines}
    assert names["Anna"] == "#22aa55"  # the colour from the lyrics file
    assert names["Ben"] == "#ff3399"  # the profile's singer 2
    assert list(names)[0] == "Hänschen klein"


def test_a_colour_in_the_lyrics_file_overrides_the_profile() -> None:
    scene = duet_scene()
    colours = {line.singers: line.colours.sung for line in scene.lines()}
    assert colours["1"] == "#22aa55"
    assert colours["2"] == "#ff3399"
    assert colours["all"] == "#ffcc00"


def test_a_song_without_sung_lines_is_one_title_screen() -> None:
    from fakes.measure import FixedMeasurer  # noqa: PLC0415  # only this test needs it
    from vocatron.core.layout.build import SongText, layout  # noqa: PLC0415

    scene = layout([], SongText("Nichts", None, 30.0, {}), profile(), (960, 720), FixedMeasurer())
    assert [e.kind for e in scene.elements] == ["title"]
    assert scene.elements[0].end == 30.0


def test_rectangles_that_only_touch_do_not_overlap_and_a_sliver_does() -> None:
    box = Rect(x=10, y=10, w=10, h=10)
    for other in (Rect(x=20, y=10, w=5, h=5), Rect(x=0, y=10, w=10, h=5),
                  Rect(x=10, y=20, w=5, h=5), Rect(x=10, y=0, w=5, h=10)):  # fmt: skip
        assert not box.overlaps(other)
        assert not other.overlaps(box)
    for other in (Rect(x=19.9, y=10, w=5, h=5), Rect(x=0, y=10, w=10.1, h=5),
                  Rect(x=10, y=19.9, w=5, h=5), Rect(x=10, y=0, w=5, h=10.1)):  # fmt: skip
        assert box.overlaps(other)
        assert other.overlaps(box)


def test_a_rectangle_inside_may_touch_the_edges_and_a_thousandth_more() -> None:
    outer = Rect(x=10, y=10, w=100, h=50)
    assert outer.inside(outer)
    assert Rect(x=9.999, y=9.999, w=100.002, h=50.002).inside(outer)
    for leaving in (Rect(x=9.99, y=10, w=10, h=10), Rect(x=10, y=9.99, w=10, h=10),
                    Rect(x=100.01, y=10, w=10, h=10), Rect(x=10, y=50.01, w=10, h=10)):  # fmt: skip
        assert not leaving.inside(outer)


def test_the_wipe_front_is_linear_inside_a_syllable_and_exact_at_its_edges() -> None:
    scene = entchen_scene()
    line = scene.lines()[0]
    span = line.spans[1]
    middle = (span.start + span.end) / 2
    assert line.wipe_front(span.start, scene.look) == pytest.approx(span.x0)
    assert line.wipe_front(middle, scene.look) == pytest.approx((span.x0 + span.x1) / 2)
    assert line.wipe_front(span.end, scene.look) == pytest.approx(span.x1)
    instant = line.spans[0].model_copy(update={"end": line.spans[0].start})
    flat = line.model_copy(update={"spans": [instant]})
    assert flat.wipe_front(instant.start, scene.look) == pytest.approx(instant.x1)


def test_an_element_is_visible_from_its_start_until_just_before_its_end() -> None:
    line = entchen_scene().lines()[0]
    assert line.visible(line.start)
    assert not line.visible(line.end)


def test_a_preview_and_a_progress_bar_round_trip_through_json() -> None:
    box = Rect(x=10, y=20, w=300, h=40)
    preview = PreviewElement(
        start=1.0,
        end=3.0,
        box=box,
        of_line=2,
        line=CardLine(
            text="la la", size=30.0, edge=2.0, shadow=1.0, colour="#ffffff",
            edge_colour="#000000", box=box, text_x=12.0, text_y=22.0,
        ),
    )  # fmt: skip
    bar = ProgressElement(start=0.0, end=9.0, box=box, fill="#ffcc00", frame="#ffffff")
    scene = entchen_scene()
    drawn = scene.model_copy(
        update={"elements": [*scene.elements, preview, bar], "preview_row": box}
    )
    again = Scene.model_validate_json(drawn.model_dump_json())
    assert again == drawn
    assert [e.kind for e in again.elements[-2:]] == ["preview", "progress"]
    assert again.preview_row == box
    assert all(line.page is None for line in again.lines())


def timer_of(start: float, end: float) -> TimerElement:
    box = Rect(x=100.0, y=300.0, w=40.0, h=30.0)
    return TimerElement(
        start=start, end=end, box=box, colour="#ff6666", edge_colour="#222244",
        size=26.0, edge=2.0, shadow=1.0, text_y=302.0,
    )  # fmt: skip


def test_a_timer_round_trips_through_json() -> None:
    scene = entchen_scene(breaks={"form": "timer"})
    (timer,) = (e for e in scene.elements if isinstance(e, TimerElement))
    assert timer.kind == "timer"
    again = Scene.model_validate_json(scene.model_dump_json())
    assert again == scene
    assert any(isinstance(e, TimerElement) for e in again.elements)


def test_a_timer_shows_the_whole_seconds_until_it_goes_rounded_up() -> None:
    timer = timer_of(10.0, 17.3)
    assert timer.total == 8
    assert [timer.seconds_left(t) for t in (10.0, 10.2, 10.299, 10.3, 16.5, 17.299)] == [
        8, 8, 8, 7, 1, 1,
    ]  # fmt: skip
    assert timer.seconds_left(9.0) == 8 and timer.seconds_left(18.0) == 1  # held at both ends


def test_a_timer_of_whole_seconds_is_not_one_number_too_long() -> None:
    timer = timer_of(10.0, 20.0)
    assert timer.total == 10 and timer.seconds_left(10.0) == 10
    assert timer.seconds_left(10.5) == 10 and timer.seconds_left(11.0) == 9


def test_a_timer_changes_once_a_second_after_the_start() -> None:
    timer = timer_of(10.0, 13.3)
    assert timer.changes() == [10.3, 11.3, 12.3]
    assert [timer.seconds_left(t) for t in (10.299, 10.3, 11.3, 12.3, 13.299)] == [4, 3, 2, 1, 1]
    assert timer_of(10.0, 10.4).changes() == []  # a break of under a second counts one number


def test_a_line_on_a_path_is_where_the_path_has_it_at_every_time() -> None:
    scene = entchen_scene()
    line = scene.lines()[0]
    path = [
        Keyframe(time=1.0, y=140.0),
        Keyframe(time=3.0, y=100.0),
        Keyframe(time=4.0, y=100.0),
        Keyframe(time=5.0, y=60.0),
        Keyframe(time=5.0, y=40.0),  # a jump
        Keyframe(time=9.0, y=0.0),
    ]
    moving = line.model_copy(update={"path": path, "text_y": 40.0})
    assert moving.y_at(0.0) == 140.0  # before the first keyframe: where it starts
    assert moving.y_at(1.0) == 140.0 and moving.y_at(2.0) == 120.0  # gliding
    assert moving.y_at(3.5) == 100.0  # standing still
    assert moving.y_at(4.5) == 80.0  # half way down to 60
    assert moving.y_at(5.0) == 40.0  # at a jump: the place after it
    assert moving.y_at(7.0) == 20.0
    assert moving.y_at(9.0) == 0.0 and moving.y_at(50.0) == 0.0  # after the last: where it ends
    assert moving.box_at(4.5).y == moving.box.y + (80.0 - 40.0)
    assert moving.box_at(4.5).h == moving.box.h
    assert line.y_at(3.0) == line.text_y and line.box_at(3.0) == line.box  # no path: stays


def notice_of(**update: object) -> CardElement:
    """A break card: it stands still, in every mode (ADR-0040)."""
    box = Rect(x=100.0, y=300.0, w=200.0, h=40.0)
    line = CardLine(
        text="Pause", size=26.0, edge=2.0, shadow=1.0, colour="#ffffff", edge_colour="#000000",
        box=box, text_x=102.0, text_y=302.0,
    )  # fmt: skip
    card = CardElement(start=1.0, end=7.0, box=box, kind="break", lines=[line])
    return card.model_copy(update=update)


def test_a_break_card_a_bar_and_a_timer_have_no_path() -> None:
    bar = {"start": 2.0, "end": 4.0, "box": Rect(x=10, y=20, w=100, h=8)}
    path = [Keyframe(time=1.0, y=400.0), Keyframe(time=2.0, y=300.0)]
    for element in (notice_of(), timer_of(2.0, 9.0)):
        assert not hasattr(element, "path")
        with pytest.raises(ValidationError):
            type(element).model_validate({**element.model_dump(), "path": path})
    with pytest.raises(ValidationError):
        ProgressElement.model_validate({**bar, "fill": "#ffcc00", "frame": "#fff", "path": path})


def test_a_break_card_round_trips_through_json() -> None:
    scene = entchen_scene()
    drawn = scene.model_copy(update={"elements": [*scene.elements, notice_of()]})
    assert Scene.model_validate_json(drawn.model_dump_json()) == drawn
