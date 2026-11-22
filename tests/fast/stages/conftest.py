"""Fixtures shared by the stage tests."""

from pathlib import Path

import pytest

from fakes.songs import FakeWorld


@pytest.fixture
def one(world: FakeWorld) -> FakeWorld:
    """A world with one song, ``/music/Artist - Title.mp3``, and the folk-song lyrics next to it."""
    world.add_song(Path("/music/Artist - Title.mp3"))
    return world
