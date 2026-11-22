"""The captured consoles of one command run."""

from io import StringIO
from pathlib import Path

from rich.console import Console

from fakes.songs import FakeWorld
from vocatron.cli.commands import Edges

CLONE = Path("/clone")


def console(stream: StringIO) -> Console:
    """A console that writes plain text of fixed width into ``stream``."""
    return Console(file=stream, width=100, color_system=None)


class Streams:
    """The captured console and error console of one command run."""

    def __init__(self, world: FakeWorld) -> None:
        self.out = StringIO()
        self.err = StringIO()
        self.edges = Edges(
            world.engines, console(self.out), console(self.err), Path("/work"), world.probe, CLONE
        )
