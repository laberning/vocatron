"""Rules 13 to 15 and 19: the countdown, the title, the ending and the intro.."""

from vocatron.core.layout.build import MIN_END_SCREEN
from vocatron.core.layout.intro import intro_minimum
from vocatron.core.layout.mark import builds_up
from vocatron.core.layout.phrases import is_ensemble
from vocatron.core.layout.place import (
    hold_end,
)
from vocatron.core.layout.rules_base import (
    EPS,
    ROUNDING,
    TOLERANCE,
    gaps,
    need,
)
from vocatron.core.profiles.model import Profile
from vocatron.core.scene import (
    CardElement,
    CountdownElement,
    LineElement,
    Scene,
    TitleMark,
)
from vocatron.core.tempo import countdown_beat, countdown_end


def scene_beat(scene: Scene, profile: Profile) -> float | None:
    """Return the beat the scene's countdowns count, or ``None`` when they count seconds."""
    return None if scene.bpm is None else countdown_beat(scene.bpm, profile.countdown.count)


def counts_in(countdown: CountdownElement, line: LineElement, beat: float | None) -> bool:
    """Return whether ``countdown`` counts in ``line``: it ends where ``countdown_end`` says.

    The end is taken with the scene's beat (``beat``) or with the countdown's own, so a countdown
    with a wrong beat still belongs to its line and its beat is reported by rule 13.
    """
    ends = {countdown_end(line.sing_start, beat), countdown_end(line.sing_start, countdown.beat)}
    return any(abs(countdown.end - end) <= TOLERANCE for end in ends)


def _countdown_floor(scene: Scene, sing_start: float, ended: float) -> float:
    """Return the earliest a countdown before a line sung at ``sing_start`` may start.

    That is the end of the line before (``ended``, 0 for the first line), or the end of the title
    or break screen before the line when that is later. In scroll mode the break screen ends where
    the column starts to glide in again (ADR-0040).
    """
    screens = [*scene.cards("title"), *scene.cards("break")]
    ends = [e.end for e in screens if e.end <= sing_start + TOLERANCE]
    return max([ended, *ends])


def _rest_start(line: LineElement) -> float:
    """Return when the column came to rest for the line to be sung (scroll mode).

    That is the end of the last move of its path before it is sung.
    """
    moves = [b.time for a, b in zip(line.path, line.path[1:], strict=False) if a.y != b.y]
    before = [time for time in moves if time <= line.sing_start + TOLERANCE]
    return before[-1] if before else line.path[0].time


def _floors(scene: Scene, profile: Profile, line: LineElement, ended: float) -> tuple[float, float]:
    """Return the earliest a countdown before ``line`` may start, and where it must start early.

    The first is the hard floor: the end of the line before, of a title or break screen, and in
    scroll mode of the glide into the line. The second is where a countdown with fewer beats than
    wanted is judged: in scroll mode the hard floor moves with the glide, so it is the end of the
    line, title or break screen before it plus the longest glide and wipe shift.
    """
    floor = _countdown_floor(scene, line.sing_start, ended)
    if scene.scroll is None:
        return floor, floor
    slack = scene.scroll.glide + max(profile.wipe.offset, 0.0)
    return max(floor, _rest_start(line)), floor + slack


def _rule_13_beats(  # the countdown, the beat, the two floors, the profile and the line
    countdown: CountdownElement, beat: float, floors: tuple[float, float], profile: Profile,
    index: int,
) -> None:  # fmt: skip
    """Check a countdown in beats: whole beats of the song's beat, starting as early as it may.

    Its beat is the tempo's beat folded by ``countdown_beat``, so that ``count`` beats last
    between ``MIN_COUNTDOWN`` and ``MAX_COUNTDOWN`` seconds. It lasts a whole number of beats, at
    most ``count``, and one with fewer beats starts on the first whole beat after ``floor``, so
    less than a beat is left over. ``floors`` are the hard floor and the one a countdown with
    fewer beats than wanted is judged against (``_floors``).
    """
    floor, soft = floors
    need(
        countdown.beat is not None and abs(countdown.beat - beat) <= ROUNDING + EPS,
        f"rule 13: the countdown of line {index} does not count beats of {beat:.3f} s",
    )
    count, wanted = countdown.count, profile.countdown.count
    need(1 <= count <= wanted, f"rule 13: the countdown of line {index} counts {count} beats")
    duration = countdown.end - countdown.start
    need(
        abs(duration - count * beat) <= TOLERANCE,
        f"rule 13: the countdown of line {index} lasts {duration} s, not {count} beats",
    )
    need(countdown.start >= floor - TOLERANCE, f"rule 13: the countdown of line {index} is early")
    need(
        count == wanted or countdown.start - soft < beat + TOLERANCE,
        f"rule 13: the countdown of line {index} has fewer beats than fit",
    )


