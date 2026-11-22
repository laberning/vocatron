"""Stage 1: the sample songs the profile check lays out (ADR-0019)."""

from fakes.measure import FixedMeasurer
from fakes.scenes import profile
from vocatron.core.layout.sample import (
    SAMPLE_SINGERS,
    sample_scene,
    sample_scenes,
    timed_song,
)
from vocatron.core.presets import PRESETS
from vocatron.core.scene import CardElement, Scene


def card_texts(scene: Scene, kind: str) -> list[str]:
    return [
        line.text
        for e in scene.elements
        if isinstance(e, CardElement) and e.kind == kind
        for line in e.lines
    ]


def test_every_sample_scene_is_laid_out_for_the_preset_asked_for() -> None:
    preset = PRESETS["16x9-1080"]
    found = sample_scenes(profile(), FixedMeasurer(), preset.name)
    assert [title for title, _ in found] == [
        "sample lyrics", "Alle meine Entchen", "Hänschen klein (duet)", "Hänschen klein (turns)",
    ]  # fmt: skip
    assert {(s.width, s.height) for _, s in found} == {(preset.width, preset.height)}
    durations = [s.duration for _, s in found]
    assert durations == [120.0, 60.0, 45.0, 45.0]  # the duets start at 4 s: 5 s of intro


def test_only_the_last_duet_changes_singers_inside_lines() -> None:
    found = dict(sample_scenes(profile(), FixedMeasurer()))
    assert not any(x.turns for x in found["Hänschen klein (duet)"].lines())
    assert any(x.turns for x in found["Hänschen klein (turns)"].lines())


def test_the_sample_lyrics_have_their_title_singers_and_gaps() -> None:
    scene = sample_scene(profile(), FixedMeasurer())
    assert card_texts(scene, "title")[:2] == ["Ein Titel", "Eine Künstlerin"]
    assert {x.singers for x in scene.lines()} == set(SAMPLE_SINGERS)
    lines = scene.lines()
    assert lines[0].sing_start == 9.0
    gaps = [b.sing_start - a.sing_end for a, b in zip(lines, lines[1:], strict=False)]
    assert max(gaps) > 19.0


def test_the_case_of_the_profile_applies_to_the_sample() -> None:
    upper = profile().model_copy(
        update={"font": profile().font.model_copy(update={"case": "upper"})}
    )
    assert sample_scene(upper, FixedMeasurer()).lines()[0].text.isupper()


def test_a_timed_song_starts_at_twelve_seconds_with_estimated_words() -> None:
    song = timed_song("eins zwei\n")
    assert song.words[0].start == 12.0
    assert all(w.estimated for w in song.words)
