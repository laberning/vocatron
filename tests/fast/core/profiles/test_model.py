"""Stage 1: style profiles load, report errors at file:line:column and take overrides (ADR-0009)."""

import pytest
from pydantic import JsonValue, ValidationError

import vocatron.core.profiles.model as profile_module
from fakes.resources import FakeResources
from vocatron.core.colour import contrast_ratio, distance
from vocatron.core.profiles.model import (
    BUILTIN_PROFILES,
    CDG_SLOTS_HINT,
    CLASSIC_PROFILES,
    DEFAULT_PROFILE,
    MIN_FILL_DISTANCE,
    MIN_WIPE_CONTRAST,
    Intro,
    Profile,
    ProfileError,
    Title,
    digest_json,
    is_name,
    made_for_cdg,
    parse_profile,
    profile_problems,
)

BUILTIN_FONT_SIZE = 0.12  # the font size of two-line-turns
TEXT = FakeResources().builtin_profile("two-line-turns") or ""  # most tests edit this look


def messages(text: str, overrides: dict[str, JsonValue] | None = None) -> list[str]:
    with pytest.raises(ProfileError) as error:
        parse_profile("my.yaml", text, overrides)
    return error.value.messages


def test_the_built_in_profile_loads_with_its_shipped_values() -> None:
    profile = parse_profile("two-line-turns.yaml", TEXT)
    assert (profile.name, profile.mode, profile.slots) == ("two-line-turns", "line", 2)
    # timing measured on classic discs (lead-in up to 5 s, hold 2 s, countdown steps of 0.6 s)
    assert (profile.lead_in.min, profile.lead_in.target, profile.lead_in.max) == (1.0, 3.0, 5.0)
    assert (profile.clear.hold, profile.countdown.duration) == (2.0, 2.4)
    assert profile.colours.singer1.sung == "#3399ff"
    assert profile.colours.group.sung == "#ffcc00"
    assert profile_problems(profile) == []


def test_the_default_profile_is_built_in() -> None:
    assert is_name(DEFAULT_PROFILE)
    assert DEFAULT_PROFILE in BUILTIN_PROFILES
    assert not is_name("my.yaml")
    assert not is_name("/home/anna/two-line-turns")


def test_the_start_screen_form_is_the_wordmark_by_default_and_plain_is_accepted() -> None:
    assert parse_profile("my.yaml", TEXT).title.form == "wordmark"
    assert parse_profile("my.yaml", TEXT, {"title": {"form": "plain"}}).title.form == "plain"


def test_a_start_screen_form_other_than_wordmark_or_plain_is_refused_at_its_key() -> None:
    (message,) = messages(TEXT, {"title": {"form": "fancy"}})
    assert "title.form" in message


def test_a_wrong_value_is_reported_with_file_line_and_column() -> None:
    text = TEXT.replace("slots: 2", "slots: 9", 1)
    (message,) = messages(text)
    row = text.splitlines().index("slots: 9") + 1
    assert message.startswith(f"my.yaml:{row}:1: slots: ")


def test_an_unknown_key_is_an_error_at_its_position() -> None:
    text = TEXT.replace("edge: {width: 0.08}", "edge: {width: 0.08, glow: 3}")
    (message,) = messages(text)
    assert "my.yaml:" in message
    assert "edge.glow" in message


def test_a_bad_colour_is_reported_inside_its_mapping() -> None:
    text = TEXT.replace('sung: "#3399ff"', 'sung: "blue"')
    (message,) = messages(text)
    assert "colours.singer1.sung" in message


def test_invalid_yaml_is_reported_with_its_position() -> None:
    (message,) = messages("name: [unclosed\n")
    assert message.startswith("my.yaml:")


def test_a_missing_part_is_reported() -> None:
    text = "\n".join(line for line in TEXT.splitlines() if not line.startswith("  singer3"))
    assert any("colours.singer3" in m for m in messages(text))


def test_the_lead_in_must_be_ordered() -> None:
    text = TEXT.replace(
        "lead_in: {min: 1.0, target: 3.0, max: 5.0}", "lead_in: {min: 5.0, target: 3.0, max: 1.0}"
    )
    assert any("min <= target <= max" in m for m in messages(text))


