"""The CD+G profile: a style profile simplified for the CD+G screen (ADR-0029).

A look carries a ``cdg`` section (``vocatron.core.profiles.model.CdgLook``) with its sizes in
pixels, its slots, its edge, its wipe step and colour overrides. ``cdg_profile`` turns the
profile into a normal ``Profile`` that the unchanged layout and the CD+G writer use: the sizes
become shares of the 192 px safe area, the colours are rounded to 12 bits (or overridden), the
shadow and the fade of the end screen are dropped. A fallback step (``fit_steps``) changes the
page turn of a page look (line by line, ADR-0041), the lead-in minimum and the wipe step for a
song that does not make the timing as the look declares it.
"""

from dataclasses import dataclass

from vocatron.core.colour import long_hex, round_12bit
from vocatron.core.profiles.model import (
    SAFE_HEIGHT_PX,
    SINGER_KEYS,
    CdgLook,
    CdgSingerColours,
    PageTurn,
    Profile,
    SingerColours,
)

COARSE_WIPE = 6
"""The wipe step of the last fallback: a tile column (``cdg.wipe_columns`` 6)."""
SINGLE_KEYS = (*SINGER_KEYS, "group")


@dataclass(frozen=True)
class FitStep:
    """One try of the fallback: how a page turns, how early a line appears, how coarse the wipe is.

    Attributes:
        number: The position in the steps of the look, from 0 (as the look declares it).
        name: A short description for the song log.
        lead_min: The lead-in minimum in seconds.
        lead_target: The lead-in target in seconds (never below ``lead_min``).
        wipe_columns: The pixels a wipe, bar or countdown moves at a time.
        page_turn: How a page gives way to the next (``page.turn``): ``line`` from the step "line
            by line" on for a page look, otherwise what the look declares.
    """

    number: int
    name: str
    lead_min: float
    lead_target: float
    wipe_columns: int
    page_turn: PageTurn = "page"


def cdg_section(profile: Profile) -> CdgLook:
    """Return the ``cdg`` section of ``profile``.

    Raises:
        ValueError: If the profile has none (check ``made_for_cdg`` first).
    """
    if profile.cdg is None:
        raise ValueError(f"profile {profile.name!r} has no cdg section")
    return profile.cdg


def fit_steps(profile: Profile) -> list[FitStep]:
    """Return the fallback steps of a look, in the order they are tried.

    As declared; for a page look that turns whole pages, the same with its pages turning line by
    line (ADR-0041); the lead-in minimum raised to the look's target; to its maximum; then the
    wipe at 6 pixels. The later steps keep the line turn. A step that would repeat the one before
    it is left out.
    """
    section, lead = cdg_section(profile), profile.lead_in
    declared = profile.page.turn
    later: PageTurn = "line" if profile.mode == "page" else declared
    wanted: list[tuple[str, float, float, int, PageTurn]] = [
        ("as declared", lead.min, lead.target, section.wipe_columns, declared)
    ]
    if later != declared:
        wanted.append(("line by line", lead.min, lead.target, section.wipe_columns, later))
    wanted += [
        ("lines earlier (lead-in target)", lead.target, lead.target, section.wipe_columns, later),
        ("lines earlier (lead-in maximum)", lead.max, lead.max, section.wipe_columns, later),
        ("coarser wipe", lead.max, lead.max, COARSE_WIPE, later),
    ]
    steps: list[FitStep] = []
    for name, lead_min, lead_target, wipe, turn in wanted:
        if steps and (lead_min, wipe, turn) == (
            steps[-1].lead_min,
            steps[-1].wipe_columns,
            steps[-1].page_turn,
        ):
            continue
        steps.append(FitStep(len(steps), name, lead_min, lead_target, wipe, turn))
    return steps


def _rounded(colours: SingerColours, override: CdgSingerColours | None) -> dict[str, str]:
    """Return the three colours of a singer rounded to 12 bits, an override winning."""
    chosen = override or CdgSingerColours()
    return {
        part: round_12bit(long_hex(getattr(chosen, part) or getattr(colours, part)))
        for part in ("unsung", "sung", "edge")
    }


def cdg_profile(profile: Profile, step: FitStep | None = None) -> Profile:
    """Return the profile as the CD+G screen draws it.

    Args:
        profile: A profile with a ``cdg`` section.
        step: The fallback step; ``None`` for the look as declared.

    Raises:
        ValueError: If the profile has no ``cdg`` section.
        pydantic.ValidationError: If the result breaks a rule of a profile (the loader refuses
            such sections, so this does not happen for a profile it has accepted).
    """
    section = cdg_section(profile)
    data = profile.model_dump()
    data["slots"] = section.slots
    data["font"]["size"] = section.font_px / SAFE_HEIGHT_PX
    data["font"]["min_size"] = section.min_font_px / SAFE_HEIGHT_PX
    data["edge"]["width"] = section.edge_px / section.font_px
    data["shadow"]["offset"] = 0.0
    data["ending"]["fade"] = 0.0
    overrides = section.colours
    data["background"] = round_12bit(long_hex(overrides.background or profile.background))
    for key in SINGLE_KEYS:
        data["colours"][key] = _rounded(getattr(profile.colours, key), getattr(overrides, key))
    if step is not None:
        data["page"]["turn"] = step.page_turn
        data["lead_in"] = {
            "min": step.lead_min,
            "target": step.lead_target,
            "max": profile.lead_in.max,
        }
    return Profile.model_validate(data)
