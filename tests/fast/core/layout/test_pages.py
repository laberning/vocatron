"""Stage 1: page mode cuts the lines into pages and times them (rules 5, 9, 10, 11)."""

import itertools
import math
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from conformance.scene_rules import check_scene
from fakes.measure import FixedMeasurer
from fakes.phrases import line
from fakes.scenes import profile
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.pages import cut_pages, page_turn, place_pages
from vocatron.core.layout.phrases import Phrase, Turn
from vocatron.core.layout.place import Placement, Times, gaps
from vocatron.core.profiles.model import Page, Profile
from vocatron.core.scene import Scene

# fixed numbers, not whatever the shipped looks are tuned to
BASE = profile(
    mode="page",
    slots=4,
    lead_in={"min": 1.0, "target": 2.5, "max": 3.0},
    clear={"hold": 1.5, "replace_after": 0.33},
)
ONE = BASE.model_copy(update={"slots": 1})


def spans(*pairs: tuple[float, float]) -> list[Times]:
    return [Times(start, end) for start, end in pairs]


def run(*starts: float) -> list[Times]:
    """Lines of one second that start at ``starts``."""
    return spans(*((start, start + 1.0) for start in starts))


def pages_of(times: list[Times], chosen: Profile = BASE) -> list[tuple[int, int]]:
    return cut_pages(times, chosen)


def test_a_long_gap_always_ends_a_page() -> None:
    assert pages_of(run(10, 11.5, 20, 21.5)) == [(0, 2), (2, 4)]
    assert pages_of(run(10, 20, 30)) == [(0, 1), (1, 2), (2, 3)]
    assert pages_of(run(10, 16)) == [(0, 1), (1, 2)]  # exactly clear_after (5 s) is long


def test_a_run_gets_the_fewest_pages_cut_at_the_longest_pause() -> None:
    # pauses before lines 1 to 5: 0.3, 0.5, 0.4, 1.5, 0.3 s; up to four lines per page
    six = spans((10, 11), (11.3, 12.3), (12.8, 13.8), (14.2, 15.2), (16.7, 17.7), (18, 19))
    assert pages_of(six) == [(0, 4), (4, 6)]
    assert len(pages_of([*six, Times(19.2, 20)])) == 2  # seven lines still fit two pages
    assert len(pages_of(run(10, 12, 14, 16, 18, 20, 22, 24, 26))) == 3  # nine lines, three pages


def test_min_lines_is_kept_where_the_run_allows_it() -> None:
    # pauses before lines 1 to 4: 0.3, 0.5, 0.9, 2.0 s
    five = spans((10, 11), (11.3, 12.3), (12.8, 13.8), (14.7, 15.7), (17.7, 18.7))
    assert pages_of(five) == [(0, 4), (4, 5)]  # min_lines 1: the longest pause wins
    wanted = profile(mode="page", slots=4, page={"min_lines": 2})
    assert pages_of(five, wanted) == [(0, 3), (3, 5)]  # 3 + 2, cut at the longest pause that works
    assert pages_of(run(10), wanted) == [(0, 1)]  # a song of one line cannot have two


def test_the_earlier_cut_wins_a_tie() -> None:
    three = BASE.model_copy(update={"slots": 3})
    assert pages_of(run(10, 12, 14, 16), three) == [(0, 1), (1, 4)]  # equal pauses: cut early


def every_cutting(times: list[Times], chosen: Profile) -> list[tuple[int, int]] | None:
    """The best cutting by trying every allowed set of cuts in every run (the oracle)."""
    before = [silence.before for silence in gaps(times)]
    starts = [0, *(i for i in range(1, len(times)) if before[i] >= chosen.breaks.clear_after)]
    pages: list[tuple[int, int]] = []
    for first, end in zip(starts, [*starts[1:], len(times)], strict=True):
        allowed = [c for c in range(first + 1, end) if before[c] >= 0]
        ranked: list[tuple[tuple[int, int, float, tuple[int, ...]], list[tuple[int, int]]]] = []
        for count in range(len(allowed) + 1):
            for cuts in itertools.combinations(allowed, count):
                bounds = [first, *cuts, end]
                run_pages = list(itertools.pairwise(bounds))
                if all(b - a <= chosen.slots for a, b in run_pages):
                    small = sum(b - a < chosen.page.min_lines for a, b in run_pages)
                    worst = min((before[c] for c in cuts), default=math.inf)
                    ranked.append(((len(run_pages), small, -worst, cuts), run_pages))
        if not ranked:
            return None
        pages += min(ranked)[1]
    return pages


