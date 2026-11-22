"""Stage 1: a line in scroll mode in the ASS file: one event per stretch of its path (ADR-0033).

The events are read back and compared with the path of the scene: when each starts and ends,
where it stands or moves, and that the wipe lies in one still event and is not cut.
"""

import re

import pytest
from pydantic import JsonValue

from fakes.measure import FixedMeasurer
from fakes.phrases import line
from fakes.scenes import builtin_profile, entchen_with
from vocatron.core.ass.parse import Event, Script, parse_ass
from vocatron.core.ass.timing import cs_of
from vocatron.core.ass.write import (
    DIM_RAMP,
    GLOW_MIN_OPACITY,
    _alphas,
    _dim,
    _dim_sung,
    _opacity,
    write_ass,
)
from vocatron.core.colour import ass_alpha
from vocatron.core.layout.build import SongText, layout
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    CardElement,
    LineElement,
    ProgressElement,
    Scene,
    TimerElement,
)

FRAME = (960, 720)
NO_INTRO: JsonValue = {"solo": 0.0, "group": 0.0}


def scroll_profile(**overrides: JsonValue) -> Profile:
    return builtin_profile("lyric-scroll", intro=NO_INTRO, **overrides)


def events_for(scene: Scene, row: LineElement) -> list[Event]:
    """The lyric events of one row: its text, in the order of the file."""
    script = parse_ass(write_ass(scene))
    return [e for e in script.events if e.text == row.text and not e.drawing and e.layer == 0]


def scene_of(chosen: Profile, *rows: tuple[float, float]) -> Scene:
    phrases = [line(a, b, f"{WORDS[i]} la") for i, (a, b) in enumerate(rows)]
    return layout(phrases, SongText("T", "A", 60.0, {}, bpm=None), chosen, FRAME, FixedMeasurer())


def parsed(scene: Scene) -> Script:
    return parse_ass(write_ass(scene))


WORDS = ["eins", "zwei", "drei", "vier", "fünf", "sechs"]
SONG = [(10.0, 12.0), (15.0, 17.0), (20.0, 22.0), (25.0, 27.0), (30.0, 32.0)]


def test_a_line_is_one_event_per_still_part_and_glide_of_its_path() -> None:
    scene = scene_of(scroll_profile(), *SONG)
    row = scene.lines()[1]
    events = events_for(scene, row)
    stretches = [
        (a, b)
        for a, b in zip(row.path, row.path[1:], strict=False)
        if cs_of(b.time) > cs_of(a.time)
    ]
    assert len(events) == len(stretches)
    for event, (a, b) in zip(events, stretches, strict=True):
        assert (event.start, event.end) == (cs_of(a.time), cs_of(b.time))
        moves = a.y != b.y
        assert (event.move is not None) is moves
        assert (event.position is not None) is not moves


def test_a_glide_is_a_move_over_its_time_and_a_still_part_a_position() -> None:
    scene = scene_of(scroll_profile(), *SONG)
    row = scene.lines()[1]
    for event, (a, b) in zip(
        events_for(scene, row), zip(row.path, row.path[1:], strict=False), strict=False
    ):
        if event.move:
            x1, y1, x2, y2, t1, t2 = event.move
            assert (x1, x2) == (row.text_x, row.text_x)
            assert abs(y1 - a.y) < 0.01 and abs(y2 - b.y) < 0.01
            assert (t1, t2) == (0, round((b.time - a.time) * 1000))
        else:
            assert event.position is not None
            assert abs(event.position[1] - a.y) < 0.01


def test_the_line_fades_in_while_it_glides_in_and_out_while_it_glides_out() -> None:
    scene = scene_of(scroll_profile(), *SONG)
    row = scene.lines()[0]  # in view from the start to the glide that takes it out
    events = events_for(scene, row)
    first, last = events[0], events[-1]
    assert first.fade_in_ms == round((first.end - first.start) * 10)
    assert last.fade_out_ms == round((last.end - last.start) * 10)
    assert all(e.fade_in_ms == 0 and e.fade_out_ms == 0 for e in events[1:-1])


