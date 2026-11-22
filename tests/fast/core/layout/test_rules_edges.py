"""Stage 1: the overlap check and the edge cases of the scene rules."""

import math
from collections.abc import Callable

from fakes.measure import FixedMeasurer
from fakes.rule_breaks import (
    BIG,
    CP,
    LINE_COUNT,
    NO_INTRO,
    SMALL,
    P,
    edit,
    hits,
    messages,
    mutate,
    page_profile,
    page_scene,
    preview_profile,
    preview_scene,
    sooner,
    title_of,
    with_span,
    without,
)
from fakes.scenes import (
    entchen_scene,
    entchen_with,
)
from vocatron.core.layout.build import MIN_END_SCREEN, SongText
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.rules_base import EPS, TOLERANCE, gaps
from vocatron.core.layout.rules_singers import rule_17_slots
from vocatron.core.layout.sample import scene_of, timed_song
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    CardElement,
    Colours,
    CountdownElement,
    LineElement,
    PreviewElement,
    Rect,
    Scene,
    Shortfall,
)


def test_two_elements_at_the_same_time_in_the_same_place_overlap() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    twin = line.model_copy()
    scene = base.model_copy(update={"elements": [*base.elements, twin]})
    assert "overlap" in hits(scene, P)
    message = next(m for m in scene_findings(scene, P) if m.startswith("two elements overlap"))
    assert "line 6.0-15.16" in message


def test_elements_that_touch_in_time_or_in_space_do_not_overlap() -> None:
    base = entchen_scene()
    title = title_of(base)
    first = base.lines()[0]
    touching = edit(base, "title", 0, end=first.start + SMALL)
    assert "overlap" not in hits(touching, P)
    overlapping = edit(base, "title", 0, end=first.start + BIG)
    assert "overlap" in hits(overlapping, P)
    assert title.box.overlaps(first.box)  # the boxes do overlap: only the time keeps them apart
    # the same time, the boxes side by side
    right_edge = Rect(x=first.box.right, y=first.box.y, w=10, h=first.box.h)
    beside = base.model_copy(
        update={"elements": [*base.elements, first.model_copy(update={"box": right_edge})]}
    )
    assert "overlap" not in hits(beside, P)


def solved(make: Callable[[float], float], wanted: float, guess: float) -> float:
    """Return the float ``x`` near ``guess`` for which ``make(x)`` is exactly ``wanted``.

    ``make`` must rise or fall steadily with ``x``; it is the arithmetic a rule does with the
    value, so that the result sits on the edge of the rule to the last bit.
    """
    rising = make(guess + 1.0) > make(guess)
    x = guess
    for _ in range(64):
        value = make(x)
        if value == wanted:
            return x
        x = math.nextafter(x, math.inf if (value < wanted) == rising else -math.inf)
    raise AssertionError("no float found for the edge")


def test_edge_rule_3_a_line_exactly_at_the_slack_below_the_smallest_size() -> None:
    base = entchen_scene()
    scene = edit(base, "line", 0, size=P.font.min_size * base.safe.h - TOLERANCE)
    assert "3" not in hits(scene, P)


def test_edge_rule_5_a_line_after_a_gap_shown_exactly_the_target_less_the_slack() -> None:
    base = entchen_scene()
    line = base.lines()[2]  # after a long gap
    shown = line.sing_start - line.start
    target = solved(lambda t: t - TOLERANCE, shown, shown + TOLERANCE)
    lead = P.lead_in.model_copy(update={"max": 1e9, "target": target})
    cleared = P.clear.model_copy(update={"hold": 0.0})  # the screen is cleared as the singing stops
    chosen = P.model_copy(update={"lead_in": lead, "clear": cleared})
    room = line.sing_start - base.lines()[1].sing_end
    assert room > target  # the room after the clearing is no limit, the target is
    assert "line 2 after a gap" not in " ".join(messages(base, chosen, 5))
    later = edit(base, "line", 2, start=line.start + BIG)
    assert "line 2 after a gap" in " ".join(messages(later, chosen, 5))


def test_edge_rule_5_a_reported_line_of_the_first_page_could_not_appear_sooner_than_0() -> None:
    base = page_scene()
    chosen = page_profile()
    lines = base.lines()
    second = next(i for i, x in enumerate(lines) if x.page == 0 and i > 0)
    late = edit(base, "line", second, start=lines[second].sing_start - 0.5)
    reported = late.model_copy(
        update={"shortfalls": [Shortfall(kind="lead-in", line=second, message="x")]}
    )
    assert "could appear sooner" in " ".join(messages(reported, chosen, 5))


def test_edge_rule_6_a_line_that_goes_the_least_before_the_last_syllable_ends() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    scene = edit(base, "line", 0, end=line.sing_end - EPS)
    assert "6" not in hits(scene, P)


def test_edge_rule_6_a_last_syllable_without_length_needs_no_screen_time() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    last = len(line.spans) - 1
    point = mutate(
        base,
        "line",
        0,
        lambda x: with_span(x, last, start=x.spans[last].end).model_copy(
            update={"end": x.spans[last].end - EPS / 2}
        ),
    )
    assert "6" not in hits(point, P)


