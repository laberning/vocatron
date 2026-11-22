"""Stage 1: YAML parsed with the line and column of every key and list item."""

import pytest

from vocatron.core.yaml_pos import YamlSyntaxError, parse_yaml


def test_every_key_and_list_item_has_its_line_and_column() -> None:
    data, positions = parse_yaml("f.yaml", "a: 1\nb:\n  c: [x, y]\n  d:\n    - e: 2\n")
    assert data == {"a": 1, "b": {"c": ["x", "y"], "d": [{"e": 2}]}}
    assert positions[("a",)] == (1, 1)
    assert positions[("b", "c")] == (3, 3)
    assert positions[("b", "c", 1)] == (3, 10)
    assert positions[("b", "d", 0)] == (5, 7)
    assert positions[("b", "d", 0, "e")] == (5, 7)


def test_a_syntax_error_names_file_line_column_and_the_problem() -> None:
    with pytest.raises(YamlSyntaxError) as error:
        parse_yaml("f.yaml", "a: 1\nb: [1, 2\nc: 3\n")
    assert str(error.value).startswith("f.yaml:3:2: ")
    assert "expected ',' or ']'" in str(error.value)
