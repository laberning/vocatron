"""Stage 1: the rules hold on generated lyrics, in milliseconds, without rendering."""

import itertools
from typing import Any, Literal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from conformance.scene_rules import check_scene
from fakes.measure import FixedMeasurer
from fakes.phrases import line as sung_line
from fakes.resources import FakeResources
from vocatron.core.layout.build import SongText, layout
from vocatron.core.layout.phrases import Phrase, Piece, Turn, one_after_another
from vocatron.core.lyrics.document import SingerInfo
from vocatron.core.presets import PRESETS
from vocatron.core.profiles.model import (
    BUILTIN_PROFILES,
    Page,
    Pop,
    Preview,
    Profile,
    Transition,
    Upcoming,
    parse_profile,
)
from vocatron.core.scene import Scene

TEXT = FakeResources().builtin_profile("two-line-turns") or ""
BASE = parse_profile("two-line-turns", TEXT)
FRAMES = [(p.width, p.height) for p in PRESETS.values()]

SINGERS = st.sampled_from(["1", "2", "3", "4", "5", "all", "1,3", "2,5"])
SYLLABLE = st.text(alphabet="abdefgilmnoprstuwz", min_size=1, max_size=5)
WORD = st.lists(SYLLABLE, min_size=1, max_size=4)
LONG_WORD = st.lists(SYLLABLE, min_size=1, max_size=3).map(lambda parts: parts * 8)
LONG_TEXT = " ".join(["lala"] * 14)  # split into lines at the size of the sample
SECONDS = st.sampled_from([0.05, 0.2, 0.4, 0.8, 1.5])
SILENCE = st.sampled_from(
    [0.0, 0.3, 1.0, 3.0, 4.8, 4.9996, 5.0, 5.2, 6.0, 14.0, 15.0, 20.0, 45.0]
)  # around clear_after (5 s, 4.9996 rounds to it) and notice_after (15 s)


@st.composite
def song(draw: st.DrawFn) -> list[Phrase]:
    """Lines with long words, long lines, many short lines, long breaks and duets with turns.

    The lines never overlap in time, as the alignment gives them (ADR-0018).
    """
    mode = draw(st.sampled_from(["mixed", "short", "long-words", "long-lines"]))
    count = draw(st.integers(1, 3 if mode == "long-words" else 14))
    clock = draw(st.sampled_from([0.0, 0.5, 2.0, 4.0, 9.0, 30.0]))
    phrases: list[Phrase] = []
    previous_start = 0.0
    for _ in range(count):
        words = draw(
            st.lists(
                LONG_WORD if mode == "long-words" else WORD,
                min_size=1,
                max_size=3 if mode == "short" else 6,
            )
            if mode != "long-lines"
            else st.lists(WORD, min_size=7, max_size=14)
        )
        start = max(clock + draw(SILENCE), previous_start, 0.0)
        previous_start = start
        pieces: list[Piece] = []
        word_starts: list[int] = []  # the index of the first piece of each word
        for number, word in enumerate(words):
            word_starts.append(len(pieces))
            for position, syllable in enumerate(word):
                last_of_word = position == len(word) - 1
                end = start + draw(SECONDS)
                space = " " if last_of_word and number < len(words) - 1 else ""
                pieces.append(Piece(syllable + space, start, end))
                start = end
        singers = draw(SINGERS)
        turns: list[Turn] = []
        for number in sorted(
            draw(st.sets(st.integers(1, len(words) - 1), max_size=3)) if len(words) > 1 else []
        ):
            other = draw(
                SINGERS.filter(
                    lambda who, before=(turns[-1].singers if turns else singers): who != before
                )
            )
            turns.append(Turn(word_starts[number], other))
        phrases.append(Phrase(singers, tuple(pieces), tuple(turns)))
        clock = max(start, clock)
    return sorted(phrases, key=lambda phrase: phrase.start)


def run(
    phrases: list[Phrase], profile: Profile, frame: tuple[int, int], duration: float | None = 300.0
) -> Scene:
    info = SongText("Titel", "Künstler", duration, {1: SingerInfo(name="Anna", colour="#112233")})
    return layout(phrases, info, profile, frame, FixedMeasurer())


