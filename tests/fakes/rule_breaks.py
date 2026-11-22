"""Helpers of the tests that break a scene rule: break one thing in a clean sample scene."""

import re
from collections.abc import Callable
from typing import Any

from pydantic import JsonValue

from fakes.scenes import (
    builtin_profile,
    entchen_scene,
    entchen_with,
    profile,
)
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.rules_base import TOLERANCE
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    CardElement,
    Keyframe,
    LineElement,
    Rect,
    Scene,
    SceneElement,
)

SMALL = TOLERANCE / 2  # inside the slack of the rules


BIG = TOLERANCE * 3  # outside it


def hits(scene: Scene, chosen: Profile) -> set[str]:
    """Return which rules complain: their numbers, ``overlap`` for the overlap check."""
    found = set()
    for message in scene_findings(scene, chosen):
        number = re.match(r"rule (\d+)", message)
        found.add(number.group(1) if number else "overlap")
    return found


def messages(scene: Scene, chosen: Profile, rule: int) -> list[str]:
    """Return the findings of rule ``rule``."""
    return [m for m in scene_findings(scene, chosen) if m.startswith(f"rule {rule}")]


def mutate(scene: Scene, kind: str, nth: int, change: Callable[[Any], Any]) -> Scene:
    """Return ``scene`` with the ``nth`` element of ``kind`` replaced by ``change(element)``."""
    seen = -1
    elements: list[SceneElement] = []
    for element in scene.elements:
        if element.kind == kind:
            seen += 1
            elements.append(change(element) if seen == nth else element)
        else:
            elements.append(element)
    assert seen >= nth, f"the scene has no {kind} number {nth}"
    return scene.model_copy(update={"elements": elements})


def line_far_away(card: CardElement) -> CardElement:
    """Return the card with its first line moved to a corner, out of the frame of its mark."""
    far = card.lines[0].model_copy(update={"box": Rect(x=0, y=0, w=10, h=10)})
    return card.model_copy(update={"lines": [far, *card.lines[1:]]})


def word_outside(card: CardElement) -> CardElement:
    """Return the card with the wordmark of its mark moved out of the safe area."""
    assert card.mark is not None
    out = card.mark.word.model_copy(update={"x": -5.0})
    return card.model_copy(update={"mark": card.mark.model_copy(update={"word": out})})


def edit(scene: Scene, kind: str, nth: int, **update: Any) -> Scene:
    """Return ``scene`` with fields of the ``nth`` element of ``kind`` changed."""
    return mutate(scene, kind, nth, lambda e: e.model_copy(update=update))


def without(scene: Scene, kind: str) -> Scene:
    """Return ``scene`` without any element of ``kind``."""
    return scene.model_copy(update={"elements": [e for e in scene.elements if e.kind != kind]})


def shifted(box: Rect, dx: float = 0.0, dy: float = 0.0) -> Rect:
    """Return ``box`` moved."""
    return Rect(x=box.x + dx, y=box.y + dy, w=box.w, h=box.h)


def with_span(line: LineElement, number: int, **update: float) -> LineElement:
    """Return ``line`` with fields of syllable ``number`` changed."""
    spans = list(line.spans)
    spans[number] = spans[number].model_copy(update=update)
    return line.model_copy(update={"spans": spans})


def page_profile() -> Profile:
    return builtin_profile("blue-page")


def page_scene() -> Scene:
    return entchen_with(page_profile())


def preview_profile() -> Profile:
    return builtin_profile("one-line-preview")


def preview_scene() -> Scene:
    return entchen_with(preview_profile())


def progress_profile() -> Profile:
    return builtin_profile("blue-page")


P = profile()


NO_INTRO = profile(intro={"solo": 0.0, "group": 0.0})  # for songs that start early


LINE_COUNT = len(entchen_scene().lines())


def title_of(scene: Scene) -> CardElement:
    return next(e for e in scene.elements if isinstance(e, CardElement) and e.kind == "title")


def palette(number: int) -> JsonValue:
    return {
        "unsung": f"#ff{number}0{number}0",
        "sung": f"#0{number}ff{number}0",
        "edge": f"#{number}0{number}0ff",
    }


PALETTES: dict[str, JsonValue] = {f"singer{i}": palette(i) for i in range(1, 6)}
PALETTES["group"] = palette(6)


CP = profile(
    colours=PALETTES
)  # the built-in profiles give every singer the same unsung and edge colour


FADE_PROFILE = profile(cdg=None, transition={"form": "fade", "time": 0.3})


def rule_20(scene: Scene, chosen: Profile = FADE_PROFILE) -> list[str]:
    return messages(scene, chosen, 20)


def sooner(scene: Scene, chosen: Profile) -> bool:
    """Tell whether rule 5 says a reported line could have appeared sooner."""
    return "could appear sooner" in " ".join(messages(scene, chosen, 5))


LONG_LINE = " ".join(["lala"] * 6)  # too wide for one row at the size of the sample


FRAME = (960, 720)


def form_scene(form: str) -> tuple[Scene, Profile]:
    """The scrolling folk song with the break screen of the form ``form``."""
    chosen = builtin_profile("lyric-scroll", breaks={"form": form})
    return entchen_with(chosen), chosen


def moved_path(path: list[Keyframe], by: float) -> list[Keyframe]:
    return [Keyframe(time=k.time, y=k.y + by) for k in path]
