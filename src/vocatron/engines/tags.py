"""Tag reading with tinytag (ADR-0002)."""

from pathlib import Path

from tinytag import TinyTag, TinyTagException

from vocatron.core.song import Tags
from vocatron.engines.protocols import TagReadError


class TinyTagReader:
    """Reads artist, title and duration with tinytag."""

    def read(self, path: Path) -> Tags:
        """Read the tags of ``path``.

        Raises:
            TagReadError: If tinytag cannot read the file.
        """
        try:
            tag = TinyTag.get(path)
        except (TinyTagException, OSError) as error:
            raise TagReadError(f"cannot read {path.name}: {error}") from error
        return Tags(artist=tag.artist, title=tag.title, duration=tag.duration)
