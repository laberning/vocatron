"""Export the JSON schemas of all stage files and ``status.json`` to ``schemas/`` (ADR-0006).

Run with ``make schemas``. A schema change needs a bump of the model's ``schema_version``; the
fast tests fail when a committed schema differs from its model or is missing.

Schema files of earlier versions stay in ``schemas/`` and never change. ``schemas/SHA256SUMS``
pins the SHA-256 of every committed schema file; this tool only adds lines for new versions and
stops, writing nothing, when a schema of an existing version would change.
"""

import sys
from pathlib import Path

from vocatron.core.schemas import (
    MANIFEST_NAME,
    extend_manifest,
    parse_manifest,
    render_manifest,
    schema_files,
)
from vocatron.stages.registry import schema_models

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"


def main() -> int:
    """Write every current schema file and the manifest; return the exit code."""
    SCHEMA_DIR.mkdir(exist_ok=True)
    manifest_path = SCHEMA_DIR / MANIFEST_NAME
    known: dict[str, str] = {}
    if manifest_path.exists():
        known = parse_manifest(manifest_path.read_text(encoding="utf-8"))
    files = schema_files(schema_models())
    try:
        digests = extend_manifest(known, files)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for name, text in files.items():
        (SCHEMA_DIR / name).write_text(text, encoding="utf-8")
        print(f"wrote schemas/{name}")
    manifest_path.write_text(render_manifest(digests), encoding="utf-8")
    print(f"wrote schemas/{MANIFEST_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
