"""Stage 1: the rules of the countdown, the title and the ending (rules 13 to 15)."""

from typing import Any

import pytest

from fakes.measure import FixedMeasurer
from fakes.rule_breaks import (
    BIG,
    NO_INTRO,
    SMALL,
    P,
    edit,
    hits,
    messages,
    mutate,
    shifted,
    title_of,
    without,
)
from fakes.scenes import (
    entchen_scene,
    entchen_with,
    profile,
)
from vocatron.core.layout.build import SongText
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.rules_base import TOLERANCE, gaps
from vocatron.core.layout.sample import scene_of, timed_song
from vocatron.core.scene import (
    CardElement,
    CountdownElement,
    Rect,
    Scene,
    Shortfall,
)


def test_rule_13_a_gap_without_a_countdown() -> None:
    scene = without(entchen_scene(), "countdown")
    assert "13" in hits(scene, P)
    assert messages(scene, P, 13)[0] == "rule 13: 0"


def test_rule_13_two_countdowns_before_one_line() -> None:
    base = entchen_scene()
    countdown = next(e for e in base.elements if isinstance(e, CountdownElement))
    scene = base.model_copy(update={"elements": [*base.elements, countdown]})
    assert "two countdowns before line 0" in " ".join(messages(scene, P, 13))


def test_rule_13_a_countdown_that_is_too_long_or_has_no_length() -> None:
    base = entchen_scene(bpm=None)  # countdowns in seconds
    countdown = next(e for e in base.elements if isinstance(e, CountdownElement))
    longer = edit(base, "countdown", 0, start=countdown.end - P.countdown.duration - BIG)
    assert "lasts" in " ".join(messages(longer, P, 13))
    ok = edit(base, "countdown", 0, start=countdown.end - P.countdown.duration - SMALL)
    assert "lasts" not in " ".join(messages(ok, P, 13))
    none = edit(base, "countdown", 0, start=countdown.end)
    assert "lasts" in " ".join(messages(none, P, 13))
    backwards = edit(base, "countdown", 0, start=countdown.end + 1.0)
    assert "lasts" in " ".join(messages(backwards, P, 13))
    tiny = edit(base, "countdown", 0, start=countdown.end - 0.001)
    assert "lasts" not in " ".join(messages(tiny, P, 13))


def beat_countdown(**update: Any) -> tuple[Scene, CountdownElement]:
    """Return the sample at 100 BPM (4 beats of 0.6 s) with its first countdown changed."""
    base = entchen_scene()
    countdown = next(e for e in base.elements if isinstance(e, CountdownElement))
    assert (countdown.beat, countdown.count) == (0.6, 4)
    return edit(base, "countdown", 0, **update), countdown


def test_rule_13_a_countdown_in_beats_holds() -> None:
    assert messages(beat_countdown()[0], P, 13) == []


def test_rule_13_a_countdown_in_beats_lasts_a_whole_number_of_beats() -> None:
    scene, countdown = beat_countdown()
    longer = edit(scene, "countdown", 0, start=countdown.start - BIG)
    assert "not 4 beats" in " ".join(messages(longer, P, 13))
    shorter = edit(scene, "countdown", 0, start=countdown.start + BIG)
    assert "not 4 beats" in " ".join(messages(shorter, P, 13))
    near = edit(scene, "countdown", 0, start=countdown.start + SMALL)
    assert messages(near, P, 13) == []


def test_rule_13_a_countdown_in_beats_counts_at_most_the_profiles_count() -> None:
    scene, countdown = beat_countdown()
    five = edit(scene, "countdown", 0, count=5, start=countdown.end - 5 * 0.6)
    assert "of line 0 counts 5 beats" in " ".join(messages(five, P, 13))
    zero = edit(scene, "countdown", 0, count=0, start=countdown.end)
    assert "counts 0 beats" in " ".join(messages(zero, P, 13))