def test_the_wipe_is_in_one_still_event_and_not_cut() -> None:
    scene = scene_of(scroll_profile(), *SONG)
    for row in scene.lines():
        events = events_for(scene, row)
        singing = [e for e in events if e.start <= cs_of(row.sing_start) < e.end]
        (event,) = singing
        assert event.move is None
        span = sum(s.centis for s in event.sweeps)
        assert abs(event.start + span - cs_of(row.sing_end)) <= len(row.spans)  # rounding only


def test_the_wipe_continues_across_a_glide_that_starts_while_the_line_is_sung() -> None:
    chosen = scroll_profile(scroll={"dim_sung": 0.6})
    scene = scene_of(chosen, (10.0, 11.5), (11.5, 13.0), (13.0, 14.5))  # no silence between
    row = scene.lines()[1]
    events = events_for(scene, row)
    out = [e for e in events if e.move is not None and e.start < cs_of(row.sing_end) <= e.end]
    (leaving,) = out  # the glide out starts during the end of the singing and ends with it
    assert leaving.start >= cs_of(row.sing_end - 0.3) - 1
    span = sum(s.centis for s in leaving.sweeps)
    assert abs(leaving.start + span - cs_of(row.sing_end)) <= len(row.spans)  # rounding only
    before = next(e for e in events if e.end == leaving.start)
    assert before.move is None and before.start < leaving.start
    assert r"\t(" not in leaving.tags  # dimmed only after the last syllable
    after = [e for e in events if e.start >= leaving.end]
    assert after and all(e.sweeps == () for e in after)


def test_the_parts_before_the_singing_have_not_swept_and_those_after_are_plain_and_sung() -> None:
    scene = scene_of(scroll_profile(), *SONG)
    row = scene.lines()[2]
    for event in events_for(scene, row):
        if event.end <= cs_of(row.sing_start):
            ahead = event.sweeps[0].centis if event.sweeps[0].text == "" else 0
            assert event.start + ahead >= event.end - 1  # the sweep has not started yet
        elif event.start >= cs_of(row.sing_end):
            assert event.sweeps == ()  # plain text: the primary colour is the sung colour


def test_a_jump_makes_no_event() -> None:
    scene = scene_of(scroll_profile(), (10.0, 11.5), (11.5, 13.0), (13.0, 14.5))
    for row in scene.lines():
        events = events_for(scene, row)
        assert all(e.end > e.start for e in events)
        assert events[0].start == cs_of(row.start)


def test_a_line_is_dimmed_before_its_singing_and_after_it() -> None:
    chosen = scroll_profile(upcoming={"dim": 0.5}, scroll={"dim_sung": 0.6})
    scene = scene_of(chosen, *SONG)
    row = scene.lines()[2]
    events = events_for(scene, row)
    before, after = events[0], events[-1]
    assert rf"\1a{ass_alpha(0.5)}" in before.tags  # dimmed by 0.5 while it waits below
    assert rf"\1a{ass_alpha(0.4)}" in after.tags  # dimmed by 0.6 once it has been sung
    (sung,) = [e for e in events if e.start <= cs_of(row.sing_start) < e.end]
    assert r"\t(" in sung.tags


def ramp_start(event: Event, row: LineElement) -> int:
    """Milliseconds into ``event`` at which the dim after the singing starts."""
    return round((row.sing_end - event.start / 100) * 1000)


def test_the_sung_dim_ramps_after_the_last_syllable_in_the_event_that_has_it() -> None:
    chosen = scroll_profile(scroll={"dim_sung": 0.6})
    scene = scene_of(chosen, *SONG)
    row = scene.lines()[2]
    (sung,) = [e for e in events_for(scene, row) if e.start <= cs_of(row.sing_start) < e.end]
    ramps = [(int(a), int(b)) for a, b in re.findall(r"\\t\((\d+),(\d+),", sung.tags)]
    wanted = (ramp_start(sung, row), ramp_start(sung, row) + round(DIM_RAMP * 1000))
    assert any(abs(a - wanted[0]) <= 10 and abs(b - wanted[1]) <= 10 for a, b in ramps), ramps


