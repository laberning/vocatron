"""Stage 1: checking a profile without rendering: loads, colours, fit, layout rules (ADR-0019)."""

from dataclasses import replace
from typing import Any

import pytest
from pydantic import JsonValue

from fakes.measure import FixedMeasurer
from fakes.raster import FakeRasteriser
from fakes.resources import FakeResources
from vocatron.core.cdg import check as cdg_check
from vocatron.core.cdg.fit import Fit
from vocatron.core.measure import TextMeasurer
from vocatron.core.profiles import check as profiles_check
from vocatron.core.profiles.check import check_profile
from vocatron.core.profiles.model import BUILTIN_PROFILES, CLASSIC_PROFILES, Profile, parse_profile
from vocatron.core.scene import Scene, Shortfall
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser

RESOURCES = FakeResources()
CDG_TEXT = RESOURCES.builtin_profile("blue-page") or ""
TEXT = CDG_TEXT.replace("made_for_cdg: true", "made_for_cdg: false")  # the video checks only
REAL = PillowMeasurer(RESOURCES.font_file())


def problems(
    text: str, overrides: dict[str, JsonValue] | None = None, name: str = "blue-page"
) -> list[str]:
    return check_profile(
        "my/blue-page.yaml",
        text,
        expected_name=name,
        overrides=overrides or {},
        measurer=FixedMeasurer(),
        rasteriser=FakeRasteriser(),
    )


def row_of(text: str, start: str) -> int:
    return next(i for i, line in enumerate(text.splitlines(), 1) if line.startswith(start))


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
@pytest.mark.parametrize("real", [False, True], ids=["fixed", "real"])
def test_every_built_in_profile_passes_with_both_measurers(name: str, real: bool) -> None:
    text = RESOURCES.builtin_profile(name) or ""
    measurer = REAL if real else FixedMeasurer()
    # The video checks only: the CD+G check of every look runs with the real font in the
    # conformance kit (test_model_conformance), and its timing needs the shapes of the letters.
    # A video-only look has no cdg section to switch off.
    overrides: dict[str, JsonValue] = (
        {"cdg": {"made_for_cdg": False}} if name in CLASSIC_PROFILES else {}
    )
    assert (
        check_profile(
            f"{name}.yaml",
            text,
            expected_name=name,
            overrides=overrides,
            measurer=measurer,
            rasteriser=FakeRasteriser(),
        )
        == []
    )


def test_a_schema_error_names_line_and_column() -> None:
    (message,) = problems(TEXT.replace("slots: 4", "slots: 9", 1))
    assert message.startswith(f"my/blue-page.yaml:{row_of(TEXT, 'slots:')}:1: slots: ")


def test_a_contrast_problem_names_the_line_of_the_colour() -> None:
    bad = TEXT.replace('background: "#000055"', 'background: "#ffffff"')
    found = problems(bad)
    row = row_of(bad, "  singer1")
    assert any(
        m.startswith(f"my/blue-page.yaml:{row}:") and "colours.singer1.unsung: has contrast" in m
        for m in found
    )


def test_a_line_that_cannot_fit_names_the_line_of_min_size() -> None:
    big = TEXT.replace("size: 0.11", "size: 0.4").replace("min_size: 0.08", "min_size: 0.4")
    found = problems(big)
    row = row_of(big, "  min_size")
    assert found
    assert any(m.startswith(f"my/blue-page.yaml:{row}:3: font.min_size: ") for m in found)
    presets = {m.rsplit("(preset ", 1)[1].rstrip(")") for m in found if "font.min_size" in m}
    assert presets == {"4x3-720", "4x3-720-nvenc", "av1-720"}  # the wide frames have room


def test_a_wrong_name_is_reported_at_the_name() -> None:
    (message,) = problems(TEXT, name="mine")
    assert message.startswith(
        "my/blue-page.yaml:3:1: name: is 'blue-page', but the profile is 'mine'"
    )


def test_an_override_that_breaks_the_colours_is_named() -> None:
    found = problems(TEXT, {"colours": {"singer1": {"unsung": "#000066"}}})
    assert any(m.startswith("profile_overrides.colours.singer1.unsung") for m in found)