@settings(max_examples=150, deadline=None)
@given(phrases=song(), frame=st.sampled_from(FRAMES))
def test_the_rules_hold_on_generated_songs(phrases: list[Phrase], frame: tuple[int, int]) -> None:
    check_scene(run(phrases, BASE, frame), BASE)


def scaled(profile: Profile, slots: int, rows: int = 1) -> Profile:
    """The profile with ``slots`` slots of ``rows`` rows and a font small enough for the block."""
    size = min(0.12, 0.8 / (1.34 * slots * rows + 0.3))
    return profile.model_copy(
        update={
            "slots": slots,
            "line_rows": rows,
            "font": profile.font.model_copy(update={"size": size, "min_size": 0.66 * size}),
        }
    )


@settings(max_examples=60, deadline=None)
@given(phrases=song(), slots=st.integers(1, 6), granularity=st.sampled_from(["smooth", "syllable"]))
def test_the_rules_hold_for_other_slot_counts_and_wipes(
    phrases: list[Phrase], slots: int, granularity: str
) -> None:
    profile = scaled(BASE, slots).model_copy(
        update={
            "wipe": BASE.wipe.model_copy(update={"granularity": granularity, "offset": 0.1}),
            "countdown": BASE.countdown.model_copy(update={"form": "dots"}),
        }
    )
    check_scene(run(phrases, profile, (960, 720)), profile)


@settings(max_examples=60, deadline=None)
@given(
    phrases=song(),
    shape=st.sampled_from([(4, 2), (6, 2), (6, 3)]),
    rows=st.integers(1, 2),
    frame=st.sampled_from(FRAMES),
)
def test_the_rules_hold_when_the_lines_turn_in_blocks(
    phrases: list[Phrase], shape: tuple[int, int], rows: int, frame: tuple[int, int]
) -> None:
    slots, block = shape
    profile = scaled(BASE, slots, rows).model_copy(update={"block": block})
    scene = run(phrases, profile, frame)
    check_scene(scene, profile)  # rules 5, 9, 22 and 23 among them
    assert not [s for s in scene.shortfalls if s.kind == "block"]


@settings(max_examples=40, deadline=None)
@given(
    shape=st.sampled_from([(4, 2), (6, 2), (6, 3)]),
    rows=st.integers(1, 2),
    sizes=st.lists(st.integers(1, 5), min_size=1, max_size=4),
)
def test_the_rules_hold_when_runs_of_lines_end_in_a_break_or_the_song(
    shape: tuple[int, int], rows: int, sizes: list[int]
) -> None:
    # runs of 1 to 5 lines with a long break between: most end in a group shorter than its block
    slots, block = shape
    profile = scaled(BASE, slots, rows).model_copy(update={"block": block})
    clock, phrases = 1.0, list[Phrase]()
    for size in sizes:
        for _ in range(size):
            phrases.append(sung_line(clock, clock + 1.0, "la la"))
            clock += 1.5
        clock += profile.breaks.clear_after + 3.0
    scene = run(phrases, profile, (960, 720))
    check_scene(scene, profile)


@st.composite
def held_lines(draw: st.DrawFn) -> list[Phrase]:
    """Lines of which some are held long over the lines after them (backing vocals, a duet)."""
    clock = 1.0
    found: list[Phrase] = []
    for _ in range(draw(st.integers(1, 10))):
        clock += draw(st.sampled_from([0.5, 1.0, 2.0, 6.0]))
        long = draw(st.sampled_from([0.4, 1.0, 3.0, 12.0]))
        found.append(sung_line(clock, clock + long, draw(st.sampled_from(["la la", LONG_TEXT]))))
    return found


@settings(max_examples=80, deadline=None)
@given(
    phrases=held_lines(),
    shape=st.sampled_from([(4, 2), (6, 2), (6, 3)]),
    rows=st.integers(1, 2),
)
def test_the_rules_hold_when_held_lines_leave_no_block_free(
    phrases: list[Phrase], shape: tuple[int, int], rows: int
) -> None:
    # never more lines sung at once than slots (rule 17), so the placement can keep them apart
    ends = [(p.pieces[0].start, p.pieces[-1].end) for p in phrases]
    slots, block = shape
    assume(all(sum(a <= s < b for a, b in ends) <= slots - 1 for s, _ in ends))
    profile = scaled(BASE, slots, rows).model_copy(update={"block": block})
    check_scene(run(phrases, profile, (960, 720)), profile)  # rules 5, 9, 23 among them


