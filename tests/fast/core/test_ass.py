"""Stage 1: the ASS writer is checked by parsing its output back (ADR-0009)."""

import pytest
from syrupy.assertion import SnapshotAssertion

from fakes.scenes import builtin_profile, duet_scene, entchen_scene, entchen_with, turn_scene
from vocatron.core.ass.parse import Event, Script, parse_ass
from vocatron.core.ass.timing import ass_time, cs_of, parse_time
from vocatron.core.ass.write import karaoke_text, write_ass
from vocatron.core.colour import ass_colour
from vocatron.core.scene import (
    CardElement,
    CountdownElement,
    LineElement,
    PreviewElement,
    ProgressElement,
    Scene,
    TimerElement,
)

HALF_CENTI = 0.005 + 1e-9


def lines_and_events(scene: Scene) -> tuple[Script, list[LineElement], list[Event]]:
    script = parse_ass(write_ass(scene))
    events = [e for e in script.events if e.sweeps and not e.drawing and e.size is not None]
    return script, scene.lines(), [e for e in events if e.sweeps]


def test_the_header_has_the_frame_size_and_one_style_per_colour_set() -> None:
    scene = entchen_scene()
    script = parse_ass(write_ass(scene))
    assert (script.width, script.height) == (960, 720)
    assert set(script.styles.values()) == {"Noto Sans"}
    assert len(script.styles) >= 2


def test_every_lyric_event_starts_and_ends_with_its_line() -> None:
    scene = entchen_scene()
    _, lines, events = lines_and_events(scene)
    assert len(events) == len(lines)
    for line, event in zip(lines, events, strict=True):
        assert abs(event.start / 100 - line.start) <= HALF_CENTI
        assert abs(event.end / 100 - line.end) <= HALF_CENTI
        assert event.text == line.text
        assert event.position == pytest.approx((line.text_x, line.text_y), abs=0.01)
        assert event.size == line.size


def test_the_wipe_durations_add_up_to_the_end_of_the_last_syllable() -> None:
    scene = entchen_scene()
    _, lines, events = lines_and_events(scene)
    for line, event in zip(lines, events, strict=True):
        assert abs(event.sweep_end / 100 - line.sing_end) <= HALF_CENTI


def test_every_syllable_is_swept_from_its_own_start() -> None:
    scene = duet_scene()
    _, lines, events = lines_and_events(scene)
    for line, event in zip(lines, events, strict=True):
        cursor = event.start
        syllables = iter(line.spans)
        for sweep in event.sweeps:
            if sweep.text:
                span = next(syllables)
                assert sweep.text == span.text
                assert abs(cursor / 100 - span.start) <= HALF_CENTI
                assert abs((cursor + sweep.centis) / 100 - span.end) <= HALF_CENTI
            cursor += sweep.centis
        assert next(syllables, None) is None


def test_a_smooth_wipe_uses_kf_and_a_syllable_wipe_uses_k() -> None:
    smooth = karaoke_text(entchen_scene().lines()[0], "smooth", 0.0)
    syllable = karaoke_text(entchen_scene().lines()[0], "syllable", 0.0)
    assert "\\kf" in smooth
    assert "\\kf" not in syllable
    assert "\\k" in syllable


def test_the_wipe_offset_moves_the_sweep_not_the_event() -> None:
    plain = entchen_scene()
    shifted = entchen_scene(wipe={"offset": 0.2})
    line = plain.lines()[0]
    event = next(e for e in parse_ass(write_ass(shifted)).events if e.sweeps and e.size)
    assert abs(event.sweep_end / 100 - (line.sing_end + 0.2)) <= HALF_CENTI
    assert abs(event.start / 100 - line.start) <= HALF_CENTI


