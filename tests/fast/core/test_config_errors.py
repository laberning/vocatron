"""Stage 1: pointing configuration errors at a line and column."""

from vocatron.core.config_errors import Issue, Positions, describe, describe_all, locate

POSITIONS: Positions = {("probe",): (2, 1), ("probe", "min_duration"): (3, 3)}


def test_locate_uses_the_deepest_known_key() -> None:
    assert locate(("probe", "min_duration"), POSITIONS) == (3, 3)
    assert locate(("probe", "unknown"), POSITIONS) == (2, 1)
    assert locate(("other",), POSITIONS) == (1, 1)
    assert locate((), POSITIONS) == (1, 1)


def test_describe_formats_file_line_column_path_and_message() -> None:
    issue = Issue(("probe", "min_duration"), "Input should be a valid number")
    assert describe("v.yaml", issue, POSITIONS) == (
        "v.yaml:3:3: probe.min_duration: Input should be a valid number"
    )
    assert describe("v.yaml", Issue((), "bad"), POSITIONS) == "v.yaml:1:1: bad"


def test_describe_all_keeps_the_order() -> None:
    issues = [Issue(("a",), "x"), Issue(("b",), "y")]
    assert describe_all("f", issues, {}) == ["f:1:1: a: x", "f:1:1: b: y"]