def test_edge_rule_8_a_narrow_syllable_of_more_than_a_pixel_is_held_to_it() -> None:
    base = entchen_scene()
    scene = base.model_copy(update={"look": base.look.model_copy(update={"wipe": "syllable"})})
    narrow = mutate(
        scene,
        "line",
        0,
        lambda x: x.model_copy(
            update={"spans": [s.model_copy(update={"x1": s.x0 + 1.5}) for s in x.spans]}
        ),
    )
    assert messages(narrow, P, 8)[0].startswith("rule 8: line 0 ")


def test_edge_rule_9_the_last_line_goes_exactly_at_the_slack() -> None:
    base = entchen_scene()
    chosen = P.model_copy(update={"clear": P.clear.model_copy(update={"hold": 0.0})})
    line = base.lines()[-1]
    at_zero = [span.model_copy(update={"start": 0.0, "end": 0.0}) for span in line.spans]
    only = base.model_copy(update={"elements": [line.model_copy(update={"spans": at_zero})]})
    # sung to its end at 0, so it goes at 0: a slack of exactly TOLERANCE is a float of its own
    assert messages(edit(only, "line", 0, start=0.0, end=TOLERANCE), chosen, 9) == []
    assert messages(edit(only, "line", 0, start=0.0, end=2 * TOLERANCE), chosen, 9) != []


def test_edge_rule_10_lines_with_and_without_a_page_are_not_numbered_in_order() -> None:
    base = page_scene()
    scene = edit(base, "line", 0, page=None)
    assert "numbered in order" in " ".join(messages(scene, page_profile(), 10))


def test_edge_rule_11_a_line_that_shows_within_the_slack_fills_the_gap() -> None:
    base = preview_scene()
    chosen = preview_profile()
    ended = base.lines()[0].sing_end
    assert base.lines()[0].end == ended
    near = edit(base, "line", 1, start=ended + 0.004)
    assert messages(near, chosen, 11) == []
    far = edit(base, "line", 1, start=ended + 0.01)
    assert "the screen is empty" in " ".join(messages(far, chosen, 11))


def test_edge_rule_12_a_gap_as_long_as_clear_after_is_a_long_gap() -> None:
    base = entchen_scene()
    lines = base.lines()
    chosen = P.model_copy(
        update={"breaks": P.breaks.model_copy(update={"clear_after": gaps(lines)[2].before})}
    )
    late = edit(base, "line", 2, start=17.0)
    stays = edit(late, "line", 1, end=17.0)
    assert "before line 2" in " ".join(messages(stays, chosen, 12))


def test_edge_rule_12_a_break_screen_starting_the_slack_before_the_screen_is_cleared() -> None:
    base = entchen_scene()
    lines = base.lines()
    cleared = max(x.sing_end for x in lines[:5]) + P.clear.hold
    scene = edit(base, "break", 0, start=cleared - TOLERANCE)
    assert "too early" not in " ".join(messages(scene, P, 12))


def test_edge_rule_12_a_progress_bar_the_slack_above_the_bottom_of_the_text() -> None:
    base = page_scene()
    card = next(e for e in base.elements if e.kind == "break")
    bar = next(e for e in base.elements if e.kind == "progress")
    box = Rect(x=bar.box.x, y=card.box.bottom - TOLERANCE, w=bar.box.w, h=bar.box.h)
    scene = edit(base, "progress", 0, box=box)
    assert "under the text" not in " ".join(messages(scene, page_profile(), 12))


def test_edge_rule_14_a_song_that_starts_when_a_short_title_would_just_fit_needs_none() -> None:
    song = timed_song(
        "Alle meine Entchen\nschwimmen auf dem See\n",
        start=NO_INTRO.lead_in.min + NO_INTRO.title.min_short,
    )
    scene = scene_of(
        song,
        SongText("Ein Titel", "Eine Künstlerin", 30.0, {}),
        NO_INTRO,
        "4x3-720",
        FixedMeasurer(),
    )
    assert (
        abs(scene.lines()[0].sing_start - (NO_INTRO.lead_in.min + NO_INTRO.title.min_short)) < SMALL
    )
    assert "missing" not in " ".join(messages(without(scene, "title"), NO_INTRO, 14))


def test_edge_rule_15_the_last_line_goes_exactly_the_slack_after_its_hold() -> None:
    base = entchen_scene()
    limit = max(x.sing_end for x in base.lines()) + P.clear.hold + TOLERANCE
    scene = edit(base, "line", LINE_COUNT - 1, end=limit)
    assert messages(scene, P, 15) == []


def test_edge_rule_15_the_end_screen_starts_exactly_the_slack_late() -> None:
    base = entchen_scene()
    last = max(x.sing_end for x in base.lines())
    # The end screen is due at 0, so its offset is exactly the slack in floating point (near the
    # real due time it is not, and the edge would go untested). The negative wait is not a valid
    # look but model_copy does not check it; with ``end_screen`` off the hold is not capped by
    # it, so the hold check passes and the start check is reached.
    ending = P.ending.model_copy(update={"start_after": -last, "end_screen": False})
    chosen = P.model_copy(update={"ending": ending})
    scene = edit(base, "end", 0, start=TOLERANCE)
    assert "wrong time" not in " ".join(messages(scene, chosen, 15))
    assert "wrong time" in " ".join(messages(edit(base, "end", 0, start=2 * TOLERANCE), chosen, 15))