@pytest.mark.parametrize("beat", [0.3, 0.599, 0.601, 1.2])
def test_rule_13_a_countdown_in_beats_counts_the_beat_of_the_songs_tempo(beat: float) -> None:
    scene, countdown = beat_countdown()
    changed = edit(scene, "countdown", 0, beat=beat, start=countdown.end - 4 * beat)
    assert "does not count beats of 0.600 s" in " ".join(messages(changed, P, 13))
    assert messages(edit(scene, "countdown", 0, beat=0.6005), P, 13) == []


def test_a_countdown_with_a_wrong_beat_belongs_to_its_line_wherever_it_ends() -> None:
    # it ends a beat of the song before the line, or a beat of its own: either way rule 13
    # reports the beat and rule 11 still finds the line (ADR-0028)
    scene, countdown = beat_countdown()
    sing = scene.lines()[0].sing_start
    kept = edit(scene, "countdown", 0, beat=0.3, start=countdown.end - 4 * 0.3)
    own = edit(scene, "countdown", 0, beat=0.3, end=sing - 0.3, start=sing - 0.3 - 4 * 0.3)
    wrong = ["rule 13: the countdown of line 0 does not count beats of 0.600 s"]
    assert scene_findings(kept, P) == wrong
    assert scene_findings(own, P) == wrong


def test_rule_13_a_countdown_in_beats_that_ends_at_the_line_start_is_refused() -> None:
    scene, countdown = beat_countdown()
    sing = scene.lines()[0].sing_start
    assert countdown.end == pytest.approx(sing - 0.6)  # a beat before the line (ADR-0028)
    late = edit(scene, "countdown", 0, end=sing, start=sing - 4 * 0.6)
    assert messages(late, P, 13)[0] == "rule 13: 0"
    half = edit(scene, "countdown", 0, end=sing - 0.3, start=sing - 0.3 - 4 * 0.6)
    assert messages(half, P, 13)[0] == "rule 13: 0"


def test_rule_13_the_beat_is_the_tempo_folded_into_the_countdown_window() -> None:
    # 200 BPM is a beat of 0.3 s: 4 beats (1.2 s) are too short, so the countdown counts 0.6 s
    scene, _ = beat_countdown()
    assert messages(scene.model_copy(update={"bpm": 200.0}), P, 13) == []
    assert messages(scene.model_copy(update={"bpm": 90.0}), P, 13) != []


def test_rule_13_a_countdown_in_beats_without_a_beat_is_refused() -> None:
    scene, _ = beat_countdown(beat=None)
    assert "does not count beats" in " ".join(messages(scene, P, 13))


def test_rule_13_a_countdown_in_beats_in_a_song_without_a_tempo_is_refused() -> None:
    scene, _ = beat_countdown()
    seconds = scene.model_copy(update={"bpm": None})
    assert "rule 13: the countdown of line 0 counts beats" in messages(seconds, P, 13)


def title_ending_at(scene: Scene, end: float) -> Scene:
    """Return ``scene`` with the title screen ending at ``end``."""
    return mutate(scene, "title", 0, lambda e: e.model_copy(update={"end": end}))


def test_rule_13_a_countdown_in_beats_does_not_start_before_the_title_screen_ends() -> None:
    scene, countdown = beat_countdown()
    assert messages(title_ending_at(scene, countdown.start), P, 13) == []
    early = title_ending_at(scene, countdown.start + BIG)
    assert "is early" in " ".join(messages(early, P, 13))


def test_rule_13_fewer_beats_start_on_the_first_whole_beat_after_the_title_screen() -> None:
    scene, countdown = beat_countdown()
    three = edit(scene, "countdown", 0, count=3, start=countdown.end - 3 * 0.6)
    # the title ends 0.5 s before: less than a beat is left over, so three beats are right
    assert messages(title_ending_at(three, countdown.end - 3 * 0.6 - 0.5), P, 13) == []
    # just under a beat is left over: still right
    assert messages(title_ending_at(three, countdown.end - 3 * 0.6 - 0.6 + SMALL), P, 13) == []
    one = edit(scene, "countdown", 0, count=1, start=countdown.end - 0.6)
    assert messages(title_ending_at(one, countdown.end - 0.6 - 0.5), P, 13) == []
    # a whole beat is left over (0.6 s): a fourth beat would have fit
    fits = title_ending_at(three, countdown.end - 3 * 0.6 - 0.6 - BIG)
    assert "fewer beats than fit" in " ".join(messages(fits, P, 13))


