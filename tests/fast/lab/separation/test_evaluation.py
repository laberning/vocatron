"""Stage 1: grouping, timing summary and finalist proposal of the objective evaluation."""

import math

from vocatron.core.models import DEFAULT_VOCALS_MODEL, VOCALS_MODELS
from vocatron.lab.separation.evaluation import (
    ALL,
    REFERENCE,
    Timing,
    ensemble_name,
    group_rows,
    plus_minus,
    propose_finalists,
    timing_summary,
)
from vocatron.lab.separation.metrics import Scores, Summary


def scores(sdr: float, fullness: float = 30.0) -> Scores:
    return Scores(sdr=sdr, si_sdr=sdr - 1, fullness=fullness, bleedless=40.0)


def test_the_reference_is_the_registered_model_of_the_comparison_not_the_new_default() -> None:
    assert REFERENCE == "bs-roformer-ep317"
    assert REFERENCE in VOCALS_MODELS
    assert REFERENCE != DEFAULT_VOCALS_MODEL


def test_scores_are_summarised_over_all_material_and_per_group() -> None:
    table = group_rows(
        {"a": scores(10), "b": scores(12), "c": scores(20)},
        {"a": "official", "b": "official", "c": "woodward", "unscored": "x"},
    )
    assert list(table) == [ALL, "official", "woodward"]
    assert table[ALL]["sdr"].mean == 14
    assert table[ALL]["sdr"].count == 3
    assert table["official"]["sdr"].mean == 11
    assert table["official"]["sdr"].error > 0
    assert table["woodward"]["si_sdr"].mean == 19
    assert math.isnan(table["woodward"]["sdr"].error)


def test_speed_is_seconds_per_second_of_audio_and_memory_is_the_peak() -> None:
    timings = [Timing(name="a", audio_seconds=100, seconds=50, peak_vram_gib=2.0),
               Timing(name="b", audio_seconds=100, seconds=70, peak_vram_gib=3.5)]  # fmt: skip
    assert timing_summary(timings) == (0.6, 3.5)
    assert timing_summary([]) == (None, None)
    assert timing_summary([Timing(name="c", audio_seconds=1, seconds=1)]) == (1.0, None)


def test_the_finalists_are_the_best_by_sdr_without_the_reference() -> None:
    means = {
        "bs-roformer-ep317": (17.9, 30.0),
        "a": (17.5, 34.0),
        "b": (17.4, 35.0),
        "c": (17.0, 33.0),
        "d": (16.0, 40.0),
        "e": (math.nan, math.nan),
    }
    assert propose_finalists(means) == ["a", "b", "c"]
    assert propose_finalists(means, count=2) == ["a", "b"]


def test_a_fuller_candidate_close_to_the_best_takes_the_last_place() -> None:
    means = {"a": (17.5, 34.0), "b": (17.4, 33.0), "c": (17.35, 32.0), "d": (17.3, 38.0)}
    assert propose_finalists(means) == ["a", "b", "d"]
    means["d"] = (17.1, 38.0)  # fuller, but more than 0.2 dB below the best
    assert propose_finalists(means) == ["a", "b", "c"]
    means["d"] = (17.3, 33.5)  # within 0.2 dB, but not fuller than every finalist
    assert propose_finalists(means) == ["a", "b", "c"]


def test_nothing_is_proposed_without_measurements() -> None:
    assert propose_finalists({}) == []
    assert propose_finalists({"bs-roformer-ep317": (18.0, 30.0)}) == []


def test_numbers_are_formatted_with_their_error() -> None:
    assert plus_minus(Summary(1.234, 0.056, 4)) == "1.23 ± 0.06"
    assert plus_minus(Summary(1.234, math.nan, 1)) == "1.23"
    assert plus_minus(Summary(math.nan, math.nan, 0)) == "-"


def test_an_ensemble_is_named_after_its_members() -> None:
    assert ensemble_name(("x", "y")) == "ensemble x + y"


def test_the_finalists_are_ranked_by_sdr_not_by_name() -> None:
    means = {"zeta": (17.5, 30.0), "alpha": (17.0, 30.0), "mid": (17.2, 30.0), "beta": (16.0, 30.0)}
    assert propose_finalists(means) == ["zeta", "mid", "alpha"]


def test_the_margin_counts_from_the_best_and_its_edge_is_included() -> None:
    # 0.25 dB below the best, but only 0.15 dB below the second: not close enough
    means = {"a": (17.5, 30.0), "b": (17.4, 31.0), "c": (17.0, 31.0), "d": (17.25, 40.0)}
    assert propose_finalists(means, count=2) == ["a", "b"]
    # exactly the margin below the best (0.5 - 0.3 is exactly 0.2) still counts
    means = {"a": (0.5, 30.0), "b": (0.45, 31.0), "c": (0.3, 40.0)}
    assert propose_finalists(means, count=2) == ["a", "c"]


def test_as_full_as_a_finalist_is_not_fuller() -> None:
    means = {"a": (17.5, 34.0), "b": (17.4, 33.0), "c": (17.4, 34.0)}
    assert propose_finalists(means, count=2) == ["a", "b"]


def test_the_fullest_of_several_close_candidates_takes_the_place() -> None:
    means = {
        "a": (17.5, 30.0),
        "b": (17.45, 31.0),
        "z": (17.38, 39.0),  # first in SDR order and last by name, but less full
        "m": (17.36, 40.0),
    }
    assert propose_finalists(means, count=2) == ["a", "m"]