def rule_13_countdown(scene: Scene, profile: Profile) -> None:
    """A countdown runs before the first line and after a long gap, and ends at ``countdown_end``.

    Without a tempo (``Scene.bpm``) it lasts at most ``countdown.duration`` seconds and ends at
    the line start. With one it counts beats (ADR-0022): a whole number of beats of the song's
    beat, up to ``countdown.count``, ending one beat before the line (ADR-0028). A line has no
    countdown only when it appears as it is sung or, with a tempo, when the line, title or break
    screen before it leaves less than one beat before that end. A countdown never starts before
    the line before it has been sung. In scroll mode it also starts after the column has glided to
    its line, and stands just above the line (ADR-0033).
    """
    beat = scene_beat(scene, profile)
    lines = scene.lines()
    countdowns = [e for e in scene.elements if isinstance(e, CountdownElement)]
    for index, gap in enumerate(gaps(lines)):
        if gap.before < profile.countdown.min_gap:
            continue
        sing_start = lines[index].sing_start
        found = [c for c in countdowns if counts_in(c, lines[index], beat)]
        floor, soft = floors = _floors(scene, profile, lines[index], gap.ended)
        if not found:  # the line appears as it is sung (and is reported), so there is no time
            room = countdown_end(sing_start, beat) - soft
            appears = lines[index].start >= sing_start - TOLERANCE and scene.scroll is None
            gone = scene.scroll is not None and beat is None and sing_start - soft <= TOLERANCE
            need(
                appears or gone or (beat is not None and room < beat + TOLERANCE),
                f"rule 13: {index}",
            )
            continue
        need(len(found) == 1, f"rule 13: two countdowns before line {index}")
        if beat is not None:
            _rule_13_beats(found[0], beat, floors, profile, index)
        else:
            need(found[0].beat is None, f"rule 13: the countdown of line {index} counts beats")
            need(
                found[0].start >= floor - TOLERANCE,
                f"rule 13: the countdown of line {index} is early",
            )
            duration = found[0].end - found[0].start
            need(
                0 < duration <= profile.countdown.duration + TOLERANCE,
                f"rule 13: the countdown of line {index} lasts {duration} s",
            )
        box, safe = found[0].box, scene.safe
        need(box.inside(safe), "rule 13: the countdown leaves the safe area")
        over_first_letter = min(max(lines[index].text_x, safe.x), safe.right - box.w)
        need(abs(box.x - over_first_letter) <= TOLERANCE, f"rule 13: countdown of line {index}")
        below = lines[index].box.y if scene.scroll is not None else scene.slots[0].y
        need(box.bottom <= below + TOLERANCE, "rule 13: the countdown is not above")
    need(
        len(countdowns) <= sum(g.before >= profile.countdown.min_gap for g in gaps(lines)),
        "rule 13: a countdown without a gap",
    )


def _mark_shapes(  # the card, its mark, the look, the rule and the screen for the messages
    card: CardElement, mark: TitleMark, profile: Profile, rule: str, screen: str
) -> None:
    """Check what the start and end screens with the wordmark share (ADR-0055, ADR-0057).

    The mark stands only with ``title.form: wordmark``; the lines and the rule lie inside the
    frame, and the wordmark does not touch the frame. ``rule`` and ``screen`` name the rule and
    the screen in the messages.
    """
    need(profile.title.form == "wordmark", f"{rule}: a mark on a plain {screen}")
    need(
        all(line.box.inside(mark.frame) for line in card.lines),
        f"{rule}: a line leaves the frame of the {screen}",
    )
    need(mark.rule is None or mark.rule.inside(mark.frame), f"{rule}: the rule leaves the frame")
    need(not mark.word.overlaps(mark.frame), f"{rule}: the wordmark and the frame overlap")