def test_cards_are_events_without_a_sweep_and_the_end_screen_fades_out() -> None:
    scene = entchen_scene()
    cards = [e for e in scene.elements if isinstance(e, CardElement)]
    script = parse_ass(write_ass(scene))
    plain = [e for e in script.events if not e.sweeps and not e.drawing]
    assert len(plain) == sum(len(card.lines) for card in cards)
    title, end = cards[0], cards[-1]
    assert (title.kind, end.kind) == ("title", "end")
    titles = [e for e in plain if abs(e.start / 100 - title.start) <= HALF_CENTI]
    ends = [e for e in plain if abs(e.start / 100 - end.start) <= HALF_CENTI]
    assert {e.fade_out_ms for e in titles} == {0}
    assert {e.fade_out_ms for e in ends} == {500}
    assert all(abs(e.end / 100 - end.end) <= HALF_CENTI for e in ends)


def test_a_countdown_bar_is_one_drawing_that_shrinks_until_the_line_starts() -> None:
    scene = entchen_scene()
    countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
    text = write_ass(scene)
    drawings = [e for e in parse_ass(text).events if e.drawing]
    first = drawings[0]
    assert abs(first.start / 100 - countdown.start) <= HALF_CENTI
    assert abs(first.end / 100 - countdown.end) <= HALF_CENTI
    assert f"\\t(0,{round((countdown.end - countdown.start) * 1000)},\\fscx1)" in text


def test_countdown_dots_go_out_one_by_one_ending_with_the_line_start() -> None:
    scene = entchen_scene(countdown={"form": "dots", "count": 4})
    countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
    dots = [e for e in parse_ass(write_ass(scene)).events if e.drawing][:4]
    ends = sorted(e.end / 100 for e in dots)
    assert len(dots) == 4
    assert ends[-1] == pytest.approx(countdown.end, abs=0.01)
    step = (countdown.end - countdown.start) / 4  # four dots, one goes out per step
    assert ends[0] == pytest.approx(countdown.start + step, abs=0.01)


def test_braces_and_backslashes_in_the_text_cannot_become_tags() -> None:
    line = entchen_scene().lines()[0]
    spans = [line.spans[0].model_copy(update={"text": "{\\b1}x\\N"}), *line.spans[1:]]
    nasty = line.model_copy(update={"spans": spans})
    text = karaoke_text(nasty, "smooth", 0.0)
    assert "{\\b1}" not in text
    assert "\\N" not in text


def test_times_are_written_as_centiseconds() -> None:
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(cs_of(3661.239)) == "1:01:01.24"
    assert ass_time(-5) == "0:00:00.00"


def test_times_are_read_back_as_centiseconds() -> None:
    assert parse_time("1:02:03.45") == ((1 * 60 + 2) * 60 + 3) * 100 + 45
    assert parse_time(ass_time(cs_of(3661.239))) == cs_of(3661.239)


def test_the_ass_file_of_a_folk_song_is_golden(snapshot: SnapshotAssertion) -> None:
    assert write_ass(entchen_scene()) == snapshot


def test_the_ass_file_of_a_duet_is_golden(snapshot: SnapshotAssertion) -> None:
    assert write_ass(duet_scene()) == snapshot


def test_a_file_without_a_frame_size_is_refused() -> None:
    with pytest.raises(ValueError, match="PlayResX"):
        parse_ass("[Script Info]\n")


def test_the_lines_of_the_scene_are_all_events() -> None:
    scene = entchen_scene()
    count = sum(isinstance(e, LineElement) for e in scene.elements)
    assert sum(1 for e in parse_ass(write_ass(scene)).events if e.sweeps and e.size) == count


def test_a_syllable_wipe_switches_every_syllable_with_k() -> None:
    line = entchen_scene().lines()[0]
    sweeps = parse_ass(f"PlayResX: 1\nPlayResY: 1\nDialogue: 0,0:00:00.00,0:00:09.00,s,,0,0,0,,"
                       f"{karaoke_text(line, 'syllable', 0.0)}").events[0].sweeps  # fmt: skip
    assert {sweep.tag for sweep in sweeps} == {"k"}
    assert [sweep.text for sweep in sweeps if sweep.text] == [span.text for span in line.spans]


