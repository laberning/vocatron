"""The real clock: the time of day, and a monotonic clock for measuring how long things take."""

import time
from datetime import UTC, datetime


class SystemClock:
    """The current time of the system, in UTC."""

    def now(self) -> datetime:
        """Return the current time in UTC."""
        return datetime.now(UTC)

    def monotonic(self) -> float:
        """Return seconds on a clock that only moves forward, for measuring durations."""
        return time.monotonic()