def test_edge_rule_15_the_end_screen_ends_exactly_the_slack_early() -> None:
    base = entchen_scene().model_copy(update={"duration": 0.0})
    scene = edit(base, "end", 0, end=TOLERANCE)
    assert "ends early" not in " ".join(messages(scene, P, 15))
    assert "ends early" in " ".join(messages(edit(base, "end", 0, end=2 * TOLERANCE), P, 15))


def test_edge_rule_15_the_fade_is_exactly_the_slack_off() -> None:
    base = entchen_scene()
    chosen = P.model_copy(update={"ending": P.ending.model_copy(update={"fade": 0.0})})
    scene = edit(base, "end", 0, fade_out=TOLERANCE)
    assert "fade is wrong" not in " ".join(messages(scene, chosen, 15))
    assert "fade is wrong" in " ".join(
        messages(edit(base, "end", 0, fade_out=2 * TOLERANCE), chosen, 15)
    )


def test_edge_rule_15_an_end_screen_of_exactly_the_least_length_is_needed() -> None:
    base = without(entchen_scene(), "end")
    last = max(x.sing_end for x in base.lines())
    after = P.ending.start_after
    duration = solved(lambda d: d - last - after, MIN_END_SCREEN, last + after + MIN_END_SCREEN)
    scene = base.model_copy(update={"duration": duration})
    assert "end screen is missing" in " ".join(messages(scene, P, 15))


def test_edge_overlap_of_exactly_the_slack_in_time_is_none() -> None:
    base = entchen_scene()
    box = Rect(x=0, y=0, w=5, h=5)
    first = CardElement(kind="end", start=0.0, end=TOLERANCE, box=box, lines=[])
    second = first.model_copy(update={"end": 5.0})
    scene = base.model_copy(update={"elements": [first, second, *base.elements]})
    assert "overlap" not in hits(scene, P)
    longer = first.model_copy(update={"end": 2 * TOLERANCE})
    scene = base.model_copy(update={"elements": [longer, second, *base.elements]})
    assert "overlap" in hits(scene, P)


def test_edge_rule_14_the_title_ends_exactly_the_slack_after_the_first_line_starts() -> None:
    base = entchen_scene()
    scene = edit(base, "title", 0, end=base.lines()[0].start + TOLERANCE)
    assert "still there" not in " ".join(messages(scene, P, 14))


def test_edge_rule_14_a_title_exactly_the_slack_shorter_than_the_least_is_fine() -> None:
    base = entchen_scene()
    assert base.lines()[0].sing_start >= P.title.min + P.lead_in.target
    scene = edit(base, "title", 0, end=P.title.min - TOLERANCE)
    assert "too short" not in " ".join(messages(scene, P, 14))


def test_edge_rule_14_a_shortened_title_exactly_the_slack_short_of_the_least_is_fine() -> None:
    start = P.title.min + P.lead_in.target - 1.0
    song = timed_song("Alle meine Entchen\nschwimmen auf dem See\n", start=start)
    scene = scene_of(
        song, SongText("Ein Titel", "Eine Künstlerin", 30.0, {}), P, "4x3-720", FixedMeasurer()
    )
    exact = edit(scene, "title", 0, end=P.title.min_short - TOLERANCE)
    assert "shortened too far" not in " ".join(messages(exact, P, 14))


def test_edge_rule_5_a_gap_as_long_as_clear_after_asks_for_the_target_lead_in() -> None:
    base = entchen_scene()
    lines = base.lines()
    chosen = P.model_copy(
        update={"breaks": P.breaks.model_copy(update={"clear_after": gaps(lines)[2].before})}
    )
    scene = edit(base, "line", 2, start=lines[2].sing_start - (P.lead_in.target - 1.0))
    assert "line 2 after a gap" in " ".join(messages(scene, chosen, 5))


def test_edge_rule_17_a_line_that_stops_the_instant_another_starts_is_not_sung_with_it() -> None:
    base = entchen_scene()

    def sung(line: LineElement, start: float, end: float) -> LineElement:
        return line.model_copy(
            update={"spans": [line.spans[0].model_copy(update={"start": start, "end": end})]}
        )

    scene = mutate(
        mutate(base, "line", 0, lambda x: sung(x, 0.0, 5.0)), "line", 1, lambda x: sung(x, 0.0, EPS)
    )
    one_slot = P.model_copy(update={"slots": 1})
    rule_17_slots(scene, one_slot)


def test_edge_rule_7_a_front_that_stops_short_of_the_end_of_a_wide_syllable() -> None:
    base = entchen_scene()
    last = len(base.lines()[0].spans) - 1
    wide = mutate(
        base,
        "line",
        0,
        lambda x: with_span(x, last, x1=x.spans[last].x1 + 1e6),
    )
    assert messages(wide, P, 7) == []


def test_edge_rule_11_a_break_screen_after_a_gap_exactly_as_long_as_notice_after() -> None:
    base = entchen_scene()
    gap = gaps(base.lines())[5].before
    notice = solved(lambda n: n - EPS, gap, gap + EPS)
    chosen = P.model_copy(update={"breaks": P.breaks.model_copy(update={"notice_after": notice})})
    assert "a break screen in a short gap" not in " ".join(messages(base, chosen, 11))


