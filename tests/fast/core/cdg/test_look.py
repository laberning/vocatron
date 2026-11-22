"""Stage 1: the CD+G profile made from a look, and the fallback steps (ADR-0029)."""

import pytest
from pydantic import JsonValue

from fakes.scenes import builtin_profile
from vocatron.core.cdg.look import COARSE_WIPE, cdg_profile, cdg_section, fit_steps
from vocatron.core.colour import round_12bit
from vocatron.core.profiles.model import CLASSIC_PROFILES, SINGER_KEYS, Profile

SAFE = 192


def look(name: str = "two-line-turns", **overrides: JsonValue) -> Profile:
    return builtin_profile(name, **overrides)


def test_the_pixel_sizes_become_shares_of_the_safe_area() -> None:
    video = look()
    section = cdg_section(video)
    made = cdg_profile(video)
    assert made.font.size == pytest.approx(section.font_px / SAFE)
    assert made.font.min_size == pytest.approx(section.min_font_px / SAFE)
    assert made.edge.width * made.font.size * SAFE == pytest.approx(section.edge_px)
    assert made.slots == section.slots


def test_the_look_may_use_fewer_slots_and_a_thicker_edge_on_cdg() -> None:
    made = cdg_profile(look("full-page", cdg={"slots": 4, "edge_px": 2, "font_px": 20}))
    assert made.slots == 4
    assert made.edge.width * 20 == pytest.approx(2)


def test_the_shadow_and_the_fade_are_always_dropped() -> None:
    made = cdg_profile(look(shadow={"offset": 0.1}, ending={"fade": 2.0}))
    assert made.shadow.offset == 0.0 and made.ending.fade == 0.0
    assert made.padding(1.0) == made.edge.width  # the layout makes no room for a shadow


def test_colours_are_rounded_to_12_bits_and_an_override_wins() -> None:
    video = look(
        colours={"singer1": {"sung": "#3a9bfe", "unsung": "#fefefe"}},
        cdg={"colours": {"singer1": {"unsung": "#f0a"}, "background": "#003"}},
        background="#010101",
    )
    made = cdg_profile(video)
    assert made.colours.singer1.sung == "#3399ff"  # rounded
    assert made.colours.singer1.unsung == "#ff00aa"  # overridden: #rgb
    assert made.colours.singer1.edge == "#000000"
    assert made.background == "#000033"
    assert made.colours.singer2 == video.colours.singer2  # 12-bit colours stay as they are


@pytest.mark.parametrize("name", CLASSIC_PROFILES)
def test_the_built_in_looks_show_their_video_colours_rounded_and_nothing_else(name: str) -> None:
    video = look(name)
    made = cdg_profile(video)
    assert made.background == round_12bit(video.background)
    for key in (*SINGER_KEYS, "group"):
        for part in ("unsung", "sung", "edge"):
            wanted = round_12bit(getattr(getattr(video.colours, key), part))
            assert getattr(getattr(made.colours, key), part) == wanted, f"{key}.{part}"


def test_everything_else_is_the_video_look_and_the_video_look_is_not_changed() -> None:
    video = look("blue-page")
    before = video.model_dump()
    made = cdg_profile(video)
    assert video.model_dump() == before
    changed = {"slots", "font", "edge", "shadow", "ending", "colours", "background", "lead_in"}
    for key in before:
        if key not in changed:
            assert getattr(made, key) == getattr(video, key), key
    assert made.mode == "page" and made.page == video.page and made.countdown == video.countdown


def test_a_look_without_a_cdg_section_has_no_cdg_profile() -> None:
    video = look(cdg=None)
    with pytest.raises(ValueError, match="has no cdg section"):
        cdg_profile(video)


def test_the_steps_raise_the_lead_in_minimum_and_then_coarsen_the_wipe() -> None:
    video = look()  # lead-in 1 / 3 / 5 s, wipe 3
    steps = fit_steps(video)
    assert [(s.number, s.lead_min, s.lead_target, s.wipe_columns) for s in steps] == [
        (0, 1.0, 3.0, 3),
        (1, 3.0, 3.0, 3),
        (2, 5.0, 5.0, 3),
        (3, 5.0, 5.0, COARSE_WIPE),
    ]
    made = cdg_profile(video, steps[2])
    assert (made.lead_in.min, made.lead_in.target, made.lead_in.max) == (5.0, 5.0, 5.0)
    assert cdg_profile(video, steps[0]).lead_in == video.lead_in
    assert cdg_profile(video).lead_in == video.lead_in  # no step: as declared


def test_a_step_that_would_repeat_the_one_before_is_left_out() -> None:
    same = look(lead_in={"min": 3.0, "target": 3.0, "max": 3.0}, cdg={"wipe_columns": 6})
    assert [s.name for s in fit_steps(same)] == ["as declared"]
    target_is_max = look(lead_in={"min": 1.0, "target": 5.0, "max": 5.0})
    assert [s.lead_min for s in fit_steps(target_is_max)] == [1.0, 5.0, 5.0]
    assert [s.wipe_columns for s in fit_steps(target_is_max)] == [3, 3, 6]


def test_the_steps_are_the_same_for_the_same_profile() -> None:
    assert fit_steps(look()) == fit_steps(look())
    assert [s.number for s in fit_steps(look())] == list(range(4))


def test_a_page_look_gets_a_step_that_turns_its_pages_line_by_line_right_after_the_look() -> None:
    page = look("blue-page")
    steps = fit_steps(page)
    assert [(s.name, s.page_turn) for s in steps[:2]] == [
        ("as declared", "page"),
        ("line by line", "line"),
    ]
    assert steps[1].lead_min == steps[0].lead_min  # the same timing, only the page turn changes
    assert steps[1].wipe_columns == steps[0].wipe_columns
    assert all(s.page_turn == "line" for s in steps[1:])  # the later steps keep it
    assert [s.number for s in steps] == list(range(len(steps)))


def test_the_step_sets_page_turn_in_the_cdg_profile_and_the_look_as_declared_keeps_it() -> None:
    page = look("blue-page")
    steps = fit_steps(page)
    assert cdg_profile(page).page.turn == "page"  # no step: as declared
    assert cdg_profile(page, steps[0]).page.turn == "page"
    assert all(cdg_profile(page, step).page.turn == "line" for step in steps[1:])
    assert page.page.turn == "page"  # the video look is not changed


def test_line_looks_get_no_line_by_line_step_and_keep_their_page_turn() -> None:
    for name in ("two-line-turns", "one-line-preview", "four-line-stack", "three-line"):
        steps = fit_steps(look(name))
        assert "line by line" not in [s.name for s in steps]
        assert {s.page_turn for s in steps} == {"page"}
        assert cdg_profile(look(name), steps[-1]).page.turn == "page"


def test_a_page_look_that_declares_line_turns_has_no_extra_step() -> None:
    declared = look("blue-page", page={"turn": "line"})
    steps = fit_steps(declared)
    assert "line by line" not in [s.name for s in steps]
    assert {s.page_turn for s in steps} == {"line"}


def test_the_line_step_is_left_out_when_nothing_else_differs_and_it_is_the_only_one() -> None:
    same = look(
        "blue-page", lead_in={"min": 3.0, "target": 3.0, "max": 3.0}, cdg={"wipe_columns": 6}
    )
    assert [(s.name, s.page_turn) for s in fit_steps(same)] == [
        ("as declared", "page"),
        ("line by line", "line"),
    ]
