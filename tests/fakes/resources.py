"""The package resources for the fast tests: the built-in profiles are read from the source tree."""

from pathlib import Path

from vocatron.engines.resources import PackageResources

SOURCE = Path(__file__).resolve().parents[2] / "src" / "vocatron"


class FakeResources(PackageResources):
    """Reads the built-in profiles and the font folder of the checkout."""

    def __init__(self) -> None:
        super().__init__(SOURCE)