def test_the_wipe_offset_moves_every_syllable() -> None:
    plain, shifted = entchen_scene(), entchen_scene(wipe={"offset": 0.2})
    line = plain.lines()[0]
    event = next(e for e in parse_ass(write_ass(shifted)).events if e.sweeps and e.size)
    cursor, starts = event.start, list[float]()
    for sweep in event.sweeps:
        if sweep.text:
            starts.append(cursor / 100)
        cursor += sweep.centis
    assert starts == pytest.approx([span.start + 0.2 for span in line.spans], abs=HALF_CENTI)


def test_the_dots_are_circles_side_by_side_over_the_countdown_box() -> None:
    scene = entchen_scene(countdown={"form": "dots", "count": 4})
    countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
    dots = [e for e in parse_ass(write_ass(scene)).events if e.drawing][:4]
    pitch = countdown.box.w / 4
    xs = [dot.position[0] for dot in dots if dot.position is not None]
    assert xs == pytest.approx([countdown.box.x + i * pitch for i in range(4)], abs=0.01)
    h = countdown.box.h
    r, k = h / 2, h / 2 * 0.5522847498
    circle = (
        f"m 0 {r:.2f} b 0 {r - k:.2f} {r - k:.2f} 0 {r:.2f} 0 {r + k:.2f} 0 {h:.2f} {r - k:.2f} "
        f"{h:.2f} {r:.2f} {h:.2f} {r + k:.2f} {r + k:.2f} {h:.2f} {r:.2f} {h:.2f} {r - k:.2f} "
        f"{h:.2f} 0 {r + k:.2f} 0 {r:.2f}"
    )
    normal = " ".join(p.rstrip("0").rstrip(".") if "." in p else p for p in circle.split())
    assert normal in write_ass(scene)


def test_the_bar_is_a_rectangle_of_the_countdown_box() -> None:
    scene = entchen_scene()
    box = next(e for e in scene.elements if isinstance(e, CountdownElement)).box
    w, h = (f"{v:.2f}".rstrip("0").rstrip(".") for v in (box.w, box.h))
    assert f"m 0 0 l {w} 0 {w} {h} 0 {h}" in write_ass(scene)


def test_tag_characters_and_line_breaks_in_the_text_become_harmless_characters() -> None:
    line = entchen_scene().lines()[0]
    spans = [line.spans[0].model_copy(update={"text": "{a}\\b\nc\rd"})]
    text = karaoke_text(line.model_copy(update={"spans": spans}), "smooth", 0.0)
    assert text.endswith("}(a)/b cd")


def test_a_fade_is_written_in_milliseconds() -> None:
    scene = entchen_scene(ending={"fade": 1.25})
    assert "\\fad(0,1250)" in write_ass(scene)


def test_hours_are_counted_in_full() -> None:
    assert ass_time(359999) == "0:59:59.99"
    assert ass_time(360000) == "1:00:00.00"


def test_a_preview_is_a_plain_text_event_in_the_unsung_colour() -> None:
    scene = entchen_with(builtin_profile("one-line-preview"))
    preview = next(e for e in scene.elements if isinstance(e, PreviewElement))
    script = parse_ass(write_ass(scene))
    event = next(e for e in script.events if e.text == preview.line.text and not e.sweeps)
    assert event.size == pytest.approx(preview.line.size, abs=0.01)
    assert event.text == preview.line.text
    assert (event.start / 100, event.end / 100) == pytest.approx(
        (preview.start, preview.end), abs=HALF_CENTI
    )
    assert event.position == pytest.approx((preview.line.text_x, preview.line.text_y), abs=0.01)
    assert event.style.startswith(preview.line.colour[1:].lower())  # the unsung colour
    assert event.fade_out_ms == 0


