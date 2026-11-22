"""Stage 1: the timing of a song on CD+G and the fallback steps (ADR-0029)."""

from dataclasses import replace

import pytest
from pydantic import JsonValue

from fakes.measure import FixedMeasurer
from fakes.raster import FakeRasteriser
from fakes.scenes import builtin_profile
from vocatron.core.cdg.fit import MAX_WIPE_LAG, Fit, fit_stream, write_step
from vocatron.core.cdg.look import fit_steps
from vocatron.core.cdg.stream import build_stream
from vocatron.core.errors import StageError
from vocatron.core.layout import sample
from vocatron.core.layout.phrases import phrases_from
from vocatron.core.layout.rules import scene_findings
from vocatron.core.profiles.model import Profile
from vocatron.engines.measure import PillowMeasurer
from vocatron.engines.raster import PillowRasteriser
from vocatron.engines.resources import PackageResources

QUICK = {i: 0.3 for i in range(1, 5)}  # the folk song with 0.3 s between the lines


def song_of(gaps: dict[int, float] | None = None) -> sample.Piece:
    song = sample.timed_song(sample.ENTCHEN, start=9.0, gaps=gaps)
    return song, sample.song_text("Alle meine Entchen", "Volkslied", 60.0, {})


def fit(look: Profile, piece: sample.Piece) -> Fit:
    song, text = piece
    phrases = phrases_from(song.words, song.lines, look.font.case)
    return fit_stream(phrases, text, look, FixedMeasurer(), FakeRasteriser())


def declared(look: Profile, piece: sample.Piece) -> Fit:
    """Write the song at the first step only, as the look declares it."""
    song, text = piece
    phrases = phrases_from(song.words, song.lines, look.font.case)
    first = fit_steps(look)[0]
    return write_step(phrases, text, look, first, FixedMeasurer(), FakeRasteriser())


def late(**overrides: JsonValue) -> Profile:
    """A look whose slot is refilled only at the lead-in minimum, so a small minimum is late."""
    return builtin_profile("two-line-turns", clear={"hold": 0, "replace_after": 9.0}, **overrides)


def test_a_song_in_time_takes_the_first_step_and_writes_one_stream() -> None:
    result = fit(builtin_profile("two-line-turns"), song_of({2: 6.0, 4: 22.0}))
    assert result.step.number == 0 and result.in_time
    assert result.late_lines == 0 and result.wipe_lag <= MAX_WIPE_LAG
    assert result.profile.lead_in == builtin_profile("two-line-turns").lead_in


def test_a_song_whose_lines_come_too_late_takes_the_step_that_draws_them_earlier() -> None:
    look = late(lead_in={"min": 0.05, "target": 1.0, "max": 2.0})
    first = declared(look, song_of(QUICK))
    assert first.late_lines > 0 and not first.in_time
    result = fit(look, song_of(QUICK))
    assert (result.step.number, result.in_time, result.late_lines) == (1, True, 0)
    assert result.step.name == "lines earlier (lead-in target)"
    assert result.profile.lead_in.min == 1.0
    assert result.steps == 4


def test_the_next_step_takes_the_lead_in_maximum() -> None:
    look = late(lead_in={"min": 0.05, "target": 0.05, "max": 1.0})
    result = fit(look, song_of(QUICK))
    assert (result.step.number, result.in_time) == (1, True)  # target equals the minimum: left out
    assert result.step.name == "lines earlier (lead-in maximum)"
    assert result.profile.lead_in.min == 1.0


def test_when_no_step_is_in_time_the_last_one_is_written_with_the_flag() -> None:
    look = late(lead_in={"min": 0.05, "target": 0.05, "max": 0.05})
    result = fit(look, song_of(QUICK))
    assert result.step.number == result.steps - 1 == 1
    assert result.step.name == "coarser wipe" and result.step.wipe_columns == 6
    assert not result.in_time and result.late_lines > 0
    assert len(result.written.stream) > 0  # the file is written all the same


def test_the_same_input_takes_the_same_step_and_gives_the_same_bytes() -> None:
    look = late(lead_in={"min": 0.05, "target": 1.0, "max": 2.0})
    first, second = fit(look, song_of(QUICK)), fit(look, song_of(QUICK))
    assert first.step == second.step and first.written.stream == second.written.stream