@settings(max_examples=300, deadline=None)
@given(
    silences=st.lists(st.sampled_from([-0.5, 0.0, 0.2, 0.5, 1.0, 6.0]), min_size=1, max_size=10),
    slots=st.integers(1, 6),
    low=st.integers(1, 6),
)
def test_the_cutting_is_the_best_of_every_allowed_cutting(
    silences: list[float], slots: int, low: int
) -> None:
    chosen = BASE.model_copy(update={"slots": slots, "page": Page(min_lines=min(low, slots))})
    times: list[Times] = []
    sung = 10.0
    for silence in silences:
        start = max(sung + silence, times[-1].start) if times else sung
        times.append(Times(start, start + 1.0))
        sung = max(sung, start + 1.0)
    expected = every_cutting(times, chosen)
    if expected is None:
        with pytest.raises(ValueError, match="do not fit pages"):
            cut_pages(times, chosen)
    else:
        assert cut_pages(times, chosen) == expected


def test_no_page_is_cut_between_lines_sung_at_once() -> None:
    overlapping = spans((10, 14), (12, 16), (17, 18), (17.5, 19))
    for slots in (2, 3):
        assert pages_of(overlapping, BASE.model_copy(update={"slots": slots})) == [(0, 2), (2, 4)]


def test_a_chain_of_overlaps_longer_than_the_slots_cannot_be_cut_into_pages() -> None:
    chain = spans((10, 12), (11.8, 14), (13.9, 16))  # lines are never merged (ADR-0018)
    with pytest.raises(ValueError, match="lines 0 to 2 do not fit pages of 2 lines"):
        cut_pages(chain, BASE.model_copy(update={"slots": 2}))


def slots_of(placed: list[Placement]) -> list[int]:
    return [p.slot for p in placed]


def test_a_song_without_lines_has_no_pages() -> None:
    assert place_pages([], 7.0, BASE) == []


def test_a_short_page_sits_centred_in_the_block() -> None:
    five = BASE.model_copy(update={"slots": 5})
    placed = place_pages(run(10, 12, 30), 7.0, five)
    assert slots_of(placed) == [1, 2, 2]  # two lines in five slots: one empty slot above
    assert slots_of(place_pages(run(10, 12, 14), 7.0, BASE)) == [0, 1, 2]  # half a slot high
    assert slots_of(place_pages(run(10, 12, 14, 16), 7.0, BASE)) == [0, 1, 2, 3]
    assert slots_of(place_pages(run(10, 12), 7.0, BASE)) == [1, 2]  # two in four: centred


def test_every_line_of_a_page_appears_and_goes_with_the_page() -> None:
    placed = place_pages(run(10, 11.5, 13, 20, 21.5), 7.0, BASE)
    assert [p.page for p in placed] == [0, 0, 0, 1, 1]
    assert {(p.show, p.hide) for p in placed[:3]} == {(7.0, 15.5)}
    assert len({(p.show, p.hide) for p in placed[3:]}) == 1
    assert placed[3].hide == pytest.approx(22.5 + 1.5)  # the last page: hold after the last line


@pytest.mark.parametrize(
    ("next_start", "turn"),
    [
        (22.5, 20.0),  # 2.5 s of silence: the page turns as soon as it has been sung
        (23.5, 21.0),  # 3.5 s: held a second, then the next page comes lead_in.target ahead
        (24.4, 21.5),  # 4.4 s: the hold (1.5 s) ends before the target lead-in is due
        (24.8, 21.8),  # 4.8 s: the page waits for lead_in.max, the screen stays full until then
    ],
)
def test_the_hold_gives_way_to_the_lead_in_target_of_the_next_page(
    next_start: float, turn: float
) -> None:
    first, second = place_pages(run(19, next_start), 7.0, ONE)
    assert second.show == pytest.approx(turn)
    assert first.hide == pytest.approx(turn)


