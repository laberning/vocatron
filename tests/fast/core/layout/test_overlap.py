"""Stage 1: two lines sung at once are shown side by side and wipe together (ADR-0054)."""

from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import JsonValue

from conformance.scene_rules import check_scene
from fakes.measure import FixedMeasurer
from fakes.phrases import line as sung
from fakes.resources import FakeResources
from fakes.rule_breaks import CP, edit, hits, messages
from fakes.scenes import entchen_with
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.phrases import Phrase
from vocatron.core.layout.place import (
    Run,
    Stack,
    Times,
    falls_back,
    groups,
    kept_lead_in,
    lyric_runs,
    pair_runs,
    place,
    stacked,
    units,
)
from vocatron.core.lyrics.document import SingerInfo, Voice
from vocatron.core.profiles.model import BUILTIN_PROFILES, Profile, parse_profile
from vocatron.core.scene import LineElement, Scene

RULE_TIMING: dict[str, JsonValue] = {
    "lead_in": {"min": 1.0, "target": 2.5, "max": 3.0},
    "clear": {"hold": 1.5, "replace_after": 0.33},
}


def look(name: str, overrides: dict[str, JsonValue] | None = None) -> Profile:
    text = FakeResources().builtin_profile(name) or ""
    return parse_profile(name, text, {**RULE_TIMING, **(overrides or {})})


TWO_SLOTS = look("two-line-turns")
THREE_SLOTS = look("three-line")
STACK = look("four-line-stack")
FRAME = (960, 720)
FIRST, SECOND = 1, 2


def times(*spans: tuple[float, float]) -> list[Times]:
    return [Times(start, end) for start, end in spans]


def scene_of(phrases: list[Phrase], profile: Profile) -> Scene:
    info = SongText("Titel", "Künstler", 300.0, {1: SingerInfo(name="Anna")})
    scene = layout(phrases, info, profile, FRAME, FixedMeasurer())
    check_scene(scene, profile)
    return scene


def by_text(scene: Scene) -> dict[str, LineElement]:
    return {line.text: line for line in scene.lines()}


# ---------------------------------------------------------------- pairs


def runs(
    spans: list[Times], voices: list[Voice], parts: list[int], profile: Profile = THREE_SLOTS
) -> list[Run]:
    return pair_runs(spans, voices, parts, profile)


def test_two_lines_of_different_voices_that_overlap_are_a_pair_first_voice_on_top() -> None:
    spans = times((10, 14), (12, 16), (20, 24))
    assert runs(spans, [1, 2, 1], [0, 0, 0]) == [(0, 1)]


def test_the_second_voice_may_start_first_and_the_first_voice_still_stands_on_top() -> None:
    assert runs(times((10, 16), (12, 14)), [2, 1], [0, 0]) == [(1, 0)]


def test_lines_that_only_touch_or_share_a_voice_are_not_a_pair() -> None:
    assert runs(times((10, 14), (14, 16)), [1, 2], [0, 0]) == []
    assert runs(times((10, 14), (12, 16)), [1, 1], [0, 0]) == []


def test_a_second_voice_line_over_two_first_voice_lines_is_paired_with_the_first() -> None:
    spans = times((10, 12), (11, 20), (14, 16))
    assert runs(spans, [1, 2, 1], [0, 0, 0]) == [(0, 1)]


def test_a_split_line_is_paired_with_all_its_rows_whichever_voice_it_has() -> None:
    # the first voice's line has two rows: one starts before the second voice's, one after
    spans = times((10, 12), (11, 16), (12, 14))
    assert runs(spans, [1, 2, 1], [0, 0, 1]) == [(0, 2, 1)]
    # the second voice's line has two rows
    spans = times((10, 16), (11, 13), (13, 15))
    assert runs(spans, [1, 2, 2], [0, 0, 1]) == [(0, 1, 2)]
    both = times((10, 12), (11, 13), (12, 14), (13, 15))
    assert runs(both, [1, 2, 1, 2], [0, 0, 1, 1], STACK) == [(0, 2, 1, 3)]


def test_a_pair_with_a_line_of_another_lyric_line_between_its_lines_is_not_formed() -> None:
    # the second row of the first voice's lyric line is sung between the second voice's line and
    # the first voice's next line, which would be its pair
    spans = times((6.0, 6.3), (6.0, 7.5), (6.3, 6.6), (6.6, 7.2))
    assert runs(spans, [1, 2, 1, 1], [0, 0, 1, 0], TWO_SLOTS) == []
    assert runs(spans, [1, 2, 1, 1], [0, 0, 1, 0], STACK) == [(0, 2, 1)]  # room for the first pair


def test_a_pair_that_needs_more_rows_than_the_stack_has_is_not_formed() -> None:
    spans = times((10, 12), (11, 16), (12, 14))
    assert runs(spans, [1, 2, 1], [0, 0, 1], TWO_SLOTS) == []
    both = times((10, 12), (11, 13), (12, 14), (13, 15))
    assert runs(both, [1, 2, 1, 2], [0, 0, 1, 1], THREE_SLOTS) == []