def test_the_smallest_font_may_not_exceed_the_font() -> None:
    assert any("min_size" in m for m in messages(TEXT.replace("min_size: 0.08", "min_size: 0.2")))


def test_overrides_replace_single_values_and_keep_the_rest() -> None:
    profile = parse_profile("p", TEXT, {"font": {"size": 0.1}, "slots": 3})
    assert profile.font.size == 0.1
    assert profile.font.min_size == 0.08
    assert profile.slots == 3
    assert profile.colours.singer2.sung == "#ff3399"


def test_an_override_error_names_the_override_not_the_file() -> None:
    (message,) = messages(TEXT, {"font": {"size": 7}})
    assert message.startswith("profile_overrides.font.size:")
    assert "my.yaml" not in message


def test_an_override_of_a_whole_part_is_checked_too() -> None:
    (message,) = messages(TEXT, {"colours": {"singer1": {"sung": "red"}}})
    assert message.startswith("profile_overrides.colours.singer1.sung:")


def test_colours_that_are_too_alike_or_too_dark_are_found() -> None:
    dark = parse_profile(
        "p", TEXT, {"colours": {"singer1": {"unsung": "#101010", "sung": "#111111"}}}
    )
    problems = profile_problems(dark)
    assert any("singer1.unsung" in p and "contrast" in p for p in problems)
    assert any("singer1" in p and "too alike" in p for p in problems)


def test_an_edge_that_is_as_bright_as_the_text_is_found() -> None:
    profile = parse_profile("p", TEXT, {"colours": {"group": {"edge": "#ffffff"}}})
    assert any("group" in p and "its edge" in p for p in profile_problems(profile))


def test_overrides_in_two_parts_are_all_named_when_both_are_wrong() -> None:
    with pytest.raises(ProfileError) as error:
        parse_profile("two-line-turns", TEXT, {"font": {"size": 9}, "clear": {"hold": -1}})
    assert sorted(error.value.messages) == [
        "profile_overrides.clear.hold: Input should be greater than or equal to 0",
        "profile_overrides.font.size: Input should be less than or equal to 0.4",
    ]
    assert str(error.value) == "\n".join(error.value.messages)


def test_page_mode_and_its_min_lines_load() -> None:
    text = TEXT.replace("mode: line", "mode: page\npage: {min_lines: 2}")
    profile = parse_profile("page.yaml", text)
    assert (profile.mode, profile.slots, profile.page.min_lines) == ("page", 2, 2)
    assert parse_profile("page.yaml", TEXT).page.min_lines == 1


def test_min_lines_above_slots_is_refused() -> None:
    text = TEXT.replace("mode: line", "mode: page\npage: {min_lines: 3}")
    (message,) = messages(text)
    assert "page.min_lines must not be larger than slots" in message


@pytest.mark.parametrize(
    ("mode", "slots"), [("line", 2), ("page", 1), ("page", 2)], ids=["two", "page-one", "page-two"]
)
def test_a_preview_needs_line_mode_and_one_slot(mode: str, slots: int) -> None:
    text = TEXT.replace("mode: line", f"mode: {mode}").replace("slots: 2", f"slots: {slots}")
    (message,) = messages(text, {"preview": {"show": True}})
    assert "preview.show needs mode: line and slots: 1" in message
    ok = TEXT.replace("slots: 2", "slots: 1")
    assert parse_profile("one.yaml", ok, {"preview": {"show": True}}).preview.scale == 0.7


def test_six_slots_load_and_seven_are_refused() -> None:
    assert parse_profile("six.yaml", TEXT.replace("slots: 2", "slots: 6")).slots == 6
    (message,) = messages(TEXT.replace("slots: 2", "slots: 7", 1))
    assert "less than or equal to 6" in message


def test_the_preview_scale_stays_between_0_4_and_0_9() -> None:
    for scale in (0.3, 0.95):
        (message,) = messages(
            TEXT.replace("slots: 2", "slots: 1"), {"preview": {"show": True, "scale": scale}}
        )
        assert "preview.scale" in message


def test_two_line_turns_has_its_shipped_values() -> None:
    profile = parse_profile("two-line-turns.yaml", TEXT)
    assert (profile.mode, profile.preview.show, profile.breaks.form) == ("line", False, "notice")
    assert (profile.countdown.form, profile.page.min_lines) == ("shrinking-bar", 1)