def test_a_broken_layout_rule_names_file_and_preset_only(monkeypatch: pytest.MonkeyPatch) -> None:

    def broken(scene: Scene, profile: Profile) -> list[str]:
        return ["rule 1: a box"]

    monkeypatch.setattr(profiles_check, "scene_findings", broken)
    found = problems(TEXT)
    assert "my/blue-page.yaml: preset 4x3-720, sample lyrics: rule 1: a box" in found
    assert len(found) == len(set(found))


def test_sung_and_unsung_too_alike_is_reported_at_the_singer() -> None:
    alike = TEXT.replace('sung: "#ff5a1f"', 'sung: "#fffffe"', 1)
    row = row_of(alike, "  singer1")
    message = "colours.singer1: sung and unsung colours are too alike to tell apart"
    assert f"my/blue-page.yaml:{row}:3: {message}" in problems(alike)


def test_a_sung_colour_that_does_not_show_the_wipe_is_reported_at_its_value() -> None:
    yellow = TEXT.replace('sung: "#ff5a1f"', 'sung: "#ffff00"', 1)
    row = row_of(yellow, "  singer1")
    column = yellow.splitlines()[row - 1].index(" sung:") + 2  # the key
    assert problems(yellow) == [
        f"my/blue-page.yaml:{row}:{column}: colours.singer1.sung: has contrast 1.07 with the "
        "unsung colour, too little to see the wipe"
    ]
    assert problems(TEXT) == []


LOOK = RESOURCES.builtin_profile("two-line-turns") or ""
LOOK_ROW = row_of(LOOK, "cdg:")


class WideMeasurer:
    """Text three times as wide as the fixed measurer says: a word that cannot be fitted."""

    def width(self, text: str, size: float) -> float:
        return 3 * FixedMeasurer().width(text, size)


ONE_STEP: dict[str, JsonValue] = {
    "lead_in": {"min": 1, "target": 1, "max": 1},
    "cdg": {"wipe_columns": 6},
}  # no fallback step to try after the first: the check of a bad look stays fast


def cdg_problems(
    text: str = LOOK,
    overrides: dict[str, JsonValue] | None = None,
    measurer: TextMeasurer | None = None,
) -> list[str]:
    """Check a look with the fakes (two-line-turns passes with them) and return the problems."""
    return check_profile(
        "my/look.yaml",
        text,
        expected_name="two-line-turns",
        overrides=overrides or {},
        measurer=measurer or FixedMeasurer(),
        rasteriser=FakeRasteriser(),
    )


def with_cdg(values: str) -> str:
    """The look with ``values`` added to its ``cdg`` section."""
    return LOOK.replace("wipe_columns: 3}", f"wipe_columns: 3, {values}}}")


def test_a_look_made_for_cdg_passes_the_cdg_check() -> None:
    assert cdg_problems() == []


def test_a_look_that_is_not_made_for_cdg_is_not_checked_on_cdg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("the CD+G check ran")

    monkeypatch.setattr(profiles_check, "check_cdg", never)
    unmarked = LOOK.replace("made_for_cdg: true", "made_for_cdg: false")
    assert cdg_problems(unmarked) == []
    assert cdg_problems(LOOK[: LOOK.index("# On CD+G")]) == []  # no section at all


def test_more_than_16_colours_are_reported_at_cdg_colours() -> None:
    unsung = ", ".join(f"singer{n}: {{unsung: '#{n}{n}eeee'}}" for n in range(1, 6))
    found = cdg_problems(with_cdg(f"colours: {{{unsung}}}"))
    assert all(m.startswith(f"my/look.yaml:{LOOK_ROW}:") for m in found)
    palette = [m for m in found if "more than the 16 entries" in m]
    assert palette and all("cdg.colours: " in m and "#11eeee" in m for m in palette)  # named


def test_contrast_that_the_12_bit_colours_lose_is_reported_at_the_colour() -> None:
    found = cdg_problems(with_cdg("colours: {singer1: {sung: '#111'}}"))
    assert any(
        m.startswith(f"my/look.yaml:{LOOK_ROW}:") and "cdg.colours.singer1.sung: has contrast" in m
        for m in found
    ), found
    assert all(m.endswith("on CD+G") or "cdg." not in m for m in found)


