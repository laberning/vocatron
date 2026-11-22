"""Stage 1: the silent intro before the song: the amount, the scene, the legend (ADR-0020)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from conformance.scene_rules import check_scene
from fakes.measure import FixedMeasurer
from fakes.phrases import line
from fakes.scenes import duet_with, profile
from vocatron.core.ass.parse import parse_ass
from vocatron.core.ass.write import write_ass
from vocatron.core.layout.build import SongText, layout, together_labels
from vocatron.core.layout.intro import intro_lead, intro_minimum
from vocatron.core.layout.phrases import (
    Phrase,
    Turn,
    is_ensemble,
    marks_of,
    numbers_in,
    shifted,
)
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.rules_base import TOLERANCE
from vocatron.core.layout.sample import DUET_TURNS, SAMPLE_BPM, song_text
from vocatron.core.lyrics.document import SingerInfo
from vocatron.core.profiles.model import Intro, Profile
from vocatron.core.scene import CardElement, CountdownElement, Scene

FRAME = (960, 720)
OFF: dict[str, JsonValue] = {"solo": 0.0, "group": 0.0}
NAMES = {1: SingerInfo(name="Anna"), 2: SingerInfo(name="Ben"), 3: SingerInfo(name="Cleo")}


def scene_of(
    phrases: list[Phrase],
    chosen: Profile | None = None,
    names: dict[int, SingerInfo] | None = None,
    duration: float | None = 60.0,
) -> Scene:
    look = chosen or profile()
    text = SongText("Titel", "Künstler", duration, names or {}, "Beide", "Alle")
    built = layout(phrases, text, look, FRAME, FixedMeasurer())
    check_scene(built, look)
    return built


def cards(scene: Scene, kind: str) -> list[CardElement]:
    return [e for e in scene.elements if isinstance(e, CardElement) and e.kind == kind]


# ------------------------------------------------------------------ the amount


def test_the_built_in_minimums_are_eight_seconds_alone_and_nine_together() -> None:
    assert profile().intro == Intro(solo=8.0, group=9.0)


@pytest.mark.parametrize(
    ("first", "ensemble", "lead"),
    [
        (1.5, False, 6.5),  # a solo song missing 6.5 s
        (8.0, False, 0.0),  # exactly late enough
        (9.0, False, 0.0),
        (2.0, True, 7.0),  # a duet missing 7 s
        (8.5, True, 0.5),  # a duet needs more than a solo
        (0.0, True, 9.0),
    ],
)
def test_only_as_much_silence_as_is_missing(first: float, ensemble: bool, lead: float) -> None:
    assert intro_lead(first, ensemble, profile()) == pytest.approx(lead)


def test_zero_turns_the_intro_off() -> None:
    off = profile(intro=OFF)
    assert intro_lead(0.5, False, off) == 0.0
    assert intro_lead(0.5, True, off) == 0.0


def test_the_minimum_follows_the_profile_and_the_ensemble() -> None:
    own = profile(intro={"solo": 3.0, "group": 9.0})
    assert (intro_minimum(False, own), intro_minimum(True, own)) == (3.0, 9.0)


@given(
    first=st.floats(0, 60, allow_nan=False),
    ensemble=st.booleans(),
    solo=st.floats(0, 20, allow_nan=False),
    extra=st.floats(0, 20, allow_nan=False),
)
def test_the_lead_is_never_negative_and_the_first_word_is_never_before_the_minimum(
    first: float, ensemble: bool, solo: float, extra: float
) -> None:
    look = profile(intro={"solo": solo, "group": solo + extra})
    lead = intro_lead(first, ensemble, look)
    minimum = intro_minimum(ensemble, look)
    assert lead >= 0
    assert first + lead >= minimum - 0.0006  # rounded to a thousandth
    assert (lead == 0) == (first >= minimum - 0.0005)  # none exactly when late enough


@given(
    first=st.floats(0, 30, allow_nan=False),
    gaps=st.lists(st.floats(0.5, 10, allow_nan=False), min_size=1, max_size=5),
    lead=st.floats(0, 20, allow_nan=False),
)
def test_shifting_keeps_every_gap(first: float, gaps: list[float], lead: float) -> None:
    starts = [first]
    for gap in gaps:
        starts.append(starts[-1] + 1.0 + gap)
    phrases = [line(start, start + 1.0) for start in starts]
    later = shifted(phrases, lead)
    for before, after in zip(phrases, later, strict=True):
        assert after.start == pytest.approx(before.start + lead)
        assert after.end == pytest.approx(before.end + lead)
        assert after.text == before.text
    assert [b.start - a.end for a, b in zip(later, later[1:], strict=False)] == pytest.approx(
        [b.start - a.end for a, b in zip(phrases, phrases[1:], strict=False)]
    )


def test_shifting_by_nothing_changes_nothing() -> None:
    phrases = [line(1.0, 2.0)]
    assert shifted(phrases, 0.0) == phrases


# ------------------------------------------------------------------ who counts as a group


def test_a_song_of_one_singer_is_solo() -> None:
    assert not is_ensemble(marks_of([line(1, 2), line(3, 4)]))


@pytest.mark.parametrize("marks", [["1", "2"], ["all"], ["1,2"], ["1", "1,3"]])
def test_more_singers_or_a_group_or_all_make_an_ensemble(marks: list[str]) -> None:
    assert is_ensemble(marks)


def test_a_turn_to_another_singer_makes_an_ensemble() -> None:
    phrase = line(1, 3)
    turned = Phrase("1", phrase.pieces, (Turn(1, "2"),))
    assert marks_of([turned]) == ["1", "2"]
    assert is_ensemble(marks_of([turned]))


def test_all_names_no_single_singer() -> None:
    assert numbers_in(["all", "1,3", "2"]) == {"1", "2", "3"}


# ------------------------------------------------------------------ the scene


def test_a_solo_song_that_starts_at_once_is_shifted_to_eight_seconds() -> None:
    scene = scene_of([line(1.5, 3.0), line(4.0, 6.0)])
    assert scene.lead == 6.5
    first, second = scene.lines()
    assert first.sing_start == pytest.approx(8.0)
    assert second.sing_start == pytest.approx(10.5)
    assert scene.duration == pytest.approx(66.5)  # the song's 60 s and the lead


def test_a_song_that_starts_late_enough_gets_no_intro() -> None:
    scene = scene_of([line(10.0, 12.0)])
    assert scene.lead == 0.0
    assert scene.lines()[0].sing_start == 10.0
    assert scene.duration == 60.0


def test_the_intro_off_leaves_the_song_as_it_is() -> None:
    scene = scene_of([line(1.0, 3.0)], profile(intro=OFF))
    assert scene.lead == 0.0
    assert scene.lines()[0].sing_start == 1.0


def test_a_duet_is_shifted_to_nine_seconds() -> None:
    scene = scene_of([line(2.0, 3.0, singers="1"), line(4.0, 5.0, singers="2")])
    assert scene.lead == 7.0
    assert scene.lines()[0].sing_start == pytest.approx(9.0)


def test_a_line_for_everyone_alone_counts_as_a_group() -> None:
    assert scene_of([line(2.0, 3.0, singers="all")]).lead == 7.0


def test_every_element_is_later_by_the_lead() -> None:
    look = profile(intro=OFF)
    songs = [line(1.0, 3.0), line(4.0, 5.0), line(20.0, 22.0)]
    plain = scene_of(songs, look)
    moved = scene_of(songs)  # solo: 8 - 1 = 7 s
    assert moved.lead == 7.0
    assert [e.kind for e in moved.lines()] == [e.kind for e in plain.lines()]
    for before, after in zip(plain.lines(), moved.lines(), strict=True):
        assert after.sing_start == pytest.approx(before.sing_start + 7.0)
        assert after.sing_end == pytest.approx(before.sing_end + 7.0)
        assert [s.start for s in after.spans] == pytest.approx(
            [s.start + 7.0 for s in before.spans]
        )


def test_the_title_stays_five_seconds_for_a_solo_song_and_six_for_a_duet() -> None:
    (solo,) = cards(scene_of([line(1.0, 2.0)]), "title")
    assert (solo.start, solo.end) == (0.0, pytest.approx(5.0))
    duet = scene_of([line(1.0, 2.0, singers="1"), line(3.0, 4.0, singers="2")])
    (title,) = cards(duet, "title")
    assert (title.start, title.end) == (0.0, pytest.approx(6.0))


@pytest.mark.parametrize("singers", [("1", "1"), ("1", "2")])
def test_the_countdown_runs_in_the_intro_and_ends_at_the_first_word(
    singers: tuple[str, str],
) -> None:
    scene = scene_of([line(1.0, 2.0, singers=singers[0]), line(3.0, 4.0, singers=singers[1])])
    (countdown,) = [e for e in scene.elements if isinstance(e, CountdownElement)]
    first = scene.lines()[0].sing_start
    assert first >= 8.0 - 1e-6
    assert countdown.end == pytest.approx(first)
    (title,) = cards(scene, "title")
    assert countdown.start >= title.end - 1e-6


def test_the_ass_file_has_the_shifted_times() -> None:
    scene = scene_of([line(1.0, 3.0, "eins zwei")])
    script = parse_ass(write_ass(scene))
    events = [e for e in script.events if e.sweeps and not e.drawing and e.size is not None]
    (event,) = events
    assert event.sweep_end / 100 == pytest.approx(scene.lines()[0].sing_end, abs=0.01)
    assert scene.lines()[0].sing_end == pytest.approx(3.0 + scene.lead)


def test_a_song_without_lines_gets_no_intro() -> None:
    empty = layout([], SongText("T", None, 30.0, {}), profile(), FRAME, FixedMeasurer())
    assert (empty.lead, empty.duration) == (0.0, 30.0)


def test_without_a_known_length_the_video_ends_with_the_last_line() -> None:
    scene = scene_of([line(1.0, 3.0)], duration=None)
    assert scene.duration >= scene.lines()[0].end


def test_the_scene_says_its_lead_in_layout_json() -> None:
    scene = scene_of([line(1.0, 3.0)])
    assert Scene.model_validate_json(scene.model_dump_json()).lead == scene.lead


# ------------------------------------------------------------------ the rule


def broken(scene: Scene, look: Profile) -> list[str]:
    return [m for m in scene_findings(scene, look) if m.startswith("rule 19")]


def test_rule_19_holds_for_a_song_with_and_without_intro() -> None:
    look = profile()
    assert broken(scene_of([line(1.0, 2.0)]), look) == []
    assert broken(scene_of([line(11.0, 12.0)]), look) == []


def test_rule_19_finds_a_first_word_before_the_minimum() -> None:
    early = scene_of([line(1.0, 2.0)], profile(intro=OFF))  # no intro was added
    assert "below" in " ".join(broken(early, profile()))


def test_rule_19_finds_more_silence_than_was_missing() -> None:
    look = profile()
    scene = scene_of([line(9.0, 10.0)])
    assert "missing" in " ".join(broken(scene.model_copy(update={"lead": 2.0}), look))


def test_rule_19_finds_a_negative_lead() -> None:
    assert broken(scene_of([line(9.0, 10.0)]).model_copy(update={"lead": -1.0}), profile())


def test_rule_19_finds_a_lead_without_lines() -> None:
    empty = layout([], SongText("T", None, 30.0, {}), profile(), FRAME, FixedMeasurer())
    assert broken(empty.model_copy(update={"lead": 2.0}), profile())


def test_rule_19_asks_a_duet_for_nine_seconds() -> None:
    solo_only = profile(intro={"solo": 8.0, "group": 0.0})
    duet = scene_of([line(2.0, 3.0, singers="1"), line(4.0, 5.0, singers="2")], solo_only)
    assert duet.lead == 0.0
    assert "below 9.0" in " ".join(broken(duet, profile()))


# ------------------------------------------------------------------ the legend


def labels(*marks: str, names: dict[int, SingerInfo] | None = None) -> tuple[str, ...]:
    phrases = [line(i * 2.0, i * 2.0 + 1.0, singers=mark) for i, mark in enumerate(marks)]
    return together_labels(phrases, SongText("T", None, None, names or {}, "Beide", "Alle"))


def test_a_group_of_some_singers_is_listed_by_their_names() -> None:
    assert labels("1", "2", "3", "1,3", names=NAMES) == ("Anna & Cleo",)


def test_all_is_the_word_of_the_language_for_two_singers() -> None:
    assert labels("1", "2", "all", names={1: NAMES[1], 2: NAMES[2]}) == ("Beide",)


def test_all_is_the_other_word_for_three_singers() -> None:
    assert labels("1", "2", "3", "all", names=NAMES) == ("Alle",)


def test_a_group_naming_every_singer_is_shown_with_the_word_and_listed_once() -> None:
    assert labels("1", "2", "1,2", "all", "1,2", names={1: NAMES[1], 2: NAMES[2]}) == ("Beide",)


def test_a_group_is_listed_only_when_all_its_members_have_names() -> None:
    assert labels("1", "2", "3", "1,3", names={1: NAMES[1], 2: NAMES[2]}) == ()


def test_each_group_is_listed_once_in_order() -> None:
    marks = ("1", "2", "3", "2,3", "1,2", "2,3")
    assert labels(*marks, names=NAMES) == ("Ben & Cleo", "Anna & Ben")


def test_a_solo_song_and_a_duet_without_shared_lines_list_no_group() -> None:
    assert labels("1", "1", names=NAMES) == ()
    assert labels("1", "2", names=NAMES) == ()


def test_a_singer_without_a_name_still_counts_for_the_word() -> None:
    two = {1: NAMES[1], 2: NAMES[2]}
    assert labels("1", "2", "3", "all", names={**two, 3: SingerInfo(name="Cleo")}) == ("Alle",)
    assert labels("1", "2", "3", "all", names=two) == ()  # singer 3 has no name


def test_everyone_is_listed_only_when_every_singer_has_a_name() -> None:
    assert labels("1", "2", "all") == ()
    assert labels("1", "2", "1,2", names={1: NAMES[1]}) == ()
    assert labels("all") == ()  # nobody is named at all


def test_a_language_without_the_word_lists_no_group_of_everyone() -> None:
    phrases = [line(1, 2, singers="1"), line(3, 4, singers="2"), line(5, 6, singers="all")]
    names = {1: NAMES[1], 2: NAMES[2]}
    assert together_labels(phrases, SongText("T", None, None, names)) == ()


def test_the_title_screen_lists_the_group_in_the_group_colour() -> None:
    look = profile()
    names = {1: NAMES[1], 2: NAMES[2]}
    scene = scene_of([line(8.0, 9.0, singers="1"), line(10.0, 11.0, singers="all")], look, names)
    (title,) = cards(scene, "title")
    texts = [x.text for x in title.lines]
    assert texts[-3:] == ["Anna", "Ben", "Beide"]
    assert title.lines[-1].colour == look.colours.group.sung


def test_a_song_without_lines_together_has_no_group_entry_on_the_title() -> None:
    scene = scene_of(
        [line(8.0, 9.0, singers="1"), line(10.0, 11.0, singers="2")],
        names={1: NAMES[1], 2: NAMES[2]},
    )
    (title,) = cards(scene, "title")
    assert [x.text for x in title.lines][-2:] == ["Anna", "Ben"]


def test_a_title_without_singers_has_no_group_entry_either() -> None:
    look = profile(title={"fields": ["title", "artist"]})
    scene = scene_of([line(8.0, 9.0, singers="all")], look)
    (title,) = cards(scene, "title")
    assert [x.text for x in title.lines] == ["Titel", "Künstler"]


def test_the_duet_sample_with_turns_keeps_the_rules_with_an_intro() -> None:
    scene = duet_with(profile(), turns=DUET_TURNS)
    assert scene.lead == 5.0
    check_scene(scene, profile())


def test_shifting_keeps_who_sings_and_the_turns() -> None:
    phrase = line(1, 3, "eins zwei", singers="1")
    turned = Phrase("1", phrase.pieces, (Turn(1, "all"),))
    (later,) = shifted([turned], 2.0)
    assert (later.singers, later.turns) == ("1", (Turn(1, "all"),))


def test_a_singer_whose_name_is_empty_has_no_name() -> None:
    names = {1: NAMES[1], 2: SingerInfo(name=None)}
    assert labels("1", "2", "1,2", names=names) == ()


def test_an_unnamed_group_does_not_hide_the_groups_after_it() -> None:
    assert labels("1", "2", "3", "1,4", "2,3", names=NAMES) == ("Ben & Cleo",)


def test_the_sample_songs_use_the_german_words() -> None:
    expected = SongText("T", "A", 1.0, NAMES, "Beide", "Alle", SAMPLE_BPM)
    assert song_text("T", "A", 1.0, NAMES) == expected
    assert song_text("T", "A", 1.0, NAMES, None).bpm is None


def test_rule_19_a_song_without_lines_and_without_lead_holds() -> None:
    empty = layout([], SongText("T", None, 30.0, {}), profile(), FRAME, FixedMeasurer())
    assert broken(empty, profile()) == []
    found = broken(empty.model_copy(update={"lead": 1.0}), profile())
    assert "without sung lines" in " ".join(found)


def test_edge_rule_19_a_first_word_exactly_the_slack_early_holds() -> None:
    early = scene_of([line(8.0 - TOLERANCE, 10.0)], profile(intro=OFF))
    assert early.lines()[0].sing_start == 8.0 - TOLERANCE
    assert broken(early, profile()) == []


def test_edge_rule_19_a_lead_exactly_the_slack_too_long_holds() -> None:
    late = scene_of([line(9.0, 10.0)])
    assert broken(late.model_copy(update={"lead": TOLERANCE}), profile()) == []