@pytest.mark.parametrize("block", [1, 2])
def test_a_line_wrapped_onto_two_rows_and_held_long_goes_when_its_last_row_is_sung(
    block: int,
) -> None:
    # the long line wraps; its first row's words end before the lines after it go, its second
    # row's words after: both rows stay until the whole line is sung (rules 9 and 23)
    phrases = [sung_line(1.5, 4.5, LONG_TEXT)]
    phrases += [sung_line(start, start + 0.4, "la la") for start in (2.0, 2.5, 3.0, 3.5)]
    profile = scaled(BASE, 4, 2).model_copy(update={"block": block})
    scene = run(phrases, profile, (960, 720))
    wrapped = scene.lines()[:2]
    assert [x.row for x in wrapped] == [0, 1]
    assert wrapped[0].sing_end < wrapped[1].sing_end <= wrapped[0].end == wrapped[1].end
    check_scene(scene, profile)


def test_a_wrapped_line_held_in_its_block_stays_with_its_last_row() -> None:
    # the wrapped line is sung over the lines after it and stays until its last row is sung,
    # longer than its pair; rule 23 excuses it by the end of the whole line, not of its row
    phrases = [sung_line(1.5, 4.5, LONG_TEXT), sung_line(2.0, 5.0, "la la")]
    phrases += [sung_line(start, start + 0.4, "la la") for start in (2.5, 3.0, 3.5, 4.0, 4.5)]
    phrases += [sung_line(start, start + 0.4, "la la") for start in (5.0, 5.5)]
    profile = scaled(BASE, 4, 2).model_copy(update={"block": 2})
    check_scene(run(phrases, profile, (960, 720)), profile)


@settings(max_examples=150, deadline=None)
@given(
    phrases=song(),
    slots=st.integers(1, 6),
    lines=st.integers(1, 6),
    frame=st.sampled_from(FRAMES),
    form=st.sampled_from(["notice", "progress", "timer"]),
)
def test_the_rules_hold_in_page_mode(
    phrases: list[Phrase], slots: int, lines: int, frame: tuple[int, int], form: str
) -> None:
    profile = scaled(BASE, slots).model_copy(
        update={
            "mode": "page",
            "page": Page(min_lines=min(lines, slots)),
            "breaks": BASE.breaks.model_copy(update={"form": form}),
            "countdown": BASE.countdown.model_copy(update={"form": "blocks"}),
        }
    )
    check_scene(run(phrases, profile, frame), profile)


@settings(max_examples=100, deadline=None)
@given(
    phrases=song(),
    scale=st.sampled_from([0.4, 0.7, 0.9]),
    form=st.sampled_from(["notice", "progress", "timer"]),
)
def test_the_rules_hold_with_a_preview_and_a_progress_bar(
    phrases: list[Phrase], scale: float, form: str
) -> None:
    profile = scaled(BASE, 1).model_copy(
        update={
            "preview": Preview(show=True, scale=scale),
            "breaks": BASE.breaks.model_copy(update={"form": form}),
        }
    )
    scene = run(phrases, profile, (960, 720))
    check_scene(scene, profile)  # rule 4 keeps every preview inside the preview row
    assert scene.preview_row is not None


@settings(max_examples=150, deadline=None)
@given(
    phrases=song(),
    slots=st.integers(1, 3),
    mode=st.sampled_from(["line", "page"]),
    frame=st.sampled_from(FRAMES),
    preview=st.booleans(),
)
def test_the_rules_hold_with_lines_of_two_rows(
    phrases: list[Phrase], slots: int, mode: str, frame: tuple[int, int], preview: bool
) -> None:
    profile = scaled(BASE, slots, 2).model_copy(
        update={
            "mode": mode,
            "preview": Preview(show=preview and mode == "line" and slots == 1),
        }
    )
    scene = run(phrases, profile, frame)
    check_scene(scene, profile)
    assert not [s for s in scene.shortfalls if s.kind == "block"]


@settings(max_examples=40, deadline=None)
@given(phrases=song(), position=st.sampled_from(["top", "middle", "lower-third", "bottom"]))
def test_the_rules_hold_for_every_position_and_alignment(
    phrases: list[Phrase], position: str
) -> None:
    profile = BASE.model_copy(update={"position": position, "align": "left"})
    scene = run(phrases, profile, (1280, 720))
    assert all(line.box.x == scene.safe.x for line in scene.lines())
    del scene
    check_scene(
        run(phrases, profile.model_copy(update={"align": "center"}), (1280, 720)),
        profile.model_copy(update={"align": "center"}),
    )


