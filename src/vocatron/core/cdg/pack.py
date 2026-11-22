"""The MP3+G zip: which members it holds, in which order, with which time (ADR-0030).

The zip replaces the loose pair when ``cdg_zip`` is on. The names and the order are fixed here;
the ``Packer`` engine writes the bytes, so the same inputs give the same zip.
"""

MP3_SUFFIX = ".mp3"
CDG_SUFFIX = ".cdg"
ZIP_SUFFIX = ".zip"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)
"""The time stamp of every member: the earliest a zip can hold, so no clock enters the bytes."""


def pair_names(name: str) -> tuple[str, str]:
    """Return the file names of the MP3 and the CD+G file of the song ``name``, in that order."""
    return f"{name}{MP3_SUFFIX}", f"{name}{CDG_SUFFIX}"


def zip_name(name: str) -> str:
    """Return the file name of the zip of the song ``name``."""
    return f"{name}{ZIP_SUFFIX}"
