"""Write the logo files of the wordmark and the V symbol (ADR-0055).

Run with ``make logo``. The files go to ``docs/assets/logo/``; they are made from the same
polygons the video draws (``vocatron.core.wordmark``), by ``vocatron.core.logo``. A fast test
fails when the committed files differ from what this writes. ``LOGO_DIR`` and ``write_logo_files``
are also used by the tests.
"""

import sys
from pathlib import Path

from vocatron.core.logo import logo_files

LOGO_DIR = Path(__file__).resolve().parent.parent / "docs" / "assets" / "logo"


def write_logo_files(folder: Path = LOGO_DIR) -> list[Path]:
    """Write every logo file into ``folder`` and return their paths."""
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, text in logo_files().items():
        target = folder / name
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written


def main() -> int:
    """Write the files and say where they went."""
    for path in write_logo_files():
        print(f"wrote {path.relative_to(LOGO_DIR.parent.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