def test_edge_rule_11_a_gap_exactly_as_long_as_clear_after_may_clear_the_screen() -> None:
    base = entchen_scene()
    lines = base.lines()
    chosen = P.model_copy(
        update={"breaks": P.breaks.model_copy(update={"clear_after": gaps(lines)[2].before})}
    )
    cleared = edit(edit(base, "line", 0, end=lines[1].sing_end), "line", 1, end=lines[1].sing_end)
    assert "gap before line 2" not in " ".join(messages(cleared, chosen, 11))
    shorter = P.model_copy(
        update={"breaks": P.breaks.model_copy(update={"clear_after": gaps(lines)[2].before + 0.5})}
    )
    assert "gap before line 2" in " ".join(messages(cleared, shorter, 11))


def test_edge_rule_11_a_line_that_goes_as_the_next_one_is_sung_leaves_no_moment_to_check() -> None:
    base = preview_scene()
    chosen = preview_profile()
    lines = base.lines()
    resumes = lines[1].sing_start
    scene = edit(edit(base, "line", 0, end=resumes), "line", 1, start=resumes + 0.01)
    assert "the screen is empty" not in " ".join(messages(scene, chosen, 11))
    earlier = edit(edit(base, "line", 0, end=resumes - 0.02), "line", 1, start=resumes + 0.01)
    assert "the screen is empty" in " ".join(messages(earlier, chosen, 11))


def test_edge_rule_12_a_line_that_goes_exactly_the_slack_after_the_hold_is_gone() -> None:
    base = entchen_scene()
    lines = base.lines()
    cleared = max(x.sing_end for x in lines[:5]) + P.clear.hold
    scene = edit(base, "line", 4, end=cleared + TOLERANCE)
    assert "a line stays" not in " ".join(messages(scene, P, 12))


def test_edge_rule_13_a_line_shown_exactly_the_slack_early_needs_no_countdown() -> None:
    base = without(entchen_scene(), "countdown")
    after_gaps = [i for i, g in enumerate(gaps(base.lines())) if g.before >= P.countdown.min_gap]
    assert after_gaps
    scene = base
    for number in after_gaps:
        sing = base.lines()[number].sing_start
        scene = edit(scene, "line", number, start=sing - TOLERANCE)
    assert messages(scene, P, 13) == []


def test_edge_rule_13_a_countdown_that_ends_exactly_the_slack_above_the_slots() -> None:
    base = entchen_scene()
    countdown = next(e for e in base.elements if isinstance(e, CountdownElement))
    wanted = base.slots[0].y + TOLERANCE
    y = solved(lambda top: top + countdown.box.h, wanted, wanted - countdown.box.h)
    box = Rect(x=countdown.box.x, y=y, w=countdown.box.w, h=countdown.box.h)
    scene = edit(base, "countdown", 0, box=box)
    assert "not above" not in " ".join(messages(scene, P, 13))


def test_edge_rule_14_a_song_that_starts_exactly_the_slack_after_a_short_title_would_fit() -> None:
    base = without(without(entchen_scene(), "title"), "countdown")
    first = base.lines()[0]
    start = P.lead_in.min + P.title.min_short + TOLERANCE
    scene = edit(
        base,
        "line",
        0,
        spans=[first.spans[0].model_copy(update={"start": start}), *first.spans[1:]],
    )
    assert "missing" in " ".join(messages(scene, P, 14))


def lead_in_of(chosen: Profile, **update: float) -> Profile:
    """Return ``chosen`` with lead-in values replaced (not validated: an edge, not a profile)."""
    return chosen.model_copy(update={"lead_in": chosen.lead_in.model_copy(update=update)})


def test_edge_rule_3_a_line_exactly_the_slack_wider_than_the_safe_area() -> None:
    base = entchen_scene()
    slack = base.safe.w + TOLERANCE
    box = Rect(x=base.safe.x, y=base.slots[0].y, w=slack, h=base.slots[0].h)
    assert "too wide" not in " ".join(messages(edit(base, "line", 0, box=box), P, 3))
    box = Rect(x=base.safe.x, y=base.slots[0].y, w=slack + 0.001, h=base.slots[0].h)
    assert "too wide" in " ".join(messages(edit(base, "line", 0, box=box), P, 3))


def test_edge_rule_3_a_line_exactly_the_slack_above_the_font_size() -> None:
    base = entchen_scene()
    scene = edit(base, "line", 0, size=P.font.size * base.safe.h + TOLERANCE)
    assert "larger" not in " ".join(messages(scene, P, 3))


def test_edge_rule_4_a_preview_that_starts_at_the_bottom_of_the_slots() -> None:
    base = preview_scene()
    chosen = preview_profile()
    preview = next(e for e in base.elements if isinstance(e, PreviewElement))
    slot = base.slots[0]
    row = Rect(x=48.0, y=slot.y, w=864.0, h=400.0)
    for slack in (0.0, TOLERANCE):
        wanted = preview.box.y + slack
        height = solved(lambda h: slot.y + h, wanted, wanted - slot.y)
        taller = Rect(x=slot.x, y=slot.y, w=slot.w, h=height)
        scene = base.model_copy(update={"slots": [taller], "preview_row": row})
        assert messages(scene, chosen, 4) == []
    below = Rect(x=slot.x, y=slot.y, w=slot.w, h=preview.box.y - slot.y + 2 * TOLERANCE)
    scene = base.model_copy(update={"slots": [below], "preview_row": row})
    assert messages(scene, chosen, 4) == ["rule 4"]


