"""Stage 1: the report of a song, the summary lines and the report file, as golden text."""

import pytest
from syrupy.assertion import SnapshotAssertion

from vocatron.core.alignment.file import AlignedLine, AlignmentFile, QualityReport
from vocatron.core.lyrics.document import Voice
from vocatron.core.lyrics.file import LyricLine, LyricsFile
from vocatron.core.report import (
    CountdownNote,
    Findings,
    ReportFile,
    SummaryRow,
    SummaryState,
    build_report,
    clip,
    columns,
    exit_code_of,
    format_row,
    format_rows,
    name_width,
    pad,
    report_text,
    row_not_run,
    row_of_report,
    row_of_status,
    second_voice_lines,
    short_name,
    total_line,
)
from vocatron.core.status import ErrorInfo, SongStatus, StageOutcome

QUALITY = QualityReport(
    words=100,
    estimated=4,
    estimated_share=0.04,
    longest_gap=1.5,
    gap_line=3,
    too_short=0,
    too_long=1,
)
UPDATED = "2026-10-29T12:00:00+00:00"


def status(
    state: str = "ok",
    reasons: list[str] | None = None,
    error: ErrorInfo | None = None,
    current: str | None = None,
) -> SongStatus:
    return SongStatus.model_validate(
        {
            "name": "A - B",
            "source": "a.mp3",
            "state": state,
            "current": current,
            "reasons": reasons or [],
            "error": error,
            "stages": [StageOutcome(stage="probe", action="ran")],
            "updated": UPDATED,
        }
    )


FOUND = Findings(
    duration=185.0, lyrics="ok", quality=QUALITY, rails="used", outputs=("A - B.mp4", "A - B.lrc")
)


def test_a_report_carries_the_verdict_the_numbers_and_the_outputs() -> None:
    report = build_report(
        status("review", ["alignment: 12% estimated"]), FOUND, {"probe": 0.5}, None
    )
    assert (report.status, report.reasons) == ("review", ["alignment: 12% estimated"])
    assert (report.duration, report.lyrics, report.rails) == (185.0, "ok", "used")
    assert report.quality == QUALITY
    assert report.outputs == ["A - B.mp4", "A - B.lrc"]
    assert report.updated == UPDATED


def test_the_times_of_skipped_stages_stay_from_the_run_that_made_them() -> None:
    first = build_report(status(), FOUND, {"probe": 1.0, "separation": 100.0, "render": 20.0}, None)
    second = build_report(status(), FOUND, {"render": 25.0}, first)
    assert second.stage_seconds == {"probe": 1.0, "separation": 100.0, "render": 25.0}
    assert second.seconds == 126.0


def test_a_failed_song_has_the_error_and_no_outputs() -> None:
    error = ErrorInfo(stage="render", kind="render-failed", message="boom")
    report = build_report(status("failed", error=error), FOUND, {"render": 3.0}, None)
    assert (report.status, report.error, report.outputs) == ("failed", error, [])


def test_a_song_that_is_still_running_has_no_report() -> None:
    with pytest.raises(ValueError, match="running"):
        build_report(status("running", current="render"), FOUND, {}, None)


def test_the_report_carries_the_note_on_the_countdown() -> None:
    found = Findings(countdown=CountdownNote.of(101.4))
    report = build_report(status(), found, {}, None)
    assert report.countdown == CountdownNote(tempo=101.4, unit="beats")
    assert build_report(status(), FOUND, {}, None).countdown is None  # the tempo stage never ran


def test_a_countdown_without_a_tempo_counts_seconds_and_is_no_reason_for_review() -> None:
    note = CountdownNote.of(None)
    assert (note.tempo, note.unit) == (None, "seconds")
    report = build_report(status(), Findings(countdown=note), {}, None)
    assert (report.status, report.reasons) == ("ok", [])


def test_the_report_file_round_trips() -> None:
    report = build_report(status(), FOUND, {"probe": 0.5}, None)
    assert ReportFile.model_validate_json(report.model_dump_json()) == report