def test_the_two_new_looks_have_their_shipped_values() -> None:
    def load(name: str) -> Profile:
        return parse_profile(name, FakeResources().builtin_profile(name) or "")

    tall, three = load("tall-page"), load("three-line")
    assert (tall.mode, tall.slots, tall.line_rows) == ("page", 6, 2)
    assert (tall.page.min_lines, tall.page.slot_per_row) == (3, True)
    assert (tall.countdown.form, tall.countdown.count, tall.countdown.min_gap) == ("dots", 5, 8.0)
    assert (three.mode, three.slots, three.line_rows) == ("line", 3, 1)
    assert (three.breaks.form, three.countdown.form) == ("timer", "shrinking-bar")
    assert (three.background, three.colours.singer1.unsung) == ("#444466", "#ff9900")
    assert all(made_for_cdg(p) and profile_problems(p) == [] for p in (tall, three))
    assert CLASSIC_PROFILES[-2:] == ("tall-page", "three-line")  # after one-line-preview
    assert (*CLASSIC_PROFILES, "neon", "lyric-video", "lyric-scroll") == BUILTIN_PROFILES


def test_the_modern_looks_have_their_shipped_values() -> None:
    def load(name: str) -> Profile:
        return parse_profile(name, FakeResources().builtin_profile(name) or "")

    neon, lyric = load("neon"), load("lyric-video")
    assert (neon.mode, neon.slots, neon.line_rows) == ("line", 2, 1)
    assert neon.glow.sung == 0.6 and neon.glow.colour is None
    assert neon.pop.scale == 1.0  # no pop: the growing word made the lines wobble
    assert (neon.transition.form, neon.transition.time) == ("fade", 0.3)
    assert neon.upcoming.dim == 0.0
    assert neon.background_motion.colours == ["#04050c", "#150a30", "#061a2e"]
    assert (lyric.mode, lyric.slots, lyric.line_rows) == ("line", 2, 1)
    assert (lyric.transition.form, lyric.transition.time, lyric.upcoming.dim) == ("slide", 0.3, 0.5)
    assert (lyric.glow.sung, lyric.pop.scale, lyric.edge.width) == (0.0, 1.0, 0.0)
    assert lyric.background_motion.colours == []
    assert lyric.font.size > BUILTIN_FONT_SIZE  # large text
    assert all(profile_problems(p) == [] for p in (neon, lyric))


def test_the_built_in_looks_have_their_shipped_values() -> None:
    def load(name: str) -> Profile:
        return parse_profile(f"{name}.yaml", FakeResources().builtin_profile(name) or "")

    stack, page, blue, single = (
        load(n) for n in ("four-line-stack", "full-page", "blue-page", "one-line-preview")
    )
    assert (stack.mode, stack.slots, stack.breaks.form) == ("line", 4, "progress")
    assert (stack.block, stack.cdg and stack.cdg.slots) == (2, 4)  # two lines at a time
    assert page.block == blue.block == single.block == 1
    assert (stack.countdown.form, stack.countdown.count, stack.countdown.duration) == (
        "dots",
        4,
        2.4,
    )
    assert (page.mode, page.slots, page.page.min_lines) == ("page", 5, 3)
    assert (blue.mode, blue.slots, blue.background) == ("page", 4, "#000055")
    assert (blue.countdown.form, blue.breaks.form) == ("blocks", "progress")
    assert (single.slots, single.preview.show, single.preview.scale) == (1, True, 0.7)
    assert all(profile_problems(p) == [] for p in (stack, page, blue, single))


def test_a_profile_with_the_old_duet_setting_is_refused() -> None:
    text = TEXT + "duet: {overlap: merge, min_overlap: 0.5}\n"
    (message,) = messages(text)
    assert "duet" in message
    assert parse_profile("my.yaml", TEXT).model_dump().get("duet") is None


def test_the_duet_setting_is_refused_as_an_override_too() -> None:
    with pytest.raises(ProfileError) as error:
        parse_profile("my.yaml", TEXT, {"duet": {"min_overlap": 1.0}})
    assert "duet" in error.value.messages[0]


def test_line_rows_default_to_one_and_allow_two() -> None:
    assert parse_profile("p.yaml", TEXT).line_rows == 1
    assert parse_profile("p.yaml", TEXT, {"line_rows": 2}).line_rows == 2


