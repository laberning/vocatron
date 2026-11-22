"""Stage 1: passages, trials, sessions, levels, tally and decision rule of the listening test."""

from collections import Counter
from collections.abc import Sequence
from typing import Literal

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vocatron.core.bench import SongResult, run_of
from vocatron.lab.separation.listening import (
    CLIP_CEILING,
    CRITERIA,
    IDENTICAL_PER_PAIR,
    ORIGINAL,
    Choice,
    Judgement,
    ListeningKey,
    PairTally,
    Passage,
    Results,
    Side,
    Window,
    common_medians,
    decide,
    densest_windows,
    judgements_by_trial,
    make_key,
    match_levels,
    merge_results,
    plan_passages,
    sign_test_p,
    tally,
    wins_needed,
)

RATE = 100  # a low sample rate keeps the arrays small; the rules do not depend on it
SYSTEMS = ("ref", "new-a", "new-b")


def burst(seconds: float, start: float, end: float, level: float = 0.5) -> np.ndarray:
    """A stereo stem of ``seconds`` that is silent except between ``start`` and ``end``."""
    audio = np.zeros((2, int(seconds * RATE)), dtype=np.float32)
    audio[:, int(start * RATE) : int(end * RATE)] = level
    return audio


def test_passages_follow_the_loudest_stretches_without_overlap() -> None:
    lead = burst(120, 10, 20) + burst(120, 90, 100) + burst(120, 60, 65, 0.4)
    windows = plan_passages(lead, RATE, seconds=10, count=3)
    starts = [w.start for w in windows]
    assert starts[0] == 10  # the earliest of the equally loud windows
    assert starts[-1] == 90
    assert 55 <= starts[1] <= 65  # the quieter burst comes third in loudness
    assert all(b - a >= 10 for a, b in zip(starts, starts[1:], strict=False))
    assert all(w.seconds == 10 for w in windows)


def test_a_passage_chosen_by_time_is_always_one_of_them() -> None:
    lead = burst(120, 10, 40)
    windows = plan_passages(lead, RATE, seconds=10, count=2, extra_starts=[75.0])
    assert 75.0 in [w.start for w in windows]
    assert len(windows) == 2
    assert len(plan_passages(lead, RATE, seconds=10, count=1, extra_starts=[75.0, 100.0])) == 2


def test_a_song_shorter_than_the_passages_gives_fewer_of_them() -> None:
    windows = plan_passages(burst(25, 2, 20), RATE, seconds=10, count=5)
    assert 1 <= len(windows) <= 2
    assert plan_passages(burst(5, 1, 4), RATE, seconds=10, count=3) == [Window(start=0, seconds=5)]


def test_a_song_without_audio_is_an_error() -> None:
    with pytest.raises(ValueError, match="no audio"):
        plan_passages(np.zeros((2, 0), dtype=np.float32), RATE)