def test_edge_rule_5_a_line_shown_exactly_the_slack_longer_than_the_most() -> None:
    base = entchen_scene()
    line = base.lines()[2]
    wanted = P.lead_in.max + TOLERANCE
    start = solved(lambda st: line.sing_start - st, wanted, line.sing_start - wanted)
    assert "ahead" not in " ".join(messages(edit(base, "line", 2, start=start), P, 5))


def test_edge_rule_5_the_second_line_after_a_gap_is_shown_for_the_target_time() -> None:
    base = entchen_scene()
    chosen = P.model_copy(
        update={
            "breaks": P.breaks.model_copy(update={"clear_after": 0.5}),
            "lead_in": P.lead_in.model_copy(update={"min": 0.1, "target": 100.0, "max": 1e9}),
            "clear": P.clear.model_copy(update={"hold": 0.0}),
        }
    )
    line = base.lines()[1]  # 0.68 s after line 0: all the room there is after the clearing
    later = edit(base, "line", 1, start=line.sing_start - 0.3)
    assert messages(later, chosen, 5) == ["rule 5: line 1 after a gap"]
    at_clearing = edit(later, "line", 1, start=base.lines()[0].sing_end)
    assert "line 1" not in " ".join(messages(at_clearing, chosen, 5))


def test_edge_rule_6_a_line_that_appears_exactly_the_slack_late_is_fine() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    scene = edit(base, "line", 0, start=line.sing_start + EPS)
    assert "appears late" not in " ".join(messages(scene, P, 6))


def test_edge_rule_6_a_syllable_the_length_of_the_slack_is_seen_or_found_out() -> None:
    base = entchen_scene()
    last = len(base.lines()[0].spans) - 1
    point = mutate(base, "line", 0, lambda x: with_span(x, last, start=0.0, end=EPS))
    assert messages(point, P, 6) == ["rule 6: line 0"]
    tiny = mutate(base, "line", 0, lambda x: with_span(x, last, start=0.0, end=EPS / 2))
    assert messages(tiny, P, 6) == []
    line = base.lines()[0]
    end = line.sing_end
    short = mutate(
        base,
        "line",
        0,
        lambda x: with_span(x, last, start=end - 1.5 * EPS).model_copy(update={"end": x.end}),
    )
    short = edit(short, "line", 0, end=end - EPS)
    assert messages(short, P, 6) == ["rule 6: line 0"]


def test_edge_rule_7_a_first_word_that_ends_before_the_first_pixel() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    first = next(
        i
        for i, s in enumerate(line.spans)
        if i + 1 == len(line.spans) or line.spans[i + 1].start > s.end + TOLERANCE
    )
    narrow = mutate(base, "line", 0, lambda x: with_span(x, first, x0=0.0, x1=0.5))
    assert messages(narrow, P, 7) == []


def test_edge_rule_7_a_syllable_without_width_is_inside_itself() -> None:
    base = entchen_scene()
    first = base.lines()[0].spans[0]
    flat = mutate(base, "line", 0, lambda x: with_span(x, 0, x1=first.x0))
    assert messages(flat, P, 7) == []


def test_edge_rule_7_a_syllable_with_an_edge_on_the_slack() -> None:
    base = entchen_scene()
    syllables = base.model_copy(update={"look": base.look.model_copy(update={"wipe": "syllable"})})
    first = base.lines()[0].spans[0]
    reversed_ = mutate(syllables, "line", 0, lambda x: with_span(x, 0, x0=100.0, x1=100.0 - EPS))
    del first
    assert messages(reversed_, P, 7) == []


def test_edge_rule_7_syllables_that_end_on_the_same_place_do_not_go_backwards() -> None:
    base = entchen_scene()
    first = base.lines()[0].spans[0]
    flat = mutate(base, "line", 0, lambda x: with_span(x, 1, x0=first.x1, x1=first.x1))
    assert messages(flat, P, 7) == []


def test_edge_rule_8_syllables_of_the_edge_length_and_width() -> None:
    base = entchen_scene()
    syllables = base.look.model_copy(update={"wipe": "syllable"})
    line = base.lines()[0]
    span = line.spans[0]

    def alone(start: float, end: float, width: float) -> Scene:
        one = span.model_copy(update={"start": start, "end": end, "x0": 0.0, "x1": width})
        return base.model_copy(
            update={"look": syllables, "elements": [line.model_copy(update={"spans": [one]})]}
        )

    assert messages(alone(0.0, 4 * TOLERANCE, 50.0), P, 8) == []
    assert messages(alone(0.0, 4.5 * TOLERANCE, 50.0), P, 8) != []
    assert messages(alone(0.0, 1.0, 1.0), P, 8) == []
    assert messages(alone(0.0, 1.0, 1.5), P, 8) != []


