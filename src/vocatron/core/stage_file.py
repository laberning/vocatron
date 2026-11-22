"""Stage files, fingerprints and the skip rule (ADR-0006).

Every stage file carries a ``schema_version``, the review ``reasons`` of its stage and the
``fingerprint`` it was made with. A stage is skipped when the fingerprint computed now equals the
stored one; file times play no part, so copying or syncing a folder does not re-run anything.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class Fingerprint(BaseModel):
    """What a stage file was made from.

    Attributes:
        inputs: SHA-256 of the content of every input file, by input name.
        settings: SHA-256 of the canonical JSON of the settings the stage declares.
        stage_version: The version of the stage's own code.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    inputs: dict[str, str]
    settings: str
    stage_version: int


class StageFile(BaseModel):
    """Base of every stage file: JSON in the work folder, validated by Pydantic.

    A subclass declares ``schema_version: Literal[N] = N`` and bumps it for every schema change;
    the committed JSON schema of the new version is exported with ``make schemas``.

    Attributes:
        fingerprint: What the file was made from.
        reasons: Why the song needs review according to this stage; empty when all is well.
    """

    model_config = ConfigDict(extra="forbid")

    SCHEMA_NAME: ClassVar[str]
    fingerprint: Fingerprint
    reasons: list[str] = Field(default_factory=list)


def hash_bytes(data: bytes) -> str:
    """Return the SHA-256 of ``data`` as hexadecimal text."""
    return hashlib.sha256(data).hexdigest()


def settings_hash(settings: BaseModel) -> str:
    """Return the SHA-256 of the canonical JSON (sorted keys, no spaces, ASCII) of ``settings``."""
    canonical = json.dumps(settings.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hash_bytes(canonical.encode())  # json.dumps escapes non-ASCII, so this is ASCII


def make_fingerprint(
    input_hashes: Mapping[str, str], settings: BaseModel, stage_version: int
) -> Fingerprint:
    """Build the fingerprint of a stage run from its input hashes and settings."""
    return Fingerprint(
        inputs=dict(input_hashes), settings=settings_hash(settings), stage_version=stage_version
    )


def is_current(stored: Fingerprint | None, now: Fingerprint, *, force: bool) -> bool:
    """Tell whether a stage may be skipped.

    Args:
        stored: The fingerprint in the existing, valid stage file; ``None`` if there is none.
        now: The fingerprint computed from the current inputs and settings.
        force: Run regardless.

    Returns:
        ``True`` when the stored output is current and the run is not forced.
    """
    return not force and stored is not None and stored == now