def test_the_rows_of_a_unit_are_found_among_the_lines_of_the_other_voice() -> None:
    assert units([0, 0, 1, 1, 0], [1, 2, 1, 2, 1]) == [(0, 2), (1, 3), (4,)]
    assert units([0, 1, 0], None) == [(0, 1), (2,)]
    assert units([0, 2, 0], None) == [(0,), (1,), (2,)]  # a part that does not follow its line


def test_lyric_runs_are_the_split_lines_that_fit_the_slots() -> None:
    assert lyric_runs([0, 1, 0, 0, 1, 2], None, 3) == {
        0: (0, 1),
        1: (0, 1),
        3: (3, 4, 5),
        4: (3, 4, 5),
        5: (3, 4, 5),
    }
    assert lyric_runs([0, 1, 2, 3, 0], None, 3) == {}  # more parts than slots: a slot each
    assert lyric_runs([0, 1, 0, 1], None, 2) == {}  # two slots take turns
    assert lyric_runs([0, 0, 1], [1, 2, 1], 4) == {0: (0, 2), 2: (0, 2)}


def test_a_pair_is_due_when_the_earlier_first_row_starts_and_stacks_the_first_voice_on_top() -> (
    None
):
    spans = times((10, 16), (12, 14))
    stack = Stack(spans, [2, 1], [0, 0], THREE_SLOTS)
    assert stack.due == [10, 10]
    assert stacked([0, 1], {0: (1, 0), 1: (1, 0)}) == [1, 0]
    assert stacked([0, 1], {0: (0, 1), 1: (0, 1)}) == [0, 1]
    # the later rows keep their own start
    split = Stack(times((10, 12), (11, 16), (12, 14)), [1, 2, 1], [0, 0, 1], THREE_SLOTS)
    assert split.due == [10, 10, 12]


def test_stacked_puts_a_pair_where_its_first_line_is_and_leaves_the_other_lines() -> None:
    assert stacked([0, 1, 2], {1: (2, 1), 2: (2, 1)}) == [0, 2, 1]
    assert stacked([0, 1, 2], {}) == [0, 1, 2]
    assert stacked([0, 1, 2, 3], {0: (0, 2, 1), 1: (0, 2, 1), 2: (0, 2, 1)}) == [0, 2, 1, 3]


# ---------------------------------------------------------------- line mode


def test_the_second_voice_line_takes_the_slot_below_and_both_appear_together() -> None:
    spans = times((10, 14), (12, 16))
    first, second = place(spans, 7.0, THREE_SLOTS, [0, 0], [1, 2])
    assert (first.slot, second.slot) == (0, 1)
    assert first.show == second.show == pytest.approx(7.0)  # before either starts


def test_a_second_voice_line_that_starts_first_still_goes_below() -> None:
    second, first = place(times((10, 16), (12, 14)), 7.0, THREE_SLOTS, [0, 0], [2, 1])
    assert (first.slot, second.slot) == (0, 1)
    assert first.show <= 10 and second.show <= 10


def test_two_slots_also_hold_a_pair_with_the_second_voice_first() -> None:
    second, first = place(times((10, 16), (12, 14)), 7.0, TWO_SLOTS, [0, 0], [2, 1])
    assert (first.slot, second.slot) == (0, 1)


def test_the_later_line_of_a_pair_appears_by_the_time_the_earlier_starts() -> None:
    # the first voice's slot is free at 3, before its mate starts at 3.5: it does not wait
    spans = times((0, 3), (3.5, 6.5), (5, 6))
    placed = place(spans, 0.0, TWO_SLOTS, [0, 0, 0], [2, 2, 1])
    assert [p.slot for p in placed] == [0, 1, 0]
    assert placed[2].show == pytest.approx(3.0)


def test_a_pair_with_the_second_voice_first_takes_the_rows_that_suit_its_order() -> None:
    # the slots from the top fit the first voice above the second; one row lower would not
    spans = times((0, 0.6), (2.1, 8.1), (4, 4.6))
    placed = place(spans, 0.0, THREE_SLOTS, [0, 0, 0], [2, 2, 1])
    assert [p.slot for p in placed] == [0, 1, 0]


def test_two_slots_are_both_taken_by_a_pair_and_the_next_line_takes_the_first_to_end() -> None:
    spans = times((10, 14), (12, 18), (19, 21))
    placed = place(spans, 7.0, TWO_SLOTS, [0, 0, 0], [1, 2, 1])
    assert [p.slot for p in placed] == [0, 1, 0]
    assert placed[2].show >= spans[0].end  # its slot was free when it appeared


def test_a_slot_is_never_reused_while_its_line_is_sung() -> None:
    # a second voice line sung over the next first voice line; the one after takes the next slot
    spans = times((10, 12), (11, 20), (14, 16), (17, 19))
    placed = place(spans, 7.0, THREE_SLOTS, [0] * 4, [1, 2, 1, 1])
    assert [p.slot for p in placed[:2]] == [0, 1]
    assert placed[2].slot == 2  # the next free slot
    assert placed[3].slot == 0
    for later, line in enumerate(placed):
        for earlier in range(later):
            if placed[earlier].slot == line.slot:
                assert line.show >= spans[earlier].end - 1e-9


