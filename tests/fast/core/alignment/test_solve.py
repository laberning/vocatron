"""Stage 1: the alignment of lyrics on canned emissions, with and without line times."""

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import numpy as np
import pytest

from fakes.acoustic import BLANK, SECONDS_PER_FRAME, TAIL, VOCABULARY, layout, spike_matrix, sung
from vocatron.core.alignment import solve as solve_module
from vocatron.core.alignment.chunks import Emissions
from vocatron.core.alignment.ctc import CtcPath, Spans
from vocatron.core.alignment.estimate import Settled
from vocatron.core.alignment.rails import RailCheck
from vocatron.core.alignment.solve import Switches, line_starts, solve
from vocatron.core.alignment.tokens import Transcript, build_transcript, line_of_target
from vocatron.core.languages.de import GERMAN

LINES = [
    "Alle meine Entchen",
    "schwimmen auf dem See",
    "Köpfchen in das Wasser",
    "Schwänzchen in die Höh",
]
SECONDS = [4.0, 9.0, 14.0, 19.0]  # where the human .lrc says the lines start
STARTS = {i: round(t / SECONDS_PER_FRAME) for i, t in enumerate(SECONDS)}


def test_every_word_is_found_where_it_is_sung() -> None:
    emissions, transcript, spikes = sung(LINES, STARTS)
    solution = solve(emissions, LINES, None, GERMAN)
    assert [w.text for w in solution.transcript.words] == [w.text for w in transcript.words]
    for word, slot, timed in zip(transcript.words, transcript.slots, solution.words, strict=True):
        assert slot is not None
        assert timed.start == pytest.approx(spikes[slot[0]] * SECONDS_PER_FRAME)
        assert timed.letters[-1][1] == pytest.approx((spikes[slot[1]] + 1) * SECONDS_PER_FRAME)
        assert timed.end >= timed.letters[-1][1]  # held to the end of the voice (ADR-0013)
        assert not timed.estimated
        assert len(timed.letters) == len(word.spoken)
    assert solution.rails.rails == "none"
    assert solution.frames == len(emissions.log_probs)


def test_line_starts_are_the_starts_of_the_first_words() -> None:
    emissions, _, _ = sung(LINES, STARTS)
    solution = solve(emissions, LINES, None, GERMAN)
    found = line_starts(solution.transcript, solution.words)
    assert found == pytest.approx(SECONDS, abs=0.1)


def test_a_word_without_sound_is_estimated_between_its_neighbours() -> None:
    lines = ["ja — nein"]
    emissions, _, _ = sung(lines)
    solution = solve(emissions, lines, None, GERMAN)
    assert [w.estimated for w in solution.words] == [False, True, False]
    assert solution.words[0].end <= solution.words[1].start <= solution.words[2].start


def test_line_times_that_fit_up_to_an_offset_are_shifted_and_narrow_the_search() -> None:
    emissions, _, _ = sung(LINES, {i: f + 25 for i, f in STARTS.items()})  # sung 0.5 s later
    solution = solve(emissions, LINES, SECONDS, GERMAN)
    assert solution.rails.rails == "shifted"
    assert solution.rails.offset == pytest.approx(0.5, abs=0.1)
    found = line_starts(solution.transcript, solution.words)
    assert found == pytest.approx([t + 0.5 for t in SECONDS], abs=0.1)


def test_line_times_that_disagree_with_the_singing_are_ignored_and_the_alignment_still_works() -> (
    None
):
    emissions, _, _ = sung(LINES, STARTS)
    wrong = [4.0, 12.0, 11.0, 25.0]
    solution = solve(emissions, LINES, wrong, GERMAN)
    assert solution.rails.rails == "ignored"
    found = line_starts(solution.transcript, solution.words)
    assert found == pytest.approx(SECONDS, abs=0.1)  # the alignment has the last word


def test_without_hints_or_with_too_few_the_rails_are_not_used() -> None:
    emissions, _, _ = sung(LINES, STARTS)
    assert solve(emissions, LINES, None, GERMAN).rails.rails == "none"
    assert solve(emissions, LINES, [4.0, None, None, None], GERMAN).rails.rails == "none"


def test_lyrics_that_do_not_fit_the_audio_are_an_error() -> None:
    emissions, _, _ = sung(["ja"])
    with pytest.raises(ValueError, match="no alignment path"):
        solve(emissions, ["wort " * 400], None, GERMAN)


def test_lyrics_without_any_sound_are_an_error() -> None:
    emissions, _, _ = sung(["ja"])
    with pytest.raises(ValueError, match="no targets"):
        solve(emissions, ["— –"], None, GERMAN)


