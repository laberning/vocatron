"""Stage 1: rows of a card: texts side by side (``join``) and wrapped rows (``tight``)."""

import pytest

from fakes.measure import FixedMeasurer
from fakes.scenes import builtin_profile
from vocatron.core.layout.cards import (
    JOIN_GAP,
    LINE_PITCH,
    ROW_PITCH,
    Canvas,
    CardText,
    card,
)
from vocatron.core.scene import Rect

WHITE = "#ffffff"


def canvas_of(width: float, height: float = 300.0, size: float = 20.0) -> Canvas:
    return Canvas(
        FixedMeasurer(), builtin_profile("two-line-turns"), Rect(x=0, y=0, w=width, h=height), size
    )


def test_texts_side_by_side_share_a_row_centred_as_a_group_with_a_gap() -> None:
    texts = [CardText("AAAA", 1.0, "#111111"), CardText("BBBB", 1.0, "#222222", join=True)]
    shown = card("title", texts, canvas_of(400.0), 0.0, 5.0)
    first, second = shown.lines
    assert first.box.y == second.box.y
    assert (first.colour, second.colour) == ("#111111", "#222222")
    gap = second.text_x - first.text_x - 40.0
    assert gap == pytest.approx(JOIN_GAP * 20.0, abs=0.01)
    left, right = first.text_x, second.text_x + 40.0
    assert (left + right) / 2 == pytest.approx(200.0, abs=0.01)


def test_a_row_too_wide_shrinks_all_its_texts_alike() -> None:
    texts = [CardText("A" * 20, 1.0, WHITE), CardText("B" * 20, 1.0, WHITE, join=True)]
    shown = card("title", texts, canvas_of(300.0), 0.0, 5.0)
    first, second = shown.lines
    assert first.size == second.size < 20.0
    assert second.box.right <= 300.0 and first.box.x >= 0.0


def test_the_rows_of_one_text_shrink_together_and_stand_closer() -> None:
    texts = [CardText("A" * 10, 1.0, WHITE), CardText("B" * 30, 1.0, WHITE, tight=True)]
    shown = card("title", texts, canvas_of(300.0), 0.0, 5.0)
    first, second = shown.lines
    assert first.size == second.size < 20.0  # the short row shrinks with the long one
    assert second.box.y - first.box.y == pytest.approx(ROW_PITCH * first.size, abs=0.01)


def test_separate_texts_keep_their_own_sizes_and_the_normal_pitch() -> None:
    texts = [CardText("A" * 10, 1.0, WHITE), CardText("B" * 30, 1.0, WHITE)]
    first, second = card("title", texts, canvas_of(300.0), 0.0, 5.0).lines
    assert first.size == 20.0 and second.size < 20.0
    assert second.box.y - first.box.y == pytest.approx(LINE_PITCH * 20.0, abs=0.01)


def test_many_rows_are_shrunk_to_the_height_with_rows_and_joins_alike() -> None:
    texts = [CardText("X", 1.0, WHITE)] + [CardText("Y", 1.0, WHITE, join=True)] * 2
    texts += [CardText("Z", 1.0, WHITE, tight=True)] * 8
    shown = card("title", texts, canvas_of(300.0, height=100.0), 0.0, 5.0)
    assert all(x.size < 20.0 for x in shown.lines)
    assert all(x.box.y >= 0.0 and x.box.bottom <= 100.0 + 1e-6 for x in shown.lines)
