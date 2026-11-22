"""Stage 1: the status rules of the lyrics (table), approval, the duet flag and the .lrc fit."""

import pytest

from vocatron.core.lyrics.clean import Removal
from vocatron.core.lyrics.verdict import (
    CREDITS,
    DUET_WITHOUT_MARKS,
    LRC_MISMATCH,
    REPEAT_MARKERS,
    SECTION_MARKERS,
    SINGLE_SOURCE,
    UNKNOWN_LOOKUP,
    UNSURE_MATCH,
    Approval,
    Facts,
    Previous,
    approval,
    decide,
    is_duet,
    lrc_fits,
)

SECTION = Removal(line=1, kind="section", text="[Chorus]")
REPEAT = Removal(line=2, kind="repeat", text="x (2x)")
CREDIT = Removal(line=3, kind="credit", text="Text: Volksgut")
FOUND = Facts(source="lookup", lines=4, match="exact", agreeing=2)


def reasons(facts: Facts) -> list[str]:
    verdict = decide(facts)
    return [r.split(" (")[0] for r in verdict.reasons]


@pytest.mark.parametrize(
    ("facts", "status", "expected"),
    [
        (Facts(source="sidecar", lines=0), "missing", []),
        (Facts(source="lookup", lines=0, match="exact", agreeing=3), "missing", []),
        (Facts(source="sidecar", lines=4), "ok", []),
        (FOUND, "ok", []),
        (FOUND.model_copy(update={"agreeing": 5}), "ok", []),
        (FOUND.model_copy(update={"agreeing": 1}), "review", [SINGLE_SOURCE]),
        (FOUND.model_copy(update={"match": "close"}), "review", [UNSURE_MATCH]),
        (
            FOUND.model_copy(update={"match": "close", "agreeing": 1}),
            "review",
            [UNSURE_MATCH, SINGLE_SOURCE],
        ),
        (Facts(source="sidecar", lines=4, agreeing=0, match="close"), "ok", []),
        (Facts(source="sidecar", lines=4, removals=(SECTION,)), "review", [SECTION_MARKERS]),
        (
            Facts(source="sidecar", lines=4, removals=(SECTION, REPEAT, CREDIT, SECTION)),
            "review",
            [SECTION_MARKERS, REPEAT_MARKERS, CREDITS],
        ),
        (Facts(source="sidecar", lines=4, lrc_fits=False), "review", [LRC_MISMATCH]),
        (Facts(source="sidecar", lines=4, lrc_fits=True), "ok", []),
        (Facts(source="sidecar", lines=4, duet=True), "review", [DUET_WITHOUT_MARKS]),
        (Facts(source="sidecar", lines=4, duet=True, marked=True), "ok", []),
        (Facts(source="sidecar", lines=4, duet=False, marked=False), "ok", []),
        (Facts(source="lookup", lines=4), "review", [UNKNOWN_LOOKUP]),
        (Facts(source="lookup", lines=4, lrc_fits=False), "review", [UNKNOWN_LOOKUP, LRC_MISMATCH]),
    ],
)
def test_the_status_table(facts: Facts, status: str, expected: list[str]) -> None:
    verdict = decide(facts)
    assert verdict.status == status
    assert reasons(facts) == expected


def test_removal_reasons_count_the_lines() -> None:
    one = decide(Facts(source="sidecar", lines=4, removals=(SECTION,)))
    two = decide(Facts(source="sidecar", lines=4, removals=(SECTION, SECTION)))
    assert one.reasons == ("section markers removed (1 line)",)
    assert two.reasons == ("section markers removed (2 lines)",)


@pytest.mark.parametrize(
    ("digest", "previous", "expected"),
    [
        ("a", None, Approval(approved=False, keep_findings=False)),
        (
            "b",
            Previous(sidecar_hash="a", written_hash="a", approved=False),
            Approval(approved=True, keep_findings=False),
        ),
        (
            "b",
            Previous(sidecar_hash="a", written_hash=None, approved=False),
            Approval(approved=True, keep_findings=False),
        ),
        (
            "a",
            Previous(sidecar_hash="a", written_hash="a", approved=False),
            Approval(approved=False, keep_findings=True),
        ),
        (
            "a",
            Previous(sidecar_hash="a", written_hash="a", approved=True),
            Approval(approved=True, keep_findings=True),
        ),
        (
            "a",
            Previous(sidecar_hash="a", written_hash=None, approved=False),
            Approval(approved=False, keep_findings=False),
        ),
        (
            "a",
            Previous(sidecar_hash="a", written_hash=None, approved=True),
            Approval(approved=True, keep_findings=False),
        ),
    ],
)
def test_a_changed_sidecar_counts_as_approved(
    digest: str, previous: Previous | None, expected: Approval
) -> None:
    assert approval(digest, previous) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Anna & Ben - Hänschen klein (Duet)", True),
        ("Anna & Ben - Hänschen klein DUETT", True),
        ("Hänschen klein", False),
    ],
)
def test_the_default_duet_pattern_matches_in_any_case(name: str, expected: bool) -> None:
    assert is_duet("duet(t)?", name, "Hänschen klein") is expected


def test_the_duet_pattern_is_looked_for_in_every_text() -> None:
    assert is_duet("duet", "Hänschen klein", "Hänschen klein (Duet)")
    assert is_duet("zu zweit", "Hänschen klein zu zweit")


@pytest.mark.parametrize(
    ("last", "length", "duration", "expected"),
    [
        (170.0, 180.0, 181.5, True),
        (170.0, 180.0, 183.0, False),
        (185.0, None, 180.0, False),
        (181.0, None, 180.0, True),
        (None, 180.0, 180.0, True),
        (None, None, 180.0, None),
        (170.0, 180.0, None, None),
        (None, 182.0, 180.0, True),  # exactly 2 s off still fits
        (182.0, None, 180.0, True),
    ],
)
def test_the_lrc_fits_when_length_and_last_line_agree_with_the_song(
    last: float | None, length: float | None, duration: float | None, expected: bool | None
) -> None:
    assert lrc_fits(last, length, duration) is expected


def test_a_dropped_symbol_is_a_review_reason_with_its_lines_and_name() -> None:
    glyph = Removal(line=45, kind="glyph", text="ab √ cd", character=0x221A)
    hearts = [Removal(line=n, kind="glyph", text="ab ♥", character=0x2665) for n in (46, 50)]
    removals = (hearts[0], glyph, SECTION, hearts[1])
    verdict = decide(Facts(source="sidecar", lines=4, removals=removals))
    assert verdict.status == "review"
    assert verdict.reasons == (
        "lines 46, 50: dropped U+2665 BLACK HEART SUIT (not in the font)",  # one reason per symbol
        "line 45: dropped U+221A SQUARE ROOT (not in the font)",
        f"{SECTION_MARKERS} (1 line)",
    )
