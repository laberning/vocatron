"""Rules 1 to 17 and 19 to 23 of the presentation as checks on a scene (ADR-0009, ADR-0019).

Every rule takes the scene and the profile it was made with, looks at the model only (never a
frame) and raises ``RuleBroken`` with a message that names the rule. ``scene_findings`` runs
them all and returns the messages of those that do not hold. The profile check
(``vocatron.core.profiles.check``) runs it for a fan's profile, the property tests run it over
generated songs and the profile conformance kit for every registered profile. Rule 18, the
contrast of the colours, belongs to the profile, not the scene (``profile_problems``).

The rules check what the scene says about itself, not what the layout was given. The rules live
by family in ``rules_slots``, ``rules_showing``, ``rules_cards``, ``rules_singers`` and
``rules_scroll``; the helpers they share are in ``rules_base``. This module holds the list in
the order the rules run.
"""

from typing import Protocol

from vocatron.core.layout.rules_base import RuleBroken
from vocatron.core.layout.rules_cards import (
    rule_13_countdown,
    rule_14_title,
    rule_15_ending,
    rule_19_intro,
)
from vocatron.core.layout.rules_scroll import no_overlap, rule_21_scroll_path
from vocatron.core.layout.rules_showing import (
    rule_5_lead_in,
    rule_6_visible_while_sung,
    rule_7_wipe_in_time,
    rule_8_held_notes,
    rule_9_hold_and_clear,
    rule_10_replacement_order,
    rule_11_short_gaps,
    rule_12_long_gaps,
)
from vocatron.core.layout.rules_singers import (
    rule_16_singers,
    rule_17_slots,
    rule_20_transitions,
    rule_22_restart_after_break,
    rule_23_blocks,
)
from vocatron.core.layout.rules_slots import (
    rule_1_safe_area,
    rule_2_slots,
    rule_3_fit,
    rule_4_alignment,
)
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import Scene

RULES = (
    rule_1_safe_area, rule_2_slots, rule_3_fit, rule_4_alignment, rule_5_lead_in,
    rule_6_visible_while_sung, rule_7_wipe_in_time, rule_8_held_notes, rule_9_hold_and_clear,
    rule_10_replacement_order, rule_11_short_gaps, rule_12_long_gaps, rule_13_countdown,
    rule_14_title, rule_15_ending, rule_16_singers, rule_17_slots,
    rule_19_intro, rule_20_transitions, rule_21_scroll_path, rule_22_restart_after_break,
    rule_23_blocks, no_overlap,
)  # fmt: skip


class Rule(Protocol):
    """A rule of the scene: a named function that raises when the scene breaks it."""

    __name__: str

    def __call__(self, scene: Scene, profile: Profile, /) -> None:
        """Check ``scene`` made with ``profile``."""


def _label(rule: Rule) -> str:
    """Return how findings name ``rule``: ``rule 12`` for ``rule_12_long_gaps``, else its name."""
    parts = rule.__name__.split("_")
    return f"rule {parts[1]}" if parts[0] == "rule" else " ".join(parts)


def scene_findings(scene: Scene, profile: Profile) -> list[str]:
    """Run every rule on ``scene``; return the message of each rule that does not hold.

    A rule reports its first problem only. An empty list means the scene follows the rules. A
    scene so inconsistent that a rule fails on it in another way (a countdown before no line, a
    progress bar with no break screen) gives the finding ``rule N could not be checked`` with
    the kind of error, so a check of a profile never stops at a layout bug.
    """
    found: list[str] = []
    for rule in RULES:
        try:
            rule(scene, profile)
        except RuleBroken as broken:
            found.append(str(broken))
        except Exception as error:  # any other error means the scene contradicts itself
            found.append(f"{_label(rule)} could not be checked: {type(error).__name__}")
    return found
