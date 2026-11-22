"""Conformance kits: the same tests for every entry of an extension-point registry (ADR-0007)."""

from conformance.fixtures_de import GERMAN
from conformance.fixtures_en import ENGLISH
from conformance.language_kit import Fixtures

FIXTURES: dict[str, Fixtures] = {"de": GERMAN, "en": ENGLISH}
"""The fixtures of every language module, by code; a new module adds its own."""