def test_a_fake_model_vocabulary_is_the_models() -> None:
    assert len(VOCABULARY) == 38


FIVE = [*LINES, "Hänschen klein ging allein"]
FIVE_SECONDS = [*SECONDS, 24.0]


def test_the_windows_of_the_second_pass_move_a_line_to_where_its_time_says() -> None:
    """Line 3 is sung twice: loud too early (a decoy), softer at its time. The hints win."""
    starts = {i: round(t / SECONDS_PER_FRAME) for i, t in enumerate(FIVE_SECONDS)}
    transcript = build_transcript(FIVE, GERMAN, VOCABULARY)
    truth = layout(transcript, starts)
    line = [i for i, owner in enumerate(line_of_target(transcript)) if owner == 2]
    decoy = {truth[i] - 150: transcript.targets[i] for i in line}  # 3 s too early
    by_frame = {frame: transcript.targets[i] for i, frame in truth.items()} | decoy
    log_probs = spike_matrix(max(truth.values()) + TAIL, by_frame)
    soft = np.log(np.full(len(VOCABULARY), 0.01 / (len(VOCABULARY) - 2)))
    for i in line:  # the true singing of line 3 is less clear than the decoy
        row = soft.copy()
        row[transcript.targets[i]], row[BLANK] = np.log(0.5), np.log(0.49)
        log_probs[truth[i]] = row
    emissions = Emissions(log_probs, SECONDS_PER_FRAME, VOCABULARY)
    free = line_starts(transcript, solve(emissions, FIVE, None, GERMAN).words)
    assert free[2] == pytest.approx(FIVE_SECONDS[2] - 3.0, abs=0.1)  # the decoy, without hints
    solution = solve(emissions, FIVE, FIVE_SECONDS, GERMAN)
    assert solution.rails.rails == "shifted"
    found = line_starts(solution.transcript, solution.words)
    assert found == pytest.approx(FIVE_SECONDS, abs=0.1)


def test_hints_whose_windows_leave_no_path_are_dropped_as_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starts = {i: round(t / SECONDS_PER_FRAME) for i, t in enumerate(FIVE_SECONDS)}
    emissions, _, _ = sung(FIVE, starts)
    first_pass = solve_module._pass

    def no_room(
        emissions: Emissions, transcript: Transcript, windows: Sequence[tuple[int, int]] | None
    ) -> tuple[CtcPath, Spans]:
        if windows is not None:  # the second pass
            raise ValueError("no alignment path")
        return first_pass(emissions, transcript, windows)

    monkeypatch.setattr(solve_module, "_pass", no_room)
    solution = solve(emissions, FIVE, [4.0, 9.0, 14.0, 19.0, 24.0], GERMAN)
    assert solution.rails == RailCheck("ignored", 0.0, 5, 0.0, 1.0)
    found = line_starts(solution.transcript, solution.words)
    assert found == pytest.approx(FIVE_SECONDS, abs=0.1)  # the first pass stands


def test_one_out_of_order_hint_is_dropped_and_the_others_still_guide_the_search() -> None:
    starts = {i: round(t / SECONDS_PER_FRAME) for i, t in enumerate(FIVE_SECONDS)}
    emissions, _, _ = sung(FIVE, starts)
    hints = [4.0, 9.0, 143.0, 19.0, 24.0]  # a typo: [00:14] written [02:23]
    solution = solve(emissions, FIVE, hints, GERMAN)
    assert solution.rails.rails == "shifted"
    assert solution.rails.dropped == (2,)
    assert solution.rails.compared == 4
    found = line_starts(solution.transcript, solution.words)
    assert found == pytest.approx(FIVE_SECONDS, abs=0.1)


def test_the_dropped_hints_are_named_when_the_rest_is_ignored_or_too_few() -> None:
    starts = {i: round(t / SECONDS_PER_FRAME) for i, t in enumerate(FIVE_SECONDS)}
    emissions, _, _ = sung(FIVE, starts)
    ignored = solve(emissions, FIVE, [4.0, 30.0, 20.0, 25.0, 31.0], GERMAN).rails
    assert ignored.rails == "ignored"
    assert ignored.dropped == (1,)
    few = solve(emissions, FIVE, [4.0, 30.0, 12.0, None, None], GERMAN).rails
    assert few.rails == "none"
    assert few.dropped == (1,)


# ---------------------------------------------------------------- voice activity (ADR-0012)