def test_a_contrast_problem_of_the_video_colours_is_not_reported_a_second_time_for_cdg() -> None:
    pale = LOOK.replace('background: "#000000"', 'background: "#ffffff"')
    found = cdg_problems(pale)
    assert any("colours.singer1.unsung: has contrast" in m for m in found)
    assert not any("cdg.colours" in m for m in found)


def test_a_line_that_is_too_wide_at_the_smallest_size_is_reported_at_min_font_px() -> None:
    big: dict[str, JsonValue] = {
        **ONE_STEP,
        "cdg": {"font_px": 76, "min_font_px": 76, "wipe_columns": 6},
    }
    found = cdg_problems(overrides=big, measurer=WideMeasurer())
    wide = [m for m in found if "cdg.min_font_px" in m]
    assert wide
    assert all(m.startswith("profile_overrides.cdg.min_font_px: ") for m in wide)
    assert all(m.endswith("(CD+G)") for m in wide)


def test_slots_that_do_not_fit_the_safe_area_are_reported_at_cdg_slots() -> None:
    crowded = LOOK.replace(
        "slots: 2, font_px: 24, min_font_px: 18", "slots: 6, font_px: 40, min_font_px: 40"
    )
    found = cdg_problems(crowded, ONE_STEP)
    column = crowded.splitlines()[LOOK_ROW - 1].index("slots: 6") + 1
    blocks = [m for m in found if "do not fit the safe area" in m]
    assert blocks
    assert all(m.startswith(f"my/look.yaml:{LOOK_ROW}:{column}: cdg.slots: ") for m in blocks)


def test_a_song_that_is_not_in_time_after_the_last_step_is_reported_at_font_px() -> None:
    stuck: dict[str, JsonValue] = {
        "lead_in": {"min": 0.05, "target": 0.05, "max": 0.05},
        "clear": {"replace_after": 9.0},
    }
    found = cdg_problems(overrides=stuck)
    column = LOOK.splitlines()[LOOK_ROW - 1].index("font_px") + 1
    assert any(
        m.startswith("profile_overrides.") or m.startswith(f"my/look.yaml:{LOOK_ROW}:{column}:")
        for m in found
    )
    assert any("cdg.font_px: " in m and "not fully drawn before they are sung" in m for m in found)


def test_a_wipe_that_stays_behind_is_reported_at_wipe_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = cdg_check.fit_stream

    def slow_wipe(*args: Any) -> Fit:
        fit = real(*args)
        scheduled = replace(fit.written.scheduled, wipe_lag=0.2)
        return replace(fit, written=replace(fit.written, scheduled=scheduled))

    monkeypatch.setattr(cdg_check, "fit_stream", slow_wipe)
    found = cdg_problems()
    column = LOOK.splitlines()[LOOK_ROW - 1].index("wipe_columns") + 1
    assert found
    assert all(m.startswith(f"my/look.yaml:{LOOK_ROW}:{column}: cdg.wipe_columns: ") for m in found)
    assert "the wipe is 200 ms behind (at most 50 ms), even with as declared" in found[0]


def test_a_broken_layout_rule_on_the_cdg_screen_names_file_and_cdg_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(scene: Scene, profile: Profile) -> list[str]:
        return ["rule 1: a box"]

    monkeypatch.setattr(cdg_check, "scene_findings", broken)
    found = cdg_problems(LOOK.replace("made_for_cdg: true", "made_for_cdg: true"))
    assert "my/look.yaml: CD+G, sample lyrics: rule 1: a box" in found
    assert "my/look.yaml: CD+G, dense song: rule 1: a box" in found


def test_an_override_of_the_cdg_section_is_checked_and_named() -> None:
    crowded: dict[str, JsonValue] = {
        **ONE_STEP,
        "cdg": {"slots": 6, "font_px": 40, "min_font_px": 40, "wipe_columns": 6},
    }
    found = cdg_problems(overrides=crowded)
    assert any(m.startswith("profile_overrides.cdg.slots: ") for m in found)


LYRIC_TEXT = RESOURCES.builtin_profile("lyric-video") or ""
NEON_TEXT = RESOURCES.builtin_profile("neon") or ""


