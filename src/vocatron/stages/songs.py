"""Find the songs of an input path and name them (ADR-0006).

The input is one audio file or a folder; only the audio files directly in the folder count, never
subfolders (so never Vocatron's own output folder). Names are made unique over *all* audio files
of the folder, so a song gets the same name whether it is run alone or with the others.
"""

from pathlib import Path

from vocatron.core.errors import UsageError
from vocatron.core.names import resolve_collisions
from vocatron.core.song import Tags, identify
from vocatron.engines.protocols import AUDIO_SUFFIXES, TagReader, TagReadError
from vocatron.stages.config import Config
from vocatron.stages.stage import Engines, Song


def _read_tags(reader: TagReader, path: Path) -> tuple[Tags | None, str | None]:
    """Read the tags of ``path``; return the error text instead when they cannot be read."""
    try:
        return reader.read(path), None
    except TagReadError as error:
        return None, str(error)


def discover(path: Path, config: Config, engines: Engines) -> list[Song]:
    """Find, identify and name the songs to process.

    Args:
        path: An audio file or a folder with audio files.
        config: The configuration (for the output folder).
        engines: The engines (file store and tag reader).

    Returns:
        The songs in sorted path order, each with its work folder.

    Raises:
        UsageError: If the path does not exist, is not an audio file or folder, or the folder has
            no audio files.
    """
    kind = engines.store.kind(path)
    if kind is None:
        raise UsageError(f"{path} does not exist")
    if kind == "file" and path.suffix.lower() not in AUDIO_SUFFIXES:
        raise UsageError(f"{path} is not an audio file ({', '.join(AUDIO_SUFFIXES)})")
    songs_dir = path if kind == "folder" else path.parent
    files = engines.store.list_audio(songs_dir)
    if not files:
        raise UsageError(f"no audio files in {songs_dir}")
    read = {file: _read_tags(engines.tags, file) for file in files}
    identities = {file: identify(tags, file.stem) for file, (tags, _) in read.items()}
    names = resolve_collisions({file: identity.name for file, identity in identities.items()})
    output_dir = songs_dir / config.output.folder
    selected = files if kind == "folder" else [file for file in files if file == path]
    if not selected:
        raise UsageError(f"{path} was not found among the audio files of {songs_dir}")
    return [
        Song(
            source=file,
            name=names[file],
            identity=identities[file],
            tags=read[file][0],
            tag_error=read[file][1],
            output_dir=output_dir,
            work_dir=output_dir / names[file],
        )
        for file in selected
    ]