def test_a_song_with_one_voice_is_placed_as_before() -> None:
    spans = times((10, 12), (12.5, 15), (15.5, 18), (18.5, 20))
    assert place(spans, 7.5, THREE_SLOTS, [0] * 4, [1] * 4) == place(spans, 7.5, THREE_SLOTS)


def test_a_pair_whose_slots_are_still_sung_breaks_up_and_each_line_takes_a_slot() -> None:
    # the second voice still sings in the top slot as the first voice of the pair starts
    spans = times((0, 6), (1, 2.5), (2.5, 4), (4, 10), (6.5, 9.5))
    voices: list[Voice] = [2, 1, 1, 1, 2]
    parts = [0, 0, 1, 0, 0]
    assert pair_runs(spans, voices, parts, TWO_SLOTS) == [(3, 4)]
    placed = place(spans, 0.0, TWO_SLOTS, parts, voices)
    assert [p.slot for p in placed] == [0, 1, 1, 1, 0]  # a slot each: the one free first
    assert placed[3].show <= spans[3].start
    assert placed[4].show == pytest.approx(spans[0].end)  # not before the top slot is sung


def test_a_pair_breaks_up_even_when_its_slot_is_sung_only_a_little_longer() -> None:
    # the lower part of the split line still sings 0.1 s into the pair
    spans = times((0.5, 0.8), (0.8, 1.1), (1, 4), (1.6, 4.6))
    placed = place(spans, 0.0, TWO_SLOTS, [0, 1, 0, 0], [1, 1, 2, 1])
    assert [p.slot for p in placed] == [0, 1, 0, 1]


def test_a_split_line_whose_slots_are_still_sung_takes_a_slot_per_part() -> None:
    # the second voice sings in the middle slot as the split first-voice line starts
    spans = times((3.5, 6.5), (5, 8), (7, 7.5), (7.5, 8))
    placed = place(spans, 0.0, THREE_SLOTS, [0, 0, 0, 1], [1, 2, 1, 1])
    assert [p.slot for p in placed] == [0, 1, 2, 0]  # not two neighbouring free slots
    assert placed[3].show >= spans[0].end


def test_the_lines_after_a_split_line_that_broke_up_take_slots_as_before() -> None:
    spans = times((1.5, 7.5), (3.5, 5.5), (5.5, 7.5), (7.5, 9.5), (10.5, 16.5))
    placed = place(spans, 0.0, THREE_SLOTS, [0, 0, 1, 2, 0], [2, 1, 1, 1, 2])
    assert [p.slot for p in placed] == [0, 1, 2, 1, 0]


LONG = " ".join(["lala"] * 6)  # too wide for one row: split into two parts


@pytest.mark.parametrize(
    ("phrases", "profile", "broken"),
    [
        (
            [
                sung(0, 6, "aa bb", voice=2, tint="2"),
                sung(1, 4, LONG),
                sung(4, 10, "cc dd"),
                sung(6.5, 9.5, "ee ff", voice=2, tint="2"),
            ],
            TWO_SLOTS,
            ("cc dd", "ee ff"),
        ),
        (
            [
                sung(3.5, 6.5, "aa bb"),
                sung(5, 8, "cc dd", voice=2, tint="2"),
                sung(7, 8, LONG),
            ],
            THREE_SLOTS,
            None,
        ),
    ],
)
def test_the_rules_hold_when_a_pair_or_a_split_line_breaks_up(
    phrases: list[Phrase], profile: Profile, broken: tuple[str, str] | None
) -> None:
    scene = scene_of(phrases, profile)  # check_scene: rule 10 accepts a slot each
    if broken is not None:
        found = by_text(scene)
        assert found[broken[0]].slot != found[broken[1]].slot - 1  # not first voice above
    else:
        parts = [line.slot for line in scene.lines() if line.text.startswith("lala")]
        assert len(parts) == 2 and parts[1] != parts[0] + 1  # not in neighbouring slots


def second(start: float, end: float, text: str) -> Phrase:
    return sung(start, end, text, voice=SECOND, tint="2")


@pytest.mark.parametrize(
    "phrases",
    [
        [second(0.5, 1.1, "aa"), sung(1.5, 6.5, "bb"), second(2.6, 4.1, "cc")],
        [
            second(1, 4, "aa"),
            sung(4, 4.6, "bb"),
            second(5.5, 10.5, "cc"),
            sung(6.1, 11.1, "dd"),
        ],
        [
            sung(1.5, 2.1, "aa"),
            sung(2.1, 5.1, "bb"),
            second(6, 7.5, "cc"),
            second(7.5, 12.5, "dd"),
            sung(8.1, 11.1, "ee"),
        ],
    ],
)
def test_rule_10_accepts_a_pair_in_the_best_rows_whichever_voice_comes_first(
    phrases: list[Phrase],
) -> None:
    scene_of(phrases, THREE_SLOTS)  # check_scene: rule 10 judges the pair from its top row