@given(
    count=st.integers(1, 5),
    length=st.integers(1, 8),
    seed=st.integers(0, 20),
)
@settings(max_examples=30, deadline=None)
def test_windows_never_overlap_and_stay_inside_the_song(count: int, length: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    lead = rng.uniform(-1, 1, (2, 40 * RATE)).astype(np.float32)
    starts = densest_windows(lead, count, length * RATE, RATE)
    assert starts == sorted(starts)
    assert all(b - a >= length * RATE for a, b in zip(starts, starts[1:], strict=False))
    assert all(0 <= s <= 40 * RATE - length * RATE for s in starts)
    assert len(starts) <= count


def passages(songs: int = 3, per_song: int = 5) -> list[Passage]:
    return [
        Passage(id=f"p{i:02d}", song=f"song {i // per_song}", window=Window(start=i, seconds=10))
        for i in range(songs * per_song)
    ]


def key_of(
    systems: Sequence[str] = SYSTEMS[:2], seed: int = 1, per_session: int = 36
) -> ListeningKey:
    return make_key(passages(), systems, seed, per_session)


def test_every_candidate_is_judged_twice_on_every_passage_in_both_orders() -> None:
    key = key_of()
    real = [t for t in key.trials if not t.identical]
    assert len(real) == 30  # 15 passages, two orders
    for passage in key.passages:
        pair = [t for t in real if t.passage == passage.id]
        assert len(pair) == 2
        first, second = sorted(pair, key=lambda t: t.repeat)
        assert (first.a, first.b) == (second.b, second.a)
        assert not first.repeat
        assert second.repeat


def test_the_reference_is_on_one_side_and_the_candidate_on_the_other() -> None:
    key = key_of(SYSTEMS)
    for trial in key.trials:
        sides = {key.system_of(trial.a), key.system_of(trial.b)}
        if trial.identical:
            assert sides == {"ref"}
            assert trial.a != trial.b  # two clips, so the page cannot tell
        else:
            assert sides == {"ref", trial.candidate}
        assert key.system_of(trial.original) == ORIGINAL


def test_each_pair_gets_its_hidden_identical_trials() -> None:
    key = key_of(SYSTEMS)
    counts = Counter(t.candidate for t in key.trials if t.identical)
    assert counts == {"new-a": IDENTICAL_PER_PAIR, "new-b": IDENTICAL_PER_PAIR}
    assert len(key.trials) == 2 * (30 + IDENTICAL_PER_PAIR)


def test_the_swapped_repeats_come_in_later_sessions_than_the_first_judgements() -> None:
    key = key_of(per_session=17)
    firsts = [t.session for t in key.trials if not t.repeat and not t.identical]
    repeats = [t.session for t in key.trials if t.repeat]
    assert key.sessions == 2
    assert sum(1 for s in firsts if s == 1) > sum(1 for s in repeats if s == 1)
    assert min(repeats) >= min(firsts)
    sessions = Counter(t.session for t in key.trials)
    assert max(sessions.values()) <= 17
    assert [t.id for t in key.trials] == [f"t{i:03d}" for i in range(1, len(key.trials) + 1)]


def test_the_same_seed_gives_the_same_test_and_another_seed_another_one() -> None:
    assert key_of(seed=3) == key_of(seed=3)
    assert key_of(seed=3).trials != key_of(seed=4).trials


def test_clip_ids_tell_nothing_about_the_system_and_the_key_round_trips() -> None:
    key = key_of(SYSTEMS)
    assert all(c.id.startswith("c") and c.id[1:].isdigit() for c in key.clips)
    assert ListeningKey.model_validate_json(key.model_dump_json()) == key
    assert len({c.id for c in key.clips}) == len(key.clips)
    assert [c.id for c in key.clips] == sorted(c.id for c in key.clips)


def test_no_clip_id_pattern_gives_a_system_away() -> None:
    key = key_of(SYSTEMS)
    number = {c.id: int(c.id[1:]) for c in key.clips}
    for system in SYSTEMS:
        # the distance from the original's clip to the system's clip of the same passage
        steps = {
            number[clip.id] - number[original.id]
            for clip in key.clips
            if clip.system == system
            for original in key.clips
            if original.system == ORIGINAL and original.passage == clip.passage
        }
        assert len(steps) > 1, system
        residues = {number[c.id] % (len(SYSTEMS) + 1) for c in key.clips if c.system == system}
        assert len(residues) > 1, system


@pytest.mark.parametrize(
    "systems", [("only",), ("a", "a"), ("a", ORIGINAL), ()], ids=["one", "same", "orig", "none"]
)
def test_a_test_needs_distinct_systems_and_not_the_name_of_the_original(
    systems: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="distinct systems"):
        make_key(passages(), systems, 1, 36)


def test_a_test_needs_passages_and_sessions() -> None:
    with pytest.raises(ValueError, match="passages"):
        make_key([], SYSTEMS, 1, 36)
    with pytest.raises(ValueError, match="sessions"):
        make_key(passages(), SYSTEMS, 1, 0)


def level(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


def test_levelling_gives_the_clips_one_loudness() -> None:
    quiet, loud = burst(2, 0, 2, 0.1), burst(2, 0, 2, 0.3)
    a, b = match_levels([quiet, loud])
    assert level(a) == pytest.approx(level(b))
    assert level(a) == pytest.approx(0.2, rel=1e-4)
    assert a.dtype == b.dtype == np.float32


def test_levelling_keeps_the_loudest_clip_under_the_ceiling_with_equal_levels() -> None:
    peaky = burst(2, 0, 2, 0.1)
    peaky[:, 5] = 0.99
    flat = burst(2, 0, 2, 0.95)
    a, b = match_levels([peaky, flat])
    assert max(float(np.max(np.abs(a))), float(np.max(np.abs(b)))) <= CLIP_CEILING + 1e-6
    assert level(a) == pytest.approx(level(b))


def test_levelling_leaves_silence_alone() -> None:
    silent = np.zeros((2, 10), dtype=np.float32)
    assert match_levels([silent, silent]) == [silent, silent]
    out = match_levels([silent, burst(1, 0, 1, 0.1), burst(1, 0, 1, 0.3)])
    assert not out[0].any()
    assert level(out[1]) == pytest.approx(level(out[2]))


def judge(key: ListeningKey, who_wins: str, *, skip_identical: bool = False) -> Results:
    """Judgements in which the buttons of ``who_wins`` ('cand', 'ref', 'tie', 'A') are preferred."""
    items = []
    for trial in key.trials:
        if trial.identical:
            items.append(Judgement(trial=trial.id, preference="tie"))
            continue
        a_system = key.system_of(trial.a)
        if who_wins == "A":
            choice = "A"
        elif who_wins == "tie":
            choice = "tie"
        else:
            winner = trial.candidate if who_wins == "cand" else key.reference
            choice = "A" if a_system == winner else "B"
        items.append(Judgement(trial=trial.id, preference=choice))
    return Results(judgements=tuple(items))


def test_a_candidate_preferred_everywhere_wins_every_judgement() -> None:
    key = key_of()
    result = tally(key, judgements_by_trial(key, judge(key, "cand")), "new-a")
    assert (result.judged, result.wins, result.losses, result.ties) == (30, 30, 0, 0)
    assert (result.consistent_wins, result.consistent_losses, result.flips) == (15, 0, 0)
    assert result.passages == 15
    assert (result.identical, result.identical_tied) == (IDENTICAL_PER_PAIR, IDENTICAL_PER_PAIR)
    assert result.p_value < 1e-6


def test_always_pressing_a_is_position_bias_that_cancels_in_the_swapped_orders() -> None:
    key = key_of()
    result = tally(key, judgements_by_trial(key, judge(key, "A")), "new-a")
    assert result.wins == result.losses == 15
    assert result.flips == 15
    assert result.consistent_wins == result.consistent_losses == 0
    assert result.p_value > 0.5


def test_only_the_trials_of_the_asked_candidate_are_counted() -> None:
    key = key_of(SYSTEMS)
    table = judgements_by_trial(key, judge(key, "cand"))
    assert tally(key, table, "new-b").judged == 30
    assert tally(key, table, "new-a").judged == 30


def test_the_criteria_are_counted_for_the_candidate_the_reference_and_same() -> None:
    key = key_of()
    first = next(t for t in key.trials if not t.identical)
    cand_side: Side = "A" if key.system_of(first.a) == "new-a" else "B"
    other: Side = "B" if cand_side == "A" else "A"
    items = list(judge(key, "tie").judgements)
    criteria: dict[str, Side] = {"lead": cand_side, "artefacts": other, "backing": "same"}
    items[key.trials.index(first)] = Judgement(trial=first.id, preference="tie", criteria=criteria)
    result = tally(key, judgements_by_trial(key, Results(judgements=tuple(items))), "new-a")
    assert result.criteria["lead"] == (1, 0, 0)
    assert result.criteria["artefacts"] == (0, 1, 0)
    assert result.criteria["backing"] == (0, 0, 1)
    assert result.criteria["damage"] == (0, 0, 0)
    assert set(result.criteria) == set(CRITERIA)


def test_judgements_are_checked_against_the_key() -> None:
    key = key_of()
    full = judge(key, "cand")
    with pytest.raises(ValueError, match="not judged"):
        judgements_by_trial(key, Results(judgements=full.judgements[:-3]))
    with pytest.raises(ValueError, match="unknown trial"):
        judgements_by_trial(
            key, Results(judgements=(*full.judgements, Judgement(trial="t999", preference="A")))
        )
    with pytest.raises(ValueError, match="judged twice"):
        judgements_by_trial(key, Results(judgements=(*full.judgements, full.judgements[0])))
    odd = Judgement.model_construct(trial="t001", preference="A", criteria={"mood": "A"})
    with pytest.raises(ValueError, match="unknown criterion"):
        judgements_by_trial(key, Results(judgements=(odd, *full.judgements[1:])))


def test_the_results_of_sessions_are_merged_and_a_later_judgement_wins() -> None:
    first = Results(
        judgements=(
            Judgement(trial="t001", preference="A"),
            Judgement(trial="t002", preference="B"),
        )
    )
    second = Results(
        judgements=(
            Judgement(trial="t002", preference="tie"),
            Judgement(trial="t003", preference="A"),
        )
    )
    merged = merge_results([first, second])
    assert {j.trial: j.preference for j in merged.judgements} == {
        "t001": "A",
        "t002": "tie",
        "t003": "A",
    }


def test_the_sign_test_is_the_upper_tail_of_a_fair_coin() -> None:
    assert sign_test_p(20, 10) == pytest.approx(0.0494, abs=1e-3)
    assert sign_test_p(9, 1) == pytest.approx(11 / 1024)
    assert sign_test_p(0, 0) == 1.0
    assert sign_test_p(5, 5) > 0.5
    assert sign_test_p(10, 0) == pytest.approx(1 / 1024)


@given(wins=st.integers(0, 40), losses=st.integers(0, 40))
def test_the_sign_test_falls_when_wins_rise(wins: int, losses: int) -> None:
    assert 0 < sign_test_p(wins, losses) <= 1
    assert sign_test_p(wins + 1, losses) <= sign_test_p(wins, losses + 1) + 1e-12 or losses == 0


def test_twenty_of_thirty_are_needed_and_the_share_is_rounded_up() -> None:
    assert wins_needed(30) == 20
    assert wins_needed(15) == 10
    assert wins_needed(31) == 21
    assert wins_needed(0) == 1


def verdict(
    counts: dict[str, int] | None = None, numbers: dict[str, float | None] | None = None
) -> dict[str, bool]:
    """Decide on a tally of 21 wins, 6 losses and 3 ties and good numbers, with changes."""
    own = {"wins": 21, "losses": 6, "ties": 3, "consistent_losses": 0} | (counts or {})
    result = PairTally(
        candidate="c",
        judged=own["wins"] + own["losses"] + own["ties"],
        wins=own["wins"],
        losses=own["losses"],
        ties=own["ties"],
        p_value=sign_test_p(own["wins"], own["losses"]),
        consistent_wins=5,
        consistent_losses=own["consistent_losses"],
        flips=2,
        passages=15,
        identical=4,
        identical_tied=3,
        criteria={},
    )
    given: dict[str, float | None] = {
        "sync_median_ms": 140.0,
        "reference_sync_median_ms": 150.0,
        "peak_vram_gib": 4.0,
    } | (numbers or {})
    outcome = decide(
        result,
        sync_median_ms=given["sync_median_ms"],
        reference_sync_median_ms=given["reference_sync_median_ms"],
        peak_vram_gib=given["peak_vram_gib"],
        gpu_gib=8.0,
    )
    return {check.name: check.ok for check in outcome.checks} | {"passes": outcome.passes}


def test_a_candidate_that_meets_every_condition_passes() -> None:
    assert verdict()["passes"]
    assert verdict({"wins": 20, "losses": 10, "ties": 0})["passes"]  # the edge: 20 of 30


@pytest.mark.parametrize(
    ("counts", "numbers", "failed"),
    [
        ({"wins": 19, "losses": 11, "ties": 0}, {}, "preferred in at least 20 of 30 judgements"),
        ({"consistent_losses": 1}, {}, "never clearly worse"),
        ({}, {"sync_median_ms": 150.5}, "sync benchmark not worse"),
        ({}, {"sync_median_ms": None}, "sync benchmark not worse"),
        ({}, {"reference_sync_median_ms": None}, "sync benchmark not worse"),
        ({}, {"peak_vram_gib": 6.1}, "fits the GPU within the 75 % cap"),
        ({}, {"peak_vram_gib": None}, "fits the GPU within the 75 % cap"),
    ],
)
def test_each_condition_alone_can_fail_the_candidate(
    counts: dict[str, int], numbers: dict[str, float | None], failed: str
) -> None:
    outcome = verdict(counts, numbers)
    assert [name for name, ok in outcome.items() if not ok and name != "passes"] == [failed]
    assert not outcome["passes"]


def test_ties_are_not_preferences_and_nothing_judged_never_passes() -> None:
    assert not verdict({"wins": 0, "losses": 0, "ties": 0})["passes"]
    assert not verdict({"wins": 10, "losses": 0, "ties": 20})["passes"]  # 10 of 30


def test_the_edges_of_the_sync_and_memory_rules_pass() -> None:
    assert verdict(numbers={"sync_median_ms": 150.0, "peak_vram_gib": 6.0})["passes"]


def test_the_sync_medians_count_only_the_songs_both_runs_compared() -> None:
    def result(*errors: float) -> SongResult:
        return SongResult(
            status="ok", lines=len(errors), compared=len(errors), errors_ms=list(errors)
        )

    candidate = run_of({"a": result(10, 30), "b": result(500), "c": result()})
    reference = run_of({"a": result(20, 40), "c": result(900), "d": result(900)})
    assert common_medians(candidate, reference) == (20.0, 30.0)
    assert common_medians(candidate, run_of({})) == (None, None)


def test_the_sync_medians_compare_the_offset_corrected_errors_where_both_runs_have_them() -> None:
    def result(errors: list[float], corrected: list[float] | None) -> SongResult:
        return SongResult(
            status="ok", lines=len(errors), compared=len(errors), errors_ms=errors,
            corrected_errors_ms=corrected,
        )  # fmt: skip

    candidate = run_of({"a": result([500, 520], [10, 30]), "b": result([100], None)})
    reference = run_of({"a": result([600, 620], [20, 40]), "b": result([300], [5])})
    # song a: corrected on both sides; song b: the candidate has none, so absolute on both sides
    assert common_medians(candidate, reference) == (30.0, 40.0)


# ------------------------------------------------------------- edges found by mutation testing


def samples(*spans: tuple[int, int, float], size: int = 100) -> np.ndarray:
    """A stereo stem of ``size`` samples with ``level`` between each ``(start, end, level)``."""
    audio = np.zeros((2, size), dtype=np.float32)
    for start, end, value in spans:
        audio[:, start:end] = value
    return audio


def test_the_loudness_of_a_window_is_its_energy_whatever_the_sign_of_the_samples() -> None:
    lead = samples((10, 20, -0.5), (60, 70, 0.3))
    assert densest_windows(lead, 1, 10, 10) == [10]


def test_of_equally_loud_windows_the_first_one_at_the_very_start_wins() -> None:
    lead = samples((0, 10, 0.5), (50, 60, 0.5))
    assert densest_windows(lead, 1, 10, 10) == [0]


def test_windows_are_only_tried_on_the_hop() -> None:
    lead = samples((5, 25, 0.5))
    assert densest_windows(lead, 1, 20, 10) in ([0], [10])


def test_a_song_as_short_as_one_window_gives_only_that_window() -> None:
    assert densest_windows(samples((0, 1, 0.5), size=1), 2, 1, 1) == [0]
    assert densest_windows(samples((0, 3, 0.5), size=3), 5, 1, 1) == [0, 1, 2]
    assert densest_windows(samples((0, 10, 0.5), size=10), 1, 10, 1, fixed=[1]) == [0]


def test_a_chosen_start_at_the_beginning_is_kept_and_one_past_the_end_dropped() -> None:
    lead = samples((60, 70, 0.5))
    assert densest_windows(lead, 1, 10, 10, fixed=[0]) == [0]
    assert densest_windows(lead, 1, 10, 10, fixed=[95]) == [60]


def test_no_window_overlaps_any_chosen_start() -> None:
    lead = samples((5, 15, 0.9), (45, 65, 0.9), (80, 90, 0.2))
    starts = densest_windows(lead, 3, 20, 5, fixed=[0, 50])
    assert starts[:1] == [0]
    assert 50 in starts
    assert all(b - a >= 20 for a, b in zip(starts, starts[1:], strict=False))


def test_windows_may_touch_a_chosen_start_and_each_other() -> None:
    lead = samples((10, 20, 0.9), (20, 30, 0.8))
    assert densest_windows(lead, 2, 10, 10, fixed=[0]) == [0, 10]
    assert densest_windows(lead, 2, 10, 10) == [10, 20]


def test_passages_start_on_whole_seconds_and_the_message_of_no_audio() -> None:
    lead = np.zeros((2, 10 * RATE), dtype=np.float32)
    lead[:, 155:300] = 0.5
    (window,) = plan_passages(lead, RATE, seconds=1.0, count=1)
    assert window.start == float(int(window.start))
    with pytest.raises(ValueError, match=r"^the lead-vocal stem holds no audio$"):
        plan_passages(np.zeros((2, 0), dtype=np.float32), RATE)


def test_an_unknown_clip_names_itself() -> None:
    with pytest.raises(KeyError) as caught:
        key_of().system_of("c999")
    assert caught.value.args == ("c999",)


def test_a_session_may_hold_a_single_trial() -> None:
    key = make_key(passages(1, 2), SYSTEMS[:2], 1, 1)
    assert key.sessions == len(key.trials)
    assert [t.session for t in key.trials] == list(range(1, len(key.trials) + 1))
    message = r"^a test needs distinct systems \(at least two\), passages and sessions$"
    with pytest.raises(ValueError, match=message):
        make_key(passages(), SYSTEMS[:2], 1, 0)


def test_silent_clips_do_not_lower_the_common_level() -> None:
    silent = np.zeros((2, RATE), dtype=np.float32)
    out = match_levels([silent, burst(1, 0, 1, 0.1), burst(1, 0, 1, 0.3)])
    assert level(out[1]) == pytest.approx(0.2, rel=1e-4)


def test_clips_scaled_under_the_ceiling_stay_float32() -> None:
    out = match_levels([burst(1, 0, 1, 0.99), burst(1, 0, 1, 0.99)])
    assert all(clip.dtype == np.float32 for clip in out)


def test_the_missing_message_names_the_first_missing_trial() -> None:
    key = key_of()
    full = judge(key, "cand").judgements
    last = full[-1].trial
    with pytest.raises(
        ValueError, match=rf"^1 of {len(full)} trials are not judged \(first: {last}\)$"
    ):
        judgements_by_trial(key, Results(judgements=full[:-1]))


def test_one_win_of_one_has_half_a_chance() -> None:
    assert sign_test_p(1, 0) == pytest.approx(0.5)
    assert sign_test_p(0, 1) == pytest.approx(1.0)


def test_wins_losses_and_ties_all_count_as_judged_and_criteria_add_up() -> None:
    key = key_of()
    items = []
    real = 0
    for trial in key.trials:
        if trial.identical:
            items.append(Judgement(trial=trial.id, preference="tie"))
            continue
        cand: Literal["A", "B"] = "A" if key.system_of(trial.a) == "new-a" else "B"
        ref: Literal["A", "B"] = "B" if cand == "A" else "A"
        preference: Choice = ("tie", cand, ref)[real % 3]
        real += 1
        criteria: dict[str, Side] = {"backing": "same", "damage": "same", "lead": cand}
        items.append(Judgement(trial=trial.id, preference=preference, criteria=criteria))
    result = tally(key, judgements_by_trial(key, Results(judgements=tuple(items))), "new-a")
    assert result.candidate == "new-a"
    assert (result.wins, result.losses, result.ties) == (10, 10, 10)
    assert result.judged == 30
    assert result.criteria["backing"] == (0, 0, 30)
    assert result.criteria["lead"] == (30, 0, 0)


def test_a_song_without_errors_does_not_stop_the_sync_medians() -> None:
    def result(*errors: float) -> SongResult:
        return SongResult(
            status="ok", lines=len(errors), compared=len(errors), errors_ms=list(errors)
        )

    candidate = run_of({"a": result(), "b": result(10, 30)})
    reference = run_of({"a": result(5), "b": result(20, 40)})
    assert common_medians(candidate, reference) == (20.0, 30.0)


def test_the_checks_tell_their_numbers() -> None:
    result = PairTally(
        candidate="c", judged=30, wins=21, losses=6, ties=3, p_value=0.0123,
        consistent_wins=5, consistent_losses=1, flips=2, passages=15, identical=4,
        identical_tied=3, criteria={},
    )  # fmt: skip
    outcome = decide(
        result, sync_median_ms=140.0, reference_sync_median_ms=150.0, peak_vram_gib=4.0,
        gpu_gib=8.0,
    )  # fmt: skip
    assert [check.detail for check in outcome.checks] == [
        "21 of 30 (needs 20); sign test p 0.012",
        "the reference won both orders on 1 passage(s)",
        "median 140.0 ms against 150.0 ms",
        "peak 4.0 GiB of 6.0 GiB",
    ]


def test_one_win_of_one_judgement_meets_the_share() -> None:
    assert verdict({"wins": 1, "losses": 0, "ties": 0})["preferred in at least 20 of 30 judgements"]


def test_at_one_sample_per_second_every_sample_is_a_start() -> None:
    lead = samples((3, 5, 0.5), size=10)
    (window,) = plan_passages(lead, 1, seconds=2.0, count=1)
    assert window.start == 3.0