@pytest.mark.parametrize("rows", [0, 3])
def test_line_rows_outside_one_to_two_are_refused(rows: int) -> None:
    (message,) = messages(TEXT, {"line_rows": rows})
    assert message.startswith("profile_overrides.line_rows:")


def test_only_three_looks_wrap_lines_onto_two_rows() -> None:
    rows = {
        name: parse_profile(name, FakeResources().builtin_profile(name) or "").line_rows
        for name in BUILTIN_PROFILES
    }
    assert rows == dict.fromkeys(BUILTIN_PROFILES, 1) | {
        "one-line-preview": 2,
        "tall-page": 2,
        "lyric-scroll": 2,
    }


SLOT_PER_ROW: dict[str, JsonValue] = {
    "mode": "page",
    "slots": 4,
    "line_rows": 2,
    "page": {"slot_per_row": True},
    "cdg": {"slots": 4},
}


def test_slot_per_row_needs_page_mode_and_two_rows() -> None:
    assert parse_profile("p.yaml", TEXT, SLOT_PER_ROW).page.slot_per_row
    assert not parse_profile("p.yaml", TEXT).page.slot_per_row  # off unless asked for
    for without in ({"mode": "line"}, {"line_rows": 1}):
        (message,) = messages(TEXT, SLOT_PER_ROW | without)
        assert "page.slot_per_row needs mode: page and line_rows: 2" in message


def test_page_turn_is_the_whole_page_unless_asked_for_and_needs_page_mode() -> None:
    page: dict[str, JsonValue] = {"mode": "page", "page": {"turn": "line"}}
    assert parse_profile("p.yaml", TEXT).page.turn == "page"
    assert parse_profile("p.yaml", TEXT, page).page.turn == "line"
    (message,) = messages(TEXT, {"page": {"turn": "line"}})  # the look is in line mode
    assert "page.turn: line needs mode: page" in message
    assert messages(TEXT, {"mode": "page", "page": {"turn": "sideways"}})  # only page or line


def test_the_built_in_looks_turn_whole_pages() -> None:
    turns = {
        name: parse_profile(name, FakeResources().builtin_profile(name) or "").page.turn
        for name in BUILTIN_PROFILES
    }
    assert turns == dict.fromkeys(BUILTIN_PROFILES, "page")


def test_slot_per_row_needs_two_slots_on_the_screen_and_on_cdg() -> None:
    (message,) = messages(TEXT, SLOT_PER_ROW | {"slots": 1})
    assert "page.slot_per_row needs slots of at least 2" in message
    (message,) = messages(TEXT, SLOT_PER_ROW | {"cdg": {"slots": 1}})
    assert message.startswith("profile_overrides.cdg.slots:")
    assert "page.slot_per_row needs cdg.slots of at least 2" in message


BLOCKS: dict[str, JsonValue] = {"slots": 4, "block": 2, "cdg": {"slots": 4}}


def test_block_is_one_line_unless_asked_for_and_has_limits() -> None:
    assert parse_profile("p.yaml", TEXT).block == 1
    assert parse_profile("p.yaml", TEXT, BLOCKS).block == 2
    triples: dict[str, JsonValue] = {"slots": 6, "block": 3, "cdg": {"slots": 6}}
    assert parse_profile("p.yaml", TEXT, triples).block == 3
    for wrong in (0, 4):
        (message,) = messages(TEXT, {"block": wrong})
        assert "block" in message


def test_block_needs_slots_in_whole_blocks_and_at_least_two_of_them() -> None:
    for slots in (3, 2, 1):  # not a multiple, or one block only
        (message,) = messages(TEXT, BLOCKS | {"slots": slots})
        assert message.startswith("profile_overrides.slots:")  # refused at its key
        assert "slots must be a multiple of block (2) with at least two blocks" in message
    (message,) = messages(TEXT, {"slots": 4, "block": 3, "cdg": {"slots": 6}})
    assert message.startswith("profile_overrides.slots:")
    assert "slots must be a multiple of block (3)" in message