@settings(max_examples=150, deadline=None)
@given(
    phrases=song(),
    bpm=st.none() | st.floats(40.0, 240.0),
    count=st.integers(1, 8),
    mode=st.sampled_from(["line", "page"]),
)
def test_the_rules_hold_with_countdowns_in_beats(
    phrases: list[Phrase], bpm: float | None, count: int, mode: str
) -> None:
    profile = BASE.model_copy(
        update={
            "mode": mode,
            "page": Page(min_lines=1),
            "countdown": BASE.countdown.model_copy(update={"form": "dots", "count": count}),
        }
    )
    info = SongText("Titel", "Künstler", 300.0, {}, bpm=bpm)
    scene = layout(phrases, info, profile, (960, 720), FixedMeasurer())
    assert scene.bpm == bpm
    check_scene(scene, profile)


@settings(max_examples=150, deadline=None)
@given(
    phrases=song(),
    slots=st.integers(2, 6),
    lines=st.integers(1, 6),
    frame=st.sampled_from(FRAMES),
    form=st.sampled_from(["notice", "timer"]),
)
def test_the_rules_hold_with_rows_over_slots(
    phrases: list[Phrase], slots: int, lines: int, frame: tuple[int, int], form: str
) -> None:
    profile = scaled(BASE, slots).model_copy(
        update={
            "mode": "page",
            "line_rows": 2,
            "page": Page(min_lines=min(lines, slots), slot_per_row=True),
            "breaks": BASE.breaks.model_copy(update={"form": form}),
        }
    )
    scene = run(phrases, profile, frame)
    check_scene(scene, profile)
    assert not [s for s in scene.shortfalls if s.kind == "block"]
    seen = {x.slot for x in scene.lines()}
    assert max(seen) < slots  # every row has a slot of its own on its page
    for number in {x.page for x in scene.lines()}:
        page = [x for x in scene.lines() if x.page == number]
        assert len({x.slot for x in page}) == len(page)  # no two rows share a slot


@settings(max_examples=200, deadline=None)
@given(
    phrases=song(),
    slots=st.integers(1, 6),
    lines=st.integers(1, 6),
    rows=st.booleans(),
    frame=st.sampled_from(FRAMES),
)
def test_the_rules_hold_when_pages_turn_line_by_line(
    phrases: list[Phrase], slots: int, lines: int, rows: bool, frame: tuple[int, int]
) -> None:
    """Every line of a page that turns line by line appears after its slot was sung and in time."""
    assume(slots >= 2 or not rows)
    profile = scaled(BASE, slots, 2 if rows else 1).model_copy(
        update={
            "mode": "page",
            "page": Page(min_lines=min(lines, slots), slot_per_row=rows, turn="line"),
        }
    )
    scene = run(phrases, profile, frame)
    check_scene(scene, profile)
    for line in scene.lines():
        assert line.start <= line.sing_start + 0.01  # never after its first syllable
        assert line.start <= line.end


@settings(max_examples=100, deadline=None)
@given(
    phrases=song(),
    frame=st.sampled_from(FRAMES),
    mode=st.sampled_from(["line", "page"]),
    title=st.booleans(),
    bpm=st.none() | st.floats(40.0, 240.0),
)
def test_the_rules_hold_with_a_timer(
    phrases: list[Phrase], frame: tuple[int, int], mode: str, title: bool, bpm: float | None
) -> None:
    profile = scaled(BASE, 3).model_copy(
        update={
            "mode": mode,
            "breaks": BASE.breaks.model_copy(update={"form": "timer", "show_title": title}),
        }
    )
    info = SongText("Titel", "Künstler", 300.0, {}, bpm=bpm)
    check_scene(layout(phrases, info, profile, frame, FixedMeasurer()), profile)


