"""The mark in a lyrics file that Vocatron wrote (ADR-0008: an edited file counts as approved).

Vocatron marks the file it writes after a lookup, so that its origin survives a new work folder:
an ``.lrc`` gets the standard creator tag ``[re: Vocatron <check>]`` as its first row, a ``.txt``
the header key ``written_by: "Vocatron <check>"`` as the first row of its ``---`` block. Players
ignore both. The check is the start of the SHA-256 of the file without that row, so any edit of
the file, and a removed mark, makes it a file that differs from what Vocatron wrote.
"""

import hashlib
import re

from vocatron.core.lyrics.document import HEADER_FENCE, Document, Kind, write

WRITER = "Vocatron"
CREATOR_TAG = "re"
"""The standard LRC tag for the program that made the file."""
CHECK_LENGTH = 16
"""Hex digits of the SHA-256 kept in the mark."""
_PLACEHOLDER = "0" * CHECK_LENGTH
_MARKS: dict[Kind, re.Pattern[str]] = {
    "lrc": re.compile(rf"\[{CREATOR_TAG}: {WRITER} ([0-9a-f]{{{CHECK_LENGTH}}})\]\n"),
    "txt": re.compile(rf'written_by: "{WRITER} ([0-9a-f]{{{CHECK_LENGTH}}})"\n'),
}
_ROWS: dict[Kind, int] = {"lrc": 0, "txt": 1}
"""The row of the mark: the first of an ``.lrc``, the one after the opening fence of a ``.txt``."""


def _check(rows: list[str], kind: Kind) -> str:
    """Return the check of a file: the start of the SHA-256 of all rows but the mark's."""
    rest = rows[: _ROWS[kind]] + rows[_ROWS[kind] + 1 :]
    return hashlib.sha256("".join(rest).encode()).hexdigest()[:CHECK_LENGTH]


def _with_mark(document: Document, check: str) -> Document:
    """Return the document with the mark ``Vocatron <check>``."""
    value = f"{WRITER} {check}"
    if document.kind == "lrc":
        return document.model_copy(update={"tags": ((CREATOR_TAG, value), *document.tags)})
    return document.model_copy(update={"written_by": value})


def write_marked(document: Document) -> str:
    """Write a document as Vocatron writes it next to a song: canonical, with the mark.

    ``document`` itself carries no mark (no ``re`` tag, no ``written_by``).
    """
    draft = write(_with_mark(document, _PLACEHOLDER)).splitlines(keepends=True)
    return write(_with_mark(document, _check(draft, document.kind)))


def written_by_vocatron(text: str, kind: Kind, sha256: str | None = None) -> bool:
    """Tell whether ``text`` is a lyrics file exactly as Vocatron wrote it.

    True only when the mark is in its row and its check fits the rest of the file.

    Args:
        text: The text of the file.
        kind: ``lrc`` or ``txt``.
        sha256: The SHA-256 of the file's bytes, when known: the text must be exactly those
            bytes in UTF-8, so a reader that turns CRLF into LF does not hide an edit.
    """
    if sha256 is not None and hashlib.sha256(text.encode()).hexdigest() != sha256:
        return False
    rows = text.splitlines(keepends=True)
    row = _ROWS[kind]
    if len(rows) <= row or (kind == "txt" and rows[0] != HEADER_FENCE + "\n"):
        return False
    found = _MARKS[kind].fullmatch(rows[row])
    return found is not None and found.group(1) == _check(rows, kind)
