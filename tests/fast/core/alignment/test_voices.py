"""Stage 1: a second voice in the audio and in the alignment, on invented emissions (ADR-0052)."""

from dataclasses import dataclass, replace

import numpy as np
import pytest

from fakes.acoustic import SECONDS_PER_FRAME, VOCABULARY, layout, spike_matrix
from vocatron.core.alignment.chunks import BackingPart, Emissions
from vocatron.core.alignment.mix import backing_sounds
from vocatron.core.alignment.solve import Solution, VoiceReport, line_starts, solve
from vocatron.core.alignment.solve import _add as add_reports
from vocatron.core.alignment.tokens import DELIMITER, build_transcript
from vocatron.core.alignment.voice import SWITCHED_OFF, Detection
from vocatron.core.alignment.voices import (
    BACKING_MARGIN,
    CROWDED,
    FREE_SHARE,
    LEAD_DEAF,
    LEAD_SILENT_SHARE,
    Hearing,
    choose,
    letter_targets,
)
from vocatron.core.languages.de import GERMAN

LOUD, QUIET = -20.0, -70.0
SHORT = "Alle Tage"
LINES = [
    "Alle meine Entchen",
    "schwimmen auf dem See",
    "Köpfchen in das Wasser",
    "Schwänzchen in die Höh",
    "Hänschen klein ging allein",
    "in die weite Welt hinein",
    "Stock und Hut steht ihm gut",
]


# ---------------------------------------------------------------- the choice


def hearing(
    due: float,
    *,
    lead: float = 0.9,
    backing: float = 0.9,
    voiced: float | None = 0.9,
    letters: int = 15,
    slot: float = 5.0,
) -> Hearing:
    """A line heard like a line of one voice (3 letters per second) unless told otherwise."""
    return Hearing(due, lead, backing, voiced, letters, slot)


def second(
    due: float,
    *,
    slot: float = 2.0,
    lead: float = 0.05,
    backing: float = 0.6,
    voiced: float | None = 0.0,
) -> Hearing:
    """A line only the backing hears, while the lead is silent, in a crowded slot."""
    return hearing(due, lead=lead, backing=backing, voiced=voiced, letters=25, slot=slot)


def song(*extra: Hearing) -> list[Hearing | None]:
    """Four lines of one voice, 5 s apart, then the lines in ``extra``."""
    return [*(hearing(5.0 * i) for i in range(4)), *extra]


def starts_of(solution: Solution) -> list[float]:
    """Where each line starts (every line of these songs has a word)."""
    found = line_starts(solution.transcript, solution.words)
    assert None not in found
    return [x for x in found if x is not None]


def test_a_line_only_the_backing_hears_in_a_crowded_slot_goes_to_the_second_voice() -> None:
    heard = song(second(21.0))
    assert choose(heard, [1] * 5) == [1, 1, 1, 1, 2]


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"backing": 0.2}, "the backing does not hear it clearly better"),
        ({"lead": 0.5, "voiced": 0.9}, "the lead hears it and sounds in it"),
        ({"slot": 10.0}, "its slot is not crowded"),
    ],
)
def test_without_one_of_the_signs_the_line_stays_on_the_first_voice(
    change: dict[str, float], why: str
) -> None:
    del why
    assert choose(song(second(21.0, **change)), [1] * 5)[4] == 1


def test_a_lead_that_hears_nothing_counts_as_busy_whether_or_not_it_sounds() -> None:
    sounding = second(21.0, voiced=0.9, lead=LEAD_DEAF)
    assert choose(song(sounding), [1] * 5)[4] == 2
    hears = second(21.0, voiced=0.9, lead=LEAD_DEAF + 0.1)
    assert choose(song(hears), [1] * 5)[4] == 1


def test_a_lead_voice_that_is_not_known_leaves_only_the_lead_hearing_nothing() -> None:
    assert choose(song(second(21.0, voiced=None, lead=0.4)), [1] * 5)[4] == 1
    assert choose(song(second(21.0, voiced=None, lead=0.0)), [1] * 5)[4] == 2


def test_the_second_voice_takes_the_next_line_only_when_it_is_free() -> None:
    heard = song(second(21.0), second(23.0), second(26.0))
    voices = choose(heard, [1] * 7)
    assert voices[4:] == [2, 1, 2]  # 2 s after the last is busy (0.65 of the usual 5 s is 3.25 s)
    assert FREE_SHARE * 5.0 <= 26.0 - 21.0


def test_a_run_of_lines_in_normal_slots_never_becomes_a_second_voice() -> None:
    heard = [hearing(5.0 * i, lead=0.0, backing=0.8, voiced=0.0) for i in range(8)]
    assert choose(heard, [1] * 8) == [1] * 8  # a part the backing sings alone: one voice


