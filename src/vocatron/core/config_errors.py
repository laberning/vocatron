"""Point a configuration error at a line and column of the YAML file (ADR-0002).

The YAML loader (an engine) reports where every key stands; Pydantic reports the location of an
error as a path of keys. This module joins the two without touching a file.
"""

from collections.abc import Mapping, Sequence
from typing import NamedTuple

Location = tuple[str | int, ...]
Positions = Mapping[Location, tuple[int, int]]


class Issue(NamedTuple):
    """One problem found in a configuration.

    Attributes:
        loc: Path of keys to the problem, empty for the whole document.
        message: What is wrong.
    """

    loc: Location
    message: str


def locate(loc: Location, positions: Positions) -> tuple[int, int]:
    """Return the line and column (both from 1) of the deepest known key on ``loc``.

    Falls back to the start of the document when no part of the path is known.
    """
    key = loc
    while (found := positions.get(key)) is None:
        if not key:
            return (1, 1)
        key = key[:-1]
    return found


def describe(file: str, issue: Issue, positions: Positions) -> str:
    """Format an issue as ``file:line:column: path: message``."""
    line, column = locate(issue.loc, positions)
    where = ".".join(str(part) for part in issue.loc)
    prefix = f"{file}:{line}:{column}: "
    return f"{prefix}{where}: {issue.message}" if where else f"{prefix}{issue.message}"


def describe_all(file: str, issues: Sequence[Issue], positions: Positions) -> list[str]:
    """Format every issue, in the order they were found."""
    return [describe(file, issue, positions) for issue in issues]
