"""Stage 1 tests for ``tools/coverage_layers.py``."""

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

import coverage_layers
from coverage_layers import Summary


def report(**layers: tuple[int, int]) -> dict[str, Summary]:
    """Build files with ``(statements, covered)`` per layer, without branches."""
    return {
        f"src/vocatron/{layer}/mod.py": Summary(total, covered, 0, 0)
        for layer, (total, covered) in layers.items()
    }


def test_layer_of_reads_the_layer_from_the_path() -> None:
    assert coverage_layers.layer_of("src/vocatron/core/x.py") == "core"
    assert coverage_layers.layer_of("/abs/src/vocatron/cli/app.py") == "cli"
    assert coverage_layers.layer_of("src/vocatron/lab/cdg/analysis.py") == "lab"
    assert coverage_layers.layer_of("src/vocatron/__main__.py") is None
    assert coverage_layers.layer_of("tools/gate.py") is None
    assert coverage_layers.layer_of("src/vocatron/other/x.py") is None


def test_empty_layers_pass_and_say_so() -> None:
    lines, ok = coverage_layers.check({})
    assert ok
    assert all("no code yet" in line for line in lines)


def test_layer_at_the_minimum_passes() -> None:
    _, ok = coverage_layers.check(report(core=(100, 95), stages=(10, 9)))
    assert ok


def test_layer_below_the_minimum_fails_and_is_named() -> None:
    lines, ok = coverage_layers.check(report(core=(100, 94), cli=(10, 10)))
    assert not ok
    assert any(line.startswith("core:") and "below the minimum 95" in line for line in lines)


def test_lab_has_the_minimum_of_core() -> None:
    lines, ok = coverage_layers.check(report(lab=(100, 94)))
    assert not ok
    assert any(line.startswith("lab:") and "below the minimum 95" in line for line in lines)


def test_each_layer_has_its_own_minimum() -> None:
    lines, ok = coverage_layers.check(report(engines=(100, 60), cli=(100, 79)))
    assert not ok
    assert any(line.startswith("cli:") and "below" in line for line in lines)
    assert any(line.startswith("engines:") and "below" not in line for line in lines)


def test_branches_count_like_coverage_py() -> None:
    files = {"src/vocatron/core/a.py": Summary(10, 10, 10, 0)}
    percentages = coverage_layers.layer_percentages(files)
    assert percentages["core"] == pytest.approx(50.0)


@given(
    st.lists(
        st.tuples(st.integers(1, 500), st.floats(0, 1), st.integers(0, 100), st.floats(0, 1)),
        min_size=1,
        max_size=10,
    )
)
def test_percentage_is_always_between_zero_and_hundred(
    rows: list[tuple[int, float, int, float]],
) -> None:
    files = {
        f"src/vocatron/core/m{i}.py": Summary(s, int(s * c), b, int(b * cb))
        for i, (s, c, b, cb) in enumerate(rows)
    }
    percent = coverage_layers.layer_percentages(files)["core"]
    assert percent is not None
    assert 0.0 <= percent <= 100.0


def test_parse_report_reads_coverage_py_json() -> None:
    raw = {
        "files": {
            "src/vocatron/cli/app.py": {
                "summary": {
                    "num_statements": 5,
                    "covered_lines": 4,
                    "num_branches": 2,
                    "covered_branches": 1,
                }
            }
        }
    }
    assert coverage_layers.parse_report(raw) == {"src/vocatron/cli/app.py": Summary(5, 4, 2, 1)}


@pytest.mark.parametrize("raw", [[], {"files": []}, {"files": {"a.py": {}}}])
def test_parse_report_rejects_other_shapes(raw: object) -> None:
    with pytest.raises(ValueError, match="coverage|summary"):
        coverage_layers.parse_report(raw)


def test_main_reads_the_file_and_sets_the_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "coverage.json"
    summary = {"num_statements": 10, "covered_lines": 1}
    path.write_text(json.dumps({"files": {"src/vocatron/core/a.py": {"summary": summary}}}))
    assert coverage_layers.main([str(path)]) == 1
    assert "core: coverage 10.0 %" in capsys.readouterr().out


def test_main_without_data_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert coverage_layers.main([str(tmp_path / "missing.json")]) == 1
    assert "no coverage data" in capsys.readouterr().out