def test_after_a_long_gap_the_page_clears_after_the_hold_and_the_next_one_comes_later() -> None:
    first, second = place_pages(run(19, 40), 7.0, ONE)
    assert first.hide == pytest.approx(20 + 1.5)
    assert second.show == pytest.approx(40 - 3.0)  # lead_in.max before it is sung
    first, second = place_pages(run(19, 25.5), 7.0, ONE)  # 5.5 s is a long gap
    assert (first.hide, second.show) == pytest.approx((21.5, 22.5))
    first, second = place_pages(run(19, 25), 7.0, ONE)  # exactly clear_after is long too
    assert (first.hide, second.show) == pytest.approx((21.5, 22.0))


def test_the_screen_is_never_empty_between_pages_in_a_short_gap() -> None:
    times = spans(
        (10, 11), (11.5, 12.5), (13, 14), (17.5, 18.5), (19, 20), (23.2, 24.2), (26.5, 27.5)
    )
    placed = place_pages(times, 7.0, BASE.model_copy(update={"slots": 3}))
    firsts = {p.page: p for p in reversed(placed)}
    assert len(firsts) == 3
    for number in range(2):
        assert firsts[number].hide == firsts[number + 1].show


def scene_of(phrases: list[Phrase], chosen: Profile = BASE) -> Scene:
    song = SongText("Titel", "Künstler", 120.0, {})
    built = layout(phrases, song, chosen, (960, 720), FixedMeasurer())
    check_scene(built, chosen)
    return built


def test_lines_of_two_singers_keep_their_own_colours_in_page_mode() -> None:
    scene = scene_of([line(10, 12, "la la", "1"), line(12.0, 14, "li li", "2")])
    first, second = scene.lines()
    assert (first.singers, second.singers) == ("1", "2")
    assert first.colours.unsung == BASE.colours.singer1.unsung
    assert second.colours.edge == BASE.colours.singer2.edge
    assert (first.page, second.page) == (0, 0)


def test_a_turn_inside_a_line_survives_page_mode() -> None:
    phrase = Phrase("1", line(10, 14, "la li lo lu").pieces, (Turn(2, "2"),))
    (only,) = scene_of([phrase]).lines()
    assert [(t.span, t.singers) for t in only.turns] == [(2, "2")]


def test_the_first_page_appears_with_the_title_and_the_lead_in_is_counted_per_page() -> None:
    scene = scene_of([line(20, 22), line(22.6, 24), line(40, 42)])
    first, second, third = scene.lines()
    assert first.start == second.start == pytest.approx(20 - BASE.lead_in.target)
    assert third.start == pytest.approx(40 - BASE.lead_in.max)
    assert scene.shortfalls == []


def test_a_page_turn_in_continuous_singing_reports_the_short_lead_in_of_its_first_line() -> None:
    chosen = BASE.model_copy(update={"slots": 2})
    scene = scene_of([line(20, 21), line(21.3, 22.3), line(22.9, 23.9), line(24.2, 25.2)], chosen)
    third = scene.lines()[2]
    assert third.start == pytest.approx(22.3)  # as soon as the page before has been sung
    assert [(s.kind, s.line) for s in scene.shortfalls] == [("lead-in", 2)]


# ----------------------------------------------- two rows over two slots (page.slot_per_row)

PER_ROW = profile(
    mode="page",
    slots=6,
    line_rows=2,
    page={"min_lines": 1, "slot_per_row": True},
    cdg={"slots": 6},
    font={"size": 0.1, "min_size": 0.07},
)
LONG = " ".join(["lala"] * 6)  # 29 characters: two rows at this size (26 fit in one)