PAUSED = ["Alle meine Entchen schwimmen", "— auf dem See"]


def paused_song(*, onset_seconds_before_next: float = 0.2) -> tuple[Emissions, int]:
    """A song whose second line starts with a word without sound; the voice sounds again
    ``onset_seconds_before_next`` before ``auf``. Returns the emissions and the frame of the onset.
    """
    emissions, transcript, spikes = sung(PAUSED)
    assert emissions.loudness is not None
    sounding = [slot for slot in transcript.slots if slot is not None]
    auf = sounding[4][0]  # the fifth word with sound
    onset = spikes[auf] - round(onset_seconds_before_next / SECONDS_PER_FRAME)
    loud = emissions.loudness.copy()
    loud[onset : onset + 8] = -20.0  # 0.16 s of voice inside the gap
    return replace(emissions, loudness=loud), onset


def test_a_word_without_sound_is_placed_where_the_voice_starts_again() -> None:
    emissions, onset = paused_song()
    on = solve(emissions, PAUSED, None, GERMAN)
    off = solve(emissions, PAUSED, None, GERMAN, switches=Switches(voice_activity=False))
    dash = next(i for i, w in enumerate(on.transcript.words) if not w.spoken)
    assert on.words[dash].estimated
    assert on.words[dash].start == pytest.approx(onset * SECONDS_PER_FRAME)
    assert 0.03 <= on.words[dash].end - on.words[dash].start <= 0.12
    assert on.words[dash].end <= on.words[dash + 1].start
    assert off.words[dash].start == pytest.approx(on.words[dash - 1].end)  # fills the pause
    assert (on.voice.detection.reason, on.voice.placed, on.voice.re_estimated) == ("used", 1, 0)
    assert on.voice.kept == 0
    assert on.voice.detection.threshold_db > -70.0


def test_the_lines_reach_the_placement_so_a_line_first_word_takes_the_last_voice_start() -> None:
    """ADR-0021: ``solve`` passes every word's line, so a run that starts a line is placed
    backwards from the next word; across the line, as in ADR-0012, it would take the first start.
    """
    emissions, transcript, spikes = sung(PAUSED, {0: 50, 1: 300})
    assert emissions.loudness is not None
    sounding = [slot for slot in transcript.slots if slot is not None]
    early = spikes[sounding[3][1]] + 40  # a blip of voice well after the first line
    late = spikes[sounding[4][0]] - 12  # the voice start right before the next word
    loud = emissions.loudness.copy()
    loud[early : early + 8] = -20.0
    loud[late : late + 8] = -20.0
    solution = solve(replace(emissions, loudness=loud), PAUSED, None, GERMAN)
    dash = next(i for i, w in enumerate(solution.transcript.words) if not w.spoken)
    assert solution.words[dash].start == pytest.approx(late * SECONDS_PER_FRAME)
    assert (solution.voice.placed, solution.voice.kept) == (1, 0)


def test_the_report_counts_the_words_kept_at_the_model_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = solve_module.settle

    def counted(*args: Any) -> Settled:
        return replace(real(*args), kept=5)

    monkeypatch.setattr(solve_module, "settle", counted)
    emissions, _ = paused_song()
    assert solve(emissions, PAUSED, None, GERMAN).voice.kept == 5


def test_with_the_setting_off_or_without_loudness_the_words_are_those_of_before() -> None:
    emissions, _ = paused_song()
    off = solve(emissions, PAUSED, None, GERMAN, switches=Switches(voice_activity=False))
    bare = solve(replace(emissions, loudness=None), PAUSED, None, GERMAN)
    assert (off.voice.detection.reason, bare.voice.detection.reason) == (
        "switched off",
        "no loudness",
    )
    assert off.words == bare.words
    assert off.words != solve(emissions, PAUSED, None, GERMAN).words
    assert line_starts(off.transcript, off.words) == line_starts(bare.transcript, bare.words)


def test_an_implausible_song_falls_back_to_the_earlier_placement() -> None:
    emissions, _ = paused_song()
    flat = replace(emissions, loudness=np.full(len(emissions.log_probs), -40.0, np.float32))
    solution = solve(flat, PAUSED, None, GERMAN)
    assert solution.voice.detection.reason == "low contrast"
    assert solution.voice.placed == 0
    assert (
        solution.words
        == solve(emissions, PAUSED, None, GERMAN, switches=Switches(voice_activity=False)).words
    )