def test_the_sung_dim_waits_for_a_wipe_that_is_shifted_later() -> None:
    chosen = scroll_profile(scroll={"dim_sung": 0.6}, wipe={"offset": 0.3})
    scene = scene_of(chosen, *SONG)
    row = scene.lines()[2]
    done = row.sing_end + 0.3
    (event,) = [e for e in events_for(scene, row) if e.start <= cs_of(done) < e.end]
    ramps = [(int(a), int(b)) for a, b in re.findall(r"\\t\((\d+),(\d+),", event.tags)]
    start = round((done - event.start / 100) * 1000)
    wanted = (start, start + round(DIM_RAMP * 1000))
    assert any(abs(a - wanted[0]) <= 10 and abs(b - wanted[1]) <= 10 for a, b in ramps), ramps


def test_without_a_dim_the_line_keeps_its_opacity() -> None:
    scene = scene_of(scroll_profile(upcoming={"dim": 0.0}), *SONG)
    assert scene.look.sung_dim == 0.0
    assert all(r"\1a" not in e.tags for e in parsed(scene).events if e.text)


def test_a_line_in_line_mode_has_no_move_and_one_event() -> None:
    scene = entchen_with(builtin_profile("two-line-turns"))
    script = parsed(scene)
    assert all(e.move is None for e in script.events)


def test_the_glow_follows_the_glide_under_the_line() -> None:
    chosen = scroll_profile(glow={"sung": 0.6})
    scene = scene_of(chosen, *SONG)
    row = scene.lines()[1]
    script = parsed(scene)
    glow = [e for e in script.events if e.layer == 0 and e.move and e.text == row.text]
    text = [e for e in script.events if e.layer == 1 and e.move and e.text == row.text]
    assert glow and len(glow) == len(text)
    assert [e.move for e in glow] == [e.move for e in text]


def test_the_glow_sinks_with_a_sung_line_so_the_line_keeps_its_look() -> None:
    chosen = scroll_profile(glow={"sung": 0.6}, scroll={"dim_sung": 0.6})
    scene = scene_of(chosen, *SONG)
    row = scene.lines()[1]
    script = parsed(scene)
    glow = [e for e in script.events if e.layer == 0 and e.text == row.text]
    text = [e for e in script.events if e.layer == 1 and e.text == row.text]
    after = [(g, t) for g, t in zip(glow, text, strict=True) if t.end > cs_of(row.sing_end)]
    assert after
    full = ass_alpha(GLOW_MIN_OPACITY + (1 - GLOW_MIN_OPACITY) * 0.6)
    dimmed = ass_alpha((GLOW_MIN_OPACITY + (1 - GLOW_MIN_OPACITY) * 0.6) * 0.4)
    assert full != dimmed
    for g, t in after:
        ramps = re.findall(r"\\t\((\d+),(\d+),", g.tags)
        assert len(ramps) <= 1
        assert set(ramps) <= set(re.findall(r"\\t\((\d+),(\d+),", t.tags))  # the same sinking
        assert f"\\1a{dimmed}" in g.tags, g.tags
    before = [g for g in glow if g.end <= cs_of(row.sing_end)]
    assert before
    assert all(f"\\1a{full}" in g.tags and "\\t(" not in g.tags for g in before)


def test_the_parser_reads_a_move() -> None:
    rows = "\n".join(
        [
            "[Script Info]",
            "PlayResX: 960",
            "PlayResY: 720",
            "[V4+ Styles]",
            "[Events]",
            r"Dialogue: 0,0:00:01.00,0:00:02.00,a,,0,0,0,,{\an7\move(10,20.5,10,5,0,400)}x",
        ]
    )
    (event,) = parse_ass(rows).events
    assert event.move == (10.0, 20.5, 10.0, 5.0, 0, 400)
    assert event.position is None


# ------------------------------------------------------------ the break screen (ADR-0040)

BREAK_SONG = [(10.0, 12.0), (15.0, 17.0), (50.0, 52.0), (55.0, 57.0), (60.0, 62.0)]


def notice_scene(**overrides: JsonValue) -> tuple[Scene, CardElement]:
    scene = scene_of(scroll_profile(**overrides), *BREAK_SONG)
    (notice,) = [e for e in scene.elements if isinstance(e, CardElement) and e.kind == "break"]
    return scene, notice


def notice_events(scene: Scene, notice: CardElement) -> list[Event]:
    """The events of the notice text, in file order."""
    text = notice.lines[0].text
    return [e for e in parsed(scene).events if e.text == text and not e.drawing]