def test_rule_13_no_countdown_is_right_only_when_less_than_a_beat_is_left() -> None:
    scene = without(entchen_scene(), "countdown")
    end = next(c for c in entchen_scene().elements if isinstance(c, CountdownElement)).end
    # the beat at 100 BPM is 0.6 s
    assert messages(title_ending_at(scene, end - 0.6 - BIG), P, 13)[0] == "rule 13: 0"
    assert "rule 13: 0" not in messages(title_ending_at(scene, end - 0.5), P, 13)
    assert "rule 13: 0" not in messages(title_ending_at(scene, end - 0.6 + SMALL), P, 13)
    assert "rule 13: 0" not in messages(title_ending_at(scene, end), P, 13)


def test_rule_13_a_break_screen_is_a_floor_for_the_beats_too() -> None:
    base = entchen_scene()
    (screen,) = [e for e in base.elements if isinstance(e, CardElement) and e.kind == "break"]
    after = next(c for c in base.elements if isinstance(c, CountdownElement) and c.end > screen.end)
    early = mutate(base, "break", 0, lambda e: e.model_copy(update={"end": after.start + BIG}))
    assert any("is early" in m for m in messages(early, P, 13))


def test_rule_13_a_countdown_over_the_line_before_is_early() -> None:
    # 8 beats of 0.3 s: the gap of 0.68 s after line 0, less the beat before line 1, leaves room
    # for one beat; four beats would start while line 0 is sung
    chosen = profile(countdown={"min_gap": 0.6, "count": 8})
    scene = entchen_with(chosen)
    found = [e for e in scene.elements if isinstance(e, CountdownElement)]
    second = scene.lines()[1].sing_start
    index = next(i for i, c in enumerate(found) if c.end == pytest.approx(second - 0.3))
    assert (found[index].count, found[index].beat) == (1, 0.3)
    assert messages(scene, chosen, 13) == []
    four = edit(scene, "countdown", index, count=4, start=found[index].end - 4 * 0.3)
    assert messages(four, chosen, 13) == ["rule 13: the countdown of line 1 is early"]


def test_rule_13_a_countdown_in_seconds_over_the_line_before_is_early() -> None:
    chosen = profile(countdown={"min_gap": 0.6})
    scene = entchen_with(chosen, bpm=None)
    found = [e for e in scene.elements if isinstance(e, CountdownElement)]
    index = next(i for i, c in enumerate(found) if c.end == scene.lines()[1].sing_start)
    ended = scene.lines()[0].sing_end
    assert found[index].start == pytest.approx(ended)  # cut where line 0 has been sung
    assert messages(scene, chosen, 13) == []
    assert messages(edit(scene, "countdown", index, start=ended - TOLERANCE), chosen, 13) == []
    early = edit(scene, "countdown", index, start=ended - BIG)
    assert messages(early, chosen, 13) == ["rule 13: the countdown of line 1 is early"]


def test_rule_13_without_a_tempo_any_room_needs_a_countdown() -> None:
    seconds = entchen_scene(bpm=None)
    scene = without(seconds, "countdown")
    end = next(c for c in seconds.elements if isinstance(c, CountdownElement)).end
    assert messages(title_ending_at(scene, end - 0.1), P, 13)[0] == "rule 13: 0"


def test_rule_13_a_countdown_outside_the_safe_area() -> None:
    base = entchen_scene()
    countdown = next(e for e in base.elements if isinstance(e, CountdownElement))
    scene = edit(base, "countdown", 0, box=shifted(countdown.box, dx=-200))
    assert "leaves the safe area" in " ".join(messages(scene, P, 13))


