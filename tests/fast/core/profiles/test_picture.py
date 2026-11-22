"""Stage 1: what the picture of a look shows and when it goes stale (ADR-0019, ADR-0045).

The moments are checked on the committed timing of the English demo song with every built-in
look, and on a made-up duet for the edge cases. Messages name looks, kinds and numbers, never
lyrics.
"""

import functools

import pytest

from fakes.measure import FixedMeasurer
from fakes.picture_song import made_up_song
from fakes.resources import FakeResources
from picture_song import SONG_FILE, committed_song
from vocatron.core.languages import LANGUAGES
from vocatron.core.layout.rules import scene_findings
from vocatron.core.layout.rules_base import is_later_row
from vocatron.core.lyrics.file import LyricLine
from vocatron.core.profiles.model import BUILTIN_PROFILES, Profile, parse_profile
from vocatron.core.profiles.picture import (
    CHANGE_DELAY,
    COUNTDOWN_BEFORE,
    END_SCREEN_AFTER,
    MOMENT_NAMES,
    START_SCREEN_AT,
    Moment,
    PictureSong,
    parse_picture_song,
    picture_digest,
    picture_moments,
    picture_scene,
    picture_text,
    render_picture_song,
)
from vocatron.core.scene import CardElement, CountdownElement, LineElement, Scene
from vocatron.engines.measure import PillowMeasurer

RESOURCES = FakeResources()
MEASURER = PillowMeasurer(RESOURCES.font_file())
SONG = committed_song()


def profile_of(name: str) -> Profile:
    return parse_profile(name, RESOURCES.builtin_profile(name) or "")


@functools.cache
def made(name: str) -> tuple[Profile, Scene, list[Moment]]:
    """The demo song laid out in a look and its moments, once per test process."""
    profile = profile_of(name)
    scene = picture_scene(SONG, profile, MEASURER)
    return profile, scene, picture_moments(scene, profile)


def kinds_at(scene: Scene, seconds: float) -> list[str]:
    return sorted(e.kind for e in scene.visible_at(seconds))