def test_rule_10_finds_a_pair_apart_or_in_rows_that_free_later() -> None:
    scene = scene_of(
        [
            sung(1.5, 2.1, "aa"),
            sung(2.1, 5.1, "bb"),
            second(6, 7.5, "cc"),
            second(7.5, 12.5, "dd"),
            sung(8.1, 11.1, "ee"),
        ],
        THREE_SLOTS,
    )
    assert [line.slot for line in scene.lines()] == [0, 1, 2, 1, 0]
    apart = edit(scene, "line", 4, slot=2)  # the first voice, placed after its mate
    assert "rule 10: line 4 is not next to the line it is sung with" in messages(
        apart, THREE_SLOTS, 10
    )
    lower = edit(edit(scene, "line", 4, slot=1), "line", 3, slot=2)
    assert messages(lower, THREE_SLOTS, 10) == ["rule 10: line 3"]


# ---------------------------------------------------------------- blocks


def test_a_pair_belongs_to_one_group_that_starts_with_the_pair_when_it_does_not_fit() -> None:
    spans = times((10, 12), (14, 18), (15, 19), (22, 24))
    assert groups(spans, [0] * 4, STACK, [1, 1, 2, 1]) == [0, 1, 1, 2]
    assert groups(spans, [0] * 4, STACK) == [0, 0, 1, 1]  # without voices as before


def test_a_pair_fills_a_group_to_its_last_line() -> None:
    spans = times((10, 12), (14, 18), (15, 19), (22, 24))
    blocks_of_three = STACK.model_copy(update={"block": 3, "slots": 6})
    assert groups(spans, [0] * 4, blocks_of_three, [1, 1, 2, 1]) == [0, 0, 0, 1]


def test_a_pair_in_a_block_stands_first_voice_above_second_voice_both_wiping_at_once() -> None:
    scene = scene_of(
        [sung(10, 14, "aa bb", voice=1), sung(11, 15, "cc dd", voice=2, tint="2")], STACK
    )
    lines = by_text(scene)
    top, bottom = lines["aa bb"], lines["cc dd"]
    assert (top.slot, bottom.slot) == (0, 1)
    assert top.start == bottom.start <= 10 - 1.0
    assert top.sing_start < bottom.sing_end and bottom.sing_start < top.sing_end
    assert bottom.voice == 2 and bottom.singers == "1"  # no duet: nobody else is marked
    assert bottom.colours.sung == STACK.singer_colours("2").sung
    assert top.voice == 1


def test_the_second_voice_first_is_still_below_in_a_block() -> None:
    scene = scene_of(
        [sung(10, 16, "cc dd", voice=2, tint="2"), sung(12, 14, "aa bb", voice=1)], STACK
    )
    lines = by_text(scene)
    assert lines["aa bb"].slot + 1 == lines["cc dd"].slot
    assert lines["aa bb"].start == lines["cc dd"].start


def test_a_second_voice_line_over_two_first_voice_lines_keeps_its_block() -> None:
    scene = scene_of(
        [
            sung(10, 12, "aa bb", voice=1),
            sung(11, 20, "cc dd", voice=2, tint="2"),
            sung(14, 16, "ee ff", voice=1),
            sung(21, 23, "gg hh", voice=1),
        ],
        STACK,
    )
    lines = by_text(scene)
    assert lines["cc dd"].end >= 20  # not replaced while sung
    assert lines["ee ff"].slot // 2 != lines["cc dd"].slot // 2  # the next free block
    assert lines["gg hh"].start >= lines["cc dd"].end or lines["gg hh"].slot != lines["cc dd"].slot


def test_second_voice_lines_that_overlap_nothing_are_laid_out_like_any_other() -> None:
    phrases = [sung(10 + 3 * i, 12 + 3 * i, f"l{i} la") for i in range(6)]
    voiced = [p if i % 2 else replace(p, voice=2, tint="2") for i, p in enumerate(phrases)]
    plain, other = scene_of(phrases, STACK), scene_of(voiced, STACK)
    place_of = [(x.slot, x.start, x.end) for x in plain.lines()]
    assert place_of == [(x.slot, x.start, x.end) for x in other.lines()]
    assert [x.voice for x in other.lines()] == [2, 1, 2, 1, 2, 1]
    assert all(line.voice == 1 for line in plain.lines())


# ---------------------------------------------------------------- colours and looks


def test_a_second_voice_line_without_its_own_mark_is_drawn_in_the_colour_of_singer_2() -> None:
    scene = scene_of([sung(10, 14, "aa bb"), sung(11, 15, "cc dd", voice=2, tint="2")], THREE_SLOTS)
    lines = by_text(scene)
    assert lines["cc dd"].colours.sung == THREE_SLOTS.singer_colours("2").sung
    assert lines["aa bb"].colours.sung == THREE_SLOTS.singer_colours("1").sung


def test_a_second_voice_line_with_its_own_mark_keeps_it() -> None:
    scene = scene_of([sung(10, 14, "aa bb"), sung(11, 15, "cc dd", "3", voice=2)], THREE_SLOTS)
    assert by_text(scene)["cc dd"].singers == "3"


