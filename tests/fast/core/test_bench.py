"""Stage 1: the metrics of the sync benchmark and the rule that fails it."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vocatron.core.bench import (
    BenchRun,
    SongResult,
    bench_files,
    failures,
    language_problem,
    line_errors,
    run_of,
    song_result,
    summarise,
)
from vocatron.core.languages import LANGUAGES


def song(*errors_ms: float, status: str = "ok", corrected: bool = True) -> SongResult:
    """A song whose corrected errors equal its absolute ones (or are missing: an old result)."""
    return SongResult.model_validate(
        {
            "status": status,
            "lines": len(errors_ms),
            "compared": len(errors_ms),
            "errors_ms": errors_ms,
            "corrected_errors_ms": errors_ms if corrected else None,
        }
    )


def test_a_line_error_is_found_minus_reference_in_milliseconds() -> None:
    assert line_errors([1.0, 2.5, None, 4.0], [1.1, 2.0, 3.0, None]) == pytest.approx(
        [-100.0, 500.0]
    )


def test_the_summary_has_median_and_shares_within_200_and_500_ms() -> None:
    summary = summarise([50.0, 100.0, 200.0, 400.0, 900.0])
    assert (summary.count, summary.median_ms) == (5, 200.0)
    assert (summary.within_200_ms, summary.within_500_ms) == (0.6, 0.8)
    empty = summarise([])
    assert (empty.count, empty.median_ms, empty.within_200_ms) == (0, None, None)


def test_a_song_result_keeps_absolute_errors_and_the_median_offset() -> None:
    result = song_result("review", ["r"], [1.0, 2.0, 3.0, None], [0.9, 2.2, None, 4.0], 0.05, 12.34)
    assert (result.lines, result.compared) == (4, 2)
    assert result.errors_ms == [100.0, 200.0]
    assert result.offset_ms == pytest.approx(-50.0)
    assert (result.estimated_share, result.seconds, result.reasons) == (0.05, 12.3, ["r"])
    unmatched = song_result("ok", [], [None], [None], None, 1.0)
    assert (unmatched.offset_ms, unmatched.corrected_errors_ms) == (None, [])


def test_all_songs_are_pooled_for_the_overall_summary() -> None:
    run = run_of({"a": song(100.0, 100.0, 100.0), "b": song(900.0)})
    assert (run.overall.count, run.overall.median_ms) == (4, 100.0)


def test_a_run_within_the_limit_and_the_baseline_passes() -> None:
    last = run_of({"a": song(150.0, 160.0)})
    assert failures(last, None) == []
    assert failures(last, run_of({"a": song(120.0)})) == []  # 35 ms worse is allowed


def test_a_median_above_200_ms_fails() -> None:
    (message,) = failures(run_of({"a": song(250.0, 260.0)}), None)
    assert message == "overall corrected median error 255 ms is above the 200 ms limit"


def test_more_than_50_ms_worse_than_the_baseline_fails() -> None:
    (message,) = failures(run_of({"a": song(160.0)}), run_of({"a": song(100.0)}))
    assert "60 ms worse than the baseline (100 ms; allowed: 50 ms)" in message
    assert message.startswith("overall corrected median error 160 ms")


def test_a_failed_song_fails_the_run_and_no_comparison_at_all_does_too() -> None:
    assert failures(run_of({"a": song(100.0), "b": song(status="failed")}), None) == [
        "b: the run failed"
    ]
    assert failures(run_of({"a": song()}), None) == [
        "no line start could be compared with a reference"
    ]


def test_a_run_survives_a_trip_through_json() -> None:
    run = run_of({"a": song(100.0, 300.0)})
    assert BenchRun.model_validate_json(run.model_dump_json()) == run


def test_errors_and_the_offset_are_kept_to_a_tenth_of_a_millisecond() -> None:
    result = song_result("ok", [], [1.123456, 2.0], [1.0, 2.0], None, 1.0)
    assert result.errors_ms == [123.5, 0.0]
    assert result.offset_ms == 61.7  # the median of 123.456 and 0


def test_the_limits_are_inclusive() -> None:
    assert summarise([200.0, 500.0]).within_200_ms == 0.5
    assert summarise([200.0, 500.0]).within_500_ms == 1.0
    at_limit = run_of({"a": song(200.0)})
    assert failures(at_limit, None) == []
    assert failures(run_of({"a": song(150.0)}), run_of({"a": song(100.0)})) == []


def test_the_corrected_error_removes_the_constant_shift_of_a_song() -> None:
    # signed errors 560, 570, 580, 900: offset 575; corrected 15, 5, 5, 325
    result = song_result("ok", [], [10.56, 20.57, 30.58, 40.9], [10.0, 20.0, 30.0, 40.0], None, 1.0)
    assert result.errors_ms == [560.0, 570.0, 580.0, 900.0]
    assert result.offset_ms == 575.0
    assert result.corrected_errors_ms == [15.0, 5.0, 5.0, 325.0]


def test_the_corrected_errors_are_rounded_to_a_tenth_of_a_millisecond() -> None:
    # signed errors 0, 12.34, 100: offset 12.34; corrected 12.34, 0, 87.66
    result = song_result("ok", [], [1.0, 2.01234, 3.1], [1.0, 2.0, 3.0], None, 1.0)
    assert result.corrected_errors_ms == [12.3, 0.0, 87.7]


def test_line_starts_and_reference_times_must_be_as_many() -> None:
    with pytest.raises(ValueError, match="zip"):
        line_errors([1.0, 2.0], [1.0])


def test_the_overall_corrected_summary_pools_the_corrected_errors() -> None:
    shifted = song_result("ok", [], [1.6, 2.6, 3.6], [1.0, 2.0, 3.0], None, 1.0)  # shift 600 ms
    exact = song_result("ok", [], [1.1, 2.0, 3.0], [1.0, 2.0, 3.0], None, 1.0)
    run = run_of({"a": shifted, "b": exact})
    assert run.overall.median_ms == pytest.approx(350.0)
    assert run.overall_corrected is not None
    assert run.overall_corrected.count == 6
    assert run.overall_corrected.median_ms == 0.0
    assert run.overall_corrected.within_200_ms == 1.0


def test_a_shifted_reference_passes_by_its_corrected_error_only() -> None:
    shifted = song_result("ok", [], [1.6, 2.6, 3.6, 4.6], [1.0, 2.0, 3.0, 4.0], None, 1.0)
    run = run_of({"a": shifted})
    assert run.overall.median_ms == 600.0
    assert failures(run, None) == []


def test_a_baseline_without_corrected_values_is_judged_by_the_limit_only() -> None:
    old = run_of({"a": song(10.0, corrected=False)})
    assert old.overall_corrected is None
    assert failures(run_of({"a": song(190.0)}), old) == []  # 180 ms worse, but no corrected value
    assert failures(run_of({"a": song(250.0)}), old) != []


def test_a_run_without_corrected_values_is_judged_by_its_absolute_median() -> None:
    old = run_of({"a": song(250.0, corrected=False), "b": song()})
    assert old.overall_corrected is None
    assert failures(old, None) == ["overall median error 250 ms is above the 200 ms limit"]
    mixed = run_of({"a": song(10.0, corrected=False), "b": song(20.0)})
    assert mixed.overall_corrected is None  # no corrected summary from part of the songs


def test_a_version_1_file_is_still_readable() -> None:
    text = (
        '{"schema_version": 1, "songs": {"a": {"status": "ok", "lines": 1, "compared": 1,'
        ' "errors_ms": [100.0], "offset_ms": 100.0}}, "overall": {"count": 1, "median_ms": 100.0,'
        ' "within_200_ms": 1.0, "within_500_ms": 1.0}}'
    )
    run = BenchRun.model_validate_json(text)
    assert (run.overall_corrected, run.songs["a"].corrected_errors_ms) == (None, None)
    assert (
        BenchRun.model_validate_json(run_of({"a": song(1.0)}).model_dump_json()).schema_version == 2
    )


_times = st.lists(st.floats(0, 600, allow_nan=False), min_size=1, max_size=30)


@given(
    _times,
    st.lists(st.floats(-2, 2, allow_nan=False), min_size=30, max_size=30),
    st.floats(-30, 30),
)
def test_a_constant_shift_of_the_reference_changes_the_absolute_not_the_corrected_error(
    reference: list[float], noise: list[float], shift: float
) -> None:
    found = [r + n for r, n in zip(reference, noise, strict=False)]
    base = song_result("ok", [], found, reference, None, 1.0)
    moved = song_result("ok", [], found, [r + shift for r in reference], None, 1.0)
    assert base.corrected_errors_ms == pytest.approx(moved.corrected_errors_ms, abs=0.2)
    assert all(e >= 0 for e in moved.corrected_errors_ms or [])
    assert base.offset_ms is not None and moved.offset_ms is not None
    assert moved.offset_ms == pytest.approx(base.offset_ms - shift * 1000.0, abs=0.2)


def medians(reference: list[float], noise: list[float], shift: float) -> tuple[float, float]:
    """The corrected and absolute median of lines found ``noise + shift`` after the reference."""
    found = [r + n + shift for r, n in zip(reference, noise, strict=False)]
    result = song_result("ok", [], found, reference, None, 1.0)
    corrected = summarise(result.corrected_errors_ms or []).median_ms
    absolute = summarise(result.errors_ms).median_ms
    assert corrected is not None and absolute is not None
    return corrected, absolute


@given(
    _times,
    st.lists(st.floats(0, 2, allow_nan=False), min_size=30, max_size=30),
    st.floats(0, 30),
)
def test_for_errors_of_one_sign_the_corrected_median_is_not_above_the_absolute_median(
    reference: list[float], noise: list[float], shift: float
) -> None:
    corrected, absolute = medians(reference, noise, shift)
    assert corrected <= absolute + 0.2  # rounding to a tenth of a millisecond


@given(
    _times,
    st.lists(st.floats(-2, 2, allow_nan=False), min_size=30, max_size=30),
    st.floats(-30, 30),
)
def test_the_corrected_median_is_at_most_twice_the_absolute_median(
    reference: list[float], noise: list[float], shift: float
) -> None:
    corrected, absolute = medians(reference, noise, shift)
    assert corrected <= 2 * absolute + 0.4  # rounding to a tenth of a millisecond


def test_with_errors_of_both_signs_the_corrected_median_can_be_above_the_absolute_one() -> None:
    # signed errors -100, 0, 100, 9900, 10000: offset 100; corrected 200, 100, 0, ...
    result = song_result(
        "ok", [], [0.9, 2.0, 3.1, 13.9, 15.0], [1.0, 2.0, 3.0, 4.0, 5.0], None, 1.0
    )
    assert summarise(result.errors_ms).median_ms == pytest.approx(100.0)
    assert summarise(result.corrected_errors_ms or []).median_ms == pytest.approx(200.0)


@pytest.mark.parametrize(
    ("language", "model", "names"),
    [
        ("de", None, ("songs", "work", "last.json", "baseline.json")),
        ("de", "m", ("songs", "work-m", "last-m.json", "baseline.json")),
        ("en", None, ("songs-en", "work-en", "last-en.json", "baseline-en.json")),
        ("en", "m", ("songs-en", "work-m-en", "last-m-en.json", "baseline-en.json")),
    ],
)
def test_german_keeps_its_names_and_another_language_appends_its_code(
    language: str, model: str | None, names: tuple[str, str, str, str]
) -> None:
    assert tuple(bench_files(language, model)) == names


def test_no_two_languages_share_a_file() -> None:
    codes = list(LANGUAGES)
    for model in (None, "m"):
        names = [bench_files(code, model) for code in codes]
        for field in ("songs", "work", "last", "baseline"):
            values = [getattr(n, field) for n in names]
            assert len(set(values)) == len(values), field
    assert bench_files("en", "m").baseline == bench_files("en").baseline  # no model in a baseline


def test_a_song_is_in_the_right_folder_when_its_language_matches_or_is_not_known() -> None:
    assert language_problem("de", "de") is None
    assert language_problem(None, "en") is None  # the lyrics stage failed: a failure of its own
    assert language_problem("en", "de") == (
        "the lyrics are in language en, this corpus folder is for de"
    )