def rows() -> list[SummaryRow]:
    ok = build_report(status(), FOUND, {"probe": 1.0, "separation": 100.0, "render": 24.0}, None)
    review = build_report(
        status("review", ["lyrics: 2 lines flagged", "alignment: 4.2 s gap in line 3"]),
        Findings(duration=240.0),
        {"probe": 1.0, "separation": 190.0},
        None,
    )
    failed = build_report(
        status(
            "failed", error=ErrorInfo(stage="separation", kind="time-limit", message="too slow")
        ),
        Findings(),
        {"probe": 0.5},
        None,
    )
    return [
        row_of_report(ok.model_copy(update={"name": "Artist - First"})),
        row_of_report(review.model_copy(update={"name": "Artist - Second long name"})),
        row_of_report(failed.model_copy(update={"name": "Third"})),
        row_of_status(status("running", current="alignment"), 200.0),
        row_not_run("Fifth"),
    ]


def test_the_summary_is_golden(snapshot: SnapshotAssertion) -> None:
    lines = [*format_rows(rows()), "", total_line(rows(), 650.0)]
    assert "\n".join(lines) == snapshot


def test_the_total_line_names_only_the_counts_there_are() -> None:
    ok = [SummaryRow("ok", "a"), SummaryRow("ok", "b")]
    assert total_line(ok, None) == "2 songs: 2 ok, 0 review, 0 failed"
    assert total_line(ok[:1], 61.0) == "1 song: 1 ok, 0 review, 0 failed in 1m 01s"
    live = [SummaryRow("running", "c"), SummaryRow("interrupted", "d"), row_not_run("e")]
    assert total_line(live, None).endswith("1 running, 1 interrupted, 1 not run")


def test_the_report_text_has_the_date_the_lines_and_the_total(snapshot: SnapshotAssertion) -> None:
    assert report_text(rows(), 650.0, "2026-10-29 12:00") == snapshot


@pytest.mark.parametrize(
    ("states", "code"),
    [
        (["ok", "review"], 0),
        (["ok", "failed"], 1),
        (["ok", "interrupted"], 1),
        (["running"], 1),
        (["ok", "not run"], 0),
        ([], 0),
    ],
)
def test_the_exit_code_is_one_when_a_song_failed_or_was_interrupted(
    states: list[SummaryState], code: int
) -> None:
    summary = [SummaryRow(state, "x") for state in states]
    assert exit_code_of(summary) == code


def test_a_review_song_without_reasons_in_its_report_still_shows_brackets_only_when_asked() -> None:
    row = row_of_status(status("review", ["x: y"]))
    assert row.detail == "(x: y)"
    failed = row_of_status(status("failed", error=ErrorInfo(stage="a", kind="k", message="m")))
    assert failed.detail == "a: m"


def test_a_running_song_has_no_report() -> None:
    with pytest.raises(ValueError, match="still running has no report"):
        build_report(status("running", current="render"), FOUND, {}, None)


def test_the_times_are_rounded_to_hundredths() -> None:
    report = build_report(status(), FOUND, {"probe": 0.123456, "render": 1.004}, None)
    assert report.stage_seconds == {"probe": 0.12, "render": 1.0}
    assert report.seconds == 1.13


def test_a_failed_song_without_an_error_has_an_empty_detail() -> None:
    report = build_report(status("failed"), FOUND, {}, None)
    assert row_of_report(report).detail == ""
    row = row_of_status(status("failed"), 10.0)
    assert (row.state, row.name, row.length, row.detail) == ("failed", "A - B", 10.0, "")


def test_a_row_from_the_status_names_reasons_only_for_review() -> None:
    assert row_of_status(status("ok", ["ignored"])).detail == ""
    assert row_of_status(status("review", ["one", "two"])).detail == "(one; two)"