def test_rule_16_lets_a_second_voice_line_have_the_colours_of_singer_2() -> None:
    base = entchen_with(CP)
    two = CP.singer_colours("2")
    tinted = base.lines()[0].colours.model_copy(update={"unsung": two.unsung, "edge": two.edge})
    assert "16" not in hits(edit(base, "line", 0, colours=tinted, voice=SECOND), CP)
    assert "16" in hits(edit(base, "line", 0, colours=tinted), CP)  # not a first-voice line


def test_lines_that_only_touch_are_not_noted_as_sung_at_once() -> None:
    phrases = [sung(10, 14, "aa bb"), sung(14, 16, "cc dd", voice=2, tint="2")]
    scene = scene_of(phrases, look("lyric-scroll"))
    assert not [s for s in scene.shortfalls if s.kind == "overlap"]


@pytest.mark.parametrize(("pairs", "said"), [(10, ""), (11, " and 2 more")])
def test_the_note_names_at_most_twenty_lines(pairs: int, said: str) -> None:
    phrases = [
        line
        for i in range(pairs)
        for line in (sung(10 * i, 10 * i + 4, "aa"), second(10 * i + 2, 10 * i + 6, "bb"))
    ]
    scene = scene_of(phrases, look("lyric-scroll"))
    [note] = [s.message for s in scene.shortfalls if s.kind == "overlap"]
    listed = ", ".join(str(n) for n in range(1, 21))
    assert note == f"lines {listed}{said} sung at once are shown one after the other in this look"


@pytest.mark.parametrize("name", ["lyric-scroll", "one-line-preview", "full-page", "blue-page"])
def test_the_other_looks_show_the_lines_one_after_the_other_and_say_so(name: str) -> None:
    profile = look(name)
    phrases = [sung(10, 14, "aa bb"), sung(12, 16, "cc dd", voice=2, tint="2")]
    scene = scene_of(phrases, profile)
    notes = [s for s in scene.shortfalls if s.kind == "overlap"]
    assert [n.message for n in notes] == [
        "lines 1, 2 sung at once are shown one after the other in this look"
    ]
    lines = scene.lines()
    assert all(a.sing_end <= b.sing_start + 1e-9 for a, b in zip(lines, lines[1:], strict=False))


def test_the_look_with_places_for_both_says_nothing_about_overlaps() -> None:
    scene = scene_of([sung(10, 14, "aa bb"), sung(12, 16, "cc dd", voice=2)], STACK)
    assert not [s for s in scene.shortfalls if s.kind == "overlap"]


# ---------------------------------------------------------------- every look that stacks

STACKING = [
    name
    for name in BUILTIN_PROFILES
    if (p := look(name)).mode == "line" and p.slots >= 2  # two slots hold a pair
]
SYLLABLES = st.sampled_from(["la", "lo", "ti", "ra", "so"])


@st.composite
def duet(draw: st.DrawFn) -> list[Phrase]:
    """Two voices that overlap fully, partly and not at all, with long breaks and long lines."""
    phrases: list[Phrase] = []
    for voice in (FIRST, SECOND):
        clock = draw(st.sampled_from([0.0, 1.0, 3.0, 8.0]))
        for _ in range(draw(st.integers(0, 6))):
            start = clock + draw(st.sampled_from([0.0, 0.5, 1.5, 3.0, 5.5, 12.0]))
            length = draw(st.sampled_from([0.6, 1.5, 3.0, 5.0, 9.0]))
            words = draw(st.integers(1, 12))
            text = " ".join(draw(SYLLABLES) for _ in range(words))
            phrases.append(
                sung(
                    start, start + length, text, voice=voice, tint="2" if voice == SECOND else None
                )
            )
            clock = start + length
    return sorted(phrases, key=lambda phrase: phrase.start)


@settings(max_examples=60, deadline=None)
@given(phrases=duet(), name=st.sampled_from(STACKING), slots=st.sampled_from([None, 2, 3, 4, 6]))
def test_the_rules_hold_for_two_voices_in_every_look_that_stacks(
    phrases: list[Phrase], name: str, slots: int | None
) -> None:
    profile = look(name)
    if slots is not None and profile.block == 1:
        size = min(0.12, 0.8 / (1.34 * slots + 0.3))
        profile = profile.model_copy(
            update={
                "slots": slots,
                "font": profile.font.model_copy(update={"size": size, "min_size": 0.66 * size}),
            }
        )
    scene = scene_of(phrases, profile)
    assert not [s for s in scene.shortfalls if s.kind == "overlap"]
    for index, line in enumerate(scene.lines()):  # a slot is never refilled while it is sung
        for other in scene.lines()[:index]:
            if other.slot == line.slot and other.row == line.row == 0:
                assert other.sing_end <= line.start + 0.01 or other.end <= line.start + 0.01