def test_the_second_voice_of_the_file_stays_and_counts_as_the_last_of_that_voice() -> None:
    heard = song(second(21.0), second(23.0))
    assert choose(heard, [1, 1, 1, 1, 1, 2]) == [1, 1, 1, 1, 2, 2]
    assert choose(heard, [1, 1, 1, 1, 2, 1]) == [1, 1, 1, 1, 2, 1]  # 21 was kept, 23 is busy


def test_lines_without_a_hearing_stay_where_the_file_put_them() -> None:
    assert choose([None, None], [1, 2]) == [1, 2]
    assert choose([], []) == []


def test_the_constants_are_what_the_docstring_says() -> None:
    assert pytest.approx(0.2) == BACKING_MARGIN
    assert CROWDED > 1.0


# ---------------------------------------------------------------- the alignment on two voices


@dataclass(frozen=True)
class Sung:
    """A line, who sings it, and when its first letter sounds."""

    text: str
    voice: int
    start: float
    heard: bool = True  # a line nobody hears: no letter in either output, and silent on its stem


def voices_song(sung: list[Sung]) -> tuple[Emissions, list[str], list[float]]:
    """Return emissions in which voice 1 sounds in the lead's output and voice 2 in the backing's.

    Every line is laid out on its own (``layout``), so lines of the two voices may overlap in
    time. The lead's loudness sounds over the first voice, the backing's over the second, and the
    loudness of the vocals over both.
    """
    lead: dict[int, int] = {}
    backing: dict[int, int] = {}
    spans: dict[int, list[tuple[int, int]]] = {1: [], 2: []}
    for line in sung:
        if not line.heard:
            continue
        transcript = build_transcript([line.text], GERMAN, VOCABULARY)
        spikes = layout(transcript, {0: round(line.start / SECONDS_PER_FRAME)})
        into = lead if line.voice == 1 else backing
        into.update({frame: transcript.targets[i] for i, frame in spikes.items()})
        spans[line.voice].append((min(spikes.values()), max(spikes.values()) + 1))
    frames = max((*lead, *backing)) + 100

    def loud(*voices: int) -> np.ndarray:
        out = np.full(frames, QUIET, dtype=np.float32)
        for voice in voices:
            for first, stop in spans[voice]:
                out[first:stop] = LOUD
        return out

    emissions = Emissions(
        spike_matrix(frames, lead),
        SECONDS_PER_FRAME,
        VOCABULARY,
        loud(1, 2),
        BackingPart(spike_matrix(frames, backing), loud(1), loud(2)),
    )
    return emissions, [line.text for line in sung], [line.start for line in sung]


def together() -> list[Sung]:
    """Three lines of one voice, a pair sung at the same time, and a line after them."""
    return [
        Sung(LINES[0], 1, 4.0),
        Sung(LINES[1], 1, 9.0),
        Sung(LINES[2], 1, 14.0),
        Sung(LINES[3], 1, 19.0),
        Sung(LINES[4], 2, 19.0),
        Sung(LINES[5], 1, 25.0),
    ]


def test_two_lines_sung_at_once_are_each_found_where_they_sound() -> None:
    emissions, lines, starts = voices_song(together())
    one = solve(emissions, lines, starts, GERMAN)
    two = solve(emissions, lines, starts, GERMAN, voices=[1, 1, 1, 1, 2, 1])
    found = starts_of(two)
    assert found == pytest.approx(starts, abs=0.1)
    assert two.voices == (1, 1, 1, 1, 2, 1)
    assert two.found == ()  # from the file, not from the audio
    first, second_line = (
        [w for w, t in zip(two.transcript.words, two.words, strict=True) if w.line == n]
        for n in (3, 4)
    )
    assert second_line[0].line == 4 and first[0].line == 3
    spans = {
        n: (
            min(
                t.start for w, t in zip(two.transcript.words, two.words, strict=True) if w.line == n
            ),
            max(t.end for w, t in zip(two.transcript.words, two.words, strict=True) if w.line == n),
        )
        for n in (3, 4)
    }
    assert spans[3][0] < spans[4][1] and spans[4][0] < spans[3][1]  # the lines overlap in time
    assert one.voices == (1, 1, 1, 1, 1, 1)  # without the mark one path: the lines follow