def test_both_passes_use_the_voice_and_the_report_is_that_of_the_last_pass() -> None:
    emissions, _, _ = sung(LINES, {i: f + 25 for i, f in STARTS.items()})  # sung 0.5 s later
    solution = solve(emissions, LINES, SECONDS, GERMAN)
    assert solution.rails.rails == "shifted"
    assert solution.voice.detection.reason == "used"
    assert solution.voice.detection.activity is not None


def test_the_second_pass_with_line_times_places_the_word_on_the_voice_as_well() -> None:
    lines = [LINES[0], "— " + LINES[1], *LINES[2:]]
    emissions, transcript, spikes = sung(lines, STARTS)
    assert emissions.loudness is not None
    sounding = [slot for slot in transcript.slots if slot is not None]
    onset = spikes[sounding[3][0]] - 10  # the voice sounds 0.2 s before "schwimmen"
    loud = emissions.loudness.copy()
    loud[onset : onset + 8] = -20.0
    emissions = replace(emissions, loudness=loud)
    hinted = solve(emissions, lines, [t + 0.5 for t in SECONDS], GERMAN)
    assert hinted.rails.rails == "shifted"
    dash = next(i for i, w in enumerate(hinted.transcript.words) if not w.spoken)
    assert hinted.words[dash].start == pytest.approx(onset * SECONDS_PER_FRAME)
    assert hinted.voice.placed == 1


def test_a_weakly_heard_word_in_silence_is_re_estimated_and_reported() -> None:
    emissions, transcript, spikes = sung(PAUSED)
    assert emissions.loudness is not None
    sounding = [slot for slot in transcript.slots if slot is not None]
    first, last = sounding[4]  # "auf"
    probs = np.exp(emissions.log_probs.astype(np.float64))
    for target in range(first, last + 1):  # heard with a confidence of about 0.3
        row = probs[spikes[target]]
        token = int(row.argmax())
        row[token], row[BLANK] = 0.3, row[BLANK] + row[token] - 0.3
    loud = emissions.loudness.copy()
    loud[spikes[first] : spikes[last] + 1] = -70.0  # and it lies in silence
    onset = spikes[first] - 15
    loud[onset : onset + 8] = -20.0  # the voice sounds a little earlier
    weak = replace(emissions, log_probs=np.log(probs).astype(np.float32), loudness=loud)
    solution = solve(weak, PAUSED, None, GERMAN)
    assert solution.voice.re_estimated == 1
    auf = next(i for i, w in enumerate(solution.transcript.words) if w.text == "auf")
    assert solution.words[auf].estimated


# ---------------------------------------------------------------- word ends on the voice (ADR-0013)


def held_song() -> Emissions:
    """The canned song with the voice running 0.3 s beyond the last letter of its last word."""
    emissions, _, _ = sung(LINES, STARTS)
    assert emissions.loudness is not None
    ends = (
        solve(emissions, LINES, None, GERMAN, switches=Switches(voice_activity=False)).words[-1].end
    )
    loud = emissions.loudness.copy()
    loud[round(ends / SECONDS_PER_FRAME) : round((ends + 0.3) / SECONDS_PER_FRAME)] = -20.0
    return replace(emissions, loudness=loud)


def test_a_measured_word_is_held_to_the_end_of_the_voice_and_starts_stay() -> None:
    emissions = held_song()
    off = solve(emissions, LINES, None, GERMAN, switches=Switches(voice_activity=False))
    on = solve(emissions, LINES, None, GERMAN)
    assert [w.start for w in on.words] == [w.start for w in off.words]
    assert all(a.end >= b.end for a, b in zip(on.words, off.words, strict=True))
    assert on.voice.held > 0
    assert on.voice.held_median > 0.0
    assert on.words[-1].end >= off.words[-1].end + 0.25
    assert line_starts(on.transcript, on.words) == line_starts(off.transcript, off.words)


def test_with_the_voice_off_or_implausible_nothing_is_held() -> None:
    emissions = held_song()
    off = solve(emissions, LINES, None, GERMAN, switches=Switches(voice_activity=False))
    flat = replace(emissions, loudness=np.full(len(emissions.log_probs), -40.0, np.float32))
    for solution in (off, solve(flat, LINES, None, GERMAN)):
        assert (solution.voice.held, solution.voice.held_median) == (0, 0.0)
        assert solution.words == off.words


BACKING_LINES = ["Alle meine Entchen", "schwimmen auf dem See"]
BACKING_WORD = 1  # "meine": sung only in the backing stem