@settings(max_examples=40, deadline=None)
@given(phrases=duet(), name=st.sampled_from(["lyric-scroll", "full-page", "one-line-preview"]))
def test_the_other_looks_hold_their_rules_with_two_voices(phrases: list[Phrase], name: str) -> None:
    scene = scene_of(phrases, look(name))
    lines = scene.lines()
    assert all(a.sing_end <= b.sing_start + 0.01 for a, b in zip(lines, lines[1:], strict=False))


# ---------------------------------------------------------------- lines of several rows


def by_slot(scene: Scene) -> list[tuple[str, int]]:
    """The first letters of every row with its slot, top to bottom."""
    return sorted(((x.text[:2], x.slot) for x in scene.lines()), key=lambda found: found[1])


def test_a_split_second_voice_line_is_shown_below_the_first_voice_line_in_every_row() -> None:
    scene = scene_of([sung(10, 18, "aa bb"), second(11, 20, LONG)], look("three-line"))
    lines = scene.lines()
    assert by_slot(scene) == [("aa", 0), ("la", 1), ("la", 2)]
    assert lines[0].start == lines[1].start <= 10 - 1.0  # both on screen before either starts
    assert lines[2].start >= lines[1].start  # the second row appears when its slot is free


def test_a_split_first_voice_line_stands_above_the_second_voice_line_it_is_sung_with() -> None:
    scene = scene_of([sung(10, 20, LONG), second(11, 14, "aa bb")], THREE_SLOTS)
    assert by_slot(scene) == [("la", 0), ("la", 1), ("aa", 2)]


def test_two_split_lines_sung_at_once_take_four_rows_in_order() -> None:
    phrases = [sung(10, 20, LONG), second(11, 21, LONG.replace("lala", "lolo"))]
    scene = scene_of(phrases, STACK)
    assert by_slot(scene) == [("la", 0), ("la", 1), ("lo", 2), ("lo", 3)]
    assert len({x.start for x in scene.lines()}) == 1  # blocks turn together


def test_a_pair_of_three_rows_takes_the_rows_of_both_blocks_while_it_is_sung() -> None:
    scene = scene_of([sung(10, 18, "aa bb"), second(11, 20, LONG)], STACK)
    assert by_slot(scene) == [("aa", 0), ("la", 1), ("la", 2)]  # the second block is taken too
    lines = scene.lines()
    assert len({x.start for x in lines}) == 1 and len({x.end for x in lines}) == 1


def test_the_next_group_waits_for_both_blocks_of_a_wide_pair() -> None:
    phrases = [sung(10, 18, "aa bb"), second(11, 20, LONG), sung(21, 23, "cc dd")]
    lines = scene_of(phrases, STACK).lines()
    after = [x for x in lines if x.text == "cc dd"][0]
    assert after.start >= 20 - 0.01  # not while the second voice's second row is sung
    assert {x.end for x in lines if x is not after} == {after.start}  # the pair goes as a whole


def test_a_group_that_starts_before_a_wide_pair_is_sung_turns_line_by_line() -> None:
    phrases = [sung(10, 18, "aa bb"), second(11, 22, LONG), sung(19, 21, "cc dd")]
    lines = scene_of(phrases, STACK).lines()  # check_scene: rule 23 judges the fallback
    after = [x for x in lines if x.text == "cc dd"][0]
    assert after.slot not in {x.slot for x in lines if x is not after and x.sing_end > 19}


def test_a_pair_that_needs_more_rows_than_the_look_has_is_shown_line_by_line() -> None:
    phrases = [sung(10, 20, LONG), second(11, 21, LONG.replace("lala", "lolo"))]
    scene = scene_of(phrases, THREE_SLOTS)  # four rows do not fit three slots: no pair
    assert not [s for s in scene.shortfalls if s.kind == "overlap"]
    lines = scene.lines()
    for index, line in enumerate(lines):
        for other in lines[:index]:
            if other.slot == line.slot:
                assert other.sing_end <= line.start + 0.01 or other.end <= line.start + 0.01


def test_a_line_turning_alone_takes_a_sung_row_of_a_wide_pair_block_by_block() -> None:
    # a wide pair (the first voice above the two rows of the second), then first-voice lines
    # sung while the second voice's long second row is: they turn line by line
    spans = times((10, 16), (14, 15.8), (15.8, 23), (16, 18.2), (18.2, 22), (22, 23.5))
    voices: list[Voice] = [1, 2, 2, 1, 1, 1]
    placed = place(spans, 0.0, STACK, [0, 0, 1, 0, 0, 0], voices)
    assert [p.slot for p in placed[:4]] == [0, 1, 2, 3]
    # not the slot of the line sung just before (lead-in 0) but the block whose rows are sung
    assert [p.slot for p in placed[4:]] == [0, 1]  # in reading order
    assert placed[4].show <= 18.2 - STACK.lead_in.min
    assert placed[4].show >= 16  # never while the row it replaces is sung
    assert placed[2].hide >= 23  # the second voice's row stays while it is sung