@settings(max_examples=100, deadline=None)
@given(phrases=song(), slots=st.integers(3, 6), frame=st.sampled_from(FRAMES))
def test_the_parts_of_a_split_line_read_top_to_bottom_in_line_mode(
    phrases: list[Phrase], slots: int, frame: tuple[int, int]
) -> None:
    profile = scaled(BASE, slots)
    scene = run(phrases, profile, frame)
    check_scene(scene, profile)
    lines = scene.lines()
    starts = [i for i, x in enumerate(lines) if x.part == 0] + [len(lines)]
    for first, after in itertools.pairwise(starts):
        line = lines[first:after]  # the parts of one lyric line, in the order they are sung
        assert [x.part for x in line] == list(range(len(line)))
        if len(line) <= slots:
            assert [x.slot for x in line] == list(range(line[0].slot, line[0].slot + len(line)))
            assert [x.start for x in line] == sorted(x.start for x in line)


@settings(max_examples=60, deadline=None)
@given(
    phrases=song(),
    slots=st.integers(1, 6),
    form=st.sampled_from(["none", "fade", "slide"]),
    offset=st.sampled_from([-0.4, 0.0, 0.3]),
    frame=st.sampled_from(FRAMES),
)
def test_the_rules_hold_for_looks_with_effects(
    phrases: list[Phrase],
    slots: int,
    form: Literal["none", "fade", "slide"],
    offset: float,
    frame: tuple[int, int],
) -> None:
    """Pop, transitions and dimmed lines on any slot count, wipe shift and frame (ADR-0032)."""
    profile = scaled(BASE, slots).model_copy(
        update={
            "cdg": None,
            "pop": Pop(scale=1.15, time=0.4),
            "transition": Transition(form=form, time=0.5),
            "upcoming": Upcoming(dim=0.5),
            "wipe": BASE.wipe.model_copy(update={"offset": offset}),
        }
    )
    check_scene(run(phrases, profile, frame), profile)


SCROLL = parse_profile("lyric-scroll", FakeResources().builtin_profile("lyric-scroll") or "")


SCROLL_SETTINGS = st.fixed_dictionaries(
    {
        "form": st.sampled_from(["notice", "progress", "timer"]),
        "rows": st.integers(1, 2),
        "before": st.integers(0, 2),
        "after": st.integers(1, 4),
        "glide": st.sampled_from([0.2, 0.4, 1.0]),
        "min_glide": st.sampled_from([0.1, 0.3, 1.0]),
        "offset": st.sampled_from([-0.5, 0.0, 0.1, 0.5]),
        "current": st.sampled_from([0.3, 0.42, 0.6]),
    }
)


def scrolling(settings_: dict[str, Any]) -> Profile:
    """The scrolling look with the generated settings of the column."""
    return SCROLL.model_copy(
        update={
            "line_rows": settings_["rows"],
            "breaks": SCROLL.breaks.model_copy(update={"form": settings_["form"]}),
            "wipe": SCROLL.wipe.model_copy(update={"offset": settings_["offset"]}),
            "scroll": SCROLL.scroll.model_copy(
                update={
                    "before": settings_["before"],
                    "after": settings_["after"],
                    "glide": settings_["glide"],
                    "min_glide": min(settings_["min_glide"], settings_["glide"]),
                    "current": settings_["current"],
                }
            ),
        }
    )


def test_a_wrapped_line_glides_out_as_a_whole() -> None:
    """A second row sung only in the glide out of its line is not moving while it is sung.

    The rows of a wrapped line glide together in the last ``min_glide`` of the whole line
    (ADR-0036), so a short second row may be sung entirely during that glide.
    """

    def phrase(texts: list[str], start: float) -> Phrase:
        pieces = tuple(
            Piece(text=t, start=round(start + 0.05 * k, 2), end=round(start + 0.05 * (k + 1), 2))
            for k, t in enumerate(texts)
        )
        return Phrase(singers="1", pieces=pieces, turns=())

    long = ["a", "a", "aaa", "aaaa ", "aaaaa ", "a", "a", "aaaa", "aaaaa"]
    phrases = [phrase(["a ", "a"], 0.0), phrase(long, 0.1), phrase(["a"], 0.55)]
    shape = {
        "form": "notice",
        "rows": 2,
        "before": 0,
        "after": 1,
        "glide": 0.4,
        "min_glide": 0.3,
        "offset": -0.5,
        "current": 0.3,
    }
    profile = scrolling(shape)
    scene = run(phrases, profile, (960, 720))
    second = scene.lines()[2]
    assert second.row == 1  # the second row of the long line
    moves = [(a.time, b.time) for a, b in itertools.pairwise(second.path) if abs(a.y - b.y) > 1e-6]
    assert any(a < second.sing_start < b for a, b in moves)  # sung during the glide out
    check_scene(scene, profile)