def test_the_progress_bar_is_a_frame_and_a_fill_that_grows_until_the_line_appears() -> None:
    scene = entchen_with(builtin_profile("blue-page"))
    bar = next(e for e in scene.elements if isinstance(e, ProgressElement))
    text = write_ass(scene)
    mine = [
        e for e in parse_ass(text).events if e.drawing and abs(e.start / 100 - bar.start) < 0.006
    ]
    drawings = [e for e in mine if e.position is not None and e.position[1] > bar.box.y - 1]
    assert len(drawings) == 2  # the fill and the frame
    assert all(abs(e.end / 100 - bar.end) <= HALF_CENTI for e in drawings)
    millis = round((bar.end - bar.start) * 1000)
    assert f"\\fscx1\\t(0,{millis},\\fscx100)" in text  # from empty to full over the screen
    assert "\\1a&HFF&" in text  # the frame has no fill
    left, top = drawings[0].position or (0, 0)
    assert left >= bar.box.x and top >= bar.box.y  # inside the box, the outline ends at its edge


def test_blocks_are_squares_that_go_out_one_by_one() -> None:
    scene = entchen_with(builtin_profile("blue-page"))
    countdown = next(e for e in scene.elements if isinstance(e, CountdownElement))
    blocks = [
        e
        for e in parse_ass(write_ass(scene)).events
        if e.drawing and abs(e.start / 100 - countdown.start) <= HALF_CENTI and e.position
    ][:4]
    assert len(blocks) == 4
    ends = sorted(e.end / 100 for e in blocks)
    step = (countdown.end - countdown.start) / 4
    assert ends == pytest.approx([countdown.start + step * n for n in (1, 2, 3, 4)], abs=0.01)
    side = f"{countdown.box.h:.2f}".rstrip("0").rstrip(".")
    assert f"m 0 0 l {side} 0 {side} {side} 0 {side}" in write_ass(scene)  # a square, no curve


@pytest.mark.parametrize(
    "look", ["two-line-turns", "four-line-stack", "blue-page", "one-line-preview"]
)
def test_every_event_uses_a_style_of_the_file(look: str) -> None:
    script = parse_ass(write_ass(entchen_with(builtin_profile(look))))
    assert {event.style for event in script.events} <= set(script.styles)


def test_the_progress_fill_and_frame_are_the_box_less_its_frame() -> None:
    scene = entchen_with(builtin_profile("blue-page"))
    bar = next(e for e in scene.elements if isinstance(e, ProgressElement))
    edge = bar.box.h * 0.2
    width = f"{bar.box.w - 2 * edge:.2f}".rstrip("0").rstrip(".")
    height = f"{bar.box.h - 2 * edge:.2f}".rstrip("0").rstrip(".")
    rectangle = f"m 0 0 l {width} 0 {width} {height} 0 {height}"
    text = write_ass(scene)
    assert text.count(rectangle) == 2 * len(
        [e for e in scene.elements if isinstance(e, ProgressElement)]
    )  # straight corners, the fill and the frame
    assert f"\\bord{f'{edge:.2f}'.rstrip('0').rstrip('.')}\\shad0" in text


def test_a_turn_switches_the_colours_before_its_syllable() -> None:
    scene = turn_scene()
    _, lines, events = lines_and_events(scene)
    switched = 0
    for line, event in zip(lines, events, strict=True):
        turns = {turn.span: turn.colours for turn in line.turns}
        pieces = [sweep for sweep in event.sweeps if sweep.text]
        assert len(pieces) == len(line.spans)
        for index, sweep in enumerate(pieces):
            if index in turns:
                colours = turns[index]
                expected = tuple(
                    ass_colour(c) for c in (colours.sung, colours.unsung, colours.edge)
                )
                assert sweep.colours == expected
                switched += 1
            else:
                assert sweep.colours is None
    assert switched == 2


def test_a_switch_comes_in_the_block_of_the_syllable_it_colours() -> None:
    line = turn_scene().lines()[4]  # "Stock und Hut": Ben sings "Hut"
    text = karaoke_text(line, "smooth", 0.0)
    colours = line.turns[0].colours
    switch = f"\\1c{ass_colour(colours.sung)}\\2c{ass_colour(colours.unsung)}"
    before, after = text.split(switch)
    assert after.split("}")[1] == line.spans[line.turns[0].span].text  # right before its text
    assert before.endswith("{")
    assert "\\1c" not in before  # the first singer's colours come from the style