def test_the_wipe_step_of_the_look_is_the_one_the_stream_is_written_with() -> None:
    steps = {
        columns: fit(builtin_profile("two-line-turns", cdg={"wipe_columns": columns}), song_of())
        for columns in (1, 3, 6)
    }
    assert all(result.step.wipe_columns == columns for columns, result in steps.items())
    # a coarser wipe changes fewer tiles: the file differs, and fewer packets draw
    assert steps[6].written.scheduled.drawing_packets < steps[1].written.scheduled.drawing_packets


def test_a_wipe_more_than_50_ms_behind_is_not_in_time_however_well_the_lines_are_drawn() -> None:
    result = declared(builtin_profile("two-line-turns"), song_of())
    assert result.in_time and result.late_lines == 0

    def with_wipe_lag(seconds: float) -> Fit:
        scheduled = replace(result.written.scheduled, wipe_lag=seconds)
        return replace(result, written=replace(result.written, scheduled=scheduled))

    assert with_wipe_lag(MAX_WIPE_LAG).in_time  # exactly 50 ms is still fine
    assert not with_wipe_lag(MAX_WIPE_LAG + 0.01).in_time


def test_a_look_that_needs_more_than_16_colours_is_the_error_cdg_palette() -> None:
    unsung: dict[str, JsonValue] = {f"singer{n}": {"unsung": f"#{n}{n}eeee"} for n in range(1, 6)}
    look = builtin_profile("two-line-turns", colours=unsung)
    song = sample.timed_song(sample.ENTCHEN, singers=["1", "2", "3", "4", "5"])
    text = sample.song_text("Alle meine Entchen", "Volkslied", 60.0, {})
    with pytest.raises(StageError) as error:
        fit(look, (song, text))
    assert error.value.kind == "cdg-palette"


# ------------------------------------------------------------ page looks (ADR-0041)

PAGE_LOOKS = ("blue-page", "full-page", "tall-page")
FONT = PackageResources().font_file()


def real(look: Profile, piece: sample.Piece, first_only: bool = False) -> Fit:
    """Write the song with the bundled font: page looks need the real size of the letters."""
    song, text = piece
    phrases = phrases_from(song.words, song.lines, look.font.case)
    tools = PillowMeasurer(FONT), PillowRasteriser(FONT)
    if first_only:
        return write_step(phrases, text, look, fit_steps(look)[0], *tools)
    return fit_stream(phrases, text, look, *tools)


@pytest.mark.parametrize("name", PAGE_LOOKS)
def test_pages_back_to_back_are_late_with_whole_page_turns(name: str) -> None:
    first = real(builtin_profile(name), sample.back_to_back_piece(), first_only=True)
    assert first.step.page_turn == "page"
    assert first.late_lines > 0 and not first.in_time  # a page cannot be drawn in no time


@pytest.mark.parametrize("name", PAGE_LOOKS)
def test_a_page_look_that_is_late_with_whole_pages_turns_line_by_line_for_the_whole_song(
    name: str,
) -> None:
    result = real(builtin_profile(name), sample.back_to_back_piece())
    assert result.in_time and result.late_lines == 0
    assert (result.step.name, result.step.page_turn) == ("line by line", "line")
    assert result.profile.page.turn == "line"
    assert len({x.page for x in result.scene.lines()}) > 2  # several pages, all turned line by line
    assert scene_findings(result.scene, result.profile) == []


@pytest.mark.parametrize("name", PAGE_LOOKS)
def test_a_page_look_song_in_time_with_whole_pages_keeps_them(name: str) -> None:
    pauses = {i: 4.5 for i in range(1, 5)}  # a pause before every line: time to draw a page
    result = real(builtin_profile(name), song_of(pauses))
    assert result.step.number == 0 and result.in_time
    assert result.profile.page.turn == "page"


def test_a_line_look_is_written_without_clearing_and_a_page_look_clears_first() -> None:
    song = sample.entchen_piece()
    for name, clears in (
        ("two-line-turns", False),
        ("one-line-preview", False),
        ("blue-page", True),
    ):
        fit = real(builtin_profile(name), song, first_only=True)
        plain = build_stream(fit.scene, PillowRasteriser(FONT), fit.step.wipe_columns)
        assert (fit.written.stream != plain.stream) is clears, name