def test_the_break_screen_is_one_still_event_per_line_over_its_whole_life() -> None:
    scene, notice = notice_scene()
    events = notice_events(scene, notice)
    assert [(e.start, e.end) for e in events] == [(cs_of(notice.start), cs_of(notice.end))]
    (event,) = events
    assert event.move is None and event.position is not None
    assert (event.position[0], event.position[1]) == (
        notice.lines[0].text_x,
        notice.lines[0].text_y,
    )
    assert event.fade_in_ms == 0 == event.fade_out_ms
    assert r"\1a" not in event.tags and r"\t(" not in event.tags  # nothing dims it


def test_the_progress_bar_is_one_still_fill_and_one_still_frame() -> None:
    scene, _ = notice_scene(breaks={"form": "progress"})
    (bar,) = [e for e in scene.elements if isinstance(e, ProgressElement)]
    drawings = [e for e in parsed(scene).events if e.drawing and r"\fscx" in e.tags + r"\fscx"]
    fills = [e for e in drawings if re.search(r"\\fscx[\d.]+\\t\(", e.tags)]
    frames = [e for e in drawings if r"\1a&HFF&" in e.tags]
    assert [(e.start, e.end) for e in (*fills, *frames)] == [(cs_of(bar.start), cs_of(bar.end))] * 2
    edge = bar.box.h * 0.2
    (fill,) = fills
    found = re.search(r"\\fscx([\d.]+)\\t\(0,(\d+),\\fscx([\d.]+)\)", fill.tags)
    assert found is not None and float(found[3]) == 100
    assert int(found[2]) == round((bar.end - bar.start) * 1000)
    for event in (fill, *frames):
        assert event.move is None and event.position is not None
        assert event.position == pytest.approx((bar.box.x + edge, bar.box.y + edge), abs=0.01)
        assert event.fade_in_ms == 0 == event.fade_out_ms


def test_the_timer_counts_at_the_seconds_and_stands_still() -> None:
    scene, _ = notice_scene(breaks={"form": "timer"})
    (timer,) = [e for e in scene.elements if isinstance(e, TimerElement)]
    events = [e for e in parsed(scene).events if e.text.isdigit()]
    assert (events[0].start, events[-1].end) == (cs_of(timer.start), cs_of(timer.end))
    assert sorted({int(e.text) for e in events}, reverse=True) == list(range(timer.total, 0, -1))
    changes = [e.start for e, before in zip(events[1:], events, strict=False)
               if e.text != before.text]  # fmt: skip
    assert changes == [cs_of(t) for t in timer.changes()]
    centre = timer.box.x + timer.box.w / 2
    for event, after in zip(events, [*events[1:], None], strict=True):
        assert int(event.text) == timer.seconds_left(event.start / 100)
        assert event.move is None and event.position is not None
        assert event.position == pytest.approx((centre, timer.text_y), abs=0.01)
        assert after is None or event.end == after.start
        assert r"\1a" not in event.tags and event.fade_in_ms == 0 == event.fade_out_ms


def test_a_timer_has_no_event_for_a_stretch_too_short_to_be_seen() -> None:
    scene, _ = notice_scene(breaks={"form": "timer"})
    (timer,) = [e for e in scene.elements if isinstance(e, TimerElement)]
    near = timer.model_copy(update={"end": timer.start + 2.004})  # a number for 4 ms
    cut = scene.model_copy(update={"elements": [near if e is timer else e for e in scene.elements]})
    events = [e for e in parsed(cut).events if e.text.isdigit()]
    assert all(e.end > e.start for e in events)
    assert events[-1].end == cs_of(near.end)


def test_the_lines_before_a_break_go_in_a_last_plain_event_that_fades_out() -> None:
    scene, notice = notice_scene(ending={"fade": 0.5})
    first = scene.lines()[0]
    assert first.exit == 0.5 and first.end == notice.start
    events = events_for(scene, first)
    last = events[-1]
    assert (last.start, last.end) == (cs_of(first.end - 0.5), cs_of(first.end))
    assert last.fade_out_ms == 500 and last.fade_in_ms == 0
    assert r"\k" not in last.text and r"\kf" not in last.tags  # plain text in the sung colours
    before = events[-2]
    assert before.end == last.start and before.fade_out_ms == 0