def _rule_14_mark(title: CardElement, profile: Profile) -> None:
    """Check the wordmark of a title screen: its shapes, its lines and its build-up (ADR-0055).

    There is a mark only with ``title.form: wordmark``. On the CD+G screen its letters are pixel
    letters, it has no build-up and the screen lasts at least ``BUILD_MIN`` seconds (a shorter one
    is the plain card, ADR-0056).
    The wordmark and the frame lie inside the safe area (rule 1 checks their boxes), the lines
    inside the frame, the rule inside it too, and the build-up lies inside the title window; it is
    played only on a screen of at least ``BUILD_MIN`` seconds (``builds_up``), its steps one after
    the other, and it ends before the screen.
    """
    mark = title.mark
    if mark is None:
        return
    _mark_shapes(title, mark, profile, "rule 14", "title screen")
    length = title.end - title.start
    build = mark.build
    if mark.pixel:
        need(build is None and builds_up(length), "rule 14: a pixel mark on a short screen")
        return
    need((build is not None) == builds_up(length), "rule 14: the build-up is wrong")
    if build is None:
        return
    spans = [build.edge, *(fill.when for fill in build.fills), build.wipe]
    need(
        all(title.start - TOLERANCE <= x.start <= x.end <= title.end + TOLERANCE for x in spans),
        "rule 14: the build-up leaves the title window",
    )
    need(
        all(a.end <= b.start + TOLERANCE for a, b in zip(spans, spans[1:], strict=False)),
        "rule 14: the steps of the build-up overlap",
    )


def rule_14_title(scene: Scene, profile: Profile) -> None:
    """The title screen starts at 0, is long enough and is gone before the first line."""
    titles = scene.cards("title")
    lines = scene.lines()
    if not lines or not profile.title.fields:
        return
    first = lines[0]
    if not titles:
        need(
            first.sing_start < profile.lead_in.min + profile.title.min_short + TOLERANCE,
            "rule 14: the title screen is missing",
        )
        return
    (title,) = titles
    need(title.start == 0.0, "rule 14: the title does not start at 0")
    need(title.end <= first.start + TOLERANCE, "rule 14: the title is still there")
    _rule_14_mark(title, profile)
    length = title.end - title.start
    short = any(s.kind == "title" for s in scene.shortfalls)
    if first.sing_start >= profile.title.min + profile.lead_in.target:
        need(length >= profile.title.min - TOLERANCE, "rule 14: the title is too short")
    else:
        need(length >= profile.title.min_short - TOLERANCE or short, "rule 14: shortened too far")


def _rule_15_mark(end: CardElement, profile: Profile) -> None:
    """Check the wordmark of an end screen: the wordmark form only, finished from its first frame.

    The mark is the start screen's without the build-up and made of polygon letters; on CD+G the
    end screen is the plain card (ADR-0057). Rule 1 checks the boxes, and the lines are inside
    the frame as on the start screen.
    """
    mark = end.mark
    if mark is None:
        return
    _mark_shapes(end, mark, profile, "rule 15", "end screen")
    need(mark.build is None and not mark.pixel, "rule 15: the end screen's mark builds up")


def rule_15_ending(scene: Scene, profile: Profile) -> None:
    """Nothing stays after the last line's hold; the end screen starts after ``start_after``.

    The hold gives way to the end screen: no lyric line, countdown or notice is on screen once
    the end screen has started (ADR-0037).
    """
    lines = scene.lines()
    if not lines:
        return
    last = max(x.sing_end for x in lines)
    need(max(x.end for x in lines) <= hold_end(last, profile) + TOLERANCE, "rule 15")
    ends = scene.cards("end")
    for end in ends:
        need(
            abs(end.start - (last + profile.ending.start_after)) <= TOLERANCE,
            "rule 15: the end screen starts at the wrong time",
        )
        need(abs(end.end - scene.duration) <= TOLERANCE, "rule 15: the end screen ends early")
        over = [e for e in scene.elements if e is not end and e.end > end.start + TOLERANCE]
        need(not over, "rule 15: lyrics are still on screen when the end screen starts")
        need(abs(end.fade_out - profile.ending.fade) <= TOLERANCE, "rule 15: the fade is wrong")
        _rule_15_mark(end, profile)
    if (
        profile.ending.end_screen
        and scene.duration - last - profile.ending.start_after >= MIN_END_SCREEN
    ):
        need(len(ends) == 1, "rule 15: the end screen is missing")


def rule_19_intro(scene: Scene, profile: Profile) -> None:
    """The first word is sung at or after the intro minimum, and the lead is what was missing."""
    lines = scene.lines()
    need(scene.lead >= 0, "rule 19: the lead is negative")
    if not lines:
        need(scene.lead == 0, "rule 19: a lead without sung lines")
        return
    marks = [x.singers for x in lines] + [t.singers for x in lines for t in x.turns]
    minimum = intro_minimum(is_ensemble(marks), profile)
    first = min(x.sing_start for x in lines)
    need(
        first >= minimum - TOLERANCE, f"rule 19: the first word is sung at {first}, below {minimum}"
    )
    missing = max(0.0, minimum - (first - scene.lead))
    need(
        abs(scene.lead - missing) <= TOLERANCE,
        f"rule 19: the lead is {scene.lead} s, but {missing:.3f} s were missing",
    )
