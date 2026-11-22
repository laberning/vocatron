"""How long a batch will take: speeds per stage, the time left, and how to show times.

Every stage has a speed, the seconds of work per second of audio. The defaults come from our own
measurements; each finished stage teaches the speed of its stage on its device, as a running
average, so the estimate fits the machine after a few songs. The time left of a batch is the rest
of the current song (scaled by the measured progress of its stage) plus the songs after it; a
stage that will be skipped counts zero. Everything here is a pure function or a model; the files
and the clock are the stages' business (ADR-0006, ADR-0007).
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_SPEEDS: Mapping[str, float] = {
    "probe": 0.0,
    "lyrics": 0.0,
    "separation": 0.6,
    "tempo": 0.002,
    "alignment": 0.05,
    "syllables": 0.001,
    "layout": 0.0003,
    "render": 0.07,
    "cdg": 0.0,  # nothing when CD+G is off; a run that makes it teaches the speed
}
"""Seconds of work per second of audio, measured on the development machine (8 GiB laptop GPU)."""
DEFAULT_LENGTH = 240.0
"""The length assumed for a song whose length is not known."""
WINDOW = 10
"""A learnt speed is the average of about this many of the latest runs."""
STALE_AFTER = 120.0
"""A ``progress.json`` that was not touched for this many seconds is from a run that died."""
PROGRESS_FILE = "progress.json"
"""The name of the file in the work folder of the song being made."""
WRITE_EVERY = 2.0
"""``progress.json`` is written at most this often (seconds)."""

type Plan = Mapping[str, float]
"""The expected seconds of each stage that will run for one song, in pipeline order."""


class SpeedEntry(BaseModel):
    """A learnt speed.

    Attributes:
        speed: Seconds of work per second of audio.
        runs: How many runs went into it (capped at ``WINDOW``).
    """

    model_config = ConfigDict(extra="forbid")

    speed: float = Field(ge=0)
    runs: int = Field(ge=1)


class Timings(BaseModel):
    """The learnt speeds of this machine (``.cache/timings.json`` in the clone, never in git).

    Attributes:
        schema_version: Version of this file's schema.
        speeds: The learnt speed by ``stage:device``.
        devices: The device a stage ran on last, by stage; the estimate before a run assumes it.
    """

    SCHEMA_NAME: ClassVar[str] = "timings"
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    speeds: dict[str, SpeedEntry] = Field(default_factory=dict)
    devices: dict[str, str] = Field(default_factory=dict)


def speed_key(stage: str, device: str) -> str:
    """Return the key of a learnt speed."""
    return f"{stage}:{device}"


def speed_of(timings: Timings, stage: str, device: str | None = None) -> float:
    """Return the speed to expect for ``stage``: the learnt one, else the default.

    The learnt speed is the one for ``device``, or for the device the stage ran on last.

    Args:
        timings: The learnt speeds.
        stage: The stage name.
        device: The device the stage will run on, or ``None`` when not known yet.

    Returns:
        Seconds of work per second of audio; 0 for a stage with no default.
    """
    chosen = device or timings.devices.get(stage)
    entry = timings.speeds.get(speed_key(stage, chosen)) if chosen else None
    return entry.speed if entry is not None else DEFAULT_SPEEDS.get(stage, 0.0)


def learn(timings: Timings, stage: str, device: str, seconds: float, length: float) -> Timings:
    """Return ``timings`` taught that ``stage`` took ``seconds`` for ``length`` seconds of audio.

    A run with no length or no time teaches nothing.
    """
    if length <= 0 or seconds <= 0:
        return timings
    key = speed_key(stage, device)
    old = timings.speeds.get(key)
    observed = seconds / length
    runs = 1 if old is None else min(old.runs + 1, WINDOW)
    speed = observed if old is None else old.speed + (observed - old.speed) / runs
    return Timings(
        speeds={**timings.speeds, key: SpeedEntry(speed=speed, runs=runs)},
        devices={**timings.devices, stage: device},
    )


def expected(stages: Sequence[str], length: float | None, timings: Timings) -> dict[str, float]:
    """Return the expected seconds of each of ``stages`` for a song of ``length`` seconds."""
    seconds = DEFAULT_LENGTH if length is None else length
    return {stage: speed_of(timings, stage) * seconds for stage in stages}


def song_left(plan: Plan, finished: Sequence[str], current: str | None, fraction: float) -> float:
    """Return the seconds a song still needs.

    Args:
        plan: The expected seconds of its stages.
        finished: The stages that are done.
        current: The stage that is running, if any.
        fraction: How far the current stage is (0 to 1).
    """
    done = set(finished)
    left = sum(seconds for stage, seconds in plan.items() if stage not in done and stage != current)
    if current is not None and current in plan:
        left += plan[current] * (1 - min(max(fraction, 0.0), 1.0))
    return left


def percent(left: float, total: float, finished: int, songs: int) -> int:
    """Return how far a batch is in percent.

    By time when stages with work are planned, else by the number of songs (a batch that skips
    everything has no time to go by).
    """
    if total > 0:
        return round(100 * min(max(1 - left / total, 0.0), 1.0))
    return round(100 * finished / songs) if songs else 100


def format_duration(seconds: float | None) -> str:
    """Return a duration for people: ``45s``, ``2m 05s``, ``1h 02m``; ``?`` when not known."""
    if seconds is None:
        return "?"
    whole = round(max(seconds, 0.0))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def format_length(seconds: float | None) -> str:
    """Return the length of a song as ``m:ss``; ``-`` when not known."""
    if seconds is None:
        return "-"
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}:{secs:02d}"


class ProgressFile(BaseModel):
    """``progress.json`` in the work folder of the song being made, for ``vocatron status``.

    It exists while the song is made and is removed when the song is done; one that is old
    belongs to a run that died.

    Attributes:
        schema_version: Version of this file's schema.
        stage: The stage that is running.
        fraction: How far that stage is (0 to 1).
        left: The seconds the song still needs, or ``None`` when not known.
        updated: When the file was written (ISO 8601, from the injected clock).
    """

    SCHEMA_NAME: ClassVar[str] = "progress"
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    stage: str
    fraction: float = Field(ge=0, le=1)
    left: float | None = None
    updated: str


def is_fresh(file: ProgressFile, now: datetime) -> bool:
    """Tell whether a ``progress.json`` belongs to a run that is still going.

    One that was not touched for ``STALE_AFTER`` seconds, or whose time cannot be read, belongs
    to a run that died.
    """
    try:
        written = datetime.fromisoformat(file.updated)
    except ValueError:
        return False
    return abs((now - written).total_seconds()) < STALE_AFTER


def progress_text(stage: str, fraction: float, left: float | None) -> str:
    """Return ``separation 41%, about 3m 20s left`` for a running stage."""
    return f"{stage} {round(fraction * 100)}%, about {format_duration(left)} left"