def test_a_slot_conflict_in_the_file_is_located_at_the_key_slots() -> None:
    line = next(i for i, x in enumerate(TEXT.splitlines(), 1) if x.startswith("slots:"))
    text = TEXT.replace("\nslots:", "\nblock: 2\nslots:", 1)  # the file's two slots: one block
    (message,) = messages(text, {"cdg": {"slots": 4}})
    assert message.startswith(f"my.yaml:{line + 1}:1: slots: ")
    assert "slots must be a multiple of block (2)" in message


def test_block_is_checked_on_the_cdg_slots_at_their_key() -> None:
    (message,) = messages(TEXT, BLOCKS | {"cdg": {"slots": 3}})
    assert message.startswith("profile_overrides.cdg.slots:")
    assert "cdg.slots must be a multiple of block (2) with at least two blocks" in message


def test_block_is_refused_with_page_and_scroll_mode() -> None:
    for mode in ("page", "scroll"):
        (message,) = messages(TEXT, BLOCKS | {"mode": mode})
        assert message.startswith("profile_overrides.block:")  # refused at its key
        assert "block needs mode: line" in message


def test_a_look_without_blocks_keeps_the_digest_of_its_picture() -> None:
    assert '"block"' not in digest_json(parse_profile("p.yaml", TEXT))
    assert '"block":2' in digest_json(parse_profile("p.yaml", TEXT, BLOCKS))


def test_the_timer_form_loads() -> None:
    assert parse_profile("p.yaml", TEXT, {"breaks": {"form": "timer"}}).breaks.form == "timer"
    assert parse_profile("p.yaml", TEXT).breaks.form == "notice"  # the default stays
    (message,) = messages(TEXT, {"breaks": {"form": "clock"}})
    assert message.startswith("profile_overrides.breaks.form:")


YELLOW_ON_WHITE: dict[str, JsonValue] = {
    "colours": {"singer1": {"unsung": "#ffffff", "sung": "#ffff00"}}
}


def test_a_sung_colour_that_does_not_stand_out_from_the_unsung_one_is_found() -> None:
    profile = parse_profile("p", TEXT, YELLOW_ON_WHITE)
    (problem,) = profile_problems(profile)
    assert problem == (
        "singer1.sung has contrast 1.07 with the unsung colour, too little to see the wipe"
    )


def test_the_wipe_contrast_is_judged_by_lightness_and_not_by_hue() -> None:
    # far apart in colour (distance 255) but alike in lightness; red on white is clearly seen
    assert MIN_FILL_DISTANCE < 255
    assert (
        profile_problems(parse_profile("p", TEXT, {"colours": {"singer1": {"sung": "#ff0000"}}}))
        == []
    )
    assert profile_problems(parse_profile("p", TEXT, YELLOW_ON_WHITE)) != []


def grey(value: int) -> str:
    return f"#{value:02x}{value:02x}{value:02x}"


def test_a_wipe_contrast_at_the_minimum_is_fine_and_just_below_is_not() -> None:
    # the lightest grey that has at least MIN_WIPE_CONTRAST against white, and the one above it
    ok = next(
        v for v in range(255, 0, -1) if contrast_ratio("#ffffff", grey(v)) >= MIN_WIPE_CONTRAST
    )
    assert contrast_ratio("#ffffff", grey(ok + 1)) < MIN_WIPE_CONTRAST
    for value, fine in ((ok, True), (ok + 1, False)):
        profile = parse_profile("p", TEXT, {"colours": {"singer1": {"sung": grey(value)}}})
        assert any("wipe" in p for p in profile_problems(profile)) is not fine


def test_singer_1_and_singer_4_of_the_blue_page_are_apart_from_the_others() -> None:
    profile = parse_profile("p", FakeResources().builtin_profile("blue-page") or "")
    sung = {key: profile.singer_colours(key).sung for key in ("1", "2", "3", "4", "5", "group")}
    assert sung["1"] == "#ff5a1f"
    for key in ("1", "4"):
        for other, colour in sung.items():
            if other != key:
                assert distance(sung[key], colour) >= 100, (key, other)


def test_a_wipe_contrast_exactly_at_the_minimum_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    look = parse_profile("p", TEXT)
    keys = ("1", "2", "3", "4", "5", "group")
    lowest = min(contrast_ratio(c.unsung, c.sung) for c in map(look.singer_colours, keys))
    monkeypatch.setattr(profile_module, "MIN_WIPE_CONTRAST", lowest)
    assert profile_problems(look) == []
    monkeypatch.setattr(profile_module, "MIN_WIPE_CONTRAST", lowest + 0.001)
    assert [p for p in profile_problems(look) if "wipe" in p] != []