def test_a_wrapped_line_takes_two_neighbouring_slots() -> None:
    placed = place_pages(run(10, 12, 14), 7.0, PER_ROW, rows=[2, 1, 2])
    assert slots_of(placed) == [0, 2, 3]  # five rows in six slots: one empty slot below
    scene = scene_of([line(10, 16, LONG), line(17, 19), line(20, 26, LONG)], PER_ROW)
    assert [(x.slot, x.row) for x in scene.lines()] == [(0, 0), (1, 1), (2, 0), (3, 0), (4, 1)]
    top, bottom = scene.lines()[:2]
    assert (top.start, top.end) == (bottom.start, bottom.end)
    assert top.box.inside(scene.slots[0]) and bottom.box.inside(scene.slots[1])  # a row a slot
    assert bottom.box.y >= top.box.bottom


def test_a_page_holds_at_most_slots_rows() -> None:
    rows = [2, 2, 2, 2]  # eight rows in a page of six: three lines, the longest pause before line 3
    four = spans((10, 11), (11.5, 12.5), (13, 14), (15.5, 16.5))
    assert cut_pages(four, PER_ROW, rows) == [(0, 3), (3, 4)]
    assert cut_pages(run(10, 11.5, 13), PER_ROW, [1, 1, 1]) == [(0, 3)]  # lines of one row: three
    short = PER_ROW.model_copy(update={"slots": 4})
    five = spans((10, 11), (11.5, 12.5), (13, 14), (15.5, 16.5), (17, 18))
    assert cut_pages(five, short, [2, 1, 1, 1, 1]) == [(0, 3), (3, 5)]  # four rows, then two


def test_a_wrapped_line_that_does_not_fit_starts_the_next_page() -> None:
    # five lines of one row leave one slot; the wrapped line needs two, so it starts the next page
    times = spans((10, 11), (11.5, 12.5), (13, 14), (14.5, 15.5), (16, 17), (19, 20))
    rows = [1, 1, 1, 1, 1, 2]
    assert cut_pages(times, PER_ROW, rows) == [(0, 5), (5, 6)]
    placed = place_pages(times, 7.0, PER_ROW, rows)
    assert [p.page for p in placed] == [0, 0, 0, 0, 0, 1]
    assert slots_of(placed)[-1] == 2  # the second page of two rows is centred in six slots


def test_a_short_page_of_rows_sits_centred() -> None:
    assert slots_of(place_pages(run(10, 12), 7.0, PER_ROW, rows=[2, 2])) == [1, 3]
    assert slots_of(place_pages(run(10), 7.0, PER_ROW, rows=[2])) == [2]  # two rows in six slots
    assert slots_of(place_pages(run(10, 12, 14), 7.0, PER_ROW, rows=[1, 1, 1])) == [1, 2, 3]
    assert slots_of(place_pages(run(10, 12), 7.0, PER_ROW, rows=[2, 2])) == [1, 3]


def test_a_line_of_two_rows_that_fits_no_page_cannot_be_cut() -> None:
    one = PER_ROW.model_copy(update={"slots": 1})
    with pytest.raises(ValueError, match="lines 0 to 0 do not fit pages of 1 rows"):
        cut_pages(run(10), one, [2])


def test_page_numbers_and_times_of_rows_follow_their_line() -> None:
    scene = scene_of([line(10, 16, LONG), line(17, 19, LONG), line(30, 36, LONG)], PER_ROW)
    pages = [(x.page, x.row, x.start, x.end) for x in scene.lines()]
    assert [p[:2] for p in pages] == [(0, 0), (0, 1), (0, 0), (0, 1), (1, 0), (1, 1)]
    assert pages[0][2:] == pages[1][2:] == pages[2][2:] == pages[3][2:]  # a page goes as a whole


def test_the_last_page_goes_when_the_end_screen_starts() -> None:
    times = run(10, 11.5)
    for hold, end_screen, expected in ((4.0, True, 13.5), (4.0, False, 16.5), (0.5, True, 13.0)):
        chosen = BASE.model_copy(
            update={
                "clear": BASE.clear.model_copy(update={"hold": hold}),
                "ending": BASE.ending.model_copy(
                    update={"start_after": 1.0, "end_screen": end_screen}
                ),
            }
        )
        placed = place_pages(times, 7.5, chosen)
        assert [p.hide for p in placed] == [pytest.approx(expected)] * 2