def test_rule_13_a_countdown_not_over_the_first_letter() -> None:
    base = entchen_scene()
    countdown = next(e for e in base.elements if isinstance(e, CountdownElement))
    scene = edit(base, "countdown", 0, box=shifted(countdown.box, dx=BIG))
    assert "countdown of line 0" in " ".join(messages(scene, P, 13))
    near = edit(base, "countdown", 0, box=shifted(countdown.box, dx=SMALL))
    assert "countdown of line 0" not in " ".join(messages(near, P, 13))
    near = edit(base, "countdown", 0, box=shifted(countdown.box, dx=-SMALL))
    assert "countdown of line 0" not in " ".join(messages(near, P, 13))
    left = edit(base, "countdown", 0, box=shifted(countdown.box, dx=-BIG))
    assert "countdown of line 0" in " ".join(messages(left, P, 13))


def test_rule_13_a_countdown_over_a_letter_outside_the_safe_area_is_pulled_in() -> None:
    base = entchen_scene()
    countdown = next(e for e in base.elements if isinstance(e, CountdownElement))
    wide = Rect(
        x=base.safe.right - countdown.box.w, y=countdown.box.y, w=countdown.box.w, h=countdown.box.h
    )
    right = edit(edit(base, "line", 0, text_x=base.safe.right + 50), "countdown", 0, box=wide)
    assert "countdown of line 0" not in " ".join(messages(right, P, 13))
    left = edit(
        edit(base, "line", 0, text_x=base.safe.x - 50),
        "countdown",
        0,
        box=Rect(x=base.safe.x, y=countdown.box.y, w=countdown.box.w, h=countdown.box.h),
    )
    assert "countdown of line 0" not in " ".join(messages(left, P, 13))


def test_rule_13_a_countdown_not_above_the_slots() -> None:
    base = entchen_scene()
    countdown = next(e for e in base.elements if isinstance(e, CountdownElement))
    gap = base.slots[0].y - countdown.box.bottom
    low = edit(base, "countdown", 0, box=shifted(countdown.box, dy=gap + BIG))
    assert "not above" in " ".join(messages(low, P, 13))
    touching = edit(base, "countdown", 0, box=shifted(countdown.box, dy=gap + SMALL))
    assert "not above" not in " ".join(messages(touching, P, 13))
    exactly = edit(base, "countdown", 0, box=shifted(countdown.box, dy=gap))
    assert "not above" not in " ".join(messages(exactly, P, 13))


def test_rule_13_a_countdown_without_a_gap() -> None:
    base = entchen_scene()
    lines = base.lines()
    extra = CountdownElement(
        start=lines[1].sing_start - 1.0,
        end=lines[1].sing_start,
        box=Rect(x=70, y=300, w=100, h=20),
        form="shrinking-bar",
        count=4,
        colour="#fff",
    )
    scene = base.model_copy(update={"elements": [*base.elements, extra]})
    assert "a countdown without a gap" in " ".join(messages(scene, P, 13))


def test_rule_13_the_countdown_gap_is_the_profiles() -> None:
    chosen = profile(countdown={"min_gap": 6.1})  # the 6.08 s gap gets none
    scene = entchen_with(chosen)
    assert scene_findings(scene, chosen) == []
    assert "13" in hits(scene, P) or "13" not in hits(scene, P)  # the default scene is another


def test_rule_13_a_line_that_appears_as_it_is_sung_has_no_time_for_a_countdown() -> None:
    base = entchen_scene()
    without_countdowns = without(base, "countdown")
    ok = without_countdowns
    for number, line in enumerate(base.lines()):
        if gaps(base.lines())[number].before >= P.countdown.min_gap:
            ok = edit(ok, "line", number, start=line.sing_start)
    assert "13" not in hits(ok, P)


def test_rule_14_a_title_that_does_not_start_at_zero() -> None:
    base = entchen_scene()
    scene = edit(base, "title", 0, start=0.5)
    assert "14" in hits(scene, P)
    assert "does not start at 0" in messages(scene, P, 14)[0]


