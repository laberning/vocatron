"""Typed errors of the pipeline (ADR-0006).

A stage reports a failure it understands with ``StageError``; the batch runner turns it, and
any unexpected exception, into a ``failed`` status of that one song.
"""


class StageError(Exception):
    """A stage failed for a reason the user can act on.

    Attributes:
        kind: A short stable code such as ``unreadable-audio``.
    """

    def __init__(self, kind: str, message: str) -> None:
        """Create the error.

        Args:
            kind: A short stable code, shown in the status.
            message: What went wrong, in a sentence a user can act on.
        """
        super().__init__(message)
        self.kind = kind


class UsageError(Exception):
    """The command was used wrongly (a missing input, an empty folder); exit code 2."""
