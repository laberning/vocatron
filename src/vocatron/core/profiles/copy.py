"""Make an editable copy of a built-in profile (ADR-0019)."""

import json
import re

NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
"""What a profile name may look like: letters, digits, ``_``, ``.`` and ``-``; no path."""
COPY_PREFIX = "my-"


def valid_name(name: str) -> bool:
    """Tell whether ``name`` can be a profile name: it is also the name of its file."""
    return NAME_PATTERN.fullmatch(name) is not None


def default_name(source: str) -> str:
    """Return the name a copy of ``source`` gets when none is given."""
    return f"{COPY_PREFIX}{source}"


def copy_text(text: str, source: str, name: str, version: str, choose: str | None = None) -> str:
    """Return the text of the built-in profile ``source`` as a new profile called ``name``.

    A header comment says where the copy comes from and how to check and choose it; the
    ``name:`` line is replaced.

    Args:
        text: The YAML text of the built-in profile.
        source: Its name.
        name: The name of the copy.
        version: The Vocatron version that made the copy.
        choose: How the copy is checked and chosen: its path when it is not in the profiles
            folder; default ``name``.

    Raises:
        ValueError: If the text has no ``name:`` line.
    """
    lines = text.splitlines()
    found = [i for i, line in enumerate(lines) if line.startswith("name:")]
    if not found:
        raise ValueError(f"the profile {source} has no name: line")
    lines[found[0]] = f"name: {json.dumps(name)}"
    chosen_by = name if choose is None else choose
    header = (
        f"# A copy of the built-in profile {source}, made by Vocatron {version}.",
        f"# Edit it, check it with `vocatron profiles check {chosen_by}`, then choose it with",
        f"# `profile: {chosen_by}` in vocatron.yaml.",
    )
    return "\n".join([*header, *lines]) + "\n"
