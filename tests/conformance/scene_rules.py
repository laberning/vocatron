"""The rules of the classic presentation as an assertion on a scene (ADR-0009, ADR-0019).

The rules live in ``vocatron.core.layout.rules`` (the profile check uses them too); this is the
form the tests use: ``check_scene`` fails with the messages of the rules that do not hold.
"""

from vocatron.core.layout.rules import scene_findings
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import Scene


def check_scene(scene: Scene, profile: Profile) -> None:
    """Fail with the message of every rule that does not hold for ``scene``."""
    assert scene_findings(scene, profile) == []
