"""Mutation testing of named functions of ``core`` and ``lab``: ``make mutation FUNCS="..."``.

``mutmut run`` spreads to all of ``core`` and ``lab`` even with one mutant name, which takes hours.
This tool uses mutmut only to write the mutants into ``mutants/`` (it refreshes the mutated sources
and the copy of ``tests/`` first), lists the mutants of exactly the functions asked for, prints how
many there are, and runs each one the way mutmut does: pytest in ``mutants/`` with
``MUTANT_UNDER_TEST`` set to the mutant and ``PYTHONPATH=src``, so the tests import the mutated
code and not the original. It never starts more mutants than it counted.

A function is named ``vocatron.core.module.function`` or ``vocatron.core.module.Class.method``
(``vocatron.lab.…`` the same way).
The tests run are the files of ``tests/fast`` that name the module, the class or the function;
``--tests`` gives them by hand. A mutant is killed when a test fails (or hangs), and it survives
when all pass. Exit code: 0 when all are killed, 1 when one survives, 2 on a usage error or when
the tests fail without a mutant.
"""

import argparse
import io
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from functools import partial
from pathlib import Path
from typing import Literal, Protocol

MUTANTS = Path("mutants")
TESTS = Path("tests/fast")
SOURCE = Path("src")
SEPARATOR = "__mutmut_"
CLASS_MARK = "ǁ"  # mutmut's mark between the class and the method in the name of a mutant
DEFAULT_TIMEOUT = 900.0
"""Seconds one mutant may run; a mutant that makes the tests hang counts as killed."""
DEFAULT_JOBS = 4
EXIT_USAGE = 2
PYTEST_FAILED = 1

type Outcome = Literal["killed", "survived", "error"]


class Runner(Protocol):
    """Runs the tests with one mutant switched on (or none, for the empty name)."""

    def __call__(self, mutant: str, tests: Sequence[str]) -> Outcome:
        """Return whether the tests killed the mutant, let it survive or could not run."""
        ...


def candidates(function: str) -> tuple[str, str]:
    """Return the two prefixes mutmut may have given the mutants of ``function``.

    ``a.b.name`` is the function ``name`` of module ``a.b``, or the method ``name`` of class ``b``
    in module ``a``; mutmut names the first ``a.b.x_name`` and the second ``a.xǁbǁname``.
    """
    module, _, name = function.rpartition(".")
    owner, _, class_name = module.rpartition(".")
    return f"{module}.x_{name}", f"{owner}.x{CLASS_MARK}{class_name}{CLASS_MARK}{name}"


def match_mutants(names: Sequence[str], functions: Sequence[str]) -> dict[str, list[str]]:
    """Return the mutants of each function, in order; a function without a mutant is an error.

    Raises:
        ValueError: If a function has no mutant (a wrong name, or code mutmut does not mutate).
    """
    found: dict[str, list[str]] = {}
    for function in functions:
        prefixes = candidates(function)
        found[function] = [
            name for name in names if name.partition(SEPARATOR)[0] in prefixes and SEPARATOR in name
        ]
        if not found[function]:
            raise ValueError(
                f"no mutants for {function}: name a function as vocatron.core.module.function "
                "or vocatron.core.module.Class.method, and one that has code to mutate"
            )
    return found


def module_of(function: str, source: Path = SOURCE) -> str:
    """Return the dotted name of the module that holds ``function`` (the longest that exists)."""
    parts = function.split(".")
    for length in range(len(parts) - 1, 0, -1):
        base = source.joinpath(*parts[:length])
        if base.with_suffix(".py").is_file() or (base / "__init__.py").is_file():
            return ".".join(parts[:length])
    return ".".join(parts[:-1])


def names_of(function: str, source: Path = SOURCE) -> list[str]:
    """Return the module of ``function`` and each name after it (the class, then the method)."""
    module = module_of(function, source)
    return [module, *function.removeprefix(f"{module}.").split(".")]


def select_tests(functions: Sequence[str], root: Path = TESTS, source: Path = SOURCE) -> list[str]:
    """Return the test files under ``root`` that name the module, the class or the function.

    Names are matched as whole words in the text of the file (the module by its dotted name). The
    class of a method counts, as tests often reach a method through its class imported from the
    package (``from vocatron.core.cdg import CdgScreen``).
    """
    words = [
        re.compile(rf"\b{re.escape(name)}\b")
        for function in functions
        for name in names_of(function, source)
    ]
    return sorted(
        path.as_posix()
        for path in root.rglob("test_*.py")
        if any(word.search(path.read_text("utf-8")) for word in words)
    )