def test_the_rules_follow_a_line_turning_alone_into_the_sung_block_of_a_wide_pair() -> None:
    phrases = [
        sung(10, 17, "aa bb"),
        second(12, 23, LONG),  # two rows: from 12 and from 17.5
        sung(17.6, 19.8, "cc"),
        sung(19.8, 22, "dd"),
        sung(22, 23.5, "ee"),
    ]
    found = by_text(scene_of(phrases, STACK))  # check_scene: rule 23 judges the slots
    assert (found["dd"].slot, found["ee"].slot) == (0, 1)
    assert found["dd"].sing_start - found["dd"].start >= STACK.lead_in.min


@pytest.mark.parametrize("profile", [STACK, THREE_SLOTS], ids=["stack", "three"])
def test_a_line_sung_between_the_rows_of_two_lines_sung_at_once_takes_a_free_slot(
    profile: Profile,
) -> None:
    # the first voice's next line starts between the rows of the second voice's line
    phrases = [sung(10, 16, LONG), second(11, 22, LONG.replace("lala", "lolo")), sung(17, 21, "aa")]
    scene = scene_of(phrases, profile)  # check_scene: the rules hold
    lines = scene.lines()
    for index, line in enumerate(lines):  # a slot is never refilled while it is sung
        for other in lines[:index]:
            if other.slot == line.slot:
                assert other.sing_end <= line.start + 0.01 or other.end <= line.start + 0.01


# ---------------------------------------------------------------- groups and pairs, edges


def test_a_pair_of_more_than_two_rows_has_its_group_to_itself() -> None:
    big = STACK.model_copy(update={"block": 4, "slots": 8})
    # a pair of three rows would leave room for the next line, which still starts a group
    spans = times((10, 12), (10.5, 13), (13, 16), (20, 22), (21, 23))
    assert groups(spans, [0, 0, 1, 0, 0], big, [1, 2, 2, 1, 1]) == [0, 0, 0, 1, 1]
    spans = times((10, 12), (10.5, 16), (12, 14), (20, 22), (21, 23))  # the first voice split
    assert groups(spans, [0, 0, 1, 0, 0], big, [1, 2, 1, 1, 1]) == [0, 0, 0, 1, 1]


@pytest.mark.parametrize(
    ("spans", "parts", "voices", "expected"),
    [
        # a whole line, then a pair of three rows that would fill the group of four
        (
            times((5, 9.5), (10, 12), (10.5, 13), (13, 16), (16.5, 18)),
            [0, 0, 0, 1, 0],
            [1, 1, 2, 2, 1],
            [0, 1, 1, 1, 2],
        ),
        # three whole lines, then the pair
        (
            times((3, 4.5), (5, 6.5), (7, 9.5), (10, 12), (10.5, 13), (13, 16), (16.5, 18)),
            [0, 0, 0, 0, 0, 1, 0],
            [1, 1, 1, 1, 2, 2, 1],
            [0, 0, 0, 1, 1, 1, 2],
        ),
    ],
    ids=["after-one", "after-three"],
)
def test_no_line_joins_the_group_of_a_pair_of_many_rows_wherever_it_starts(
    spans: list[Times], parts: list[int], voices: list[Voice], expected: list[int]
) -> None:
    big = STACK.model_copy(update={"block": 4, "slots": 8})
    assert groups(spans, parts, big, voices) == expected


def test_a_pair_of_many_rows_turns_line_by_line_when_only_one_of_its_blocks_is_free() -> None:
    # a pair of whole lines in the top block, its second voice sung on while the first voice's
    # next line starts a pair with a split second-voice line, which needs both blocks
    spans = times((10, 12), (11, 20), (13, 25), (21, 23), (23, 26))
    voices: list[Voice] = [1, 2, 1, 2, 2]
    placed = place(spans, 0.0, STACK, [0, 0, 0, 0, 1], voices)
    assert placed[2].slot == 2  # the free block, at once, not after the top block is sung
    assert placed[2].show <= 13 - STACK.lead_in.min


def test_split_lines_that_are_not_paired_keep_their_own_groups_among_the_other_voice() -> None:
    two = STACK.model_copy(update={"block": 2, "slots": 2})  # no room for a pair of three rows
    spans = times((10, 12), (11, 13), (12, 14))
    assert groups(spans, [0, 0, 1], two, [1, 2, 1]) == [0, 1, 2]


def test_a_pair_needs_whole_blocks_of_room() -> None:
    odd = STACK.model_copy(update={"block": 2, "slots": 5})  # four slots in blocks
    spans = times((10, 12), (11, 16), (12, 14), (13, 15), (14, 18))
    assert pair_runs(spans, [1, 2, 1, 2, 2], [0, 0, 1, 1, 2], odd) == []  # five rows do not fit
    assert pair_runs(spans[:4], [1, 2, 1, 2], [0, 0, 1, 1], odd) == [(0, 2, 1, 3)]


def test_a_group_is_free_only_when_its_blocks_end_by_the_time_it_starts() -> None:
    assert falls_back([16.5, 16.5, 30, 30], 2, 16)  # a little late is late
    assert not falls_back([16.0, 16.0, 30, 30], 2, 16)
    assert falls_back([16.0, 16.0, 16.4, 30], 2, 16, 2)  # both blocks must end for two blocks
    assert not falls_back([16.0, 16.0, 16.0, 16.0], 2, 16, 2)


