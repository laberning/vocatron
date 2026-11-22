"""A clock that moves only when asked."""

from datetime import UTC, datetime, timedelta


class FakeClock:
    """Starts at a fixed time and advances by ``step`` on every ``now()`` call."""

    def __init__(
        self, start: datetime = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), step: float = 1.0
    ) -> None:
        self._current = start
        self._step = timedelta(seconds=step)
        self.elapsed = 0.0  # what ``monotonic`` says; tests and fake engines move it with ``wait``

    def now(self) -> datetime:
        current = self._current
        self._current += self._step
        return current

    def monotonic(self) -> float:
        return self.elapsed

    def wait(self, seconds: float) -> None:
        """Let ``seconds`` pass on the monotonic clock."""
        self.elapsed += seconds