def test_the_first_voice_does_not_take_the_words_the_backing_carries_for_the_second() -> None:
    """The lead is silent on a first-voice line while the backing sings the same letters as the
    second voice, a little later: the first voice's line stays at its line time (Review R1.1)."""
    sung = [Sung(LINES[i], 1, 4.0 + 5.0 * i) for i in range(3)]
    sung += [
        Sung(SHORT, 1, 19.0, heard=False),  # the lead's model hears nothing of it
        Sung(SHORT, 2, 20.8),  # the second voice sings the same letters on the backing
        Sung(LINES[5], 1, 26.0),
    ]
    emissions, lines, starts = voices_song(sung)
    hints = [4.0, 9.0, 14.0, 19.0, 21.5, 26.0]
    result = solve(emissions, lines, hints, GERMAN, voices=[1, 1, 1, 1, 2, 1])
    found = starts_of(result)
    assert found[4] == pytest.approx(starts[4], abs=0.1)  # the second voice is where it sings
    assert found[3] == pytest.approx(hints[3], abs=0.3)  # not at the second voice's frames


def test_the_second_voice_does_not_take_the_words_the_lead_carries_for_the_first() -> None:
    """The backing is silent on a second-voice line while the lead sings the same letters as the
    first voice, a little later: the second voice's line stays at its line time (Review R2.5)."""
    sung = [Sung(LINES[i], 1, 4.0 + 5.0 * i) for i in range(3)]
    sung += [
        Sung(SHORT, 2, 19.0, heard=False),  # nobody hears it, the backing does not carry it
        Sung(SHORT, 1, 20.8),  # the first voice sings the same letters on the lead
        Sung(LINES[5], 1, 26.0),
    ]
    emissions, lines, starts = voices_song(sung)
    hints = [4.0, 9.0, 14.0, 19.0, 20.8, 26.0]
    result = solve(emissions, lines, hints, GERMAN, voices=[1, 1, 1, 2, 1, 1])
    found = starts_of(result)
    assert found[4] == pytest.approx(starts[4], abs=0.1)  # the first voice is where it sings
    assert found[3] == pytest.approx(hints[3], abs=0.3)  # not at the first voice's frames
    assert [u.line for u in result.unheard] == [3]


def test_a_first_voice_line_far_from_its_line_time_is_placed_at_it_only_with_a_second_voice() -> (
    None
):
    sung = [Sung(LINES[i], 1, 4.0 + 5.0 * i) for i in range(3)]
    sung += [Sung(LINES[3], 1, 21.0), Sung(LINES[4], 2, 30.0), Sung(LINES[5], 1, 36.0)]
    emissions, lines, _ = voices_song(sung)
    hints = [4.0, 9.0, 14.0, 19.0, 30.0, 36.0]  # line 3 is sung 2 s after its line time
    alone = solve(emissions, lines, hints, GERMAN)
    with_second = solve(emissions, lines, hints, GERMAN, voices=[1, 1, 1, 1, 2, 1])
    assert alone.voices == (1,) * 6
    assert starts_of(alone)[3] == pytest.approx(21.0, abs=0.1)  # one voice: where it sounds
    assert with_second.voices == (1, 1, 1, 1, 2, 1)
    assert starts_of(with_second)[3] == pytest.approx(19.0, abs=0.1)  # two: at its line time
    assert [u.line for u in with_second.unheard] == [3]
    first = [
        t
        for w, t in zip(with_second.transcript.words, with_second.words, strict=True)
        if with_second.voices[w.line] == 1
    ]
    assert all(a.end <= b.start + 1e-9 for a, b in zip(first, first[1:], strict=False))


def test_a_late_first_voice_line_far_from_the_only_second_voice_line_stays_measured() -> None:
    sung = [Sung(LINES[0], 1, 4.0), Sung(LINES[1], 1, 11.0)]  # line 1 is sung 2 s late
    sung += [Sung(LINES[2], 1, 14.0), Sung(LINES[3], 1, 19.0)]
    sung += [Sung(LINES[4], 2, 70.0), Sung(LINES[5], 1, 76.0)]
    emissions, lines, _ = voices_song(sung)
    hints = [4.0, 9.0, 14.0, 19.0, 70.0, 76.0]
    result = solve(emissions, lines, hints, GERMAN, voices=[1, 1, 1, 1, 2, 1])
    assert starts_of(result)[1] == pytest.approx(11.0, abs=0.1)  # not moved to its line time
    assert [u.line for u in result.unheard] == []