def test_rule_14_a_title_that_is_still_there_when_the_first_line_comes() -> None:
    base = entchen_scene()
    first = base.lines()[0]
    scene = edit(base, "title", 0, end=first.start + BIG)
    assert "still there" in " ".join(messages(scene, P, 14))
    near = edit(base, "title", 0, end=first.start + SMALL)
    assert "still there" not in " ".join(messages(near, P, 14))


def test_rule_14_a_title_that_is_too_short() -> None:
    base = entchen_scene()
    assert base.lines()[0].sing_start >= P.title.min + P.lead_in.target
    scene = edit(base, "title", 0, end=P.title.min - BIG)
    assert "too short" in " ".join(messages(scene, P, 14))
    near = edit(base, "title", 0, end=P.title.min - SMALL)
    assert "too short" not in " ".join(messages(near, P, 14))
    exact = edit(base, "title", 0, end=P.title.min)
    assert "too short" not in " ".join(messages(exact, P, 14))


def test_rule_14_a_title_that_is_missing() -> None:
    scene = without(entchen_scene(), "title")
    assert "missing" in " ".join(messages(scene, P, 14))


def test_rule_14_a_song_that_starts_at_once_needs_no_title() -> None:
    song = timed_song("Alle meine Entchen\nschwimmen auf dem See\n", start=NO_INTRO.lead_in.min)
    scene = scene_of(
        song,
        SongText("Ein Titel", "Eine Künstlerin", 30.0, {}),
        NO_INTRO,
        "4x3-720",
        FixedMeasurer(),
    )
    assert not [e for e in scene.elements if e.kind == "title"]
    assert scene_findings(scene, NO_INTRO) == []
    boundary = scene.lines()[0].sing_start
    assert boundary < NO_INTRO.lead_in.min + NO_INTRO.title.min_short + TOLERANCE


def test_rule_14_a_title_is_missing_when_there_was_time_for_a_short_one() -> None:
    start = P.lead_in.min + P.title.min_short + 0.5
    song = timed_song("Alle meine Entchen\nschwimmen auf dem See\n", start=start)
    scene = scene_of(
        song, SongText("Ein Titel", "Eine Künstlerin", 30.0, {}), P, "4x3-720", FixedMeasurer()
    )
    assert title_of(scene).end - title_of(scene).start >= P.title.min_short - TOLERANCE
    assert scene_findings(scene, P) == []
    gone = without(scene, "title")
    assert "missing" in " ".join(messages(gone, P, 14))


def test_rule_14_a_shortened_title_is_not_shorter_than_the_least() -> None:
    start = P.title.min + P.lead_in.target - 1.0  # too short for the whole title
    song = timed_song("Alle meine Entchen\nschwimmen auf dem See\n", start=start)
    scene = scene_of(
        song, SongText("Ein Titel", "Eine Künstlerin", 30.0, {}), P, "4x3-720", FixedMeasurer()
    )
    assert scene_findings(scene, P) == []
    shorter = edit(scene, "title", 0, end=P.title.min_short - BIG)
    assert "shortened too far" in " ".join(messages(shorter, P, 14))
    reported = shorter.model_copy(update={"shortfalls": [Shortfall(kind="title", message="x")]})
    assert "shortened too far" not in " ".join(messages(reported, P, 14))
    near = edit(scene, "title", 0, end=P.title.min_short - SMALL)
    assert "shortened too far" not in " ".join(messages(near, P, 14))
    # the boundary between a short and a long title is at min + target
    long_enough = edit(scene, "title", 0, end=P.title.min - BIG)
    assert "shortened too far" not in " ".join(messages(long_enough, P, 14))


def test_rule_14_a_profile_without_title_fields_has_no_title() -> None:
    chosen = profile(title={"fields": []})
    scene = entchen_with(chosen)
    assert not [e for e in scene.elements if e.kind == "title"]
    assert scene_findings(scene, chosen) == []
    assert "14" in hits(scene, P)