def test_the_committed_timing_is_a_duet_with_a_long_intro_and_a_long_break() -> None:
    assert len(SONG.lines) > 30
    assert len({x.singers for x in SONG.lines if x.singers.isdigit()}) >= 2
    assert any(not x.singers.isdigit() for x in SONG.lines)  # lines sung together
    assert SONG.language in {"de", "en"}
    assert render_picture_song(parse_picture_song(SONG_FILE.read_text(encoding="utf-8"))) == (
        SONG_FILE.read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_the_picture_scene_follows_the_rules_with_named_singers_and_a_long_break(
    name: str,
) -> None:
    profile, scene, _ = made(name)
    assert scene_findings(scene, profile) == []
    assert scene_findings(picture_scene(SONG, profile, FixedMeasurer()), profile) == []
    (title,) = [e for e in scene.elements if isinstance(e, CardElement) and e.kind == "title"]
    names = {info.name for info in SONG.singers.values() if info.name}
    assert len(names) >= 2 and names <= {line.text for line in title.lines}
    lines = scene.lines()
    assert max(b.sing_start - a.sing_end for a, b in zip(lines, lines[1:], strict=False)) > 20


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_there_are_six_moments_in_the_order_of_the_sheet(name: str) -> None:
    _, scene, moments = made(name)
    assert [m.name for m in moments] == list(MOMENT_NAMES)
    assert all(0 <= m.seconds < scene.duration for m in moments)


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_five_moments_are_at_the_same_song_time_in_every_look(name: str) -> None:
    _, _, moments = made(name)
    _, _, reference = made("two-line-turns")
    same = [i for i in range(6) if i != 2]
    assert [moments[i].seconds for i in same] == [reference[i].seconds for i in same]
    assert moments[0].seconds == START_SCREEN_AT


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_the_start_screen_shows_the_title_and_no_line(name: str) -> None:
    _, scene, moments = made(name)
    assert kinds_at(scene, moments[0].seconds) == ["title"]


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_a_line_sung_together_is_half_sung_in_the_second_moment(name: str) -> None:
    _, scene, moments = made(name)
    at = moments[1].seconds
    singing = [x for x in scene.lines() if x.visible(at) and x.sing_start < at < x.sing_end]
    assert singing, name
    assert all(not x.singers.isdigit() for x in singing)
    front = singing[0].wipe_front(at, scene.look)
    assert singing[0].spans[0].x0 < front < singing[0].spans[-1].x1


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_a_line_or_page_has_just_appeared_in_the_third_moment_once_both_sing(name: str) -> None:
    profile, scene, moments = made(name)
    at = moments[2].seconds
    lines = scene.lines()
    together = next(i for i, x in enumerate(lines) if not x.singers.isdigit())
    assert at > lines[together].sing_start - 60  # in the part where the singers sing together
    if profile.mode == "scroll":
        gliding = [
            x
            for x in lines
            if any(
                a.time <= at <= b.time and a.y > b.y
                for a, b in zip(x.path, x.path[1:], strict=False)
            )
        ]
        assert gliding, name
        return
    fresh = [
        lines.index(x) for x in lines if x.visible(at) and 0 <= at - x.start <= CHANGE_DELAY + 0.01
    ]
    assert fresh and max(fresh) >= together, name  # the first line sung together has appeared


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_the_change_comes_after_the_line_sung_together_so_the_sheet_reads_in_song_order(
    name: str,
) -> None:
    _, _, moments = made(name)
    assert moments[0].seconds < moments[1].seconds < moments[2].seconds < moments[3].seconds, name
    profile, scene = laid(made_up_song(singers=["1", "2", "all", "1"] * 3, gaps={6: 22.0}), name)
    sung, change = (m.seconds for m in picture_moments(scene, profile)[1:3])
    assert sung < change, name


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_the_break_screen_shows_in_the_fourth_moment_with_no_countdown(name: str) -> None:
    _, scene, moments = made(name)
    shown = scene.visible_at(moments[3].seconds)
    assert any(isinstance(e, CardElement) and e.kind == "break" for e in shown), name
    assert not any(isinstance(e, CountdownElement) for e in shown)


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_the_countdown_runs_in_the_fifth_moment_after_the_long_break(name: str) -> None:
    _, scene, moments = made(name)
    at = moments[4].seconds
    countdowns = [e for e in scene.visible_at(at) if isinstance(e, CountdownElement)]
    assert len(countdowns) == 1
    before = max(x.sing_end for x in scene.lines() if x.sing_end < countdowns[0].start)
    assert countdowns[0].start - before > 15
    assert moments[4].seconds > moments[3].seconds


@pytest.mark.parametrize("name", BUILTIN_PROFILES)
def test_the_end_screen_shows_in_the_sixth_moment_before_the_song_ends(name: str) -> None:
    _, scene, moments = made(name)
    last = max(x.sing_end for x in scene.lines())
    assert moments[5].seconds == round(last + END_SCREEN_AFTER, 3)
    assert kinds_at(scene, moments[5].seconds) == ["end"]
    assert moments[5].seconds < (SONG.duration or 0)


def digest(
    tool: int = 1,
    text: str = "name: x\n",
    preset: str = "4x3-720",
    seconds: float = 1.0,
    ass: str = "[Script Info]\n",
    font: str = "f" * 64,
) -> str:
    return picture_digest(
        tool_version=tool,
        profile_text=text,
        preset=preset,
        moments=[Moment("a", seconds)],
        ass=ass,
        font_sha256=font,
    )


def test_the_digest_is_stable_and_follows_every_input() -> None:
    assert digest() == digest()
    assert len(digest()) == 64
    changed = [
        digest(tool=2),
        digest(text="name: y\n"),
        digest(preset="16x9-720"),
        digest(seconds=1.5),
        digest(ass="[Script Info]\nx\n"),
        digest(font="e" * 64),
    ]
    assert len({digest(), *changed}) == 7


def laid(song: PictureSong, name: str = "two-line-turns") -> tuple[Profile, Scene]:
    profile = profile_of(name)
    return profile, picture_scene(song, profile, FixedMeasurer())


def test_the_moments_of_a_made_up_duet_follow_the_rules_of_the_design() -> None:
    song = made_up_song()
    profile, scene = laid(song)
    moments = {m.name: m.seconds for m in picture_moments(scene, profile)}
    every = scene.lines()
    lines = [
        x for i, x in enumerate(every) if not is_later_row(every, i)
    ]  # a wrapped row is no line
    assert moments["start screen"] == START_SCREEN_AT
    first_of_second = next(x for x in lines if x.singers == "2")
    before = lines[lines.index(first_of_second) - 1]
    first_together = next(x for x in lines if not x.singers.isdigit())
    assert moments["a line sung together"] == round(
        (first_together.sing_start + first_together.sing_end) / 2, 3
    )
    gap_start, gap_end = before.sing_end, first_of_second.sing_start  # the longest gap
    assert moments["the break screen"] == round((gap_start + gap_end) / 2, 3)
    assert moments["the countdown"] == round(gap_end - COUNTDOWN_BEFORE, 3)
    assert moments["the end screen"] == round(lines[-1].sing_end + END_SCREEN_AFTER, 3)
    # the first change after the line sung together is half sung: two lines are on the screen
    sung = moments["a line sung together"]
    replacing = next(
        x for i, x in enumerate(lines) if x.start > sung and x.start > lines[i - 1].start
    )
    assert moments["a line or page change"] == round(replacing.start + CHANGE_DELAY, 3)


def test_a_song_of_one_singer_and_no_group_line_still_has_six_moments() -> None:
    song = made_up_song(singers=["1"] * 12)
    for name in BUILTIN_PROFILES:
        profile, scene = laid(song, name)
        moments = picture_moments(scene, profile)
        assert [m.name for m in moments] == list(MOMENT_NAMES), name
        first = scene.lines()[0]
        assert moments[1].seconds == round((first.sing_start + first.sing_end) / 2, 3)


def test_without_a_change_the_moment_is_just_after_a_line_that_appears_alone() -> None:
    song = made_up_song(singers=["1", "all"], gaps={1: 22.0}, count=2)  # two lines, never replaced
    for name in ("two-line-turns", "full-page", "lyric-scroll"):
        profile, scene = laid(song, name)
        together = next(x for x in scene.lines() if x.singers == "all")
        moments = picture_moments(scene, profile)
        assert moments[2].seconds == round(together.start + CHANGE_DELAY, 3), name
    alone = made_up_song(singers=["1", "1"], gaps={1: 22.0}, count=2)  # no line sung together
    profile, scene = laid(alone)
    moments = picture_moments(scene, profile)
    later = scene.lines()[1]  # appears on an empty screen after the line being sung
    assert moments[2].seconds == round(later.start + CHANGE_DELAY, 3) > moments[1].seconds


def test_in_scroll_mode_the_change_is_the_first_glide_after_the_first_line_sung_together() -> None:
    profile, scene = laid(made_up_song(), "lyric-scroll")
    lines = scene.lines()
    together = next(x for x in lines if not x.singers.isdigit())
    glide = next(
        (a.time + b.time) / 2
        for a, b in zip(together.path, together.path[1:], strict=True)
        if a.y > b.y and a.time >= together.sing_end
    )
    assert picture_moments(scene, profile)[2].seconds == round(glide, 3)


def test_a_long_intro_is_no_break() -> None:
    song = made_up_song(gaps={4: 6.0})  # the 20 s intro is longer than any gap between lines
    profile, scene = laid(song)
    lines = scene.lines()
    moments = picture_moments(scene, profile)
    assert lines[0].sing_end < moments[3].seconds < lines[-1].sing_start


def sung_lines(scene: Scene) -> list[LineElement]:
    every = scene.lines()
    return [x for i, x in enumerate(every) if not is_later_row(every, i)]


def sung_at(scene: Scene, profile: Profile) -> float:
    return picture_moments(scene, profile)[1].seconds


def test_the_moment_is_inside_the_first_line_sung_by_a_group_or_by_all() -> None:
    for singers in (
        ["1", "2", "1,2", "all", "1", "1", "2", "2", "all", "1", "2", "1"],
        ["1", "1", "1", "all", "2", "1,2", "1", "1", "2", "2", "all", "1"],
        ["1", "2", "1", "2", "1", "2", "1", "2", "1", "2", "1,2", "1"],
    ):
        profile, scene = laid(made_up_song(singers=singers))
        group = next(x for x in scene.lines() if not x.singers.isdigit())
        at = sung_at(scene, profile)
        assert group.sing_start < at < group.sing_end, singers
        assert at == round((group.sing_start + group.sing_end) / 2, 3)


def test_without_a_group_line_the_moment_is_in_the_first_line_of_the_second_singer() -> None:
    song = made_up_song(singers=["2", "2", "1", "1", "2", "1", "1", "2", "2", "1", "2", "1"])
    profile, scene = laid(song)
    other = next(x for x in sung_lines(scene) if x.singers == "1")
    assert other is not sung_lines(scene)[0]
    assert sung_at(scene, profile) == round((other.sing_start + other.sing_end) / 2, 3)


def test_the_second_singer_is_not_the_singer_of_the_first_line() -> None:
    song = made_up_song(singers=["1", "1", "1", "2"] * 3)
    profile, scene = laid(song)
    other = next(x for x in sung_lines(scene) if x.singers == "2")
    assert sung_at(scene, profile) == round((other.sing_start + other.sing_end) / 2, 3)


def test_the_moment_follows_the_first_group_line_not_a_later_one() -> None:
    early = made_up_song(singers=["1", "all", "1", "1", "1", "1", "1", "1", "1", "1", "all", "1"])
    late = made_up_song(singers=["1", "1", "1", "1", "1", "1", "1", "1", "1", "1", "all", "1"])
    p1, s1 = laid(early)
    p2, s2 = laid(late)
    assert sung_at(s1, p1) < sung_at(s2, p2)
    chosen = sung_lines(s1)[1]
    assert sung_at(s1, p1) == round((chosen.sing_start + chosen.sing_end) / 2, 3)


def test_the_rows_of_a_wrapped_line_count_as_one_line() -> None:
    song = made_up_song()
    profile = parse_profile(
        "one-line-preview",
        RESOURCES.builtin_profile("one-line-preview") or "",
        {"font": {"size": 0.3, "min_size": 0.1}},  # a line of two rows
    )
    scene = picture_scene(song, profile, FixedMeasurer())
    lines = scene.lines()
    assert any(is_later_row(lines, i) for i in range(len(lines)))
    moments = picture_moments(scene, profile)
    group = next(
        x for i, x in enumerate(lines) if not is_later_row(lines, i) and not x.singers.isdigit()
    )
    assert moments[1].seconds == round((group.sing_start + group.sing_end) / 2, 3)
    # a wrapped line is sung until its last row is: the break and the end screen count from there
    assert is_later_row(lines, len(lines) - 1)
    assert moments[5].seconds == round(lines[-1].sing_end + END_SCREEN_AFTER, 3)
    after = next(i for i, x in enumerate(lines) if i and x.sing_start - lines[i - 1].sing_end > 15)
    head = lines[after - 1 - lines[after - 1].row]
    gap_start = max(x.sing_end for x in lines[:after])
    assert gap_start > head.sing_end  # the second row ends later than the first
    assert moments[3].seconds == round((gap_start + lines[after].sing_start) / 2, 3)


def test_a_picture_song_survives_json_and_rejects_nonsense() -> None:
    song = made_up_song()
    assert parse_picture_song(render_picture_song(song)) == song
    assert render_picture_song(song).endswith("\n")
    with pytest.raises(ValueError, match="schema_version"):
        parse_picture_song(
            render_picture_song(song).replace('"schema_version": 1', '"schema_version": 2')
        )
    with pytest.raises(ValueError, match="title"):
        parse_picture_song("{}")


def test_the_lines_of_a_picture_song_are_lyric_lines() -> None:
    assert all(isinstance(x, LyricLine) for x in made_up_song().lines)
    assert all(isinstance(x, LineElement) for x in laid(made_up_song())[1].lines())


def test_the_song_has_more_lines_than_the_most_slots() -> None:
    most = Profile.model_fields["slots"].metadata
    assert len(SONG.lines) > max(m.le for m in most if hasattr(m, "le"))


def test_the_text_around_the_lines_is_the_song_s_with_the_words_of_its_language() -> None:
    song = made_up_song()
    text = picture_text(song)
    assert (text.title, text.artist, text.duration, text.singers, text.bpm) == (
        song.title,
        song.artist,
        song.duration,
        song.singers,
        song.bpm,
    )
    assert (text.together_two, text.together_all) == (
        LANGUAGES["de"].together_two,
        LANGUAGES["de"].together_all,
    )
    assert text.together_all and text.together_two != text.together_all


def test_a_song_of_one_line_has_no_gap_and_no_moments() -> None:
    profile, scene = laid(made_up_song(singers=["1"], gaps={}, count=1))
    with pytest.raises(ValueError, match="empty"):
        picture_moments(scene, profile)


def test_lines_that_appear_on_an_empty_screen_after_a_break_are_no_change() -> None:
    song = made_up_song(singers=["1"] * 4 + ["all"] * 8, gaps={4: 22.0})
    profile, scene = laid(song, "four-line-stack")  # two lines appear at once after the break
    lines = scene.lines()
    together = next(x for x in lines if x.singers == "all")
    shown = scene.visible_at(together.start - 0.01)
    assert not any(isinstance(e, LineElement) for e in shown)  # the screen was cleared
    assert any(e.kind == "break" for e in shown)  # but the break screen is up
    assert lines[lines.index(together) + 1].start == together.start
    moments = picture_moments(scene, profile)
    replacing = next(x for x in lines if x.start > moments[1].seconds)
    assert replacing.start > together.start  # not one of the two that appeared together
    assert moments[2].seconds == round(replacing.start + CHANGE_DELAY, 3)