def test_unheard_lines_of_both_voices_keep_their_numbers_in_the_song_and_their_order() -> None:
    sung = [
        Sung(LINES[0], 1, 4.0),
        Sung(LINES[1], 2, 9.0, heard=False),
        Sung(LINES[2], 1, 14.0, heard=False),
        Sung(LINES[3], 1, 25.0),
        Sung(LINES[4], 1, 30.0),
    ]
    emissions, lines, starts = voices_song(sung)
    result = solve(emissions, lines, starts, GERMAN, voices=[1, 2, 1, 1, 1])
    assert result.rails.rails == "shifted"
    # the first voice places its line 2 (its own line 1), the second voice line 1 (its own 0)
    assert [(u.line, u.rail) for u in result.unheard] == [(1, 9.0), (2, 14.0)]
    assert result.voice.unheard == 2  # the reports of both voices are added
    assert starts_of(result) == pytest.approx(starts, abs=0.1)


def test_a_second_voice_line_the_backing_does_not_carry_is_found_on_the_lead() -> None:
    """With line times the second voice searches the lead's rows where the backing is silent."""
    sung = [Sung(LINES[i], 1, 4.0 + 5.0 * i) for i in range(5)] + [Sung(LINES[5], 1, 29.0)]
    emissions, lines, starts = voices_song(sung)
    hints = [*starts[:4], 23.2, 29.0]  # line 4 is marked for the second voice, sung 0.8 s late
    result = solve(emissions, lines, hints, GERMAN, voices=[1, 1, 1, 1, 2, 1])
    words = [t for w, t in zip(result.transcript.words, result.words, strict=True) if w.line == 4]
    assert not any(word.estimated for word in words)
    assert words[0].start == pytest.approx(24.0, abs=0.1)


def test_a_short_second_voice_line_ends_on_the_voice_of_the_whole_song() -> None:
    """Its few words cannot find the voice themselves; the first voice's detection holds them."""
    sung = together()
    sung[4] = Sung(SHORT, 2, 19.0)
    emissions, lines, starts = voices_song(sung)
    result = solve(emissions, lines, starts, GERMAN, voices=[1, 1, 1, 1, 2, 1])
    words = [t for w, t in zip(result.transcript.words, result.words, strict=True) if w.line == 4]
    assert words[-1].end > 20.0  # held to the end of the voice, not 19.5 as on its own


def test_an_unheard_line_is_placed_on_the_voice_near_its_line_time() -> None:
    sung = [Sung(LINES[i], 1, 4.0 + 5.0 * i, heard=i != 3) for i in range(6)]
    emissions, lines, starts = voices_song(sung)
    assert emissions.loudness is not None
    loudness = emissions.loudness.copy()
    loudness[round(19.3 / SECONDS_PER_FRAME) : round(20.8 / SECONDS_PER_FRAME)] = LOUD
    result = solve(replace(emissions, loudness=loudness), lines, starts, GERMAN)
    assert [u.line for u in result.unheard] == [3]
    assert starts_of(result)[3] == pytest.approx(19.3, abs=0.05)  # the voice, not the rail 19.0


def test_one_path_cuts_the_line_that_two_voices_sing_at_once() -> None:
    emissions, lines, starts = voices_song(together())
    one = solve(emissions, lines, starts, GERMAN)
    found = starts_of(one)
    assert abs(found[4] - starts[4]) > 0.1 or abs(found[5] - starts[5]) > 0.1  # squeezed or late


def test_a_line_that_only_partly_overlaps_is_found_in_the_audio() -> None:
    sung = together()
    sung[4] = Sung(LINES[4], 2, 19.7)  # starts while the first voice still sings its line
    sung[5] = Sung(LINES[5], 1, 23.0)
    emissions, lines, starts = voices_song(sung)
    result = solve(emissions, lines, starts, GERMAN)
    assert result.voices == (1, 1, 1, 1, 2, 1)
    assert result.found == (4,)
    found = starts_of(result)
    assert found[:4] + found[5:] == pytest.approx(starts[:4] + starts[5:], abs=0.1)
    ends = [
        t.end for w, t in zip(result.transcript.words, result.words, strict=True) if w.line == 4
    ]
    assert starts[4] - 0.7 <= found[4] <= starts[4] + 0.1  # where the lead's rows are mixed in,
    assert ends[-1] == pytest.approx(19.7 + 23 * 0.06 + 0.1, abs=0.3)  # the start may be early


def test_a_song_with_one_voice_keeps_its_words_and_gains_no_second_voice() -> None:
    sung = [Sung(text, 1, 4.0 + 5.0 * i) for i, text in enumerate(LINES)]
    emissions, lines, starts = voices_song(sung)
    result = solve(emissions, lines, starts, GERMAN)
    assert result.voices == (1,) * len(lines)
    assert result.found == ()
    plain = solve(replace(emissions, backing=None), lines, starts, GERMAN)
    assert [(w.start, w.end) for w in result.words] == [(w.start, w.end) for w in plain.words]


