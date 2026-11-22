"""Song status, the rule that combines stage results, and exit codes (ADR-0006).

``status.json`` is written before and after every stage. The state of a song is ``failed`` when
a stage failed, otherwise ``running`` while stages remain (so a song interrupted by a crash or a
kill never looks finished), otherwise ``review`` when any stage gave a reason, otherwise ``ok``.

A run that stops before the last stage (``vocatron lyrics``) leaves the later stages alone. What
``status.json`` recorded for them still counts if their stage file is still current; otherwise
the stage is ``outdated``, and a stage that was running when an earlier run died is
``interrupted``. Both make the song ``review`` until ``vocatron make`` finishes it.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

State = Literal["running", "ok", "review", "failed"]
Action = Literal["ran", "skipped", "failed", "outdated", "interrupted"]
NOT_FINISHED = "not finished, run `vocatron make`"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


class ErrorInfo(BaseModel):
    """The error that failed a song.

    Attributes:
        stage: The stage that failed.
        kind: A short stable code, or the exception class of an unexpected error.
        message: What went wrong.
    """

    model_config = ConfigDict(extra="forbid")

    stage: str
    kind: str
    message: str


class StageOutcome(BaseModel):
    """What happened to one stage of one song.

    Attributes:
        stage: Name of the stage.
        action: ``ran``, ``skipped`` (output was current), ``failed``, ``outdated`` (its output
            no longer matches its inputs after a partial run) or ``interrupted`` (an earlier run
            died while it was running).
        reasons: The stage's review reasons.
    """

    model_config = ConfigDict(extra="forbid")

    stage: str
    action: Action
    reasons: list[str] = Field(default_factory=list)


class SongStatus(BaseModel):
    """The ``status.json`` of one song.

    Attributes:
        schema_version: Version of this file's schema.
        name: The safe name of the song (track and work folder).
        source: File name of the audio file.
        state: ``running``, ``ok``, ``review`` or ``failed``.
        current: The stage about to run or running while the state is ``running``.
        reasons: Why the song needs review, each prefixed with its stage.
        error: The error when the state is ``failed``.
        stages: What happened to each stage so far, in order.
        updated: When the file was written (ISO 8601, from the injected clock).
    """

    SCHEMA_NAME: ClassVar[str] = "status"
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    name: str
    source: str
    state: State
    current: str | None = None
    reasons: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None
    stages: list[StageOutcome] = Field(default_factory=list)
    updated: str

    @model_validator(mode="after")
    def check_current(self) -> Self:
        """Require ``current`` exactly while the state is ``running``.

        Raises:
            ValueError: If ``current`` is missing while running, or set in a final state.
        """
        if (self.state == "running") != (self.current is not None):
            raise ValueError("current is set exactly while the state is running")
        return self


def combine(
    outcomes: Sequence[StageOutcome], error: ErrorInfo | None, current: str | None
) -> tuple[State, list[str]]:
    """Combine the stage results so far into the state and reasons of a song.

    Args:
        outcomes: Results of the stages handled so far.
        error: The error of the failed stage, if one failed.
        current: The stage about to run, or ``None`` when no stage remains.

    Returns:
        The state and the review reasons, each prefixed with its stage name.
    """
    reasons = [f"{o.stage}: {reason}" for o in outcomes for reason in o.reasons]
    if error is not None or any(o.action == "failed" for o in outcomes):
        return "failed", reasons
    if current is not None:
        return "running", reasons
    return ("review" if reasons else "ok"), reasons


def untouched_results(
    recorded: SongStatus | None,
    untouched: Sequence[str],
    still_current: Mapping[str, list[str] | None],
) -> tuple[list[StageOutcome], ErrorInfo | None]:
    """Return what ``status.json`` records for the stages a partial run leaves alone.

    A partial run (``vocatron lyrics``) replaces the results of its own stages and keeps these,
    so the song status still covers the whole pipeline. A recorded result stays only if the
    stage's file is still current for its inputs and settings; otherwise the stage is
    ``outdated``. A stage that was running when the earlier run died is ``interrupted``. Both
    carry the reason ``NOT_FINISHED``. A recorded failure stays.

    Args:
        recorded: The status before the run, if there is a valid one.
        untouched: The names of the stages the run does not handle, in order.
        still_current: For each of them whose stage file is current now its review reasons,
            for the others ``None`` (a missing entry counts as not current).

    Returns:
        Their outcomes in order, and the recorded error if one of them failed.
    """
    if recorded is None:
        return [], None
    by_stage = {o.stage: o for o in recorded.stages if o.stage in untouched}
    if recorded.state == "running" and (died := recorded.current) in untouched and died is not None:
        by_stage[died] = StageOutcome(stage=died, action="interrupted")
    kept: list[StageOutcome] = []
    for name in untouched:
        outcome = by_stage.get(name)
        if outcome is None or outcome.action == "failed":
            if outcome is not None:
                kept.append(outcome)
            continue
        reasons = None if outcome.action == "interrupted" else still_current.get(name)
        if reasons is None:
            action = "interrupted" if outcome.action == "interrupted" else "outdated"
            kept.append(StageOutcome(stage=name, action=action, reasons=[NOT_FINISHED]))
        else:
            action = "skipped" if outcome.action == "outdated" else outcome.action
            kept.append(StageOutcome(stage=name, action=action, reasons=reasons))
    error = recorded.error
    return kept, error if error is not None and error.stage in untouched else None


def exit_code(states: Iterable[State]) -> int:
    """Return the process exit code for a batch: 1 if any song failed or was interrupted, else 0.

    A stored ``running`` state means the run of that song was interrupted.
    """
    return EXIT_FAILED if any(state in {"failed", "running"} for state in states) else EXIT_OK