def pytest_runner(timeout: float = DEFAULT_TIMEOUT) -> Runner:
    """Return the runner that starts pytest in ``mutants/`` for each mutant, as mutmut does."""

    def run(mutant: str, tests: Sequence[str]) -> Outcome:
        env = {**os.environ, "MUTANT_UNDER_TEST": mutant, "PYTHONPATH": "src"}
        command = [sys.executable, "-m", "pytest", "-x", "-q", "-n", "0", "-p", "no:randomly"]
        command += ["-p", "no:cacheprovider", "--rootdir=.", *tests]
        try:
            done = subprocess.run(
                command, cwd=MUTANTS, env=env, capture_output=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired:
            return "killed"
        if done.returncode == 0:
            return "survived"
        return "killed" if done.returncode == PYTEST_FAILED else "error"

    return run


def refresh_mutants() -> list[str]:
    """Write the mutants and the copy of the tests into ``mutants/``; return every mutant's name.

    This is the generating step of ``mutmut run`` (it only rewrites sources that changed), without
    collecting statistics or running a test. mutmut is imported here, not at the top.
    """
    from mutmut.__main__ import create_mutants  # noqa: PLC0415  # needs mutmut's configuration
    from mutmut.mutation.data import SourceFileMutationData  # noqa: PLC0415  # same
    from mutmut.utils.file_utils import (  # noqa: PLC0415  # same
        copy_also_copy_files,
        copy_src_dir,
        walk_source_files,
    )

    MUTANTS.mkdir(exist_ok=True)
    with redirect_stdout(io.StringIO()):  # mutmut prints every file it touches
        copy_src_dir()
        copy_also_copy_files()
        create_mutants(os.cpu_count() or 1)
    names: list[str] = []
    for path in walk_source_files():
        data = SourceFileMutationData(path=path)
        data.load()
        names += list(data.exit_code_by_key)
    return names


def run_all(
    mutants: Mapping[str, Sequence[str]], tests: Sequence[str], runner: Runner, jobs: int
) -> dict[str, Outcome]:
    """Run every mutant of every function once; return the outcome by mutant name."""
    names = [name for group in mutants.values() for name in group]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        outcomes = list(pool.map(partial(runner, tests=tests), names))
    return dict(zip(names, outcomes, strict=True))


def parser() -> argparse.ArgumentParser:
    """Return the command line parser."""
    found = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    found.add_argument(
        "functions", nargs="*", help="vocatron.core.module.function (or Class.method)"
    )
    found.add_argument("--tests", nargs="+", default=None, help="test files, instead of the guess")
    found.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help="mutants run at once")
    found.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds per mutant")
    return found


def say(line: str) -> None:
    """Print ``line`` at once: the run goes on for many minutes, often into a log file."""
    print(line, flush=True)


def main(
    argv: Sequence[str],
    *,
    refresh: Callable[[], list[str]] = refresh_mutants,
    runner: Runner | None = None,
    out: Callable[[str], None] = say,
) -> int:
    """Run the mutants of the functions named on the command line; return the exit code."""
    args = parser().parse_args(argv)
    if not args.functions:
        out(
            'no functions named: make mutation FUNCS="vocatron.core.module.function ..." '
            "(ALL=1 runs all of core and lab and takes hours)"
        )
        return EXIT_USAGE
    try:
        mutants = match_mutants(refresh(), args.functions)
    except ValueError as error:
        out(str(error))
        return EXIT_USAGE
    tests = args.tests or select_tests(args.functions)
    if not tests:
        out("no test file names these functions or their modules: give them with --tests")
        return EXIT_USAGE
    counts = ", ".join(f"{function}: {len(group)}" for function, group in mutants.items())
    total = sum(len(group) for group in mutants.values())
    out(f"{total} mutants ({counts}); tests: {', '.join(tests)}")
    run = runner or pytest_runner(args.timeout)
    if run("", tests) != "survived":  # no mutant: the tests must pass
        out("the tests fail without a mutant; fix them first")
        return EXIT_USAGE
    outcomes = run_all(mutants, tests, run, args.jobs)
    survived = [name for name, outcome in outcomes.items() if outcome == "survived"]
    errors = [name for name, outcome in outcomes.items() if outcome == "error"]
    for name in survived:
        out(f"survived: {name}")
    for name in errors:
        out(f"could not run: {name}")
    killed = total - len(survived) - len(errors)
    out(f"{killed} killed, {len(survived)} survived, {len(errors)} errors")
    return 1 if survived or errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