def test_a_mark_in_a_file_without_line_times_still_makes_a_second_path() -> None:
    emissions, lines, starts = voices_song(together())
    result = solve(emissions, lines, None, GERMAN, voices=[1, 1, 1, 1, 2, 1])
    assert result.voices == (1, 1, 1, 1, 2, 1)
    found = starts_of(result)
    assert found[:5] == pytest.approx(starts[:5], abs=0.1)  # each voice on its own path


def test_a_second_voice_without_the_backing_is_searched_on_the_lead() -> None:
    sung = [replace(line, voice=1) for line in together()]
    emissions, lines, starts = voices_song(sung)
    result = solve(
        replace(emissions, backing=None), lines, starts, GERMAN, voices=[1, 1, 1, 1, 2, 1]
    )
    assert result.voices == (1, 1, 1, 1, 2, 1)
    assert starts_of(result)[4] >= starts[4] - 0.1


def test_words_stay_in_the_order_of_the_lyrics_when_the_voices_overlap() -> None:
    emissions, lines, starts = voices_song(together())
    result = solve(emissions, lines, starts, GERMAN, voices=[1, 1, 1, 1, 2, 1])
    assert [w.line for w in result.transcript.words] == sorted(
        w.line for w in result.transcript.words
    )
    assert len(result.words) == len(result.transcript.words)


# ---------------------------------------------------------------- edges of the rules


def test_every_sign_counts_at_its_limit() -> None:
    # 4 lines of 3 letters per second: 1.5 times that is 4.5, so 9 letters in 2 s are crowded
    edge = hearing(21.0, lead=0.0, backing=BACKING_MARGIN, voiced=LEAD_SILENT_SHARE, letters=9)
    edge = replace(edge, slot=2.0)
    assert choose(song(edge), [1] * 5)[4] == 2


def test_a_line_with_a_short_slot_still_counts_and_short_slots_make_the_usual() -> None:
    quick = [hearing(0.5 * i, letters=1, slot=0.5) for i in range(4)]  # 2 letters per second
    crowded = hearing(2.0, lead=0.0, backing=0.6, voiced=0.0, letters=4, slot=0.5)
    assert choose([*quick, crowded], [1] * 5)[4] == 2


def test_the_second_voice_is_free_again_exactly_at_its_share_of_the_usual_slot() -> None:
    heard = song(second(21.0), second(21.0 + FREE_SHARE * 5.0))
    assert choose(heard, [1] * 6)[4:] == [2, 2]


def test_a_line_without_a_hearing_does_not_end_the_choice() -> None:
    assert choose([None, *song(second(21.0))], [1] * 6)[5] == 2


def test_the_letters_of_one_line_are_its_words_with_delimiters_between() -> None:
    transcript = build_transcript(["ab cd", "efg hij kl"], GERMAN, VOCABULARY)
    delimiter = VOCABULARY.index(DELIMITER)
    targets = letter_targets(transcript, delimiter, 1)
    assert len(targets) == len("efg hij kl")
    assert targets.count(delimiter) == 2
    assert letter_targets(transcript, delimiter, 0)[:2] == list(transcript.targets[:2])


def test_the_reports_of_two_voices_add_up() -> None:
    detection = Detection(None, SWITCHED_OFF)
    first = VoiceReport(detection, placed=1, re_estimated=2, kept=3, held=2, held_median=0.1)
    second = VoiceReport(detection, placed=4, re_estimated=5, kept=6, held=6, held_median=0.5)
    first, second = replace(first, unheard=1), replace(second, unheard=2)
    total = add_reports(first, second)
    assert (total.placed, total.re_estimated, total.kept, total.held, total.unheard) == (
        5,
        7,
        9,
        8,
        3,
    )
    assert total.held_median == pytest.approx((0.1 * 2 + 0.5 * 6) / 8)
    assert total.detection is detection
    assert add_reports(VoiceReport(detection), VoiceReport(detection)).held_median == 0.0


def test_a_short_island_of_the_backing_is_no_sound() -> None:
    loudness = np.full(200, QUIET, dtype=np.float32)
    loudness[10:13] = LOUD  # 0.06 s
    loudness[100:150] = LOUD  # 1 s
    sounds = backing_sounds(loudness, -40.0, SECONDS_PER_FRAME)
    assert not sounds[10:13].any()
    assert sounds[100:150].all()


def test_a_lead_voiced_in_exactly_its_silent_share_counts_as_silent() -> None:
    edge = second(21.0, lead=LEAD_DEAF + 0.1, backing=0.9, voiced=LEAD_SILENT_SHARE)
    assert choose(song(edge), [1] * 5)[4] == 2