def test_edge_rule_9_a_gap_exactly_as_long_as_clear_after_less_the_slack_is_long() -> None:
    base = entchen_scene()
    gap = gaps(base.lines())[2].before
    clear_after = solved(lambda c: c - EPS, gap, gap + EPS)
    chosen = P.model_copy(
        update={"breaks": P.breaks.model_copy(update={"clear_after": clear_after})}
    )
    assert messages(base, chosen, 9) == []


def test_edge_rule_10_a_line_appears_exactly_the_slack_before_the_line_before_it() -> None:
    base = entchen_scene()
    lines = base.lines()
    scene = edit(base, "line", 3, start=lines[2].start - EPS)
    assert "line 3 is early" not in " ".join(messages(scene, P, 10))


def test_edge_rule_10_a_slot_freed_exactly_the_slack_after_the_first() -> None:
    base = entchen_scene()
    lines = base.lines()
    freed = lines[0].sing_end + EPS
    scene = mutate(base, "line", 1, lambda x: with_span(x, len(x.spans) - 1, end=freed))
    scene = edit(scene, "line", 2, slot=1)
    assert "rule 10: line 2" not in " ".join(messages(scene, P, 10))


def test_edge_rule_11_a_countdown_in_a_gap_exactly_the_slack_short_of_the_least() -> None:
    base = entchen_scene()
    gap = gaps(base.lines())[2].before
    least = solved(lambda m: m - EPS, gap, gap + EPS)
    chosen = P.model_copy(update={"countdown": P.countdown.model_copy(update={"min_gap": least})})
    assert "a countdown in a short gap" not in " ".join(messages(base, chosen, 11))


def test_edge_rule_11_a_line_that_starts_exactly_the_slack_before_the_break_screen_ends() -> None:
    base = entchen_scene()
    card = next(e for e in base.elements if e.kind == "break")
    scene = edit(base, "line", 5, start=card.end - TOLERANCE)
    assert "a break screen in a short gap" not in " ".join(messages(scene, P, 11))


def test_edge_rule_11_a_gap_of_no_time_needs_no_line_on_screen() -> None:
    base = preview_scene()
    lines = base.lines()
    shift = lines[1].sing_start - lines[0].sing_end
    joined = mutate(
        base,
        "line",
        1,
        lambda x: x.model_copy(
            update={
                "spans": [
                    s.model_copy(update={"start": s.start - shift, "end": s.end - shift})
                    for s in x.spans
                ]
            }
        ),
    )
    joined = edit(joined, "line", 1, start=lines[1].sing_start + 1.0)
    assert gaps(joined.lines())[1].before == 0.0
    assert "the screen is empty" not in " ".join(messages(joined, preview_profile(), 11))


def test_edge_rule_11_a_gap_less_the_slack_as_long_as_clear_after_may_clear_the_screen() -> None:
    base = entchen_scene()
    lines = base.lines()
    gap = gaps(lines)[2].before
    clear_after = solved(lambda c: c - EPS, gap, gap + EPS)
    chosen = P.model_copy(
        update={"breaks": P.breaks.model_copy(update={"clear_after": clear_after})}
    )
    cleared = edit(edit(base, "line", 0, end=lines[1].sing_end), "line", 1, end=lines[1].sing_end)
    assert "gap before line 2" not in " ".join(messages(cleared, chosen, 11))


def test_edge_rule_11_a_line_that_goes_the_slack_before_the_next_is_sung_leaves_a_moment() -> None:
    base = preview_scene()
    lines = base.lines()
    resumes = lines[1].sing_start
    scene = edit(edit(base, "line", 0, end=resumes - TOLERANCE), "line", 1, start=resumes + 0.01)
    assert "the screen is empty" not in " ".join(messages(scene, preview_profile(), 11))


def test_edge_rule_12_a_line_stays_when_the_next_shows_just_after_the_screen_is_cleared() -> None:
    base = entchen_scene()
    lines = base.lines()
    cleared = max(x.sing_end for x in lines[:5]) + P.clear.hold
    stays = edit(base, "line", 4, end=cleared + 1.0)
    for shows in (cleared + SMALL, cleared + TOLERANCE):
        scene = edit(stays, "line", 5, start=shows)
        assert "a line stays" not in " ".join(messages(scene, P, 12))
    scene = edit(stays, "line", 5, start=cleared + BIG)
    assert "a line stays" in " ".join(messages(scene, P, 12))


def test_edge_rule_12_a_line_that_starts_the_instant_before_the_next_shows() -> None:
    base = entchen_scene()
    lines = base.lines()
    shows = lines[5].start
    scene = edit(base, "line", 4, start=shows - EPS, end=shows + 2.0)
    assert "a line stays" not in " ".join(messages(scene, P, 12))


def test_edge_rule_12_a_break_screen_is_needed_after_a_gap_as_long_as_notice_after() -> None:
    base = without(entchen_scene(), "break")
    gap = gaps(base.lines())[5].before
    chosen = P.model_copy(update={"breaks": P.breaks.model_copy(update={"notice_after": gap})})
    assert "no break screen before line 5" in " ".join(messages(base, chosen, 12))


