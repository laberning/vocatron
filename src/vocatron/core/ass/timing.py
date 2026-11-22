"""Centiseconds in an ASS file (ADR-0002, ADR-0009)."""

CS = 100  # centiseconds per second


def cs_of(seconds: float) -> int:
    """Return ``seconds`` in whole centiseconds."""
    return round(seconds * CS)


def ass_time(centis: int) -> str:
    """Format centiseconds as ``H:MM:SS.cc``."""
    centis = max(centis, 0)
    return (
        f"{centis // 360000}:{centis // 6000 % 60:02d}:{centis // 100 % 60:02d}.{centis % 100:02d}"
    )


def parse_time(stamp: str) -> int:
    """Read ``H:MM:SS.cc`` as centiseconds."""
    hours, minutes, rest = stamp.split(":")
    seconds, hundredths = rest.split(".")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * CS + int(hundredths)
