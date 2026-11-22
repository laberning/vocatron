"""Stage 1: no Python module in ``src`` or ``tests`` is longer than 1000 lines (ADR-0051).

A module above the cap is split along its seams. An exception needs an entry in ``RAISED`` with
the limit it may reach and the reason; a raised limit is a review finding.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAP = 1000

# Path relative to the repository root -> (the limit of this file, the reason). Empty on purpose.
RAISED: dict[str, tuple[int, str]] = {}


def line_count(path: Path) -> int:
    """Return the number of lines of ``path``."""
    return len(path.read_text(encoding="utf-8").splitlines())


def too_long(root: Path = ROOT, raised: dict[str, tuple[int, str]] = RAISED) -> dict[str, int]:
    """Return every module in ``src`` and ``tests`` of ``root`` above its limit, with its count."""
    found: dict[str, int] = {}
    for top in ("src", "tests"):
        for path in sorted((root / top).rglob("*.py")):
            name = path.relative_to(root).as_posix()
            count = line_count(path)
            if count > raised.get(name, (CAP, ""))[0]:
                found[name] = count
    return found


def test_no_module_is_longer_than_the_cap() -> None:
    bad = too_long()
    assert not bad, f"split these modules, each is above {CAP} lines (ADR-0051): {bad}"


def test_the_gate_names_each_module_above_its_limit(tmp_path: Path) -> None:
    for name, lines in (
        ("src/a.py", CAP),
        ("src/b.py", CAP + 1),
        ("tests/c.py", CAP + 5),
        ("tests/d.py", CAP + 5),
        ("tools/e.py", CAP + 9),
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x = 1\n" * lines, encoding="utf-8")
    raised = {"tests/d.py": (CAP + 5, "invented")}
    assert too_long(tmp_path, raised) == {"src/b.py": CAP + 1, "tests/c.py": CAP + 5}


def test_every_raised_limit_names_a_file_above_the_cap_and_a_reason() -> None:
    for name, (limit, reason) in RAISED.items():
        assert (ROOT / name).is_file(), f"{name} is in RAISED but does not exist"
        assert limit > CAP, f"{name}: a raised limit is above {CAP}"
        assert reason.strip(), f"{name}: a raised limit needs a reason"
        assert line_count(ROOT / name) > CAP, f"{name} is within the cap; drop its entry"