def test_edge_rule_12_no_break_screen_is_needed_when_the_next_line_shows_at_once() -> None:
    base = without(entchen_scene(), "break")
    lines = base.lines()
    cleared = max(x.sing_end for x in lines[:5]) + P.clear.hold
    for shows in (cleared + SMALL, cleared + TOLERANCE):
        scene = edit(base, "line", 5, start=shows)
        assert "no break screen" not in " ".join(messages(scene, P, 12))
    scene = edit(base, "line", 5, start=cleared + BIG)
    assert "no break screen" in " ".join(messages(scene, P, 12))


def test_edge_rule_13_a_countdown_is_needed_after_a_gap_as_long_as_the_least() -> None:
    base = entchen_scene()
    gap = gaps(base.lines())[2].before
    chosen = P.model_copy(update={"countdown": P.countdown.model_copy(update={"min_gap": gap})})
    scene = mutate(base, "countdown", 1, lambda _: None)
    scene = scene.model_copy(update={"elements": [e for e in scene.elements if e is not None]})
    assert "rule 13: 2" in messages(scene, chosen, 13)


def test_edge_rule_13_every_gap_is_looked_at_not_only_the_first() -> None:
    base = entchen_scene()
    countdowns = [e for e in base.elements if isinstance(e, CountdownElement)]
    last = countdowns[-1]
    scene = base.model_copy(update={"elements": [e for e in base.elements if e is not last]})
    assert messages(scene, P, 13) == ["rule 13: 5"]
    first = countdowns[0]
    line = base.lines()[0]
    scene = scene.model_copy(update={"elements": [e for e in scene.elements if e is not first]})
    scene = edit(scene, "line", 0, start=line.sing_start)
    assert messages(scene, P, 13) == ["rule 13: 5"]


def test_edge_singers_one_to_five_have_the_colours_of_their_own() -> None:
    base = entchen_with(CP)
    for singer in "12345":
        own = CP.singer_colours(singer)
        colours = Colours(unsung=own.unsung, sung=own.sung, edge=own.edge)
        scene = edit(base, "line", 0, singers=singer, colours=colours)
        assert messages(scene, CP, 16) == [], singer


def reported_at(scene: Scene, number: int, seen: float, shown: float = 0.8) -> Scene:
    """Return ``scene`` with line ``number`` reported and first seen at ``seen``.

    The syllables are moved so that the line is shown for ``shown`` seconds before it is sung,
    which is less than the least lead-in of ``SHORT_LEAD``.
    """
    line = scene.lines()[number]
    shift = (seen + shown) - line.sing_start
    moved = mutate(
        scene,
        "line",
        number,
        lambda x: x.model_copy(
            update={
                "start": seen,
                "spans": [
                    s.model_copy(update={"start": s.start + shift, "end": s.end + shift})
                    for s in x.spans
                ],
            }
        ),
    )
    report = [*scene.shortfalls, Shortfall(kind="lead-in", line=number, message="x")]
    return without(moved, "countdown").model_copy(update={"shortfalls": report})


SHORT_LEAD = 0.95  # a lead-in just under the least of the profiles, for lines shown 0.8 s ahead


def test_edge_rule_5_a_reported_first_line_could_have_appeared_at_the_start() -> None:
    base = entchen_scene()
    chosen = lead_in_of(P, min=SHORT_LEAD, max=1e9)
    assert not sooner(reported_at(base, 0, TOLERANCE), chosen)
    assert sooner(reported_at(base, 0, 0.5), chosen)
    assert sooner(reported_at(base, 0, 2 * TOLERANCE), chosen)


def test_edge_rule_5_a_reported_line_in_a_free_slot_could_appear_with_the_line_before_it() -> None:
    base = entchen_scene()
    chosen = lead_in_of(P, min=SHORT_LEAD, max=1e9)
    first = base.lines()[0].start
    assert not sooner(reported_at(base, 1, first), chosen)
    assert not sooner(reported_at(base, 1, first - 0.1), chosen)
    assert sooner(reported_at(base, 1, first + 0.1), chosen)
    # the line before it may itself be shown early: the earliest moves with it
    early = edit(base, "line", 0, start=0.0)
    assert sooner(reported_at(early, 1, 0.5), chosen)


def test_edge_rule_5_a_reported_line_waits_for_the_slot_it_shares() -> None:
    base = entchen_scene()
    chosen = lead_in_of(P, min=SHORT_LEAD, max=1e9)
    lines = base.lines()
    free = lines[0].sing_end  # line 2 shares the slot of line 0
    assert not sooner(reported_at(base, 2, free), chosen)
    assert sooner(reported_at(base, 2, free + 0.1), chosen)


def test_edge_rule_5_a_reported_preview_could_appear_with_the_line_before_it() -> None:
    base = preview_scene()
    chosen = lead_in_of(preview_profile(), min=SHORT_LEAD, max=1e9)
    lines = base.lines()
    previews = [e for e in base.elements if isinstance(e, PreviewElement)]
    number = next(i for i, p in enumerate(previews) if p.of_line == 3)
    for seen, expected in ((lines[2].start, False), (lines[2].start + 0.1, True)):
        scene = mutate(
            reported_at(base, 3, seen),
            "preview",
            number,
            lambda p, at=seen: p.model_copy(update={"start": at, "end": at}),
        )
        assert sooner(scene, chosen) is expected


