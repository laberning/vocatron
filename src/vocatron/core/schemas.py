"""Naming and rendering of the committed JSON schemas (ADR-0006, ADR-0004)."""

import hashlib
import json
import re
from collections.abc import Iterable, Mapping

from pydantic import BaseModel

_HEX64 = re.compile(r"[0-9a-f]{64}")


def schema_version(model: type[BaseModel]) -> int:
    """Return the schema version a model declares as the default of ``schema_version``."""
    default = model.model_fields["schema_version"].default
    if not isinstance(default, int):
        message = f"{model.__name__} has no integer default for schema_version"
        raise TypeError(message)
    return default


def schema_name(model: type[BaseModel]) -> str:
    """Return the file stem of a model's schema, for example ``song``."""
    name = getattr(model, "SCHEMA_NAME", None)
    if not isinstance(name, str):
        message = f"{model.__name__} has no SCHEMA_NAME"
        raise TypeError(message)
    return name


def schema_filename(model: type[BaseModel]) -> str:
    """Return ``<name>.v<version>.json`` for a model."""
    return f"{schema_name(model)}.v{schema_version(model)}.json"


def schema_text(model: type[BaseModel]) -> str:
    """Return the JSON schema of a model as stable, human-readable text."""
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def schema_files(models: Iterable[type[BaseModel]]) -> dict[str, str]:
    """Return the committed schema files (name to text) for ``models``."""
    return {schema_filename(model): schema_text(model) for model in models}


MANIFEST_NAME = "SHA256SUMS"
"""File in ``schemas/`` that pins the SHA-256 of every committed schema file."""


def schema_digest(text: str) -> str:
    """Return the SHA-256 (hex) of a schema file's text, encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_manifest(digests: Mapping[str, str]) -> str:
    """Return the manifest text: one ``<sha256>  <file name>`` line per file, sorted by name.

    The format is the one ``sha256sum --check`` reads.
    """
    return "".join(f"{digests[name]}  {name}\n" for name in sorted(digests))


def parse_manifest(text: str) -> dict[str, str]:
    """Return file name to SHA-256 from a manifest written by :func:`render_manifest`.

    Raises:
        ValueError: A line is not ``<64 hex digits>  <file name>``, or a name repeats.
    """
    digests: dict[str, str] = {}
    for line in text.splitlines():
        digest, separator, name = line.partition("  ")
        if not separator or not name or not _HEX64.fullmatch(digest):
            message = f"malformed manifest line: {line!r}"
            raise ValueError(message)
        if name in digests:
            message = f"{name} is listed twice in the manifest"
            raise ValueError(message)
        digests[name] = digest
    return digests


def extend_manifest(digests: Mapping[str, str], files: Mapping[str, str]) -> dict[str, str]:
    """Return the manifest with the schema files ``files`` (name to text) added.

    A committed schema file never changes (ADR-0006): stage files are a public format, so the
    schema of every version stays as it was, also after the model moved on to a newer version.

    Raises:
        ValueError: A file already in the manifest has a different text now; the model changed
            without a ``schema_version`` bump.
    """
    extended = dict(digests)
    for name, text in files.items():
        digest = schema_digest(text)
        if extended.setdefault(name, digest) != digest:
            message = f"{name} would change: bump the model's schema_version instead"
            raise ValueError(message)
    return extended