def test_a_group_falls_back_when_its_block_frees_late_while_the_other_voice_is_sung() -> None:
    lead = 1.0
    assert falls_back([12, 30, 15, 19.5], 2, 20, 1, lead)  # block 2 ends 0.5 s before, block 1 sung
    assert not falls_back([12, 30, 15, 19.5], 2, 20)  # no minimum lead-in asked
    assert not falls_back([12, 30, 15, 16], 2, 20, 1, lead)  # frees 4 s before: in time
    assert not falls_back([12, 14, 15, 19.5], 2, 20, 1, lead)  # no line sung in the other block
    assert falls_back([19.5, 19.5, 30, 30], 2, 20, 1, lead)  # the held block below the best one
    assert not falls_back([12, 30, 15, 19.0], 2, 20, 1, lead)  # exactly the minimum before: in time
    assert not falls_back([19.5] * 4, 2, 20, 2, lead)  # a group over every block has no other


def test_a_group_keeps_its_lead_in_only_while_a_line_of_the_other_voice_is_sung() -> None:
    ends = [12.0, 19.1, 15.0, 20.0, 21.0]
    voices: list[Voice] = [1, 2, 1, 1, 1]
    assert kept_lead_in(ends, voices, 4, 20, 1.0) == 1.0  # the second voice sung until 19.1
    assert kept_lead_in(ends, voices, 4, 20.2, 1.0) == 0.0  # it ends 1.1 s before: one voice
    assert kept_lead_in(ends, voices, 4, 20.1, 1.0) == 0.0  # exactly the minimum before
    assert kept_lead_in(ends, [1, 1, 1, 1, 1], 4, 20, 1.0) == 0.0  # only its own voice before
    assert kept_lead_in(ends, [1, 2, 1, 1, 2], 2, 13, 1.0) == 1.0  # the other voice of the group
    assert kept_lead_in(ends, voices, 1, 11, 1.0) == 1.0  # a second-voice group after the first
    assert kept_lead_in(ends, voices, 0, 10, 1.0) == 0.0  # nothing sung before
    assert kept_lead_in(ends, None, 4, 20, 1.0) == 0.0


def test_a_group_whose_block_frees_late_turns_line_by_line_next_to_the_other_voice() -> None:
    # the second voice holds the top block; the block below ends half a second before the next group
    spans = times((10, 12), (11, 30), (14, 15), (16, 19.5), (20, 21), (21, 22))
    voices: list[Voice] = [1, 2, 1, 1, 1, 1]
    placed = place(spans, 0.0, STACK, [0] * 6, voices)
    assert placed[4].slot == 0  # the slot that ended first, now
    assert placed[4].show <= 20 - STACK.lead_in.min
    assert placed[5].show <= 21 - STACK.lead_in.min
    one = place(spans, 0.0, STACK, [0] * 6)  # the same times in one voice: the block is awaited
    assert one[4].slot == 2
    assert one[4].show >= 19.5


# the second voice held the top block until 0.9 s before the group of 20 s; the first voice sings
# in the block below until that group starts
HELD_UNTIL_JUST_BEFORE = times(
    (10, 11), (10.5, 19.1), (11.5, 13), (13, 15), (15, 17), (17, 20), (20, 21), (21, 22)
)


def test_a_group_falls_back_when_the_other_voice_held_its_block_until_just_before() -> None:
    voices: list[Voice] = [1, 2, 1, 1, 1, 1, 1, 1]
    placed = place(HELD_UNTIL_JUST_BEFORE, 0.0, STACK, [0] * 8, voices)
    assert placed[6].show <= 20 - STACK.lead_in.min
    assert placed[7].show <= 21 - STACK.lead_in.min
    one = place(HELD_UNTIL_JUST_BEFORE, 0.0, STACK, [0] * 8)  # one voice: the block is awaited
    assert one[6].show >= 19.1


def test_the_rules_follow_a_group_that_falls_back_after_the_other_voice_held_its_block() -> None:
    words = ["aa", "bb", "cc", "dd", "ee", "ff", "gg", "hh"]
    phrases = [
        second(span.start, span.end, text) if index == 1 else sung(span.start, span.end, text)
        for index, (span, text) in enumerate(zip(HELD_UNTIL_JUST_BEFORE, words, strict=True))
    ]
    found = by_text(scene_of(phrases, STACK))  # check_scene: rule 23 judges the slots
    assert found["gg"].sing_start - found["gg"].start >= STACK.lead_in.min


@pytest.mark.parametrize("row", [0, 1, 2])
def test_rule_23_asks_every_row_of_a_wide_pair_to_go_when_the_next_group_appears(row: int) -> None:
    phrases = [sung(10, 18, "aa bb"), second(11, 20, LONG), sung(21, 23, "cc dd")]
    scene = scene_of(phrases, STACK)
    late = scene.lines()[row].end + 0.5  # one row of the pair stays after the next group came
    assert messages(edit(scene, "line", row, end=late), STACK, 23)
