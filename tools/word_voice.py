"""Where the voice sounds under every word of a song (numbers only, never a lyric).

    uv run --no-sync python tools/word_voice.py WORK_FOLDER [--all] [--rows flagged|all|none]

``WORK_FOLDER`` is the work folder of a song (``alignment.json`` and ``stems/``). With ``--all``
it is a folder of work folders (for example ``.corpus/bench/work``) and only the summary line of
each song is printed. For every word the tool prints the line, start, duration, confidence, the
voiced share and the time to the first voice on the lead stem and on the backing stem, the share
on the voice the alignment used (lead and backing added), the longest silence inside the word and
the flags of ``vocatron.lab.alignment.word_voice``. The rows are those that are flagged (default),
all, or none. Words are shown by index, never by text.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from vocatron.engines.alignment.analysis import ALIGNMENT_FILE, analyse_work_folder
from vocatron.lab.alignment.word_voice import row_line, summary, table_header


def main(argv: Sequence[str] | None = None) -> int:
    """Run the tool; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--all", action="store_true", help="FOLDER holds work folders")
    parser.add_argument("--rows", choices=("flagged", "all", "none"), default="flagged")
    args = parser.parse_args(argv)
    folders = (
        sorted(p for p in args.folder.iterdir() if (p / ALIGNMENT_FILE).exists())
        if args.all
        else [args.folder]
    )
    for folder in folders:
        result = analyse_work_folder(folder)
        if result is None:
            print(f"{folder.name}: not measured (no alignment, stems or plausible voice)")
            continue
        rows, _ = result
        print(f"{folder.name}: {summary(rows)}")
        if args.all or args.rows == "none":
            continue
        print(table_header())
        for row in rows:
            if args.rows == "all" or row.flags:
                print(row_line(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
