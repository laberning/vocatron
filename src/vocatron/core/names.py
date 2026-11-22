"""Safe file and folder names, and collision resolution (ADR-0006).

A name made here is valid on Linux, macOS and Windows: no forbidden characters, no trailing dot
or space, no reserved device name, bounded length. Making a name safe twice changes nothing.
"""

import re
from collections.abc import Mapping
from pathlib import PurePath

FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
WHITESPACE = re.compile(r"\s+")
RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)
MAX_BYTES = 200  # UTF-8 bytes; leaves room for a suffix and an extension below the 255 limit
FALLBACK = "untitled"


def _truncate(text: str) -> str:
    """Cut ``text`` to ``MAX_BYTES`` UTF-8 bytes without splitting a character."""
    return text.encode()[:MAX_BYTES].decode(errors="ignore")


def safe_name(text: str) -> str:
    """Turn ``text`` into a name that is safe as a file or folder name.

    Forbidden characters become ``_``, runs of white space become one space, leading and
    trailing dots and spaces are removed, a reserved device name (``CON``, also as ``con.txt``)
    gets a ``_`` after it and the name is cut to ``MAX_BYTES`` bytes. An empty result becomes
    ``untitled``.

    Args:
        text: Any text, for example ``Artist - Title``.

    Returns:
        The safe name. ``safe_name(safe_name(x)) == safe_name(x)``.
    """
    name = WHITESPACE.sub(" ", FORBIDDEN.sub("_", text)).strip(" .")
    stem, dot, rest = name.partition(".")
    if stem.rstrip().upper() in RESERVED:  # Windows reserves the part before the first dot
        name = f"{stem}_{dot}{rest}"
    return _truncate(name).strip(" .") or FALLBACK


def resolve_collisions[P: PurePath](wanted: Mapping[P, str]) -> dict[P, str]:
    """Give every source a unique name, stable for the same set of sources.

    Sources are handled in sorted order; the first one keeps its name, later ones with the same
    name (compared case-insensitively) get `` (2)``, `` (3)`` and so on.

    Args:
        wanted: Source path to the safe name it would like.

    Returns:
        Source path to a unique name.
    """
    taken: set[str] = set()
    result: dict[P, str] = {}
    for source in sorted(wanted):
        base = wanted[source]
        name, number = base, 1
        while name.casefold() in taken:
            number += 1
            name = f"{base} ({number})"
        taken.add(name.casefold())
        result[source] = name
    return result