def test_a_word_sung_only_in_the_backing_is_measured_when_the_backing_is_heard() -> None:
    emissions, _, spikes = sung(BACKING_LINES, backing_only=frozenset({BACKING_WORD}), hear=True)
    assert emissions.backing is not None
    without = solve(emissions, BACKING_LINES, None, GERMAN, switches=Switches(hear_backing=False))
    assert without.words[BACKING_WORD].estimated  # the lead alone cannot hear it
    assert (without.backing.reason, without.backing.frames) == ("switched off", 0)
    heard = solve(emissions, BACKING_LINES, None, GERMAN)
    word = heard.words[BACKING_WORD]
    assert not word.estimated
    assert word.confidence > 0.5
    assert word.letters
    assert (heard.backing.reason, heard.backing.words) == ("used", 1)
    assert heard.backing.frames > 0
    assert heard.voice.detection.activity is not None
    others = [i for i in range(len(heard.words)) if i != BACKING_WORD]
    assert [heard.words[i] for i in others] == [without.words[i] for i in others]


def test_a_song_without_backing_frames_gives_the_same_words_as_without_a_backing() -> None:
    emissions, _, _ = sung(BACKING_LINES, hear=True)
    plain = replace(emissions, backing=None)
    heard = solve(emissions, BACKING_LINES, None, GERMAN)
    assert (heard.backing.reason, heard.backing.frames) == ("no backing frames", 0)
    assert heard.words == solve(plain, BACKING_LINES, None, GERMAN).words
    assert solve(plain, BACKING_LINES, None, GERMAN).backing.reason == "switched off"


def test_the_rails_pass_uses_the_emissions_with_the_backing_too() -> None:
    emissions, _, _ = sung(LINES, STARTS, backing_only=frozenset({BACKING_WORD}), hear=True)
    hints = [t - 0.6 for t in SECONDS]  # the .lrc is early by one steady offset
    solution = solve(emissions, LINES, hints, GERMAN)
    assert solution.rails.rails == "shifted"
    assert not solution.words[BACKING_WORD].estimated
    assert solution.backing.words == 1
    off = solve(emissions, LINES, hints, GERMAN, switches=Switches(hear_backing=False))
    assert off.words[BACKING_WORD].estimated


def test_a_lead_whose_voice_is_not_plausible_gives_the_words_of_the_lead_alone() -> None:
    emissions, _, _ = sung(BACKING_LINES, backing_only=frozenset({BACKING_WORD}), hear=True)
    assert emissions.backing is not None
    flat = np.full(len(emissions.log_probs), -40.0, np.float32)
    implausible = replace(emissions, backing=replace(emissions.backing, lead_loudness=flat))
    heard = solve(implausible, BACKING_LINES, None, GERMAN)
    alone = solve(replace(emissions, backing=None), BACKING_LINES, None, GERMAN)
    assert (heard.backing.reason, heard.backing.frames) == ("lead voice not plausible", 0)
    assert heard.words == alone.words
    assert heard.voice == alone.voice


def silent_line(index: int) -> tuple[Emissions, Transcript]:
    """Emissions of ``LINES`` in which the words of one line are not sung at all."""
    transcript = build_transcript(LINES, GERMAN, VOCABULARY)
    words = frozenset(i for i, word in enumerate(transcript.words) if word.line == index)
    emissions, _, _ = sung(LINES, STARTS, backing_only=words)
    return emissions, transcript


def test_a_line_the_model_does_not_hear_is_placed_at_its_line_time() -> None:
    emissions, transcript = silent_line(2)
    solution = solve(emissions, LINES, SECONDS, GERMAN)
    assert solution.rails.rails == "shifted"
    found = line_starts(transcript, solution.words)
    assert found == pytest.approx(SECONDS, abs=0.1)
    assert [line.line for line in solution.unheard] == [2]
    assert solution.unheard[0].rail == pytest.approx(SECONDS[2] + solution.rails.offset)
    assert solution.voice.unheard == 1
    placed = [t for w, t in zip(transcript.words, solution.words, strict=True) if w.line == 2]
    assert len(placed) == 4
    assert all(t.estimated for t in placed)
    assert placed[0].start == pytest.approx(solution.unheard[0].rail)


def test_without_line_times_nothing_is_unheard() -> None:
    emissions, _ = silent_line(2)
    solution = solve(emissions, LINES, None, GERMAN)
    assert (solution.unheard, solution.voice.unheard) == ((), 0)


def test_a_song_whose_lines_are_all_heard_places_no_unheard_line() -> None:
    emissions, _, _ = sung(LINES, STARTS)
    solution = solve(emissions, LINES, SECONDS, GERMAN)
    assert solution.unheard == ()