def test_edge_rule_5_a_reported_page_could_have_appeared_at_the_start() -> None:
    base = page_scene()
    chosen = lead_in_of(page_profile(), min=SHORT_LEAD, max=1e9)
    second = next(i for i, x in enumerate(base.lines()) if x.page == 0 and i > 0)
    assert sooner(reported_at(base, second, 0.5), chosen)
    assert not sooner(reported_at(base, second, TOLERANCE), chosen)


def test_edge_rule_5_lead_ins_exactly_the_slack_from_the_edges() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    alone = base.model_copy(update={"elements": [line]})
    shown = line.sing_start - line.start
    report = [Shortfall(kind="lead-in", line=0, message="x")]
    reported = alone.model_copy(update={"shortfalls": report})
    least = solved(lambda m: m + TOLERANCE, shown, shown - TOLERANCE)
    assert "reported but fine" in " ".join(messages(reported, lead_in_of(P, min=least), 5))
    just = solved(lambda m: m - TOLERANCE, shown, shown + TOLERANCE)
    assert "only" not in " ".join(messages(alone, lead_in_of(P, min=just), 5))
    latest = solved(lambda m: m + TOLERANCE, shown, shown - TOLERANCE)
    assert "ahead" not in " ".join(messages(alone, lead_in_of(P, max=latest), 5))


def test_edge_rule_7_a_syllable_with_no_length_in_time_is_not_checked_in_the_middle() -> None:
    base = without(entchen_scene(), "countdown")
    brief = mutate(
        base, "line", 0, lambda x: with_span(x, 0, start=0.0, end=TOLERANCE, x0=100.0, x1=50.0)
    )
    assert messages(brief, P, 7) == []


def test_edge_rule_7_a_syllable_sung_inside_another_ends_where_the_front_is() -> None:
    base = without(entchen_scene(), "countdown")
    line = base.lines()[0]
    first = line.spans[0].model_copy(update={"start": 10.0, "end": 20.0, "x0": 0.0, "x1": 100.0})
    second = line.spans[1].model_copy(update={"start": 12.0, "end": 13.0, "x0": 10.0, "x1": 40.0})
    scene = edit(base, "line", 0, spans=[first, second])
    assert messages(scene, P, 7) == ["rule 7: line 0, end of a syllable"]
    after = scene.lines()[0].wipe_front(13.0 + EPS, scene.look)
    close = second.model_copy(update={"x1": after + TOLERANCE / 2})
    assert messages(edit(base, "line", 0, spans=[first, close]), P, 7) == []


def test_edge_rule_10_the_pages_cannot_be_mixed_up() -> None:
    base = page_scene()
    swapped = edit(edit(base, "line", 1, page=1), "line", 2, page=0)
    assert messages(swapped, page_profile(), 10) == ["rule 10"]


def test_edge_rule_10_a_page_sung_exactly_the_slack_before_the_pages_before_it() -> None:
    base = without(page_scene(), "countdown")
    lines = base.lines()
    second = next(i for i, x in enumerate(lines) if x.page == 1)
    before = max(x.sing_end for x in lines if x.page == 0)
    scene = mutate(base, "line", second, lambda x: with_span(x, 0, start=before - TOLERANCE))
    assert "cut between" not in " ".join(messages(scene, page_profile(), 10))


def test_edge_rule_13_a_countdown_exactly_the_slack_longer_than_the_profile_says() -> None:
    base = entchen_scene()
    countdown = next(e for e in base.elements if isinstance(e, CountdownElement))
    length = countdown.end - countdown.start
    duration = solved(lambda d: d + TOLERANCE, length, length - TOLERANCE)
    chosen = P.model_copy(
        update={"countdown": P.countdown.model_copy(update={"duration": duration})}
    )
    assert "lasts" not in " ".join(messages(base, chosen, 13))


def test_edge_rule_7_words_that_end_on_the_same_place_do_not_go_backwards() -> None:
    base = entchen_scene()
    line = base.lines()[0]
    ends = [
        i
        for i, s in enumerate(line.spans)
        if i + 1 == len(line.spans) or line.spans[i + 1].start > s.end + TOLERANCE
    ]
    first, second = ends[:2]
    place = line.spans[first].x1
    scene = mutate(base, "line", 0, lambda x: with_span(x, second, x0=place, x1=place))
    assert messages(scene, P, 7) == []
    behind = mutate(base, "line", 0, lambda x: with_span(x, second, x0=place - 5, x1=place - 5))
    assert "goes backwards" in " ".join(messages(behind, P, 7))


def test_edge_rule_5_a_reported_line_without_a_preview_waits_for_its_slot() -> None:
    base = preview_scene()
    chosen = lead_in_of(preview_profile(), min=SHORT_LEAD, max=1e9)
    lines = base.lines()
    previews = {e.of_line for e in base.elements if isinstance(e, PreviewElement)}
    number = next(i for i in range(2, len(lines)) if i not in previews)
    seen = lines[number - 1].start + 0.1
    assert lines[number - 1].sing_end > seen
    assert not sooner(reported_at(base, number, seen), chosen)
    late = lines[number - 1].sing_end + 0.1
    assert sooner(reported_at(base, number, late), chosen)
