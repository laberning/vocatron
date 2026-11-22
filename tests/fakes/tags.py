"""A tag reader with canned answers."""

from pathlib import Path

from vocatron.core.song import Tags
from vocatron.engines.protocols import TagReadError


class FakeTagReader:
    """Returns the tags registered for a path; a path registered with ``None`` is unreadable."""

    def __init__(self) -> None:
        self.tags: dict[Path, Tags | None] = {}
        self.reads: list[Path] = []

    def read(self, path: Path) -> Tags:
        self.reads.append(path)
        tags = self.tags.get(path, Tags(None, None, None))
        if tags is None:
            raise TagReadError(f"cannot read {path.name}: not audio")
        return tags