@settings(max_examples=150, deadline=None)
@given(phrases=song(), frame=st.sampled_from(FRAMES), shape=SCROLL_SETTINGS)
def test_the_rules_hold_in_scroll_mode(
    phrases: list[Phrase], frame: tuple[int, int], shape: dict[str, Any]
) -> None:
    profile = scrolling(shape)
    check_scene(run(phrases, profile, frame), profile)


@settings(max_examples=80, deadline=None)
@given(
    phrases=song(),
    name=st.sampled_from(BUILTIN_PROFILES),
    frame=st.sampled_from(FRAMES),
    hold=st.sampled_from([None, 0.0, 3.5, 4.5, 10.0]),
    clear_after=st.sampled_from([None, 0.5, 2.5]),
)
def test_the_rules_hold_for_every_built_in_look(
    phrases: list[Phrase],
    name: str,
    frame: tuple[int, int],
    hold: float | None,
    clear_after: float | None,
) -> None:
    """After a break every line look starts at the top, and lines leave in order (rules 9, 22).

    Also as looks of one's own whose hold takes most of a long gap, or all of it, so the hold
    gives way to ``lead_in.min`` (``place.clearing``), or whose long gap is shorter than
    ``lead_in.target``.
    """
    look = parse_profile(name, FakeResources().builtin_profile(name) or "")
    if look.mode == "scroll":  # the column has no clearing (rule 12)
        hold = clear_after = None
    if hold is not None:  # the end screen comes after the hold, as a look of one's own sets it
        ending = look.ending.model_copy(update={"start_after": max(look.ending.start_after, hold)})
        look = look.model_copy(
            update={"clear": look.clear.model_copy(update={"hold": hold}), "ending": ending}
        )
    if clear_after is not None:
        breaks = look.breaks.model_copy(update={"clear_after": clear_after})
        look = look.model_copy(update={"breaks": breaks})
    check_scene(run(phrases, look, frame), look)


@settings(max_examples=80, deadline=None)
@given(
    phrases=song(),
    mode=st.sampled_from(["line", "page", "scroll"]),
    hold=st.sampled_from([0.5, 1.5, 4.0, 8.0]),
    start_after=st.sampled_from([0.0, 1.0, 2.0]),
    end_screen=st.booleans(),
    duration=st.sampled_from([300.0, None]),
)
def test_the_rules_hold_when_the_hold_is_longer_than_the_wait_for_the_end_screen(
    phrases: list[Phrase],
    mode: str,
    hold: float,
    start_after: float,
    end_screen: bool,
    duration: float | None,
) -> None:
    """Line, page and scroll mode; ``duration=None`` leaves no room for the end screen."""
    base = SCROLL if mode == "scroll" else BASE.model_copy(update={"mode": mode})
    profile = base.model_copy(
        update={
            "clear": base.clear.model_copy(update={"hold": hold}),
            "ending": base.ending.model_copy(
                update={"start_after": start_after, "end_screen": end_screen}
            ),
        }
    )
    scene = run(phrases, profile, (960, 720), duration)
    check_scene(scene, profile)
    last = max(x.sing_end for x in scene.lines())
    wait = min(hold, start_after) if end_screen else hold
    assert max(x.end for x in scene.lines()) <= last + wait + 1e-3


@settings(max_examples=100, deadline=None)
@given(
    first=song(),
    second=song(),
    name=st.sampled_from(BUILTIN_PROFILES),
    frame=st.sampled_from(FRAMES),
)
def test_the_rules_hold_when_two_voices_overlap_and_are_shown_one_after_another(
    first: list[Phrase], second: list[Phrase], name: str, frame: tuple[int, int]
) -> None:
    # the lines of two voices are timed on their own and overlap; until both are drawn at once
    # (ADR-0052) they are shown one after the other, and every look's rules hold on that
    look = parse_profile(name, FakeResources().builtin_profile(name) or "")
    merged = sorted([*first, *second], key=lambda phrase: phrase.start)
    check_scene(run(one_after_another(merged), look, frame), look)