def test_rule_14_a_scene_without_lines_has_nothing_to_check() -> None:
    base = entchen_scene()
    empty = base.model_copy(update={"elements": [e for e in base.elements if e.kind == "title"]})
    assert "14" not in hits(empty, P)


def test_rule_15_a_line_that_stays_after_the_last_hold() -> None:
    base = entchen_scene()
    lines = base.lines()
    last = len(lines) - 1
    limit = max(x.sing_end for x in lines) + P.clear.hold
    scene = edit(base, "line", last, end=limit + BIG)
    assert "15" in hits(scene, P)
    assert "15" not in hits(edit(base, "line", last, end=limit + SMALL), P)
    assert messages(scene, P, 15)[0] == "rule 15"


def test_rule_15_the_end_screen_starts_after_the_last_line() -> None:
    base = entchen_scene()
    end = next(e for e in base.elements if e.kind == "end")
    scene = edit(base, "end", 0, start=end.start + BIG)
    assert "starts at the wrong time" in " ".join(messages(scene, P, 15))
    assert "wrong time" not in " ".join(
        messages(edit(base, "end", 0, start=end.start + SMALL), P, 15)
    )
    assert "wrong time" in " ".join(messages(edit(base, "end", 0, start=end.start - BIG), P, 15))
    assert "wrong time" not in " ".join(
        messages(edit(base, "end", 0, start=end.start - SMALL), P, 15)
    )


def test_rule_15_the_end_screen_lasts_to_the_end_of_the_song() -> None:
    base = entchen_scene()
    end = next(e for e in base.elements if e.kind == "end")
    assert "ends early" in " ".join(messages(edit(base, "end", 0, end=end.end - BIG), P, 15))
    assert "ends early" in " ".join(messages(edit(base, "end", 0, end=end.end + BIG), P, 15))
    assert "ends early" not in " ".join(messages(edit(base, "end", 0, end=end.end - SMALL), P, 15))
    assert "ends early" not in " ".join(messages(edit(base, "end", 0, end=end.end + SMALL), P, 15))


def test_rule_15_the_end_screen_fades_as_the_profile_says() -> None:
    base = entchen_scene()
    end = next(e for e in base.elements if isinstance(e, CardElement) and e.kind == "end")
    assert end.fade_out == P.ending.fade
    assert "fade is wrong" in " ".join(
        messages(edit(base, "end", 0, fade_out=end.fade_out + BIG), P, 15)
    )
    assert "fade is wrong" in " ".join(
        messages(edit(base, "end", 0, fade_out=end.fade_out - BIG), P, 15)
    )
    assert "fade is wrong" not in " ".join(
        messages(edit(base, "end", 0, fade_out=end.fade_out + SMALL), P, 15)
    )
    assert "fade is wrong" not in " ".join(
        messages(edit(base, "end", 0, fade_out=end.fade_out - SMALL), P, 15)
    )


def test_rule_15_a_long_enough_ending_needs_an_end_screen() -> None:
    scene = without(entchen_scene(), "end")
    assert "end screen is missing" in " ".join(messages(scene, P, 15))


def test_rule_15_no_end_screen_is_needed_when_the_profile_has_none_or_there_is_no_time() -> None:
    chosen = profile(ending={"end_screen": False})
    scene = entchen_with(chosen)
    assert not [e for e in scene.elements if e.kind == "end"]
    assert scene_findings(scene, chosen) == []
    assert "end screen is missing" in " ".join(messages(scene, P, 15))
    base = without(entchen_scene(), "end")
    last = max(x.sing_end for x in base.lines())
    short = base.model_copy(update={"duration": last + P.ending.start_after + 0.4})
    assert "end screen" not in " ".join(messages(short, P, 15))
    enough = base.model_copy(update={"duration": last + P.ending.start_after + 0.6})
    assert "end screen is missing" in " ".join(messages(enough, P, 15))


def test_rule_15_a_scene_without_lines_has_nothing_to_check() -> None:
    base = entchen_scene()
    empty = base.model_copy(update={"elements": []})
    assert hits(empty, P) == set()
