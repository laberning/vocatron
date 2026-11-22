"""Finding the summary line of a song in console output (the column layout lives in core.report)."""


def summary_line(out: str, state: str, name: str) -> str | None:
    """Return the first summary line of ``name`` that starts with ``state``, or ``None``."""
    for line in out.splitlines():
        if line.startswith(f"{state} ") and f"  {name}" in line:
            return line
    return None