@pytest.mark.parametrize(
    ("name", "short"),
    [
        ("Juli - Perfekte Welle", "Juli - Perfekte Welle"),
        ("SDP, Sido - Ne Leiche", "SDP, Sido - Ne Leiche"),  # two artists stay
        ("A, B, C, D - Song (feat. C, D)", "A +3 - Song"),
        ("Mark Forster, Sido - Au Revoir (feat. Sido)", "Mark Forster, Sido - Au Revoir"),
        ("A - Zusammen feat. B (feat. B)", "A - Zusammen"),
        ("A - Song - Radio Edit", "A - Song - Radio Edit"),  # only featuring parts go
        ("no dash at all", "no dash at all"),
        ("A - (feat. B)", "A - (feat. B)"),  # nothing would be left of the title
    ],
)
def test_long_names_are_shortened_for_the_summary(name: str, short: str) -> None:
    assert short_name(name) == short


def test_clip_cuts_with_an_ellipsis_only_when_needed() -> None:
    assert clip("abcdef", 6) == "abcdef"
    assert clip("abcdef", 4) == "abc…"
    assert clip("abcdef", 1) == "…"
    assert clip("abcdef", 0) == ""


def test_wide_characters_take_two_columns_and_combining_marks_none() -> None:
    assert columns("abc") == 3
    assert columns("日本語") == 6
    assert columns("e\u0301") == 1  # e with a combining acute accent
    assert columns("ab😀") == 4
    assert columns("ＡＢ") == 4  # fullwidth Latin letters


def test_clip_and_pad_count_columns_not_characters() -> None:
    assert clip("日本語の歌", 6) == "日本…"  # 4 columns of text and the ellipsis
    assert columns(clip("日本語の歌", 6)) <= 6
    assert pad("日本", 6) == "日本  "
    assert pad("abc", 2) == "abc"  # never cut, never padded past the width


def test_a_row_with_a_japanese_name_fits_the_terminal_width() -> None:
    row = SummaryRow("ok", "アーティスト - " + "とても長い歌のタイトル" * 3, 180.0, 60.0, "")
    line = format_row(row, 30, 80)
    assert columns(line) <= 80


def test_the_name_column_is_capped_on_a_terminal_but_not_in_a_file() -> None:
    names = ["Short - Song", "Very Long Artist Name - " + "x" * 80]
    assert name_width(names) == len(short_name(names[1]))
    assert name_width(names, 100) == 50  # half the terminal
    assert name_width(names, 44) == 19  # a narrow terminal: what is left after the first columns
    assert name_width(["A - B"], 100) == 5  # no wider than the longest name
    assert name_width([]) == 0
    assert name_width(names, 10) == 0  # no room left at all


def test_a_row_on_a_terminal_fits_its_width_and_keeps_the_columns() -> None:
    row = SummaryRow("failed", "A, B, C - " + "Title " * 20, 180.0, 1.0, "lyrics: " + "x" * 200)
    line = format_row(row, 30, 100)
    assert len(line) == 100
    assert line.endswith("…")
    assert line.startswith("failed    3:00       1s  A +2 - Title Title Title Titl…  lyrics: ")
    assert format_row(row, 30).endswith("x" * 200)  # a file keeps the whole detail


def test_the_second_voice_lines_come_from_the_mark_the_time_or_the_audio() -> None:
    times = [1.0, 1.0, 5.0, 9.0, 12.0]
    lyrics = LyricsFile.model_construct(
        lines=[
            LyricLine(text="a", singers="1", time=1.0),
            LyricLine(text="b", singers="1", voice=2, time=1.0),
            LyricLine(text="c", singers="1", voice=2, time=5.0),
            LyricLine(text="d", singers="1", time=9.0),
            LyricLine(text="e", singers="1", time=12.0),
        ]
    )
    voices: list[Voice] = [1, 2, 2, 2, 1]  # line 4 found in the audio
    alignment = AlignmentFile.model_construct(
        lines=[
            AlignedLine(start=t, end=t + 1, first_word=i, word_count=1, voice=v)
            for i, (t, v) in enumerate(zip(times, voices, strict=True))
        ]
    )
    found = [(x.line, x.source) for x in second_voice_lines(lyrics, alignment)]
    assert found == [(2, "time"), (3, "mark"), (4, "audio")]
