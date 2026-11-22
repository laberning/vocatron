"""Put the ``vocatron`` command on the search path, or take it away (ADR-0044).

Run by ``make install`` and ``make uninstall``. Install writes one symbolic link, ``vocatron`` in
the folder ``--bindir``, to ``.venv/bin/vocatron`` of the clone; uninstall removes that link when it
points into the clone. The decisions are plain functions that return the message and the exit code,
so the tests need no Makefile and no real folder on the search path.
"""

import argparse
import os
import sys
from pathlib import Path

COMMAND = "vocatron"


def path_folders(path_env: str) -> list[Path]:
    """Split a ``PATH`` value into resolved folders, leaving out empty entries.

    Args:
        path_env: The value of the ``PATH`` environment variable.

    Returns:
        The folders in order, with symbolic links resolved so they compare with a resolved folder.
    """
    return [Path(entry).resolve() for entry in path_env.split(os.pathsep) if entry]


def install(link: Path, target: Path, path_env: str) -> int:
    """Link ``link`` to ``target``, creating the folder of the link if needed.

    Replaces a symbolic link in the way, refuses to replace anything else, and warns (still
    succeeding) when the folder of the link is not on the search path.

    Args:
        link: The path of the command to create, for example ``~/.local/bin/vocatron``.
        target: The ``vocatron`` command in the environment of the clone.
        path_env: The value of the ``PATH`` environment variable.

    Returns:
        The process exit code: 0 on success, 1 when nothing was installed.
    """
    if not target.exists():
        print(f"{target} is missing: run 'make setup' first.", file=sys.stderr)
        return 1
    if link.exists() and not link.is_symlink():
        print(
            f"{link} is a regular file or folder, not a link: not replacing it. "
            "Move it away or choose another folder with BINDIR=...",
            file=sys.stderr,
        )
        return 1
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        link.unlink()
    link.symlink_to(target)
    print(f"Linked {link} -> {target}")
    if link.parent.resolve() not in path_folders(path_env):
        folder = link.parent.absolute()
        print(
            f"Warning: {folder} is not on your PATH. Add it, for example with this line in "
            f'~/.profile:\n  export PATH="{folder}:$PATH"',
            file=sys.stderr,
        )
    return 0


def uninstall(link: Path, clone: Path) -> int:
    """Remove ``link`` if it is a symbolic link into ``clone``.

    Args:
        link: The path of the command, for example ``~/.local/bin/vocatron``.
        clone: The folder of this clone.

    Returns:
        The process exit code: 0 when the link is removed or there was none, 1 when it is not ours.
    """
    if not link.is_symlink():
        if link.exists():
            print(f"{link} is not a link: leaving it.", file=sys.stderr)
            return 1
        print(f"Nothing to remove: {link} does not exist.")
        return 0
    if not link.resolve().is_relative_to(clone.resolve()):
        print(f"{link} does not point into this clone ({clone}): leaving it.", file=sys.stderr)
        return 1
    link.unlink()
    print(f"Removed {link}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run ``install`` or ``uninstall`` from the command line.

    Args:
        argv: The arguments; the process arguments when ``None``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "uninstall"])
    parser.add_argument("--bindir", type=Path, required=True)
    parser.add_argument("--clone", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    link = args.bindir.expanduser() / COMMAND
    if args.action == "install":
        return install(link, args.clone / ".venv" / "bin" / COMMAND, os.environ.get("PATH", ""))
    return uninstall(link, args.clone)


if __name__ == "__main__":
    sys.exit(main())
