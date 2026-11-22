"""What ships inside the package: the built-in profiles and the bundled font (ADR-0009)."""

from importlib.resources import files
from pathlib import Path

from vocatron.core.font_check import font_characters

PROFILE_FOLDER = "profiles"
FONT_FOLDER = "fonts"
FONT_FILE = "NotoSans-Bold.ttf"


class PackageResources:
    """The files of the installed package."""

    def __init__(self, package_dir: Path | None = None) -> None:
        """Read from ``package_dir`` (default: the installed ``vocatron`` package)."""
        self._root = package_dir or Path(str(files("vocatron")))
        self._drawable: frozenset[int] | None = None

    def builtin_profile(self, name: str) -> str | None:
        """Return the YAML text of the built-in profile ``name``, or ``None`` if there is none."""
        path = self._root / PROFILE_FOLDER / f"{name}.yaml"
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def fonts_dir(self) -> Path:
        """Return the folder with the bundled font; libass is pointed at it and nowhere else."""
        return self._root / FONT_FOLDER

    def font_file(self) -> Path:
        """Return the bundled font file, which the layout measures."""
        return self.fonts_dir() / FONT_FILE

    def drawable_characters(self) -> frozenset[int]:
        """Return the code points the bundled font can draw (read once, ADR-0046)."""
        if self._drawable is None:
            self._drawable = font_characters(self.font_file().read_bytes())
        return self._drawable