def test_a_line_whose_exit_does_not_fit_its_last_still_stretch_is_not_cut() -> None:
    scene, _ = notice_scene(ending={"fade": 0.5})
    first = scene.lines()[0]

    def events_with(changed: LineElement) -> list[Event]:
        swapped = [changed if e is first else e for e in scene.elements]
        return events_for(scene.model_copy(update={"elements": swapped}), changed)

    still = first.path[-1].time - first.path[-2].time
    longer = first.model_copy(update={"exit": still + 0.1})  # the fade would reach back further
    events = events_with(longer)
    assert all(e.start < e.end for e in events)
    assert all(a.end == b.start for a, b in zip(events, events[1:], strict=False))
    assert events[-1].fade_out_ms == 0 and events[-1].end == cs_of(first.end)
    gliding = first.model_copy(
        update={"path": first.path[:2], "end": first.path[1].time, "exit": 0.2}
    )  # a path that ends in a glide has no still stretch to fade in
    (glide,) = events_with(gliding)
    assert glide.move is not None and glide.end == cs_of(gliding.end)


def test_the_lines_before_a_break_without_a_fade_go_at_once() -> None:
    scene, _ = notice_scene(ending={"fade": 0.0})
    events = events_for(scene, scene.lines()[0])
    assert all(e.fade_out_ms == 0 for e in events[:-1]) and events[-1].end == cs_of(
        scene.lines()[0].end
    )


def test_the_notice_is_drawn_in_a_style_the_script_defines() -> None:
    scene, notice = notice_scene()
    text = write_ass(scene)
    for event in notice_events(scene, notice):
        assert f"Style: {event.style}," in text


def test_an_event_that_starts_while_something_sinks_starts_at_the_opacity_reached() -> None:
    look = notice_scene()[0].look
    dimmed = 1 - look.sung_dim
    assert look.sung_dim > 0
    assert _dim_sung(look, 10.0, (9.0, 10.0), _alphas) == ""  # over before it sinks
    assert _dim_sung(look, 10.0, (9.0, 11.0), _alphas) == (
        rf"\t(1000,{round((1.0 + DIM_RAMP) * 1000)},{_alphas(look, dimmed)})"
    )
    late = 10.0 + DIM_RAMP / 4
    assert _dim_sung(look, 10.0, (late, 11.0), _alphas) == (
        _alphas(look, 1 - look.sung_dim / 4)
        + rf"\t(0,{round((10.0 + DIM_RAMP - late) * 1000)},{_alphas(look, dimmed)})"
    )
    assert _dim_sung(look, 0.0, (DIM_RAMP, 1.0), _alphas) == _alphas(look, dimmed)  # just sunk
    assert _dim_sung(look, 10.0, (12.0, 13.0), _alphas) == _alphas(look, dimmed)


def test_an_event_before_its_place_rises_to_full_over_the_ramp() -> None:
    look = notice_scene()[0].look
    low = 1 - look.upcoming_dim
    assert look.upcoming_dim > 0
    assert _dim(look, 10.0, (8.0, 10.0 - DIM_RAMP)) == _alphas(look, low)  # ends as the ramp starts
    assert _dim(look, 10.0, (9.0, 11.0)) == (
        _alphas(look, low) + rf"\t({round((1 - DIM_RAMP) * 1000)},1000,{_alphas(look, 1.0)})"
    )
    half = 10.0 - DIM_RAMP / 2
    assert _dim(look, 10.0, (half, 11.0)) == (
        _alphas(look, low + (1 - low) / 2)
        + rf"\t(0,{round(DIM_RAMP / 2 * 1000)},{_alphas(look, 1.0)})"
    )
    assert _dim(look, 10.0, (10.0, 11.0)) == ""
    assert _opacity(look, 10.0, 9.0) == low
    assert _opacity(look, 10.0, 12.0) == 1.0  # full, never more


def test_only_a_glide_or_the_last_fade_fades_a_row() -> None:
    scene, _ = notice_scene(ending={"fade": 0.5})
    texts = {"".join(sp.text for sp in x.spans).strip() for x in scene.lines()}
    still = [e for e in parsed(scene).events if e.move is None and not e.drawing and e.text]
    assert any(e.text in texts for e in still)
    ends = {cs_of(x.end) for x in scene.lines()}
    assert all(
        e.fade_in_ms == 0 == e.fade_out_ms or e.end in ends for e in still if e.text in texts
    )