# ------------------------------------------------- pages that turn line by line (page.turn: line)

BY_LINE = BASE.model_copy(update={"page": Page(turn="line")})


def shows_hides(placed: list[Placement]) -> list[tuple[float, float]]:
    return [(round(p.show, 3), round(p.hide, 3)) for p in placed]


def test_pages_back_to_back_build_from_the_top_while_the_old_page_is_still_sung() -> None:
    times = run(10, 11, 12, 13, 14, 15, 16, 17)  # eight lines of a second, no pause
    assert cut_pages(times, BY_LINE) == [(0, 4), (4, 8)]
    placed = place_pages(times, 7.0, BY_LINE)
    assert slots_of(placed) == [0, 1, 2, 3, 0, 1, 2, 3]
    # a line of the new page appears 0.33 s after the line in its slot was sung, the old one goes
    assert shows_hides(placed[:4]) == [(7.0, 11.33), (7.0, 12.33), (7.0, 13.33), (7.0, 14.33)]
    assert [s for s, _ in shows_hides(placed[4:])] == [11.33, 12.33, 13.33, 14.33]
    assert (
        placed[4].show < times[4].start
    )  # the first line of the new page is there before it is sung
    assert [p.page for p in placed] == [0, 0, 0, 0, 1, 1, 1, 1]
    assert placed[-1].hide == pytest.approx(18.0 + 1.5)  # the last page goes after the hold


def test_a_line_never_appears_after_its_first_syllable_and_gives_way_to_the_lead_in_minimum() -> (
    None
):
    # four lines of 0.2 s, the fifth at 11.0 sits in slot 1, sung to 10.4: 0.33 s later is 10.73,
    # but the line wants to be there lead_in.min (1 s) ahead: it comes as soon as the slot is sung
    times = spans((10, 10.2), (10.2, 10.4), (10.4, 10.6), (10.6, 10.8), (11.0, 11.2))
    placed = place_pages(times, 7.0, BY_LINE)
    assert [p.page for p in placed] == [0, 0, 0, 0, 1]
    assert placed[4].show == pytest.approx(10.4)
    assert placed[1].hide == pytest.approx(10.4)
    for sung, p in zip(times, placed, strict=True):
        assert p.show <= sung.start


def test_the_first_line_of_the_new_page_appears_no_more_than_the_lead_in_maximum_ahead() -> None:
    times = spans((10, 11), (11, 12), (12, 13), (13, 14), (19.5, 20.5))
    placed = place_pages(times, 7.0, BASE.model_copy(update={"page": Page(turn="line")}))
    assert placed[4].show == pytest.approx(19.5 - BASE.lead_in.max)  # not at 11.33


def test_a_new_page_taller_than_the_old_one_fills_the_extra_slots_when_its_first_line_is_sung() -> (
    None
):
    times = spans((10, 11), (11.5, 12.5), (15.5, 16.5), (17, 18), (18.5, 19.5), (20, 21))
    assert cut_pages(times, BY_LINE) == [(0, 2), (2, 6)]
    placed = place_pages(times, 7.0, BY_LINE)
    assert slots_of(placed) == [1, 2, 0, 1, 2, 3]  # two lines in the middle, then four
    assert shows_hides(placed[2:])[0][0] == pytest.approx(12.5)  # slot 0: first line + lead max
    assert [s for s, _ in shows_hides(placed[2:])] == [12.5, 12.5, 12.83, 12.83]
    # the old lines go as the lines of their slots appear
    assert [h for _, h in shows_hides(placed[:2])] == [12.5, 12.83]