def video_problems(
    text: str, name: str, overrides: dict[str, JsonValue] | None = None
) -> list[str]:
    return check_profile(
        f"my/{name}.yaml",
        text,
        expected_name=name,
        overrides=overrides or {},
        measurer=FixedMeasurer(),
        rasteriser=FakeRasteriser(),
    )


def test_a_dim_that_makes_the_unsung_text_hard_to_read_is_reported_at_the_key() -> None:
    text = LYRIC_TEXT.replace("upcoming: {dim: 0.5}", "upcoming: {dim: 0.8}")
    found = video_problems(text, "lyric-video")
    assert found
    assert all(f"my/lyric-video.yaml:{row_of(text, 'upcoming:')}:" in m for m in found)
    assert all("upcoming.dim: dims the unsung text of" in m for m in found)


def test_text_that_vanishes_in_the_light_end_of_a_moving_background_is_reported() -> None:
    light: dict[str, JsonValue] = {"background_motion": {"colours": ["#000000", "#d0d0e0"]}}
    found = video_problems(NEON_TEXT, "neon", light)
    assert any("colours.singer1.unsung: has contrast" in m for m in found)


def test_an_effect_next_to_a_cdg_section_is_reported_at_the_section() -> None:
    text = NEON_TEXT + "cdg: {made_for_cdg: true}\n"
    (found,) = video_problems(text, "neon")
    assert found.startswith(
        f"my/neon.yaml:{row_of(text, 'cdg:')}:1: cdg: cannot be used with the effects"
    )


def test_a_video_only_look_is_not_checked_on_the_cdg_screen() -> None:
    assert video_problems(NEON_TEXT, "neon") == []
    assert video_problems(LYRIC_TEXT, "lyric-video") == []


def test_a_scrolling_look_whose_line_does_not_fit_is_reported_at_the_font_size() -> None:
    text = (RESOURCES.builtin_profile("lyric-scroll") or "").replace("size: 0.1", "size: 0.4")
    text = text.replace("min_size: 0.07", "min_size: 0.2")
    found = video_problems(text, "lyric-scroll")
    assert any(":font.size:" in m or "font.size" in m for m in found if "scroll.current" in m), (
        found
    )
    assert all("slots" not in m for m in found)
    assert video_problems(RESOURCES.builtin_profile("lyric-scroll") or "", "lyric-scroll") == []


def test_only_a_block_shortfall_of_a_scrolling_look_goes_to_the_font_size() -> None:
    scrolling = parse_profile("lyric-scroll", RESOURCES.builtin_profile("lyric-scroll") or "")
    wide = Shortfall(kind="too-wide", message="wide")
    block = Shortfall(kind="block", message="block")
    assert profiles_check._fit_issue(wide, "p", scrolling).loc == ("font", "min_size")
    assert profiles_check._fit_issue(block, "p", scrolling).loc == ("font", "size")


# --------------------------------------------------------- page looks on the CD+G screen (ADR-0041)

PAGE_LOOKS = ("blue-page", "full-page", "tall-page")


def real_cdg_problems(name: str, overrides: dict[str, JsonValue] | None = None) -> list[str]:
    """Check a built-in page look with the bundled font, as `vocatron profiles check` does."""
    font = RESOURCES.font_file()
    return check_profile(
        f"my/{name}.yaml",
        RESOURCES.builtin_profile(name) or "",
        expected_name=name,
        overrides=overrides or {},
        measurer=PillowMeasurer(font),
        rasteriser=PillowRasteriser(font),
    )


@pytest.mark.parametrize("name", PAGE_LOOKS)
def test_the_page_looks_pass_the_cdg_check_with_pages_back_to_back(name: str) -> None:
    assert real_cdg_problems(name) == []


def test_a_page_look_that_cannot_draw_its_pages_in_time_fails_on_the_song_without_pauses() -> None:
    stuck: dict[str, JsonValue] = {
        "lead_in": {"min": 0.05, "target": 0.05, "max": 0.05},
        "clear": {"replace_after": 9.0},
    }
    found = real_cdg_problems("blue-page", stuck)
    late = [m for m in found if "not fully drawn before they are sung" in m]
    assert any("pages back to back:" in m and "even with " in m for m in late)
