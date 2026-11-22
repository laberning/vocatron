"""Stage 1 tests of the helpers of the demo song's end-to-end test (``tests/demoreal.py``)."""

from pathlib import Path

import pytest

from demoreal import (
    Errors,
    Reference,
    demo_names,
    frame_moments,
    read_reference,
    start_errors,
    verdict,
    write_reference,
)
from fakes.scenes import entchen_scene


def test_errors_are_median_and_worst_of_the_absolute_differences() -> None:
    found = [1.0, 2.0, 3.0, 4.0, 5.0]
    reference = [1.1, 1.9, 3.0, 4.5, 5.0]
    errors = start_errors(found, reference)
    assert errors.median == pytest.approx(0.1)
    assert errors.worst == pytest.approx(0.5)
    assert errors.count == 5


def test_lists_of_different_length_or_empty_ones_cannot_be_compared() -> None:
    with pytest.raises(ValueError, match="3 words found, the reference has 2"):
        start_errors([1.0, 2.0, 3.0], [1.0, 2.0])
    with pytest.raises(ValueError, match="no words"):
        start_errors([], [])


def test_the_verdict_names_the_limit_that_was_broken_in_numbers() -> None:
    assert verdict(Errors(0.05, 0.9, 10)) is None
    assert verdict(Errors(0.1, 1.0, 10)) is None  # the limits themselves are allowed
    assert verdict(Errors(0.2, 0.9, 10)) == "median start error 200 ms (limit 100)"
    assert verdict(Errors(0.05, 1.5, 10)) == "worst start error 1.50 s (limit 1.0)"


def test_five_frames_are_chosen_the_title_and_four_moments_inside_lines() -> None:
    scene = entchen_scene()
    moments = frame_moments(scene)
    assert list(moments) == ["title", "first-line", "quarter-line", "middle-line", "late-line"]
    assert moments["title"] == 1.0
    starts = sorted(line.sing_start for line in scene.lines())
    assert moments["first-line"] == starts[0] + 0.5
    for name in ("quarter-line", "middle-line", "late-line"):
        assert moments[name] - 0.5 in starts


def test_a_reference_survives_writing_and_reading(tmp_path: Path) -> None:
    reference = Reference([1.23456, 2.0], {"title": 1.0, "first-line": 9.5004})
    path = tmp_path / "golden" / "demo" / "words.json"
    write_reference(path, reference)
    assert read_reference(path) == Reference([1.235, 2.0], {"title": 1.0, "first-line": 9.5})


def test_every_language_has_its_own_references_make_folder_sheet_and_log() -> None:
    german, english = demo_names("de"), demo_names("en")
    assert german == ("de", "make-de", "contact-sheet-demo-de.png", "stage2-demo-de.log")
    assert english == ("en", "make-en", "contact-sheet-demo-en.png", "stage2-demo-en.log")
    assert not set(german) & set(english)