def test_an_old_line_whose_slot_the_new_page_does_not_use_goes_at_the_page_turn() -> None:
    times = spans((10, 11), (11, 12), (12, 13), (13, 14), (16, 17), (17, 18))
    placed = place_pages(times, 7.0, BY_LINE)
    assert slots_of(placed) == [0, 1, 2, 3, 1, 2]  # two lines of four slots sit in slots 1 and 2
    assert placed[4].show == pytest.approx(16 - BY_LINE.lead_in.max)  # the first line: max ahead
    assert placed[5].show == pytest.approx(13.33)  # the slot of line 2 (sung to 13) is free
    # slot 3 is not used again: its line goes at the whole-page turn; the lines before it go in
    # the order they were sung, none after a later one
    assert page_turn(14.0, 16.0, BY_LINE) == pytest.approx(14.0)
    assert [p.hide for p in placed[:4]] == [pytest.approx(h) for h in (13.0, 13.0, 13.33, 14.0)]
    assert min(p.hide for p in placed[:4]) >= placed[4].show  # the screen is never empty


def test_after_a_long_gap_the_whole_page_turns_as_before() -> None:
    times = run(10, 11, 12, 13, 30, 31)
    assert place_pages(times, 7.0, BY_LINE) == [replace(p) for p in place_pages(times, 7.0, BASE)]


def test_a_gap_of_exactly_clear_after_is_long_and_the_whole_page_turns() -> None:
    times = run(10, 11, 12, 13, 19, 20)  # 5.0 s between line 3 (sung to 14) and line 4
    placed = place_pages(times, 7.0, BY_LINE)
    assert placed == place_pages(times, 7.0, BASE)
    assert len({p.show for p in placed[4:]}) == 1


def test_a_long_gap_does_not_stop_later_pages_from_turning_line_by_line() -> None:
    times = run(10, 11, 30, 31, 32, 33, 34, 35, 36, 37)  # a long gap, then eight lines at once
    placed = place_pages(times, 7.0, BY_LINE)
    assert [p.page for p in placed] == [0, 0, 1, 1, 1, 1, 2, 2, 2, 2]
    assert len({p.show for p in placed[2:6]}) == 1  # after the long gap: the whole page turns
    assert placed[6].show < times[6].start  # the next page builds up while the old one is sung
    assert len({p.show for p in placed[6:]}) > 1


def test_a_page_look_that_turns_whole_pages_is_not_changed() -> None:
    times = run(10, 11, 12, 13, 14, 15, 16, 17)
    placed = place_pages(times, 7.0, BASE)
    assert len({(p.show, p.hide) for p in placed[:4]}) == 1  # a page appears and goes as a whole
    assert len({(p.show, p.hide) for p in placed[4:]}) == 1


def test_page_turn_is_the_one_rule_of_the_whole_page_turn() -> None:
    assert page_turn(20.0, 22.5, ONE) == pytest.approx(20.0)
    assert page_turn(20.0, 23.5, ONE) == pytest.approx(21.0)
    assert page_turn(20.0, 24.8, ONE) == pytest.approx(21.8)
    assert page_turn(20.0, 20.5, ONE) == pytest.approx(20.0)  # never after the page is sung...


@settings(max_examples=300, deadline=None)
@given(
    silences=st.lists(st.sampled_from([0.0, 0.2, 0.5, 1.0, 3.0, 6.0]), min_size=2, max_size=14),
    length=st.sampled_from([0.5, 1.0, 2.0]),
    slots=st.integers(1, 6),
)
def test_every_line_of_a_page_turning_line_by_line_appears_after_its_slot_is_sung_and_in_time(
    silences: list[float], length: float, slots: int
) -> None:
    chosen = BY_LINE.model_copy(update={"slots": slots})
    times: list[Times] = []
    sung = 10.0
    for silence in silences:
        start = max(sung + silence, times[-1].start) if times else sung
        times.append(Times(start, start + length))
        sung = max(sung, start + length)
    placed = place_pages(times, 7.0, chosen)
    for index, (sung_at, p) in enumerate(zip(times, placed, strict=True)):
        assert p.show <= sung_at.start + 1e-9  # never after its first syllable
        assert p.hide >= sung_at.end - 1e-9  # never before it is sung
        for earlier in range(index):
            before = placed[earlier]
            if before.slot == p.slot and before.page != p.page:
                assert before.hide <= p.show + 1e-9  # the slot is free when it appears
                assert p.show >= times[earlier].end - 1e-9  # and the old line has been sung
    shows = [p.show for p in placed]
    assert shows == sorted(shows)  # lines appear in the order they are sung
