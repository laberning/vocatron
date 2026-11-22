"""Accept the last benchmark run of a language as its baseline (``make bench-accept``).

The names of the files come from ``vocatron.core.bench.bench_files``, the one place that knows
them: German keeps ``last.json`` and ``baseline.json``, another language appends ``-<code>``.
"""

import argparse
import shutil
import sys
from pathlib import Path

from vocatron.core.bench import bench_files
from vocatron.core.languages import DEFAULT_LANGUAGE, LANGUAGES


def accept(corpus: Path, language: str) -> tuple[bool, str]:
    """Copy the last result of ``language`` to its baseline.

    Args:
        corpus: The corpus folder (the one with ``bench/`` in it).
        language: The language code.

    Returns:
        Whether it was accepted, and the message to print.
    """
    if language not in LANGUAGES:
        return False, f"unsupported language {language!r}; supported: {', '.join(LANGUAGES)}"
    files = bench_files(language)
    last, baseline = corpus / "bench" / files.last, corpus / "bench" / files.baseline
    if not last.is_file():
        hint = "" if language == DEFAULT_LANGUAGE else f" LANGUAGE={language}"
        return False, f"no {last}: run 'make bench{hint}' first"
    shutil.copyfile(last, baseline)
    return True, f"accepted {last} as the baseline"


def main(argv: list[str]) -> int:
    """Accept the last run; exit code 0 when it was accepted, else 1."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", nargs="?", default=DEFAULT_LANGUAGE)
    parser.add_argument("--corpus", type=Path, default=Path(".corpus"))
    args = parser.parse_args(argv)
    ok, message = accept(args.corpus, args.language)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