def test_the_ass_file_of_a_duet_with_turns_is_golden(snapshot: SnapshotAssertion) -> None:
    assert write_ass(turn_scene()) == snapshot


def test_lines_without_turns_write_no_colour_switch() -> None:
    assert "\\1c" not in "".join(karaoke_text(line, "smooth", 0.0) for line in duet_scene().lines())


def test_two_karaoke_tags_in_one_block_make_two_pieces_and_the_colours_go_to_the_first() -> None:
    tags = "\\1c&H0000FF\\2c&H00FF00\\3c&HFF0000\\k10\\kf20"
    row = f"Dialogue: 0,0:00:01.00,0:00:02.00,s,,0,0,0,,{{{tags}}}ab"
    script = parse_ass("PlayResX: 960\nPlayResY: 720\n" + row + "\n")
    first, second = script.events[0].sweeps
    assert (first.tag, first.centis, first.text) == ("k", 10, "")
    assert first.colours == ("&H0000FF", "&H00FF00", "&HFF0000")
    assert (second.tag, second.centis, second.text, second.colours) == ("kf", 20, "ab", None)


def test_the_timer_is_one_text_event_per_second() -> None:
    scene = entchen_with(builtin_profile("three-line"))
    timer = next(e for e in scene.elements if isinstance(e, TimerElement))
    script = parse_ass(write_ass(scene))
    mine = [
        e
        for e in script.events
        if timer.start - 0.006 <= e.start / 100 <= timer.end and e.text.isdigit()
    ]
    assert len(mine) == timer.total  # a break of 17 s makes 17 events
    assert [e.text for e in mine] == [str(n) for n in range(timer.total, 0, -1)]
    assert abs(mine[0].start / 100 - timer.start) <= HALF_CENTI
    assert abs(mine[-1].end / 100 - timer.end) <= HALF_CENTI
    for before, after in zip(mine, mine[1:], strict=False):
        assert before.end == after.start  # no gap and no overlap between two numbers
    for before, after in zip(mine[1:], mine[2:], strict=False):  # the first is the rest of a second
        assert abs((after.start - before.start) / 100 - 1.0) <= 2 * HALF_CENTI  # a second apart
    assert all(e.size == pytest.approx(timer.size, abs=0.01) for e in mine)
    middle = timer.box.x + timer.box.w / 2
    for event in mine:
        assert event.position == pytest.approx((middle, timer.text_y), abs=0.01)
    assert "\\an8\\pos(" in write_ass(scene)  # centred at the top of the cell, not at its left


def test_the_timer_has_a_style_with_its_colour() -> None:
    scene = entchen_with(builtin_profile("three-line"))
    timer = next(e for e in scene.elements if isinstance(e, TimerElement))
    script = parse_ass(write_ass(scene))
    number = next(
        e for e in script.events if e.text == str(timer.total) and e.style in script.styles
    )
    assert timer.colour[1:].lower() in number.style  # the colour is in the name of the style


def test_a_notice_break_has_no_numbers() -> None:
    script = parse_ass(write_ass(entchen_with(builtin_profile("two-line-turns"))))
    assert not [e for e in script.events if e.text.isdigit()]


def test_a_drawing_has_no_text_and_keeps_the_tags_of_every_block() -> None:
    row = "Dialogue: 0,0:00:01.00,0:00:02.00,s,,0,0,0,,{\\pos(1,2)}{\\p1}m 0 0 l 4 0{\\p0}"
    (event,) = parse_ass("PlayResX: 960\nPlayResY: 720\n" + row + "\n").events
    assert event.drawing and event.text == ""
    assert event.tags == "\\pos(1,2)\\p1\\p0"