def test_the_intro_minimums_default_to_eight_and_nine_seconds() -> None:
    profile = parse_profile("p", TEXT.replace("intro: {solo: 8.0, group: 9.0}\n", ""))
    assert (profile.intro.solo, profile.intro.group) == (8.0, 9.0)


def test_the_intro_is_read_and_overridden() -> None:
    text = TEXT.replace("intro: {solo: 8.0, group: 9.0}", "intro: {solo: 3.0, group: 8.0}")
    assert parse_profile("p", text).intro.group == 8.0
    off = parse_profile("p", text, {"intro": {"solo": 0, "group": 0}})
    assert (off.intro.solo, off.intro.group) == (0.0, 0.0)


def test_a_negative_intro_is_refused_at_its_key() -> None:
    (message,) = messages(TEXT.replace("intro: {solo: 8.0", "intro: {solo: -1"))
    assert "intro.solo" in message


def test_every_built_in_look_sets_the_intro_and_a_four_second_start_screen() -> None:
    assert len(BUILTIN_PROFILES) == 10
    for name in BUILTIN_PROFILES:
        text = FakeResources().builtin_profile(name) or ""
        assert "\nintro: {solo: 8.0, group: 9.0}\n" in text, name
        look = parse_profile(name, text)
        assert (look.title.min_short, look.intro) == (4.0, Intro(solo=8.0, group=9.0)), name


def test_the_model_defaults_are_a_four_second_start_screen_and_the_long_intro() -> None:
    assert (Title().min_short, Intro()) == (4.0, Intro(solo=8.0, group=9.0))


def test_a_shorter_min_brings_the_default_min_short_down_with_it() -> None:
    assert Title.model_validate({"min": 3.0}).min_short == 3.0
    assert Title.model_validate({"min": 3.0, "min_short": 1.0}).min_short == 1.0
    assert Title.model_validate({"min": 6.0}).min_short == 4.0
    assert Title.model_validate({"min": 4}).min_short == 4.0
    assert Title.model_validate({}).min_short == 4.0


@pytest.mark.parametrize("minimum", ["soon", None, [3]])
def test_a_min_that_is_no_number_is_a_validation_error_not_a_crash(minimum: JsonValue) -> None:
    with pytest.raises(ValidationError, match="min"):
        Title.model_validate({"min": minimum})


BLUE = FakeResources().builtin_profile("blue-page") or ""
CDG_LINE = next(i for i, line in enumerate(BLUE.splitlines(), 1) if line.startswith("cdg:"))


@pytest.mark.parametrize("name", CLASSIC_PROFILES)
def test_every_classic_look_is_made_for_cdg_with_values_inside_the_limits(name: str) -> None:
    look = parse_profile(name, FakeResources().builtin_profile(name) or "")
    assert made_for_cdg(look)
    section = look.cdg
    assert section is not None
    assert 1 <= section.slots <= look.slots  # a look may use fewer slots on CD+G, never more
    assert 4 <= section.min_font_px <= section.font_px <= 76
    assert section.edge_px in (1, 2) and section.wipe_columns in (1, 2, 3, 6)


def test_a_look_without_the_section_or_with_the_marker_off_is_mp4_only() -> None:
    bare = BLUE[: BLUE.index("# On CD+G")]
    assert parse_profile("bare.yaml", bare).cdg is None
    assert not made_for_cdg(parse_profile("bare.yaml", bare))
    unmarked = parse_profile("off.yaml", BLUE.replace("made_for_cdg: true", "made_for_cdg: false"))
    assert unmarked.cdg is not None and not made_for_cdg(unmarked)
    assert not made_for_cdg(parse_profile("none.yaml", BLUE, {"cdg": None}))


