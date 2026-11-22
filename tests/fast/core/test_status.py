"""Stage 1: the rule that combines stage results, and exit codes."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from vocatron.core.status import (
    NOT_FINISHED,
    ErrorInfo,
    SongStatus,
    StageOutcome,
    State,
    combine,
    exit_code,
    untouched_results,
)

outcome = st.builds(
    StageOutcome,
    stage=st.sampled_from(["a", "b"]),
    action=st.sampled_from(["ran", "skipped"]),
    reasons=st.lists(st.text(min_size=1, max_size=5), max_size=2),
)
ERROR = ErrorInfo(stage="a", kind="k", message="m")


@given(st.lists(outcome, max_size=4))
def test_without_failure_the_state_follows_the_reasons(outcomes: list[StageOutcome]) -> None:
    state, reasons = combine(outcomes, None, None)
    assert state == ("review" if reasons else "ok")
    assert len(reasons) == sum(len(o.reasons) for o in outcomes)


@given(st.lists(outcome, max_size=4))
def test_an_error_always_means_failed(outcomes: list[StageOutcome]) -> None:
    assert combine(outcomes, ERROR, None)[0] == "failed"
    assert combine(outcomes, ERROR, "b")[0] == "failed"


@given(st.lists(outcome, max_size=4))
def test_while_a_stage_remains_the_song_is_running(outcomes: list[StageOutcome]) -> None:
    state, reasons = combine(outcomes, None, "next")
    assert state == "running"
    assert reasons == combine(outcomes, None, None)[1]  # the reasons so far are kept


def test_a_failed_outcome_means_failed_and_reasons_name_their_stage() -> None:
    outcomes = [
        StageOutcome(stage="lyrics", action="ran", reasons=["unsure"]),
        StageOutcome(stage="sync", action="failed"),
    ]
    assert combine(outcomes, None, "render") == ("failed", ["lyrics: unsure"])


def test_exit_code() -> None:
    states: list[State] = ["ok", "review"]
    assert exit_code(states) == 0
    assert exit_code([*states, "failed"]) == 1
    assert exit_code([*states, "running"]) == 1  # a stored running state: interrupted
    assert exit_code([]) == 0


@pytest.mark.parametrize(
    ("state", "current", "valid"),
    [("running", "probe", True), ("running", None, False), ("ok", None, True), ("ok", "a", False)],
)
def test_current_is_set_exactly_while_running(
    state: State, current: str | None, valid: bool
) -> None:
    def build() -> SongStatus:
        return SongStatus(name="n", source="s", state=state, current=current, updated="t")

    if valid:
        assert build().current == current
    else:
        with pytest.raises(ValidationError, match="current is set exactly while"):
            build()


def recorded_status(
    *, state: State = "failed", current: str | None = None, error: ErrorInfo | None = None
) -> SongStatus:
    return SongStatus(
        name="n",
        source="s",
        state=state,
        current=current,
        error=error,
        stages=[
            StageOutcome(stage="a", action="ran"),
            StageOutcome(stage="b", action="ran", reasons=["r"]),
            StageOutcome(stage="c", action="failed"),
        ],
        updated="t",
    )


FAILED_C = ErrorInfo(stage="c", kind="k", message="m")


def test_a_partial_run_keeps_only_the_results_of_the_stages_it_leaves_alone() -> None:
    recorded = recorded_status(error=FAILED_C)
    kept, error = untouched_results(recorded, ["b", "c"], {"b": ["r"]})
    assert [o.stage for o in kept] == ["b", "c"]
    assert error == recorded.error
    kept, error = untouched_results(recorded, ["b"], {"b": ["r"]})
    assert ([o.stage for o in kept], error) == (["b"], None)
    assert untouched_results(recorded_status(), ["c"], {})[1] is None
    assert untouched_results(None, ["b"], {}) == ([], None)


def test_a_later_stage_whose_file_is_still_current_keeps_its_reasons() -> None:
    kept, _ = untouched_results(recorded_status(), ["b"], {"b": ["fresh reason"]})
    assert kept == [StageOutcome(stage="b", action="ran", reasons=["fresh reason"])]


def test_a_later_stage_whose_file_is_not_current_any_more_is_outdated_and_needs_review() -> None:
    kept, _ = untouched_results(recorded_status(), ["b"], {"b": None})
    assert kept == [StageOutcome(stage="b", action="outdated", reasons=[NOT_FINISHED])]
    assert untouched_results(recorded_status(), ["b"], {})[0] == kept  # no entry: not current
    state, reasons = combine(kept, None, None)
    assert (state, reasons) == ("review", ["b: not finished, run `vocatron make`"])


def test_a_stage_that_was_running_when_the_earlier_run_died_stays_interrupted() -> None:
    recorded = recorded_status(state="running", current="b")
    kept, _ = untouched_results(recorded, ["b", "c"], {"b": ["r"], "c": None})
    assert kept[0] == StageOutcome(stage="b", action="interrupted", reasons=[NOT_FINISHED])
    assert kept[1].action == "failed"  # a recorded failure stays
    only, _ = untouched_results(recorded_status(state="running", current="z"), ["b"], {"b": ["r"]})
    assert only[0].action == "ran"  # the interrupted stage is not one this run leaves alone


def test_an_outdated_stage_that_is_current_again_is_skipped_not_outdated() -> None:
    recorded = recorded_status()
    recorded = recorded.model_copy(
        update={"stages": [StageOutcome(stage="b", action="outdated", reasons=[NOT_FINISHED])]}
    )
    kept, _ = untouched_results(recorded, ["b"], {"b": []})
    assert kept == [StageOutcome(stage="b", action="skipped")]


def test_a_later_stage_the_status_never_recorded_is_skipped_over_not_the_end() -> None:
    recorded = recorded_status()
    kept, _ = untouched_results(recorded, ["never", "b"], {"b": ["r"]})
    assert [o.stage for o in kept] == ["b"]
