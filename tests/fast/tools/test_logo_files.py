"""Stage 1: the logo files are the SVG text of the wordmark polygons (ADR-0055)."""

import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

import pytest

import logo_files
from vocatron.core.logo import logo_files as generated
from vocatron.core.logo import symbol_svg, wordmark_svg
from vocatron.core.wordmark import BAND_COLOURS, FIELD_COLOUR


def test_the_committed_files_equal_what_the_polygons_make() -> None:
    for name, text in generated().items():
        committed = (logo_files.LOGO_DIR / name).read_text(encoding="utf-8")
        assert committed == text, f"{name} is stale: run make logo"


def test_no_committed_logo_file_is_unknown() -> None:
    assert sorted(p.name for p in logo_files.LOGO_DIR.iterdir()) == sorted(generated())


@pytest.mark.parametrize("make", [wordmark_svg, symbol_svg])
def test_the_text_is_an_svg_with_the_bands_and_the_glow_but_no_field(
    make: Callable[[], str],
) -> None:
    root = ET.fromstring(make())
    assert root.tag.endswith("svg")
    text = make()
    assert "feGaussianBlur" in text
    assert FIELD_COLOUR not in text
    # Transparent background: nothing but the definitions and the drawing group sits under the
    # root, so no backing shape of any colour.
    assert [child.tag.rsplit("}", 1)[-1] for child in root] == ["defs", "g"]
    assert all(colour in text for colour in BAND_COLOURS)


def test_the_wordmark_is_wider_than_the_symbol() -> None:
    def width(text: str) -> float:
        return float(ET.fromstring(text).attrib["viewBox"].split()[2])

    assert width(wordmark_svg()) > 3 * width(symbol_svg())


def test_the_tool_writes_the_files_into_a_folder(tmp_path: Path) -> None:
    written = logo_files.write_logo_files(tmp_path / "logo")
    assert sorted(p.name for p in written) == sorted(generated())
    assert all(p.read_text(encoding="utf-8") == generated()[p.name] for p in written)