def test_the_section_has_defaults_and_takes_short_and_long_colours() -> None:
    text = BLUE.replace("wipe_columns: 3}", "wipe_columns: 3, colours: {background: '#003'}}")
    section = parse_profile("c.yaml", text).cdg
    assert section is not None and section.colours.background == "#003"
    empty = parse_profile("c.yaml", BLUE, {"cdg": {"colours": {"singer2": {"sung": "#F0A0B0"}}}})
    assert empty.cdg is not None and empty.cdg.colours.singer2 is not None
    assert empty.cdg.colours.singer2.sung == "#F0A0B0"
    minimal = parse_profile("c.yaml", BLUE, {"cdg": {}})
    assert minimal.cdg is not None and minimal.cdg.made_for_cdg  # the marker stays


def test_cdg_slots_below_the_pages_minimum_is_an_error_at_that_key() -> None:
    (message,) = messages(BLUE.replace("slots: 4, font_px", "slots: 1, font_px"))
    assert message == (
        f"my.yaml:{CDG_LINE}:27: cdg.slots: page.min_lines must not be larger than cdg.slots "
        f"({CDG_SLOTS_HINT})"
    )


def test_a_preview_needs_a_single_line_on_cdg_too() -> None:
    text = FakeResources().builtin_profile("one-line-preview") or ""
    (message,) = messages(text.replace("slots: 1, font_px", "slots: 2, font_px"))
    assert "cdg.slots: preview.show needs mode: line and cdg.slots: 1" in message


def test_an_override_that_breaks_the_section_names_the_override() -> None:
    (message,) = messages(BLUE, {"cdg": {"slots": 1}})
    assert message == (
        "profile_overrides.cdg.slots: page.min_lines must not be larger than cdg.slots "
        f"({CDG_SLOTS_HINT})"
    )


def test_an_override_of_the_video_slots_that_breaks_the_section_says_what_to_do() -> None:
    (message,) = messages(BLUE, {"page": {"min_lines": 5}, "slots": 5})
    assert message.startswith(f"my.yaml:{CDG_LINE}:27: cdg.slots: page.min_lines")
    assert "set cdg.slots to match, or cdg.made_for_cdg: false" in message
    look = parse_profile(
        "my.yaml", BLUE, {"page": {"min_lines": 5}, "slots": 5, "cdg": {"slots": 5}}
    )
    assert look.cdg is not None and look.cdg.slots == 5


def test_a_section_without_the_marker_is_not_held_to_the_rules_of_the_profile() -> None:
    off = BLUE.replace("made_for_cdg: true, slots: 4", "made_for_cdg: false, slots: 1")
    assert not made_for_cdg(parse_profile("my.yaml", off))


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ("edge_px: 1", "edge_px: 3", "cdg.edge_px"),
        ("edge_px: 1", "edge_px: 0", "cdg.edge_px"),  # a look without an edge colours it black
        ("wipe_columns: 3", "wipe_columns: 4", "cdg.wipe_columns"),
        ("font_px: 24", "font_px: 3", "cdg.font_px"),
        ("font_px: 24", "font_px: 77", "cdg.font_px"),
        ("min_font_px: 18", "min_font_px: 30", "cdg.min_font_px"),
        ("slots: 4, font_px", "slots: 7, font_px", "cdg.slots"),
        ("made_for_cdg: true", "made_for_cdg: yes please", "cdg.made_for_cdg"),
        ("wipe_columns: 3}", "wipe_columns: 3, glow: 1}", "cdg.glow"),
        ("wipe_columns: 3}", "wipe_columns: 3, colours: {singer1: {sung: '#12'}}}", "cdg.colours"),
        ("wipe_columns: 3}", "wipe_columns: 3, colours: {group: {shine: '#123'}}}", "cdg.colours"),
    ],
)
def test_a_wrong_cdg_value_is_reported_at_its_key(old: str, new: str, key: str) -> None:
    (message,) = messages(BLUE.replace(old, new))
    assert message.startswith(f"my.yaml:{CDG_LINE}:")
    assert f" {key}" in message


def test_the_default_look_is_four_line_stack_and_made_for_cdg() -> None:
    # So that `outputs: [mp4, cdg]` works without choosing another look (ADR-0043).
    assert DEFAULT_PROFILE == "four-line-stack"
    look = parse_profile(
        f"{DEFAULT_PROFILE}.yaml", FakeResources().builtin_profile(DEFAULT_PROFILE) or ""
    )
    assert look.name == DEFAULT_PROFILE
    assert made_for_cdg(look)
    assert profile_problems(look) == []
